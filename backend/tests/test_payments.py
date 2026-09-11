"""Offline tests for the Fedwire / TARGET2 payment-system connectors.

Every CSV fixture in this file is a verbatim ``curl`` capture, trimmed to a few
reference years. The headers, the two-source codes, and the corrected values
were all read from the live BIS and ECB APIs on 2026-09-11; nothing about the
source schema is guessed.

Three cells are built by the test module rather than copied, and each is
labelled where it is used:

* blanking ``OBS_VALUE`` (the BIS CPMI extract verified here is complete -- no
  blank values were observed in the 2014 or 2024 all-country files -- so the
  "blank is skipped, never zeroed" case is exercised by emptying one real cell);
* dropping the ECB vintage columns to exercise the documented fallback;
* a second vintage of one ECB period, stamped with another *real* ``VALID_FROM``
  from the same series, to exercise the revision numbering.

No test touches the network, and no test reads the wall clock.
"""

from __future__ import annotations

import csv
import io
from typing import Any, Dict, List, Sequence, Tuple

import pandas as pd
import pytest

from backend.exceptions import (
    DataSourceUnavailableError,
    EmptyDatasetError,
    SchemaValidationError,
)
from backend.modules.data.connectors import payments as payments_module
from backend.modules.data.connectors.base import (
    FetchRequest,
    validate_observation_frame,
)
from backend.modules.data.connectors.payments import (
    BIS_CPMI_ENDPOINT,
    BIS_RELEASE_CALENDAR_ENDPOINT,
    ECB_PSS_ENDPOINT,
    FEDWIRE_ENTITY_ID,
    TARGET2_ENTITY_ID,
    FedwireConnector,
    PaymentsConnector,
    Target2Connector,
    parse_bis_release_calendar,
)
from backend.modules.data.pit import OBSERVATION_COLUMNS, PITStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

#: BIS ``WS_CPMI_SYSTEMS`` for ``A.US..A.US2P.....`` -- real header, real rows.
BIS_FIXTURE_LINES: Tuple[str, ...] = (
    "FREQ,REP_CTY,MEASURE,SYSTEM_TYPE,SYSTEM,INSTRUMENT_TYPE,OTHER_PS_TRANS,TYPE_OF_INFO,TITLE,TABLE,COMMENT_TS,COLLECTION,AVAILABILITY,UNIT_MULT,UNIT_MEASURE,TIME_FORMAT,DECIMALS,OLD_TABLE,TIME_PERIOD,OBS_VALUE,COMMENT_OBS,OBS_STATUS,OBS_CONF,OBS_PRE_BREAK",
    'A,US,N,A,US2P,PA,ZZZZ,Z,"United States - Number of All Transactions in Fedwire Funds Service, Payment systems, large-value",8,Fedwire Funds Service is operated by the Federal Reserve.,S,A,6,373,,3,10,2023,193.3,,A,F,',
    'A,US,N,A,US2P,PB,ZZZZ,Z,"United States - Number of Credit transfers in Fedwire Funds Service, Payment systems, large-value",8,,S,A,6,373,,3,10,2023,193.3,,A,F,',
    'A,US,V,A,US2P,PA,ZZZZ,Z,"United States - Value of All Transactions in Fedwire Funds Service, Payment systems, large-value",9,Fedwire Funds Service is operated by the Federal Reserve.,S,A,6,USD,,3,11,2023,1087195950,,A,F,',
    'A,US,V,A,US2P,PB,ZZZZ,Z,"United States - Value of Credit transfers in Fedwire Funds Service, Payment systems, large-value",9,,S,A,6,USD,,3,11,2023,1087195950,,A,F,',
    'A,US,N,A,US2P,PA,ZZZZ,Z,"United States - Number of All Transactions in Fedwire Funds Service, Payment systems, large-value",8,Fedwire Funds Service is operated by the Federal Reserve.,S,A,6,373,,3,10,2024,209.9,,A,F,',
    'A,US,N,A,US2P,PB,ZZZZ,Z,"United States - Number of Credit transfers in Fedwire Funds Service, Payment systems, large-value",8,,S,A,6,373,,3,10,2024,209.9,,A,F,',
    'A,US,V,A,US2P,PA,ZZZZ,Z,"United States - Value of All Transactions in Fedwire Funds Service, Payment systems, large-value",9,Fedwire Funds Service is operated by the Federal Reserve.,S,A,6,USD,,3,11,2024,1133419684,,A,F,',
    'A,US,V,A,US2P,PB,ZZZZ,Z,"United States - Value of Credit transfers in Fedwire Funds Service, Payment systems, large-value",9,,S,A,6,USD,,3,11,2024,1133419684,,A,F,',
)
BIS_CSV = "\n".join(BIS_FIXTURE_LINES) + "\n"

#: Real row from the same extract, for the "wrong system" failure case.
BIS_FOREIGN_ROW = BIS_FIXTURE_LINES[1].replace(",US2P,", ",US1P,")

#: A real US2P row whose ``REP_CTY`` was changed to a reporting country that
#: does publish Fedwire-like rows (FR), so the identity check is what fires.
BIS_WRONG_COUNTRY_ROW = BIS_FIXTURE_LINES[1].replace(",US,", ",FR,", 1)

