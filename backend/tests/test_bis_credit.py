"""Tests for the BIS total-credit (private credit) connector.

The suite is offline: every payload is an inline excerpt that was captured from
``https://stats.bis.org/api/v1/data/WS_TC/all?format=csv`` with ``curl`` on
2026-09-11. The header and row formats are the real ones; the only synthesized
rows are explicitly labelled as such, and they exist solely to exercise paths the
two sampled quarters did not contain (a suppressed cell, a conflicting duplicate,
a malformed period).

The tests are organised around the failure modes that matter for a point-in-time
feed: a quarter must map to its own end date, a suppressed cell must not be read
as zero and must not kill the batch, a revised duplicate must fail rather than
silently overwrite, and ``observed_at`` must never precede ``valid_time``.
"""

from __future__ import annotations

import csv
import io
from typing import Any, Dict, List, Optional, Sequence

import pandas as pd
import pytest

from backend.exceptions import EmptyDatasetError, SchemaValidationError
from backend.modules.data.connectors import CONNECTORS, build_connector
from backend.modules.data.connectors.base import FetchRequest
from backend.modules.data.connectors.bis_credit import (
    BIS_DATA_ENDPOINT,
    BIS_DATA_PORTAL_URL,
    BIS_RELEASE_CALENDAR_ENDPOINT,
    BIS_TC_COLUMNS,
    DEFAULT_PUBLICATION_LAG_DAYS,
    BisCreditConnector,
    parse_release_calendar,
)
from backend.modules.data.pit import OBSERVATION_COLUMNS, PITStore

# --------------------------------------------------------------------------- #
# Real fixtures
# --------------------------------------------------------------------------- #

#: Verbatim excerpt of a real ``WS_TC`` response: the real header plus eight real
#: rows from the 2025-Q3/Q4 pull. It deliberately includes out-of-slice rows
#: (``ZA/C``, ``US/G``, and the two ``TC_ADJUST=U`` Ireland rows) so the default
#: private-credit slice has something to reject.
BIS_TC_CSV = """FREQ,BORROWERS_CTY,TC_BORROWERS,TC_LENDERS,VALUATION,UNIT_TYPE,TC_ADJUST,COLLECTION,DECIMALS,UNIT_MULT,UNIT_MEASURE,TITLE_TS,TIME_PERIOD,OBS_VALUE,OBS_STATUS,OBS_PRE_BREAK,OBS_CONF
Q,LU,N,A,M,770,A,E,1,0,367,Luxembourg - Credit to Non-financial corporations from All sectors at Market value - Percentage of GDP - Adjusted for breaks,2025-Q3,362.7,A,,F
Q,LU,N,A,M,770,A,E,1,0,367,Luxembourg - Credit to Non-financial corporations from All sectors at Market value - Percentage of GDP - Adjusted for breaks,2025-Q4,358.8,A,,F
Q,NZ,P,B,M,770,A,E,1,0,367,"New Zealand - Credit to Private non-financial sector from Banks, total at Market value - Percentage of GDP - Adjusted for breaks",2025-Q4,132.8,A,,F
Q,SE,P,A,M,USD,A,E,3,9,USD,Sweden - Credit to Private non-financial sector from All sectors at Market value - US dollar - Adjusted for breaks,2025-Q4,1657.085,A,,F
Q,ZA,C,A,M,770,A,E,1,0,367,South Africa - Credit to Non financial sector from All sectors at Market value - Percentage of GDP - Adjusted for breaks,2025-Q4,145.6,A,,F
Q,4T,N,A,M,USD,A,E,3,9,USD,Emerging market economies (aggregate) - Credit to Non-financial corporations from All sectors at Market value - US dollar - Adjusted for breaks,2025-Q4,38342.782,A,,F
Q,IE,N,A,M,XDC,A,E,3,9,EUR,Ireland - Credit to Non-financial corporations from All sectors at Market value - domestic currency - Adjusted for breaks,2025-Q3,598.108,A,,F
Q,IE,N,A,M,XDC,A,E,3,9,EUR,Ireland - Credit to Non-financial corporations from All sectors at Market value - domestic currency - Adjusted for breaks,2025-Q4,590.892,A,,F
Q,IE,N,A,M,XDC,U,E,3,9,EUR,Ireland - Credit to Non-financial corporations from All sectors at Market value - domestic currency - Unadjusted,2025-Q3,598.108,A,,F
Q,IE,N,A,M,XDC,U,E,3,9,EUR,Ireland - Credit to Non-financial corporations from All sectors at Market value - domestic currency - Unadjusted,2025-Q4,590.892,A,,F
Q,US,H,A,M,USD,A,E,3,9,USD,United States - Credit to Households and NPISHs from All sectors at Market value - US dollar - Adjusted for breaks,2025-Q4,20934.549,A,,F
Q,US,G,A,M,770,A,E,1,0,367,United States - Credit to General government from All sectors at Market value - Percentage of GDP - Adjusted for breaks,2025-Q4,111,A,,F
"""

