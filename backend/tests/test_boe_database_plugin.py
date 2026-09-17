"""BoE Interactive Database plugin: a strict reader of an observed contract.

The fixture below is the REAL table captured from
``boeapps/database/fromshowcolumns.asp`` during the executed probe
(2026-09-17, ``IUDBEDR``, 02/Jan/2024-08/Jan/2024, five business-day rows at
5.25 -- weekends absent, as published). Every parsing assertion here runs
against those bytes, not an imagined page.

The tests pin the probe's YELLOW-path contract: schema drift is a typed
loud failure (never silent empty data), the catalogue refuses unverified
series codes, an empty window is None per the plugin contract, and the
two-digit-year pivot -- Bank Rate history reaches 1694, and Python's %y
pivot would read '57 as 2057 -- is a declared, boundary-tested rule.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from backend.plugins import get_plugin
from backend.plugins.boe_database_plugin import (
    BoEDatabaseError,
    BoEDatabasePlugin,
    _parse_boe_date,
)

# Captured verbatim from the probe (whitespace-normalised); the thead names
# the series exactly as the live page does.
REAL_TABLE = """
<html><body>
<table id="stats-table" class="display" style="display:table;width:50%; " >
<thead> <tr>
<th width="150" style="min-width:150px; text-align:right !important" align="right" valign="bottom">Date</th>
<th style="font-weight:normal; text-align:right !important">
<span style='font-size:14px'>Official Bank Rate</span><br>
<span style='font-size:11px'><a href='#notes'>[a] [b]</a></span>
<br><strong class='highlight'>IUDBEDR</strong> </th>
</tr> </thead>
<tbody>
<tr><td align="right">02 Jan 24</td><td align="right">5.25</td></tr>
<tr><td align="right">03 Jan 24</td><td align="right">5.25</td></tr>
<tr><td align="right">04 Jan 24</td><td align="right">5.25</td></tr>
<tr><td align="right">05 Jan 24</td><td align="right">5.25</td></tr>
<tr><td align="right">08 Jan 24</td><td align="right">5.25</td></tr>
</tbody>
</table>
<table><tr><td>&nbsp;</td><td>Yes</td><td>Yes</td></tr></table>
</body></html>
"""


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200, url: str = "https://www.bankofengland.co.uk/boeapps/database/fromshowcolumns.asp"):
        self.text = text
        self.status_code = status_code
        self.url = url


@pytest.fixture()
def plugin() -> BoEDatabasePlugin:
    return BoEDatabasePlugin(config={})


def _mock_get(monkeypatch, response: _FakeResponse):
    import backend.plugins.boe_database_plugin as mod

    calls = []

    def fake_get(url, params=None, headers=None, timeout=None):
        calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        return response

    monkeypatch.setattr(mod.requests, "get", fake_get)
    return calls


class TestRegistrationAndProvenance:
    def test_registered_in_the_runtime_registry(self):
        # The loader-list incident (three plugins present in the tree but
        # absent from plugin_specs, so unselectable) is why this is explicit.
        assert get_plugin("boe_database") is not None

    def test_curated_provenance_exists(self):
        from backend.modules.data.provenance import CURATED_PROVENANCE

        record = CURATED_PROVENANCE.get("boe_database")
        assert record is not None
        assert record.publisher == "Bank of England"
        assert record.provenance_class == "official_statistics"
        # The open licence question is recorded, not hidden.
        assert "licence unconfirmed" in record.provides


class TestParsingTheObservedContract:
    def test_real_captured_table_parses_to_date_value_rows(self, plugin, monkeypatch):
        _mock_get(monkeypatch, _FakeResponse(REAL_TABLE))
        frame = plugin.fetch_indicator_data("bank_rate", datetime(2024, 1, 1), datetime(2024, 1, 31))

        assert frame is not None
        assert list(frame.columns) == ["Date", "Value"]
        assert len(frame) == 5  # business days only; the weekend is absent, as published
        assert frame["Date"].tolist() == [pd.Timestamp(f"2024-01-{d:02d}") for d in (2, 3, 4, 5, 8)]
        assert (frame["Value"] == 5.25).all()

    def test_request_carries_identifying_ua_and_dd_mon_yyyy_dates(self, plugin, monkeypatch):
        calls = _mock_get(monkeypatch, _FakeResponse(REAL_TABLE))
        plugin.fetch_indicator_data("bank_rate", datetime(2024, 1, 2), datetime(2024, 1, 8))

        assert len(calls) == 1  # one request per fetch: politeness is part of the contract
        assert "beacon-platform" in calls[0]["headers"]["User-Agent"]
        assert calls[0]["params"]["Datefrom"] == "02/Jan/2024"
        assert calls[0]["params"]["Dateto"] == "08/Jan/2024"
        assert calls[0]["params"]["SeriesCodes"] == "IUDBEDR"

    def test_window_filter_is_applied_after_parse(self, plugin, monkeypatch):
        _mock_get(monkeypatch, _FakeResponse(REAL_TABLE))
        frame = plugin.fetch_indicator_data("bank_rate", datetime(2024, 1, 3), datetime(2024, 1, 5))
        assert len(frame) == 3


class TestDriftFailsLoudly:
    def test_missing_data_table_is_an_error_not_empty(self, plugin, monkeypatch):
        _mock_get(monkeypatch, _FakeResponse("<html><body><p>maintenance</p></body></html>"))
        with pytest.raises(BoEDatabaseError, match="no data table"):
            plugin.fetch_indicator_data("bank_rate", datetime(2024, 1, 1), datetime(2024, 1, 31))

    def test_non_numeric_value_is_schema_drift(self, plugin, monkeypatch):
        drifted = REAL_TABLE.replace(
            '<tr><td align="right">04 Jan 24</td><td align="right">5.25</td></tr>',
            '<tr><td align="right">04 Jan 24</td><td align="right">n/a</td></tr>',
        )
        _mock_get(monkeypatch, _FakeResponse(drifted))
        with pytest.raises(BoEDatabaseError, match="non-numeric"):
            plugin.fetch_indicator_data("bank_rate", datetime(2024, 1, 1), datetime(2024, 1, 31))

    def test_unparseable_date_is_schema_drift(self, plugin, monkeypatch):
        drifted = REAL_TABLE.replace(">02 Jan 24<", ">02/01/2024<")
        _mock_get(monkeypatch, _FakeResponse(drifted))
        with pytest.raises(BoEDatabaseError, match="unparseable BoE date"):
            plugin.fetch_indicator_data("bank_rate", datetime(2024, 1, 1), datetime(2024, 1, 31))

    def test_errorpage_redirect_is_refused(self, plugin, monkeypatch):
        _mock_get(monkeypatch, _FakeResponse(
            REAL_TABLE, url="https://www.bankofengland.co.uk/boeapps/database/ErrorPage.asp"
        ))
        with pytest.raises(BoEDatabaseError, match="ErrorPage"):
            plugin.fetch_indicator_data("bank_rate", datetime(2024, 1, 1), datetime(2024, 1, 31))

    def test_http_error_is_typed(self, plugin, monkeypatch):
        _mock_get(monkeypatch, _FakeResponse("", status_code=503))
        with pytest.raises(BoEDatabaseError, match="HTTP 503"):
            plugin.fetch_indicator_data("bank_rate", datetime(2024, 1, 1), datetime(2024, 1, 31))

    def test_empty_window_is_none_not_an_error(self, plugin, monkeypatch):
        empty = REAL_TABLE.replace(
            "<tbody>", "<tbody>"
        )
        empty = empty.split("<tbody>")[0] + "<tbody></tbody></table></body></html>"
        _mock_get(monkeypatch, _FakeResponse(empty))
        assert plugin.fetch_indicator_data("bank_rate", datetime(2024, 1, 1), datetime(2024, 1, 31)) is None


class TestCatalogueIsEvidenceFirst:
    def test_unknown_series_refuses_and_points_at_config(self, plugin):
        with pytest.raises(BoEDatabaseError, match="rather than have the plugin guess"):
            plugin.fetch_indicator_data("SOME_INVENTED_CODE", datetime(2024, 1, 1), datetime(2024, 1, 2))

    def test_operator_declared_series_resolve(self, monkeypatch):
        declared = BoEDatabasePlugin(config={"series": {"sonia_like": "IUDSBOR"}})
        calls = _mock_get(monkeypatch, _FakeResponse(REAL_TABLE.replace("IUDBEDR", "IUDSBOR")))
        frame = declared.fetch_indicator_data("sonia_like", datetime(2024, 1, 1), datetime(2024, 1, 31))
        assert frame is not None and len(frame) == 5
        assert calls[0]["params"]["SeriesCodes"] == "IUDSBOR"

    def test_malformed_series_config_is_refused(self):
        with pytest.raises(BoEDatabaseError):
            BoEDatabasePlugin(config={"series": ["not-a-mapping"]}).validate_config()


class TestCenturyPivot:
    def test_two_digit_years_use_the_declared_pivot(self):
        # Bank Rate history reaches 1694: '57 is 1957, never 2057.
        assert _parse_boe_date("05 Jan 57") == pd.Timestamp("1957-01-05")
        assert _parse_boe_date("02 Jan 24") == pd.Timestamp("2024-01-02")

    def test_four_digit_years_and_full_month_names(self):
        assert _parse_boe_date("05 Jan 1957") == pd.Timestamp("1957-01-05")
        assert _parse_boe_date("05 January 1957") == pd.Timestamp("1957-01-05")

    def test_current_year_boundary_maps_to_2000s(self):
        yy = datetime.now().year % 100
        assert _parse_boe_date(f"05 Jan {yy:02d}") == pd.Timestamp(datetime(datetime.now().year, 1, 5))


class TestConnectionProbe:
    def test_success_reports_parsed_rows(self, plugin, monkeypatch):
        _mock_get(monkeypatch, _FakeResponse(REAL_TABLE))
        result = plugin.test_connection()
        assert result["success"] is True
        assert "5 row(s)" in result["message"]

    def test_drift_is_reported_not_raised(self, plugin, monkeypatch):
        _mock_get(monkeypatch, _FakeResponse("<html><body>gone</body></html>"))
        result = plugin.test_connection()
        assert result["success"] is False
        assert "no data table" in result["message"]
