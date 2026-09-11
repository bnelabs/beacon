"""Domain exceptions for BEACON.

Every exception carries a stable machine-readable ``code`` so that API
responses, error logs, and Prometheus counters can distinguish "the upstream
provider is down" from "the provider returned data we refuse to trust".
Callers should catch :class:`BeaconError` and branch on ``code`` rather than
on message text.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class BeaconError(Exception):
    """Base class for all BEACON domain errors."""

    code: str = "BEACON_ERROR"
    http_status: int = 500
    severity: str = "error"

    def __init__(
        self,
        message: str,
        *,
        context: Optional[Dict[str, Any]] = None,
        cause: Optional[BaseException] = None,
    ) -> None:
        self.message = message
        self.context: Dict[str, Any] = dict(context or {})
        self.cause = cause
        super().__init__(message)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise the error for API responses and structured logs."""
        payload: Dict[str, Any] = {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "context": self.context,
        }
        if self.cause is not None:
            payload["cause"] = f"{type(self.cause).__name__}: {self.cause}"
        return payload

    def __str__(self) -> str:
        if not self.context:
            return self.message
        details = ", ".join(f"{key}={value!r}" for key, value in self.context.items())
        return f"{self.message} ({details})"


class DataIngestionError(BeaconError):
    """Base class for failures while acquiring data from a provider."""

    code = "DATA_INGESTION_FAILED"
    http_status = 502
    severity = "error"


class DataSourceUnavailableError(DataIngestionError):
    """The upstream provider could not be reached or refused the request.

    Covers network failures, timeouts, rate limits, and authentication errors.
    """

    code = "DATA_SOURCE_UNAVAILABLE"
    http_status = 503


class DatasetMissingError(DataIngestionError):
    """A dataset the provider is expected to serve is absent locally.

    This is the correct failure for a file-backed plugin whose dataset has not
    been downloaded. It must never be answered with synthesised data.
    """

    code = "DATASET_MISSING"
    http_status = 503


class SchemaValidationError(DataIngestionError):
    """The provider returned data that does not match the expected schema."""

    code = "SCHEMA_INVALID"
    http_status = 502


class EmptyDatasetError(DataIngestionError):
    """The provider returned no rows for the requested scope or period."""

    code = "EMPTY_DATASET"
    http_status = 502


class DataQualityError(DataIngestionError):
    """Collected data exists but is not trustworthy enough to act on.

    Predictions and training must be blocked while this is raised.
    """

    code = "DATA_QUALITY_FAILED"
    http_status = 422
    severity = "critical"


class PredictionBlockedError(BeaconError):
    """A prediction was attempted without a verified data-quality attestation."""

    code = "PREDICTION_BLOCKED"
    http_status = 409
    severity = "critical"