#: Verbatim excerpt of a real ``BIS_REL_CAL`` response (release-calendar dataflow),
#: header plus the first real row and the four TOTAL_CREDIT rows that pin the
#: 2025-Q4 release date used below.
BIS_REL_CAL_CSV = """FREQ,CATEGORY,RELEASE_TYPE,TIME_PERIOD,OBS_VALUE,OBS_STATUS,OBS_PRE_BREAK,OBS_CONF,COMMENTARY
M,RPP,DPP,2024-03,20240530,A,,F,
Q,TOTAL_CREDIT,S,2023-Q1,20230918,A,,F,
Q,TOTAL_CREDIT,S,2024-Q4,20250616,A,,F,
Q,TOTAL_CREDIT,S,2025-Q4,20260615,A,,F,
Q,TOTAL_CREDIT,S,2026-Q2,20261207,A,,F,
"""

#: 2025-09-30 + 171 days and 2025-12-31 + 171 days, the default fallback stamps.
_Q3_DEFAULT_OBSERVED = pd.Timestamp("2026-03-20")
_Q4_DEFAULT_OBSERVED = pd.Timestamp("2026-06-20")


def _payload(text: str) -> bytes:
    return text.encode("utf-8")


def _rows(text: str = BIS_TC_CSV) -> List[Dict[str, str]]:
    return [dict(row) for row in csv.DictReader(io.StringIO(text))]


def _fields(rows: Sequence[Dict[str, str]]) -> List[str]:
    return list(rows[0].keys())


def _dump(rows: Sequence[Dict[str, str]], fields: Optional[Sequence[str]] = None) -> bytes:
    """Serialise rows back to CSV bytes, optionally reordering/dropping columns."""
    names = list(fields) if fields is not None else _fields(rows)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=names, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({name: row.get(name, "") for name in names})
    return buffer.getvalue().encode("utf-8")


def _pick(rows: Sequence[Dict[str, str]], **criteria: str) -> Dict[str, str]:
    for row in rows:
        if all(row[key] == value for key, value in criteria.items()):
            return dict(row)
    raise AssertionError(f"fixture has no row matching {criteria}")


