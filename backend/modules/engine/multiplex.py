"""Rolling multiplex network construction.

Why this exists, and what it must not repeat
-------------------------------------------

The deleted ``DataFormatter.build_graph`` produced a single adjacency matrix by
thresholding pairwise Pearson correlation at 0.5, and that matrix was then treated
as if it described who owed whom. It did not: correlation is co-movement. Two
institutions whose funding costs move together are not thereby indebted to each
other, and no clearing algorithm can be run on a co-movement matrix because it
contains no obligation.

This module keeps the economic relations **separate and labelled**. A
:class:`MultiplexLayer` carries a :class:`RelationKind`:

* ``EXPOSURE`` -- an actual obligation (interbank lending, clearing-member
  variation margin). These are the only relations admissible to the
  Eisenberg-Noe clearing engine.
* ``CO_MOVEMENT`` -- statistical co-movement of funding spreads. Informative about
  shared funding stress; carries no obligation.
* ``SIMILARITY`` -- resemblance of balance-sheet characteristics. Informative
  about substitutability; carries no obligation.

The distinction is enforced rather than documented:
:func:`require_exposure` raises if asked to hand a co-movement or similarity layer
to the clearing engine. The earlier bug was possible only because the two ideas
shared one untyped matrix.

Point-in-time discipline
------------------------

Every builder takes an explicit ``as_of`` and uses only observations dated at or
before it. A network built for time ``t`` that has read a single row dated after
``t`` is a look-ahead network, and it will make the contagion estimate look better
than it can be in production. :func:`_assert_within_as_of` enforces this at the
boundary rather than trusting callers.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from backend.modules.risk.clearing import NetworkLayer

logger = logging.getLogger(__name__)

__all__ = [
    "RelationKind",
    "MultiplexLayer",
    "MultiplexSnapshot",
    "RollingMultiplex",
    "require_exposure",
    "build_similarity_layer",
    "build_co_movement_layer",
    "build_ccp_exposure_layer",
    "build_interbank_exposure_layer",
    "build_fx_basis_layer",
    "build_fx_swap_exposure_layer",
    "cross_currency_funding_exposure",
]


class RelationKind(str, Enum):
    """The economic meaning of an edge.

    ``EXPOSURE`` is the only kind that denotes an obligation, and therefore the
    only kind on which limited liability and absolute priority are defined.
    """

    EXPOSURE = "exposure"
    CO_MOVEMENT = "co_movement"
    SIMILARITY = "similarity"


@dataclass(frozen=True)
class MultiplexLayer:
    """One relation among institutions, aligned to a shared node universe.

    ``adjacency[i, j]`` is the strength of the relation from node ``i`` to node
    ``j`` under ``kind``. For ``EXPOSURE`` that means ``i`` owes ``j`` the entry's
    value. For the symmetric kinds the matrix is undirected and stored
    symmetrically with a zero diagonal.

    ``node_ids`` is the full universe the matrix is aligned to, so that layers
    built over different subsets can be stacked without reindexing ambiguity.
    """

    name: str
    kind: RelationKind
    adjacency: np.ndarray
    node_ids: Tuple[str, ...]
    as_of: pd.Timestamp
    directed: bool
    metadata: Dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        matrix = np.asarray(self.adjacency, dtype=float)
        if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
            raise ValueError(
                f"layer {self.name!r} adjacency must be square, got {matrix.shape}"
            )
        if matrix.shape[0] != len(self.node_ids):
            raise ValueError(
                f"layer {self.name!r} has {matrix.shape[0]} rows but "
                f"{len(self.node_ids)} node ids"
            )
        if not np.all(np.isfinite(matrix)):
            raise ValueError(f"layer {self.name!r} contains non-finite weights")
        if np.any(matrix < 0):
            raise ValueError(
                f"layer {self.name!r} contains negative weights; a relation "
                "strength is a magnitude, and direction is carried by the matrix"
            )
        if not np.allclose(np.diag(matrix), 0.0):
            raise ValueError(
                f"layer {self.name!r} has a non-zero diagonal; an institution "
                "cannot hold a relation to itself"
            )
        if not self.directed and not np.allclose(matrix, matrix.T, atol=1e-9):
            raise ValueError(
                f"layer {self.name!r} is declared undirected but its adjacency "
                "is not symmetric"
            )
        object.__setattr__(self, "adjacency", matrix)
        object.__setattr__(self, "node_ids", tuple(self.node_ids))

    @property
    def is_clearing_eligible(self) -> bool:
        return self.kind is RelationKind.EXPOSURE

    @property
    def n_nodes(self) -> int:
        return int(self.adjacency.shape[0])

    def density(self) -> float:
        """Fraction of ordered node pairs carrying a non-zero relation."""
        n = self.n_nodes
        if n < 2:
            return 0.0
        possible = n * (n - 1) if self.directed else n * (n - 1) / 2
        actual = int(np.count_nonzero(self.adjacency))
        if not self.directed:
            actual //= 2
        return float(actual / possible) if possible else 0.0

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "kind": self.kind.value,
            "as_of": self.as_of.isoformat(),
            "directed": self.directed,
            "n_nodes": self.n_nodes,
            "density": self.density(),
            "is_clearing_eligible": self.is_clearing_eligible,
            "metadata": dict(self.metadata),
        }


def require_exposure(layer: MultiplexLayer) -> NetworkLayer:
    """Convert an ``EXPOSURE`` layer into a clearing-engine layer.

    This is the guard that the previous static-graph code lacked. Correlation
    thresholds were written into an untyped adjacency matrix which was then
    consumed as though it held obligations. Here the conversion is impossible
    unless the layer declares itself an exposure relation, so a co-movement layer
    cannot reach the clearing engine by accident.

    Raises:
        TypeError: if the layer is not an exposure relation.
    """
    if layer.kind is not RelationKind.EXPOSURE:
        raise TypeError(
            f"layer {layer.name!r} declares kind {layer.kind.value!r}, which is not "
            "an obligation. Only EXPOSURE layers may be cleared: a co-movement or "
            "similarity matrix contains no 'who owes whom', so limited liability "
            "and absolute priority are undefined on it."
        )
    return NetworkLayer(
        name=layer.name,
        liabilities=layer.adjacency,
        seniority=int(layer.metadata.get("seniority", 0)),
    )


def _filter_to_as_of(
    stamps: Iterable, as_of: pd.Timestamp, what: str
) -> Tuple[np.ndarray, int]:
    """Mask keeping observations dated at or before ``as_of``, plus rows withheld.

    A point-in-time panel routinely extends past the query date: asking for the
    network as of March must select the rows dated on or before March, not fail
    because June exists in the same table. Filtering is therefore the correct
    behaviour rather than an error, and the number of rows withheld is returned so
    it can be recorded instead of passing unnoticed.

    The one case that really is an error is an input that is non-empty yet lies
    *entirely* after ``as_of``. That is not a panel extending past the query, it is
    almost always the wrong frame, and returning an empty network would hide it.
    """
    values = list(stamps)
    if not values:
        return np.zeros(0, dtype=bool), 0

    parsed = pd.to_datetime(pd.Series(values))
    mask = (parsed <= pd.Timestamp(as_of)).to_numpy()
    excluded = int((~mask).sum())
    if excluded == mask.size:
        raise ValueError(
            f"{what} contains no observations dated at or before as_of {as_of} "
            f"(earliest is {parsed.min()}); a network built for {as_of} must not "
            "read the future."
        )
    return mask, excluded


def _cosine_similarity(matrix: np.ndarray) -> np.ndarray:
    """Pairwise cosine similarity of the rows of ``matrix``.

    Rows with zero norm have no direction and are left unrelated rather than
    being assigned a spurious similarity to everything.
    """
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    safe = np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms > 0)
    similarity = safe @ safe.T
    np.fill_diagonal(similarity, 0.0)
    return np.clip(similarity, 0.0, 1.0)


def _knn_sparsify(matrix: np.ndarray, k: int) -> np.ndarray:
    """Keep each node's ``k`` strongest outgoing relations, symmetrised.

    A dense similarity matrix is not a network. Sparsifying to nearest neighbours
    makes the edge set explicit and keeps the density comparable across snapshots,
    so a rise in density means the relations strengthened rather than that the
    threshold happened to fall.
    """
    n = matrix.shape[0]
    if k <= 0 or k >= n:
        return matrix
    out = np.zeros_like(matrix)
    for i in range(n):
        row = matrix[i]
        # Take the k largest entries; ties broken by index for determinism.
        order = np.argsort(-row, kind="stable")[:k]
        out[i, order] = row[order]
    return np.maximum(out, out.T)


def build_similarity_layer(
    features: pd.DataFrame,
    node_ids: Sequence[str],
    *,
    as_of: pd.Timestamp,
    known_at: Optional[pd.Timestamp] = None,
    k_neighbors: int = 5,
    min_similarity: float = 0.0,
    name: str = "balance_sheet_similarity",
) -> MultiplexLayer:
    """Balance-sheet resemblance between institutions.

    Resemblance is not an obligation: two banks with similar books are
    substitutable and may share fire-sale exposure, but neither owes the other.
    The layer is therefore labelled ``SIMILARITY`` and is refused by
    :func:`require_exposure`.

    Args:
        features: Indexed by **institution**, one column per standardised
            characteristic. This is a cross-section, so it carries no per-row
            timestamp. Missing values are imputed at the column median, a
            cross-sectional choice made within the section.
        node_ids: The shared universe the layer is aligned to. Institutions
            absent from ``features`` are left isolated.
        as_of: The information cut-off the section is used for.
        known_at: When the cross-section became known. A balance-sheet snapshot
            is only meaningful if it was published by ``as_of``; passing a
            publication date later than ``as_of`` is look-ahead and raises. The
            caller is responsible for querying a point-in-time store
            (:mod:`backend.modules.data.pit`) to obtain the section; this argument
            is how that provenance is declared and checked.
        k_neighbors: Nearest neighbours retained per node.
        min_similarity: Similarity below this is dropped.
    """
    if known_at is not None:
        declared = pd.Timestamp(known_at)
        if declared > pd.Timestamp(as_of):
            raise ValueError(
                f"balance-sheet cross-section is declared known at {declared}, "
                f"after as_of {as_of}; a network built for {as_of} must not read "
                "the future."
            )

    universe = list(node_ids)
    position = {node: index for index, node in enumerate(universe)}
    aligned = np.zeros((len(universe), features.shape[1]), dtype=float)

    present = [node for node in features.index if node in position]
    if present:
        block = features.loc[present].apply(pd.to_numeric, errors="coerce").to_numpy(dtype=float)
        medians = np.nanmedian(block, axis=0)
        medians = np.where(np.isfinite(medians), medians, 0.0)
        block = np.where(np.isfinite(block), block, medians)
        for row_index, node in enumerate(present):
            aligned[position[node]] = block[row_index]

    similarity = _cosine_similarity(aligned)
    if min_similarity > 0:
        similarity = np.where(similarity >= min_similarity, similarity, 0.0)
    similarity = _knn_sparsify(similarity, int(k_neighbors))

    return MultiplexLayer(
        name=name,
        kind=RelationKind.SIMILARITY,
        adjacency=similarity,
        node_ids=universe,
        as_of=pd.Timestamp(as_of),
        directed=False,
        metadata={
            "k_neighbors": int(k_neighbors),
            "min_similarity": float(min_similarity),
            "n_features": int(features.shape[1]),
            "n_present": len(present),
            "known_at": pd.Timestamp(known_at).isoformat() if known_at is not None else None,
        },
    )


def build_co_movement_layer(
    levels: pd.DataFrame,
    node_ids: Sequence[str],
    *,
    as_of: pd.Timestamp,
    window: int = 60,
    min_abs_correlation: float = 0.3,
    name: str = "funding_co_movement",
) -> MultiplexLayer:
    """Co-movement of funding spreads over a trailing window.

    Constructed on **changes**, not levels. Two funding spreads that both trend
    upward share a level trend and would show high correlation on levels while
    their day-to-day funding dynamics are unrelated; the shared trend is not a
    relation between the institutions.

    The result is labelled ``CO_MOVEMENT`` because that is all it is. It says the
    two institutions' funding costs move together. It does not say either owes the
    other, and :func:`require_exposure` will refuse it.

    Args:
        levels: DatetimeIndex, one column per institution.
        node_ids: The shared universe.
        as_of: Latest date permitted in ``levels``.
        window: Trailing number of observations used.
        min_abs_correlation: |correlation| below this is dropped. The absolute
            value is used because strong negative co-movement is also a shared
            funding relation.
    """
    mask, excluded = _filter_to_as_of(levels.index, as_of, "funding spread levels")
    within = levels.loc[np.asarray(mask)]
    universe = list(node_ids)
    position = {node: index for index, node in enumerate(universe)}

    matrix = np.zeros((len(universe), len(universe)), dtype=float)
    columns = [col for col in within.columns if col in position]
    if len(columns) < 2:
        return MultiplexLayer(
            name=name,
            kind=RelationKind.CO_MOVEMENT,
            adjacency=matrix,
            node_ids=universe,
            as_of=pd.Timestamp(as_of),
            directed=False,
            metadata={
                "window": int(window),
                "n_series": len(columns),
                "rows_withheld_as_future": excluded,
                "reason": "fewer than two series",
            },
        )

    changes = within[columns].apply(pd.to_numeric, errors="coerce").diff().tail(int(window))
    # A column with no variation contributes no co-movement information.
    usable = [col for col in columns if changes[col].notna().sum() >= 3 and changes[col].std(ddof=0) > 0]
    if len(usable) < 2:
        usable = []

    if usable:
        corr = changes[usable].corr().to_numpy(dtype=float)
        corr = np.nan_to_num(corr, nan=0.0)
        for i, col_i in enumerate(usable):
            for j, col_j in enumerate(usable):
                if i == j:
                    continue
                value = corr[i, j]
                if abs(value) >= min_abs_correlation:
                    matrix[position[col_i], position[col_j]] = abs(value)
        np.fill_diagonal(matrix, 0.0)
        matrix = np.maximum(matrix, matrix.T)

    return MultiplexLayer(
        name=name,
        kind=RelationKind.CO_MOVEMENT,
        adjacency=matrix,
        node_ids=universe,
        as_of=pd.Timestamp(as_of),
        directed=False,
        metadata={
            "window": int(window),
            "min_abs_correlation": float(min_abs_correlation),
            "n_series": len(columns),
            "n_usable": len(usable),
            "basis": "changes",
            "rows_withheld_as_future": excluded,
            "as_of": pd.Timestamp(as_of).isoformat(),
        },
    )


def build_interbank_exposure_layer(
    exposures: pd.DataFrame,
    node_ids: Sequence[str],
    *,
    as_of: pd.Timestamp,
    name: str = "interbank",
    seniority: int = 0,
) -> MultiplexLayer:
    """Interbank obligations: an actual ``debtor -> creditor`` relation.

    Args:
        exposures: Columns ``debtor``, ``creditor``, ``amount`` and optionally
            ``as_of``. Rows dated after ``as_of`` are rejected.
        node_ids: The shared universe.
        as_of: Information cut-off.
        seniority: Clearing priority. Lower is paid first.
    """
    required = {"debtor", "creditor", "amount"}
    missing = required - set(exposures.columns)
    if missing:
        raise ValueError(
            f"exposures is missing required column(s): {sorted(missing)}"
        )
    rows_withheld = 0
    if "as_of" in exposures.columns:
        mask, rows_withheld = _filter_to_as_of(
            exposures["as_of"], as_of, "interbank exposures"
        )
        exposures = exposures.loc[np.asarray(mask)]

    universe = list(node_ids)
    position = {node: index for index, node in enumerate(universe)}
    matrix = np.zeros((len(universe), len(universe)), dtype=float)

    unknown = set()
    for debtor, creditor, amount in zip(
        exposures["debtor"], exposures["creditor"], exposures["amount"]
    ):
        if debtor not in position or creditor not in position:
            unknown.add(debtor if debtor not in position else creditor)
            continue
        if debtor == creditor:
            continue
        value = float(amount)
        if not np.isfinite(value) or value < 0:
            raise ValueError(
                f"exposure {debtor}->{creditor} has invalid amount {amount!r}"
            )
        matrix[position[debtor], position[creditor]] += value

    if unknown:
        raise KeyError(
            f"exposures reference institutions outside the node universe: {sorted(unknown)}"
        )

    return MultiplexLayer(
        name=name,
        kind=RelationKind.EXPOSURE,
        adjacency=matrix,
        node_ids=universe,
        as_of=pd.Timestamp(as_of),
        directed=True,
        metadata={
            "seniority": int(seniority),
            "n_edges": int(np.count_nonzero(matrix)),
            "gross_notional": float(matrix.sum()),
            "rows_withheld_as_future": rows_withheld,
        },
    )


def build_ccp_exposure_layer(
    member_exposures: pd.DataFrame,
    node_ids: Sequence[str],
    *,
    as_of: pd.Timestamp,
    ccp_id: str,
    name: Optional[str] = None,
) -> MultiplexLayer:
    """Clearing-member obligations to a central counterparty.

    Variation margin is an obligation, so this layer is ``EXPOSURE`` and may be
    cleared. The edge points from the clearing member to the CCP: the member owes
    the margin. Loss mutualisation -- the CCP passing a default fund shortfall back
    to surviving members -- is a separate relation and is not modelled here, which
    is recorded in the layer metadata rather than silently assumed away.

    Args:
        member_exposures: Columns ``member`` and ``exposure``. Optionally ``as_of``.
        node_ids: The shared universe, which must contain ``ccp_id``.
        as_of: Information cut-off.
        ccp_id: The central counterparty node.
    """
    if ccp_id not in set(node_ids):
        raise KeyError(f"ccp_id {ccp_id!r} is not in the node universe")
    required = {"member", "exposure"}
    missing = required - set(member_exposures.columns)
    if missing:
        raise ValueError(
            f"member_exposures is missing required column(s): {sorted(missing)}"
        )

    rows_withheld = 0
    if "as_of" in member_exposures.columns:
        mask, rows_withheld = _filter_to_as_of(
            member_exposures["as_of"], as_of, "CCP member exposures"
        )
        member_exposures = member_exposures.loc[np.asarray(mask)]

    universe = list(node_ids)
    position = {node: index for index, node in enumerate(universe)}
    matrix = np.zeros((len(universe), len(universe)), dtype=float)
    ccp_index = position[ccp_id]

    for member, exposure in zip(
        member_exposures["member"], member_exposures["exposure"]
    ):
        if member == ccp_id:
            continue
        if member not in position:
            raise KeyError(f"clearing member {member!r} is not in the node universe")
        value = float(exposure)
        if not np.isfinite(value) or value < 0:
            raise ValueError(f"member {member!r} has invalid exposure {exposure!r}")
        matrix[position[member], ccp_index] += value

    return MultiplexLayer(
        name=name or f"ccp_{ccp_id}",
        kind=RelationKind.EXPOSURE,
        adjacency=matrix,
        node_ids=universe,
        as_of=pd.Timestamp(as_of),
        directed=True,
        metadata={
            "ccp_id": ccp_id,
            "seniority": 0,
            "loss_mutualisation_modelled": False,
            "n_members": int(np.count_nonzero(matrix[:, ccp_index])),
            "rows_withheld_as_future": rows_withheld,
        },
    )


@dataclass
class MultiplexSnapshot:
    """The multiplex as it stood at one instant."""

    as_of: pd.Timestamp
    node_ids: Tuple[str, ...]
    layers: Dict[str, MultiplexLayer] = field(default_factory=dict)

    def add_layer(self, layer: MultiplexLayer) -> None:
        if tuple(layer.node_ids) != tuple(self.node_ids):
            raise ValueError(
                f"layer {layer.name!r} is aligned to a different node universe "
                "than the snapshot"
            )
        if layer.as_of > self.as_of:
            raise ValueError(
                f"layer {layer.name!r} is dated {layer.as_of}, after the snapshot "
                f"at {self.as_of}"
            )
        self.layers[layer.name] = layer

    @property
    def clearing_layers(self) -> List[NetworkLayer]:
        """Every ``EXPOSURE`` layer, ready for the clearing engine."""
        return [
            require_exposure(layer)
            for layer in self.layers.values()
            if layer.is_clearing_eligible
        ]

    def without_clearing_layers(self) -> Dict[str, MultiplexLayer]:
        """Every non-``EXPOSURE`` layer: context, not obligation."""
        return {
            name: layer
            for name, layer in self.layers.items()
            if not layer.is_clearing_eligible
        }

    def to_dict(self) -> Dict[str, object]:
        return {
            "as_of": self.as_of.isoformat(),
            "n_nodes": len(self.node_ids),
            "node_ids": list(self.node_ids),
            "layers": {name: layer.to_dict() for name, layer in self.layers.items()},
            "clearing_eligible": sorted(
                name for name, layer in self.layers.items() if layer.is_clearing_eligible
            ),
        }


class RollingMultiplex:
    """A time-ordered sequence of multiplex snapshots.

    Enforces that ``as_of`` advances: a snapshot added behind an existing one is
    rejected, because a layer history that can move backwards cannot be replayed
    and would let a backtest revise the network it already used.
    """

    def __init__(self, node_ids: Sequence[str]) -> None:
        self.node_ids = tuple(node_ids)
        self._snapshots: List[MultiplexSnapshot] = []

    def __len__(self) -> int:
        return len(self._snapshots)

    @property
    def snapshots(self) -> List[MultiplexSnapshot]:
        return list(self._snapshots)

    def add(self, snapshot: MultiplexSnapshot) -> None:
        if tuple(snapshot.node_ids) != self.node_ids:
            raise ValueError("snapshot is aligned to a different node universe")
        if self._snapshots and snapshot.as_of <= self._snapshots[-1].as_of:
            raise ValueError(
                f"snapshot at {snapshot.as_of} does not advance time past "
                f"{self._snapshots[-1].as_of}; the multiplex is append-only"
            )
        self._snapshots.append(snapshot)

    def at(self, as_of: pd.Timestamp) -> Optional[MultiplexSnapshot]:
        """The most recent snapshot at or before ``as_of``.

        Uses the latest snapshot *known* at that time, which is the only one a
        model evaluated at ``as_of`` could have seen.
        """
        as_of = pd.Timestamp(as_of)
        candidate: Optional[MultiplexSnapshot] = None
        for snapshot in self._snapshots:
            if snapshot.as_of <= as_of:
                candidate = snapshot
            else:
                break
        return candidate

    def layer_history(self, layer_name: str) -> List[Tuple[pd.Timestamp, MultiplexLayer]]:
        """Every snapshot's version of one layer, in time order."""
        history = []
        for snapshot in self._snapshots:
            layer = snapshot.layers.get(layer_name)
            if layer is not None:
                history.append((snapshot.as_of, layer))
        return history

    def to_dict(self) -> Dict[str, object]:
        return {
            "n_nodes": len(self.node_ids),
            "node_ids": list(self.node_ids),
            "n_snapshots": len(self._snapshots),
            "snapshots": [snapshot.to_dict() for snapshot in self._snapshots],
        }


