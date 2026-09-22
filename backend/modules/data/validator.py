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
Cleaning and gating decisions live elsewhere and consume this report. The one
enforcement contract it feeds: duplicate and future timestamps are integrity
breaches rather than noise, so the datasets carrying them are named in
``critical_datasets`` (and ``critical_errors`` counts them) -- the orchestrator
excludes exactly those datasets from the run and alerts, instead of certifying
rows whose value or publication time is ambiguous.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Mapping, Optional, Tuple

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

#: Ordered registry of panel/edge identities: the first tuple whose columns
#: are all present defines the frame's entity dimensions. Shared by the
#: validator, the formatter and the quality gate -- the grain definition
#: lives in exactly one place.
IDENTITY_COLUMN_SETS: Tuple[Tuple[str, ...], ...] = (
    ("source_bank", "target_bank"),
    ("bank_id", "feature"),
    ("bank_id",),
    ("ticker",),
    ("Asset",),
    ("asset",),
    ("instrument",),
)
# A single 40-day rule is only a safe fallback.  It labels perfectly healthy
# quarterly and annual feeds as stale, while it gives daily feeds too much
# slack.  These are deliberately warning thresholds rather than hard rejects:
# historical data can still be useful, but its freshness must remain visible.
FREQUENCY_MAX_STALENESS_DAYS = {
    "daily": 14.0,
    "weekly": 35.0,
    "monthly": 120.0,
    "quarterly": 300.0,
    "annual": 730.0,
    "event": 120.0,
    "irregular": 120.0,
}


@dataclass
class ValidationReport:
    #: Number of datasets carrying an integrity breach (duplicate or future
    #: timestamps). The orchestrator excludes exactly these datasets from the
    #: run -- the validator observes and reports, and this is the one finding
    #: class its contract calls a breach rather than noise.
    critical_errors: int = 0
    warnings: list = None
    errors: list = None
    missing_ratio: float = 0.0
    inconsistency_ratio: float = 0.0
    timeliness_score: float = 1.0
    anomalies_count: int = 0
    #: Structured anomaly findings, sixth round: one entry per (dataset, kind).
    anomalies: List[Dict[str, Any]] = field(default_factory=list)
    #: Per-dataset freshness evidence, including the cadence-specific threshold.
    timeliness_by_dataset: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    #: Codes of the datasets behind ``critical_errors``, so the orchestrator
    #: excludes by identity instead of guessing from a count.
    critical_datasets: List[str] = field(default_factory=list)

    def __post_init__(self):
        if self.warnings is None:
            self.warnings = []
        if self.errors is None:
            self.errors = []


#: The finding kinds that are integrity breaches rather than statistical
#: noise: a repeated observation time is ambiguous (which value is right?),
#: and a timestamp after the job's as-of is look-ahead at ingest. Both are
#: per-dataset critical; the other kinds are warnings by design.
INTEGRITY_FINDING_KINDS = frozenset({"duplicate_timestamps", "future_timestamps"})


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


def identity_columns(df: pd.DataFrame) -> List[str]:
    """Return the entity dimensions that define independent value series.

    The grain definition lives here, in exactly one place, and is shared by
    the validator (duplicate keys, per-entity checks), the formatter
    (``series_id``) and the quality gate (per-entity KPSS). Pipeline-review
    finding F5 landed because a grain fix had reached two of those three
    consumers but not the gate.
    """
    for identity in IDENTITY_COLUMN_SETS:
        if all(column in df.columns for column in identity):
            return list(identity)
    return []


def _duplicate_key_columns(df: pd.DataFrame, date_col: str) -> List[str]:
    """Return the natural observation key for duplicate detection.

    A plain date is the grain for scalar economic series, but it is not the
    grain for panels or edge tables.  In particular, AI4Risk publishes one
    row per bank-to-bank edge for each quarter, so repeated dates are expected
    and only a repeated ``(date, source, target)`` edge is a duplicate.
    """
    return [date_col, *identity_columns(df)]


def timeliness_tolerance_days(frequency: Optional[str]) -> float:
    """Return the freshness warning threshold for a declared cadence.

    ``None`` preserves the legacy 40-day fallback used by callers that do not
    have catalogue metadata.  The orchestrator passes declared frequencies for
    production collection jobs.
    """
    if frequency is None or not str(frequency).strip():
        return TIMELINESS_MAX_DAYS
    return FREQUENCY_MAX_STALENESS_DAYS.get(
        str(frequency).strip().lower(),
        TIMELINESS_MAX_DAYS,
    )


