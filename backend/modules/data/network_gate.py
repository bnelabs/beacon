"""Network quality attestation gate.

Why an attestation gate at all
------------------------------

The data-quality gate answers "were the *rows* sound?". It cannot answer "is the
*network* still the one the model was trained on?". Those fail independently. A
payload can be complete, timely and internally consistent while the interbank
network has reorganised into a topology the model has never seen -- and in that
case the model's output is an extrapolation, not a prediction.

This gate blocks inference when any of three conditions holds:

1. **Topology has moved outside the training distribution.** Measured as the
   Wasserstein-1 distance between the live multiplex and the training snapshots,
   per summary component, with a p-value from the training distribution itself.
2. **An unseen regime.** The regime label is not one the model was trained on.
   (The regime estimator arrives with the HMGM work in Phase 3; this gate takes
   the label as an input and is agnostic to how it was produced.)
3. **Conformal interval too wide.** Rejecting the *width* rather than the point
   estimate is what makes the gate useful: a model can be confidently wrong or
   honestly ignorant, and only the second is acceptable for a systemic-risk
   figure. The threshold is calibrated from training-time widths, not chosen.

Honest limits of the topology test
----------------------------------

The distance is Wasserstein-1 between 1-D *summary distributions* of the network
(edge weights, node strengths, degrees, and the spectrum of the symmetric part).
That is **not** Gromov-Wasserstein or any optimal transport between graphs
themselves, which is what the plan's phrase "Optimal Transport" might suggest.
True graph OT requires solving a quadratic assignment problem; it is expensive and
there is no solver available here that I could validate. Comparing summary
distributions is tractable, exactly computable in closed form for 1-D, and
sufficient to detect the failure modes that matter -- a layer collapsing, edges
redistributing, connectivity concentrating -- but it is blind to changes that
preserve the summary distributions while rewiring *which* nodes connect to which.
That blindness is recorded in the module and must not be forgotten when reading a
passing verdict.
"""

from __future__ import annotations

import hashlib
import json
import logging
from math import comb
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

import numpy as np

from backend.exceptions import PredictionBlockedError
from backend.modules.data.quality_gate import QualityCheck
from backend.modules.engine.multiplex import MultiplexLayer

logger = logging.getLogger(__name__)

__all__ = [
    "wasserstein_1d",
    "minimum_reference_size",
    "GraphSignature",
    "TopologyReference",
    "TopologyAssessment",
    "RegimeAssessment",
    "IntervalWidthReference",
    "NetworkAttestation",
    "NetworkQualityGate",
]

SEVERITY_CRITICAL = "critical"
SEVERITY_WARNING = "warning"
SEVERITY_INFO = "info"

DEFAULT_ALPHA = 0.01


def minimum_reference_size(alpha: float, n_components: int) -> int:
    """Smallest number of reference snapshots at which novelty can be detected.

    The empirical p-value is ``(1 + #{null >= d}) / (1 + n_null)`` where ``n_null``
    is the number of *pairwise* distances among the reference snapshots, i.e.
    ``C(n, 2)``. The smallest p-value the test can ever produce is therefore
    ``1 / (C(n, 2) + 1)``, attained when the live network is further from the
    reference than any two reference snapshots were from each other.

    For that to fall below the Bonferroni-corrected threshold ``alpha / k`` over
    ``k`` components, the reference must satisfy
    ``C(n, 2) + 1 > k / alpha``. With ``alpha = 0.01`` and four components that
    needs **29** snapshots. A smaller reference does not merely weaken the test --
    it makes rejection arithmetically impossible, so the gate would always return
    "in distribution" no matter what arrived. A gate that cannot fire is worse
    than no gate, because it manufactures assurance.

    Args:
        alpha: Family-wise significance level.
        n_components: Number of signature components tested.

    Returns:
        The minimum usable reference size.
    """
    if not 0.0 < alpha < 1.0:
        raise ValueError(f"alpha must be in (0, 1), got {alpha}")
    if n_components < 1:
        raise ValueError(f"n_components must be positive, got {n_components}")

    target = n_components / alpha
    n = 2
    while comb(n, 2) + 1 <= target:
        n += 1
    return n


# ---------------------------------------------------------------------------
# Distance
# ---------------------------------------------------------------------------

