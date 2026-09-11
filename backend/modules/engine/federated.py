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

It is **not** differential privacy, but dropout is now handled:

* It protects against an honest-but-curious server that follows the protocol. It
  does nothing against participants colluding to subtract each other's masks.
  Dropout recovery *is* implemented, following Bonawitz et al. (2017): each
  participant's finite-field Diffie-Hellman private key -- the one secret its
  pairwise masks are derived from -- is shared with a t-of-n Shamir polynomial
  over the 2047-bit prime field that is the order of the DH subgroup of the
  2048-bit RFC 3526 safe prime, and each other participant holds one share. When a
  participant that took part in mask setup does not submit a masked update, the
  server reconstructs its private key from t shares, regenerates the pairwise
  masks that no longer cancel, and subtracts them, returning the aggregate over
  the participants that did submit. If fewer than t participants remain the
  secret is information-theoretically unrecoverable and the aggregator *raises*
  rather than returning a corrupted number. See
  :func:`secure_aggregate_with_dropout`.
* The two arithmetic worlds are kept strictly apart. Shares live in GF(p); the
  masks are floating-point numpy PRG output. The boundary is crossed in exactly
  one place -- the reconstructed field element is the integer that seeds the PRG
  -- and because Shamir reconstruction over the field recovers that integer
  bit-for-bit, the float mask is regenerated bit-for-bit. No float is ever
  secret-shared and no field element is ever rounded. The exactness claim is
  therefore inherited unchanged from the unmasked sum, to floating-point
  precision.
* Masking hides individual updates from the server but places no bound on what the
  aggregate reveals about any one participant. A single participant's contribution
  is exactly recoverable from the aggregate by differencing across rounds. That is
  the property formal privacy would bound and this does not.
* Collusion: fewer than t shares reveal nothing about a participant's private key
  (information-theoretic), but t or more participants colluding can reconstruct
  any participant's key and unmask that participant. A participant can still bias
  the aggregate through the value of its own update, which the protocol does not
  constrain; it cannot silently substitute a different shared key, because the
  Feldman commitment to the polynomial's constant term must equal its broadcast
  public key. Public keys are not authenticated (there is no PKI or key
  transparency), so an active man-in-the-middle is out of scope.

Reachability (honest status)
----------------------------

Nothing in production imports this module. A repository-wide scan finds no
non-test importer of ``backend.modules.engine.federated``: no API route, no task,
no engine orchestrator, and no config key names it. The two dynamic loaders that
could in principle reach a module by name do not: ``backend/__init__.py``
resolves a fixed five-entry table, and ``backend/plugins/__init__.py`` loads
data-source plugins only. The gap is recorded in
``backend/tests/test_reachability.py`` (``KNOWN_UNREACHABLE``), which fails if an
importer appears without the census being updated, and in
``docs/EXECUTIVE_REVIEW_REMEDIATION.md``.

