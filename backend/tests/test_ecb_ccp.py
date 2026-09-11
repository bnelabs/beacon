"""Tests for the ECB Central Counterparty Clearing Statistics connector.

The fixture is a **verbatim** excerpt of a live ``GET
/service/data/CCP/all?format=csvdata`` response captured with
``curl -H "User-Agent: BNELabs-BEACON/1.0 (research; bne@bnelabs.dev)"`` on
2026-09-11. It keeps the real 28-column header and nine real rows, chosen to
exercise the cases that matter:

* ``AT1``/``D00``/2006, ``AT1``/``D01``/2006 and ``FR1``/``OUT``/``U``/``DE``/
  2006 carry the ``OBS_VALUE`` that is *empty* with ``OBS_STATUS=M`` ("data
  cannot exist"), so the skip-and-count path runs against real data;
* ``AT1``/``D03``/2006 and ``AT1``/``D0T``/2006 are plain participant counts;
* ``FR1``/``LNK``/``Z``/2006 appears twice, once as ``SERIES_DENOM=E``
  (``UNIT=EUR``, millions) and once as ``SERIES_DENOM=Q`` (``UNIT=PURE_NUMB``,
  thousands). They share CCP, info type and instrument, which is exactly why
  the series key has to carry the denomination: a key built from "CCP x info
  type x instrument x frequency" alone would collide here with two different
  values.
* ``AT1``/``D0T``/2025 repeats the 2006 key in a second reference year.

Everything is offline: the parsers are fed the recorded bytes, and ``load`` is
driven through an injected stub client.
"""

from __future__ import annotations

import csv
import io

import pandas as pd
import pytest

from backend.exceptions import DataSourceUnavailableError, EmptyDatasetError
from backend.exceptions import SchemaValidationError
from backend.modules.data.connectors.base import (
    FetchRequest,
    validate_observation_frame,
)
from backend.modules.data.connectors.ecb_ccp import (
    DEFAULT_PUBLICATION_LAG_DAYS,
    INFO_TYPE_LABELS,
    EcbCcpConnector,
)
from backend.modules.data.pit import OBSERVATION_COLUMNS, PITStore

CSV_HEADER = (
    "KEY,FREQ,CCP_SYSTEM,SSS_INFO_TYPE,SSS_INSTRUMENT,COUNT_AREA,SSS_SYSTEM,"
    "CURRENCY_TRANS,SERIES_DENOM,TIME_PERIOD,OBS_VALUE,OBS_STATUS,OBS_CONF,"
    "OBS_PRE_BREAK,OBS_COM,TIME_FORMAT,COLLECTION,COMPILING_ORG,DISS_ORG,"
    "PUBL_ECB,PUBL_MU,PUBL_PUBLIC,DECIMALS,SOURCE_AGENCY,TITLE,TITLE_COMPL,"
    "UNIT,UNIT_MULT"
)