def wasserstein_1d(a: Sequence[float], b: Sequence[float]) -> float:
    """Exact Wasserstein-1 distance between two 1-D empirical distributions.

    In one dimension the optimal transport plan is the monotone one, so the
    distance has a closed form as the area between the two CDFs::

        W1 = integral |F_a(x) - F_b(x)| dx

    computed on the pooled support, where the CDF difference is a step function.
    No solver and no approximation is involved, which is why the summary-based
    representation was chosen over a graph-space optimal transport problem.

    The two samples need not be the same size: the CDFs are weighted by their own
    counts, so an unequal number of observations is handled correctly rather than
    being silently truncated.

    Args:
        a, b: Non-empty finite samples.

    Returns:
        The distance, which is 0 for identical samples and positive otherwise.

    Raises:
        ValueError: If either sample is empty or contains non-finite values.
    """
    left = np.asarray(a, dtype=float).reshape(-1)
    right = np.asarray(b, dtype=float).reshape(-1)

    for sample, name in ((left, "a"), (right, "b")):
        if sample.size == 0:
            raise ValueError(f"sample {name} is empty; W1 is undefined")
        if not np.all(np.isfinite(sample)):
            raise ValueError(f"sample {name} contains non-finite values")

    pooled = np.sort(np.concatenate([left, right]))
    left_cdf = np.searchsorted(np.sort(left), pooled, side="right") / left.size
    right_cdf = np.searchsorted(np.sort(right), pooled, side="right") / right.size

    difference = np.abs(left_cdf - right_cdf)
    # The difference is constant on each interval between consecutive pooled
    # points, and zero outside the pooled range, so the integral is a sum.
    widths = np.diff(pooled)
    return float(np.sum(difference[:-1] * widths))


# ---------------------------------------------------------------------------
# Signatures
# ---------------------------------------------------------------------------

_SIGNATURE_COMPONENTS = ("edge_weights", "node_strengths", "degrees", "spectrum", "size")


@dataclass(frozen=True)
class GraphSignature:
    """A tractable 1-D summary of one network layer.

    Four views, chosen because together they detect the failures that matter:

    * ``edge_weights`` -- how strong the surviving relations are. Empty when the
      layer has no edges, in which case it is skipped in the distance and the
      collapse is caught by the other three instead.
    * ``node_strengths`` -- total relation weight per node, so redistribution
      shows up even when the total is unchanged.
    * ``degrees`` -- how many relations each node has, catching a layer that
      fragments into isolated nodes.
    * ``spectrum`` -- eigenvalues of the symmetric part ``(A + A^T) / 2``, a real
      spectrum for directed layers too, summarising global connectivity. The
      symmetric part is used rather than the adjacency itself because a directed
      adjacency has complex eigenvalues, which have no natural order and so no
      CDF for a 1-D distance.
    * ``size`` -- the node count, as a degenerate one-point distribution.

    ``size`` is tested separately because the other four are *distributions* of
    node-level quantities and are therefore blind to how many nodes there are. A
    6-node ring and a 30-node ring both have degree 1 at every node, the same
    distribution of node strengths, and spectra that both approximate the same
    arcsine law, so all four components report near-zero distance for a network
    five times the size. Size is part of the topology and is asserted as such.
    """

    name: str
    edge_weights: np.ndarray
    node_strengths: np.ndarray
    degrees: np.ndarray
    spectrum: np.ndarray
    size: np.ndarray
    n_nodes: int

    @classmethod
    def from_layer(cls, layer: MultiplexLayer) -> "GraphSignature":
        adjacency = np.asarray(layer.adjacency, dtype=float)
        if adjacency.ndim != 2 or adjacency.shape[0] != adjacency.shape[1]:
            raise ValueError(
                f"layer {layer.name!r} adjacency must be square, got {adjacency.shape}"
            )

        edges = adjacency[adjacency > 0]
        strengths = adjacency.sum(axis=1)
        degrees = (adjacency > 0).sum(axis=1).astype(float)
        symmetric_part = (adjacency + adjacency.T) / 2.0
        spectrum = (
            np.linalg.eigvalsh(symmetric_part)
            if adjacency.shape[0] > 0
            else np.zeros(0, dtype=float)
        )

        n_nodes = int(adjacency.shape[0])
        return cls(
            name=layer.name,
            edge_weights=np.asarray(edges, dtype=float),
            node_strengths=np.asarray(strengths, dtype=float),
            degrees=degrees,
            spectrum=np.asarray(spectrum, dtype=float),
            size=np.asarray([float(n_nodes)], dtype=float),
            n_nodes=n_nodes,
        )

    def components(self) -> Dict[str, np.ndarray]:
        return {name: getattr(self, name) for name in _SIGNATURE_COMPONENTS}

    def to_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "n_nodes": self.n_nodes,
            "n_edges": int(self.edge_weights.size),
            "total_strength": float(self.node_strengths.sum()),
        }