# ---------------------------------------------------------------------------
# Cross-currency (FX swap) funding
# ---------------------------------------------------------------------------
#
# Systemic liquidity crises almost always reach the FX swap market before they
# reach anything else: a institution that funds itself in one currency and lends
# or invests in another must obtain the foreign currency, and when it cannot the
# cross-currency basis widens. That widening is the first observable symptom.
#
# Two different things are built here, and keeping them apart is the whole point.
#
# ``build_fx_swap_exposure_layer`` builds an EXPOSURE layer, because a currency
# swap is a contractual obligation: the near leg is drawn, the far leg is owed.
# It is clearing-eligible like any other obligation.
#
# ``build_fx_basis_layer`` builds a CO_MOVEMENT layer, because a basis is a
# *price*, not a promise. Two institutions funded in the same currency at risk
# are exposed to the same squeeze; neither owes the other anything. Clearing this
# layer would be the same category error as running Eisenberg-Noe on a
# correlation matrix, which is precisely the error this module was rebuilt to
# remove. ``require_exposure`` refuses it, and a test asserts that it does.


def _basis_by_funding_currency(
    basis: object,
) -> Dict[str, float]:
    """Coerce a basis publication into ``{currency: basis_points}``.

    Accepts a mapping, a ``pandas.Series`` indexed by currency, or a frame with
    ``currency`` and ``basis`` columns. Duplicate, conflicting or non-finite
    entries raise rather than being resolved by whichever row happened to be last.
    """
    rates: Dict[str, float] = {}
    if isinstance(basis, pd.DataFrame):
        required = {"currency", "basis"}
        missing = required - set(basis.columns)
        if missing:
            raise ValueError(f"basis is missing required column(s): {sorted(missing)}")
        pairs = list(zip(basis["currency"], basis["basis"]))
    elif isinstance(basis, pd.Series):
        pairs = list(basis.items())
    elif isinstance(basis, dict):
        pairs = list(basis.items())
    else:
        raise TypeError(
            "basis must be a mapping, a pandas Series or a DataFrame with "
            f"'currency' and 'basis' columns, got {type(basis).__name__}"
        )

    for currency, value in pairs:
        key = str(currency)
        numeric = float(value)
        if not np.isfinite(numeric):
            raise ValueError(f"basis for {key!r} is not finite: {value!r}")
        if key in rates and rates[key] != numeric:
            raise ValueError(
                f"conflicting basis observations for {key!r}: "
                f"{rates[key]} and {numeric}"
            )
        rates[key] = numeric
    if not rates:
        raise ValueError("basis is empty; no currency has a basis observation")
    return rates


