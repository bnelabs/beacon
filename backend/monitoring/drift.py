"""Data-drift detection for BEACON (workstream F).

Implemented with **pure numpy** -- deliberately no scipy, no pandas requirement
(pandas objects are accepted and converted when present).

Provided statistics
-------------------
``population_stability_index``
    The standard PSI used in credit-risk monitoring::

        PSI = sum_i (actual_i - expected_i) * ln(actual_i / expected_i)

    Bins are the *equal-frequency* deciles of the reference (expected)
    distribution, which is the conventional definition.  Zero-width bins (ties /
    discrete features) are removed with ``numpy.unique`` and zero proportions are
    pushed to a small epsilon so the statistic can never be ``inf``/``nan``.

``kolmogorov_smirnov_statistic``
    Two-sample KS ``D`` statistic plus an approximate p-value from the asymptotic
    Kolmogorov distribution.  Both complementary series of that distribution are
    implemented from scratch (:func:`kolmogorov_cdf`, :func:`kolmogorov_sf`) and
    the numerically appropriate one is selected for the argument.

``jensen_shannon_divergence``
    Symmetric, bounded (``[0, 1]`` bits) divergence between the two empirical
    histograms; robust to disjoint support thanks to epsilon smoothing.

``detect_drift``
    Turns the statistics into a JSON-serialisable per-feature + overall verdict
    using the standard PSI bands (none ``< 0.1``, moderate ``0.1-0.25``,
    major ``> 0.25``).

``FeatureDriftMonitor``
    Holds a training-time reference summary (bin edges + proportions + a bounded
    reference sample so a real KS test is still possible after a restart) that
    round-trips through JSON, so live inference features can be compared against
    the training distribution.  Scoring updates the Prometheus gauge
    ``beacon_feature_drift_psi{feature=...}``.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union

import numpy as np

from .metrics import feature_drift_psi as feature_drift_psi_gauge

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_THRESHOLDS",
    "SEVERITY_NONE",
    "SEVERITY_MODERATE",
    "SEVERITY_MAJOR",
    "population_stability_index",
    "kolmogorov_smirnov_statistic",
    "kolmogorov_cdf",
    "kolmogorov_sf",
    "jensen_shannon_divergence",
    "psi_severity",
    "detect_drift",
    "FeatureDriftMonitor",
    "feature_drift_psi_gauge",
]

#: Small epsilon used to avoid ``log(0)`` / division by zero.
DEFAULT_EPSILON = 1e-6

SEVERITY_NONE = "none"
SEVERITY_MODERATE = "moderate"
SEVERITY_MAJOR = "major"

_SEVERITY_ORDER = {SEVERITY_NONE: 0, SEVERITY_MODERATE: 1, SEVERITY_MAJOR: 2}

#: Standard PSI interpretation bands plus KS/JSD decision thresholds.
DEFAULT_THRESHOLDS: Dict[str, float] = {
    # PSI < psi_none                        -> no drift
    "psi_none": 0.1,
    # psi_none <= PSI <= psi_major          -> moderate drift
    # PSI > psi_major                       -> major drift
    "psi_major": 0.25,
    # KS: drift when p-value below the level AND D above the minimum effect size
    "ks_pvalue": 0.05,
    "ks_statistic": 0.10,
    # Jensen-Shannon divergence (bits) considered meaningful
    "jsd": 0.10,
}

_JSON_SCHEMA_VERSION = 1


# ---------------------------------------------------------------------------
# Coercion helpers
# ---------------------------------------------------------------------------


def _as_float_array(values: Any) -> np.ndarray:
    """Coerce ``values`` to a finite, 1-D float array (NaNs/infs dropped)."""

    if values is None:
        raise ValueError("expected a sequence of numbers, got None")

    if isinstance(values, np.ndarray):
        array = values
    elif hasattr(values, "to_numpy"):  # pandas Series
        array = np.asarray(values.to_numpy())
    elif isinstance(values, (str, bytes)):
        raise TypeError("expected a sequence of numbers, got a string")
    else:
        array = np.asarray(list(values) if not isinstance(values, (list, tuple)) else values)

    if array.dtype == object:
        array = array.astype(float)
    array = np.asarray(array, dtype=float).reshape(-1)
    if array.size:
        array = array[np.isfinite(array)]
    return array


def _require_samples(values: Any, name: str) -> np.ndarray:
    array = _as_float_array(values)
    if array.size == 0:
        raise ValueError(f"{name} contains no finite samples")
    return array


def _as_feature_mapping(obj: Any) -> Dict[str, np.ndarray]:
    """Accept a mapping ``{feature: values}`` or a pandas DataFrame."""

    if obj is None:
        raise ValueError("expected a feature mapping, got None")

    if hasattr(obj, "columns") and hasattr(obj, "__getitem__"):  # DataFrame
        return {str(column): _as_float_array(obj[column]) for column in obj.columns}

    if isinstance(obj, Mapping):
        return {str(key): _as_float_array(value) for key, value in obj.items()}

    raise TypeError(
        "expected a mapping of feature name -> samples or a pandas DataFrame, "
        f"got {type(obj).__name__}"
    )


def _merged_thresholds(thresholds: Optional[Mapping[str, float]]) -> Dict[str, float]:
    merged = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        for key, value in thresholds.items():
            if key in merged:
                merged[key] = float(value)
    # Guard against inverted configuration.
    if merged["psi_major"] < merged["psi_none"]:
        merged["psi_none"], merged["psi_major"] = (
            merged["psi_major"],
            merged["psi_none"],
        )
    return merged


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# PSI
# ---------------------------------------------------------------------------


def _quantile_edges(expected: np.ndarray, buckets: int) -> np.ndarray:
    """Equal-frequency bin edges from the reference sample.

    Returns strictly increasing finite edges (zero-width bins removed).  A
    degenerate constant feature yields a tiny symmetric interval around the
    constant so that downstream histogramming stays well defined.
    """

    buckets = max(2, int(buckets))
    quantiles = np.linspace(0.0, 1.0, buckets + 1)
    edges = np.unique(np.quantile(expected, quantiles))
    edges = np.asarray(edges, dtype=float)

    if edges.size < 2:
        centre = float(edges[0]) if edges.size else 0.0
        width = max(abs(centre) * 1e-6, 1e-9)
        edges = np.asarray([centre - width, centre + width], dtype=float)

    return edges


def _full_edges(edges: np.ndarray) -> np.ndarray:
    """Open the outer bins to +/-inf so out-of-range live values are counted."""

    full = np.asarray(edges, dtype=float).copy()
    full[0] = -np.inf
    full[-1] = np.inf
    return full


def _proportions(values: np.ndarray, full_edges: np.ndarray) -> np.ndarray:
    """Histogram proportions of ``values`` over ``full_edges``."""

    counts, _ = np.histogram(values, bins=full_edges)
    total = float(counts.sum())
    if total <= 0:  # pragma: no cover - defensive
        return np.zeros_like(counts, dtype=float)
    return counts.astype(float) / total


def population_stability_index(
    expected: Any,
    actual: Any,
    buckets: int = 10,
    epsilon: float = DEFAULT_EPSILON,
) -> float:
    """Population Stability Index of ``actual`` against ``expected``.

    ``expected`` is the reference/training distribution (its deciles define the
    bins), ``actual`` is the live/current distribution.  Returns ``0.0`` for
    identical distributions and grows without bound as they separate.

    Raises ``ValueError`` when either sample is empty after dropping non-finite
    values -- silently returning ``0`` would hide a broken feature feed.
    """

    reference = _require_samples(expected, "expected")
    current = _require_samples(actual, "actual")

    if buckets is not None and int(buckets) < 2:
        raise ValueError("buckets must be >= 2")

    eps = float(epsilon)
    if not math.isfinite(eps) or eps <= 0.0:
        raise ValueError("epsilon must be a positive finite number")

    edges = _quantile_edges(reference, int(buckets))
    if edges.size < 3:
        # The reference is (near-)constant, so its quantile bins collapsed to a
        # single open bin -- a level shift would be invisible.  Fall back to
        # equal-width bins over the pooled range, which still detects it.
        lower = float(min(reference.min(), current.min()))
        upper = float(max(reference.max(), current.max()))
        if upper <= lower:
            return 0.0
        edges = np.linspace(lower, upper, int(buckets) + 1)
    full = _full_edges(edges)

    expected_props = np.clip(_proportions(reference, full), eps, None)
    actual_props = np.clip(_proportions(current, full), eps, None)

    psi = np.sum((actual_props - expected_props) * np.log(actual_props / expected_props))
    return float(psi)


# ---------------------------------------------------------------------------
# Kolmogorov-Smirnov (two sample, asymptotic p-value)
# ---------------------------------------------------------------------------


def kolmogorov_cdf(x: float) -> float:
    """CDF of the Kolmogorov distribution ``P(K <= x)``.

    Two complementary series are used (Jacobi theta transformation of the same
    distribution) and the one that converges fastest for ``x`` is selected::

        F(x) = sqrt(2*pi)/x * sum_{k>=1} exp(-(2k-1)^2 * pi^2 / (8 x^2))   (small x)
        F(x) = 1 - 2 * sum_{k>=1} (-1)^(k-1) * exp(-2 k^2 x^2)             (large x)
    """

    try:
        value = float(x)
    except (TypeError, ValueError):
        raise ValueError(f"x must be a number, got {x!r}")

    if not math.isfinite(value) or value <= 0.0:
        return 0.0

    if value < 1.18:
        total = 0.0
        for k in range(1, 201):
            term = math.exp(-((2.0 * k - 1.0) ** 2) * math.pi ** 2 / (8.0 * value * value))
            total += term
            if term <= 1e-18:
                break
        cdf = math.sqrt(2.0 * math.pi) / value * total
    else:
        total = 0.0
        sign = 1.0
        for k in range(1, 201):
            term = math.exp(-2.0 * k * k * value * value)
            total += sign * term
            sign = -sign
            if term <= 1e-18:
                break
        cdf = 1.0 - 2.0 * total

    return float(min(1.0, max(0.0, cdf)))


def kolmogorov_sf(x: float) -> float:
    """Survival function ``P(K > x) = 1 - F(x)`` of the Kolmogorov distribution."""

    return float(min(1.0, max(0.0, 1.0 - kolmogorov_cdf(x))))


def _two_sample_ks_statistic(expected: np.ndarray, actual: np.ndarray) -> float:
    """``sup_x |F_expected(x) - F_actual(x)|`` over the pooled sample."""

    pooled = np.concatenate((expected, actual))
    pooled = np.sort(pooled, kind="mergesort")
    expected_sorted = np.sort(expected, kind="mergesort")
    actual_sorted = np.sort(actual, kind="mergesort")

    cdf_expected = np.searchsorted(expected_sorted, pooled, side="right") / expected.size
    cdf_actual = np.searchsorted(actual_sorted, pooled, side="right") / actual.size

    return float(np.max(np.abs(cdf_expected - cdf_actual)))


def kolmogorov_smirnov_statistic(
    expected: Any, actual: Any
) -> Tuple[float, float]:
    """Two-sample KS test.

    Returns ``(D, p_value)`` where ``D`` is in ``[0, 1]`` and ``p_value`` is the
    asymptotic Kolmogorov approximation ``Q(sqrt(n_eff) * D)`` with
    ``n_eff = n * m / (n + m)``.  Identical samples give ``D = 0`` and ``p = 1``.
    """

    reference = _require_samples(expected, "expected")
    current = _require_samples(actual, "actual")

    d_statistic = _two_sample_ks_statistic(reference, current)

    n_eff = (reference.size * current.size) / float(reference.size + current.size)
    p_value = kolmogorov_sf(math.sqrt(n_eff) * d_statistic)

    return float(d_statistic), float(min(1.0, max(0.0, p_value)))


# ---------------------------------------------------------------------------
# Jensen-Shannon divergence
# ---------------------------------------------------------------------------


def jensen_shannon_divergence(
    expected: Any,
    actual: Any,
    buckets: int = 20,
    base: float = 2.0,
    epsilon: float = 1e-12,
) -> float:
    """Jensen-Shannon divergence between the two empirical distributions.

    ``buckets`` equal-width bins span the pooled range.  The result is expressed
    in ``base`` units: with the default ``base=2`` it is in bits and bounded by
    ``log2(2) = 1``; pass ``base=math.e`` for nats, or ``base=None`` for nats.
    Identical distributions return exactly ``0.0``.
    """

    reference = _require_samples(expected, "expected")
    current = _require_samples(actual, "actual")

    buckets = max(2, int(buckets))
    lower = float(min(reference.min(), current.min()))
    upper = float(max(reference.max(), current.max()))
    if not math.isfinite(lower) or not math.isfinite(upper) or upper <= lower:
        width = max(abs(lower) * 1e-6, 1e-9)
        lower, upper = lower - width, upper + width

    edges = np.linspace(lower, upper, buckets + 1)
    edges[0] = -np.inf
    edges[-1] = np.inf

    eps = float(epsilon)
    p = np.clip(_proportions(reference, edges), eps, None)
    q = np.clip(_proportions(current, edges), eps, None)
    p = p / p.sum()
    q = q / q.sum()
    m = 0.5 * (p + q)

    def _kl(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.sum(a * np.log(a / b)))

    divergence = 0.5 * _kl(p, m) + 0.5 * _kl(q, m)
    if base is None:
        return float(divergence)
    divisor = math.log(float(base))
    if divisor <= 0.0:
        raise ValueError("base must be > 1 (or None for nats)")
    return float(divergence / divisor)


# ---------------------------------------------------------------------------
# Severity / verdict
# ---------------------------------------------------------------------------


def psi_severity(
    psi: float, thresholds: Optional[Mapping[str, float]] = None
) -> str:
    """Map a PSI value to ``"none" | "moderate" | "major"``.

    Standard bands: ``< 0.1`` none, ``0.1 - 0.25`` moderate, ``> 0.25`` major.
    The upper band boundary is inclusive for *moderate* (major requires
    strictly greater than ``psi_major``).
    """

    limits = _merged_thresholds(thresholds)
    try:
        value = float(psi)
    except (TypeError, ValueError):
        return SEVERITY_NONE
    if not math.isfinite(value) or value < limits["psi_none"]:
        return SEVERITY_NONE
    if value <= limits["psi_major"]:
        return SEVERITY_MODERATE
    return SEVERITY_MAJOR


def _worst_severity(severities: Iterable[str]) -> str:
    worst = SEVERITY_NONE
    for severity in severities:
        if _SEVERITY_ORDER.get(severity, 0) > _SEVERITY_ORDER[worst]:
            worst = severity
    return worst


def _evaluate_feature(
    expected: np.ndarray,
    actual: np.ndarray,
    limits: Mapping[str, float],
    psi_override: Optional[float] = None,
) -> Dict[str, Any]:
    """Compute every statistic/verdict for a single feature."""

    psi = (
        float(psi_override)
        if psi_override is not None
        else population_stability_index(expected, actual, buckets=10)
    )
    d_statistic, p_value = kolmogorov_smirnov_statistic(expected, actual)
    jsd = jensen_shannon_divergence(expected, actual)

    severity = psi_severity(psi, limits)
    ks_drifted = bool(
        p_value < limits["ks_pvalue"] and d_statistic > limits["ks_statistic"]
    )
    jsd_drifted = bool(jsd > limits["jsd"])

    if severity == SEVERITY_MAJOR:
        recommendation = "retrain/investigate immediately: reference distribution no longer applies"
    elif severity == SEVERITY_MODERATE:
        recommendation = "monitor closely and schedule retraining if the trend continues"
    elif ks_drifted or jsd_drifted:
        recommendation = "shape shift detected without PSI alarm: inspect feature pipeline"
    else:
        recommendation = "no action required"

    return {
        "psi": round(float(psi), 12),
        "ks_statistic": round(float(d_statistic), 12),
        "ks_pvalue": round(float(p_value), 12),
        "jensen_shannon_divergence": round(float(jsd), 12),
        "psi_severity": severity,
        "ks_drifted": ks_drifted,
        "jsd_drifted": jsd_drifted,
        "severity": severity if severity != SEVERITY_NONE else (
            SEVERITY_MODERATE if (ks_drifted or jsd_drifted) else SEVERITY_NONE
        ),
        "drifted": bool(
            severity != SEVERITY_NONE or ks_drifted or jsd_drifted
        ),
        "verdict": "drift"
        if (severity != SEVERITY_NONE or ks_drifted or jsd_drifted)
        else "stable",
        "recommendation": recommendation,
    }


def _set_feature_gauges(psi_by_feature: Mapping[str, float]) -> None:
    for feature, value in psi_by_feature.items():
        try:
            feature_drift_psi_gauge.labels(feature=str(feature)).set(float(value))
        except Exception:  # pragma: no cover - metrics must never break scoring
            logger.debug("Could not publish PSI gauge for feature %r", feature)


def detect_drift(
    reference: Any,
    current: Any,
    thresholds: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    """Compare ``current`` against ``reference`` and return a drift report.

    Both arguments accept either a mapping ``{feature_name: samples}`` or a
    pandas DataFrame.  The returned dictionary is JSON-serialisable and contains
    per-feature PSI/KS/JSD, per-feature verdicts and an overall verdict::

        {
          "generated_at": "...",
          "thresholds": {...},
          "features": {
            "lcr": {"psi": 0.03, "ks_statistic": 0.05, "ks_pvalue": 0.41,
                    "jensen_shannon_divergence": 0.01, "severity": "none",
                    "verdict": "stable", ...}
          },
          "overall": {
            "verdict": "drift", "severity": "major",
            "drifted_features": ["lcr"], "n_features": 1, "n_drifted": 1,
            "max_psi": 0.31, "max_psi_feature": "lcr",
            "psi_by_feature": {"lcr": 0.31}, "missing_features": []
          }
        }
    """

    limits = _merged_thresholds(thresholds)
    reference_map = _as_feature_mapping(reference)
    current_map = _as_feature_mapping(current)

    shared = [name for name in reference_map if name in current_map]
    missing = sorted(name for name in reference_map if name not in current_map)
    extra = sorted(name for name in current_map if name not in reference_map)

    features: Dict[str, Dict[str, Any]] = {}
    for name in shared:
        expected = reference_map[name]
        actual = current_map[name]

        if expected.size == 0 or actual.size == 0:
            features[name] = {
                "psi": None,
                "ks_statistic": None,
                "ks_pvalue": None,
                "jensen_shannon_divergence": None,
                "psi_severity": SEVERITY_NONE,
                "ks_drifted": False,
                "jsd_drifted": False,
                "severity": SEVERITY_NONE,
                "drifted": False,
                "verdict": "unknown",
                "error": "empty sample after dropping non-finite values",
            }
            continue

        try:
            features[name] = _evaluate_feature(expected, actual, limits)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Drift evaluation failed for feature %r: %s", name, exc)
            features[name] = {
                "psi": None,
                "ks_statistic": None,
                "ks_pvalue": None,
                "jensen_shannon_divergence": None,
                "psi_severity": SEVERITY_NONE,
                "ks_drifted": False,
                "jsd_drifted": False,
                "severity": SEVERITY_NONE,
                "drifted": False,
                "verdict": "unknown",
                "error": str(exc),
            }

    evaluated = {
        name: info
        for name, info in features.items()
        if info.get("psi") is not None
    }
    psi_by_feature = {name: info["psi"] for name, info in evaluated.items()}
    _set_feature_gauges(psi_by_feature)

    drifted_features = sorted(
        name for name, info in evaluated.items() if info.get("drifted")
    )
    severities = [info["severity"] for info in evaluated.values()]
    overall_severity = _worst_severity(severities) if severities else SEVERITY_NONE

    if evaluated:
        max_psi_feature = max(psi_by_feature, key=lambda name: psi_by_feature[name])
        max_psi = psi_by_feature[max_psi_feature]
    else:
        max_psi_feature = None
        max_psi = None

    return {
        "generated_at": _now_iso(),
        "thresholds": dict(limits),
        "features": features,
        "overall": {
            "verdict": "drift" if drifted_features else "stable",
            "severity": overall_severity,
            "drifted_features": drifted_features,
            "n_features": len(evaluated),
            "n_drifted": len(drifted_features),
            "max_psi": max_psi,
            "max_psi_feature": max_psi_feature,
            "psi_by_feature": psi_by_feature,
            "missing_in_current": missing,
            "extra_in_current": extra,
        },
    }


# ---------------------------------------------------------------------------
# Persistable reference-distribution monitor
# ---------------------------------------------------------------------------


class FeatureDriftMonitor:
    """Compare live inference features against a training reference summary.

    The summary stores, per feature:

    * ``bin_edges`` -- finite *interior* edges of the training quantile bins
      (the outer bins are open, so no infinities need to be serialised);
    * ``expected_proportions`` -- training histogram proportions per bin;
    * ``reference_sample`` -- a bounded reservoir of the training values, which
      keeps a genuine two-sample KS test possible after a restart;
    * descriptive statistics (count/mean/std/min/max).

    Everything round-trips through JSON (:meth:`to_json` / :meth:`from_json`),
    and :meth:`score` publishes ``beacon_feature_drift_psi{feature=...}``.
    """

    def __init__(
        self,
        buckets: int = 10,
        epsilon: float = DEFAULT_EPSILON,
        max_reference_samples: int = 2000,
        name: str = "beacon-default",
    ) -> None:
        if int(buckets) < 2:
            raise ValueError("buckets must be >= 2")
        if int(max_reference_samples) < 2:
            raise ValueError("max_reference_samples must be >= 2")

        self.buckets = int(buckets)
        self.epsilon = float(epsilon)
        self.max_reference_samples = int(max_reference_samples)
        self.name = str(name)
        self.created_at = _now_iso()
        self._features: Dict[str, Dict[str, Any]] = {}

    # -- construction -------------------------------------------------------
    def _summarise(self, values: np.ndarray) -> Dict[str, Any]:
        edges = _quantile_edges(values, self.buckets)
        full = _full_edges(edges)
        proportions = _proportions(values, full)

        if values.size > self.max_reference_samples:
            # Deterministic, evenly spaced subsample (no RNG state to manage).
            indices = np.linspace(
                0, values.size - 1, self.max_reference_samples
            ).astype(int)
            sample = values[indices]
        else:
            sample = values

        return {
            "bin_edges": [float(edge) for edge in edges[1:-1]],
            "expected_proportions": [float(p) for p in proportions],
            "reference_sample": [float(v) for v in sample],
            "n_samples": int(values.size),
            "mean": float(values.mean()),
            "std": float(values.std()),
            "min": float(values.min()),
            "max": float(values.max()),
            "buckets": int(proportions.size),
        }

    def fit(self, reference: Any, feature_names: Optional[Sequence[str]] = None) -> "FeatureDriftMonitor":
        """Learn the reference distribution summary from training data."""

        mapping = _as_feature_mapping(reference)
        if feature_names is not None:
            wanted = [str(name) for name in feature_names]
            mapping = {name: mapping[name] for name in wanted if name in mapping}

        summarised: Dict[str, Dict[str, Any]] = {}
        for name, values in mapping.items():
            if values.size == 0:
                logger.warning("Skipping feature %r: no finite reference samples", name)
                continue
            summarised[name] = self._summarise(values)

        self._features = summarised
        self.created_at = _now_iso()
        return self

    # -- introspection ------------------------------------------------------
    @property
    def feature_names(self) -> List[str]:
        return sorted(self._features)

    @property
    def is_fitted(self) -> bool:
        return bool(self._features)

    @property
    def reference_size(self) -> int:
        return sum(int(info["n_samples"]) for info in self._features.values())

    def summarise_feature(self, feature: str) -> Dict[str, Any]:
        if feature not in self._features:
            raise KeyError(f"feature {feature!r} is not part of the reference summary")
        return dict(self._features[feature])

    # -- scoring ------------------------------------------------------------
    def psi(self, feature: str, values: Any) -> float:
        """PSI of ``values`` against the stored *training* bins for ``feature``."""

        if feature not in self._features:
            raise KeyError(f"feature {feature!r} is not part of the reference summary")
        current = _require_samples(values, "values")

        info = self._features[feature]
        interior = np.asarray(info["bin_edges"], dtype=float)
        eps = self.epsilon

        if interior.size:
            # Normal case: use the frozen training quantile bins (outer bins open).
            full = np.concatenate(([-np.inf], interior, [np.inf]))
            expected = np.clip(
                np.asarray(info["expected_proportions"], dtype=float), eps, None
            )
        else:
            # Degenerate (constant) training reference: the quantile bins
            # collapsed.  Bin equal-width over the pooled range so a genuine
            # level shift is still detected instead of always scoring 0.
            reference_sample = self._reference_array(feature)
            if reference_sample.size == 0:  # pragma: no cover - defensive
                raise ValueError(f"feature {feature!r} has no stored reference samples")
            lower = float(min(reference_sample.min(), current.min()))
            upper = float(max(reference_sample.max(), current.max()))
            if upper <= lower:
                return 0.0
            full = np.linspace(lower, upper, self.buckets + 1)
            full[0], full[-1] = -np.inf, np.inf
            expected = np.clip(_proportions(reference_sample, full), eps, None)

        actual = np.clip(_proportions(current, full), eps, None)
        if actual.size != expected.size:  # pragma: no cover - defensive
            size = min(actual.size, expected.size)
            actual, expected = actual[:size], expected[:size]
        return float(np.sum((actual - expected) * np.log(actual / expected)))

    def _reference_array(self, feature: str) -> np.ndarray:
        return np.asarray(self._features[feature]["reference_sample"], dtype=float)

    def score(
        self,
        current: Any,
        thresholds: Optional[Mapping[str, float]] = None,
    ) -> Dict[str, Any]:
        """Score live features against the training summary.

        Returns the same JSON-serialisable structure as :func:`detect_drift`, but
        the PSI values come from the *frozen training bins* rather than from the
        live sample's own quantiles.  Also updates
        ``beacon_feature_drift_psi{feature=...}``.
        """

        if not self.is_fitted:
            raise RuntimeError("FeatureDriftMonitor must be fitted before scoring")

        limits = _merged_thresholds(thresholds)
        current_map = _as_feature_mapping(current)

        features: Dict[str, Dict[str, Any]] = {}
        for name, info in self._features.items():
            if name not in current_map:
                continue
            actual = current_map[name]
            if actual.size == 0:
                features[name] = {
                    "psi": None,
                    "ks_statistic": None,
                    "ks_pvalue": None,
                    "jensen_shannon_divergence": None,
                    "psi_severity": SEVERITY_NONE,
                    "ks_drifted": False,
                    "jsd_drifted": False,
                    "severity": SEVERITY_NONE,
                    "drifted": False,
                    "verdict": "unknown",
                    "error": "empty sample after dropping non-finite values",
                }
                continue

            reference_sample = self._reference_array(name)
            try:
                psi = (
                    self.psi(name, actual)
                    if reference_sample.size
                    else population_stability_index(
                        reference_sample, actual, buckets=self.buckets, epsilon=self.epsilon
                    )
                )
                features[name] = _evaluate_feature(
                    reference_sample, actual, limits, psi_override=psi
                )
                features[name]["reference_n_samples"] = int(info["n_samples"])
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Monitoring score failed for feature %r: %s", name, exc)
                features[name] = {
                    "psi": None,
                    "ks_statistic": None,
                    "ks_pvalue": None,
                    "jensen_shannon_divergence": None,
                    "psi_severity": SEVERITY_NONE,
                    "ks_drifted": False,
                    "jsd_drifted": False,
                    "severity": SEVERITY_NONE,
                    "drifted": False,
                    "verdict": "unknown",
                    "error": str(exc),
                }

        evaluated = {
            name: info for name, info in features.items() if info.get("psi") is not None
        }
        psi_by_feature = {name: info["psi"] for name, info in evaluated.items()}
        _set_feature_gauges(psi_by_feature)

        drifted_features = sorted(
            name for name, info in evaluated.items() if info.get("drifted")
        )
        overall_severity = (
            _worst_severity(info["severity"] for info in evaluated.values())
            if evaluated
            else SEVERITY_NONE
        )
        if psi_by_feature:
            max_psi_feature = max(psi_by_feature, key=lambda key: psi_by_feature[key])
            max_psi = psi_by_feature[max_psi_feature]
        else:
            max_psi_feature, max_psi = None, None

        return {
            "generated_at": _now_iso(),
            "monitor": self.name,
            "thresholds": dict(limits),
            "features": features,
            "overall": {
                "verdict": "drift" if drifted_features else "stable",
                "severity": overall_severity,
                "drifted_features": drifted_features,
                "n_features": len(evaluated),
                "n_drifted": len(drifted_features),
                "max_psi": max_psi,
                "max_psi_feature": max_psi_feature,
                "psi_by_feature": psi_by_feature,
                "missing_in_current": sorted(
                    name for name in self._features if name not in current_map
                ),
                "extra_in_current": sorted(
                    name for name in current_map if name not in self._features
                ),
            },
        }

    # -- persistence --------------------------------------------------------
    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": _JSON_SCHEMA_VERSION,
            "kind": "beacon.feature_drift_monitor",
            "name": self.name,
            "created_at": self.created_at,
            "buckets": self.buckets,
            "epsilon": self.epsilon,
            "max_reference_samples": self.max_reference_samples,
            "n_features": len(self._features),
            "features": {
                name: dict(info) for name, info in self._features.items()
            },
        }

    def to_json(self, indent: Optional[int] = None) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FeatureDriftMonitor":
        if not isinstance(payload, Mapping):
            raise TypeError("payload must be a mapping")
        version = int(payload.get("schema_version", _JSON_SCHEMA_VERSION))
        if version != _JSON_SCHEMA_VERSION:
            raise ValueError(
                f"unsupported FeatureDriftMonitor schema_version {version}"
            )

        monitor = cls(
            buckets=int(payload.get("buckets", 10)),
            epsilon=float(payload.get("epsilon", DEFAULT_EPSILON)),
            max_reference_samples=int(payload.get("max_reference_samples", 2000)),
            name=str(payload.get("name", "beacon-default")),
        )
        monitor.created_at = str(payload.get("created_at", _now_iso()))

        features = payload.get("features") or {}
        if not isinstance(features, Mapping):
            raise TypeError("'features' must be a mapping")

        restored: Dict[str, Dict[str, Any]] = {}
        for name, info in features.items():
            entry = dict(info)
            entry["bin_edges"] = [float(edge) for edge in entry.get("bin_edges", [])]
            entry["expected_proportions"] = [
                float(p) for p in entry.get("expected_proportions", [])
            ]
            entry["reference_sample"] = [
                float(v) for v in entry.get("reference_sample", [])
            ]
            entry["n_samples"] = int(entry.get("n_samples", len(entry["reference_sample"])))
            restored[str(name)] = entry
        monitor._features = restored
        return monitor

    @classmethod
    def from_json(cls, payload: Union[str, bytes, Mapping[str, Any]]) -> "FeatureDriftMonitor":
        if isinstance(payload, (str, bytes, bytearray)):
            return cls.from_dict(json.loads(payload))
        return cls.from_dict(payload)

    def save(self, path: Union[str, os.PathLike[str]]) -> str:
        target = os.fspath(path)
        directory = os.path.dirname(os.path.abspath(target))
        if directory:
            os.makedirs(directory, exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(self.to_json(indent=2))
        return target

    @classmethod
    def load(cls, path: Union[str, os.PathLike[str]]) -> "FeatureDriftMonitor":
        with open(os.fspath(path), "r", encoding="utf-8") as handle:
            return cls.from_json(handle.read())

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<FeatureDriftMonitor name={self.name!r} features={len(self._features)} "
            f"buckets={self.buckets} fitted={self.is_fitted}>"
        )
