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

    def test_metadata_and_series_identity_are_carried_into_the_package(self):
        frame = pd.DataFrame({
            "Date": pd.date_range("2024-01-01", periods=3, freq="D"),
            "Value": [1.0, 2.0, 3.0],
        })
        out = DataFormatter("job").format(
            {"SRC": frame},
            "timeseries",
            source_metadata={
                "SRC": {
                    "frequency": "monthly",
                    "unit": "index",
                    "granularity": "macro",
                }
            },
        )
        assert out["frequency"].tolist() == ["monthly"] * 3
        assert out["unit"].tolist() == ["index"] * 3
        assert out["series_id"].tolist() == ["SRC"] * 3

    def test_features_do_not_cross_source_or_panel_boundaries(self):
        dates = pd.date_range("2024-01-01", periods=8, freq="D")
        scalar = pd.DataFrame({"Date": dates, "Value": np.arange(8, dtype=float)})
        panel = pd.DataFrame({
            "Date": list(dates) + list(dates),
            "source_bank": ["A"] * 8 + ["B"] * 8,
            "target_bank": ["B"] * 8 + ["A"] * 8,
            "Value": list(np.arange(8, dtype=float)) + list(100 + np.arange(8, dtype=float)),
        })
        formatter = DataFormatter("job")
        out = formatter.format(
            {"SRC": scalar, "PANEL": panel},
            "timeseries",
            source_metadata={
                "SRC": {"frequency": "daily"},
                "PANEL": {"frequency": "quarterly"},
            },
        )
        features = formatter.extract_features(out)

        # The first row of every independent series has only its own value in
        # the rolling mean; it must not inherit the preceding source or edge.
        assert features.loc[out["series_id"] == "SRC", "value_mean"].iloc[0] == pytest.approx(0.0)
        panel_first = features.loc[
            out["series_id"].eq("PANEL::A::B") | out["series_id"].eq("PANEL::B::A"),
            "value_mean",
        ]
        assert panel_first.iloc[0] == pytest.approx(0.0)
        assert panel_first.iloc[8] == pytest.approx(100.0)


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

    def test_retry_budget_stops_further_attempts(self, monkeypatch):
        """An exhausted budget stops retries even with attempts left (F8).

        The HTTP layer beneath retries too, so attempt counts alone did not
        bound the wall time one catalogue item could spend against a
        struggling provider. The budget bounds the between-attempt window;
        a legitimately long single fetch is never cut off mid-flight.
        """
        monkeypatch.setenv("BEACON_FETCH_RETRY_BUDGET_SECONDS", "0")
        flaky = _Flaky(99, DataSourceUnavailableError)
        collector = _collector_with(flaky)
        with pytest.raises(DataSourceUnavailableError):
            collector._fetch_with_retry(object(), "2024-01-01", "2024-02-01")
        assert flaky.calls == 1  # budget 0: the first attempt is the last

    def test_invalid_retry_budget_falls_back_to_the_default(self, monkeypatch):
        """A malformed override is ignored with a warning, not crashed on."""
        from backend.modules.data.collector import (
            FETCH_RETRY_BUDGET_SECONDS,
            _fetch_retry_budget_seconds,
        )

        monkeypatch.setenv("BEACON_FETCH_RETRY_BUDGET_SECONDS", "soon")
        assert _fetch_retry_budget_seconds() == FETCH_RETRY_BUDGET_SECONDS

        flaky = _Flaky(99, DataSourceUnavailableError)
        collector = _collector_with(flaky)
        with pytest.raises(DataSourceUnavailableError):
            collector._fetch_with_retry(object(), "2024-01-01", "2024-02-01")
        assert flaky.calls == 3  # the default budget is not smaller than the attempts


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


