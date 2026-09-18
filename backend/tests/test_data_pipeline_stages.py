"""Round-seven coverage (I1): the data-shaping stages where silent
corruptions actually live.

The suite was component-heavy and pipeline-light: formatter, cleaner and the
collector's retry semantics had no direct tests. These anchor the contracts
each stage promises:

* formatter standardises plugin column chaos into the canonical schema and
  lowercase aliases, and never drops rows;
* cleaner preserves gaps as NaN (no imputation) and reports them per source;
* collector retries only transient unavailability, bounded, and records
  non-transient failures on the first attempt.
"""

from __future__ import annotations

from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from backend.exceptions import DataSourceUnavailableError, DatasetMissingError
from backend.modules.data.cleaner import DataCleaner
from backend.modules.data.collector import DataCollector
from backend.modules.data.formatter import DataFormatter


def _plugin_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "date": pd.date_range("2024-01-01", periods=5, freq="D"),
        "close": [1.0, 2.0, np.nan, 4.0, 5.0],
        "volume": [10, 20, 30, 40, 50],
    })


class TestFormatter:
    def test_columns_are_standardised_with_aliases(self):
        out = DataFormatter("job").format({"SRC": _plugin_frame()}, "timeseries")
        for column in ("Date", "Close", "Volume", "date", "close"):
            assert column in out.columns
        assert len(out) == 5

    def test_value_alias_prefers_value_then_close(self):
        out = DataFormatter("job").format({"SRC": _plugin_frame()}, "timeseries")
        assert "value" in out.columns or "Value" in out.columns

    def test_empty_frames_are_skipped_not_crashing(self):
        out = DataFormatter("job").format({"SRC": pd.DataFrame(), "OK": _plugin_frame()}, "timeseries")
        assert len(out) == 5


class TestCleaner:
    def test_gaps_are_preserved_not_imputed(self):
        frame = _plugin_frame()
        cleaned, report = DataCleaner("job").clean({"SRC": frame})
        assert cleaned["SRC"].isnull().sum().sum() == 1
        assert report.gaps_detected == 1
        assert report.gaps_by_source == {"SRC": 1}
        assert any("preserved as NaN" in warning for warning in report.warnings)

    def test_empty_sources_are_reported(self):
        cleaned, report = DataCleaner("job").clean({"EMPTY": pd.DataFrame()})
        assert report.empty_sources == ["EMPTY"]

    def test_clean_frames_produce_no_warnings(self):
        frame = _plugin_frame().dropna()
        _, report = DataCleaner("job").clean({"SRC": frame})
        assert report.gaps_detected == 0
        assert report.warnings == []


class _Flaky:
    def __init__(self, failures, error):
        self.failures = failures
        self.error = error
        self.calls = 0

    def __call__(self, item, start_date, end_date):
        self.calls += 1
        if self.calls <= self.failures:
            raise self.error("boom")
        return pd.DataFrame({"Date": [pd.Timestamp("2024-01-01")], "Value": [1.0]})


def _collector_with(flaky):
    collector = DataCollector.__new__(DataCollector)
    collector.job_id = "job"
    collector._fetch_item_data = flaky
    return collector


class TestCollectorRetry:
    def test_transient_unavailability_is_retried_then_succeeds(self):
        flaky = _Flaky(2, DataSourceUnavailableError)
        collector = _collector_with(flaky)
        df = collector._fetch_with_retry(object(), "2024-01-01", "2024-02-01")
        assert len(df) == 1
        assert flaky.calls == 3  # two failures + success, within 3 attempts

    def test_transient_unavailability_exhausts_attempts(self):
        flaky = _Flaky(99, DataSourceUnavailableError)
        collector = _collector_with(flaky)
        with pytest.raises(DataSourceUnavailableError):
            collector._fetch_with_retry(object(), "2024-01-01", "2024-02-01")
        assert flaky.calls == 3  # bounded, not infinite

    def test_non_transient_failures_are_not_retried(self):
        flaky = _Flaky(99, DatasetMissingError)
        collector = _collector_with(flaky)
        with pytest.raises(DatasetMissingError):
            collector._fetch_with_retry(object(), "2024-01-01", "2024-02-01")
        assert flaky.calls == 1  # a decision, not a blip


def test_indicator_provider_is_not_routed_through_asset_transport(monkeypatch):
    import backend.modules.data.collector as collector_module

    calls = []

    class IndicatorPlugin:
        def __init__(self, config):
            self.config = config

        def fetch_asset_data(self, symbols, start_date, end_date):
            raise AssertionError("indicator provider was routed as an asset")

        def fetch_indicator_data(self, indicator_id, start_date, end_date):
            calls.append(indicator_id)
            return pd.DataFrame({"date": [pd.Timestamp("2024-01-01")], "value": [4.2]})

    monkeypatch.setattr(collector_module, "get_plugin", lambda plugin_type: IndicatorPlugin)
    monkeypatch.setattr(collector_module, "config_with_env_keys", lambda plugin_type, config: config)

    item = SimpleNamespace(
        category="bonds",
        endpoint="DGS10",
        parameters={},
        data_source=SimpleNamespace(plugin_type="fred", config={}),
    )
    collector = DataCollector.__new__(DataCollector)

    frame = collector._fetch_item_data(item, "2024-01-01", "2024-01-31")

    assert calls == ["DGS10"]
    assert len(frame) == 1
    assert list(frame.columns) == ["Date", "Value"]