class _StubClient:
    """Minimal stand-in for ``HttpClient`` that serves recorded bytes."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls: List[Dict[str, Any]] = []

    def get(
        self,
        url: str,
        *,
        params: Any = None,
        accept: Optional[str] = None,
        connector: str = "connector",
    ) -> bytes:
        self.calls.append(
            {"url": url, "params": params, "accept": accept, "connector": connector}
        )
        return self.payload


class _ExplodingClient:
    """Fails loudly if anything tries to touch the network during parsing."""

    def get(self, url: str, **kwargs: Any) -> bytes:
        raise AssertionError("parse() must not perform network I/O")


@pytest.fixture()
def connector() -> BisCreditConnector:
    return BisCreditConnector(client=_ExplodingClient())


class TestSpec:
    def test_identity_and_cadence(self, connector):
        assert connector.spec.name == "bis_credit"
        assert connector.spec.kind == "bis"
        assert connector.spec.cadence == "quarterly"
        assert connector.spec.requires_credentials is False

    def test_points_at_the_verified_endpoint_and_portal(self, connector):
        assert connector.spec.endpoint == BIS_DATA_ENDPOINT
        assert connector.spec.source_url == BIS_DATA_PORTAL_URL
        assert BIS_DATA_ENDPOINT.endswith("/data/WS_TC/all")

    def test_licence_states_the_bis_attribution_condition(self, connector):
        # The binding condition we verified is attribution, not a blanket licence.
        licence = connector.spec.licence
        assert "BIS" in licence
        assert "cited" in licence.lower()


class TestBuildUrl:
    def test_without_bounds_asks_for_everything(self, connector):
        assert connector.build_url(FetchRequest()) == f"{BIS_DATA_ENDPOINT}?format=csv"

    def test_with_bounds_emits_period_parameters(self, connector):
        url = connector.build_url(FetchRequest(start="2025-Q1", end="2025-Q4"))
        assert url == (
            f"{BIS_DATA_ENDPOINT}?format=csv&startPeriod=2025-Q1&endPeriod=2025-Q4"
        )

    def test_mid_quarter_bounds_coarsen_to_the_containing_quarter(self, connector):
        url = connector.build_url(FetchRequest(start="2025-02-14", end="2025-11-02"))
        assert "startPeriod=2025-Q1" in url
        assert "endPeriod=2025-Q4" in url

    def test_single_bound_is_supported(self, connector):
        start_only = connector.build_url(FetchRequest(start="2025-05-01"))
        end_only = connector.build_url(FetchRequest(end="2025-05-01"))
        assert start_only.endswith("startPeriod=2025-Q2")
        assert end_only.endswith("endPeriod=2025-Q2")


class TestHappyPath:
    def test_parses_the_private_slice(self, connector):
        frame = connector.parse(_payload(BIS_TC_CSV), FetchRequest())

        # 12 real rows, of which ZA/C, US/G and the two adjust=U Ireland rows fall
        # outside the default borrowers/lenders/adjustments slice.
        assert frame.shape[0] == 8
        assert list(frame.columns) == list(OBSERVATION_COLUMNS)
        assert set(frame["entity_id"]) == {"LU", "NZ", "SE", "4T", "IE", "US"}
        assert set(frame["series_id"]) == {
            "BIS:TC:borrowers=N:lenders=A:val=M:unit=770",
            "BIS:TC:borrowers=P:lenders=B:val=M:unit=770",
            "BIS:TC:borrowers=P:lenders=A:val=M:unit=USD",
            "BIS:TC:borrowers=N:lenders=A:val=M:unit=USD",
            "BIS:TC:borrowers=N:lenders=A:val=M:unit=XDC",
            "BIS:TC:borrowers=H:lenders=A:val=M:unit=USD",
        }

    def test_reports_what_it_skipped(self, connector):
        connector.parse(_payload(BIS_TC_CSV), FetchRequest())
        stats = connector.last_stats
        assert stats.rows_in_payload == 12
        assert stats.rows_out_of_slice == 4
        assert stats.rows_suppressed == 0
        assert stats.duplicate_rows_collapsed == 0
        assert stats.rows_emitted == 8

    def test_values_are_stored_as_published(self, connector):
        frame = connector.parse(_payload(BIS_TC_CSV), FetchRequest())
        sweden = frame[
            (frame["entity_id"] == "SE")
            & (frame["series_id"] == "BIS:TC:borrowers=P:lenders=A:val=M:unit=USD")
        ]
        # UNIT_TYPE=USD rows carry UNIT_MULT=9 (billions). Storing 1657.085 as
        # 1.657e12 would apply a conversion the connector deliberately does not.
        assert float(sweden["value"].iloc[0]) == pytest.approx(1657.085)
        assert int(sweden["revision"].iloc[0]) == 0

    def test_parse_performs_no_network_io(self, connector):
        # The fixture client raises on any get(); parsing must still succeed.
        frame = connector.parse(_payload(BIS_TC_CSV), FetchRequest())
        assert not frame.empty

    def test_request_window_narrows_the_result(self, connector):
        frame = connector.parse(
            _payload(BIS_TC_CSV), FetchRequest(start="2025-10-01", end="2025-12-31")
        )
        # Only the six Q4 rows in the default slice survive; the two Q3 rows
        # (LU and IE) are filtered by the exact request window.
        assert set(frame["entity_id"]) == {"LU", "NZ", "SE", "4T", "IE", "US"}
        assert set(frame["valid_time"]) == {pd.Timestamp("2025-12-31")}
        assert connector.last_stats.rows_filtered_by_request == 2

    def test_quarter_label_bounds_cover_the_whole_quarter(self, connector):
        # ``pd.Timestamp("2025-Q4")`` is 2025-10-01, so an exact-bound filter
        # would drop every Q4 row, whose valid_time is the quarter's last day.
        # The window is applied at quarter granularity, matching the URL.
        frame = connector.parse(
            _payload(BIS_TC_CSV), FetchRequest(start="2025-Q4", end="2025-Q4")
        )
        assert set(frame["valid_time"]) == {pd.Timestamp("2025-12-31")}
        assert frame.shape[0] == 6

    def test_entity_and_series_scopes_are_applied(self, connector):
        # BIS is not sent these filters, so parse is where they must take effect.
        by_entity = connector.parse(
            _payload(BIS_TC_CSV), FetchRequest(entity_ids=("SE",))
        )
        assert set(by_entity["entity_id"]) == {"SE"}

        series = "BIS:TC:borrowers=N:lenders=A:val=M:unit=770"
        by_series = connector.parse(
            _payload(BIS_TC_CSV), FetchRequest(series_ids=(series,))
        )
        assert set(by_series["series_id"]) == {series}
        assert set(by_series["entity_id"]) == {"LU"}


class TestValidTime:
    def test_quarter_maps_to_the_end_of_that_quarter(self, connector):
        frame = connector.parse(_payload(BIS_TC_CSV), FetchRequest())
        lu = frame[frame["entity_id"] == "LU"]
        by_quarter = {
            str(row.valid_time.date()): float(row.value)
            for row in lu.itertuples()
        }
        assert by_quarter == {"2025-09-30": 362.7, "2025-12-31": 358.8}

    @pytest.mark.parametrize(
        ("period", "expected"),
        [
            ("2025-Q1", "2025-03-31"),
            ("2025-Q2", "2025-06-30"),
            ("2025-Q3", "2025-09-30"),
            ("2025-Q4", "2025-12-31"),
            ("2024-Q4", "2024-12-31"),
        ],
    )
    def test_every_quarter_end(self, connector, period, expected):
        # Synthetic: a real row with only its TIME_PERIOD changed, so the real
        # header and row shape are preserved.
        row = _pick(_rows(), BORROWERS_CTY="LU", TC_BORROWERS="N", TIME_PERIOD="2025-Q4")
        row["TIME_PERIOD"] = period
        frame = connector.parse(_dump([row]), FetchRequest())
        assert pd.Timestamp(frame["valid_time"].iloc[0]) == pd.Timestamp(expected)

    def test_period_is_the_quarter_end_not_the_start(self, connector):
        frame = connector.parse(_payload(BIS_TC_CSV), FetchRequest())
        for stamp in frame["valid_time"]:
            assert stamp.day >= 28, "a quarter must end on the month's last day"


class TestSeriesId:
    def test_exact_key_convention(self, connector):
        frame = connector.parse(_payload(BIS_TC_CSV), FetchRequest())
        lux = frame[frame["entity_id"] == "LU"].iloc[0]
        assert lux["series_id"] == "BIS:TC:borrowers=N:lenders=A:val=M:unit=770"

    def test_key_names_all_coded_dimensions(self, connector):
        frame = connector.parse(_payload(BIS_TC_CSV), FetchRequest())
        ireland = frame[
            (frame["entity_id"] == "IE") & (frame["valid_time"] == "2025-12-31")
        ].iloc[0]
        assert ireland["series_id"] == (
            "BIS:TC:borrowers=N:lenders=A:val=M:unit=XDC"
        )

    def test_entity_is_the_borrower_country_aggregate_included(self, connector):
        frame = connector.parse(_payload(BIS_TC_CSV), FetchRequest())
        assert "4T" in set(frame["entity_id"])


class TestSliceIsConfigurable:
    def test_government_and_non_financial_sector_are_excluded_by_default(self, connector):
        frame = connector.parse(_payload(BIS_TC_CSV), FetchRequest())
        borrowers = {sid.split(":")[2].split("=")[1] for sid in frame["series_id"]}
        assert borrowers == {"P", "N", "H"}

    def test_widening_the_slice_includes_government(self):
        connector = BisCreditConnector(
            borrowers=("P", "N", "H", "C", "G"), client=_ExplodingClient()
        )
        frame = connector.parse(_payload(BIS_TC_CSV), FetchRequest())
        assert "ZA" in set(frame["entity_id"])
        assert "US" in set(frame["entity_id"])

    def test_unadjusted_rows_are_excluded_by_default(self, connector):
        frame = connector.parse(_payload(BIS_TC_CSV), FetchRequest())
        # The two adjust=U Ireland rows carry the same coded dimensions as the
        # adjust=A rows, so including both would collide on the series key.
        assert frame.shape[0] == 8

    def test_unadjusted_slice_is_selectable_on_its_own(self):
        connector = BisCreditConnector(adjustments=("U",), client=_ExplodingClient())
        frame = connector.parse(_payload(BIS_TC_CSV), FetchRequest())
        assert set(frame["entity_id"]) == {"IE"}

    def test_empty_slice_is_rejected_at_construction(self):
        with pytest.raises(ValueError, match="borrowers"):
            BisCreditConnector(borrowers=())


class TestSuppressedCells:
    def test_empty_value_is_skipped_and_counted(self, connector):
        rows = _rows()
        suppressed = dict(_pick(rows, BORROWERS_CTY="LU", TIME_PERIOD="2025-Q4"))
        suppressed["OBS_VALUE"] = ""  # synthetic: a suppressed cell
        kept = dict(_pick(rows, BORROWERS_CTY="SE", TIME_PERIOD="2025-Q4"))
        frame = connector.parse(_dump([suppressed, kept]), FetchRequest())
        assert frame.shape[0] == 1
        assert set(frame["entity_id"]) == {"SE"}
        assert connector.last_stats.rows_suppressed == 1

    @pytest.mark.parametrize("placeholder", ["", "..", "-", "c", "NaN"])
    def test_placeholder_set_is_skipped(self, connector, placeholder):
        rows = _rows()
        row = dict(_pick(rows, BORROWERS_CTY="LU", TIME_PERIOD="2025-Q4"))
        row["OBS_VALUE"] = placeholder
        kept = dict(_pick(rows, BORROWERS_CTY="SE", TIME_PERIOD="2025-Q4"))
        payload = _dump([row, kept])
        frame = connector.parse(payload, FetchRequest())
        assert frame.shape[0] == 1
        assert connector.last_stats.rows_suppressed == 1

    def test_all_suppressed_raises_empty_not_a_zero_frame(self, connector):
        rows = _rows()
        row = dict(_pick(rows, BORROWERS_CTY="LU", TIME_PERIOD="2025-Q4"))
        row["OBS_VALUE"] = ""
        with pytest.raises(EmptyDatasetError):
            connector.parse(_dump([row]), FetchRequest())
        assert connector.last_stats.rows_suppressed == 1

    def test_present_but_non_numeric_value_fails_closed(self, connector):
        rows = _rows()
        row = dict(_pick(rows, BORROWERS_CTY="LU", TIME_PERIOD="2025-Q4"))
        row["OBS_VALUE"] = "not-a-number"  # schema drift, not suppression
        with pytest.raises(SchemaValidationError):
            connector.parse(_dump([row]), FetchRequest())


class TestUnitMultiplierSemantics:
    def test_multiplier_is_a_function_of_unit_type_in_the_real_data(self):
        # Verified against CL_UNIT_MULT: 9 = billions, 0 = units. If BIS ever
        # emits one UNIT_TYPE with two multipliers, series_id would no longer
        # determine the scale and this connector has to be revisited.
        rows = _rows()
        pairings = {(row["UNIT_TYPE"], row["UNIT_MULT"]) for row in rows}
        assert pairings == {
            ("770", "0"),
            ("USD", "9"),
            ("XDC", "9"),
        }

    def test_percent_of_gdp_values_are_not_rescaled(self, connector):
        frame = connector.parse(_payload(BIS_TC_CSV), FetchRequest())
        lux = frame[
            (frame["entity_id"] == "LU")
            & (frame["valid_time"] == pd.Timestamp("2025-12-31"))
        ].iloc[0]
        # 358.8 is already "percent of GDP"; multiplying by 10**0 is the no-op
        # this connector performs by storing the published value.
        assert float(lux["value"]) == pytest.approx(358.8)


class TestObservedAt:
    def test_default_lag_is_the_documented_assumption(self, connector):
        assert DEFAULT_PUBLICATION_LAG_DAYS == 171
        frame = connector.parse(_payload(BIS_TC_CSV), FetchRequest())
        for row in frame.itertuples():
            expected = (
                _Q3_DEFAULT_OBSERVED
                if row.valid_time == pd.Timestamp("2025-09-30")
                else _Q4_DEFAULT_OBSERVED
            )
            assert row.observed_at == expected

    def test_explicit_release_dates_override_the_lag(self):
        connector = BisCreditConnector(
            release_dates={"2025-Q4": "2026-06-15"}, client=_ExplodingClient()
        )
        frame = connector.parse(_payload(BIS_TC_CSV), FetchRequest())
        q4 = frame[frame["valid_time"] == pd.Timestamp("2025-12-31")]
        assert set(q4["observed_at"]) == {pd.Timestamp("2026-06-15")}
        # A period with no calendar entry still falls back to the lag.
        q3 = frame[frame["valid_time"] == pd.Timestamp("2025-09-30")]
        assert set(q3["observed_at"]) == {_Q3_DEFAULT_OBSERVED}

    def test_observed_at_never_precedes_valid_time(self, connector):
        frame = connector.parse(_payload(BIS_TC_CSV), FetchRequest())
        assert (frame["observed_at"] >= frame["valid_time"]).all()

    def test_zero_lag_is_allowed_and_still_not_before(self):
        connector = BisCreditConnector(
            publication_lag_days=0, client=_ExplodingClient()
        )
        frame = connector.parse(_payload(BIS_TC_CSV), FetchRequest())
        assert (frame["observed_at"] == frame["valid_time"]).all()

    def test_release_date_before_the_period_fails_closed(self):
        connector = BisCreditConnector(
            release_dates={"2025-Q4": "2025-12-30"}, client=_ExplodingClient()
        )
        with pytest.raises(SchemaValidationError, match="observed_at"):
            connector.parse(_payload(BIS_TC_CSV), FetchRequest())

    def test_negative_lag_is_rejected(self):
        with pytest.raises(ValueError, match="publication_lag_days"):
            BisCreditConnector(publication_lag_days=-1)

    def test_observed_at_is_not_wall_clock_time(self, connector):
        frame = connector.parse(_payload(BIS_TC_CSV), FetchRequest())
        # Every stamp is derived from the period, so none can be "now".
        assert frame["observed_at"].max() <= pd.Timestamp("2026-12-31")


class TestFailClosed:
    def test_missing_column_raises_schema_error(self, connector):
        rows = _rows()
        fields = [name for name in _fields(rows) if name != "TIME_PERIOD"]
        with pytest.raises(SchemaValidationError, match="missing required columns"):
            connector.parse(_dump(rows, fields), FetchRequest())

    def test_reordered_columns_raise_schema_error(self, connector):
        rows = _rows()
        fields = _fields(rows)
        i, j = fields.index("TC_BORROWERS"), fields.index("TC_LENDERS")
        fields[i], fields[j] = fields[j], fields[i]
        with pytest.raises(SchemaValidationError, match="unexpected order"):
            connector.parse(_dump(rows, fields), FetchRequest())

    def test_all_rows_out_of_slice_raises_empty(self, connector):
        rows = _rows()
        out_of_slice = [
            _pick(rows, BORROWERS_CTY="ZA", TIME_PERIOD="2025-Q4"),
            _pick(rows, BORROWERS_CTY="US", TC_BORROWERS="G", TIME_PERIOD="2025-Q4"),
        ]
        with pytest.raises(EmptyDatasetError):
            connector.parse(_dump(out_of_slice), FetchRequest())

    def test_window_excluding_everything_raises_empty(self, connector):
        with pytest.raises(EmptyDatasetError, match="no rows survived"):
            connector.parse(
                _payload(BIS_TC_CSV),
                FetchRequest(start="2020-01-01", end="2020-12-31"),
            )

    def test_header_without_rows_raises_empty(self, connector):
        header_only = _dump([], _fields(_rows()))
        with pytest.raises(EmptyDatasetError, match="no rows"):
            connector.parse(header_only, FetchRequest())

    def test_empty_payload_raises_schema_error(self, connector):
        with pytest.raises(SchemaValidationError):
            connector.parse(b"", FetchRequest())

    def test_malformed_period_raises_schema_error(self, connector):
        rows = _rows()
        row = dict(_pick(rows, BORROWERS_CTY="LU", TIME_PERIOD="2025-Q4"))
        row["TIME_PERIOD"] = "2025-Q5"  # synthetic
        with pytest.raises(SchemaValidationError, match="TIME_PERIOD"):
            connector.parse(_dump([row]), FetchRequest())

    def test_conflicting_duplicate_series_raises(self, connector):
        rows = _rows()
        original = _pick(rows, BORROWERS_CTY="LU", TIME_PERIOD="2025-Q4")
        clash = dict(original)
        clash["OBS_VALUE"] = "999.9"  # synthetic: same key, different value
        with pytest.raises(SchemaValidationError, match="conflicting values"):
            connector.parse(_dump([original, clash]), FetchRequest())

    def test_identical_duplicate_is_collapsed_and_counted(self, connector):
        rows = _rows()
        original = _pick(rows, BORROWERS_CTY="LU", TIME_PERIOD="2025-Q4")
        payload = _dump([original, dict(original)])
        frame = connector.parse(payload, FetchRequest())
        assert frame.shape[0] == 1
        assert connector.last_stats.duplicate_rows_collapsed == 1


class TestReleaseCalendar:
    def test_parses_the_real_calendar_excerpt(self):
        releases = parse_release_calendar(_payload(BIS_REL_CAL_CSV))
        assert releases["2025-Q4"] == pd.Timestamp("2026-06-15")
        assert releases["2023-Q1"] == pd.Timestamp("2023-09-18")
        assert releases["2026-Q2"] == pd.Timestamp("2026-12-07")
        # RPP rows are a different category and must not leak in.
        assert "2024-03" not in releases

    def test_calendar_mapping_drives_observed_at(self):
        releases = parse_release_calendar(_payload(BIS_REL_CAL_CSV))
        connector = BisCreditConnector(
            release_dates=releases, client=_ExplodingClient()
        )
        frame = connector.parse(_payload(BIS_TC_CSV), FetchRequest())
        q4 = frame[frame["valid_time"] == pd.Timestamp("2025-12-31")]
        assert set(q4["observed_at"]) == {pd.Timestamp("2026-06-15")}

    def test_unknown_category_raises_empty(self):
        with pytest.raises(EmptyDatasetError):
            parse_release_calendar(_payload(BIS_REL_CAL_CSV), categories=("NOPE",))

    def test_calendar_endpoint_asks_for_csv(self):
        # Without the query the API answers XML, which this parser cannot read.
        assert BIS_RELEASE_CALENDAR_ENDPOINT.endswith("?format=csv")


class TestLoadIntoPitStore:
    def test_load_then_reload_is_idempotent(self):
        client = _StubClient(_payload(BIS_TC_CSV))
        connector = BisCreditConnector(client=client)
        store = PITStore()

        first = connector.load(store, FetchRequest())
        assert first.connector == "bis_credit"
        assert first.fetched == 8
        assert first.added == 8
        assert first.entities == ("4T", "IE", "LU", "NZ", "SE", "US")
        assert str(first.first_valid_time) == "2025-09-30 00:00:00"
        assert str(first.last_valid_time) == "2025-12-31 00:00:00"
        assert len(store) == 8

        second = connector.load(store, FetchRequest())
        assert second.fetched == 8
        assert second.added == 0
        assert len(store) == 8

        assert len(client.calls) == 2
        assert client.calls[0]["connector"] == "bis_credit"
        assert client.calls[0]["accept"] == "text/csv"

    def test_stored_frame_keeps_both_clocks(self):
        store = PITStore()
        BisCreditConnector(client=_StubClient(_payload(BIS_TC_CSV))).load(store)
        frame = store.to_frame()
        assert list(frame.columns) == list(OBSERVATION_COLUMNS)
        assert (frame["observed_at"] >= frame["valid_time"]).all()
        lu = frame[frame["entity_id"] == "LU"].sort_values("valid_time")
        assert list(lu["valid_time"]) == [
            pd.Timestamp("2025-09-30"),
            pd.Timestamp("2025-12-31"),
        ]

    def test_store_query_respects_the_publication_clock(self):
        store = PITStore()
        BisCreditConnector(client=_StubClient(_payload(BIS_TC_CSV))).load(store)
        series = "BIS:TC:borrowers=N:lenders=A:val=M:unit=770"
        # Before the first release, Q4 was not knowable.
        early = store.query("LU", series, as_of="2026-01-01")
        assert pd.Timestamp("2025-12-31") not in set(early["valid_time"])
        late = store.query("LU", series, as_of="2026-06-20")
        assert pd.Timestamp("2025-12-31") in set(late["valid_time"])


class TestRegistry:
    def test_registered_under_the_expected_name(self):
        assert "bis_credit" in CONNECTORS
        assert isinstance(build_connector("bis_credit"), BisCreditConnector)


def test_module_exports_the_verified_column_contract():
    assert BIS_TC_COLUMNS[0] == "FREQ"
    assert "OBS_VALUE" in BIS_TC_COLUMNS
    assert "TIME_PERIOD" in BIS_TC_COLUMNS
