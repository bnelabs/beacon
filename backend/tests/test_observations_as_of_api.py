"""The as-of observation endpoint: what this deployment knew, when it knew it.

``TimeSeriesStore.observations_as_of`` has existed since the vintage-log
migration, was tested, and had no production caller -- the reachability census
recorded it as a reader with nothing on the other end. That left the point-in-
time contract half-built: the log recorded every publication, and no operator,
dashboard, or backtest could ask the question the log exists to answer.

This route is the caller. Its contract is the network graph's, because that is
the one place in this API that already answers "as of" honestly:

* a malformed ``as_of`` is a typed 422 that names the value it could not read;
* nothing known at that instant is HTTP 200 with ``status: "unavailable"`` and a
  reason -- **never** the current values. Serving today's number under an
  ``as_of`` is the exact look-ahead the vintage log was built to prevent, and a
  client that silently receives it cannot tell it is being lied to;
* every row carries *why* its publication instant is what it is
  (``publication_basis``): a certified snapshot's capture instant, this
  deployment's ingest instant, or ``unknown`` for rows written before provenance
  existed. An as-of answer that does not say which of those it rests on asks the
  reader to trust it without evidence;
* truncation is reported, not hidden.

The endpoint reads only ``indicator_vintage_log``. ``indicator_observations`` is
the latest-value store, and a query that reached it would answer every historical
question with today's belief -- so one test below writes a latest-value row with
no vintage behind it and requires the endpoint to say it does not know.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.api.main import app
from backend.database import Base, get_db
from backend.models.timeseries import IndicatorObservation, IndicatorVintageLog
from backend.modules.results.timeseries_store import TimeSeriesStore

T0 = datetime(2026, 1, 31, tzinfo=timezone.utc)
T1 = datetime(2026, 2, 28, tzinfo=timezone.utc)
PUBLISHED = datetime(2026, 3, 3, 9, 0, tzinfo=timezone.utc)

_SOURCE = "imf"
_INDICATOR = "LIQ_RATIO"

_TABLES = [IndicatorObservation.__table__, IndicatorVintageLog.__table__]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def session():
    # StaticPool + check_same_thread=False, the same pairing ``backend.database``
    # uses for SQLite: ``TestClient`` runs the ASGI app on a worker thread, and
    # the default pool for ``:memory:`` hands each thread its *own* database --
    # so the fixture's rows would be invisible to the route and every request
    # would fail with "no such table".
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=_TABLES)
    factory = sessionmaker(bind=engine)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def api(client, session):
    """Route the endpoint at this test's own database, not the shared one."""
    app.dependency_overrides[get_db] = lambda: session
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_db, None)


def _vintage(session, time, value, *, published_at, basis="certified_snapshot", snapshot_id=None, job="job-1"):
    session.add(
        IndicatorVintageLog(
            source_code=_SOURCE,
            indicator_code=_INDICATOR,
            region="GLOBAL",
            time=time,
            value=value,
            published_at=published_at,
            publication_basis=basis,
            snapshot_id=snapshot_id,
            ingest_job_id=job,
        )
    )
    session.commit()


def _get(api, **params):
    query = {"source_code": _SOURCE, "indicator_code": _INDICATOR, **params}
    return api.get("/api/v1/observations/as-of", params=query)


class TestAnAnswerCarriesItsProvenance:
    def test_a_series_known_at_the_instant_is_returned_with_its_instants(self, api, session):
        _vintage(session, T0, 100.0, published_at=PUBLISHED, snapshot_id="sha256:" + "a" * 64)
        _vintage(session, T1, 101.0, published_at=PUBLISHED, snapshot_id="sha256:" + "a" * 64)

        response = _get(api, as_of=PUBLISHED.isoformat())
        assert response.status_code == 200
        payload = response.json()

        assert payload["status"] == "available"
        assert payload["as_of"] == PUBLISHED.isoformat()
        assert payload["source_code"] == _SOURCE
        assert payload["indicator_code"] == _INDICATOR
        assert [row["value"] for row in payload["observations"]] == [100.0, 101.0]
        assert [row["time"] for row in payload["observations"]] == [
            T0.isoformat(),
            T1.isoformat(),
        ]
        assert all(row["publication_basis"] == "certified_snapshot" for row in payload["observations"])
        assert all(row["snapshot_id"] == "sha256:" + "a" * 64 for row in payload["observations"])
        assert payload["provenance_coverage"] == {
            "certified_snapshot": 2,
            "ingest_instant": 0,
            "unknown": 0,
        }

    def test_rows_written_before_provenance_existed_are_reported_as_unknown(self, api, session):
        _vintage(session, T0, 100.0, published_at=PUBLISHED, basis=None, snapshot_id=None)

        payload = _get(api, as_of=PUBLISHED.isoformat()).json()
        assert payload["observations"][0]["publication_basis"] == "unknown"
        assert payload["provenance_coverage"]["unknown"] == 1
        assert payload["provenance_coverage"]["certified_snapshot"] == 0

    def test_the_newest_vintage_at_or_before_the_instant_wins_per_period(self, api, session):
        _vintage(session, T0, 100.0, published_at=PUBLISHED - timedelta(days=1))
        _vintage(session, T0, 95.0, published_at=PUBLISHED, basis="ingest_instant")

        payload = _get(api, as_of=PUBLISHED.isoformat()).json()
        assert [row["value"] for row in payload["observations"]] == [95.0]

    def test_the_as_of_reader_has_a_production_caller(self):
        """The census recorded `observations_as_of` as tested and uncalled."""
        paths = app.openapi()["paths"]
        assert "/api/v1/observations/as-of" in paths
        assert "get" in paths["/api/v1/observations/as-of"]