CSV_ROWS = (
    # AT1 D00 2006 -- participant count that cannot exist, empty OBS_VALUE.
    'CCP.A.AT1.D00.Z.X0.ZZZ.Z0Z.Q,A,AT1,D00,Z,X0,ZZZ,Z0Z,Q,2006,,M,F,,,P1Y,E,'
    ',,,,,0,,"CCP Austria, Total participants - central bank, Not applicable",'
    'CCP Austria - Total participants - central bank - Not applicable - Not '
    'applicable - Not applicable - Not applicable - Quantity,PURE_NUMB,1',
    # AT1 D01 2006 -- likewise empty.
    'CCP.A.AT1.D01.Z.X0.ZZZ.Z0Z.Q,A,AT1,D01,Z,X0,ZZZ,Z0Z,Q,2006,,M,F,,,P1Y,E,'
    ',,,,,0,,"CCP Austria, Total participants - central counterparty (CCP), Not '
    'applicable",CCP Austria - Total participants - central counterparty (CCP) '
    '- Not applicable - Not applicable - Not applicable - Not applicable - '
    'Quantity,PURE_NUMB,1',
    # AT1 D03 2006 -- a real count: 51 credit-institution participants.
    'CCP.A.AT1.D03.Z.X0.ZZZ.Z0Z.Q,A,AT1,D03,Z,X0,ZZZ,Z0Z,Q,2006,51,A,F,,,P1Y,E,'
    ',,,,,0,,"CCP Austria, Total participants - credit institution, Not '
    'applicable",CCP Austria - Total participants - credit institution - Not '
    'applicable - Not applicable - Not applicable - Not applicable - '
    'Quantity,PURE_NUMB,1',
    # AT1 D0T 2006 -- the 66 participant total for the same CCP and year.
    'CCP.A.AT1.D0T.Z.X0.ZZZ.Z0Z.Q,A,AT1,D0T,Z,X0,ZZZ,Z0Z,Q,2006,66,A,F,,,P1Y,E,'
    ',,,,,0,,"CCP Austria, Total participants, Not applicable",CCP Austria - '
    'Total participants - Not applicable - Not applicable - Not applicable - '
    'Not applicable - Quantity,PURE_NUMB,1',
    # FR1 LNK Z 2006, denomination E (euro notional in millions).
    'CCP.A.FR1.LNK.Z.X0.ZZZ.Z0Z.E,A,FR1,LNK,Z,X0,ZZZ,Z0Z,E,2006,7125425,A,F,,,'
    'P1Y,S,,,,,,0,,"LCH. Clearnet S.A. (France), Transactions through a clearing '
    'link, Not applicable",LCH. Clearnet S.A. (France) - Transactions through a '
    'clearing link - Not applicable - Not applicable - Not applicable - Not '
    'applicable - Euro,EUR,6',
    # FR1 LNK Z 2006, denomination Q (trade count in thousands).
    'CCP.A.FR1.LNK.Z.X0.ZZZ.Z0Z.Q,A,FR1,LNK,Z,X0,ZZZ,Z0Z,Q,2006,393,A,F,,,P1Y,'
    'S,,,,,,0,,"LCH. Clearnet S.A. (France), Transactions through a clearing '
    'link, Not applicable",LCH. Clearnet S.A. (France) - Transactions through a '
    'clearing link - Not applicable - Not applicable - Not applicable - Not '
    'applicable - Quantity,PURE_NUMB,3',
    # FR1 OUT U DE 2006, denomination E -- empty OBS_VALUE with OBS_STATUS=M.
    'CCP.A.FR1.OUT.U.DE.ZZZ.EUR.Q,A,FR1,OUT,U,DE,ZZZ,EUR,Q,2006,,M,F,,,P1Y,S,'
    ',,,,,0,,"LCH. Clearnet S.A. (France), Outright, Debt securities, equities '
    'and other securities","LCH. Clearnet S.A. (France) - Outright - Debt '
    'securities, equities and other securities - Germany - Not applicable - '
    'Euro - Quantity",PURE_NUMB,3',
    # FR1 OUT U X0 2006, denomination E, all currencies combined.
    'CCP.A.FR1.OUT.U.X0.ZZZ.Z01.E,A,FR1,OUT,U,X0,ZZZ,Z01,E,2006,7481355,A,F,,,'
    'P1Y,S,,,,,,0,,"LCH. Clearnet S.A. (France), Outright, Debt securities, '
    'equities and other securities","LCH. Clearnet S.A. (France) - Outright - '
    'Debt securities, equities and other securities - Not applicable - Not '
    'applicable - All currencies combined - Euro",EUR,6',
    # AT1 D0T 2025 -- the same series key in a second reference year.
    'CCP.A.AT1.D0T.Z.X0.ZZZ.Z0Z.Q,A,AT1,D0T,Z,X0,ZZZ,Z0Z,Q,2025,35,A,F,,,P1Y,E,'
    ',,,,,0,,"CCP Austria, Total participants, Not applicable",CCP Austria - '
    'Total participants - Not applicable - Not applicable - Not applicable - '
    'Not applicable - Quantity,PURE_NUMB,1',
)

CSV_TEXT = "\n".join((CSV_HEADER,) + CSV_ROWS) + "\n"
CSV_BYTES = CSV_TEXT.encode("utf-8")