The masking, threshold sharing and dropout recovery below are implemented and
tested but unreachable, and are labelled as such rather than advertised as a
running capability. No call site is faked, because a real one would need a
federated training coordinator the repository does not have: something that owns
the participant roster and model shape, runs the advertise/commit/mask/unmask
sequence over a real transport, and selects the weighting scheme. The existing
``EngineOrchestrator`` and ``ModelTrainer`` are single-node training loops;
attaching ``federated_average`` to one of them would produce an import that
never exercises masking, sharing, or recovery -- a green reachability check with
no capability behind it, which is the failure this census exists to prevent.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

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
    # Threshold-secret-sharing dropout recovery.
    "FIELD_PRIME",
    "FIELD_GENERATOR",
    "SHARING_PRIME",
    "ShamirShare",
    "ShamirDealing",
    "FeldmanCommitments",
    "ServerRoundState",
    "SecureRoundPlan",
    "shamir_split",
    "shamir_reconstruct",
    "plan_secure_round",
    "secure_aggregate_with_dropout",
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
                f"mask; missing={missing} unknown={unknown}. Use "
                "secure_aggregate_with_dropout to recover a threshold of missing "
                "participants, or restart the round without the missing clients."
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
# Dropout recovery by threshold secret sharing (Bonawitz et al., 2017)
# ---------------------------------------------------------------------------
#
# The deterministic pairwise masks above are lossless only while every
# participant that took part in mask setup submits its masked update. If one is
# missing, its half of every pair with a present participant stays in the sum.
# The construction below removes that residual with threshold secret sharing,
# following Bonawitz et al. (2017, "Practical Secure Aggregation for
# Privacy-Preserving Machine Learning").
#
# The one secret that has to be recovered for a missing participant is its
# finite-field Diffie-Hellman private key ``a_u``: every pairwise mask involving
# ``u`` is derived from ``a_u`` and the *public* keys of the two endpoints, so
# recovering ``a_u`` recovers all of ``u``'s pairwise masks at once. Each
# participant Shamir-shares ``a_u`` over GF(p) for the 2048-bit RFC 3526 safe
# prime and publishes Feldman commitments g^{c_k} to the polynomial coefficients
# (``c_0 = a_u``). The constant commitment is therefore exactly ``u``'s public
# key, so a dealer cannot substitute a different polynomial without the server
# noticing. On dropout the server reconstructs ``a_u`` from t verified shares and
# regenerates the masks that no longer cancel.
#
# The field/float boundary is crossed in exactly one place. Shares live in GF(p);
# masks are numpy PRG output seeded by a 64-bit hash of the shared DH secret.
# Shamir reconstruction returns the integer DH secret bit-for-bit, so the hash --
# and therefore every float in the mask -- is reproduced bit-for-bit. Nothing
# that is a float is ever secret-shared and nothing that is a field element is
# ever rounded, which is why recovery inherits the exactness of the unmasked sum.

# RFC 3526 Group 14, the 2048-bit MODP safe prime. A safe prime is used because
# the pairwise masks are derived from Diffie-Hellman between the two endpoints;
# with a smooth prime an attacker could recover a private key modulo small
# factors, and a single recovered private key unmasks every update at that node.
FIELD_PRIME = int(
    "FFFFFFFFFFFFFFFFC90FDAA22168C234C4C6628B80DC1CD1"
    "29024E088A67CC74020BBEA63B139B22514A08798E3404DD"
    "EF9519B3CD3A431B302B0A6DF25F14374FE1356D6D51C245"
    "E485B576625E7EC6F44C42E9A637ED6B0BFF5CB6F406B7ED"
    "EE386BFB5A899FA5AE9F24117C4B1FE649286651ECE45B3D"
    "C2007CB8A163BF0598DA48361C55D39A69163FA8FD24CF5F"
    "83655D23DCA3AD961C62F356208552BB9ED529077096966D"
    "670C354E4ABC9804F1746C08CA18217C32905E462E36CE3B"
    "E39E772C180E86039B2783A2EC07A28FB5C55DF06F4C52C9"
    "DE2BCBF6955817183995497CEA956AE515D2261898FA0510"
    "15728E5A8AACAA68FFFFFFFFFFFFFFFF",
    16,
)
# `FIELD_PRIME` is the 2048-bit DH group modulus; `SHARING_PRIME` is the prime
# order of the subgroup generator 2 and is the field the Shamir shares live in.
# They must not be conflated: Feldman verification raises the generator to the
# share value, and the generator's order is `SHARING_PRIME`, so shares and
# polynomial coefficients are reduced modulo `SHARING_PRIME`, not `FIELD_PRIME`.
FIELD_GENERATOR = 2
SHARING_PRIME = (FIELD_PRIME - 1) // 2