def _comparable(
    live: np.ndarray, reference: np.ndarray
) -> bool:
    """Whether two component samples can be meaningfully compared.

    An empty and a non-empty edge-weight sample means the layer appeared or
    vanished. That is a real change, but W1 is not defined against an empty
    support, and the other components (which always have ``n_nodes`` entries)
    detect it, so the component is skipped rather than assigned a fabricated
    number.
    """
    return live.size > 0 and reference.size > 0


# ---------------------------------------------------------------------------
# Reference distribution
# ---------------------------------------------------------------------------

@dataclass
class TopologyAssessment:
    """Result of comparing a live network against the training distribution."""

    distances: Dict[str, float]
    p_values: Dict[str, float]
    skipped: List[str]
    aggregate_p_value: float
    threshold: float
    is_novel: bool
    n_reference: int
    n_null_samples: int
    calibratable: bool = True

    def to_dict(self) -> Dict[str, object]:
        return {
            "distances": {k: float(v) for k, v in self.distances.items()},
            "p_values": {k: float(v) for k, v in self.p_values.items()},
            "skipped_components": list(self.skipped),
            "aggregate_p_value": float(self.aggregate_p_value),
            "threshold": float(self.threshold),
            "is_novel": bool(self.is_novel),
            "n_reference": int(self.n_reference),
            "n_null_samples": int(self.n_null_samples),
            "calibratable": bool(self.calibratable),
        }