def test_collector_clips_provider_padding_to_the_requested_window(monkeypatch):
    import backend.modules.data.collector as collector_module

    class IndicatorPlugin:
        def __init__(self, config):
            self.config = config

        def fetch_indicator_data(self, indicator_id, start_date, end_date):
            return pd.DataFrame({
                "Date": pd.to_datetime(["2019-12-31", "2020-01-01", "2020-01-31", "2020-02-01"]),
                "Value": [0.0, 1.0, 2.0, 3.0],
            })

    monkeypatch.setattr(collector_module, "get_plugin", lambda plugin_type: IndicatorPlugin)
    monkeypatch.setattr(collector_module, "config_with_env_keys", lambda plugin_type, config: config)

    item = SimpleNamespace(
        code="PADDED",
        category="economic_indicators",
        endpoint="PADDED",
        parameters={},
        data_source=SimpleNamespace(plugin_type="fred", config={}),
    )
    collector = DataCollector.__new__(DataCollector)
    collector.job_id = "job"

    frame = collector._fetch_item_data(item, "2020-01-01", "2020-01-31")
    assert frame["Date"].tolist() == [pd.Timestamp("2020-01-01"), pd.Timestamp("2020-01-31")]


# ---------------------------------------------------------------------------
# Degraded fetches: a stale-cache success is collected AND witnessed (F9)
# ---------------------------------------------------------------------------


def _stale_aware_plugin(hits: int):
    """A plugin whose resilient session reports ``hits`` stale-cache serves."""

    class _Plugin:
        def __init__(self, config):
            self.config = config
            self._resilient_session = None

        def fetch_indicator_data(self, indicator_id, start_date, end_date):
            # the real base.http property builds this lazily; the counter is
            # what the collector reads after the fetch
            self._resilient_session = SimpleNamespace(stale_fallback_hits=hits)
            return pd.DataFrame({"Date": [pd.Timestamp("2024-01-15")], "Value": [1.0]})

    return _Plugin


def _stale_item():
    return SimpleNamespace(
        code="STALE_ITEM",
        category="economic_indicators",
        endpoint="STALE_ITEM",
        parameters={},
        region=None,
        data_source=SimpleNamespace(plugin_type="fake_stale", config={}),
    )


def test_stale_cache_fetch_marks_the_item_degraded(monkeypatch):
    import backend.modules.data.collector as collector_module

    monkeypatch.setattr(collector_module, "get_plugin", lambda t: _stale_aware_plugin(1))
    monkeypatch.setattr(collector_module, "config_with_env_keys", lambda t, c: c)

    collector = DataCollector.__new__(DataCollector)
    collector.job_id = "job"
    frame = collector._fetch_item_data(_stale_item(), "2024-01-01", "2024-02-01")

    assert len(frame) == 1  # the data arrived...
    assert collector._last_fetch_degraded is True  # ...and the degradation is witnessed


def test_fresh_fetch_is_not_degraded(monkeypatch):
    import backend.modules.data.collector as collector_module

    monkeypatch.setattr(collector_module, "get_plugin", lambda t: _stale_aware_plugin(0))
    monkeypatch.setattr(collector_module, "config_with_env_keys", lambda t, c: c)

    collector = DataCollector.__new__(DataCollector)
    collector.job_id = "job"
    collector._fetch_item_data(_stale_item(), "2024-01-01", "2024-02-01")

    assert collector._last_fetch_degraded is False


def test_collect_records_degraded_codes_in_the_report(monkeypatch):
    """The report separates collected from collected-degraded.

    A degraded item still counts as collected (the data reached the
    pipeline), but ``report.degraded`` is what telemetry reads so a
    cache-served success never clears the provider's failure streak.
    """
    item = _stale_item()

    class _FakeQuery:
        def filter(self, *args, **kwargs):
            return self

        def first(self):
            return item

    class _FakeDB:
        def query(self, model):
            return _FakeQuery()

    collector = DataCollector(_FakeDB(), "job", "/tmp")

    def _degraded_fetch(fetch_item, start_date, end_date):
        collector._last_fetch_degraded = True
        return pd.DataFrame({"Date": [pd.Timestamp("2024-01-15")], "Value": [1.0]})

    monkeypatch.setattr(collector, "_fetch_item_data", _degraded_fetch)

    collected = collector.collect([1], "2024-01-01", "2024-02-01")

    assert list(collected) == ["STALE_ITEM"]
    report = collector.last_report
    assert report.collected == ["STALE_ITEM"]
    assert report.degraded == ["STALE_ITEM"]
    assert report.to_dict()["degraded"] == ["STALE_ITEM"]
    assert report.success_ratio == 1.0  # degraded is not failed