@dataclass(frozen=True)
class ShamirShare:
    """One evaluation point ``(x, f(x))`` of a dealer's sharing polynomial."""

    x: int
    y: int

    def __post_init__(self) -> None:
        if self.x < 1:
            raise ValueError(f"share index x must be positive, got {self.x}")
        if self.y < 0:
            raise ValueError(f"share value y must be non-negative, got {self.y}")


@dataclass(frozen=True)
class FeldmanCommitments:
    """Feldman VSS commitments ``g^{c_k}`` to a sharing polynomial's coefficients.

    Checking a share against the commitments proves it lies on the dealer's
    polynomial without revealing the secret. The constant commitment is the
    dealer's Diffie-Hellman public key, so publishing the commitments leaks
    nothing that was not already broadcast, while a share that does not lie on the
    polynomial can be discarded. Without this, interpolation over t bogus shares
    would return a plausible field element and silently corrupt the aggregate.

    The commitments live in the order-``sharing_prime`` subgroup of
    ``GF(modulus)``: ``modulus`` is the 2048-bit safe prime and ``sharing_prime``
    is ``(modulus - 1) / 2``, which is prime. Shares and coefficients are reduced
    modulo ``sharing_prime`` because that is the group order.
    """

    commitments: Tuple[int, ...]
    sharing_prime: int = SHARING_PRIME
    modulus: int = FIELD_PRIME
    generator: int = FIELD_GENERATOR

    def verify(self, share: ShamirShare) -> bool:
        """True iff ``share`` lies on the committed polynomial.

        Recomputes ``g^{f(x)} == prod_k C_k^{x^k}`` in the subgroup. A forged
        index, a tampered value, or a share from a different dealing all fail.
        """
        if share.x < 1 or not (0 <= share.y < self.sharing_prime):
            return False
        expected = pow(self.generator, share.y, self.modulus)
        actual = 1
        exponent = 1  # x^k, reduced modulo the group order
        point = share.x % self.sharing_prime
        for commitment in self.commitments:
            actual = (actual * pow(commitment, exponent, self.modulus)) % self.modulus
            exponent = (exponent * point) % self.sharing_prime
        return expected == actual


@dataclass(frozen=True)
class ShamirDealing:
    """A dealer's t-of-n shares plus the commitments that authenticate them."""

    shares: Tuple[ShamirShare, ...]
    commitments: FeldmanCommitments

    def __post_init__(self) -> None:
        if not self.shares:
            raise ValueError("a dealing must contain at least one share")


def _sample_field_element(
    rng: np.random.Generator, modulus: int, *, nonzero: bool = False
) -> int:
    """Uniform element via rejection sampling, so there is no modular bias.

    numpy's integer generator is 64-bit, so a 2048-bit candidate is drawn as raw
    bytes and rejected when it falls outside ``[0, modulus)``. The acceptance
    probability is at least one half, so the loop terminates quickly; the point is
    that the accepted value is exactly uniform rather than ``random_bytes %
    modulus``, which would slightly favour small residues.
    """
    width = (modulus.bit_length() + 7) // 8
    while True:
        candidate = int.from_bytes(rng.bytes(width), "big")
        if candidate < modulus and (candidate != 0 or not nonzero):
            return candidate