#: BIS ``BIS_REL_CAL`` -- real header and the real CPMI rows, plus one real
#: non-CPMI monthly row that must be ignored.
BIS_CALENDAR_CSV = "\n".join(
    (
        "FREQ,CATEGORY,RELEASE_TYPE,TIME_PERIOD,OBS_VALUE,OBS_STATUS,OBS_PRE_BREAK,OBS_CONF,COMMENTARY",
        "A,CPMI_FMI,S,2022,20240213,A,,F,",
        "A,CPMI_FMI,S,2023,20250325,A,,F,",
        "A,CPMI_FMI,S,2024,20260427,A,,F,",
        "A,CPMI_CT,S,2022,20240213,A,,F,",
        "A,CPMI_CT,S,2023,20250325,A,,F,",
        "A,CPMI_CT,S,2024,20260427,A,,F,",
        "M,RPP,DPP,2024-03,20240530,A,,F,",
    )
) + "\n"

#: ECB ``PSS`` for ``A.U2.F000.I39.P101..X0.00..`` with ``includeHistory=true``
#: -- real 38-column header, real rows, and the real ``ACTION=Delete`` tombstone
#: whose blank ``OBS_VALUE`` is the source's only "nothing here" marker.
ECB_FIXTURE_LINES: Tuple[str, ...] = (
    "KEY,FREQ,REF_AREA,PSS_INFO_TYPE,PSS_INSTRUMENT,PSS_SYSTEM,DATA_TYPE_PSS,COUNT_AREA,COUNT_SECTOR,CURRENCY_TRANS,SERIES_DENOM,TIME_PERIOD,OBS_VALUE,OBS_STATUS,OBS_CONF,OBS_PRE_BREAK,OBS_COM,TIME_FORMAT,BREAKS,COLLECTION,COMPILING_ORG,DISS_ORG,DOM_SER_IDS,PUBL_ECB,PUBL_MU,PUBL_PUBLIC,COMPILATION,DECIMALS,METHOD_REF,NAT_TITLE,SOURCE_AGENCY,TITLE,TITLE_COMPL,UNIT,UNIT_MULT,ACTION,VALID_FROM,VALID_TO",
    'PSS.A.U2.F000.I39.P101.NT.X0.00.Z0Z.Z,A,U2,F000,I39,P101,NT,X0,00,Z0Z,Z,2013,89.793018,A,F,,,P1Y,,S,,,,,,,,3,NA,,,Number of credit transfers and direct debits in TARGET component - Euro area (changing composition),"Euro area (changing composition) - All transactions - Payment services (sent), direct debits and credit transfers - Payments processing system - large value - TARGET2/TARGET component - Number - Unspecified sector counterpart",PURE_NUMB,6,Replace,2016-09-26T10:00:02.000+02:00,',
    'PSS.A.U2.F000.I39.P101.NT.X0.00.Z0Z.Z,A,U2,F000,I39,P101,NT,X0,00,Z0Z,Z,2014,86.03922399999999,A,F,,,P1Y,,S,,,,,,,,3,NA,,,Number of credit transfers and direct debits in TARGET component - Euro area (changing composition),"Euro area (changing composition) - All transactions - Payment services (sent), direct debits and credit transfers - Payments processing system - large value - TARGET2/TARGET component - Number - Unspecified sector counterpart",PURE_NUMB,6,Replace,2019-07-26T10:00:02.000+02:00,',
    'PSS.A.U2.F000.I39.P101.NT.X0.00.Z0Z.Z,A,U2,F000,I39,P101,NT,X0,00,Z0Z,Z,2015,86.95612000000001,A,F,,,P1Y,,S,,,,,,,,3,NA,,,Number of credit transfers and direct debits in TARGET component - Euro area (changing composition),"Euro area (changing composition) - All transactions - Payment services (sent), direct debits and credit transfers - Payments processing system - large value - TARGET2/TARGET component - Number - Unspecified sector counterpart",PURE_NUMB,6,Replace,2016-09-26T10:00:02.000+02:00,',
    'PSS.A.U2.F000.I39.P101.VT.X0.00.EUR.E,A,U2,F000,I39,P101,VT,X0,00,EUR,E,2013,547977009.848,A,F,,,P1Y,,S,,,,,,,,3,NA,,,Value of credit transfers and direct debits in TARGET component - Euro area (changing composition),"Euro area (changing composition) - All transactions - Payment services (sent), direct debits and credit transfers - Payments processing system - large value - TARGET2/TARGET component - Value - Unspecified sector counterpart - Euro - denominated in Euro",EUR,6,Replace,2016-09-26T10:00:02.000+02:00,',
    'PSS.A.U2.F000.I39.P101.VT.X0.00.EUR.E,A,U2,F000,I39,P101,VT,X0,00,EUR,E,2014,484933987.82299995,A,F,,,P1Y,,S,,,,,,,,3,NA,,,Value of credit transfers and direct debits in TARGET component - Euro area (changing composition),"Euro area (changing composition) - All transactions - Payment services (sent), direct debits and credit transfers - Payments processing system - large value - TARGET2/TARGET component - Value - Unspecified sector counterpart - Euro - denominated in Euro",EUR,6,Replace,2019-07-26T10:00:02.000+02:00,',
    'PSS.A.U2.F000.I39.P101.VT.X0.00.EUR.E,A,U2,F000,I39,P101,VT,X0,00,EUR,E,2015,495027099.918,A,F,,,P1Y,,S,,,,,,,,3,NA,,,Value of credit transfers and direct debits in TARGET component - Euro area (changing composition),"Euro area (changing composition) - All transactions - Payment services (sent), direct debits and credit transfers - Payments processing system - large value - TARGET2/TARGET component - Value - Unspecified sector counterpart - Euro - denominated in Euro",EUR,6,Replace,2016-09-26T10:00:02.000+02:00,',
    'PSS.A.U2.F000.I39.P101.NT.X0.00.Z0Z.Z,A,U2,F000,I39,P101,NT,X0,00,Z0Z,Z,2013,,,,,,,,,,,,,,,,,,,,,,,,Delete,,2015-10-16T03:20:32.000+02:00',
)
ECB_CSV = "\n".join(ECB_FIXTURE_LINES) + "\n"