#: Number of fixture rows that carry a real (non-empty) OBS_VALUE.
EMITTED = 6
#: Number of fixture rows whose OBS_VALUE is empty.
SKIPPED = 3

D03_KEY = "CCP.A.AT1.D03.Z.X0.ZZZ.Z0Z.Q"
D0T_KEY = "CCP.A.AT1.D0T.Z.X0.ZZZ.Z0Z.Q"
LNK_E_KEY = "CCP.A.FR1.LNK.Z.X0.ZZZ.Z0Z.E"
LNK_Q_KEY = "CCP.A.FR1.LNK.Z.X0.ZZZ.Z0Z.Q"

D0T_2006_SERIES = (
    "ECB:CCP:ccp=AT1:info=D0T:instr=Z:area=X0:sss=ZZZ:cur=Z0Z:denom=Q:"
    "unit=PURE_NUMB:mult=1:freq=A"
)
LNK_E_SERIES = (
    "ECB:CCP:ccp=FR1:info=LNK:instr=Z:area=X0:sss=ZZZ:cur=Z0Z:denom=E:"
    "unit=EUR:mult=6:freq=A"
)
LNK_Q_SERIES = (
    "ECB:CCP:ccp=FR1:info=LNK:instr=Z:area=X0:sss=ZZZ:cur=Z0Z:denom=Q:"
    "unit=PURE_NUMB:mult=3:freq=A"
)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _rows(text: str) -> list:
    """Parse CSV text into a list of rows, respecting quoting."""
    return list(csv.reader(io.StringIO(text)))


def _text(rows: list) -> str:
    """Serialise rows back to CSV text with a trailing newline."""
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    return buffer.getvalue()


def _parse(text: str = CSV_TEXT, request=None, *, connector=None):
    """Parse ``text`` with a fresh connector; return ``(connector, frame)``."""
    resolved = connector or EcbCcpConnector()
    frame = resolved.parse(text.encode("utf-8"), request or FetchRequest())
    return resolved, frame


def _set_field(text: str, key: str, column: str, value: str) -> str:
    """Replace ``column`` of every data row whose KEY equals ``key``."""
    rows = _rows(text)
    index = rows[0].index(column)
    changed = 0
    for row in rows[1:]:
        if row[0] == key:
            row[index] = value
            changed += 1
    assert changed >= 1, f"fixture has no row with KEY={key!r}"
    return _text(rows)


def _append_copy(text: str, key: str, column=None, value=None) -> str:
    """Append a copy of the row whose KEY equals ``key``, optionally edited."""
    rows = _rows(text)
    index = None if column is None else rows[0].index(column)
    for row in rows[1:]:
        if row[0] == key:
            clone = list(row)
            if index is not None:
                clone[index] = value
            rows.append(clone)
            return _text(rows)
    raise AssertionError(f"fixture has no row with KEY={key!r}")


def _drop_column(text: str, column: str) -> str:
    """Remove ``column`` from the header and every row."""
    rows = _rows(text)
    index = rows[0].index(column)
    return _text(
        [[value for position, value in enumerate(row) if position != index]
         for row in rows]
    )


def _empty_only(text: str) -> str:
    """Keep the header plus only the rows whose OBS_VALUE is empty."""
    rows = _rows(text)
    index = rows[0].index("OBS_VALUE")
    return _text([rows[0]] + [row for row in rows[1:] if row[index] == ""])


