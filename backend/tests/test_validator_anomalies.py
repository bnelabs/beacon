"""The validator must detect what it claims to detect.

Before the sixth round the validator implemented one check (missing ratio)
while its docstring promised anomaly detection, and ``anomalies_count`` was
0 for every dataset of every run. Each test below anchors one check of the
new battery to a hand-built series whose anomalies are known by construction
-- and a clean series must produce silence, because a detector that cries
always is as useless as one that never cries.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from backend.modules.data.validator import DataValidator, ValidationReport


def _frame(values, dates=None) -> pd.DataFrame:
    n = len(values)
    dates = dates if dates is not None else pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame({"Date": dates, "Value": values})


def _clean(n: int = 120, seed: int = 4) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return 100 + rng.normal(0, 0.5, n).cumsum() * 0.05


def _validate(df) -> ValidationReport:
    return DataValidator("test-job").validate({"SERIES": df})


class TestCleanSeriesIsSilent:
    def test_no_anomalies_and_measured_timeliness(self):
        report = _validate(_frame(_clean()))
        assert report.anomalies_count == 0
        assert report.anomalies == []
        assert report.timeliness_score == 0.0  # synthetic 2024 data is old vs now
        assert report.inconsistency_ratio == 0.0


class TestDuplicateTimestamps:
    def test_duplicates_are_counted_and_located(self):
        dates = pd.date_range("2026-09-01", periods=60, freq="D").tolist()
        dates[10] = dates[9]  # duplicate observation time
        dates[20] = dates[19]
        report = _validate(_frame(_clean(60), dates=pd.DatetimeIndex(dates)))
        kinds = {entry["kind"]: entry for entry in report.anomalies}
        assert kinds["duplicate_timestamps"]["count"] == 2
        assert report.inconsistency_ratio == pytest.approx(2 / 60)

    def test_edge_panels_use_date_and_endpoints_as_the_grain(self):
        frame = pd.DataFrame(
            {
                "Date": [pd.Timestamp("2026-01-01")] * 3,
                "source_bank": ["A", "A", "B"],
                "target_bank": ["B", "C", "A"],
                "Value": [1.0, 2.0, 3.0],
            }
        )
        report = _validate(frame)
        assert report.inconsistency_ratio == 0.0
        assert not report.anomalies

    def test_repeated_edge_is_still_a_duplicate(self):
        frame = pd.DataFrame(
            {
                "Date": [pd.Timestamp("2026-01-01")] * 2,
                "source_bank": ["A", "A"],
                "target_bank": ["B", "B"],
                "Value": [1.0, 1.5],
            }
        )
        report = _validate(frame)
        kinds = {entry["kind"]: entry for entry in report.anomalies}
        assert kinds["duplicate_timestamps"]["count"] == 1


class TestFutureTimestamps:
    def test_lookahead_at_ingest_is_flagged(self):
        dates = pd.date_range("2025-01-01", periods=60, freq="D")
        df = _frame(_clean(60), dates)
        df.loc[55, "Date"] = pd.Timestamp("2030-01-01")
        report = _validate(df)
        kinds = {entry["kind"]: entry for entry in report.anomalies}
        assert kinds["future_timestamps"]["count"] == 1


class TestPointOutliers:
    def test_a_jump_in_differences_is_detected(self):
        values = _clean(120)
        values[60:] += 25  # level jump -> one huge first difference
        report = _validate(_frame(values))
        kinds = {entry["kind"]: entry for entry in report.anomalies}
        assert "point_outliers" in kinds
        assert kinds["point_outliers"]["count"] >= 1

    def test_modified_z_is_robust_to_the_outlier_itself(self):
        values = np.zeros(50)
        values[25] = 1000.0
        report = _validate(_frame(values))
        kinds = {entry["kind"]: entry for entry in report.anomalies}
        assert "point_outliers" in kinds


class TestGapRuns:
    def test_a_long_missing_stretch_is_a_gap_run(self):
        values = _clean(100)
        values[40:50] = np.nan
        report = _validate(_frame(values))
        kinds = {entry["kind"]: entry for entry in report.anomalies}
        assert kinds["gap_runs"]["count"] == 1

    def test_short_gaps_are_not_gap_runs(self):
        values = _clean(100)
        values[40:43] = np.nan  # 3 < MIN_GAP_RUN
        report = _validate(_frame(values))
        kinds = {entry["kind"]: entry for entry in report.anomalies}
        assert "gap_runs" not in kinds


class TestScaleBreaks:
    def test_a_unit_change_is_flagged(self):
        values = np.concatenate([np.full(60, 5.0), np.full(60, 500.0)])
        report = _validate(_frame(values))
        kinds = {entry["kind"]: entry for entry in report.anomalies}
        assert "scale_break" in kinds


class TestStaleRuns:
    def test_a_frozen_feed_is_flagged(self):
        values = np.concatenate([_clean(60), np.full(40, 7.77)])
        report = _validate(_frame(values))
        kinds = {entry["kind"]: entry for entry in report.anomalies}
        assert kinds["stale_run"]["count"] >= 1


class TestRollup:
    def test_anomalies_count_is_the_sum_of_findings(self):
        values = _clean(100)
        values[40:50] = np.nan
        values[70:] += 25
        report = _validate(_frame(values))
        assert report.anomalies_count == sum(entry["count"] for entry in report.anomalies)
        assert report.anomalies_count > 0

    def test_empty_datasets_still_warn(self):
        report = DataValidator("test-job").validate({"EMPTY": pd.DataFrame()})
        assert report.warnings and report.anomalies_count == 0
