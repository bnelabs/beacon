"""Crowded-trade overlap across institutional holdings.

Why this module exists
----------------------

BEACON already answers three distinct network questions:

* *who owes whom* -- the Eisenberg-Noe clearing vector
  (:mod:`backend.modules.risk.clearing`);
* *how prices feed back into forced selling* -- the Brunnermeier-Pedersen
  liquidity spiral (:mod:`backend.modules.risk.liquidity_spiral`);
* *whether the network's routes have thinned* -- topological redundancy in the
  graph modules.

None of them sees a **crowded trade**. When many institutions hold the same
position, a single liquidation propagates as a *correlated unwind*: the holders
sell the same names at the same time, and the price impact each one inflicts on
the others is the transmission channel itself. That is a distinct volatility
channel. It is invisible to node-level statistics and to owed-balance exposure
data, because two institutions can hold identical positions and have no
contractual link at all. The risk lives in the overlap of their books, not in
any contract between them.

What is implemented
-------------------

Given a holdings matrix (institutions x instruments, values are position sizes):

* a **signed cosine overlap** and two **Jaccard-style name overlaps** (one
  sign-agnostic, one directional) over every pair of institutions, exposed as
  separate, named measures rather than one silently chosen metric;
* a **gross Herfindahl-Hirschman concentration** of each instrument across
  institutions, with its bounds documented and tested;
* a normalised **system-level crowded-trade score** built from the *effective
  number of holders* of each instrument, weighted by gross exposure;
* a **correlated-unwind exposure** for a named instrument at a caller-supplied
  concentration threshold;
* institution and instrument names carried through to every result so a
  regulator can read *who* and *what*, not just a scalar.

Conventions that must be stated up front
----------------------------------------

**Zero versus missing.** These are different facts. A genuine zero means "holds
none of this"; a missing entry means "we do not know". The module never treats a
missing entry as a zero position. Missing entries are governed by an explicit
:class:`MissingDataPolicy`:

* :attr:`MissingDataPolicy.FAIL_CLOSED` (the default) raises
  :class:`PortfolioOverlapDataError` if any NaN is present.
* :attr:`MissingDataPolicy.EXCLUDE_INSTITUTIONS` drops every institution whose
  row contains a NaN and records the dropped names.
* :attr:`MissingDataPolicy.EXCLUDE_INSTRUMENTS` drops every instrument whose
  column contains a NaN and records the dropped names.
* :attr:`MissingDataPolicy.EXCLUDE_BOTH` drops every institution and every
  instrument with a NaN, each judged on the original matrix, and records both
  sets.

The two exclusion policies are explicit *caller declarations*; nothing is
dropped silently, and every exclusion is reported in the result.

**Signed positions.** Shorts are supported and are written as negative sizes.
The convention is that a long and a short in the same name are *opposite*
exposure, not the same crowded trade:

* the cosine overlap is **signed**, so two identical shorts correlate ``+1``,
  a long against an equal short correlates ``-1``, and disjoint books
  correlate ``0``;
* the **directional** Jaccard overlap counts a name as shared only when both
  institutions hold it on the same side, so long-versus-short scores ``0``;
* the **sign-agnostic** Jaccard overlap reports that both books touch the same
  name regardless of direction, and is exposed separately and labelled as
  such;
* per-instrument crowding and the correlated-unwind exposure are measured on
  **absolute** (gross) holdings -- unwinding a short is a purchase, which is
  also a flow and also moves the price -- and the result reports the long and
  short breakdown so the direction is never hidden.

**Pairwise magic numbers.** Every pairwise matrix is symmetric with a diagonal
of exactly ``1`` by definition (a book trivially overlaps itself, including an
all-zero book). A zero-norm book has cosine ``0`` against every other book.

Why the system score inverts the HHI
------------------------------------

Per-instrument HHI is high when *few* institutions hold the instrument and low
when *many* hold it equally. Crowding is the opposite: it is high when many
institutions share the exposure. The system score therefore uses the
*effective number of holders* ``1 / HHI`` (which equals ``n_j`` at perfect
equality and ``1`` for a single holder), normalised by the institution count,
weighted by the instrument's share of system gross exposure, and finally
renormalised so that ``0`` means every instrument has a single holder (no
crowding) and ``1`` means every instrument is held equally by every
institution. Both the raw HHI and the normalised score are reported, and the
inversion is deliberate, not an error.

What is NOT implemented, and the limitations
--------------------------------------------

* **Overlap is not causality.** Two institutions may hold the same names for
  unrelated reasons -- index membership, mandates, a liquidity bucket -- and a
  shared position need not mean a shared trigger or a shared exit.
* **No look-through.** Positions may be hedged or offset by derivatives and
  fund holdings for which this matrix has no look-through. What is measured is
  the visible book.
* **Delta-equivalent, point-in-time.** Holdings carry no maturity, liquidity,
  seniority, collateral, or netting information, and no path: this is a
  snapshot, not a projection.
* **Absent is not unheld.** An instrument missing from the columns is not the
  same fact as a zero in the matrix, and the module cannot see what was never
  supplied.
* **The crowding score is a summary statistic.** Its normalisation and the
  concentration threshold are conventions, not regulatory definitions, and a
  high score is a flag, not a finding.
* **Gross crowding nets nothing.** A long and a short in the same name both
  count toward gross concentration even though they offset directionally. The
  directional overlap matrices and the long/short split expose this, but the
  system score does not net it.
* **No price or behaviour model.** The "shock" is a name, not a severity. The
  module identifies where a correlated unwind could originate; it does not
  simulate the unwind, and the exposure does not scale with the size of any
  shock.
* **The cosine ignores size.** A small book and a large one pointed the same
  way correlate ``+1``; cosine measures direction, not magnitude.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from backend.exceptions import DataQualityError

__all__ = [
    "MissingDataPolicy",
    "InstrumentCrowding",
    "CrowdingScore",
    "CorrelatedUnwindExposure",
    "PortfolioOverlapResult",
    "PortfolioOverlapDataError",
    "analyse_portfolio_overlap",
    "signed_cosine_overlap",
    "jaccard_name_overlap",
    "jaccard_directional_overlap",
    "instrument_crowding",
    "system_crowding_score",
    "correlated_unwind_exposure",
]

PositionsLike = Union[np.ndarray, Sequence[Sequence[float]]]


class PortfolioOverlapDataError(DataQualityError):
    """Holdings data that cannot be trusted for overlap measurement.

    Subclasses :class:`~backend.exceptions.DataQualityError` so callers already
    branching on the quality taxonomy catch it, while the distinct stable
    ``code`` distinguishes "holdings contain missing values" from other quality
    failures without reading the message text.
    """

    code = "PORTFOLIO_OVERLAP_DATA_INVALID"


class MissingDataPolicy(str, Enum):
    """What to do when the holdings matrix contains missing (NaN) entries.

    A NaN is "we do not know", which is not the same fact as a zero position
    ("holds none"). The default refuses to guess; the exclusion policies are
    explicit caller declarations that drop and report the affected labels.

    Attributes:
        FAIL_CLOSED: Raise :class:`PortfolioOverlapDataError` if any NaN is
            present. The default. No value is ever imputed.
        EXCLUDE_INSTITUTIONS: Drop every institution (row) containing a NaN and
            report the dropped names. Institutions with complete rows are kept,
            including their genuine zeros.
        EXCLUDE_INSTRUMENTS: Drop every instrument (column) containing a NaN and
            report the dropped names. Complete columns are kept, including their
            genuine zeros.
        EXCLUDE_BOTH: Drop every institution whose row contains a NaN and every
            instrument whose column contains a NaN, each judged on the original
            matrix, reporting both sets. The retained submatrix is therefore
            free of missing entries; it is the union of the two single-axis
            exclusions, not a sequence of them.
    """

    FAIL_CLOSED = "fail_closed"
    EXCLUDE_INSTITUTIONS = "exclude_institutions"
    EXCLUDE_INSTRUMENTS = "exclude_instruments"
    EXCLUDE_BOTH = "exclude_both"


@dataclass(frozen=True)
class InstrumentCrowding:
    """Gross concentration of one instrument across institutions.

    Attributes:
        instrument: Instrument name.
        gross_exposure: ``sum_i |h_ij|`` -- total absolute position in the name.
        net_exposure: ``sum_i h_ij`` -- signed net, long minus short.
        long_exposure: ``sum_{h_ij > 0} h_ij`` -- total long size.
        short_exposure: ``-sum_{h_ij < 0} h_ij`` -- total short size, positive.
        n_holders: Number of institutions with a nonzero holding of the name.
        hhi: Herfindahl-Hirschman index of the gross shares across holders,
            ``sum_i (|h_ij| / gross_exposure)**2``. Bounds are ``1 / n_holders``
            at perfect equality and ``1`` at a single holder. Reported as
            ``0.0`` for a name nobody holds, where no shares exist and there is
            no crowding to measure; such a name carries zero weight in the
            system score.
        effective_holders: ``1 / hhi``, the effective number of equal-sized
            holders, in ``[1, n_holders]``; ``0.0`` when nobody holds the name.
        weight: The name's share of system gross exposure,
            ``gross_exposure / total_gross``.
    """

    instrument: str
    gross_exposure: float
    net_exposure: float
    long_exposure: float
    short_exposure: float
    n_holders: int
    hhi: float
    effective_holders: float
    weight: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "instrument": self.instrument,
            "gross_exposure": float(self.gross_exposure),
            "net_exposure": float(self.net_exposure),
            "long_exposure": float(self.long_exposure),
            "short_exposure": float(self.short_exposure),
            "n_holders": int(self.n_holders),
            "hhi": float(self.hhi),
            "effective_holders": float(self.effective_holders),
            "weight": float(self.weight),
        }


@dataclass(frozen=True)
class CrowdingScore:
    """System-level crowded-trade score, aggregated over instruments.

    Attributes:
        raw: Exposure-weighted mean participation,
            ``sum_j w_j * (1 / HHI_j) / n``. Rises with both broad participation
            and exposure in widely-held names. Bounds ``[1/n, 1]`` for ``n > 1``.
        normalized: ``raw`` renormalised so that ``0`` means every instrument has
            a single holder and ``1`` means every instrument is held equally by
            all institutions. Reported as ``0.0`` for a single-institution system,
            where no cross-institutional crowding is possible.
        n_institutions: Institution count the score was computed against.
        total_gross_exposure: ``sum_ij |h_ij|``.
        weighted_mean_hhi: Exposure-weighted mean of the per-instrument HHIs.
    """

    raw: float
    normalized: float
    n_institutions: int
    total_gross_exposure: float
    weighted_mean_hhi: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "raw": float(self.raw),
            "normalized": float(self.normalized),
            "n_institutions": int(self.n_institutions),
            "total_gross_exposure": float(self.total_gross_exposure),
            "weighted_mean_hhi": float(self.weighted_mean_hhi),
        }


@dataclass(frozen=True)
class CorrelatedUnwindExposure:
    """How much of the system liquidates together when one name is shocked.

    An institution is treated as forced to unwind its holding of the instrument
    when that holding is at least ``concentration_threshold`` of its own gross
    book, i.e. when the shock hits a name the institution is concentrated in.
    The comparison is inclusive (``>=``), so an institution exactly at the
    threshold qualifies.

    Attributes:
        instrument: The shocked instrument.
        concentration_threshold: The caller-supplied threshold in ``[0, 1]``.
        exposure: Sum of absolute positions in the instrument over every
            qualifying institution.
        fraction_of_instrument: ``exposure`` divided by the instrument's gross
            exposure; ``0.0`` if nobody holds the name.
        fraction_of_system: ``exposure`` divided by total system gross exposure;
            ``0.0`` if the system holds nothing.
        n_liquidating: Number of qualifying institutions.
        liquidating_institutions: Names of the qualifying institutions, sorted.
        long_exposure: Long part of ``exposure``.
        short_exposure: Short part of ``exposure``, positive.
    """

    instrument: str
    concentration_threshold: float
    exposure: float
    fraction_of_instrument: float
    fraction_of_system: float
    n_liquidating: int
    liquidating_institutions: Tuple[str, ...]
    long_exposure: float
    short_exposure: float

    def to_dict(self) -> Dict[str, object]:
        return {
            "instrument": self.instrument,
            "concentration_threshold": float(self.concentration_threshold),
            "exposure": float(self.exposure),
            "fraction_of_instrument": float(self.fraction_of_instrument),
            "fraction_of_system": float(self.fraction_of_system),
            "n_liquidating": int(self.n_liquidating),
            "liquidating_institutions": list(self.liquidating_institutions),
            "long_exposure": float(self.long_exposure),
            "short_exposure": float(self.short_exposure),
        }


@dataclass(frozen=True)
class PortfolioOverlapResult:
    """Outcome of a crowded-trade overlap analysis.

    All labels are carried through so the result can be read by name. Pairwise
    matrices are ordered by :attr:`institution_ids`.

    Attributes:
        positions: The holdings matrix actually used, after any declared
            exclusions, institutions x instruments.
        institution_ids: Ordered institution names retained.
        instrument_ids: Ordered instrument names retained.
        cosine_overlap: ``(n, n)`` signed cosine similarity of the position
            vectors. Symmetric, diagonal exactly ``1``.
        jaccard_name_overlap: ``(n, n)`` sign-agnostic Jaccard overlap of the
            sets of names held. Symmetric, diagonal exactly ``1``.
        jaccard_directional_overlap: ``(n, n)`` Jaccard overlap counting a name
            as shared only when both institutions hold it on the same side.
            Symmetric, diagonal exactly ``1``.
        instrument_crowding: Per-instrument gross concentration, ordered by
            :attr:`instrument_ids`.
        system_crowding: The system-level score.
        unwind_exposures: Correlated-unwind exposure keyed by instrument name,
            populated only when a threshold was supplied.
        missing_policy: The policy the analysis was computed under.
        excluded_institutions: Institution names dropped by the policy.
        excluded_instruments: Instrument names dropped by the policy.
    """

    positions: np.ndarray
    institution_ids: List[str]
    instrument_ids: List[str]
    cosine_overlap: np.ndarray
    jaccard_name_overlap: np.ndarray
    jaccard_directional_overlap: np.ndarray
    instrument_crowding: List[InstrumentCrowding]
    system_crowding: CrowdingScore
    unwind_exposures: Dict[str, CorrelatedUnwindExposure]
    missing_policy: MissingDataPolicy
    excluded_institutions: List[str]
    excluded_instruments: List[str]

    def unwind_exposure(
        self, instrument: str, concentration_threshold: float
    ) -> CorrelatedUnwindExposure:
        """Correlated-unwind exposure for a named instrument.

        The threshold is a required argument: this module never invents one.
        """
        if instrument not in self.instrument_ids:
            raise ValueError(
                f"unknown instrument {instrument!r}; "
                f"known instruments are {self.instrument_ids}"
            )
        threshold = _validate_threshold(concentration_threshold)
        index = self.instrument_ids.index(instrument)
        return _unwind_for_column(
            self.positions, index, threshold, self.institution_ids, instrument
        )

    def to_dict(self) -> Dict[str, object]:
        """A JSON-safe, name-keyed view of the whole result."""
        return {
            "missing_policy": self.missing_policy.value,
            "institutions": list(self.institution_ids),
            "instruments": list(self.instrument_ids),
            "excluded_institutions": list(self.excluded_institutions),
            "excluded_instruments": list(self.excluded_instruments),
            "positions": {
                self.institution_ids[i]: {
                    self.instrument_ids[j]: float(self.positions[i, j])
                    for j in range(len(self.instrument_ids))
                }
                for i in range(len(self.institution_ids))
            },
            "cosine_overlap": _matrix_to_named(
                self.cosine_overlap, self.institution_ids
            ),
            "jaccard_name_overlap": _matrix_to_named(
                self.jaccard_name_overlap, self.institution_ids
            ),
            "jaccard_directional_overlap": _matrix_to_named(
                self.jaccard_directional_overlap, self.institution_ids
            ),
            "instrument_crowding": [c.to_dict() for c in self.instrument_crowding],
            "system_crowding": self.system_crowding.to_dict(),
            "unwind_exposures": {
                name: exposure.to_dict()
                for name, exposure in self.unwind_exposures.items()
            },
        }


def _matrix_to_named(matrix: np.ndarray, labels: Sequence[str]) -> Dict[str, object]:
    return {
        labels[i]: {
            labels[j]: float(matrix[i, j]) for j in range(len(labels))
        }
        for i in range(len(labels))
    }


def _coerce_policy(policy: Union[MissingDataPolicy, str]) -> MissingDataPolicy:
    if isinstance(policy, MissingDataPolicy):
        return policy
    try:
        return MissingDataPolicy(policy)
    except ValueError as exc:
        allowed = [member.value for member in MissingDataPolicy]
        raise ValueError(
            f"missing_policy must be one of {allowed}, got {policy!r}"
        ) from exc


def _as_matrix(positions: PositionsLike, *, allow_missing: bool = False) -> np.ndarray:
    """Validate a holdings matrix and return it as a float array.

    Infinite values are always rejected: they are malformed, not missing. NaN is
    rejected unless ``allow_missing`` is set, because a caller reaching a
    low-level helper directly has no policy to declare and must fail closed.
    """
    try:
        array = np.asarray(positions, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"positions must be a rectangular numeric matrix: {exc}"
        ) from exc
    if array.ndim != 2:
        raise ValueError(
            "positions must be a 2-D matrix (institutions x instruments), "
            f"got ndim {array.ndim}"
        )
    if np.isinf(array).any():
        raise ValueError(
            "positions contains non-finite (infinite) values; these are "
            "malformed, not missing, and are always refused"
        )
    if not allow_missing and np.isnan(array).any():
        raise ValueError(
            "positions contains missing (NaN) values; use "
            "analyse_portfolio_overlap with an explicit MissingDataPolicy "
            "rather than letting a helper treat them as zero"
        )
    return array


def _normalise_ids(
    ids: Optional[Sequence[str]], expected: int, what: str
) -> List[str]:
    if ids is None:
        raise ValueError(f"{what} is required")
    values = [str(value) for value in ids]
    if len(values) != expected:
        raise ValueError(
            f"{what} has length {len(values)} but positions has {expected} "
            f"{'rows' if what == 'institution_ids' else 'columns'}"
        )
    seen: set = set()
    duplicates: List[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    if duplicates:
        raise ValueError(f"{what} contains duplicate labels: {duplicates}")
    if any(value == "" for value in values):
        raise ValueError(f"{what} contains an empty label")
    return values


def _validate_threshold(threshold: float) -> float:
    value = float(threshold)
    if not np.isfinite(value):
        raise ValueError(
            f"concentration_threshold must be finite, got {threshold!r}"
        )
    if not 0.0 <= value <= 1.0:
        raise ValueError(
            f"concentration_threshold must lie in [0, 1], got {value}"
        )
    return value


def signed_cosine_overlap(positions: PositionsLike) -> np.ndarray:
    """Signed cosine similarity between every pair of position vectors.

    ``dot(u, v) / (||u|| * ||v||)`` on the raw (signed) positions. Identical
    direction is ``+1`` regardless of magnitude, opposite direction is ``-1``,
    and disjoint books are ``0``. The diagonal is exactly ``1`` by definition; a
    zero-norm book is ``0`` against every other book.
    """
    array = _as_matrix(positions)
    dot = array @ array.T
    norms = np.linalg.norm(array, axis=1)
    denominator = np.outer(norms, norms)
    overlap = np.divide(
        dot, denominator, out=np.zeros_like(dot, dtype=float), where=denominator > 0
    )
    overlap = np.clip(overlap, -1.0, 1.0)
    # Self-overlap is an identity, not a measurement, so it holds even for an
    # all-zero book where the cosine is otherwise undefined.
    np.fill_diagonal(overlap, 1.0)
    return overlap


def jaccard_name_overlap(positions: PositionsLike) -> np.ndarray:
    """Jaccard overlap of the sets of names held, ignoring direction.

    ``|held_i n held_k| / |held_i u held_k|`` where a name is held when the
    position is nonzero. Long and short in the same name count as shared here;
    use :func:`jaccard_directional_overlap` to separate the sides. The diagonal
    is exactly ``1``; two empty books have no names to share and score ``0``.
    """
    array = _as_matrix(positions)
    held = (array != 0.0).astype(float)
    held_counts = held.sum(axis=1)
    intersection = held @ held.T
    union = held_counts[:, None] + held_counts[None, :] - intersection
    overlap = np.divide(
        intersection, union, out=np.zeros_like(intersection), where=union > 0
    )
    np.fill_diagonal(overlap, 1.0)
    return overlap


def jaccard_directional_overlap(positions: PositionsLike) -> np.ndarray:
    """Jaccard overlap counting a name as shared only on the same side.

    A name held long by one institution and short by another is *not* shared:
    ``|same-sign names| / |names held by either|``. Two identical shorts score
    ``1``; an exact long against an exact short scores ``0``. The diagonal is
    exactly ``1``.
    """
    array = _as_matrix(positions)
    held = (array != 0.0).astype(float)
    positive = (array > 0.0).astype(float)
    negative = (array < 0.0).astype(float)

    held_counts = held.sum(axis=1)
    union = held_counts[:, None] + held_counts[None, :] - held @ held.T
    same_side = positive @ positive.T + negative @ negative.T
    overlap = np.divide(
        same_side, union, out=np.zeros_like(same_side), where=union > 0
    )
    np.fill_diagonal(overlap, 1.0)
    return overlap


def instrument_crowding(
    positions: PositionsLike,
    instrument_ids: Optional[Sequence[str]] = None,
) -> List[InstrumentCrowding]:
    """Gross concentration of each instrument across institutions.

    Uses absolute holdings, because a short must eventually be bought back and
    that purchase is also a flow. HHI is ``sum_i (|h_ij| / gross_j)**2`` with
    bounds ``1 / n_holders`` at perfect equality and ``1`` at a single holder;
    a name nobody holds is reported as ``0.0`` and carries zero weight.
    """
    array = _as_matrix(positions)
    _, n_instruments = array.shape
    if instrument_ids is None:
        labels = [f"instrument_{j}" for j in range(n_instruments)]
    else:
        labels = _normalise_ids(instrument_ids, n_instruments, "instrument_ids")

    absolute = np.abs(array)
    gross = absolute.sum(axis=0)
    total_gross = float(gross.sum())

    crowding: List[InstrumentCrowding] = []
    for j, label in enumerate(labels):
        column = absolute[:, j]
        column_gross = float(gross[j])
        signed_column = array[:, j]
        long_exposure = float(signed_column[signed_column > 0.0].sum())
        short_exposure = float(-signed_column[signed_column < 0.0].sum())
        net_exposure = float(signed_column.sum())
        holders = column > 0.0
        n_holders = int(holders.sum())

        if column_gross > 0.0:
            shares = column / column_gross
            hhi = float((shares * shares).sum())
            effective_holders = float(1.0 / hhi)
        else:
            # No holders: there are no shares, so HHI is undefined. Report zero
            # concentration and let the zero weight keep it out of the score.
            hhi = 0.0
            effective_holders = 0.0

        weight = float(column_gross / total_gross) if total_gross > 0.0 else 0.0
        crowding.append(
            InstrumentCrowding(
                instrument=label,
                gross_exposure=column_gross,
                net_exposure=net_exposure,
                long_exposure=long_exposure,
                short_exposure=short_exposure,
                n_holders=n_holders,
                hhi=hhi,
                effective_holders=effective_holders,
                weight=weight,
            )
        )
    return crowding


def system_crowding_score(
    per_instrument: Sequence[InstrumentCrowding],
    n_institutions: int,
) -> CrowdingScore:
    """Aggregate per-instrument crowding into one normalised system score.

    ``raw = sum_j w_j * effective_holders_j / n``. The effective-holder term is
    the reciprocal of the HHI, so the score rises when many institutions share
    a name and falls when a name is held by few. It is then renormalised so that
    ``0`` means every instrument has exactly one holder and ``1`` means every
    instrument is held equally by all ``n`` institutions.
    """
    if n_institutions < 1:
        raise ValueError(
            f"n_institutions must be at least 1, got {n_institutions}"
        )

    raw = 0.0
    weighted_mean_hhi = 0.0
    total_gross = 0.0
    for entry in per_instrument:
        raw += entry.weight * entry.effective_holders / n_institutions
        weighted_mean_hhi += entry.weight * entry.hhi
        total_gross += entry.gross_exposure

    if n_institutions <= 1:
        # With one institution there is no cross-institutional crowding at all,
        # and the baseline 1/n equals 1, so the normalisation is degenerate.
        normalized = 0.0
    else:
        baseline = 1.0 / n_institutions
        normalized = (raw - baseline) / (1.0 - baseline)
        normalized = float(min(max(normalized, 0.0), 1.0))

    return CrowdingScore(
        raw=float(raw),
        normalized=float(normalized),
        n_institutions=int(n_institutions),
        total_gross_exposure=float(total_gross),
        weighted_mean_hhi=float(weighted_mean_hhi),
    )


def _unwind_for_column(
    array: np.ndarray,
    instrument_index: int,
    threshold: float,
    institution_ids: Sequence[str],
    instrument: str,
) -> CorrelatedUnwindExposure:
    absolute = np.abs(array)
    column = absolute[:, instrument_index]
    row_gross = absolute.sum(axis=1)
    signed_column = array[:, instrument_index]

    concentration = np.divide(
        column, row_gross, out=np.zeros_like(column), where=row_gross > 0
    )
    # A non-holder has concentration 0 and must never qualify, even at
    # threshold 0; the holder test is therefore explicit.
    qualifies = (column > 0.0) & (concentration >= threshold)

    exposure = float(column[qualifies].sum())
    instrument_gross = float(column.sum())
    system_gross = float(absolute.sum())
    long_exposure = float(signed_column[qualifies & (signed_column > 0.0)].sum())
    short_exposure = float(-signed_column[qualifies & (signed_column < 0.0)].sum())

    liquidating = tuple(
        sorted(
            institution_ids[i]
            for i in np.flatnonzero(qualifies)
        )
    )

    return CorrelatedUnwindExposure(
        instrument=instrument,
        concentration_threshold=float(threshold),
        exposure=exposure,
        fraction_of_instrument=(
            float(exposure / instrument_gross) if instrument_gross > 0.0 else 0.0
        ),
        fraction_of_system=(
            float(exposure / system_gross) if system_gross > 0.0 else 0.0
        ),
        n_liquidating=int(qualifies.sum()),
        liquidating_institutions=liquidating,
        long_exposure=long_exposure,
        short_exposure=short_exposure,
    )


def correlated_unwind_exposure(
    positions: PositionsLike,
    institution_ids: Sequence[str],
    instrument_ids: Sequence[str],
    *,
    instrument: str,
    concentration_threshold: float,
) -> CorrelatedUnwindExposure:
    """Correlated-unwind exposure for one named instrument.

    The threshold is a required keyword argument; the module never supplies a
    default, because any particular value is a convention rather than a
    definition. An institution qualifies when its absolute holding of the
    instrument is *at least* ``concentration_threshold`` of its own gross book.
    """
    array = _as_matrix(positions)
    inst_ids = _normalise_ids(institution_ids, array.shape[0], "institution_ids")
    instr_ids = _normalise_ids(instrument_ids, array.shape[1], "instrument_ids")
    if instrument not in instr_ids:
        raise ValueError(
            f"unknown instrument {instrument!r}; known instruments are {instr_ids}"
        )
    threshold = _validate_threshold(concentration_threshold)
    index = instr_ids.index(instrument)
    return _unwind_for_column(array, index, threshold, inst_ids, instrument)


def analyse_portfolio_overlap(
    positions: PositionsLike,
    institution_ids: Sequence[str],
    instrument_ids: Sequence[str],
    *,
    missing_policy: Union[MissingDataPolicy, str] = MissingDataPolicy.FAIL_CLOSED,
    concentration_threshold: Optional[float] = None,
) -> PortfolioOverlapResult:
    """Measure crowded-trade overlap across a holdings matrix.

    Args:
        positions: Holdings, institutions (rows) x instruments (columns).
            Position sizes are signed; a short is negative.
        institution_ids: Institution names, one per row.
        instrument_ids: Instrument names, one per column.
        missing_policy: How to treat NaN entries. Defaults to
            :attr:`MissingDataPolicy.FAIL_CLOSED`, which raises rather than
            guessing. Pass a value of :class:`MissingDataPolicy` (or its string
            value) to declare an exclusion explicitly.
        concentration_threshold: If supplied, correlated-unwind exposures are
            computed for every instrument at this threshold. ``None`` (the
            default) means not computed -- there is no invented default
            threshold.

    Raises:
        PortfolioOverlapDataError: NaN under the fail-closed policy, or an empty
            institution or instrument set after exclusions.
        ValueError: Malformed input -- non-2-D positions, infinite positions,
            mismatched or duplicate labels, or an out-of-range threshold.
    """
    policy = _coerce_policy(missing_policy)
    array = _as_matrix(positions, allow_missing=True)
    n_rows, n_cols = array.shape
    inst_ids = _normalise_ids(institution_ids, n_rows, "institution_ids")
    instr_ids = _normalise_ids(instrument_ids, n_cols, "instrument_ids")

    if n_rows == 0:
        raise PortfolioOverlapDataError(
            "a holdings matrix needs at least one institution",
            context={"n_institutions": 0, "n_instruments": n_cols},
        )
    if n_cols == 0:
        raise PortfolioOverlapDataError(
            "a holdings matrix needs at least one instrument",
            context={"n_institutions": n_rows, "n_instruments": 0},
        )

    missing = np.isnan(array)
    excluded_institutions: List[str] = []
    excluded_instruments: List[str] = []

    if missing.any():
        if policy is MissingDataPolicy.FAIL_CLOSED:
            bad_rows = [
                inst_ids[i] for i in np.flatnonzero(missing.any(axis=1))
            ]
            bad_cols = [
                instr_ids[j] for j in np.flatnonzero(missing.any(axis=0))
            ]
            raise PortfolioOverlapDataError(
                "holdings contain missing (NaN) values and the fail_closed "
                "policy refuses to impute them; declare an explicit exclusion "
                "policy if those institutions or instruments are to be dropped",
                context={
                    "missing_policy": policy.value,
                    "n_missing": int(missing.sum()),
                    "institutions_with_missing": bad_rows,
                    "instruments_with_missing": bad_cols,
                },
            )

        if policy in (
            MissingDataPolicy.EXCLUDE_INSTITUTIONS,
            MissingDataPolicy.EXCLUDE_BOTH,
        ):
            keep_rows = ~missing.any(axis=1)
            excluded_institutions = [
                inst_ids[i] for i in np.flatnonzero(~keep_rows)
            ]
            array = array[keep_rows]
            inst_ids = [inst_ids[i] for i in np.flatnonzero(keep_rows)]

        if policy in (
            MissingDataPolicy.EXCLUDE_INSTRUMENTS,
            MissingDataPolicy.EXCLUDE_BOTH,
        ):
            # Both masks are judged on the original matrix. Dropping bad rows
            # cannot rescue a column (every NaN sits in some bad row), so a
            # column re-check after the row drop would be a silent no-op; the
            # union of the two axes is what "exclude both" means here.
            keep_cols = ~missing.any(axis=0)
            excluded_instruments = [
                instr_ids[j] for j in np.flatnonzero(~keep_cols)
            ]
            array = array[:, keep_cols]
            instr_ids = [instr_ids[j] for j in np.flatnonzero(keep_cols)]

    if len(inst_ids) == 0:
        raise PortfolioOverlapDataError(
            "no institutions remain after applying the missing-data policy",
            context={
                "missing_policy": policy.value,
                "excluded_institutions": excluded_institutions,
                "excluded_instruments": excluded_instruments,
            },
        )
    if len(instr_ids) == 0:
        raise PortfolioOverlapDataError(
            "no instruments remain after applying the missing-data policy",
            context={
                "missing_policy": policy.value,
                "excluded_institutions": excluded_institutions,
                "excluded_instruments": excluded_instruments,
            },
        )

    array = np.array(array, dtype=float, copy=True)

    crowding = instrument_crowding(array, instr_ids)
    score = system_crowding_score(crowding, len(inst_ids))

    unwind: Dict[str, CorrelatedUnwindExposure] = {}
    if concentration_threshold is not None:
        threshold = _validate_threshold(concentration_threshold)
        for index, name in enumerate(instr_ids):
            unwind[name] = _unwind_for_column(
                array, index, threshold, inst_ids, name
            )

    return PortfolioOverlapResult(
        positions=array,
        institution_ids=list(inst_ids),
        instrument_ids=list(instr_ids),
        cosine_overlap=signed_cosine_overlap(array),
        jaccard_name_overlap=jaccard_name_overlap(array),
        jaccard_directional_overlap=jaccard_directional_overlap(array),
        instrument_crowding=crowding,
        system_crowding=score,
        unwind_exposures=unwind,
        missing_policy=policy,
        excluded_institutions=excluded_institutions,
        excluded_instruments=excluded_instruments,
    )
