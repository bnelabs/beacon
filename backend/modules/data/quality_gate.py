"""Data-quality gate.

A risk platform must not train or predict on data it cannot vouch for. This
module turns that principle into an enforced precondition: collected datasets
are evaluated against an explicit :class:`QualityPolicy`, and anything that
fails raises a typed error instead of quietly flowing downstream.

The gate owns its verdict twice over:

* It re-derives the structural checks (row counts, columns, missingness,
  freshness) rather than trusting a composite ``fit_for_engine`` flag. That flag
  is a weighted average, so a payload that is *completely empty* still scores
  70/100 -- the missing-value and consistency terms are vacuously perfect -- and
  would otherwise be certified.
* It computes the **composite quality score itself** from
  :class:`QualityComponents`, never from a caller-supplied scalar. The pipeline
  hands over its sub-scores (completeness, consistency, timeliness, accuracy)
  and the gate applies the weights. A caller therefore cannot inject an
  optimistic score that the gate would then inherit, because there is no
  parameter through which to inject one.

Stationarity: reported, not certified away
------------------------------------------

The gate also runs the KPSS stationarity test (see
:mod:`backend.modules.data.fractional`) on each non-empty value column, because
a prediction engine that regresses non-stationary levels on one another can
produce a spurious fit no accuracy score will reveal. The deliberate decision is
to **report non-stationarity as a finding rather than fail certification by
default**, and to make failing an explicit opt-in (``require_stationarity``).

The reasoning is that this gate certifies *raw collected* data, and raw
financial levels are non-stationary by construction: prices, exchange rates and
nominal aggregates are I(1). If a unit root were fatal here, the gate would
reject the standard input of the very models that are built to handle it -- the
same module already ships fractional differencing precisely so that levels can
be stationarised at the feature stage -- and operators would have no compliant
way to ingest a macro series, which in practice means the gate gets disabled.
Failing everything and silently passing everything are both worse than a
finding that is always recorded: non-stationary and unassessable columns are
written into the attestation with the statistic and the verdict, logged as a
warning, and can be made blocking per deployment with
``QualityPolicy.require_stationarity``.

Degenerate input is never waved through. An empty payload is still rejected
structurally and independently of the composite (section 2A of the executive
review); a value column with no finite observations or with zero variance is a
hard failure, because no stationarity verdict -- and no information -- can be
extracted from it. A column that is simply too short to test is reported as a
warning rather than a failure, since sample size is already governed by the
row-count checks.

Governance-critical state travels as an explicit argument, never through
``DataFrame.attrs``: pandas does not preserve ``attrs`` through ``groupby``,
``merge``, ``concat``, or most reshaping, so a pipeline that transforms the
frame before prediction can silently lose the attestation.
:class:`AttestationResolver` is the single place where a prediction is allowed
to proceed, and the only way to skip it is the environment-gated
``BEACON_ALLOW_UNVERIFIED_DATA`` override, which is refused outright in
production.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Set

import numpy as np
import pandas as pd

from backend.exceptions import (
    DataQualityError,
    EmptyDatasetError,
    PredictionBlockedError,
    SchemaValidationError,
)
from .fractional import KPSS_CRITICAL_VALUES, KPSS_MIN_OBSERVATIONS, kpss_test

logger = logging.getLogger(__name__)

# Sink signature: (source_name, issue_description, severity)
AlertSink = Callable[[str, str, str], None]

#: Component weights owned by the platform, not by a caller. They are the same
#: weights the DATA pipeline used before this module owned the composite, kept
#: identical so historic scores stay comparable.
DEFAULT_COMPONENT_WEIGHTS: Dict[str, float] = {
    "completeness": 0.25,
    "consistency": 0.25,
    "timeliness": 0.20,
    "accuracy": 0.30,
}

#: Structural checks that make up the gate-measured "consistency" sub-score.
STRUCTURAL_CHECKS: Sequence[str] = (
    "datasets_present",
    "total_rows",
    "rows_per_dataset",
    "required_columns",
    "value_column",
    "missing_ratio",
)

_COMPONENT_NAMES: Sequence[str] = ("completeness", "consistency", "timeliness", "accuracy")

#: Environments in which the unverified-data override is refused outright.
PRODUCTION_ENVIRONMENTS = frozenset({"production", "prod"})

#: The single environment variable that may permit prediction without an attestation.
UNVERIFIED_OVERRIDE_ENV = "BEACON_ALLOW_UNVERIFIED_DATA"

_ENVIRONMENT_ENV_VARS: Sequence[str] = ("BEACON_ENV", "ENVIRONMENT", "APP_ENV")


def resolve_environment(environ: Optional[Mapping[str, str]] = None) -> str:
    """Return the active deployment environment, defaulting to ``development``."""
    source: Mapping[str, str] = os.environ if environ is None else environ
    for name in _ENVIRONMENT_ENV_VARS:
        value = source.get(name)
        if value is not None and str(value).strip():
            return str(value).strip().lower()
    return "development"


def unverified_override_requested(environ: Optional[Mapping[str, str]] = None) -> bool:
    """Whether the explicit unverified-data override was requested."""
    source: Mapping[str, str] = os.environ if environ is None else environ
    raw = source.get(UNVERIFIED_OVERRIDE_ENV)
    return str(raw).strip().lower() in {"1", "true", "yes", "on"} if raw is not None else False


@dataclass(frozen=True)
class QualityComponents:
    """Sub-scores a payload's quality is decomposed into.

    ``None`` means "not measured", not "zero": the composite renormalises its
    weights over the components that are actually present, so a caller that
    cannot measure timeliness does not silently drag the score down. Out-of-range
    or non-finite values are rejected rather than clamped.
    """

    completeness: Optional[float] = None
    consistency: Optional[float] = None
    timeliness: Optional[float] = None
    accuracy: Optional[float] = None

    @classmethod
    def from_mapping(cls, payload: Optional[Mapping[str, Any]]) -> "QualityComponents":
        """Build components from a mapping, ignoring unknown keys."""
        if payload is None:
            return cls()
        if isinstance(payload, QualityComponents):
            return payload
        if not isinstance(payload, Mapping):
            raise SchemaValidationError(
                f"quality components must be a mapping, got {type(payload).__name__}",
            )
        return cls(**{name: payload.get(name) for name in _COMPONENT_NAMES if name in payload})

    def to_dict(self) -> Dict[str, Optional[float]]:
        return {name: getattr(self, name) for name in _COMPONENT_NAMES}

    def validated(self) -> "QualityComponents":
        """Raise ``ValueError`` unless every present component is a percentage."""
        for name in _COMPONENT_NAMES:
            value = getattr(self, name)
            if value is None:
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"{name} must be a number in [0, 100], got {value!r}") from exc
            if not math.isfinite(numeric) or not 0.0 <= numeric <= 100.0:
                raise ValueError(f"{name} must be within [0, 100], got {value!r}")
        return self

    def composite(self, weights: Optional[Mapping[str, float]] = None) -> float:
        """Weighted mean over the present components, weights renormalised.

        The gate calls this; callers do not compute a composite and hand it over.
        """
        effective = dict(DEFAULT_COMPONENT_WEIGHTS if weights is None else weights)
        weighted = 0.0
        total_weight = 0.0
        for name, weight in effective.items():
            value = getattr(self, name, None)
            if value is None:
                continue
            numeric_weight = float(weight)
            if numeric_weight < 0.0 or not math.isfinite(numeric_weight):
                raise ValueError(f"weight for {name} must be a finite non-negative number")
            weighted += float(value) * numeric_weight
            total_weight += numeric_weight
        if total_weight == 0.0:
            return 0.0
        return weighted / total_weight


@dataclass(frozen=True)
class QualityPolicy:
    """Thresholds a data payload must satisfy before the model may consume it."""

    min_datasets: int = 1
    min_rows_per_dataset: int = 2
    min_total_rows: int = 10
    max_missing_ratio: float = 0.3
    min_quality_score: float = 70.0
    min_completeness: float = 80.0
    required_columns: Sequence[str] = ("Date",)
    value_columns: Sequence[str] = ("Value", "Close")
    max_staleness_days: Optional[int] = None
    score_weights: Optional[Mapping[str, float]] = None
    check_stationarity: bool = True
    stationarity_significance: str = "5%"
    require_stationarity: bool = False

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["required_columns"] = list(self.required_columns)
        payload["value_columns"] = list(self.value_columns)
        payload["score_weights"] = dict(self.score_weights or DEFAULT_COMPONENT_WEIGHTS)
        return payload


@dataclass
class QualityCheck:
    """Outcome of a single quality assertion."""

    name: str
    passed: bool
    severity: str
    detail: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class QualityAttestation:
    """Signed-off verdict on a payload, carried alongside it into the model.

    ``quality_score`` is always the gate's own arithmetic over ``components``.
    ``score_source`` records where the sub-scores came from (``components``,
    ``measured``, ``empty_payload``, or ``legacy_record``) and ``snapshot_id``
    names the content-addressed copy of the exact rows that were verified.
    """

    job_id: str
    verified: bool
    checked_at: str
    checks: List[QualityCheck] = field(default_factory=list)
    dataset_row_counts: Dict[str, int] = field(default_factory=dict)
    quality_score: Optional[float] = None
    completeness: Optional[float] = None
    components: Dict[str, Optional[float]] = field(default_factory=dict)
    score_source: Optional[str] = None
    snapshot_id: Optional[str] = None

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
            "quality_score": None if self.quality_score is None else round(float(self.quality_score), 6),
            "snapshot_id": self.snapshot_id,
            "dataset_row_counts": dict(sorted(self.dataset_row_counts.items())),
            "checks": [
                {"name": check.name, "passed": bool(check.passed), "severity": check.severity}
                for check in self.checks
            ],
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "verified": self.verified,
            "checked_at": self.checked_at,
            "quality_score": self.quality_score,
            "completeness": self.completeness,
            "components": dict(self.components),
            "score_source": self.score_source,
            "snapshot_id": self.snapshot_id,
            "attestation_id": self.attestation_id,
            "dataset_row_counts": dict(self.dataset_row_counts),
            "checks": [check.to_dict() for check in self.checks],
            "failures": [check.to_dict() for check in self.failures],
        }

    def summary(self) -> str:
        if self.verified:
            return f"Data quality verified for job {self.job_id} ({len(self.checks)} checks passed)"
        reasons = "; ".join(f"{check.name}: {check.detail}" for check in self.failures)
        return f"Data quality rejected for job {self.job_id} - {reasons}"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "QualityAttestation":
        """Rebuild an attestation persisted on a job result."""
        return cls(
            job_id=payload.get("job_id", "unknown"),
            verified=bool(payload.get("verified", False)),
            checked_at=payload.get("checked_at", ""),
            checks=[QualityCheck(**check) for check in payload.get("checks", [])],
            dataset_row_counts=dict(payload.get("dataset_row_counts") or {}),
            quality_score=payload.get("quality_score"),
            completeness=payload.get("completeness"),
            components=dict(payload.get("components") or {}),
            score_source=payload.get("score_source"),
            snapshot_id=payload.get("snapshot_id"),
        )

    @classmethod
    def from_legacy_result(
        cls, result: Mapping[str, Any], *, job_id: str = "unknown"
    ) -> Optional["QualityAttestation"]:
        """Reconstruct a verdict for jobs recorded before attestations existed.

        Legacy records only stored the composite score, which accepts an empty
        payload. The reconstruction therefore requires ``fit_for_engine`` *and* a
        passing score, and flags itself as reconstructed so the provenance is
        visible in the audit trail. Callers remain responsible for verifying the
        payload they actually loaded.
        """
        if not result or "fit_for_engine" not in result:
            return None

        fit = bool(result.get("fit_for_engine"))
        raw_score = result.get("quality_score")
        score = None if raw_score is None else float(raw_score)
        passed = fit and score is not None and score >= QualityPolicy().min_quality_score

        return cls(
            job_id=job_id,
            verified=passed,
            checked_at="",
            checks=[
                QualityCheck(
                    name="legacy_record",
                    passed=passed,
                    severity="critical",
                    detail=(
                        "reconstructed from a pre-hardening job record "
                        f"(fit_for_engine={fit}, quality_score={score})"
                    ),
                )
            ],
            quality_score=score,
            completeness=result.get("completeness"),
            score_source="legacy_record",
        )


class DataQualityGate:
    """Evaluates and enforces :class:`QualityPolicy` against collected data."""

    def __init__(self, policy: Optional[QualityPolicy] = None, alert_sink: Optional[AlertSink] = None):
        self.policy = policy or QualityPolicy()
        self.alert_sink = alert_sink

    # -- scoring ------------------------------------------------------------

    def effective_weights(self) -> Mapping[str, float]:
        """Component weights this gate applies (policy override or platform default)."""
        return self.policy.score_weights or DEFAULT_COMPONENT_WEIGHTS

    def composite_score(self, components: QualityComponents) -> float:
        """The gate's own composite. The caller never supplies this number."""
        return float(components.validated().composite(self.effective_weights()))

    def measure_components(self, datasets: Mapping[str, pd.DataFrame]) -> QualityComponents:
        """Sub-scores the gate can compute from the payload alone.

        Completeness comes from the missing-cell ratio; consistency is the share
        of the structural checks that pass; timeliness is measured only when the
        policy sets ``max_staleness_days``; accuracy is not measurable from a
        bare payload and stays ``None`` (so it is left out of the composite).

        A payload with no non-empty dataset has no measurable quality at all, so
        it scores exactly ``0.0`` instead of inheriting vacuously perfect
        sub-scores.
        """
        non_empty = {
            code: df for code, df in datasets.items() if df is not None and not df.empty
        }
        if not non_empty:
            return QualityComponents(completeness=0.0, consistency=0.0)

        missing_ratio = self._overall_missing_ratio(non_empty)
        completeness = 100.0 * (1.0 - missing_ratio)

        structural = self._structural_checks(non_empty)
        passed = sum(1 for check in structural if check.passed)
        consistency = 100.0 * passed / len(structural) if structural else 0.0

        timeliness: Optional[float] = None
        if self.policy.max_staleness_days is not None:
            staleness = self._staleness_days(non_empty)
            timeliness = (
                100.0
                if staleness is not None and staleness <= self.policy.max_staleness_days
                else 0.0
            )

        return QualityComponents(
            completeness=completeness,
            consistency=consistency,
            timeliness=timeliness,
            accuracy=None,
        )

    # -- evaluation ---------------------------------------------------------

    def evaluate(
        self,
        datasets: Mapping[str, pd.DataFrame],
        *,
        job_id: str,
        components: Optional[QualityComponents] = None,
        snapshot_id: Optional[str] = None,
        event_series_codes: Optional[Set[str]] = None,
    ) -> QualityAttestation:
        """Evaluate a payload and return an attestation carrying the gate's score.

        ``components`` is the *raw sub-score* evidence from the pipeline. The
        composite is computed here from those sub-scores; there is deliberately no
        parameter for a pre-computed score, because accepting one would let a
        flawed weighting upstream decide the gate's verdict.
        """
        policy = self.policy
        row_counts = {
            code: int(len(df)) for code, df in datasets.items() if df is not None
        }
        non_empty = {code: df for code, df in datasets.items() if df is not None and not df.empty}

        # One implementation of the structural assertions serves both the verdict
        # and the gate-measured consistency sub-score.
        checks: List[QualityCheck] = list(self._structural_checks(non_empty))

        def record(name: str, passed: bool, detail: str, severity: str = "critical") -> None:
            checks.append(QualityCheck(name=name, passed=passed, severity=severity, detail=detail))

        if policy.max_staleness_days is not None:
            staleness = self._staleness_days(non_empty)
            record(
                "freshness",
                staleness is not None and staleness <= policy.max_staleness_days,
                f"newest observation is {staleness} day(s) old"
                if staleness is not None
                else "no parseable Date column to assess freshness",
            )

        # Stationarity is reported for every non-empty value column. It is
        # deliberately outside ``_structural_checks`` so it does not enter the
        # consistency sub-score: the sub-score measures completeness of the
        # schema, while non-stationarity is a property of the data that is
        # expected for legitimate levels and must not silently move the gate's
        # arithmetic.
        if policy.check_stationarity:
            checks.extend(self._stationarity_checks(non_empty, event_series_codes=event_series_codes))

        # The composite is always the gate's own arithmetic.
        if not non_empty:
            resolved = QualityComponents(completeness=0.0, consistency=0.0)
            score_source = "empty_payload"
        elif components is not None:
            resolved = quality_components(components)
            score_source = "components"
        else:
            resolved = self.measure_components(datasets)
            score_source = "measured"

        resolved = resolved.validated()
        composite = float(resolved.composite(self.effective_weights()))

        record(
            "quality_score",
            composite >= policy.min_quality_score,
            f"quality score {composite:.1f} (source: {score_source}), "
            f"require >= {policy.min_quality_score}",
        )

        if policy.min_completeness is not None and resolved.completeness is not None:
            record(
                "completeness",
                resolved.completeness >= policy.min_completeness,
                f"completeness {resolved.completeness:.1f}%, require >= {policy.min_completeness}%",
            )

        return QualityAttestation(
            job_id=job_id,
            verified=all(check.passed for check in checks),
            checked_at=datetime.now(timezone.utc).isoformat(),
            checks=checks,
            dataset_row_counts=row_counts,
            quality_score=composite,
            completeness=resolved.completeness,
            components=resolved.to_dict(),
            score_source=score_source,
            snapshot_id=snapshot_id,
        )

    def enforce(
        self,
        datasets: Mapping[str, pd.DataFrame],
        *,
        job_id: str,
        components: Optional[QualityComponents] = None,
        snapshot_id: Optional[str] = None,
        event_series_codes: Optional[Set[str]] = None,
    ) -> QualityAttestation:
        """Evaluate and raise when the payload is not fit for consumption.

        Raises:
            EmptyDatasetError: When no dataset in the payload contains rows.
            DataQualityError: When the payload fails one or more quality checks.
        """
        attestation = self.evaluate(
            datasets,
            job_id=job_id,
            components=components,
            snapshot_id=snapshot_id,
            event_series_codes=event_series_codes,
        )
        if attestation.verified:
            logger.info(attestation.summary())
            return attestation

        total_rows = sum(attestation.dataset_row_counts.values())
        if total_rows == 0:
            error: DataQualityError = EmptyDatasetError(
                "No rows were collected; refusing to train or predict on an empty payload",
                context={"job_id": job_id, "dataset_row_counts": attestation.dataset_row_counts},
            )
        else:
            error = DataQualityError(
                "Collected data failed the quality gate",
                context={
                    "job_id": job_id,
                    "failures": [f"{check.name}: {check.detail}" for check in attestation.failures],
                    "dataset_row_counts": attestation.dataset_row_counts,
                    "quality_score": attestation.quality_score,
                },
            )

        self._emit_alert(job_id, attestation)
        raise error

    # -- consumption --------------------------------------------------------

    @staticmethod
    def require(attestation: Optional[QualityAttestation]) -> QualityAttestation:
        """Assert that a payload was attested before it is used for inference.

        Raises:
            PredictionBlockedError: When the attestation is missing or negative.
        """
        if attestation is None:
            raise PredictionBlockedError(
                "Prediction blocked: the input payload carries no data-quality attestation",
                context={"remediation": "run the DATA stage quality gate before predicting"},
            )
        if not attestation.verified:
            raise PredictionBlockedError(
                "Prediction blocked: the input payload failed data-quality verification",
                context={
                    "job_id": attestation.job_id,
                    "failures": [f"{check.name}: {check.detail}" for check in attestation.failures],
                },
            )
        return attestation

    @staticmethod
    def attestation_from_job_result(
        result: Optional[Mapping[str, Any]], *, job_id: str = "unknown"
    ) -> Optional[QualityAttestation]:
        """Resolve the attestation persisted on a data-collection job result.

        Prefers the full attestation written by the DATA stage and falls back to
        a reconstruction from the legacy scalar fields.
        """
        payload = (result or {}).get("quality_attestation")
        if payload:
            return QualityAttestation.from_dict(payload)
        return QualityAttestation.from_legacy_result(result or {}, job_id=job_id)

    # -- internals ----------------------------------------------------------

    def _structural_checks(self, datasets: Mapping[str, pd.DataFrame]) -> List[QualityCheck]:
        """Structural assertions in isolation, reused for the consistency sub-score."""
        policy = self.policy
        checks: List[QualityCheck] = []

        def record(name: str, passed: bool, detail: str) -> None:
            checks.append(QualityCheck(name=name, passed=passed, severity="critical", detail=detail))

        undersized = [
            code for code, df in datasets.items() if len(df) < policy.min_rows_per_dataset
        ]
        missing_columns = {
            code: [col for col in policy.required_columns if col not in df.columns]
            for code, df in datasets.items()
        }
        missing_columns = {code: cols for code, cols in missing_columns.items() if cols}
        missing_value_columns = [
            code
            for code, df in datasets.items()
            if policy.value_columns and not any(col in df.columns for col in policy.value_columns)
        ]
        missing_ratio = self._overall_missing_ratio(datasets)

        record(
            "datasets_present",
            len(datasets) >= policy.min_datasets,
            f"{len(datasets)} non-empty dataset(s), require >= {policy.min_datasets}",
        )
        record(
            "total_rows",
            sum(len(df) for df in datasets.values()) >= policy.min_total_rows,
            f"{sum(len(df) for df in datasets.values())} total rows, "
            f"require >= {policy.min_total_rows}",
        )
        record(
            "rows_per_dataset",
            not undersized,
            "all datasets meet the minimum row count"
            if not undersized
            else f"datasets below {policy.min_rows_per_dataset} rows: {sorted(undersized)}",
        )
        record(
            "required_columns",
            not missing_columns,
            "required columns present"
            if not missing_columns
            else f"missing required columns: {missing_columns}",
        )
        record(
            "value_column",
            not missing_value_columns,
            "value column present in every dataset"
            if not missing_value_columns
            else f"no {list(policy.value_columns)} column in: {sorted(missing_value_columns)}",
        )
        record(
            "missing_ratio",
            missing_ratio <= policy.max_missing_ratio,
            f"missing ratio {missing_ratio:.3f}, limit {policy.max_missing_ratio}",
        )
        return checks

    def _value_column(self, df: pd.DataFrame) -> Optional[str]:
        """First policy value column present in ``df``, or ``None``.

        The ``value_column`` structural check already fails a dataset that has
        none, so the stationarity scan skips such a frame instead of duplicating
        that verdict.
        """
        for column in self.policy.value_columns:
            if column in df.columns:
                return column
        return None

    def _stationarity_checks(
        self,
        datasets: Mapping[str, pd.DataFrame],
        *,
        event_series_codes: Optional[Set[str]] = None,
    ) -> List[QualityCheck]:
        """KPSS findings for every non-empty value column.

        One check per ``(dataset, value column)``. A column is *non-stationary*
        only when KPSS rejects stationarity under **both** the level and the
        trend null; rejecting only the level null is the signature of a
        trend-stationary series and is acceptable. A variant that cannot be
        computed (for example a trend so clean its residuals are numerical dust)
        cannot prove a unit root, so it is reported as unassessable rather than
        treated as evidence either way.

        The pass/fail mapping is where the report-versus-fail decision lives:
        an unfavourable or unassessable finding is recorded with
        ``severity="warning"`` and ``passed=True`` unless
        ``policy.require_stationarity`` is set, in which case it becomes a
        ``critical`` failure that blocks certification. A column with no finite
        observations or no variance is always a ``critical`` failure: there is
        nothing to assess and nothing to certify. See the module docstring for
        why reporting is the default for legitimate I(1) levels.
        """
        policy = self.policy
        for variant in ("level", "trend"):
            if policy.stationarity_significance not in KPSS_CRITICAL_VALUES[variant]:
                raise ValueError(
                    f"stationarity_significance {policy.stationarity_significance!r} "
                    f"is not a tabulated KPSS level; expected one of "
                    f"{sorted(KPSS_CRITICAL_VALUES[variant])}"
                )

        checks: List[QualityCheck] = []
        for code, df in datasets.items():
            column = self._value_column(df)
            if column is None:
                continue
            name = f"stationarity[{code}.{column}]"

            series = pd.to_numeric(df[column], errors="coerce").to_numpy(dtype=float)
            series = series[np.isfinite(series)]

            if series.size == 0:
                checks.append(
                    QualityCheck(
                        name=name,
                        passed=False,
                        severity="critical",
                        detail=(
                            "KPSS not assessable: the value column has no finite "
                            "observations, so it carries no information"
                        ),
                    )
                )
                continue
            if series.size < KPSS_MIN_OBSERVATIONS:
                checks.append(
                    QualityCheck(
                        name=name,
                        passed=True,
                        severity="warning",
                        detail=(
                            f"KPSS not assessed: {series.size} finite observation(s), "
                            f"need at least {KPSS_MIN_OBSERVATIONS}; sample size is "
                            f"governed by the row-count checks"
                        ),
                    )
                )
                continue
            if float(np.ptp(series)) == 0.0 and code in (event_series_codes or set()):
                checks.append(
                    QualityCheck(
                        name=name,
                        passed=True,
                        severity="warning",
                        detail=(
                            "stationarity not applicable: this declared event "
                            "series uses a constant occurrence marker; information "
                            "is carried by its event dates"
                        ),
                    )
                )
                continue
            if float(np.ptp(series)) == 0.0:
                checks.append(
                    QualityCheck(
                        name=name,
                        passed=False,
                        severity="critical",
                        detail=(
                            "KPSS not assessable: the value column is constant, so "
                            "its long-run variance is zero and it carries no "
                            "information"
                        ),
                    )
                )
                continue

            results: Dict[str, Optional[Any]] = {}
            fragments: List[str] = []
            for regression in ("level", "trend"):
                try:
                    result = kpss_test(
                        series,
                        regression=regression,
                        significance=policy.stationarity_significance,
                    )
                except ValueError as exc:
                    results[regression] = None
                    fragments.append(f"{regression}: not assessable ({exc})")
                else:
                    results[regression] = result
                    fragments.append(
                        f"{regression}: {result.statistic:.3f} "
                        f"({result.verdict} at {result.significance})"
                    )

            rejected = [
                regression
                for regression, result in results.items()
                if result is not None and not result.stationary
            ]
            accepted = [
                regression
                for regression, result in results.items()
                if result is not None and result.stationary
            ]
            if accepted:
                verdict = "stationary"
            elif len(rejected) == 2:
                verdict = "non-stationary"
            else:
                verdict = "unassessable"

            summary = "; ".join(fragments)
            if verdict == "stationary":
                checks.append(
                    QualityCheck(
                        name=name,
                        passed=True,
                        severity="critical",
                        detail=f"KPSS stationarity not rejected ({summary})",
                    )
                )
                continue

            blocking = bool(policy.require_stationarity)
            suffix = "" if blocking else "; reported, not blocking"
            if verdict == "non-stationary":
                detail = (
                    f"KPSS rejects stationarity under both level and trend "
                    f"({summary}){suffix}"
                )
            else:
                detail = f"KPSS stationarity could not be assessed ({summary}){suffix}"
            if not blocking:
                logger.warning("Data-quality finding for %s: %s", name, detail)
            checks.append(
                QualityCheck(
                    name=name,
                    passed=not blocking,
                    severity="critical" if blocking else "warning",
                    detail=detail,
                )
            )
        return checks

    def _emit_alert(self, job_id: str, attestation: QualityAttestation) -> None:
        logger.error(attestation.summary())
        if self.alert_sink is None:
            return
        for check in attestation.failures:
            severity = "critical" if check.severity == "critical" else "high"
            try:
                self.alert_sink(f"pipeline:{job_id}", f"{check.name}: {check.detail}", severity)
            except Exception:  # noqa: BLE001 - alerting must never mask the gate failure
                logger.exception("Data-quality alert sink failed for job %s", job_id)

    @staticmethod
    def _overall_missing_ratio(datasets: Mapping[str, pd.DataFrame]) -> float:
        total_cells = 0
        missing_cells = 0
        for df in datasets.values():
            total_cells += df.shape[0] * df.shape[1]
            missing_cells += int(df.isnull().sum().sum())
        if total_cells == 0:
            return 1.0
        return missing_cells / total_cells

    @staticmethod
    def _staleness_days(datasets: Mapping[str, pd.DataFrame]) -> Optional[int]:
        newest: Optional[pd.Timestamp] = None
        for df in datasets.values():
            if "Date" not in df.columns:
                continue
            dates = pd.to_datetime(df["Date"], errors="coerce").dropna()
            if dates.empty:
                continue
            candidate = dates.max()
            if newest is None or candidate > newest:
                newest = candidate
        if newest is None:
            return None
        reference = pd.Timestamp.now(tz=newest.tz) if newest.tz else pd.Timestamp.now()
        return int((reference - newest).days)