def cross_currency_funding_exposure(
    funding_mix: pd.DataFrame,
    basis: object,
    *,
    stress_only: bool = True,
) -> Dict[str, float]:
    """Per-institution exposure to a cross-currency funding squeeze.

    An institution's exposure is the share-weighted basis of the currencies it
    funds itself in::

        exposure_i = sum_c  share_ic * f(basis_c)

    The basis is indexed by **funding currency** and quoted in basis points. A
    negative basis is the stress direction -- it means obtaining US dollars
    against that currency costs a premium -- so with ``stress_only`` (the
    default) ``f(b) = max(0, -b)`` and a positive basis adds nothing. That
    asymmetry is deliberate: a basis in the other direction is not evidence of a
    dollar squeeze and must not be counted as one. ``stress_only=False`` uses
    ``|b|`` to treat both directions as dislocation.

    Args:
        funding_mix: Columns ``institution``, ``currency`` and ``share``. Shares
            are the institution's funding composition and must sum to 1 per
            institution. A share may be zero, in which case the currency needs no
            basis observation.
        basis: Basis points by funding currency -- a mapping, a ``Series``, or a
            frame with ``currency`` and ``basis``.
        stress_only: Count only the dollar-squeeze direction, as above.

    Returns:
        ``{institution: exposure_in_basis_points}``.

    Raises:
        ValueError: If the frame is malformed, a share is negative or non-finite,
            an institution's shares do not sum to 1, or the basis is malformed.
        KeyError: If an institution funds in a currency with a non-zero share and
            no basis observation exists. A missing price is not a zero price.
    """
    required = {"institution", "currency", "share"}
    missing = required - set(funding_mix.columns)
    if missing:
        raise ValueError(
            f"funding_mix is missing required column(s): {sorted(missing)}"
        )
    rates = _basis_by_funding_currency(basis)

    mixes: Dict[str, Dict[str, float]] = {}
    for institution, currency, share in zip(
        funding_mix["institution"], funding_mix["currency"], funding_mix["share"]
    ):
        key = str(institution)
        value = float(share)
        if not np.isfinite(value) or value < 0:
            raise ValueError(
                f"funding share for {key!r} in {currency!r} is invalid: {share!r}"
            )
        bucket = mixes.setdefault(key, {})
        bucket[str(currency)] = bucket.get(str(currency), 0.0) + value

    if not mixes:
        raise ValueError("funding_mix is empty; no institution has a funding mix")

    exposure: Dict[str, float] = {}
    for institution, bucket in mixes.items():
        total = sum(bucket.values())
        if not np.isfinite(total) or total <= 0.0:
            raise ValueError(
                f"funding shares for {institution!r} sum to {total!r}; a funding "
                "composition must be a positive distribution"
            )
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"funding shares for {institution!r} sum to {total:.6f}, not 1"
            )
        unobserved = sorted(
            currency
            for currency, weight in bucket.items()
            if weight > 0.0 and currency not in rates
        )
        if unobserved:
            raise KeyError(
                f"{institution!r} funds in {unobserved} but no basis observation "
                "exists for those currencies; a missing basis is not a zero basis"
            )
        value = 0.0
        for currency, weight in bucket.items():
            if currency not in rates:
                continue
            quoted = rates[currency]
            value += weight * (max(0.0, -quoted) if stress_only else abs(quoted))
        exposure[institution] = float(value)
    return exposure