class TopologyReference:
    """The empirical distribution of training-time topologies.

    The threshold is not chosen. It is derived from how far training snapshots
    already sit from one another: if the live network is further from the
    reference than training snapshots ever were from each other, it is outside
    the distribution the model saw. That is a statement about the training data,
    not a hand-picked tolerance.

    Args:
        signatures: One signature per training snapshot.
        alpha: Family-wise significance level for the novelty test.
    """

    def __init__(
        self,
        signatures: Sequence[GraphSignature],
        alpha: float = DEFAULT_ALPHA,
    ) -> None:
        if not signatures:
            raise ValueError("a topology reference needs at least one signature")
        if not 0.0 < alpha < 1.0:
            raise ValueError(f"alpha must be in (0, 1), got {alpha}")

        self.signatures: List[GraphSignature] = list(signatures)
        self.alpha = float(alpha)
        self.components = sorted(
            {name for signature in self.signatures for name in signature.components()}
        )
        self._null_distances: Dict[str, np.ndarray] = {
            name: self._build_null(name) for name in self.components
        }

        self.minimum_reference_size = minimum_reference_size(
            self.alpha, max(len(self.components), 1)
        )
        if len(self.signatures) < self.minimum_reference_size:
            logger.warning(
                "Topology reference has %d snapshots but needs at least %d to reject "
                "novelty at alpha=%g over %d components. The smallest attainable "
                "p-value is 1/(C(n,2)+1) = %.4g, which exceeds the corrected "
                "threshold %.4g, so this gate CANNOT flag novelty regardless of the "
                "input. Supply more reference snapshots or the verdict is meaningless.",
                len(self.signatures),
                self.minimum_reference_size,
                self.alpha,
                len(self.components),
                1.0 / (comb(len(self.signatures), 2) + 1),
                self.alpha / max(len(self.components), 1),
            )

    def _build_null(self, component: str) -> np.ndarray:
        """All pairwise distances between training signatures for one component."""
        samples = []
        for signature in self.signatures:
            sample = signature.components().get(component)
            if sample is not None and sample.size > 0:
                samples.append(sample)

        if len(samples) < 2:
            return np.zeros(0, dtype=float)

        distances = []
        for i in range(len(samples)):
            for j in range(i + 1, len(samples)):
                distances.append(wasserstein_1d(samples[i], samples[j]))
        return np.asarray(distances, dtype=float)

    @property
    def is_calibratable(self) -> bool:
        """Whether this reference is large enough to be able to reject at all.

        When false, ``assess`` will always report ``is_novel=False`` for reasons
        that have nothing to do with the data. Callers that depend on the gate
        should treat this as a blocking configuration error.
        """
        return len(self.signatures) >= self.minimum_reference_size

    @property
    def n_null_samples(self) -> int:
        return sum(int(values.size) for values in self._null_distances.values())

    def _reference_sample(self, component: str) -> np.ndarray:
        """Pool every training observation of a component into one sample.

        Pooling rather than averaging: the reference is the marginal distribution
        the model saw, so its own spread is part of the reference, not noise to be
        averaged away.
        """
        parts = [
            signature.components()[component]
            for signature in self.signatures
            if signature.components().get(component) is not None
            and signature.components()[component].size > 0
        ]
        if not parts:
            return np.zeros(0, dtype=float)
        return np.concatenate(parts)

    def assess(self, live: GraphSignature) -> TopologyAssessment:
        """Compare a live network against the training distribution.

        Each component gets an empirical p-value: the fraction of training
        pairwise distances at least as large as the live distance, with add-one
        smoothing so the minimum attainable p-value is bounded away from zero
        rather than being exactly 0 on a finite sample. The aggregate p-value is
        the minimum across components, compared against a Bonferroni-corrected
        threshold, because testing several components and taking the most extreme
        would otherwise inflate the false-positive rate.
        """
        distances: Dict[str, float] = {}
        p_values: Dict[str, float] = {}
        skipped: List[str] = []

        for component in self.components:
            live_sample = live.components().get(component)
            reference_sample = self._reference_sample(component)
            if live_sample is None or not _comparable(live_sample, reference_sample):
                skipped.append(component)
                continue

            distance = wasserstein_1d(live_sample, reference_sample)
            distances[component] = distance

            null = self._null_distances.get(component, np.zeros(0, dtype=float))
            if null.size == 0:
                skipped.append(component)
                distances.pop(component, None)
                continue
            # Add-one smoothing: (1 + #{null >= d}) / (1 + n).
            p_values[component] = float(
                (1.0 + int(np.sum(null >= distance))) / (1.0 + null.size)
            )

        if not p_values:
            # Nothing was comparable. Refusing to certify is the safe verdict:
            # a gate that passes when it could not measure anything is worse than
            # no gate, because it manufactures confidence.
            return TopologyAssessment(
                distances=distances,
                p_values={},
                skipped=skipped,
                aggregate_p_value=float("nan"),
                threshold=self.alpha,
                is_novel=True,
                n_reference=len(self.signatures),
                n_null_samples=self.n_null_samples,
                calibratable=self.is_calibratable,
            )

        aggregate = float(min(p_values.values()))
        corrected = self.alpha / len(p_values)

        return TopologyAssessment(
            distances=distances,
            p_values=p_values,
            skipped=skipped,
            aggregate_p_value=aggregate,
            threshold=corrected,
            is_novel=bool(aggregate < corrected),
            n_reference=len(self.signatures),
            n_null_samples=self.n_null_samples,
            calibratable=self.is_calibratable,
        )


# ---------------------------------------------------------------------------
# Regime
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RegimeAssessment:
    """Whether the current regime was among those the model was trained on."""

    label: str
    known: bool
    is_transition: bool
    known_regimes: Tuple[str, ...]

    def to_dict(self) -> Dict[str, object]:
        return {
            "label": self.label,
            "known": bool(self.known),
            "is_transition": bool(self.is_transition),
            "known_regimes": list(self.known_regimes),
        }


# ---------------------------------------------------------------------------
# Interval width
# ---------------------------------------------------------------------------

