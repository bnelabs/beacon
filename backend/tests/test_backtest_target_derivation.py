"""Tests for the leakage-safe backtest target derivation.

The backtest pairs each risk score with the standardized next-step actual of
the same series. The standardization must come from the pre-test window only;
these tests pin that down: test-window statistics must not leak into the
target, series without pre-test history must get NaN targets, and the OHLC
vs Value column choice must follow the data (not the schema).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from backend.tasks.job_tasks import derive_standardized_targets


def _split_frame(values_by_series: dict, pre_test: dict, test: dict) -> tuple:
    """Build train/test frames: one OHLC series (Close) and one value series."""
    rows = []
    for series, series_id in values_by_series.items():
        for date, value in list(pre_test.items()) + list(test.items()):
            row = {
                "Date": pd.Timestamp(date),
                "date": pd.Timestamp(date),
                "source_code": series,
                "series_id": series_id,
            }
            if series.startswith("EQ_"):
                row["Close"] = value
                row["close"] = value
            else:
                row["Value"] = value
                row["value"] = value
            rows.append(row)
    frame = pd.DataFrame(rows)
    cutoff = pd.Timestamp("2026-01-01")
    train = frame[frame["date"] < cutoff]
    test = frame[frame["date"] >= cutoff]
    return train, test


class TestDerivation:
    def test_standardizes_on_pre_test_stats_only(self):
        pre = {f"2025-{m:02d}-15": 10.0 + m for m in range(1, 7)}   # 11..16
        test_dates = {"2026-01-15": 20.0, "2026-02-15": 21.0}
        train, test = _split_frame(
            {"EQ_A": "EQ_A::X"}, pre, test_dates
        )
        targets = derive_standardized_targets(test, train)
        assert targets is not None
        # Pre-test mean 13.5, std 2.1213203...: the test values (20, 21) map
        # to z ~ +3.1/+3.5 -- a test-window standardization would center
        # them at (-1, +1) instead.
        mean, std = np.mean(list(pre.values())), np.std(list(pre.values()))
        expected = np.array([(20.0 - mean) / (std + 1e-8), (21.0 - mean) / (std + 1e-8)])
        assert np.allclose(targets, expected)
        # Both test values sit above the pre-test level (11..16); a
        # test-window standardization would instead center them at -1/+1.
        assert targets[0] > 0 and targets[1] > targets[0]

    def test_targets_follow_the_training_clip_law(self):
        """A 40-sigma jump in the test window is a bounded target, not 40:
        the backtest target must follow the same +-10 clipping the training
        target uses, so a step change in a low-std series is a bounded error
        in backtest exactly as it was in training."""
        pre = {f"2025-{m:02d}-15": 10.0 + m for m in range(1, 7)}   # 11..16
        test_dates = {"2026-01-15": 100.0}
        train, test = _split_frame(
            {"EQ_A": "EQ_A::X"}, pre, test_dates
        )
        targets = derive_standardized_targets(test, train)
        assert targets is not None
        mean, std = np.mean(list(pre.values())), np.std(list(pre.values()))
        unclipped = (100.0 - mean) / (std + 1e-8)
        assert unclipped > 10.0, "fixture no longer exceeds the clip"
        assert np.allclose(targets, [10.0])

    def test_series_without_pre_test_history_gets_nan(self):
        pre = {f"2025-{m:02d}-15": 10.0 + m for m in range(1, 7)}
        test_dates = {"2026-01-15": 10.0}
        train, test = _split_frame(
            {"EQ_A": "EQ_A::X", "VAL_B": "VAL_B::Y"}, pre, test_dates
        )
        # VAL_B has no pre-test rows at all.
        train = train[train["series_id"] != "VAL_B::Y"]
        targets = derive_standardized_targets(test, train)
        assert targets is not None
        by_series = dict(zip(test["series_id"].to_numpy(), targets))
        assert np.isfinite(by_series["EQ_A::X"])
        assert np.isnan(by_series["VAL_B::Y"])

    def test_value_series_uses_value_column_not_close(self):
        pre = {f"2025-{m:02d}-15": 10.0 + m for m in range(1, 7)}
        test_dates = {"2026-01-15": 20.0}
        train, test = _split_frame({"VAL_A": "VAL_A::Y"}, pre, test_dates)
        targets = derive_standardized_targets(test, train)
        assert targets is not None
        mean, std = np.mean(list(pre.values())), np.std(list(pre.values()))
        assert np.allclose(targets, [(20.0 - mean) / (std + 1e-8)])

    def test_empty_train_returns_none(self):
        train = pd.DataFrame({"Date": pd.to_datetime([]), "source_code": [], "series_id": [], "Value": []})
        test = pd.DataFrame({"Date": pd.to_datetime(["2026-01-15"]), "source_code": ["A"], "series_id": ["A::1"], "Value": [1.0]})
        assert derive_standardized_targets(test, train) is None

    def test_constant_pre_test_series_is_excluded(self):
        pre = {f"2025-{m:02d}-15": 5.0 for m in range(1, 7)}  # std 0
        test_dates = {"2026-01-15": 6.0}
        train, test = _split_frame({"VAL_A": "VAL_A::Y"}, pre, test_dates)
        # A constant series has std ~0; with the 1e-8 guard it would
        # explode, so it must be excluded instead.
        targets = derive_standardized_targets(test, train)
        assert targets is None
