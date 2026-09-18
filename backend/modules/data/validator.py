"""Data Validator — integrity checks and anomaly detection.

Rewritten in the sixth round. The previous validator claimed "quality checks
and anomaly detection" in its docstring but implemented exactly one check
(missing-cell ratio); ``anomalies_count`` stayed at its default ``0`` for every
dataset of every run, so the platform reported ``anomalies_detected: 0``
forever -- a silent lie of omission in the governance layer that exists to
surface exactly this. ``inconsistency_ratio`` and ``timeliness_score`` were
likewise never computed, so downstream reports rendered vacuous 100s. (The
quality gate re-derives its own structural consistency and is unaffected in
its *verdict*; the *reports* were the misleading part.)

The battery below is deliberately classical and auditable -- robust statistics
with named thresholds, no learned component, every finding carrying its kind,
count and a sample of offending positions:

* **duplicate timestamps** -- the same observation time twice is an integrity
  breach, not noise;
* **future timestamps** -- data published after the job's as-of is look-ahead
  at ingest time and is flagged rather than trusted;
* **point outliers** -- modified z-score (Iglewicz–Hoaglin, MAD-based) on the
  first differences, so trends and levels do not masquerade as anomalies;
  ``|MZ| > 3.5`` is the published threshold;
* **gap runs** -- consecutive missing observations longer than a reporting
  cycle candidate (default 5) indicate an interrupted publication;
* **scale breaks** -- a jump in the ratio of consecutive rolling medians
  beyond a factor of 10 indicates a unit change (percent vs ratio,
  thousands vs units), the classic silent corruption of macro series;
* **stale runs** -- long runs of byte-identical values indicate a feed that
  stopped updating while pretending to publish.

Nothing here imputes, repairs or deletes: the validator observes and reports.
Cleaning and gating decisions live elsewhere and consume this report.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

#: Modified z-score threshold (Iglewicz & Hoaglin's recommended 3.5).
MODIFIED_Z_THRESHOLD = 3.5
#: Minimum consecutive missing observations to count as a gap run.
MIN_GAP_RUN = 5
#: Rolling window (observations) for the scale-break median ratio.
SCALE_WINDOW = 20
#: log-ratio beyond which a unit/scale change is suspected (factor 10).
SCALE_BREAK_LOG_RATIO = np.log(10.0)
#: Minimum run length of identical values to call a feed stale.
MIN_STALE_RUN = 10
#: Days since the newest observation beyond which a dated dataset is stale.
TIMELINESS_MAX_DAYS = 40.0


@dataclass
class ValidationReport:
    critical_errors: int = 0
    warnings: list = None
    errors: list = None
    missing_ratio: float = 0.0
    inconsistency_ratio: float = 0.0
    timeliness_score: float = 1.0
    anomalies_count: int = 0
    #: Structured anomaly findings, sixth round: one entry per (dataset, kind).
    anomalies: List[Dict[str, Any]] = field(default_factory=list)

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []
        if self.errors is None:
            self.errors = []


def _modified_z(values: np.ndarray) -> np.ndarray:
    """Iglewicz–Hoaglin modified z-scores; MAD-based, robust to outliers."""
    med = np.nanmedian(values)
    mad = np.nanmedian(np.abs(values - med))
    if not np.isfinite(mad) or mad == 0.0:
        # Degenerate case (more than half the differences identical, e.g. a
        # flat series with one spike): MAD is blind there, so fall back to
        # the mean absolute deviation about the median, the denominator
        # Iglewicz-Hoaglin prescribe when MAD vanishes.
        mean_ad = np.nanmean(np.abs(values - med))
        if not np.isfinite(mean_ad) or mean_ad == 0.0:
            return np.zeros_like(values, dtype=float)
        return (values - med) / (1.253314 * mean_ad)
    return 0.6745 * (values - med) / mad


def _date_column(df: pd.DataFrame) -> Optional[str]:
    for candidate in ("Date", "date", "timestamp", "time"):
        if candidate in df.columns:
            return candidate
    return None


def _value_column(df: pd.DataFrame) -> Optional[str]:
    for candidate in ("Value", "value", "Close", "close"):
        if candidate in df.columns:
            return candidate
    return None


def _duplicate_key_columns(df: pd.DataFrame, date_col: str) -> List[str]:
    """Return the natural observation key for duplicate detection.

    A plain date is the grain for scalar economic series, but it is not the
    grain for panels or edge tables.  In particular, AI4Risk publishes one
    row per bank-to-bank edge for each quarter, so repeated dates are expected
    and only a repeated ``(date, source, target)`` edge is a duplicate.
    """
    for identity in (
        ("source_bank", "target_bank"),
        ("bank_id",),
        ("ticker",),
        ("Asset",),
        ("asset",),
        ("instrument",),
    ):
        if all(column in df.columns for column in identity):
            return [date_col, *identity]
    return [date_col]


class DataValidator:
    def __init__(self, job_id: str):
        self.job_id = job_id

    def validate(self, data: Dict[str, pd.DataFrame]) -> ValidationReport:
        logger.info(f"[{self.job_id}] Validating {len(data)} datasets")
        report = ValidationReport()
        # Naive UTC: provider timestamps arrive naive by convention, and
        # comparing aware against naive raises rather than informs.
        as_of = pd.Timestamp.now(tz="UTC").tz_localize(None)

        inconsistency_hits = 0
        inconsistency_cells = 0
        timeliness_measurable = 0
        timeliness_pass = 0

        for code, df in data.items():
            if df.empty:
                report.warnings.append({"code": code, "warning": "Empty dataset - no data available for requested period"})
                continue

            # -- missing values ------------------------------------------------
            total_cells = len(df) * len(df.columns)
            if total_cells > 0:
                missing_pct = df.isnull().sum().sum() / total_cells
                if missing_pct > 0.3:
                    report.warnings.append({"code": code, "warning": f"{missing_pct*100:.1f}% missing"})

            date_col = _date_column(df)
            value_col = _value_column(df)

            # -- duplicate timestamps (integrity) ------------------------------
            if date_col:
                stamps = pd.to_datetime(df[date_col], errors="coerce")
                duplicate_keys = _duplicate_key_columns(df, date_col)
                duplicated = int(df.duplicated(subset=duplicate_keys).sum())
                inconsistency_cells += len(df)
                inconsistency_hits += duplicated
                if duplicated:
                    positions = np.flatnonzero(
                        df.duplicated(subset=duplicate_keys).to_numpy()
                    )[:10]
                    self._record(report, code, "duplicate_timestamps", duplicated, positions)

                # -- future timestamps (look-ahead at ingest) ------------------
                future = int((stamps > as_of).sum())
                if future:
                    positions = np.flatnonzero((stamps > as_of).to_numpy())[:10]
                    self._record(report, code, "future_timestamps", future, positions)

                # -- timeliness: recency of the newest observation -------------
                observed = stamps.dropna()
                if not observed.empty:
                    timeliness_measurable += 1
                    age_days = (as_of - observed.max()).total_seconds() / 86400.0
                    if age_days <= TIMELINESS_MAX_DAYS:
                        timeliness_pass += 1
                    else:
                        report.warnings.append(
                            {"code": code, "warning": f"newest observation is {age_days:.0f} days old"}
                        )

            # -- value-series checks -------------------------------------------
            if value_col:
                values = pd.to_numeric(df[value_col], errors="coerce").to_numpy(dtype=float)

                # point outliers on first differences (robust)
                diffs = np.diff(values)
                finite = diffs[np.isfinite(diffs)]
                if finite.size >= 8:
                    mz = _modified_z(diffs)
                    hits = int((np.abs(mz) > MODIFIED_Z_THRESHOLD).sum())
                    if hits:
                        positions = np.flatnonzero(np.abs(mz) > MODIFIED_Z_THRESHOLD)[:10]
                        self._record(report, code, "point_outliers", hits, positions)

                # gap runs
                missing = ~np.isfinite(values)
                runs = self._run_lengths(missing)
                gap_hits = int(sum(1 for length in runs if length >= MIN_GAP_RUN))
                if gap_hits:
                    self._record(report, code, "gap_runs", gap_hits, [])

                # scale breaks: ratio of consecutive rolling medians
                observed_values = values[np.isfinite(values)]
                if observed_values.size >= 2 * SCALE_WINDOW:
                    medians = np.array(
                        [
                            np.median(observed_values[i : i + SCALE_WINDOW])
                            for i in range(0, observed_values.size - SCALE_WINDOW + 1, SCALE_WINDOW // 2)
                        ]
                    )
                    positive = np.where(np.abs(medians) > 1e-12, medians, np.nan)
                    with np.errstate(invalid="ignore", divide="ignore"):
                        log_ratios = np.abs(np.log(np.abs(positive[1:] / positive[:-1])))
                    breaks = int(np.nansum(log_ratios > SCALE_BREAK_LOG_RATIO))
                    if breaks:
                        positions = np.flatnonzero(log_ratios > SCALE_BREAK_LOG_RATIO)[:10]
                        self._record(report, code, "scale_break", breaks, positions)

                # stale runs of identical values
                runs_same = self._run_lengths_same(observed_values)
                stale = int(sum(1 for length in runs_same if length >= MIN_STALE_RUN))
                if stale:
                    self._record(report, code, "stale_run", stale, [])

        # -- roll up -----------------------------------------------------------
        total_cells = sum(len(df) * len(df.columns) for df in data.values() if not df.empty)
        if total_cells > 0:
            report.missing_ratio = (
                sum(df.isnull().sum().sum() for df in data.values() if not df.empty) / total_cells
            )
        else:
            report.missing_ratio = 0.0

        if inconsistency_cells:
            report.inconsistency_ratio = inconsistency_hits / inconsistency_cells

        if timeliness_measurable:
            report.timeliness_score = timeliness_pass / timeliness_measurable
        else:
            report.warnings.append(
                {"code": "*", "warning": "timeliness not measurable: no dated datasets in this run"}
            )

        report.anomalies_count = sum(entry["count"] for entry in report.anomalies)
        return report

    @staticmethod
    def _record(report: ValidationReport, code: str, kind: str, count: int, positions) -> None:
        report.anomalies.append(
            {
                "code": code,
                "kind": kind,
                "count": int(count),
                "positions_sample": [int(p) for p in positions],
            }
        )
        report.warnings.append({"code": code, "warning": f"{kind}: {count}"})

    @staticmethod
    def _run_lengths(mask: np.ndarray) -> List[int]:
        lengths: List[int] = []
        current = 0
        for flag in mask:
            if flag:
                current += 1
            elif current:
                lengths.append(current)
                current = 0
        if current:
            lengths.append(current)
        return lengths

    @staticmethod
    def _run_lengths_same(values: np.ndarray) -> List[int]:
        if values.size == 0:
            return []
        lengths: List[int] = []
        current = 1
        for previous, current_value in zip(values[:-1], values[1:]):
            if previous == current_value:
                current += 1
            else:
                lengths.append(current)
                current = 1
        lengths.append(current)
        return lengths
