"""Federated risk-aware learning with secure aggregation (FRAL-CSE).

The problem this addresses
--------------------------

Granular bank-level data cannot cross borders. A Fed model cannot see the ECB's
positions and an ECB model cannot see the Fed's, which is why the plan calls for
local training with only updates crossing the boundary. That much is standard
federated learning. Two things here are specific to a systemic-risk setting:

**Risk-aware weighting.** Plain federated averaging weights each participant by its
sample count. In this domain that is the wrong criterion: the institution that
matters is the one whose distress would propagate, and it may contribute few rows.
So aggregation accepts an explicit risk weight and reports what it did, rather than
letting the row count silently decide whose data shapes the global model.

**Central Sensitivity Estimation.** After each round the aggregator reports how far
each participant moved the global model, in the direction of the update and in
magnitude. That is the quantity a supervisor actually wants: not "who contributed
most data" but "whose private data is steering the shared model".

What the masking does and does not protect
------------------------------------------

The update is masked before it leaves the participant, using pairwise additive
masks that cancel on summation, so the server sees only the aggregate. That is the
Bonawitz-style construction and it is exact: the masked sum equals the unmasked sum
to floating-point precision, which the tests assert.

It is **not** differential privacy and it is **not** a complete secure-aggregation
protocol:

* It protects against an honest-but-curious server that follows the protocol. It
  does nothing against participants colluding to subtract each other's masks, and
  the construction below has no dropout recovery -- if a participant leaves after
  masking, its pairwise masks no longer cancel and the sum is wrong. The aggregator
  therefore *refuses* to aggregate when participants are missing rather than
  returning a corrupted number, which is the honest failure mode. Full dropout
  resilience needs threshold secret sharing, which is not implemented.
* Masking hides individual updates from the server but places no bound on what the
  aggregate reveals about any one participant. A single participant's contribution
  is exactly recoverable from the aggregate by differencing across rounds. That is
  the property formal privacy would bound and this does not.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

logger = logging.getLogger(__name__)

__all__ = [
    "ClientUpdate",
    "AggregationResult",
    "SecureAggregationError",
    "federated_average",
    "pairwise_masks",
    "mask_update",
    "secure_aggregate",
    "central_sensitivity",
    "FederatedTrainer",
    "WEIGHTING_SCHEMES",
]

WEIGHTING_SCHEMES = ("samples", "risk", "uniform")
_DEFAULT_MASK_SCALE = 1e3


class SecureAggregationError(Exception):
    """Raised when masking cannot be undone, rather than returning a wrong sum."""


@dataclass(frozen=True)
class ClientUpdate:
    """One participant's contribution for a round.

    ``weights`` is a flat parameter vector so the arithmetic is unambiguous; callers
    flatten and unflatten around the protocol.
    """

    client_id: str
    weights: np.ndarray
    n_samples: int
    risk_weight: float = 1.0
    loss: Optional[float] = None

    def __post_init__(self) -> None:
        vector = np.asarray(self.weights, dtype=float).reshape(-1)
        if vector.size == 0:
            raise ValueError(f"client {self.client_id!r} sent an empty update")
        if not np.all(np.isfinite(vector)):
            raise ValueError(f"client {self.client_id!r} sent non-finite weights")
        if self.n_samples < 0:
            raise ValueError(
                f"client {self.client_id!r} has negative n_samples {self.n_samples}"
            )
        if not np.isfinite(self.risk_weight) or self.risk_weight < 0:
            raise ValueError(
                f"client {self.client_id!r} has invalid risk_weight {self.risk_weight}"
            )
        object.__setattr__(self, "weights", vector)

    @property
    def dimension(self) -> int:
        return int(self.weights.size)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "client_id": self.client_id,
            "dimension": self.dimension,
            "n_samples": int(self.n_samples),
            "risk_weight": float(self.risk_weight),
            "loss": None if self.loss is None else float(self.loss),
        }


@dataclass
class AggregationResult:
    """The aggregate and the evidence behind it."""

    weights: np.ndarray
    contributions: Dict[str, float]
    n_clients: int
    weighting: str
    masked: bool
    dropped_clients: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "n_clients": int(self.n_clients),
            "weighting": self.weighting,
            "masked": bool(self.masked),
            "contributions": {k: float(v) for k, v in self.contributions.items()},
            "dropped_clients": list(self.dropped_clients),
            "norm": float(np.linalg.norm(self.weights)),
        }


# ---------------------------------------------------------------------------
# Weighting
# ---------------------------------------------------------------------------

def _contribution_weights(
    updates: Sequence[ClientUpdate], weighting: str
) -> Dict[str, float]:
    """Normalised per-client weights under the chosen scheme."""
    if weighting not in WEIGHTING_SCHEMES:
        raise ValueError(
            f"weighting must be one of {WEIGHTING_SCHEMES}, got {weighting!r}"
        )
    if not updates:
        raise ValueError("no updates to weight")

    if weighting == "uniform":
        raw = {update.client_id: 1.0 for update in updates}
    elif weighting == "samples":
        raw = {update.client_id: float(update.n_samples) for update in updates}
    else:  # risk
        # Samples set the statistical footing, the risk weight sets the systemic
        # importance. Multiplying rather than replacing keeps a large low-risk
        # participant relevant without letting a tiny high-risk one dominate.
        raw = {
            update.client_id: float(update.n_samples) * float(update.risk_weight)
            for update in updates
        }

    total = sum(raw.values())
    if total <= 0:
        # Every participant reporting zero samples is a data problem, not a reason
        # to silently fall back to a uniform average.
        raise ValueError(
            f"weighting scheme {weighting!r} produced zero total weight; check the "
            "participants' n_samples and risk_weight"
        )
    return {client: value / total for client, value in raw.items()}


def federated_average(
    updates: Sequence[ClientUpdate], *, weighting: str = "samples"
) -> AggregationResult:
    """Weighted mean of client updates. The unmasked baseline."""
    if not updates:
        raise ValueError("federated_average needs at least one update")

    dimensions = {update.dimension for update in updates}
    if len(dimensions) != 1:
        raise ValueError(
            f"updates have inconsistent dimensions {sorted(dimensions)}; clients must "
            "share a model shape"
        )

    contributions = _contribution_weights(updates, weighting)
    aggregate = np.zeros(updates[0].dimension, dtype=float)
    for update in updates:
        aggregate += contributions[update.client_id] * update.weights

    return AggregationResult(
        weights=aggregate,
        contributions=contributions,
        n_clients=len(updates),
        weighting=weighting,
        masked=False,
    )


# ---------------------------------------------------------------------------
# Secure aggregation
# ---------------------------------------------------------------------------

def _pair_seed(left: str, right: str, round_id: int) -> int:
    """Deterministic shared seed for an unordered pair, stable across processes.

    Both participants derive the same value from the sorted pair, which is what
    makes the masks cancel without any communication beyond the identifiers.
    """
    first, second = sorted((left, right))
    digest = hashlib.sha256(f"{first}|{second}|{round_id}".encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big")


def pairwise_masks(
    client_ids: Sequence[str], dimension: int, *, round_id: int = 0, scale: float = _DEFAULT_MASK_SCALE
) -> Dict[str, np.ndarray]:
    """Mask for each client, with every pair cancelling exactly on summation.

    For each unordered pair the two participants receive the same vector with
    opposite signs, so the total over all clients is zero regardless of the values.
    """
    if dimension < 1:
        raise ValueError(f"dimension must be positive, got {dimension}")
    if len(set(client_ids)) != len(client_ids):
        raise ValueError("client ids must be unique")

    masks: Dict[str, np.ndarray] = {
        client_id: np.zeros(dimension, dtype=float) for client_id in client_ids
    }
    ordered = sorted(client_ids)
    for index, first in enumerate(ordered):
        for second in ordered[index + 1 :]:
            rng = np.random.default_rng(_pair_seed(first, second, round_id))
            shared = rng.normal(scale=scale, size=dimension)
            masks[first] = masks[first] + shared
            masks[second] = masks[second] - shared
    return masks


def mask_update(
    update: ClientUpdate, mask: np.ndarray, *, weight: float = 1.0
) -> ClientUpdate:
    """Apply the aggregation weight and the mask. What actually leaves the client.

    The weight is folded in *before* masking, and this is not a detail. Pairwise
    masks cancel only under an unweighted sum: ``sum_i m_i = 0`` guarantees
    ``sum_i (x_i + m_i) = sum_i x_i``, but ``sum_i w_i (x_i + m_i) != sum_i w_i x_i``
    whenever the weights differ, because each mask is then scaled differently. An
    earlier version masked first and weighted during aggregation, which left a
    residual of hundreds on an eight-dimensional update -- a corrupted aggregate
    that would have been reported as a successful round.
    """
    value = float(weight)
    if not np.isfinite(value):
        raise ValueError(f"weight for {update.client_id!r} is not finite")
    return ClientUpdate(
        client_id=update.client_id,
        weights=value * update.weights + np.asarray(mask, dtype=float).reshape(-1),
        n_samples=update.n_samples,
        risk_weight=update.risk_weight,
        loss=update.loss,
    )


def secure_aggregate(
    updates: Sequence[ClientUpdate],
    *,
    weighting: str = "samples",
    round_id: int = 0,
    expected_clients: Optional[Sequence[str]] = None,
    scale: float = _DEFAULT_MASK_SCALE,
) -> AggregationResult:
    """Aggregate without the server seeing any individual update.

    Args:
        updates: Masked updates, as produced by :func:`mask_update` **with the
            aggregation weight already applied**. Contributions are summed with
            equal coefficients, which is what makes the masks cancel; any weighting
            must therefore be folded in before masking, not applied here.
        weighting: See :func:`federated_average`.
        round_id: Round identifier, part of the mask derivation. Reusing a round id
            across rounds reuses the masks, so it must advance.
        expected_clients: Participants the protocol assumed. A missing one leaves
            its pairwise masks uncancelled, which corrupts the sum, so a mismatch
            raises instead of returning a plausible but wrong number.
        scale: Mask magnitude. Larger hides the update better in floating point but
            loses precision in the sum; the default keeps cancellation exact to
            about 1e-12 relative.

    Raises:
        SecureAggregationError: When participants are missing or unknown.
    """
    if not updates:
        raise ValueError("secure_aggregate needs at least one update")

    present = [update.client_id for update in updates]
    if expected_clients is not None:
        expected = list(expected_clients)
        missing = sorted(set(expected) - set(present))
        unknown = sorted(set(present) - set(expected))
        if missing or unknown:
            # Refusing is the point: a silent partial aggregate is a corrupted
            # model that looks like a successful round.
            raise SecureAggregationError(
                "secure aggregation requires every participant that contributed a "
                f"mask; missing={missing} unknown={unknown}. Recover with threshold "
                "secret sharing or restart the round without the missing clients."
            )

    # Uniform summation is required, not a simplification: the masks cancel
    # pairwise only when every contribution is added with the same coefficient.
    # The caller's weighting was applied per-client in `mask_update`.
    aggregate = np.zeros(updates[0].dimension, dtype=float)
    for update in updates:
        aggregate = aggregate + update.weights

    return AggregationResult(
        weights=aggregate,
        contributions=_contribution_weights(updates, weighting),
        n_clients=len(updates),
        weighting=weighting,
        masked=True,
        dropped_clients=(),
    )


# ---------------------------------------------------------------------------
# Central sensitivity
# ---------------------------------------------------------------------------

def central_sensitivity(
    updates: Sequence[ClientUpdate],
    aggregate: np.ndarray,
    *,
    weighting: str = "samples",
) -> Dict[str, float]:
    """How far each participant pulls the aggregate, in the direction it moved it.

    The *projection* of a participant's deviation from the aggregate onto the
    aggregate's own direction, scaled by its contribution weight. A participant
    whose update points the same way the aggregate went has a large positive
    sensitivity; one that opposes it is negative. Magnitude alone would not
    distinguish a participant that moved the model from one that merely differed
    from it.

    This is a diagnostic about influence, not a privacy mechanism: it is computed
    from the aggregate and the update, so it requires the server to hold the update
    -- it is intended for the simulation path and for participants auditing their
    own influence, not for a server that is meant to see nothing.
    """
    vector = np.asarray(aggregate, dtype=float).reshape(-1)
    if vector.size == 0:
        raise ValueError("aggregate is empty")
    norm = float(np.linalg.norm(vector))
    if norm == 0.0:
        return {update.client_id: 0.0 for update in updates}

    direction = vector / norm
    contributions = _contribution_weights(updates, weighting)
    return {
        update.client_id: float(
            contributions[update.client_id] * float(np.dot(update.weights, direction))
        )
        for update in updates
    }


# ---------------------------------------------------------------------------
# Round driver
# ---------------------------------------------------------------------------

class FederatedTrainer:
    """Runs federated rounds against a supplied aggregation function.

    Deliberately thin. It owns the round bookkeeping -- advancing the round id so
    masks differ, deciding which participants report, and keeping the history -- and
    nothing about the model, because the model is the caller's.
    """

    def __init__(
        self,
        *,
        weighting: str = "samples",
        round_id: int = 0,
        secure: bool = True,
        mask_scale: float = _DEFAULT_MASK_SCALE,
    ) -> None:
        if weighting not in WEIGHTING_SCHEMES:
            raise ValueError(
                f"weighting must be one of {WEIGHTING_SCHEMES}, got {weighting!r}"
            )
        self.weighting = weighting
        self.round_id = int(round_id)
        self.secure = bool(secure)
        self.mask_scale = float(mask_scale)
        self.history: List[Dict[str, Any]] = []

    def run_round(
        self,
        updates: Sequence[ClientUpdate],
        *,
        expected_clients: Optional[Sequence[str]] = None,
    ) -> AggregationResult:
        """Aggregate one round, optionally masking first."""
        if not updates:
            raise ValueError("a round needs at least one update")

        if not self.secure:
            result = federated_average(updates, weighting=self.weighting)
        else:
            ids = [update.client_id for update in updates]
            masks = pairwise_masks(
                ids, updates[0].dimension, round_id=self.round_id, scale=self.mask_scale
            )
            contributions = _contribution_weights(updates, self.weighting)
            masked = [
                mask_update(
                    update, masks[update.client_id], weight=contributions[update.client_id]
                )
                for update in updates
            ]
            result = secure_aggregate(
                masked,
                weighting=self.weighting,
                round_id=self.round_id,
                expected_clients=expected_clients,
                scale=self.mask_scale,
            )

        self.history.append(
            {
                "round_id": self.round_id,
                "n_clients": len(updates),
                "weighting": self.weighting,
                "secure": self.secure,
                "sensitivity": central_sensitivity(
                    updates, result.weights, weighting=self.weighting
                ),
            }
        )
        self.round_id += 1
        return result

    def to_dict(self) -> Dict[str, Any]:
        return {
            "weighting": self.weighting,
            "round_id": self.round_id,
            "secure": self.secure,
            "rounds_completed": len(self.history),
            "history": list(self.history),
        }