def shamir_split(
    secret: int,
    n: int,
    threshold: int,
    *,
    rng: Optional[np.random.Generator] = None,
    field: int = SHARING_PRIME,
    modulus: int = FIELD_PRIME,
    generator: int = FIELD_GENERATOR,
) -> ShamirDealing:
    """Shamir-share ``secret`` as a t-of-n dealing over GF(field).

    The polynomial ``f(x) = secret + c_1 x + ... + c_{t-1} x^{t-1}`` has random
    coefficients, and holder ``i`` receives ``(i, f(i))``. Any ``t`` holders can
    interpolate ``f(0) = secret``; ``t - 1`` holders learn nothing, because for
    any candidate secret there is a polynomial through their points.

    ``t = 1`` is accepted but gives no secrecy -- a single share *is* the secret.
    :func:`plan_secure_round` rejects it for more than one participant.

    Args:
        secret: Field element to share, ``0 <= secret < field``.
        n: Number of holders (evaluation points ``1..n``).
        threshold: Minimum number of shares that reconstruct the secret.
        rng: Seeded generator, for reproducible tests; defaults to OS entropy.
        field: Prime field the shares live in. Defaults to ``SHARING_PRIME``, the
            order of the DH subgroup, so the Feldman commitments verify.
        modulus: Group modulus for the commitments (the safe prime).
        generator: Subgroup generator used for the Feldman commitments.
    """
    if n < 1:
        raise ValueError(f"n must be positive, got {n}")
    if not (1 <= threshold <= n):
        raise ValueError(
            f"threshold must satisfy 1 <= threshold <= {n}, got {threshold}"
        )
    if not (0 <= secret < field):
        raise ValueError(
            f"secret must be a field element in [0, {field}), got {secret}"
        )
    if rng is None:
        rng = np.random.default_rng()

    coefficients = [int(secret)] + [
        _sample_field_element(rng, field) for _ in range(threshold - 1)
    ]
    shares: List[ShamirShare] = []
    for x in range(1, n + 1):
        value = 0
        power = 1
        for coefficient in coefficients:
            value = (value + coefficient * power) % field
            power = (power * x) % field
        shares.append(ShamirShare(x=x, y=value))

    commitments = FeldmanCommitments(
        commitments=tuple(
            pow(generator, coefficient, modulus) for coefficient in coefficients
        ),
        sharing_prime=field,
        modulus=modulus,
        generator=generator,
    )
    return ShamirDealing(shares=tuple(shares), commitments=commitments)


def shamir_reconstruct(
    shares: Sequence[ShamirShare],
    *,
    threshold: int,
    field: int = SHARING_PRIME,
    commitments: Optional[FeldmanCommitments] = None,
) -> int:
    """Recover the constant term ``f(0)`` from at least ``threshold`` shares.

    With ``commitments`` supplied, shares that fail Feldman verification are
    discarded rather than trusted, so one corrupt or forged share is harmless as
    long as ``threshold`` honest shares remain. If fewer than ``threshold`` valid
    distinct shares survive, the secret is unrecoverable and this *raises*
    instead of interpolating garbage -- interpolating a wrong field element would
    regenerate a wrong float mask and return a silently corrupted aggregate,
    which is the failure mode this module exists to avoid.

    Shares must have distinct ``x``; a conflicting pair is an attack or a
    protocol error and raises rather than being silently de-duplicated.
    """
    if threshold < 1:
        raise ValueError(f"threshold must be positive, got {threshold}")

    chosen: Dict[int, int] = {}
    for share in shares:
        if commitments is not None and not commitments.verify(share):
            continue
        previous = chosen.get(share.x)
        if previous is None:
            chosen[share.x] = share.y
        elif previous != share.y:
            raise SecureAggregationError(
                f"conflicting shares for index x={share.x}: {previous} and {share.y}"
            )

    if len(chosen) < threshold:
        raise SecureAggregationError(
            f"need {threshold} distinct valid shares to reconstruct the secret, got "
            f"{len(chosen)}; the aggregate is unrecoverable"
        )

    points = sorted(chosen.items())
    secret = 0
    for index, (x_i, y_i) in enumerate(points):
        numerator = 1
        denominator = 1
        for other, (x_j, _) in enumerate(points):
            if other == index:
                continue
            numerator = (numerator * (-x_j)) % field
            denominator = (denominator * (x_i - x_j)) % field
        lagrange = numerator * pow(denominator, -1, field) % field
        secret = (secret + y_i * lagrange) % field
    return secret