def build_fx_basis_layer(
    funding_mix: pd.DataFrame,
    basis: object,
    node_ids: Sequence[str],
    *,
    as_of: pd.Timestamp,
    name: str = "fx_swap_basis",
    stress_only: bool = True,
    absent_means_zero: bool = False,
) -> MultiplexLayer:
    """Cross-currency funding stress coupling: a ``CO_MOVEMENT`` layer.

    The edge weight between two institutions is the product of their basis
    exposures, so institutions with no cross-currency funding stress are
    unconnected and none is ever connected to itself. This is a relation of
    *shared vulnerability*, not of obligation: it identifies who would be hurt by
    the same dollar squeeze at the same time. It is deliberately **not**
    clearing-eligible, and ``require_exposure`` refuses it -- there is no "who
    owes whom" in a price.

    Args:
        funding_mix: As for :func:`cross_currency_funding_exposure`.
        basis: As for :func:`cross_currency_funding_exposure`.
        node_ids: The shared universe.
        as_of: Information cut-off.
        name: Layer name.
        stress_only: As for :func:`cross_currency_funding_exposure`.
        absent_means_zero: What a node absent from ``funding_mix`` means. By
            default this is a ``KeyError``: absence of funding data is not
            evidence of domestic-only funding. Setting it to True is an explicit
            caller declaration that every unlisted node funds purely in the base
            currency, and the declaration is recorded in the layer metadata so it
            cannot be forgotten later.

    Raises:
        KeyError: If a node has no funding mix and ``absent_means_zero`` is False,
            or the mix names an institution outside the universe.
        ValueError: If the inputs are malformed, as for
            :func:`cross_currency_funding_exposure`.
    """
    exposure = cross_currency_funding_exposure(
        funding_mix, basis, stress_only=stress_only
    )
    universe = [str(node) for node in node_ids]
    if len(set(universe)) != len(universe):
        raise ValueError("node_ids contains duplicates")

    outside = sorted(set(exposure) - set(universe))
    if outside:
        raise KeyError(
            f"funding_mix names institutions outside the node universe: {outside}"
        )
    absent = sorted(set(universe) - set(exposure))
    if absent and not absent_means_zero:
        raise KeyError(
            f"no funding mix supplied for {absent}; absence of funding data is not "
            "evidence of domestic-only funding. Pass absent_means_zero=True to "
            "declare that explicitly."
        )

    if absent_means_zero:
        vector = np.array(
            [exposure.get(node, 0.0) for node in universe], dtype=float
        )
    else:
        vector = np.array([exposure[node] for node in universe], dtype=float)

    matrix = np.outer(vector, vector)
    np.fill_diagonal(matrix, 0.0)

    return MultiplexLayer(
        name=name,
        kind=RelationKind.CO_MOVEMENT,
        adjacency=matrix,
        node_ids=universe,
        as_of=pd.Timestamp(as_of),
        directed=False,
        metadata={
            "relation": "shared cross-currency funding stress",
            "basis_units": "basis points",
            "basis_convention": (
                "dollar-squeeze direction only (a negative basis is the stress "
                "sign); a positive basis contributes nothing"
                if stress_only
                else "absolute basis dislocation, both directions counted"
            ),
            "funding_exposure": {
                node: float(value) for node, value in exposure.items()
            },
            "nodes_assumed_base_currency_funded": absent if absent_means_zero else [],
            "clearing_eligible": False,
            "n_edges": int(np.count_nonzero(matrix)),
        },
    )


