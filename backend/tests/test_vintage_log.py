"""Vintage log: a restated series must not rewrite what was believed.

``indicator_observations`` is a latest-value store -- its primary key is the
period, so a restatement overwrites, and a backtest re-run tomorrow would
"have known" in May what was only published in June. The vintage log keeps
every written value with the instant it was published, and
``observations_as_of`` re-derives the series exactly as it stood at a past
date. These tests pin that contract, including the honest part: vintages are
append-only, and a restatement changes the latest value without touching the
history.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

# No private DATABASE_URL here: conftest.py pins USE_SQLITE=true suite-wide,
# and backend.database under that flag ignores DATABASE_URL and binds the
# shared on-disk ``./beacon.db`` -- which conftest also deletes at session
# start, so every run begins cold and the vintage-log counts below are only
# ever this run's own writes.

from backend.database import SessionLocal, init_db  # noqa: E402
from backend.models.timeseries import IndicatorObservation, IndicatorVintageLog  # noqa: E402
from backend.modules.results.timeseries_store import TimeSeriesStore  # noqa: E402

T0 = datetime(2026, 1, 31, tzinfo=timezone.utc)
T1 = datetime(2026, 2, 28, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def db():
    init_db()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _row(time, value, job="job-a"):
    return {
        "time": time,
        "source_code": "imf",
        "indicator_code": "LIQ_RATIO",
        "region": "GLOBAL",
        "value": value,
        "unit": "pct",
        "quality_score": 0.9,
        "ingest_job_id": job,
    }


def test_first_write_records_one_vintage(db):
    store = TimeSeriesStore(db)
    written = store.record_observations([_row(T0, 100.0)])
    assert written == 1
    vintages = (
        db.query(IndicatorVintageLog)
        .filter(IndicatorVintageLog.time == T0)
        .order_by(IndicatorVintageLog.published_at)
        .all()
    )
    assert len(vintages) == 1
    assert vintages[0].value == 100.0


def test_restatement_keeps_history_and_updates_latest(db):
    store = TimeSeriesStore(db)
    first_published = (
        db.query(IndicatorVintageLog)
        .filter(IndicatorVintageLog.time == T0)
        .order_by(IndicatorVintageLog.published_at)
        .first()
        .published_at
    )

    # the restatement arrives "a month later" in deployment time; freeze it by
    # writing through the store and reading the log's own stamps
    store.record_observations([_row(T0, 95.0, job="job-b")])

    vintages = (
        db.query(IndicatorVintageLog)
        .filter(IndicatorVintageLog.time == T0)
        .order_by(IndicatorVintageLog.published_at)
        .all()
    )
    assert [v.value for v in vintages] == [100.0, 95.0]

    latest = (
        db.query(IndicatorObservation)
        .filter(
            IndicatorObservation.time == T0,
            IndicatorObservation.source_code == "imf",
            IndicatorObservation.indicator_code == "LIQ_RATIO",
        )
        .one()
    )
    assert latest.value == 95.0
    assert latest.ingest_job_id == "job-b"

    # as of the instant between the two publications, the original value is
    # what a decision could have seen; the restatement is invisible there by
    # construction
    second_published = vintages[1].published_at
    gap = second_published - first_published
    as_of = first_published + gap / 2 if gap > timedelta(0) else first_published
    series = store.observations_as_of("imf", "LIQ_RATIO", as_of)
    assert [row.value for row in series] == [100.0]

    # as of now, the restated value is
    series_now = store.observations_as_of(
        "imf", "LIQ_RATIO", datetime.now(timezone.utc)
    )
    assert [row.value for row in series_now] == [95.0]


def test_as_of_never_sees_the_future(db):
    store = TimeSeriesStore(db)
    store.record_observations([_row(T1, 42.0, job="job-c")])
    before_any = datetime(2025, 12, 31, tzinfo=timezone.utc)
    assert store.observations_as_of("imf", "LIQ_RATIO", before_any) == []


def test_vintages_for_returns_the_full_candidate_set_oldest_first(db):
    # Direct inserts with explicit publication stamps: record_observations
    # stamps now(), which would not pin the ordering this query must return.
    rows = [
        IndicatorVintageLog(
            source_code="imf", indicator_code="PIT_FEAT", region="GLOBAL",
            time=T0, value=100.0, published_at=T0,
        ),
        IndicatorVintageLog(
            source_code="imf", indicator_code="PIT_FEAT", region="GLOBAL",
            time=T0, value=95.0, published_at=T1,
        ),
        IndicatorVintageLog(
            source_code="imf", indicator_code="PIT_FEAT", region="GLOBAL",
            time=T1, value=42.0, published_at=T1,
        ),
    ]
    db.add_all(rows)
    db.commit()

    store = TimeSeriesStore(db)

    all_rows = store.vintages_for("imf", "PIT_FEAT", region="GLOBAL")
    assert [row.value for row in all_rows] == [100.0, 95.0, 42.0]

    # valid_to bounds the described period (time), not publication.
    bounded = store.vintages_for("imf", "PIT_FEAT", region="GLOBAL", valid_to=T0)
    assert [row.value for row in bounded] == [100.0, 95.0]

    # A region with no vintages and an unknown indicator both return [].
    assert store.vintages_for("imf", "PIT_FEAT", region="US") == []
    assert store.vintages_for("imf", "NO_SUCH_INDICATOR") == []