class _StubClient:
    """HTTP-client stand-in that replays recorded bytes and records calls."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload
        self.calls = []

    def get(self, url, *, params=None, accept=None, connector="connector") -> bytes:
        self.calls.append({"url": url, "accept": accept, "connector": connector})
        return self.payload


class _FailingClient:
    """HTTP-client stand-in that always reports the source as unavailable."""

    def get(self, url, *, params=None, accept=None, connector="connector") -> bytes:
        raise DataSourceUnavailableError(
            f"{connector} could not reach the source", context={"url": url}
        )


# --------------------------------------------------------------------------- #
# Happy path
# --------------------------------------------------------------------------- #


class TestHappyPath:
    def test_parse_emits_one_row_per_non_empty_series(self):
        _, frame = _parse()

        assert len(frame) == EMITTED
        assert set(frame["entity_id"]) == {"AT1", "FR1"}
        assert list(frame.columns) == list(OBSERVATION_COLUMNS) + ["label"]

    def test_values_are_preserved_verbatim(self):
        _, frame = _parse()
        values = set(frame["value"].tolist())

        assert values == {51.0, 66.0, 7125425.0, 393.0, 7481355.0, 35.0}

    def test_frame_satisfies_the_observation_schema(self):
        _, frame = _parse()
        validated = validate_observation_frame(frame, connector="ecb_ccp")

        assert list(validated.columns) == list(OBSERVATION_COLUMNS)
        assert len(validated) == EMITTED
        # The base contract sorts by valid_time, then series, then entity.
        assert validated["valid_time"].is_monotonic_increasing

    def test_label_carries_title_but_never_enters_the_key(self):
        _, frame = _parse()
        row = frame.loc[frame["series_id"] == D0T_2006_SERIES].iloc[0]

        assert row["label"] == "CCP Austria, Total participants, Not applicable"
        assert "CCP Austria" not in row["series_id"]
        assert "Total participants" not in row["series_id"]

    def test_every_series_label_is_a_known_info_type_code(self):
        _, frame = _parse()
        codes = {
            sid.split("info=", 1)[1].split(":", 1)[0] for sid in frame["series_id"]
        }

        assert codes <= set(INFO_TYPE_LABELS)

    def test_title_stays_reachable_after_fetch_trims_the_label_column(self):
        connector = EcbCcpConnector(client=_StubClient(CSV_BYTES))

        frame = connector.fetch()

        assert "label" not in frame.columns
        assert list(frame.columns) == list(OBSERVATION_COLUMNS)
        assert connector.last_labels[D0T_2006_SERIES] == (
            "CCP Austria, Total participants, Not applicable"
        )


def test_info_type_labels_are_the_verified_ecb_codelist_names():
    # Transcribed from ECB CL_SSS_INFO_TYPE; a regression here would mean a
    # guessed code slipped in.
    assert INFO_TYPE_LABELS["D0T"] == "Total participants"
    assert INFO_TYPE_LABELS["D03"] == "Total participants - credit institution"
    assert INFO_TYPE_LABELS["LNK"] == "Transactions through a clearing link"
    assert INFO_TYPE_LABELS["OUT"] == "Outright"
    assert INFO_TYPE_LABELS["REP"] == "Repo"


# --------------------------------------------------------------------------- #
# Time conventions
# --------------------------------------------------------------------------- #


class TestTimeConventions:
    def test_annual_period_maps_to_the_end_of_the_year(self):
        _, frame = _parse()

        at_2006 = frame.loc[frame["series_id"] == D0T_2006_SERIES].iloc[0]
        at_2025 = frame.loc[frame["series_id"].str.contains("freq=A") & (
            frame["valid_time"] == pd.Timestamp("2025-12-31")
        )].iloc[0]

        assert at_2006["valid_time"] == pd.Timestamp("2006-12-31")
        assert at_2025["valid_time"] == pd.Timestamp("2025-12-31")

    def test_observed_at_is_valid_time_plus_the_documented_lag(self):
        _, frame = _parse()

        expected = frame["valid_time"] + pd.Timedelta(
            DEFAULT_PUBLICATION_LAG_DAYS, unit="D"
        )
        assert frame["observed_at"].tolist() == expected.tolist()
        assert (frame["observed_at"] >= frame["valid_time"]).all()

    def test_observed_at_is_never_current_time(self):
        with_lag, frame = _parse()

        assert with_lag.publication_lag_days == 212
        # 2006-12-31 + 212 days is 2007-07-31, not the wall clock.
        assert frame["observed_at"].max() == pd.Timestamp("2026-07-31")

    def test_publication_lag_is_overridable(self):
        connector = EcbCcpConnector(publication_lag_days=30)
        _, frame = _parse(connector=connector)

        expected = frame["valid_time"] + pd.Timedelta(30, unit="D")
        assert frame["observed_at"].tolist() == expected.tolist()

    def test_zero_lag_is_allowed_and_keeps_observed_at_equal(self):
        connector = EcbCcpConnector(publication_lag_days=0)
        _, frame = _parse(connector=connector)

        assert (frame["observed_at"] == frame["valid_time"]).all()

    def test_negative_or_non_integer_lag_is_rejected(self):
        for bad in (-1, 1.5, True, "212"):
            with pytest.raises(ValueError, match="publication_lag_days"):
                EcbCcpConnector(publication_lag_days=bad)


# --------------------------------------------------------------------------- #
# Series identity
# --------------------------------------------------------------------------- #


class TestSeriesIdentity:
    def test_series_id_is_built_from_coded_dimensions(self):
        _, frame = _parse()

        assert D0T_2006_SERIES in set(frame["series_id"])

    def test_denomination_distinguishes_quantity_from_euro_notional(self):
        _, frame = _parse()
        series = set(frame["series_id"])

        assert LNK_E_SERIES in series
        assert LNK_Q_SERIES in series
        values = dict(zip(frame["series_id"], frame["value"]))
        assert values[LNK_E_SERIES] == 7125425.0
        assert values[LNK_Q_SERIES] == 393.0

    def test_series_id_does_not_collide_on_ccp_info_instrument_alone(self):
        # The naive key the brief suggested would map both LNK rows to one
        # series. The connector must keep them apart.
        _, frame = _parse()
        naive_prefix = "ECB:CCP:ccp=FR1:info=LNK:instr=Z:area=X0:sss=ZZZ:cur=Z0Z"
        matching = [sid for sid in frame["series_id"] if sid.startswith(naive_prefix)]
        assert len(matching) == 2
        assert len(set(matching)) == 2

    def test_every_series_key_and_period_is_unique(self):
        _, frame = _parse()
        keys = list(zip(frame["series_id"], frame["valid_time"]))

        assert len(keys) == len(set(keys))

    def test_revision_is_zero_because_the_feed_exposes_no_vintages(self):
        _, frame = _parse()

        assert set(frame["revision"]) == {0}


# --------------------------------------------------------------------------- #
# Empty OBS_VALUE handling
# --------------------------------------------------------------------------- #


class TestEmptyValues:
    def test_empty_rows_are_skipped_and_counted_not_zeroed(self):
        connector, frame = _parse()

        assert connector.last_skipped_empty == SKIPPED
        # The empty AT1/D00 series must be absent, not present with value 0.
        assert not any("info=D00" in sid for sid in frame["series_id"])
        assert 0.0 not in set(frame["value"])

    def test_skip_counts_are_labelled_by_obs_status(self):
        connector, _ = _parse()

        # All three empty fixture rows carry OBS_STATUS=M ("data cannot exist").
        assert connector.last_skipped_status_counts == {"M": 3}

    def test_skip_counters_are_reset_between_parses(self):
        connector = EcbCcpConnector()
        connector.parse(CSV_BYTES, FetchRequest())
        assert connector.last_skipped_empty == SKIPPED

        connector.parse(CSV_BYTES, FetchRequest())
        assert connector.last_skipped_empty == SKIPPED
        assert connector.last_skipped_status_counts == {"M": 3}

    def test_all_rows_empty_raises_empty_dataset(self):
        text = _empty_only(CSV_TEXT)
        connector = EcbCcpConnector()

        with pytest.raises(EmptyDatasetError, match="empty OBS_VALUE"):
            connector.parse(text.encode("utf-8"), FetchRequest())
        assert connector.last_skipped_empty == SKIPPED

    def test_header_without_rows_raises_empty_dataset(self):
        with pytest.raises(EmptyDatasetError):
            EcbCcpConnector().parse((CSV_HEADER + "\n").encode("utf-8"), FetchRequest())

    def test_empty_body_raises_empty_dataset(self):
        with pytest.raises(EmptyDatasetError):
            EcbCcpConnector().parse(b"", FetchRequest())


# --------------------------------------------------------------------------- #
# Failing closed
# --------------------------------------------------------------------------- #


class TestFailClosed:
    def test_missing_required_column_raises_schema_error(self):
        text = _drop_column(CSV_TEXT, "OBS_VALUE")

        with pytest.raises(SchemaValidationError, match="missing required"):
            EcbCcpConnector().parse(text.encode("utf-8"), FetchRequest())

    def test_missing_dimension_column_is_named_in_the_error(self):
        text = _drop_column(CSV_TEXT, "SSS_INSTRUMENT")

        with pytest.raises(SchemaValidationError) as excinfo:
            EcbCcpConnector().parse(text.encode("utf-8"), FetchRequest())
        assert "SSS_INSTRUMENT" in excinfo.value.context["missing"]

    def test_non_annual_frequency_raises_schema_error(self):
        text = _set_field(CSV_TEXT, D03_KEY, "FREQ", "Q")

        with pytest.raises(SchemaValidationError, match="annual frequency"):
            EcbCcpConnector().parse(text.encode("utf-8"), FetchRequest())

    def test_non_year_time_period_raises_schema_error(self):
        text = _set_field(CSV_TEXT, D03_KEY, "TIME_PERIOD", "2006-Q1")

        with pytest.raises(SchemaValidationError, match="TIME_PERIOD"):
            EcbCcpConnector().parse(text.encode("utf-8"), FetchRequest())

    def test_placeholder_value_raises_schema_error(self):
        text = _set_field(CSV_TEXT, D03_KEY, "OBS_VALUE", "..")

        with pytest.raises(SchemaValidationError, match="placeholder"):
            EcbCcpConnector().parse(text.encode("utf-8"), FetchRequest())

    def test_conflicting_duplicate_series_raises_schema_error(self):
        text = _append_copy(CSV_TEXT, D03_KEY, "OBS_VALUE", "999")

        with pytest.raises(SchemaValidationError, match="two different values"):
            EcbCcpConnector().parse(text.encode("utf-8"), FetchRequest())

    def test_identical_duplicate_series_is_deduplicated(self):
        text = _append_copy(CSV_TEXT, D03_KEY)
        _, frame = _parse(text)

        assert len(frame) == EMITTED
        assert len(list(zip(frame["series_id"], frame["valid_time"]))) == EMITTED

    def test_unusable_dimension_code_raises_schema_error(self):
        text = _set_field(CSV_TEXT, D03_KEY, "CCP_SYSTEM", "AT:1")

        with pytest.raises(SchemaValidationError, match="self-describing"):
            EcbCcpConnector().parse(text.encode("utf-8"), FetchRequest())

    def test_non_bytes_payload_raises_schema_error(self):
        with pytest.raises(SchemaValidationError, match="must be bytes"):
            EcbCcpConnector().parse(12345, FetchRequest())

    def test_undecodable_payload_raises_schema_error(self):
        with pytest.raises(SchemaValidationError, match="UTF-8"):
            EcbCcpConnector().parse(b"\xff\xfe\x00bad", FetchRequest())


# --------------------------------------------------------------------------- #
# Request scoping and URL building
# --------------------------------------------------------------------------- #


class TestRequestScoping:
    def test_build_url_carries_format_and_period_bounds(self):
        url = EcbCcpConnector().build_url(
            FetchRequest(start="2019-01-01", end="2024-12-31")
        )

        assert url == (
            "https://data-api.ecb.europa.eu/service/data/CCP/all"
            "?format=csvdata&startPeriod=2019&endPeriod=2024"
        )

    def test_build_url_without_bounds_fetches_everything(self):
        url = EcbCcpConnector().build_url(FetchRequest())

        assert url == (
            "https://data-api.ecb.europa.eu/service/data/CCP/all?format=csvdata"
        )

    def test_build_url_uses_only_the_start_bound_when_given(self):
        url = EcbCcpConnector().build_url(FetchRequest(start="2020-06-01"))

        assert "startPeriod=2020" in url
        assert "endPeriod" not in url

    def test_accept_header_requests_csv(self):
        assert EcbCcpConnector().accept == "text/csv"

    def test_parse_honours_the_valid_time_window(self):
        _, frame = _parse(request=FetchRequest(start="2020-01-01"))

        assert len(frame) == 1
        assert frame["valid_time"].tolist() == [pd.Timestamp("2025-12-31")]

    def test_parse_honours_the_entity_filter(self):
        _, frame = _parse(request=FetchRequest(entity_ids=("FR1",)))

        assert set(frame["entity_id"]) == {"FR1"}

    def test_parse_honours_the_series_filter(self):
        _, frame = _parse(request=FetchRequest(series_ids=(LNK_Q_SERIES,)))

        assert frame["series_id"].tolist() == [LNK_Q_SERIES]


# --------------------------------------------------------------------------- #
# Fetch, reporting and point-in-time loading
# --------------------------------------------------------------------------- #


class TestLoad:
    def test_load_into_pit_store_adds_every_observation(self):
        connector = EcbCcpConnector(client=_StubClient(CSV_BYTES))
        store = PITStore()

        report = connector.load(store)

        assert report.connector == "ecb_ccp"
        assert report.fetched == EMITTED
        assert report.added == EMITTED
        assert len(store) == EMITTED

    def test_load_is_idempotent_on_repeat(self):
        connector = EcbCcpConnector(client=_StubClient(CSV_BYTES))
        store = PITStore()

        first = connector.load(store)
        second = connector.load(store)

        assert first.added == EMITTED
        assert second.added == 0
        assert len(store) == EMITTED

    def test_load_reports_series_and_entity_coverage(self):
        connector = EcbCcpConnector(client=_StubClient(CSV_BYTES))
        report = connector.load(PITStore())

        assert set(report.entities) == {"AT1", "FR1"}
        assert report.first_valid_time == pd.Timestamp("2006-12-31")
        assert report.last_valid_time == pd.Timestamp("2025-12-31")
        # Six observations, but AT1/D0T recurs in 2006 and 2025, so five keys.
        assert len(report.series) == EMITTED - 1

    def test_stored_observations_are_visible_only_after_publication(self):
        connector = EcbCcpConnector(client=_StubClient(CSV_BYTES))
        store = PITStore()
        connector.load(store)

        # The 2025 value is assumed published 2026-07-31; before then the store
        # must not hand it out, and the missing period is absent, not filled.
        before = store.query("AT1", D0T_2006_SERIES, as_of="2026-07-30")
        after = store.query("AT1", D0T_2006_SERIES, as_of="2026-07-31")

        assert before["valid_time"].tolist() == [pd.Timestamp("2006-12-31")]
        assert after["valid_time"].tolist() == [
            pd.Timestamp("2006-12-31"),
            pd.Timestamp("2025-12-31"),
        ]

    def test_fetch_wraps_the_url_and_user_agent_in_the_client_call(self):
        stub = _StubClient(CSV_BYTES)
        connector = EcbCcpConnector(client=stub)

        connector.fetch(FetchRequest(start="2025-01-01", end="2025-12-31"))

        assert len(stub.calls) == 1
        assert stub.calls[0]["url"].endswith("startPeriod=2025&endPeriod=2025")
        assert stub.calls[0]["accept"] == "text/csv"
        assert stub.calls[0]["connector"] == "ecb_ccp"

    def test_unreachable_source_propagates_as_unavailable(self):
        connector = EcbCcpConnector(client=_FailingClient())

        with pytest.raises(DataSourceUnavailableError):
            connector.fetch()


# --------------------------------------------------------------------------- #
# Spec
# --------------------------------------------------------------------------- #


class TestSpec:
    def test_spec_declares_the_verified_endpoint_and_cadence(self):
        spec = EcbCcpConnector().spec

        assert spec.name == "ecb_ccp"
        assert spec.kind == "ecb"
        assert spec.cadence == "annual"
        assert spec.requires_credentials is False
        assert spec.endpoint == "https://data-api.ecb.europa.eu/service/data/CCP/all"
        assert spec.source_url == "https://data.ecb.europa.eu/data/datasets/CCP"

    def test_spec_licence_states_the_ecb_reuse_terms(self):
        licence = EcbCcpConnector().spec.licence

        assert "reused free of charge" in licence
        assert "source is quoted" in licence
        assert "not modified" in licence

    def test_spec_entity_id_names_the_reporting_dimension(self):
        assert EcbCcpConnector().spec.entity_id == "CCP_SYSTEM"