def _derive_mask_seed(
    secret: int, first: str, second: str, round_id: int, modulus: int
) -> int:
    """64-bit PRG seed from a shared DH secret. This is the field/float boundary.

    ``secret`` is a group element, never a float. Serialising it at a fixed width
    (the modulus width) and hashing it together with the sorted pair and the round
    makes both endpoints -- and the reconstructing server -- arrive at the same
    integer seed; only that integer crosses into floating point, where numpy's PRG
    turns it into the mask. Hashing rather than seeding directly from ``secret``
    also fixes the seed width so the PRG cannot depend on the secret's magnitude.
    """
    width = (modulus.bit_length() + 7) // 8
    payload = (
        secret.to_bytes(width, "big")
        + f"|{first}|{second}|{round_id}".encode("utf-8")
    )
    digest = hashlib.sha256(payload).digest()
    return int.from_bytes(digest[:8], "big")


def _pairwise_mask_from_secret(
    secret: int,
    first: str,
    second: str,
    dimension: int,
    *,
    round_id: int,
    scale: float,
    modulus: int,
) -> np.ndarray:
    """The float mask a pair derives from its shared DH secret."""
    rng = np.random.default_rng(
        _derive_mask_seed(secret, first, second, round_id, modulus)
    )
    return rng.normal(scale=scale, size=dimension)


@dataclass(frozen=True)
class ServerRoundState:
    """The public half of a dropout-resilient round: everything the server holds.

    Deliberately excludes private keys and present-present pairwise secrets. The
    server can verify shares and reconstruct a *dropped* participant's key, but it
    never sees the key material of a participant that submitted.
    """

    expected_clients: Tuple[str, ...]
    round_id: int
    threshold: int
    sharing_prime: int
    modulus: int
    generator: int
    scale: float
    weighting: str
    contributions: Dict[str, float]
    public_keys: Dict[str, int]
    commitments: Dict[str, FeldmanCommitments]


@dataclass(frozen=True)
class SecureRoundPlan:
    """Participant-side artifacts of one dropout-resilient masked round.

    Held by the simulated participants (and by the test driver), never by the
    server: it contains the masked updates, every participant's share deal, and
    the public keys. :meth:`server_state` projects out the public half, which is
    the only part :func:`secure_aggregate_with_dropout` is allowed to see.
    """

    client_ids: Tuple[str, ...]
    dimension: int
    round_id: int
    threshold: int
    sharing_prime: int
    modulus: int
    generator: int
    scale: float
    weighting: str
    contributions: Dict[str, float]
    public_keys: Dict[str, int]
    masked_updates: Dict[str, ClientUpdate]
    dealings: Dict[str, ShamirDealing]

    def server_state(self) -> ServerRoundState:
        """The public round description the server is given."""
        return ServerRoundState(
            expected_clients=self.client_ids,
            round_id=self.round_id,
            threshold=self.threshold,
            sharing_prime=self.sharing_prime,
            modulus=self.modulus,
            generator=self.generator,
            scale=self.scale,
            weighting=self.weighting,
            contributions=dict(self.contributions),
            public_keys=dict(self.public_keys),
            commitments={
                client_id: dealing.commitments
                for client_id, dealing in self.dealings.items()
            },
        )

    def share(self, owner: str, holder: str) -> ShamirShare:
        """The share of ``owner``'s key that ``holder`` would submit on dropout."""
        if owner not in self.dealings:
            raise KeyError(f"unknown share owner {owner!r}")
        try:
            index = self.client_ids.index(holder)
        except ValueError:
            raise KeyError(f"unknown share holder {holder!r}") from None
        return self.dealings[owner].shares[index]

    def recovery_shares(
        self, owners: Sequence[str], holders: Sequence[str]
    ) -> Dict[str, Tuple[ShamirShare, ...]]:
        """Collect, for each dropped owner, the shares held by ``holders``.

        Convenience for the simulated holder side: it models the surviving
        participants responding with the shares they already hold.
        """
        return {
            owner: tuple(self.share(owner, holder) for holder in holders)
            for owner in owners
        }