def build_fx_swap_exposure_layer(
    fx_swaps: pd.DataFrame,
    node_ids: Sequence[str],
    *,
    as_of: pd.Timestamp,
    name: str = "fx_swap_funding",
    seniority: int = 0,
) -> MultiplexLayer:
    """Cross-currency funding obligations: a ``debtor -> creditor`` relation.

    An FX swap is a contractual obligation -- the near leg is drawn and the far
    leg is owed -- so this layer is ``EXPOSURE`` and may be cleared, with the edge
    pointing from the institution that owes the far leg to the one that holds it.

    **Notionals must already share one numeraire.** The layer matrix is a
    magnitude, and adding a EUR notional to a USD one would be adding unlike
    quantities; the conversion is the caller's, and the currency pairs actually
    used are recorded in the metadata so a reader can see what was aggregated.

    Args:
        fx_swaps: Columns ``debtor``, ``creditor``, ``notional`` and optionally
            ``currency_pair`` and ``as_of``. Rows dated after ``as_of`` are
            rejected, not silently included.
        node_ids: The shared universe.
        as_of: Information cut-off.
        name: Layer name.
        seniority: Clearing priority. Lower is paid first.

    Raises:
        ValueError: If a required column is missing or a notional is negative or
            non-finite.
        KeyError: If a counterparty is outside the node universe.
    """
    required = {"debtor", "creditor", "notional"}
    missing = required - set(fx_swaps.columns)
    if missing:
        raise ValueError(f"fx_swaps is missing required column(s): {sorted(missing)}")

    rows_withheld = 0
    if "as_of" in fx_swaps.columns:
        mask, rows_withheld = _filter_to_as_of(
            fx_swaps["as_of"], as_of, "FX swap obligations"
        )
        fx_swaps = fx_swaps.loc[np.asarray(mask)]

    universe = list(node_ids)
    position = {node: index for index, node in enumerate(universe)}
    matrix = np.zeros((len(universe), len(universe)), dtype=float)
    pairs = set()
    has_pairs = "currency_pair" in fx_swaps.columns
    unknown = set()

    for row in fx_swaps.itertuples(index=False):
        debtor = row.debtor
        creditor = row.creditor
        if debtor not in position or creditor not in position:
            unknown.add(debtor if debtor not in position else creditor)
            continue
        if debtor == creditor:
            continue
        value = float(row.notional)
        if not np.isfinite(value) or value < 0:
            raise ValueError(
                f"FX swap {debtor}->{creditor} has invalid notional {row.notional!r}"
            )
        matrix[position[debtor], position[creditor]] += value
        if has_pairs:
            pairs.add(str(row.currency_pair))

    if unknown:
        raise KeyError(
            "fx_swaps reference institutions outside the node universe: "
            f"{sorted(unknown)}"
        )

    return MultiplexLayer(
        name=name,
        kind=RelationKind.EXPOSURE,
        adjacency=matrix,
        node_ids=universe,
        as_of=pd.Timestamp(as_of),
        directed=True,
        metadata={
            "seniority": int(seniority),
            "currency_pairs": sorted(pairs),
            "numeraire_note": (
                "notionals are assumed to share a single numeraire; the conversion "
                "is the caller's and is not performed here"
            ),
            "n_edges": int(np.count_nonzero(matrix)),
            "gross_notional": float(matrix.sum()),
            "rows_withheld_as_future": rows_withheld,
        },
    )
