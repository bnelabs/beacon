"""Keyless feed tests: FRED CSV fallback, FDIC rewrite, registry integrity.

The defect class these guard is real and happened twice in this tree: a
plugin file that exists, is advertised by the UI, and is not reachable from
the runtime registry (``fdic`` referenced a base module that never existed;
``cftc_cot`` and ``nyfed`` were simply absent from the loader list). So the
first test asserts the property -- every concrete plugin class defined in
``backend/plugins/`` is registered -- and the rest pin the two rewritten
plugins to the payload shapes verified against the live APIs on 2026-09-15
(fredgraph.csv and the FDIC BankFind Suite).

Stooq was proposed as a third keyless feed and is deliberately absent: its
CSV download endpoint sits behind an anti-bot challenge (HTTP 200 with an
HTML noscript page as of 2026-09-15), so a plugin against it would be dead on
arrival exactly like the old FDIC one. The decision is recorded in
docs/README.md rather than in a stub.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

import backend.plugins as plugins_pkg
from backend.plugins.base import DataSourcePlugin

# ---------------------------------------------------------------------------
# Registry integrity: a plugin file that never registers is a dead plugin
# ---------------------------------------------------------------------------


def test_every_plugin_file_registers_a_live_plugin():
    registered = set(plugins_pkg.available_plugins())
    found = {}
    package_path = Path(plugins_pkg.__file__).parent
    for info in pkgutil.iter_modules([str(package_path)]):
        if info.name in {"base", "__init__"}:
            continue
        module = importlib.import_module(f"backend.plugins.{info.name}")
        for _name, cls in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(cls, DataSourcePlugin)
                and cls is not DataSourcePlugin
                and cls.__module__ == module.__name__
            ):
                found.setdefault(info.name, []).append(cls.__name__)
    assert found, "no plugin classes discovered; the scan itself broke"
    for module_name, class_names in found.items():
        for class_name in class_names:
            assert class_name in registered, (
                f"{module_name}.{class_name} is defined but absent from the "
                "runtime registry: it cannot be selected by any data source"
            )


# ---------------------------------------------------------------------------
# FRED keyless fallback
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code=200, text="", json_payload=None):
        self.status_code = status_code
        self.text = text
        self._json = json_payload

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


FRED_CSV = (
    "observation_date,STLFSI4\n"
    "2024-01-05,0.98\n"
    "2024-01-12,.\n"
    "2024-01-19,1.02\n"
)


def _fred_plugin(config=None):
    from backend.plugins.fred_plugin import FREDPlugin

    plugin = FREDPlugin.__new__(FREDPlugin)
    plugin.config = config or {}
    return plugin


class TestFredKeyless:
    def test_csv_fallback_parses_and_drops_missing(self, monkeypatch):
        import backend.plugins.fred_plugin as fred

        captured = {}

        def fake_get(url, params=None, timeout=None):
            captured.update(url=url, params=params, timeout=timeout)
            return _FakeResponse(text=FRED_CSV)

        monkeypatch.setattr(fred.requests, "get", fake_get)
        df = _fred_plugin().fetch_indicator_data(
            "STLFSI4", datetime(2024, 1, 1), datetime(2024, 1, 31)
        )
        assert df is not None and len(df) == 2  # the "." observation is dropped
        assert list(df.columns) == ["Date", "Value"]
        assert df["Value"].tolist() == [0.98, 1.02]
        assert captured["url"].endswith("/graph/fredgraph.csv")
        assert captured["params"] == {
            "id": "STLFSI4",
            "cosd": "2024-01-01",
            "coed": "2024-01-31",
        }

    def test_legacy_date_value_header_parses(self, monkeypatch):
        import backend.plugins.fred_plugin as fred

        monkeypatch.setattr(
            fred.requests, "get",
            lambda *a, **k: _FakeResponse(text="DATE,VALUE\n2024-01-05,0.98\n"),
        )
        df = _fred_plugin()._fetch_keyless_csv(
            "STLFSI4", datetime(2024, 1, 1), datetime(2024, 2, 1)
        )
        assert df["Value"].tolist() == [0.98]

    def test_http_error_is_typed_not_parsed_as_data(self, monkeypatch):
        import backend.plugins.fred_plugin as fred

        monkeypatch.setattr(
            fred.requests, "get", lambda *a, **k: _FakeResponse(status_code=404)
        )
        with pytest.raises(fred.FredKeylessError, match="renamed or retired"):
            _fred_plugin()._fetch_keyless_csv(
                "GHOST", datetime(2024, 1, 1), datetime(2024, 2, 1)
            )

    def test_html_payload_is_refused(self, monkeypatch):
        import backend.plugins.fred_plugin as fred

        monkeypatch.setattr(
            fred.requests, "get",
            lambda *a, **k: _FakeResponse(text="<html><body>nope</body></html>"),
        )
        with pytest.raises(fred.FredKeylessError):
            _fred_plugin()._fetch_keyless_csv(
                "GDP", datetime(2024, 1, 1), datetime(2024, 2, 1)
            )

    def test_keyless_fetch_error_returns_none_per_contract(self, monkeypatch):
        import backend.plugins.fred_plugin as fred

        monkeypatch.setattr(
            fred.requests, "get", lambda *a, **k: _FakeResponse(status_code=500)
        )
        df = _fred_plugin().fetch_indicator_data(
            "STLFSI4", datetime(2024, 1, 1), datetime(2024, 2, 1)
        )
        assert df is None

    def test_keyed_path_does_not_touch_the_csv_endpoint(self, monkeypatch):
        import backend.plugins.fred_plugin as fred

        calls = []
        monkeypatch.setattr(
            fred.requests, "get",
            lambda *a, **k: calls.append(a) or _FakeResponse(text=FRED_CSV),
        )

        class FakeFred:
            def __init__(self, api_key):
                self.api_key = api_key

            def get_series(self, series, observation_start=None, observation_end=None):
                return pd.Series(
                    [0.98], index=pd.to_datetime(["2024-01-05"]), name=series
                )

        fake_module = type("fredapi", (), {"Fred": FakeFred})
        monkeypatch.setitem(__import__("sys").modules, "fredapi", fake_module)
        df = _fred_plugin({"api_key": "TESTKEY"}).fetch_indicator_data(
            "STLFSI4", datetime(2024, 1, 1), datetime(2024, 2, 1)
        )
        assert df is not None and df["Value"].tolist() == [0.98]
        assert calls == []

    def test_keyed_path_falls_back_when_api_is_unreachable(self, monkeypatch):
        import backend.plugins.fred_plugin as fred

        class FailingFred:
            def __init__(self, api_key):
                self.api_key = api_key

            def get_series(self, series, observation_start=None, observation_end=None):
                raise OSError("api.stlouisfed.org is unavailable")

        fake_module = type("fredapi", (), {"Fred": FailingFred})
        monkeypatch.setitem(__import__("sys").modules, "fredapi", fake_module)
        monkeypatch.setattr(
            fred.requests, "get", lambda *a, **k: _FakeResponse(text=FRED_CSV)
        )

        df = _fred_plugin({"api_key": "TESTKEY"}).fetch_indicator_data(
            "STLFSI4", datetime(2024, 1, 1), datetime(2024, 2, 1)
        )

        assert df is not None and df["Value"].tolist() == [0.98, 1.02]

    def test_keyless_connection_probe(self, monkeypatch):
        import backend.plugins.fred_plugin as fred

        monkeypatch.setattr(
            fred.requests, "get", lambda *a, **k: _FakeResponse(text=FRED_CSV)
        )
        result = _fred_plugin().test_connection()
        assert result["success"] is True
        assert result["details"]["access"] == "keyless_csv"

    def test_missing_key_is_not_a_validation_error(self):
        _fred_plugin().validate_config()  # must not raise


# ---------------------------------------------------------------------------
# SEC public submissions fallback
# ---------------------------------------------------------------------------


def test_sec_public_submissions_uses_current_filing_date_field(monkeypatch):
    from backend.plugins.sec_plugin import SECPlugin

    plugin = SECPlugin.__new__(SECPlugin)
    plugin.config = {"user_agent": "BEACON/test@example.com"}
    payload = {
        "cik": "0000019617",
        "name": "JPMORGAN CHASE & CO",
        "filings": {
            "recent": {
                "filingDate": ["2024-02-16"],
                "form": ["10-K"],
                "accessionNumber": ["0000019617-24-000001"],
                "primaryDocument": ["jpm-20231231.htm"],
                "reportDate": ["2023-12-31"],
            }
        },
    }
    monkeypatch.setattr(plugin, "_official_submissions", lambda ticker: payload)

    frame = plugin._fetch_official_data(
        "JPM",
        datetime(2000, 1, 1),
        datetime(2026, 12, 31),
        {"filing_types": ["10-K"]},
    )

    assert len(frame) == 1
    assert frame.iloc[0]["form_type"] == "10-K"


def test_sec_catalogue_tickers_do_not_require_ticker_manifest(monkeypatch):
    from backend.plugins.sec_plugin import SECPlugin

    plugin = SECPlugin.__new__(SECPlugin)
    plugin.config = {}

    def manifest_must_not_be_called(*args, **kwargs):
        raise AssertionError("catalogue tickers should use their stable CIK")

    monkeypatch.setattr(plugin, "_official_get", manifest_must_not_be_called)

    assert plugin._ticker_cik("JPM") == "0000019617"
    assert plugin._ticker_cik("BLK") == "0001364742"


def test_sec_public_submissions_reads_historical_submission_blocks(monkeypatch):
    from backend.plugins.sec_plugin import SECPlugin

    plugin = SECPlugin.__new__(SECPlugin)
    plugin.config = {"user_agent": "BEACON/test@example.com"}
    payload = {
        "cik": "0000019617",
        "name": "JPMORGAN CHASE & CO",
        "filings": {
            "recent": {
                "filingDate": ["2024-02-16"],
                "form": ["10-K"],
                "accessionNumber": ["0000019617-24-000001"],
                "primaryDocument": ["jpm-20231231.htm"],
                "reportDate": ["2023-12-31"],
            },
            "files": [
                {
                    "name": "CIK0000019617-submissions-001.json",
                    "filingFrom": "2020-01-01",
                    "filingTo": "2023-12-31",
                },
                {
                    "name": "CIK0000019617-submissions-002.json",
                    "filingFrom": "2010-01-01",
                    "filingTo": "2019-12-31",
                },
            ],
        },
    }
    historical = {
        "filingDate": ["2023-02-17", "2019-02-15"],
        "form": ["10-K", "10-K"],
        "accessionNumber": ["0000019617-23-000001", "0000019617-19-000001"],
        "primaryDocument": ["jpm-20221231.htm", "jpm-20181231.htm"],
        "reportDate": ["2022-12-31", "2018-12-31"],
    }
    monkeypatch.setattr(plugin, "_official_submissions", lambda ticker: payload)
    monkeypatch.setattr(
        plugin,
        "_official_get",
        lambda url: historical if url.endswith("-001.json") else {"filingDate": [], "form": []},
    )

    frame = plugin._fetch_official_data(
        "JPM",
        datetime(2000, 1, 1),
        datetime(2026, 12, 31),
        {"filing_types": ["10-K"]},
    )

    assert len(frame) == 3
    assert frame.index.is_monotonic_increasing


def test_sec_public_timeout_remains_retryable(monkeypatch):
    import requests

    from backend.exceptions import DataSourceUnavailableError
    from backend.plugins.sec_plugin import SECPlugin

    plugin = SECPlugin.__new__(SECPlugin)
    plugin.config = {}

    def fail(*args, **kwargs):
        raise requests.Timeout("SEC timed out")

    monkeypatch.setattr(plugin, "fetch_data", fail)

    with pytest.raises(DataSourceUnavailableError) as exc_info:
        plugin.fetch_indicator_data(
            "JPM.10-K",
            datetime(2020, 1, 1),
            datetime(2026, 12, 31),
        )

    assert exc_info.value.code == "DATA_SOURCE_UNAVAILABLE"


def test_sec_public_submissions_keeps_rows_when_one_history_block_times_out(monkeypatch):
    import requests

    from backend.plugins.sec_plugin import SECPlugin

    plugin = SECPlugin.__new__(SECPlugin)
    plugin.config = {"user_agent": "BEACON/test@example.com"}
    payload = {
        "cik": "0000019617",
        "name": "JPMORGAN CHASE & CO",
        "filings": {
            "recent": {
                "filingDate": ["2024-02-16"],
                "form": ["10-K"],
                "accessionNumber": ["0000019617-24-000001"],
                "primaryDocument": ["jpm-20231231.htm"],
                "reportDate": ["2023-12-31"],
            },
            "files": [
                {
                    "name": "CIK0000019617-submissions-001.json",
                    "filingFrom": "2020-01-01",
                    "filingTo": "2023-12-31",
                },
                {
                    "name": "CIK0000019617-submissions-002.json",
                    "filingFrom": "2010-01-01",
                    "filingTo": "2019-12-31",
                },
            ],
        },
    }
    historical = {
        "filingDate": ["2023-02-17"],
        "form": ["10-K"],
        "accessionNumber": ["0000019617-23-000001"],
        "primaryDocument": ["jpm-20221231.htm"],
        "reportDate": ["2022-12-31"],
    }

    monkeypatch.setattr(plugin, "_official_submissions", lambda ticker: payload)

    def get_block(url):
        if url.endswith("-001.json"):
            return historical
        raise requests.Timeout("SEC archive shard timed out")

    monkeypatch.setattr(plugin, "_official_get", get_block)

    frame = plugin._fetch_official_data(
        "JPM",
        datetime(2000, 1, 1),
        datetime(2026, 12, 31),
        {"filing_types": ["10-K"]},
    )

    assert len(frame) == 2


# ---------------------------------------------------------------------------
# FDIC rewrite (payload shape verified against the live API, 2026-09-15)
# ---------------------------------------------------------------------------


FDIC_PAYLOAD = {
    "meta": {"total": 2},
    "data": [
        {"data": {"CERT": 628, "NAME": "JPMORGAN CHASE BANK NA",
                  "REPDTE": "20240331", "ASSET": 3503360000}, "score": 0},
        {"data": {"CERT": 628, "NAME": "JPMORGAN CHASE BANK NA",
                  "REPDTE": "20240630", "ASSET": None}, "score": 0},
    ],
}


def _fdic_plugin():
    from backend.plugins.fdic_plugin import FDICPlugin

    plugin = FDICPlugin.__new__(FDICPlugin)
    plugin.config = {}
    return plugin


class TestFDICPlugin:
    def test_verified_payload_shape_parses_and_nulls_are_dropped(self, monkeypatch):
        import backend.plugins.fdic_plugin as fdic

        captured = {}

        def fake_get(url, params=None, timeout=None):
            captured.update(url=url, params=params)
            return _FakeResponse(json_payload=FDIC_PAYLOAD)

        monkeypatch.setattr(fdic.requests, "get", fake_get)
        df = _fdic_plugin().fetch_indicator_data(
            "ASSET:628", datetime(2024, 1, 1), datetime(2024, 12, 31)
        )
        assert df is not None and len(df) == 1  # the null ASSET row is a gap, not a zero
        assert df["Value"].tolist() == [3503360000.0]
        assert df["Date"].iloc[0] == pd.Timestamp("2024-03-31")
        assert captured["params"]["filters"] == (
            "CERT:628 AND REPDTE:[20240101 TO 20241231]"
        )
        assert "ASSET" in captured["params"]["fields"]

    def test_undeclared_field_is_refused_not_guessed(self):
        from backend.plugins.fdic_plugin import FDICFieldError

        with pytest.raises(FDICFieldError, match="SUPPORTED_FIELDS"):
            _fdic_plugin().fetch_indicator_data(
                "IBASSET:628", datetime(2024, 1, 1), datetime(2024, 12, 31)
            )

    def test_malformed_indicator_is_refused(self):
        from backend.plugins.fdic_plugin import FDICFieldError

        for bad in ["ASSET", "ASSET:", ":628", "ASSET:JPMC"]:
            with pytest.raises(FDICFieldError):
                _fdic_plugin().fetch_indicator_data(
                    bad, datetime(2024, 1, 1), datetime(2024, 12, 31)
                )

    def test_empty_result_is_none_not_invented(self, monkeypatch):
        import backend.plugins.fdic_plugin as fdic

        monkeypatch.setattr(
            fdic.requests, "get",
            lambda *a, **k: _FakeResponse(json_payload={"meta": {"total": 0}, "data": []}),
        )
        assert _fdic_plugin().fetch_indicator_data(
            "ASSET:99999", datetime(2024, 1, 1), datetime(2024, 12, 31)
        ) is None

    def test_request_failure_returns_none(self, monkeypatch):
        import backend.plugins.fdic_plugin as fdic
        import requests as real_requests

        def boom(*a, **k):
            raise real_requests.RequestException("network down")

        monkeypatch.setattr(fdic.requests, "get", boom)
        assert _fdic_plugin().fetch_indicator_data(
            "ASSET:628", datetime(2024, 1, 1), datetime(2024, 12, 31)
        ) is None

    def test_connection_probe_reports_index_size(self, monkeypatch):
        import backend.plugins.fdic_plugin as fdic

        monkeypatch.setattr(
            fdic.requests, "get",
            lambda *a, **k: _FakeResponse(json_payload=FDIC_PAYLOAD),
        )
        result = _fdic_plugin().test_connection()
        assert result["success"] is True
        assert result["details"]["index_total"] == 2

    def test_plugin_is_keyless(self):
        from backend.plugins.fdic_plugin import FDICPlugin

        info = FDICPlugin.get_plugin_info()
        assert info["free"] is True
        assert info["registration_required"] is False