class IntervalWidthReference:
    """Calibrated ceiling on conformal interval width.

    The threshold is the empirical quantile of widths observed during training,
    so "too wide" means "wider than this model has ever been on data it was
    validated against", rather than an absolute number somebody liked. A conformal
    interval only widens when the model is uncertain, so an unusually wide
    interval is exactly the moment to refuse a point forecast.
    """

    def __init__(self, widths: Sequence[float], level: float = 0.99) -> None:
        array = np.asarray(widths, dtype=float).reshape(-1)
        if array.size == 0:
            raise ValueError("width reference needs at least one observed width")
        if not np.all(np.isfinite(array)):
            raise ValueError("width reference contains non-finite values")
        if not 0.0 < level < 1.0:
            raise ValueError(f"level must be in (0, 1), got {level}")

        self.widths = array
        self.level = float(level)

    @property
    def threshold(self) -> float:
        return float(np.quantile(self.widths, self.level, method="higher"))

    def assess(self, width: float) -> Dict[str, object]:
        if not np.isfinite(width) or width < 0:
            raise ValueError(f"width must be finite and non-negative, got {width}")
        threshold = self.threshold
        exceeded = bool(width > threshold)
        return {
            "width": float(width),
            "threshold": threshold,
            "level": self.level,
            "n_reference": int(self.widths.size),
            "exceeded": exceeded,
            "ratio": float(width / threshold) if threshold > 0 else float("inf") if width > 0 else 0.0,
        }


# ---------------------------------------------------------------------------
# Attestation
# ---------------------------------------------------------------------------