class TestNothingKnownIsSaidAsNothingKnown:
    def test_an_instant_before_any_publication_is_unavailable_not_today(self, api, session):
        _vintage(session, T0, 100.0, published_at=PUBLISHED)

        response = _get(api, as_of=(PUBLISHED - timedelta(microseconds=1)).isoformat())
        assert response.status_code == 200
        payload = response.json()

        assert payload["status"] == "unavailable"
        assert payload["observations"] == []
        assert payload["count"] == 0
        assert "unavailable_reason" in payload

    def test_the_latest_value_table_is_never_substituted_for_history(self, api, session):
        # The failure this test exists to catch: a reader that reaches
        # `indicator_observations` answers every historical question with the
        # value believed today.
        session.add(
            IndicatorObservation(
                time=T0,
                source_code=_SOURCE,
                indicator_code=_INDICATOR,
                region="GLOBAL",
                value=42.0,
                quality_score=99.0,
            )
        )
        session.commit()

        payload = _get(api, as_of=datetime(2020, 1, 1, tzinfo=timezone.utc).isoformat()).json()
        assert payload["status"] == "unavailable"
        assert payload["observations"] == []
        assert 42.0 not in [row["value"] for row in payload["observations"]]

    def test_a_restated_value_is_invisible_at_the_earlier_instant(self, api, session):
        _vintage(session, T0, 100.0, published_at=PUBLISHED)
        _vintage(session, T0, 95.0, published_at=PUBLISHED + timedelta(days=30), basis="ingest_instant")

        early = _get(api, as_of=(PUBLISHED + timedelta(days=1)).isoformat()).json()
        assert [row["value"] for row in early["observations"]] == [100.0]

        late = _get(api, as_of=(PUBLISHED + timedelta(days=31)).isoformat()).json()
        assert [row["value"] for row in late["observations"]] == [95.0]

    def test_an_unknown_series_is_unavailable_rather_than_an_empty_success(self, api, session):
        _vintage(session, T0, 100.0, published_at=PUBLISHED)

        payload = _get(
            api, indicator_code="NO_SUCH_SERIES", as_of=PUBLISHED.isoformat()
        ).json()
        assert payload["status"] == "unavailable"
        assert payload["indicator_code"] == "NO_SUCH_SERIES"


class TestMalformedInputIsTyped:
    def test_an_unreadable_as_of_names_the_value_it_could_not_read(self, api, session):
        response = _get(api, as_of="3 March 2026")
        assert response.status_code == 422
        detail = response.json()["detail"]
        assert "as_of" in str(detail)
        assert "ISO 8601" in str(detail)

    def test_unreadable_window_bounds_are_rejected_not_ignored(self, api, session):
        _vintage(session, T0, 100.0, published_at=PUBLISHED)
        response = _get(
            api, as_of=PUBLISHED.isoformat(), valid_from="the start of time"
        )
        assert response.status_code == 422
        assert "valid_from" in str(response.json()["detail"])

    def test_a_window_that_starts_after_it_ends_is_rejected(self, api, session):
        _vintage(session, T0, 100.0, published_at=PUBLISHED)
        response = _get(
            api,
            as_of=PUBLISHED.isoformat(),
            valid_from=T1.isoformat(),
            valid_to=T0.isoformat(),
        )
        assert response.status_code == 422
        assert "valid_from" in str(response.json()["detail"])


class TestWindowsRegionsAndLimits:
    def test_the_valid_time_window_selects_periods_without_changing_the_cut(self, api, session):
        _vintage(session, T0, 100.0, published_at=PUBLISHED)
        _vintage(session, T1, 101.0, published_at=PUBLISHED)

        payload = _get(
            api,
            as_of=PUBLISHED.isoformat(),
            valid_from=T1.isoformat(),
        ).json()
        assert [row["value"] for row in payload["observations"]] == [101.0]

    def test_the_region_filter_selects_the_series_not_a_neighbour(self, api, session):
        _vintage(session, T0, 100.0, published_at=PUBLISHED)
        session.add(
            IndicatorVintageLog(
                source_code=_SOURCE,
                indicator_code=_INDICATOR,
                region="EUROPE",
                time=T0,
                value=77.0,
                published_at=PUBLISHED,
                publication_basis="certified_snapshot",
            )
        )
        session.commit()

        payload = _get(api, as_of=PUBLISHED.isoformat(), region="EUROPE").json()
        assert [row["value"] for row in payload["observations"]] == [77.0]
        assert payload["region"] == "EUROPE"

    def test_a_truncated_answer_says_that_it_was_truncated(self, api, session):
        for index in range(5):
            _vintage(session, T0 + timedelta(days=index), 100.0 + index, published_at=PUBLISHED)

        payload = _get(api, as_of=PUBLISHED.isoformat(), limit=3).json()
        assert payload["status"] == "available"
        assert len(payload["observations"]) == 3
        assert payload["truncated"] is True
        assert payload["vintages_at_or_before_as_of"] == 5

    def test_the_store_and_the_endpoint_agree_on_the_same_instant(self, api, session):
        _vintage(session, T0, 100.0, published_at=PUBLISHED)
        store_rows = TimeSeriesStore(session).observations_as_of(_SOURCE, _INDICATOR, PUBLISHED)

        payload = _get(api, as_of=PUBLISHED.isoformat()).json()
        assert [row["value"] for row in payload["observations"]] == [row.value for row in store_rows]
