"""Data-quality gate.

A risk platform must not train or predict on data it cannot vouch for. This
module turns that principle into an enforced precondition: collected datasets
are evaluated against an explicit :class:`QualityPolicy`, and anything that
fails raises a typed error instead of quietly flowing downstream.

The gate deliberately re-derives its own verdict rather than trusting the
composite ``fit_for_engine`` flag. That flag is a weighted average, so a
payload that is *completely empty* still scores 70/100 (the missing-value and
consistency terms are vacuously perfect) and would otherwise be certified.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence

import pandas as pd

from backend.exceptions import (
    DataQualityError,
    EmptyDatasetError,
    PredictionBlockedError,
    SchemaValidationError,
)

logger = logging.getLogger(__name__)

# Sink signature: (source_name, issue_description, severity)
AlertSink = Callable[[str, str, str], None]


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

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["required_columns"] = list(self.required_columns)
        payload["value_columns"] = list(self.value_columns)
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
    """Signed-off verdict on a payload, carried alongside it into the model."""

    job_id: str
    verified: bool
    checked_at: str
    checks: List[QualityCheck] = field(default_factory=list)
    dataset_row_counts: Dict[str, int] = field(default_factory=dict)
    quality_score: Optional[float] = None
    completeness: Optional[float] = None

    @property
    def failures(self) -> List[QualityCheck]:
        return [check for check in self.checks if not check.passed]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id,
            "verified": self.verified,
            "checked_at": self.checked_at,
            "quality_score": self.quality_score,
            "completeness": self.completeness,
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
        )


class DataQualityGate:
    """Evaluates and enforces :class:`QualityPolicy` against collected data."""

    def __init__(self, policy: Optional[QualityPolicy] = None, alert_sink: Optional[AlertSink] = None):
        self.policy = policy or QualityPolicy()
        self.alert_sink = alert_sink

    # -- evaluation ---------------------------------------------------------

    def evaluate(
        self,
        datasets: Mapping[str, pd.DataFrame],
        *,
        job_id: str,
        quality_score: Optional[float] = None,
        completeness: Optional[float] = None,
    ) -> QualityAttestation:
        policy = self.policy
        checks: List[QualityCheck] = []
        row_counts = {
            code: int(len(df)) for code, df in datasets.items() if df is not None
        }
        non_empty = {code: df for code, df in datasets.items() if df is not None and not df.empty}

        def record(name: str, passed: bool, detail: str, severity: str = "critical") -> None:
            checks.append(QualityCheck(name=name, passed=passed, severity=severity, detail=detail))

        record(
            "datasets_present",
            len(non_empty) >= policy.min_datasets,
            f"{len(non_empty)} non-empty dataset(s), require >= {policy.min_datasets}",
        )
        record(
            "total_rows",
            sum(row_counts.values()) >= policy.min_total_rows,
            f"{sum(row_counts.values())} total rows, require >= {policy.min_total_rows}",
        )

        undersized = [code for code, df in non_empty.items() if len(df) < policy.min_rows_per_dataset]
        record(
            "rows_per_dataset",
            not undersized,
            "all datasets meet the minimum row count"
            if not undersized
            else f"datasets below {policy.min_rows_per_dataset} rows: {sorted(undersized)}",
        )

        missing_columns: Dict[str, List[str]] = {}
        missing_value_columns: List[str] = []
        for code, df in non_empty.items():
            absent = [col for col in policy.required_columns if col not in df.columns]
            if absent:
                missing_columns[code] = absent
            if policy.value_columns and not any(col in df.columns for col in policy.value_columns):
                missing_value_columns.append(code)

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

        missing_ratio = self._overall_missing_ratio(non_empty)
        record(
            "missing_ratio",
            missing_ratio <= policy.max_missing_ratio,
            f"missing ratio {missing_ratio:.3f}, limit {policy.max_missing_ratio}",
        )

        if completeness is not None:
            record(
                "completeness",
                completeness >= policy.min_completeness,
                f"completeness {completeness:.1f}%, require >= {policy.min_completeness}%",
            )

        if quality_score is not None:
            record(
                "quality_score",
                quality_score >= policy.min_quality_score,
                f"quality score {quality_score:.1f}, require >= {policy.min_quality_score}",
            )

        if policy.max_staleness_days is not None:
            staleness = self._staleness_days(non_empty)
            record(
                "freshness",
                staleness is not None and staleness <= policy.max_staleness_days,
                f"newest observation is {staleness} day(s) old"
                if staleness is not None
                else "no parseable Date column to assess freshness",
            )

        attestation = QualityAttestation(
            job_id=job_id,
            verified=all(check.passed for check in checks),
            checked_at=datetime.now(timezone.utc).isoformat(),
            checks=checks,
            dataset_row_counts=row_counts,
            quality_score=quality_score,
            completeness=completeness,
        )
        return attestation

    def enforce(
        self,
        datasets: Mapping[str, pd.DataFrame],
        *,
        job_id: str,
        quality_score: Optional[float] = None,
        completeness: Optional[float] = None,
    ) -> QualityAttestation:
        """Evaluate and raise when the payload is not fit for consumption.

        Raises:
            EmptyDatasetError: When no dataset in the payload contains rows.
            DataQualityError: When the payload fails one or more quality checks.
        """
        attestation = self.evaluate(
            datasets, job_id=job_id, quality_score=quality_score, completeness=completeness
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