@dataclass
class NetworkAttestation:
    """Verdict on the network conditions under which a prediction is requested."""

    job_id: str
    verified: bool
    checked_at: str
    checks: List[QualityCheck] = field(default_factory=list)
    topology: Dict[str, object] = field(default_factory=dict)
    regime: Dict[str, object] = field(default_factory=dict)
    interval_width: Dict[str, object] = field(default_factory=dict)

    @property
    def failures(self) -> List[QualityCheck]:
        return [check for check in self.checks if not check.passed]

    @property
    def attestation_id(self) -> str:
        """Content-addressed identity of this verdict, for a reproducibility manifest."""
        payload = {
            "job_id": self.job_id,
            "verified": bool(self.verified),
            "checked_at": self.checked_at,
            "checks": [
                {
                    "name": check.name,
                    "passed": bool(check.passed),
                    "severity": check.severity,
                }
                for check in self.checks
            ],
            "topology_aggregate_p": self.topology.get("aggregate_p_value"),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, object]:
        return {
            "job_id": self.job_id,
            "verified": self.verified,
            "checked_at": self.checked_at,
            "attestation_id": self.attestation_id,
            "checks": [check.to_dict() for check in self.checks],
            "failures": [check.to_dict() for check in self.failures],
            "topology": dict(self.topology),
            "regime": dict(self.regime),
            "interval_width": dict(self.interval_width),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "NetworkAttestation":
        return cls(
            job_id=payload.get("job_id", "unknown"),
            verified=bool(payload.get("verified", False)),
            checked_at=payload.get("checked_at", ""),
            checks=[QualityCheck(**check) for check in payload.get("checks", [])],
            topology=dict(payload.get("topology") or {}),
            regime=dict(payload.get("regime") or {}),
            interval_width=dict(payload.get("interval_width") or {}),
        )

    def summary(self) -> str:
        if self.verified:
            return (
                f"Network conditions verified for job {self.job_id} "
                f"({len(self.checks)} checks passed)"
            )
        reasons = "; ".join(f"{check.name}: {check.detail}" for check in self.failures)
        return f"Network conditions rejected for job {self.job_id} - {reasons}"


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------

class NetworkQualityGate:
    """Blocks inference when the network conditions are outside the training envelope.

    Args:
        topology_reference: Training-time topologies, or ``None`` to skip the
            topology test (in which case the skip is recorded as a warning rather
            than silently omitted).
        known_regimes: Regime labels the model was trained on.
        width_reference: Calibrated conformal width ceiling, or ``None`` to skip.
    """

    def __init__(
        self,
        topology_reference: Optional[TopologyReference] = None,
        known_regimes: Optional[Iterable[str]] = None,
        width_reference: Optional[IntervalWidthReference] = None,
        *,
        require_topology: bool = False,
        require_interval_width: bool = False,
    ) -> None:
        self.topology_reference = topology_reference
        self.known_regimes = tuple(sorted(set(known_regimes or ())))
        self.width_reference = width_reference
        self.require_topology = bool(require_topology)
        self.require_interval_width = bool(require_interval_width)

    def evaluate(
        self,
        *,
        job_id: str,
        live_layers: Optional[Sequence[MultiplexLayer]] = None,
        regime_label: Optional[str] = None,
        is_transition: bool = False,
        interval_width: Optional[float] = None,
        checked_at: str = "",
    ) -> NetworkAttestation:
        """Assess the network conditions and return a verdict.

        Any blocking condition makes the verdict negative. The gate fails closed:
        a condition that could not be measured is a warning by default, but
        ``require_topology`` and ``require_interval_width`` promote "not measured"
        to a blocking failure for callers who would rather stop than proceed
        unverified.
        """
        checks: List[QualityCheck] = []
        topology_payload: Dict[str, object] = {}
        regime_payload: Dict[str, object] = {}
        width_payload: Dict[str, object] = {}

        # -- 1. topology ----------------------------------------------------
        if self.topology_reference is None:
            checks.append(
                QualityCheck(
                    name="topology_reference_missing",
                    passed=not self.require_topology,
                    severity=SEVERITY_CRITICAL if self.require_topology else SEVERITY_WARNING,
                    detail=(
                        "no training-time topology reference was supplied, so the live "
                        "network could not be compared against the training distribution"
                    ),
                )
            )
        elif not live_layers:
            checks.append(
                QualityCheck(
                    name="topology_live_missing",
                    passed=not self.require_topology,
                    severity=SEVERITY_CRITICAL if self.require_topology else SEVERITY_WARNING,
                    detail="a topology reference exists but no live network was supplied",
                )
            )
        else:
            reference = self.topology_reference
            if not reference.is_calibratable:
                # The reference is too small for the test to be able to reject
                # anything. Recording this loudly matters: an always-passing gate
                # is a false assurance, and silence would read as "topology fine".
                checks.append(
                    QualityCheck(
                        name="topology_reference_undersized",
                        passed=not self.require_topology,
                        severity=(
                            SEVERITY_CRITICAL
                            if self.require_topology
                            else SEVERITY_WARNING
                        ),
                        detail=(
                            f"topology reference has {len(reference.signatures)} snapshots "
                            f"but needs at least {reference.minimum_reference_size} to reject "
                            "novelty at this significance level over this many components; "
                            "the topology verdict cannot fire regardless of the input"
                        ),
                    )
                )

            assessment = self._assess_topology(live_layers)
            topology_payload = assessment.to_dict()
            if assessment.is_novel:
                drifted = sorted(
                    name
                    for name, p_value in assessment.p_values.items()
                    if p_value < assessment.threshold
                )
                detail = (
                    "live network topology is outside the training distribution"
                    if drifted
                    else (
                        "topology could not be compared on any component, so it cannot "
                        "be certified as in-distribution"
                    )
                )
                if drifted:
                    detail += f" (components: {', '.join(drifted)})"
                checks.append(
                    QualityCheck(
                        name="topology_out_of_distribution",
                        passed=False,
                        severity=SEVERITY_CRITICAL,
                        detail=detail,
                    )
                )
            else:
                checks.append(
                    QualityCheck(
                        name="topology_in_distribution",
                        passed=True,
                        severity=SEVERITY_INFO,
                        detail=(
                            "live topology is within the training distribution "
                            f"(min p={assessment.aggregate_p_value:.4g}, "
                            f"threshold={assessment.threshold:.4g})"
                        ),
                    )
                )

        # -- 2. regime ------------------------------------------------------
        if regime_label is None:
            regime_payload = {"label": None, "known": False, "is_transition": bool(is_transition)}
            checks.append(
                QualityCheck(
                    name="regime_unreported",
                    passed=True,
                    severity=SEVERITY_WARNING,
                    detail=(
                        "no regime label was supplied, so the unseen-regime test could "
                        "not run; the verdict does not cover regime"
                    ),
                )
            )
        else:
            assessment = RegimeAssessment(
                label=str(regime_label),
                known=str(regime_label) in self.known_regimes,
                is_transition=bool(is_transition),
                known_regimes=self.known_regimes,
            )
            regime_payload = assessment.to_dict()
            checks.append(
                QualityCheck(
                    name="regime_known" if assessment.known else "regime_unseen",
                    passed=assessment.known,
                    severity=SEVERITY_INFO if assessment.known else SEVERITY_CRITICAL,
                    detail=(
                        f"regime {assessment.label!r} was seen during training"
                        if assessment.known
                        else (
                            f"regime {assessment.label!r} was not among the training "
                            f"regimes {list(self.known_regimes)}; the model has no "
                            "calibration for it"
                        )
                    ),
                )
            )

        # -- 3. interval width ----------------------------------------------
        if self.width_reference is None:
            checks.append(
                QualityCheck(
                    name="interval_width_reference_missing",
                    passed=not self.require_interval_width,
                    severity=(
                        SEVERITY_CRITICAL if self.require_interval_width else SEVERITY_WARNING
                    ),
                    detail=(
                        "no calibrated interval-width ceiling was supplied, so the "
                        "uncertainty test could not run"
                    ),
                )
            )
        elif interval_width is None:
            checks.append(
                QualityCheck(
                    name="interval_width_missing",
                    passed=not self.require_interval_width,
                    severity=(
                        SEVERITY_CRITICAL if self.require_interval_width else SEVERITY_WARNING
                    ),
                    detail="a width ceiling exists but no interval width was supplied",
                )
            )
        else:
            width_payload = self.width_reference.assess(float(interval_width))
            exceeded = bool(width_payload["exceeded"])
            checks.append(
                QualityCheck(
                    name="interval_width_exceeded" if exceeded else "interval_width_ok",
                    passed=not exceeded,
                    severity=SEVERITY_CRITICAL if exceeded else SEVERITY_INFO,
                    detail=(
                        f"conformal interval width {width_payload['width']:.6g} exceeds the "
                        f"calibrated ceiling {width_payload['threshold']:.6g} "
                        f"(level {width_payload['level']})"
                        if exceeded
                        else (
                            f"conformal interval width {width_payload['width']:.6g} is within "
                            f"the calibrated ceiling {width_payload['threshold']:.6g}"
                        )
                    ),
                )
            )

        verified = all(check.passed for check in checks)
        return NetworkAttestation(
            job_id=job_id,
            verified=verified,
            checked_at=checked_at,
            checks=checks,
            topology=topology_payload,
            regime=regime_payload,
            interval_width=width_payload,
        )

    def _assess_topology(self, live_layers: Sequence[MultiplexLayer]) -> TopologyAssessment:
        """Compare each live layer against its reference, then aggregate.

        Layers are matched by name. A live layer with no reference counterpart is
        treated as novel outright -- an entirely new relation appearing in the
        network is exactly the situation the gate exists to catch.
        """
        reference = self.topology_reference
        assert reference is not None

        reference_names = {signature.name for signature in reference.signatures}
        assessments: List[TopologyAssessment] = []

        for layer in live_layers:
            if layer.name not in reference_names:
                return TopologyAssessment(
                    distances={},
                    p_values={},
                    skipped=[],
                    aggregate_p_value=0.0,
                    threshold=reference.alpha,
                    is_novel=True,
                    n_reference=len(reference.signatures),
                    n_null_samples=reference.n_null_samples,
                )
            assessments.append(
                reference.assess(GraphSignature.from_layer(layer))
            )

        if not assessments:
            return reference.assess(GraphSignature.from_layer(live_layers[0]))

        # Worst layer decides, and the p-values are pooled with a Bonferroni
        # correction over the number of layers tested.
        pooled_p = min(a.aggregate_p_value for a in assessments)
        n_tests = sum(len(a.p_values) for a in assessments) or 1
        distances: Dict[str, float] = {}
        p_values: Dict[str, float] = {}
        skipped: List[str] = []
        for assessment in assessments:
            distances.update(assessment.distances)
            p_values.update(assessment.p_values)
            skipped.extend(assessment.skipped)

        threshold = reference.alpha / n_tests
        return TopologyAssessment(
            distances=distances,
            p_values=p_values,
            skipped=skipped,
            aggregate_p_value=pooled_p,
            threshold=threshold,
            is_novel=bool(pooled_p < threshold),
            n_reference=len(reference.signatures),
            n_null_samples=reference.n_null_samples,
        )

    @staticmethod
    def require(attestation: Optional[NetworkAttestation]) -> NetworkAttestation:
        """Assert that network conditions were attested before inference.

        Raises:
            PredictionBlockedError: When the attestation is missing or negative.
        """
        if attestation is None:
            raise PredictionBlockedError(
                "Prediction blocked: no network-condition attestation was supplied",
                context={
                    "remediation": (
                        "run NetworkQualityGate.evaluate against the live multiplex "
                        "before predicting"
                    )
                },
            )
        if not attestation.verified:
            raise PredictionBlockedError(
                "Prediction blocked: the live network conditions failed verification",
                context={
                    "job_id": attestation.job_id,
                    "failures": [
                        f"{check.name}: {check.detail}" for check in attestation.failures
                    ],
                },
            )
        return attestation