FEDWIRE_SERIES = {
    "number_all": "BIS:CPMI:system=US2P:cty=US:measure=N:instrument=PA:unit=PURE_NUMB",
    "value_credit": "BIS:CPMI:system=US2P:cty=US:measure=V:instrument=PB:unit=USD",
}
TARGET2_SERIES = {
    "number": "ECB:PSS:system=P101:area=U2:info=F000:instr=I39:measure=NT:unit=PURE_NUMB",
    "value": "ECB:PSS:system=P101:area=U2:info=F000:instr=I39:measure=VT:unit=EUR",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class FakeClient:
    """An :class:`HttpClient` stand-in keyed on a URL substring.

    Responses are tried in insertion order; a value that is an exception
    instance is raised instead of returned, which is how the failure paths are
    exercised without touching the network.
    """

    def __init__(self, responses: Dict[str, Any]) -> None:
        self.responses = responses
        self.calls: List[str] = []

    def get(
        self,
        url: str,
        *,
        params: Any = None,
        accept: Any = None,
        connector: str = "connector",
    ) -> bytes:
        self.calls.append(url)
        for marker, response in self.responses.items():
            if marker in url:
                if isinstance(response, BaseException):
                    raise response
                if isinstance(response, str):
                    return response.encode("utf-8")
                return response
        raise DataSourceUnavailableError(f"no fake response for {url}")


def happy_client() -> FakeClient:
    """A client that serves both sources and the BIS release calendar."""
    return FakeClient(
        {
            "WS_CPMI_SYSTEMS": BIS_CSV,
            "BIS_REL_CAL": BIS_CALENDAR_CSV,
            "data/PSS/": ECB_CSV,
        }
    )


def _rows(text: str) -> Tuple[List[str], List[List[str]]]:
    reader = csv.reader(io.StringIO(text))
    records = list(reader)
    return records[0], records[1:]


def _rewrite(text: str, header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(list(header))
    for row in rows:
        writer.writerow(list(row))
    return buffer.getvalue()


def _drop_columns(text: str, names: Sequence[str]) -> str:
    header, records = _rows(text)
    keep = [i for i, column in enumerate(header) if column not in names]
    return _rewrite(text, [header[i] for i in keep], [[r[i] for i in keep] for r in records])


def _set_value(text: str, column: str, value: str, only_row: int | None = None) -> str:
    header, records = _rows(text)
    index = header.index(column)
    for position, row in enumerate(records):
        if only_row is None or position == only_row:
            row[index] = value
    return _rewrite(text, header, records)


def _duplicate_row_with_new_vintage(text: str, row_index: int, new_vintage: str) -> str:
    header, records = _rows(text)
    required = [c for c in ("ACTION", "VALID_FROM", "VALID_TO") if c in header]
    if not required:
        return text
    index = header.index("VALID_FROM")
    clone = list(records[row_index])
    clone[index] = new_vintage
    records = list(records) + [clone]
    return _rewrite(text, header, records)


def _blank_first_data_value(text: str, column: str, row_index: int) -> str:
    return _set_value(text, column, "", only_row=row_index)


def _parse_fedwire(payload: str, request: FetchRequest | None = None):
    connector = FedwireConnector()
    return connector, connector.parse(payload, request or FetchRequest())


def _parse_target2(payload: str, request: FetchRequest | None = None):
    connector = Target2Connector()
    return connector, connector.parse(payload, request or FetchRequest())


# ---------------------------------------------------------------------------
# Fedwire / BIS CPMI
# ---------------------------------------------------------------------------


class TestFedwireParse:
    def test_spec_names_a_real_endpoint_licence_and_cadence(self):
        spec = FedwireConnector().spec
        assert spec.endpoint == BIS_CPMI_ENDPOINT
        assert spec.kind == "bis"
        assert spec.entity_id == FEDWIRE_ENTITY_ID
        assert spec.cadence == "annual"
        assert spec.requires_credentials is False
        assert "bis.org" in spec.source_url
        # The terms of permitted use were read from the BIS Data Portal mirror.
        assert "cited" in spec.licence and "bis.org" in spec.licence

    def test_build_url_pins_country_and_system(self):
        url = FedwireConnector().build_url(FetchRequest())
        assert url.startswith(BIS_CPMI_ENDPOINT + "/")
        # Verified key: FREQ.REP_CTY.MEASURE.SYSTEM_TYPE.SYSTEM.
        assert "WS_CPMI_SYSTEMS/A.US..A.US2P.....?" in url
        assert "format=csv" in url
        # No bound requested, so no server-side period filter is invented.
        assert "startPeriod" not in url and "endPeriod" not in url

    def test_build_url_widens_bounds_to_years(self):
        request = FetchRequest(start="2014-06-01", end="2024-05-31")
        url = FedwireConnector().build_url(request)
        assert "startPeriod=2014" in url
        assert "endPeriod=2024" in url

    def test_parse_produces_the_observation_schema(self):
        _, frame = _parse_fedwire(BIS_CSV)
        assert list(frame.columns) == list(OBSERVATION_COLUMNS)
        assert len(frame) == 8
        assert set(frame["entity_id"]) == {FEDWIRE_ENTITY_ID}
        validate_observation_frame(frame, connector="bis_fedwire")

    def test_year_is_stamped_as_the_end_of_the_year(self):
        _, frame = _parse_fedwire(BIS_CSV)
        years = sorted(frame["valid_time"].unique())
        assert [str(y) for y in years] == ["2023-12-31 00:00:00", "2024-12-31 00:00:00"]
        row = frame[frame["series_id"] == FEDWIRE_SERIES["number_all"]].iloc[-1]
        assert row["valid_time"] == pd.Timestamp("2024-12-31")

    def test_values_are_scaled_out_of_millions(self):
        _, frame = _parse_fedwire(BIS_CSV)
        latest = frame[frame["valid_time"] == pd.Timestamp("2024-12-31")]
        number = latest[latest["series_id"] == FEDWIRE_SERIES["number_all"]]
        value = latest[latest["series_id"] == FEDWIRE_SERIES["value_credit"]]
        # 209.9 million transactions, UNIT_MULT = 6 (millions).
        assert float(number["value"].iloc[0]) == pytest.approx(209_900_000.0)
        # 1_133_419_684 million USD.
        assert float(value["value"].iloc[0]) == pytest.approx(1.133419684e15)

    def test_series_ids_are_stable_and_self_describing(self):
        _, frame = _parse_fedwire(BIS_CSV)
        assert set(frame["series_id"]) == {
            "BIS:CPMI:system=US2P:cty=US:measure=N:instrument=PA:unit=PURE_NUMB",
            "BIS:CPMI:system=US2P:cty=US:measure=N:instrument=PB:unit=PURE_NUMB",
            "BIS:CPMI:system=US2P:cty=US:measure=V:instrument=PA:unit=USD",
            FEDWIRE_SERIES["value_credit"],
        }
        for series_id in frame["series_id"]:
            assert series_id.startswith("BIS:CPMI:system=US2P:cty=US:")
            assert ":instrument=" in series_id and ":unit=" in series_id

    def test_parse_skips_and_counts_a_blank_value(self):
        # One real row with its OBS_VALUE cell emptied; see the module docstring.
        blanked = _blank_first_data_value(BIS_CSV, "OBS_VALUE", 0)
        connector, frame = _parse_fedwire(blanked)
        assert len(frame) == 7
        assert connector.last_skipped == {"empty_value": 1}
        assert connector.last_kept == 7
        assert connector.skipped_total == 1
        # The blanked row is the 2023 number, so it is absent, not zero.
        numbers_2023 = frame[
            (frame["series_id"] == FEDWIRE_SERIES["number_all"])
            & (frame["valid_time"] == pd.Timestamp("2023-12-31"))
        ]
        assert numbers_2023.empty

    def test_all_values_blank_raises_empty_dataset(self):
        blanked = _set_value(BIS_CSV, "OBS_VALUE", "")
        connector = FedwireConnector()
        with pytest.raises(EmptyDatasetError) as excinfo:
            connector.parse(blanked, FetchRequest())
        assert excinfo.value.code == "EMPTY_DATASET"
        assert connector.last_skipped["empty_value"] == 8

    def test_a_zero_byte_body_raises_empty_dataset(self):
        with pytest.raises(EmptyDatasetError):
            FedwireConnector().parse(b"", FetchRequest())

    @pytest.mark.parametrize("column", ["OBS_VALUE", "TIME_PERIOD", "SYSTEM", "UNIT_MULT"])
    def test_missing_column_raises_schema_error(self, column: str):
        with pytest.raises(SchemaValidationError) as excinfo:
            FedwireConnector().parse(_drop_columns(BIS_CSV, [column]), FetchRequest())
        assert excinfo.value.code == "SCHEMA_INVALID"
        assert column in excinfo.value.context["missing"]

    def test_a_non_annual_period_is_refused(self):
        broken = _set_value(BIS_CSV, "TIME_PERIOD", "2024-Q4")
        with pytest.raises(SchemaValidationError):
            FedwireConnector().parse(broken, FetchRequest())

    def test_a_foreign_system_is_refused(self):
        broken = BIS_CSV + BIS_FOREIGN_ROW + "\n"
        with pytest.raises(SchemaValidationError) as excinfo:
            FedwireConnector().parse(broken, FetchRequest())
        assert "US2P" in str(excinfo.value)

    def test_a_foreign_reporting_country_is_refused(self):
        broken = BIS_CSV + BIS_WRONG_COUNTRY_ROW + "\n"
        with pytest.raises(SchemaValidationError):
            FedwireConnector().parse(broken, FetchRequest())

    def test_conflicting_duplicate_observations_are_refused(self):
        # Same identity (series, period, observed_at), two different values.
        header, records = _rows(BIS_CSV)
        clone = list(records[0])
        clone[header.index("OBS_VALUE")] = "999.9"
        broken = _rewrite(BIS_CSV, header, list(records) + [clone])
        with pytest.raises(SchemaValidationError) as excinfo:
            FedwireConnector().parse(broken, FetchRequest())
        assert "conflicting" in str(excinfo.value)

    def test_request_window_filters_rows(self):
        request = FetchRequest(start="2024-01-01", end="2024-12-31")
        connector, frame = _parse_fedwire(BIS_CSV, request)
        assert len(frame) == 4
        assert set(frame["valid_time"]) == {pd.Timestamp("2024-12-31")}
        assert connector.last_skipped.get("out_of_window") == 4

    def test_window_with_no_overlap_raises_empty_dataset(self):
        request = FetchRequest(start="1990-01-01", end="1990-12-31")
        with pytest.raises(EmptyDatasetError):
            FedwireConnector().parse(BIS_CSV, request)

    def test_observed_at_never_precedes_valid_time(self):
        _, frame = _parse_fedwire(BIS_CSV)
        assert (frame["observed_at"] >= frame["valid_time"]).all()
        # Without a calendar the documented 1y6m lag is used, from the year end.
        assert set(frame["observed_at"]) == {
            pd.Timestamp("2025-06-30"),
            pd.Timestamp("2026-06-30"),
        }

    def test_revision_is_zero_because_the_source_keeps_one_vintage(self):
        _, frame = _parse_fedwire(BIS_CSV)
        assert set(frame["revision"]) == {0}

    def test_entity_scope_outside_this_source_raises_empty_dataset(self):
        request = FetchRequest(entity_ids=(TARGET2_ENTITY_ID,))
        connector = FedwireConnector()
        with pytest.raises(EmptyDatasetError):
            connector.parse(BIS_CSV, request)
        assert connector.last_skipped["out_of_scope_entity"] == 8

    def test_series_scope_keeps_only_the_named_series(self):
        request = FetchRequest(series_ids=(FEDWIRE_SERIES["value_credit"],))
        _, frame = _parse_fedwire(BIS_CSV, request)
        assert len(frame) == 2
        assert set(frame["series_id"]) == {FEDWIRE_SERIES["value_credit"]}


class TestFedwireFetch:
    def test_fetch_takes_observed_at_from_the_bis_release_calendar(self):
        client = happy_client()
        frame = FedwireConnector(client).fetch(FetchRequest())
        observed = {
            str(valid_time): str(observed_at)
            for valid_time, observed_at in zip(
                frame["valid_time"], frame["observed_at"]
            )
        }
        # Verified release dates: 2023 -> 2025-03-25, 2024 -> 2026-04-27.
        assert observed["2023-12-31 00:00:00"] == "2025-03-25 00:00:00"
        assert observed["2024-12-31 00:00:00"] == "2026-04-27 00:00:00"
        assert any("BIS_REL_CAL" in url for url in client.calls)
        validate_observation_frame(frame, connector="bis_fedwire")

    def test_years_absent_from_the_calendar_fall_back_to_the_documented_lag(self):
        # Drop both real 2024 CPMI calendar rows, leaving 2024 to the fallback.
        calendar = BIS_CALENDAR_CSV.replace(
            "A,CPMI_FMI,S,2024,20260427,A,,F,", ""
        ).replace("A,CPMI_CT,S,2024,20260427,A,,F,", "")
        client = FakeClient(
            {
                "WS_CPMI_SYSTEMS": BIS_CSV,
                "BIS_REL_CAL": calendar,
                "data/PSS/": ECB_CSV,
            }
        )
        connector = FedwireConnector(client)
        frame = connector.fetch(FetchRequest())
        assert 2024 not in connector.release_dates
        observed_2024 = frame.loc[
            frame["valid_time"] == pd.Timestamp("2024-12-31"), "observed_at"
        ].unique()
        assert [str(stamp) for stamp in observed_2024] == ["2026-06-30 00:00:00"]

    def test_an_unreachable_calendar_degrades_and_is_reported(self):
        client = FakeClient(
            {
                "WS_CPMI_SYSTEMS": BIS_CSV,
                "BIS_REL_CAL": DataSourceUnavailableError("calendar is down"),
                "data/PSS/": ECB_CSV,
            }
        )
        connector = FedwireConnector(client)
        frame = connector.fetch(FetchRequest())
        # The data still arrives; only the vintage stamps fall back.
        assert connector.release_dates == {}
        assert len(frame) == 8
        assert (frame["observed_at"] >= frame["valid_time"]).all()

    def test_an_unreachable_data_source_still_raises(self):
        client = FakeClient(
            {
                "WS_CPMI_SYSTEMS": DataSourceUnavailableError("bis is down"),
                "BIS_REL_CAL": BIS_CALENDAR_CSV,
            }
        )
        with pytest.raises(DataSourceUnavailableError) as excinfo:
            FedwireConnector(client).fetch(FetchRequest())
        assert excinfo.value.code == "DATA_SOURCE_UNAVAILABLE"

    def test_load_into_a_pit_store_is_idempotent(self):
        store = PITStore()
        connector = FedwireConnector(happy_client())
        first = connector.load(store, FetchRequest())
        second = connector.load(store, FetchRequest())

        assert first.fetched == 8 and first.added == 8
        assert second.fetched == 8 and second.added == 0
        assert len(store) == 8
        queried = store.query(FEDWIRE_ENTITY_ID, as_of="2026-12-31")
        assert len(queried) == 8

    def test_load_respects_the_as_of_discipline_of_the_store(self):
        store = PITStore()
        FedwireConnector(happy_client()).load(store, FetchRequest())
        # 2024's release date is 2026-04-27, so it is invisible a month earlier.
        early = store.query(FEDWIRE_ENTITY_ID, as_of="2026-03-01")
        assert pd.Timestamp("2024-12-31") not in set(early["valid_time"])


# ---------------------------------------------------------------------------
# TARGET2 / ECB PSS
# ---------------------------------------------------------------------------


class TestTarget2Parse:
    def test_spec_names_a_real_endpoint_licence_and_cadence(self):
        spec = Target2Connector().spec
        assert spec.endpoint == ECB_PSS_ENDPOINT
        assert spec.kind == "ecb"
        assert spec.entity_id == TARGET2_ENTITY_ID
        assert spec.cadence == "annual"
        assert spec.requires_credentials is False
        assert "ecb.europa.eu" in spec.source_url
        assert "cited" in spec.licence and "free of charge" in spec.licence

    def test_build_url_requests_the_vintage_columns(self):
        url = Target2Connector().build_url(FetchRequest())
        assert url.startswith(ECB_PSS_ENDPOINT + "/")
        # Verified key: FREQ.REF_AREA.PSS_INFO_TYPE.PSS_INSTRUMENT.PSS_SYSTEM
        #               .DATA_TYPE_PSS.COUNT_AREA.COUNT_SECTOR
        assert "/A.U2.F000.I39.P101..X0.00..?" in url
        assert "format=csvdata" in url
        assert "includeHistory=true" in url

    def test_build_url_widens_bounds_to_years(self):
        request = FetchRequest(start="2014-06-01", end="2024-05-31")
        url = Target2Connector().build_url(request)
        assert "startPeriod=2014" in url and "endPeriod=2024" in url

    def test_parse_produces_the_observation_schema(self):
        _, frame = _parse_target2(ECB_CSV)
        assert list(frame.columns) == list(OBSERVATION_COLUMNS)
        assert len(frame) == 6
        assert set(frame["entity_id"]) == {TARGET2_ENTITY_ID}
        validate_observation_frame(frame, connector="ecb_target2")

    def test_year_is_stamped_as_the_end_of_the_year(self):
        _, frame = _parse_target2(ECB_CSV)
        assert set(frame["valid_time"]) == {
            pd.Timestamp("2013-12-31"),
            pd.Timestamp("2014-12-31"),
            pd.Timestamp("2015-12-31"),
        }

    def test_values_are_scaled_out_of_millions(self):
        _, frame = _parse_target2(ECB_CSV)
        number = frame[frame["series_id"] == TARGET2_SERIES["number"]]
        first = number[number["valid_time"] == pd.Timestamp("2013-12-31")]
        assert float(first["value"].iloc[0]) == pytest.approx(89_793_018.0)

    def test_series_ids_are_prefixed_by_the_publisher(self):
        _, frame = _parse_target2(ECB_CSV)
        assert set(frame["series_id"]) == set(TARGET2_SERIES.values())
        for series_id in frame["series_id"]:
            assert series_id.startswith("ECB:PSS:system=P101:area=U2:")

    def test_observed_at_is_the_ecb_dissemination_timestamp(self):
        _, frame = _parse_target2(ECB_CSV)
        observed = set(frame["observed_at"])
        assert pd.Timestamp("2016-09-26 08:00:02") in observed
        assert pd.Timestamp("2019-07-26 08:00:02") in observed
        assert (frame["observed_at"] >= frame["valid_time"]).all()

    def test_without_valid_from_the_documented_lag_is_used(self):
        stripped = _drop_columns(ECB_CSV, ["ACTION", "VALID_FROM", "VALID_TO"])
        connector, frame = _parse_target2(stripped)
        assert set(frame["observed_at"]) == {
            pd.Timestamp("2015-12-31"),
            pd.Timestamp("2016-12-31"),
            pd.Timestamp("2017-12-31"),
        }
        assert connector.last_assumptions["assumed_publication_lag"] == 6
        # The 2013 tombstone is still blank, with or without the vintage columns.
        assert connector.last_skipped == {"empty_value": 1}

    def test_the_delete_tombstone_is_skipped_and_counted(self):
        connector, frame = _parse_target2(ECB_CSV)
        # Six values plus one blank tombstone for 2013.
        assert len(frame) == 6
        assert connector.last_skipped == {"empty_value": 1}
        assert connector.last_kept == 6

    def test_a_second_vintage_of_a_period_becomes_revision_one(self):
        # A duplicate of the 2013 number stamped with the 2019-07-26 VALID_FROM
        # that the same series really carries for its 2014 observation.
        doubled = _duplicate_row_with_new_vintage(
            ECB_CSV, 0, "2019-07-26T10:00:02.000+02:00"
        )
        _, frame = _parse_target2(doubled)
        number_2013 = frame[
            (frame["series_id"] == TARGET2_SERIES["number"])
            & (frame["valid_time"] == pd.Timestamp("2013-12-31"))
        ].sort_values("observed_at")
        assert len(number_2013) == 2
        assert list(number_2013["revision"]) == [0, 1]

    def test_all_values_blank_raises_empty_dataset(self):
        blanked = _set_value(ECB_CSV, "OBS_VALUE", "")
        connector = Target2Connector()
        with pytest.raises(EmptyDatasetError):
            connector.parse(blanked, FetchRequest())
        assert connector.last_skipped["empty_value"] == 7

    def test_a_zero_byte_body_raises_empty_dataset_not_a_schema_error(self):
        # Verified live: the ECB answers HTTP 200 with a zero-byte body for the
        # TARGET2 key in years past its 2021 last reference year.
        with pytest.raises(EmptyDatasetError) as excinfo:
            Target2Connector().parse(b"", FetchRequest())
        assert excinfo.value.code == "EMPTY_DATASET"

    @pytest.mark.parametrize("column", ["OBS_VALUE", "PSS_SYSTEM", "UNIT", "TIME_PERIOD"])
    def test_missing_column_raises_schema_error(self, column: str):
        with pytest.raises(SchemaValidationError) as excinfo:
            Target2Connector().parse(_drop_columns(ECB_CSV, [column]), FetchRequest())
        assert column in excinfo.value.context["missing"]

    def test_a_foreign_system_is_refused(self):
        broken = _set_value(ECB_CSV, "PSS_SYSTEM", "P203")
        with pytest.raises(SchemaValidationError) as excinfo:
            Target2Connector().parse(broken, FetchRequest())
        assert "P101" in str(excinfo.value)

    def test_conflicting_duplicate_observations_are_refused(self):
        header, records = _rows(ECB_CSV)
        clone = list(records[0])
        clone[header.index("OBS_VALUE")] = "1.0"
        broken = _rewrite(ECB_CSV, header, list(records) + [clone])
        with pytest.raises(SchemaValidationError):
            Target2Connector().parse(broken, FetchRequest())

    def test_request_window_filters_rows(self):
        request = FetchRequest(start="2014-01-01", end="2014-12-31")
        connector, frame = _parse_target2(ECB_CSV, request)
        assert len(frame) == 2
        assert set(frame["valid_time"]) == {pd.Timestamp("2014-12-31")}

    def test_load_into_a_pit_store_is_idempotent(self):
        store = PITStore()
        connector = Target2Connector(happy_client())
        first = connector.load(store, FetchRequest())
        second = connector.load(store, FetchRequest())

        assert first.fetched == 6 and first.added == 6
        assert second.added == 0
        assert len(store) == 6


# ---------------------------------------------------------------------------
# BIS release calendar
# ---------------------------------------------------------------------------


class TestReleaseCalendar:
    def test_reads_the_cpmi_release_dates(self):
        dates = parse_bis_release_calendar(BIS_CALENDAR_CSV)
        assert {year: str(stamp.date()) for year, stamp in sorted(dates.items())} == {
            2022: "2024-02-13",
            2023: "2025-03-25",
            2024: "2026-04-27",
        }

    def test_ignores_other_categories(self):
        # The monthly residential-property row in the fixture must not leak in.
        dates = parse_bis_release_calendar(BIS_CALENDAR_CSV)
        assert len(dates) == 3

    def test_missing_column_raises_schema_error(self):
        broken = _drop_columns(BIS_CALENDAR_CSV, ["CATEGORY"])
        with pytest.raises(SchemaValidationError):
            parse_bis_release_calendar(broken)

    def test_an_empty_calendar_is_empty_not_an_error(self):
        header, _ = _rows(BIS_CALENDAR_CSV)
        assert parse_bis_release_calendar(",".join(header) + "\n") == {}


# ---------------------------------------------------------------------------
# Facade
# ---------------------------------------------------------------------------


class TestPaymentsFacade:
    def test_spec_advertises_both_systems(self):
        spec = PaymentsConnector().spec
        assert spec.name == "payments"
        assert spec.cadence == "annual"
        assert FEDWIRE_ENTITY_ID in spec.entity_id
        assert TARGET2_ENTITY_ID in spec.entity_id
        assert BIS_CPMI_ENDPOINT in spec.endpoint
        assert ECB_PSS_ENDPOINT in spec.endpoint

    def test_build_url_names_both_endpoints(self):
        url = PaymentsConnector().build_url(FetchRequest())
        assert BIS_CPMI_ENDPOINT in url and ECB_PSS_ENDPOINT in url
        assert ";" in url

    def test_parse_combines_both_sources_without_key_collisions(self):
        connector = PaymentsConnector(happy_client())
        frame = connector.parse(
            {"fedwire": BIS_CSV, "target2": ECB_CSV}, FetchRequest()
        )
        assert len(frame) == 14
        assert set(frame["entity_id"]) == {FEDWIRE_ENTITY_ID, TARGET2_ENTITY_ID}

        fedwire_series = set(
            frame.loc[frame["entity_id"] == FEDWIRE_ENTITY_ID, "series_id"]
        )
        target2_series = set(
            frame.loc[frame["entity_id"] == TARGET2_ENTITY_ID, "series_id"]
        )
        assert fedwire_series & target2_series == set()
        assert fedwire_series | target2_series == set(frame["series_id"])
        # The prefixes alone are enough to tell the rails apart.
        assert all(s.startswith("BIS:CPMI:") for s in fedwire_series)
        assert all(s.startswith("ECB:PSS:") for s in target2_series)
        validate_observation_frame(frame, connector="payments")

    def test_parse_requires_both_bodies(self):
        connector = PaymentsConnector(happy_client())
        with pytest.raises(SchemaValidationError):
            connector.parse({"fedwire": BIS_CSV}, FetchRequest())

    def test_entity_scope_fetches_only_the_named_system(self):
        client = happy_client()
        frame = PaymentsConnector(client).fetch(
            FetchRequest(entity_ids=(FEDWIRE_ENTITY_ID,))
        )
        assert len(frame) == 8
        assert set(frame["entity_id"]) == {FEDWIRE_ENTITY_ID}
        assert not any("data/PSS/" in url for url in client.calls)

    def test_series_scope_skips_the_source_that_cannot_serve_it(self):
        connector = PaymentsConnector(happy_client())
        frame = connector.parse(
            {"fedwire": BIS_CSV, "target2": ECB_CSV},
            FetchRequest(series_ids=(TARGET2_SERIES["number"],)),
        )
        assert set(frame["entity_id"]) == {TARGET2_ENTITY_ID}
        assert set(frame["series_id"]) == {TARGET2_SERIES["number"]}
        # The Fedwire body was present but never parsed: it is out of scope.
        assert connector.fedwire.last_kept == 0

    def test_a_scope_matching_neither_source_raises_empty_dataset(self):
        connector = PaymentsConnector(happy_client())
        with pytest.raises(EmptyDatasetError):
            connector.parse(
                {"fedwire": BIS_CSV, "target2": ECB_CSV},
                FetchRequest(entity_ids=("SOME_OTHER_RAIL",)),
            )

    def test_fetch_returns_one_combined_frame(self):
        client = happy_client()
        frame = PaymentsConnector(client).fetch(FetchRequest())
        assert len(frame) == 14
        assert any("WS_CPMI_SYSTEMS" in url for url in client.calls)
        assert any("BIS_REL_CAL" in url for url in client.calls)
        assert any("data/PSS/" in url for url in client.calls)

    def test_a_failing_source_fails_the_whole_call(self):
        client = FakeClient(
            {
                "WS_CPMI_SYSTEMS": BIS_CSV,
                "BIS_REL_CAL": BIS_CALENDAR_CSV,
                "data/PSS/": DataSourceUnavailableError("ecb is down"),
            }
        )
        with pytest.raises(DataSourceUnavailableError) as excinfo:
            PaymentsConnector(client).fetch(FetchRequest())
        assert excinfo.value.code == "DATA_SOURCE_UNAVAILABLE"

    def test_the_first_failing_source_aborts_before_the_second_is_called(self):
        client = FakeClient(
            {
                "WS_CPMI_SYSTEMS": DataSourceUnavailableError("bis is down"),
                "BIS_REL_CAL": BIS_CALENDAR_CSV,
                "data/PSS/": ECB_CSV,
            }
        )
        with pytest.raises(DataSourceUnavailableError):
            PaymentsConnector(client).fetch(FetchRequest())
        assert not any("data/PSS/" in url for url in client.calls)

    def test_load_into_a_pit_store_is_idempotent(self):
        store = PITStore()
        connector = PaymentsConnector(happy_client())
        first = connector.load(store, FetchRequest())
        second = connector.load(store, FetchRequest())

        assert first.fetched == 14 and first.added == 14
        assert second.added == 0
        assert len(store) == 14
        assert set(first.entities) == {FEDWIRE_ENTITY_ID, TARGET2_ENTITY_ID}
        assert first.first_valid_time == pd.Timestamp("2013-12-31")
        assert first.last_valid_time == pd.Timestamp("2024-12-31")


# ---------------------------------------------------------------------------
# Module surface
# ---------------------------------------------------------------------------


def test_module_registers_its_public_names():
    exported = set(payments_module.__all__)
    assert {
        "FedwireConnector",
        "Target2Connector",
        "PaymentsConnector",
        "parse_bis_release_calendar",
    } <= exported
    for name in exported:
        assert hasattr(payments_module, name)


def test_the_registered_facade_resolves_through_the_package_registry():
    from backend.modules.data.connectors import build_connector

    connector = build_connector("payments")
    assert isinstance(connector, PaymentsConnector)
    assert isinstance(connector.fedwire, FedwireConnector)
    assert isinstance(connector.target2, Target2Connector)
    assert BIS_RELEASE_CALENDAR_ENDPOINT in connector.fedwire.build_release_calendar_url(
        FetchRequest()
    )