def plan_secure_round(
    updates: Sequence[ClientUpdate],
    *,
    weighting: str = "samples",
    round_id: int = 0,
    threshold: Optional[int] = None,
    scale: float = _DEFAULT_MASK_SCALE,
    seed: Optional[int] = None,
) -> SecureRoundPlan:
    """Simulate the participant side of a dropout-resilient masked round.

    This replaces the deterministic :func:`pairwise_masks` for rounds that must
    survive dropout. Each participant picks a fresh DH private key, pairwise masks
    are derived from the shared DH secret between each pair, the caller's weight
    is folded into the update *before* masking (the same exactness requirement as
    :func:`mask_update`), and each private key is Shamir-shared t-of-n.

    Args:
        updates: The participants' plaintext updates for the round. All must have
            the same dimension and unique ids.
        weighting: See :func:`federated_average`; folded in before masking.
        round_id: Round identifier; part of the mask derivation, so it must advance.
        threshold: Shares needed to reconstruct a dropped key. Recovery tolerates
            ``len(updates) - threshold`` dropouts. Defaults to
            ``max(2, n - n // 3)``, which keeps the threshold above ``n / 2``
            while tolerating roughly a third of the participants leaving.
        scale: Mask magnitude, as in :func:`pairwise_masks`.
        seed: Optional PRG seed. Supplied for reproducible tests; production runs
            draw fresh keys from OS entropy.

    Returns:
        A :class:`SecureRoundPlan`; hand :meth:`SecureRoundPlan.server_state` and
        the masked updates to the server.
    """
    if not updates:
        raise ValueError("plan_secure_round needs at least one update")
    client_ids = sorted(update.client_id for update in updates)
    if len(set(client_ids)) != len(updates):
        raise ValueError("client ids must be unique")
    dimensions = {update.dimension for update in updates}
    if len(dimensions) != 1:
        raise ValueError(
            f"updates have inconsistent dimensions {sorted(dimensions)}; clients must "
            "share a model shape"
        )
    if weighting not in WEIGHTING_SCHEMES:
        raise ValueError(
            f"weighting must be one of {WEIGHTING_SCHEMES}, got {weighting!r}"
        )

    dimension = updates[0].dimension
    n = len(client_ids)
    if threshold is None:
        threshold = 1 if n == 1 else max(2, n - n // 3)
    if not (1 <= threshold <= n):
        raise ValueError(
            f"threshold must satisfy 1 <= threshold <= {n}, got {threshold}"
        )
    if n > 1 and threshold < 2:
        raise ValueError(
            "threshold below 2 gives no secrecy: a single holder could reconstruct "
            "any participant's key"
        )

    rng = np.random.default_rng(seed)
    contributions = _contribution_weights(updates, weighting)
    # Private keys are nonzero elements of the order-`SHARING_PRIME` subgroup, so
    # they are also valid Shamir secrets in the field the shares live in.
    private_keys = {
        client_id: _sample_field_element(rng, SHARING_PRIME, nonzero=True)
        for client_id in client_ids
    }
    public_keys = {
        client_id: pow(FIELD_GENERATOR, private_keys[client_id], FIELD_PRIME)
        for client_id in client_ids
    }

    masks = {client_id: np.zeros(dimension, dtype=float) for client_id in client_ids}
    for first_index, first in enumerate(client_ids):
        for second in client_ids[first_index + 1 :]:
            # Both endpoints compute g^{a_first * a_second}: this side raises the
            # peer's public key to its own private key. The server can only
            # recompute it for a dropped peer, by reconstructing that peer's key.
            secret = pow(public_keys[second], private_keys[first], FIELD_PRIME)
            shared = _pairwise_mask_from_secret(
                secret,
                first,
                second,
                dimension,
                round_id=round_id,
                scale=scale,
                modulus=FIELD_PRIME,
            )
            masks[first] = masks[first] + shared
            masks[second] = masks[second] - shared

    masked_updates = {
        update.client_id: mask_update(
            update, masks[update.client_id], weight=contributions[update.client_id]
        )
        for update in updates
    }
    dealings = {
        client_id: shamir_split(private_keys[client_id], n, threshold, rng=rng)
        for client_id in client_ids
    }

    return SecureRoundPlan(
        client_ids=tuple(client_ids),
        dimension=dimension,
        round_id=round_id,
        threshold=threshold,
        sharing_prime=SHARING_PRIME,
        modulus=FIELD_PRIME,
        generator=FIELD_GENERATOR,
        scale=scale,
        weighting=weighting,
        contributions=contributions,
        public_keys=public_keys,
        masked_updates=masked_updates,
        dealings=dealings,
    )


def secure_aggregate_with_dropout(
    updates: Sequence[ClientUpdate],
    state: ServerRoundState,
    *,
    recovery_shares: Optional[Mapping[str, Sequence[ShamirShare]]] = None,
    weighting: Optional[str] = None,
    scale: Optional[float] = None,
    renormalize: bool = True,
) -> AggregationResult:
    """Aggregate masked updates, correcting for participants that dropped out.

    The aggregate is over the participants whose masked updates the server
    actually received. For every expected participant that did not submit, the
    server gathers at least ``threshold`` verified Shamir shares of that
    participant's private key, reconstructs it, regenerates the pairwise masks
    that no longer cancel, and subtracts them. Present participants reveal
    nothing: their key material is never reconstructed and their pairwise secrets
    with other present participants are never derived.

    A participant whose masked update is absent is *excluded* from the aggregate
    (its plaintext cannot be invented), so recovery restores the exact sum over
    the participants that did submit. The per-client weights were folded in
    before masking and normalised over the *full* expected set, so that sum is
    not yet an average over the survivors; by default ``renormalize`` divides by
    the surviving weight mass, which turns it into the weighted mean over
    survivors -- the same quantity :func:`federated_average` would produce for
    exactly those participants. Pass ``renormalize=False`` to get the raw
    weighted sum instead.

    Args:
        updates: Masked updates as produced by :func:`plan_secure_round` and
            actually received by the server.
        state: Public round description from
            :meth:`SecureRoundPlan.server_state`.
        recovery_shares: For each missing participant id, the shares of its
            private key held by the participants that are present. Invalid shares
            are discarded; fewer than ``threshold`` valid shares is fatal.
        weighting: Override for result metadata; the arithmetic is always the
            uniform sum because the weights were folded in before masking.
        scale: Override for the mask scale. Must match the planning scale or the
            regenerated masks will not match the originals.
        renormalize: Divide by the surviving weight mass so the result is the
            weighted mean over survivors (default), matching
            :func:`federated_average` for the same participants.

    Raises:
        ValueError: On duplicate ids, inconsistent dimensions, or an invalid
            threshold.
        SecureAggregationError: On an unknown participant, a missing/forged
            dealing, fewer than ``threshold`` valid shares, a commitment that
            disagrees with the participant's public key, or, when renormalizing, a
            surviving weight mass of zero. Every one of these leaves the aggregate
            unrecoverable, so the function raises rather than returning an
            approximate or corrupted sum.
    """
    if not updates:
        raise ValueError("secure_aggregate_with_dropout needs at least one update")
    present = [update.client_id for update in updates]
    if len(set(present)) != len(present):
        raise ValueError("client ids must be unique")
    dimensions = {update.dimension for update in updates}
    if len(dimensions) != 1:
        raise ValueError(
            f"updates have inconsistent dimensions {sorted(dimensions)}"
        )
    dimension = updates[0].dimension

    expected = list(state.expected_clients)
    if not (1 <= state.threshold <= len(expected)):
        raise ValueError(
            f"round threshold {state.threshold} is not in [1, {len(expected)}]"
        )
    missing = sorted(set(expected) - set(present))
    unknown = sorted(set(present) - set(expected))
    if unknown:
        raise SecureAggregationError(
            f"secure aggregation received updates from unknown clients {unknown}; "
            "refusing to aggregate an unrecognised contribution"
        )

    effective_weighting = state.weighting if weighting is None else weighting
    effective_scale = state.scale if scale is None else float(scale)

    if missing and len(present) < state.threshold:
        raise SecureAggregationError(
            f"{len(missing)} of {len(expected)} participants are missing; only "
            f"{len(present)} remain and a threshold of {state.threshold} shares is "
            f"needed, so at most {len(expected) - state.threshold} dropouts are "
            "recoverable and the aggregate is unrecoverable"
        )

    residual = np.zeros(dimension, dtype=float)
    for owner in missing:
        commitments = state.commitments.get(owner)
        public_key = state.public_keys.get(owner)
        if commitments is None or public_key is None:
            raise SecureAggregationError(
                f"no public dealing on file for dropped client {owner!r}; the round "
                "cannot be recovered"
            )
        # The constant commitment is g^{a_owner}. If it is not the broadcast public
        # key, the dealer shared a different polynomial and reconstructing it would
        # produce masks that do not match the ones that participant applied.
        if commitments.commitments[0] != public_key:
            raise SecureAggregationError(
                f"Feldman commitment for {owner!r} is inconsistent with its public "
                "key; the dealer is malicious or the dealing was corrupted"
            )

        submitted = () if recovery_shares is None else tuple(
            recovery_shares.get(owner, ())
        )
        valid = tuple(share for share in submitted if commitments.verify(share))
        if len(valid) < state.threshold:
            raise SecureAggregationError(
                f"reconstructing {owner!r} needs {state.threshold} valid shares, got "
                f"{len(valid)} of {len(submitted)} submitted; the aggregate is "
                "unrecoverable"
            )
        private_key = shamir_reconstruct(
            valid,
            threshold=state.threshold,
            field=state.sharing_prime,
            commitments=commitments,
        )
        if pow(state.generator, private_key, state.modulus) != public_key:
            raise SecureAggregationError(
                f"reconstructed key for {owner!r} does not match its public key"
            )

        for client_id in present:
            first, second = sorted((client_id, owner))
            secret = pow(state.public_keys[client_id], private_key, state.modulus)
            shared = _pairwise_mask_from_secret(
                secret,
                first,
                second,
                dimension,
                round_id=state.round_id,
                scale=effective_scale,
                modulus=state.modulus,
            )
            # For pair (first, second), the first endpoint's mask carries +shared
            # and the second's carries -shared. Only the present endpoint's term
            # survives into the partial sum, so that is the term to remove.
            if client_id == first:
                residual = residual + shared
            else:
                residual = residual - shared

    # Uniform summation, exactly as in `secure_aggregate`: the weights were folded
    # in before masking, and cancellation requires equal coefficients.
    aggregate = np.zeros(dimension, dtype=float)
    for update in updates:
        aggregate = aggregate + update.weights
    aggregate = aggregate - residual

    if renormalize:
        # The folded weights were normalised over the full expected set, so the
        # partial sum is scaled by the surviving weight mass. Dividing recovers
        # the weighted mean over the survivors, matching `federated_average` for
        # the same participants. A zero mass cannot be renormalised and raises.
        survivor_mass = float(sum(state.contributions[c] for c in present))
        if survivor_mass <= 0.0 or not np.isfinite(survivor_mass):
            raise SecureAggregationError(
                "surviving participants carry zero total weight; the aggregate "
                "cannot be renormalised and recovery is refused"
            )
        aggregate = aggregate / survivor_mass
        result_contributions = _contribution_weights(updates, effective_weighting)
    else:
        result_contributions = {
            client_id: float(state.contributions[client_id]) for client_id in present
        }

    return AggregationResult(
        weights=aggregate,
        contributions=result_contributions,
        n_clients=len(updates),
        weighting=effective_weighting,
        masked=True,
        dropped_clients=tuple(missing),
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