def quality_components(payload: Any) -> QualityComponents:
    """Coerce a mapping or :class:`QualityComponents` into a validated instance."""
    if isinstance(payload, QualityComponents):
        return payload
    return QualityComponents.from_mapping(payload)


class AttestationResolver:
    """Explicit, environment-gated resolution of the prediction attestation.

    Governance-critical state is passed as an argument, never smuggled through
    ``DataFrame.attrs``. A prediction without a verified attestation fails
    loudly; the only escape hatch is ``BEACON_ALLOW_UNVERIFIED_DATA``, honoured
    solely outside production, and requesting it in production raises at
    construction time instead of quietly weakening the gate.
    """

    def __init__(
        self,
        attestation: Optional[QualityAttestation] = None,
        *,
        environ: Optional[Mapping[str, str]] = None,
    ) -> None:
        self._environ: Mapping[str, str] = os.environ if environ is None else environ
        self.environment = resolve_environment(self._environ)
        self.allow_unverified = unverified_override_requested(self._environ)
        if self.allow_unverified and self.environment in PRODUCTION_ENVIRONMENTS:
            raise PredictionBlockedError(
                f"{UNVERIFIED_OVERRIDE_ENV} is set in environment '{self.environment}'; "
                "refusing to run predictions without a data-quality attestation in production",
                context={
                    "environment": self.environment,
                    "override": UNVERIFIED_OVERRIDE_ENV,
                },
            )
        if self.allow_unverified:
            logger.warning(
                "Predictions may run without a data-quality attestation: %s is enabled for "
                "environment '%s'. This is for exploratory use only.",
                UNVERIFIED_OVERRIDE_ENV,
                self.environment,
            )
        self.default_attestation = attestation

    def set_default(self, attestation: Optional[QualityAttestation]) -> None:
        """Attach the attestation this resolver falls back to."""
        self.default_attestation = attestation

    def resolve(
        self, attestation: Optional[QualityAttestation] = None
    ) -> Optional[QualityAttestation]:
        """Return a verified attestation or raise ``PredictionBlockedError``.

        The explicit argument wins over the resolver's default, so callers can
        thread the verdict through a pipeline as a value rather than relying on
        frame metadata surviving every transformation.
        """
        candidate = attestation if attestation is not None else self.default_attestation
        if candidate is None and self.allow_unverified:
            logger.warning(
                "Predicting without a data-quality attestation because %s is enabled",
                UNVERIFIED_OVERRIDE_ENV,
            )
            return None
        return DataQualityGate.require(candidate)