class DataValidator:
    def __init__(self, job_id: str):
        self.job_id = job_id

    def validate(
        self,
        data: Dict[str, pd.DataFrame],
        frequencies: Optional[Mapping[str, str]] = None,
    ) -> ValidationReport:
        logger.info(f"[{self.job_id}] Validating {len(data)} datasets")
        report = ValidationReport()
        frequencies = frequencies or {}
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
                    frequency = frequencies.get(code)
                    max_staleness_days = timeliness_tolerance_days(frequency)
                    timely = age_days <= max_staleness_days
                    report.timeliness_by_dataset[code] = {
                        "frequency": frequency,
                        "age_days": float(age_days),
                        "max_staleness_days": float(max_staleness_days),
                        "passed": bool(timely),
                    }
                    if timely:
                        timeliness_pass += 1
                    else:
                        report.warnings.append(
                            {
                                "code": code,
                                "warning": (
                                    f"newest observation is {age_days:.0f} days old "
                                    f"(cadence={frequency or 'unspecified'}, "
                                    f"tolerance={max_staleness_days:.0f} days)"
                                ),
                            }
                        )

            # -- value-series checks -------------------------------------------
            if value_col:
                # Every value-series check is performed within the natural
                # entity grain.  Running first differences over a panel's row
                # order turns a bank-edge transition into a fake spike and a
                # panel boundary into a fake scale break.
                working = df.copy()
                working["__row_position"] = np.arange(len(working))
                if date_col:
                    working["__parsed_date"] = stamps
                identity = identity_columns(working)
                if identity:
                    series_groups = working.groupby(identity, dropna=False, sort=False)
                else:
                    series_groups = [("__scalar__", working)]

                for _, series in series_groups:
                    if date_col:
                        series = series.sort_values(
                            ["__parsed_date", "__row_position"],
                            kind="mergesort",
                        )
                    values = pd.to_numeric(series[value_col], errors="coerce").to_numpy(dtype=float)
                    row_positions = series["__row_position"].to_numpy(dtype=int)

                    # point outliers on first differences (robust)
                    diffs = np.diff(values)
                    finite = diffs[np.isfinite(diffs)]
                    if finite.size >= 8:
                        mz = _modified_z(diffs)
                        hit_indices = np.flatnonzero(np.abs(mz) > MODIFIED_Z_THRESHOLD)
                        if hit_indices.size:
                            positions = row_positions[1:][hit_indices[:10]]
                            self._record(
                                report,
                                code,
                                "point_outliers",
                                int(hit_indices.size),
                                positions,
                            )

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
                                for i in range(
                                    0,
                                    observed_values.size - SCALE_WINDOW + 1,
                                    SCALE_WINDOW // 2,
                                )
                            ]
                        )
                        positive = np.where(np.abs(medians) > 1e-12, medians, np.nan)
                        with np.errstate(invalid="ignore", divide="ignore"):
                            log_ratios = np.abs(np.log(np.abs(positive[1:] / positive[:-1])))
                        break_indices = np.flatnonzero(log_ratios > SCALE_BREAK_LOG_RATIO)
                        if break_indices.size:
                            self._record(
                                report,
                                code,
                                "scale_break",
                                int(break_indices.size),
                                break_indices[:10],
                            )

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

        # -- integrity breaches are the one critical class ----------------------
        # Duplicate and future timestamps are breaches, not noise: a repeated
        # observation time is ambiguous (which value is right?) and a timestamp
        # after the job's as-of is look-ahead at ingest. The datasets carrying
        # them are named here so the orchestrator excludes by identity -- the
        # report itself still modifies nothing.
        breached_codes: List[str] = []
        for entry in report.anomalies:
            if entry["kind"] in INTEGRITY_FINDING_KINDS and entry["code"] not in breached_codes:
                breached_codes.append(entry["code"])
        for code in breached_codes:
            kinds = sorted(
                {
                    entry["kind"]
                    for entry in report.anomalies
                    if entry["code"] == code
                    and entry["kind"] in INTEGRITY_FINDING_KINDS
                }
            )
            report.critical_datasets.append(code)
            report.errors.append(
                {
                    "code": code,
                    "error": (
                        f"integrity breach: {', '.join(kinds)}; dataset excluded "
                        "from this run's certification"
                    ),
                }
            )
        report.critical_errors = len(report.critical_datasets)
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
