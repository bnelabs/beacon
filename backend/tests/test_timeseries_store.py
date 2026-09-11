"""Tests for the time-series store.

These run on SQLite, which is exactly the plain (non-Timescale) path: the store
must produce correct windowed aggregations without hypertables or continuous
aggregates, and must fall back cleanly when a pre-aggregate is advertised but
unusable.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models.timeseries import (
    IndicatorObservation,
    ModelMetricPoint,
    RiskScorePoint,
)
from backend.modules.results.timeseries_store import (
    BASE_TABLE_SOURCE,
    CONTINUOUS_AGGREGATE_SOURCE,
    RISK_SCORES_DAILY,
    TimeSeriesStore,
)

_TABLES = [IndicatorObservation.__table__, RiskScorePoint.__table__, ModelMetricPoint.__table__]


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=_TABLES)
    factory = sessionmaker(bind=engine)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def store(session):
    return TimeSeriesStore(session)


def _risk_row(day: int, score: float, region: str = "EUROPE", entity: str = "bank-1", **extra):
    row = {
        "time": datetime(2024, 1, 1) + timedelta(days=day),
        "entity_type": "bank",
        "entity_id": entity,
        "model_version": "v1",
        "horizon_days": 1,
        "region": region,
        "risk_score": score,
    }
    row.update(extra)
    return row


# --------------------------------------------------------------------------
# Schema contract
# --------------------------------------------------------------------------

def test_time_column_is_part_of_every_primary_key():
    """TimescaleDB cannot make a hypertable when a unique index omits the time column."""
    for table in _TABLES:
        assert "time" in {column.name for column in table.primary_key.columns}, table.name


# --------------------------------------------------------------------------
# Writes
# --------------------------------------------------------------------------

def test_record_and_upsert_risk_scores(store, session):
    assert store.record_risk_scores([_risk_row(0, 10.0)]) == 1
    assert session.query(RiskScorePoint).count() == 1

    # Same natural key, new value: must update in place, never duplicate.
    store.record_risk_scores([_risk_row(0, 42.0)])
    session.expire_all()

    assert session.query(RiskScorePoint).count() == 1
    assert session.query(RiskScorePoint).one().risk_score == pytest.approx(42.0)


def test_record_observations_upsert(store, session):
    row = {
        "time": datetime(2024, 1, 1),
        "source_code": "ECB",
        "indicator_code": "LIQ",
        "region": "EUROPE",
        "value": 1.0,
    }
    store.record_observations([row])
    store.record_observations([{**row, "value": 2.5}])
    session.expire_all()

    assert session.query(IndicatorObservation).count() == 1
    assert session.query(IndicatorObservation).one().value == pytest.approx(2.5)


def test_record_model_metrics_upsert(store, session):
    row = {
        "time": datetime(2024, 1, 1),
        "job_id": "job-1",
        "metric_name": "sharpe_ratio",
        "metric_value": 1.2,
    }
    store.record_model_metrics([row])
    store.record_model_metrics([{**row, "metric_value": 1.8}])
    session.expire_all()

    assert session.query(ModelMetricPoint).count() == 1
    assert session.query(ModelMetricPoint).one().metric_value == pytest.approx(1.8)


def test_empty_writes_are_noops(store):
    assert store.record_risk_scores([]) == 0
    assert store.record_observations([]) == 0
    assert store.record_model_metrics([]) == 0


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------

def test_average_risk_by_region_over_window(store):
    rows = [
        _risk_row(0, 10.0, region="EUROPE"),
        _risk_row(1, 20.0, region="EUROPE"),
        _risk_row(2, 30.0, region="ASIA"),
        _risk_row(100, 99.0, region="EUROPE"),  # outside the 30-day window
    ]
    store.record_risk_scores(rows)

    end = datetime(2024, 1, 10)
    summaries = store.average_risk_by_region(days=30, end=end)

    by_region = {summary.region: summary for summary in summaries}
    assert by_region["EUROPE"].avg_risk_score == pytest.approx(15.0)
    assert by_region["EUROPE"].max_risk_score == pytest.approx(20.0)
    assert by_region["EUROPE"].observations == 2
    assert by_region["ASIA"].avg_risk_score == pytest.approx(30.0)
    assert all(summary.source == BASE_TABLE_SOURCE for summary in summaries)
    assert by_region["EUROPE"].to_dict()["days"] == 30


def test_average_risk_by_region_filters_entity_type(store):
    store.record_risk_scores([
        _risk_row(0, 10.0, entity_type="bank"),
        _risk_row(1, 90.0, entity_type="region", entity="EUROPE"),
    ])

    summaries = store.average_risk_by_region(
        days=30, end=datetime(2024, 1, 10), entity_type="bank"
    )
    assert len(summaries) == 1
    assert summaries[0].avg_risk_score == pytest.approx(10.0)


def test_average_risk_by_region_rejects_non_positive_window(store):
    with pytest.raises(ValueError):
        store.average_risk_by_region(days=0)


def test_regions_are_ordered_by_descending_risk(store):
    store.record_risk_scores([
        _risk_row(0, 5.0, region="AFRICA"),
        _risk_row(1, 80.0, region="EUROPE"),
    ])
    summaries = store.average_risk_by_region(days=30, end=datetime(2024, 1, 10))
    assert [summary.region for summary in summaries] == ["EUROPE", "AFRICA"]


def test_rows_without_a_region_are_excluded(store):
    store.record_risk_scores([_risk_row(0, 50.0, region=None)])
    assert store.average_risk_by_region(days=30, end=datetime(2024, 1, 10)) == []


# --------------------------------------------------------------------------
# TimescaleDB capability handling
# --------------------------------------------------------------------------

def test_continuous_aggregate_absent_on_sqlite(store):
    assert store.has_continuous_aggregate(RISK_SCORES_DAILY) is False


def test_falls_back_when_aggregate_is_advertised_but_unusable(store, session):
    """A declared-but-broken pre-aggregate must degrade, not raise."""
    store.record_risk_scores([_risk_row(0, 10.0), _risk_row(1, 30.0)])
    store._aggregate_cache[RISK_SCORES_DAILY] = True

    summaries = store.average_risk_by_region(days=30, end=datetime(2024, 1, 10))

    assert summaries, "must still answer from the base table"
    assert summaries[0].source == BASE_TABLE_SOURCE
    assert summaries[0].avg_risk_score == pytest.approx(20.0)


def test_aggregate_source_is_reported(store):
    store.record_risk_scores([_risk_row(0, 10.0)])
    summaries = store.average_risk_by_region(days=30, end=datetime(2024, 1, 10))
    assert summaries[0].source in {BASE_TABLE_SOURCE, CONTINUOUS_AGGREGATE_SOURCE}


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------

def test_latest_risk_scores_orders_newest_first(store):
    store.record_risk_scores([
        _risk_row(0, 1.0, entity="a"),
        _risk_row(5, 2.0, entity="b"),
        _risk_row(3, 3.0, entity="c"),
    ])
    latest = store.latest_risk_scores(limit=2)
    assert [point.entity_id for point in latest] == ["b", "c"]


def test_latest_risk_scores_filters(store):
    store.record_risk_scores([
        _risk_row(0, 1.0, region="EUROPE", entity="a"),
        _risk_row(1, 2.0, region="ASIA", entity="b"),
    ])
    latest = store.latest_risk_scores(region="ASIA")
    assert [point.entity_id for point in latest] == ["b"]


def test_metric_history_window(store):
    store.record_model_metrics([
        {"time": datetime(2024, 1, 1), "job_id": "j1", "metric_name": "sharpe_ratio", "metric_value": 1.0},
        {"time": datetime(2024, 3, 1), "job_id": "j2", "metric_name": "sharpe_ratio", "metric_value": 2.0},
        {"time": datetime(2024, 1, 2), "job_id": "j1", "metric_name": "rmse", "metric_value": 0.5},
    ])

    history = store.metric_history("sharpe_ratio", days=30, end=datetime(2024, 1, 31))
    assert len(history) == 1
    assert history[0].metric_value == pytest.approx(1.0)

    all_sharpe = store.metric_history("sharpe_ratio", days=365, end=datetime(2024, 12, 31))
    assert [point.metric_value for point in all_sharpe] == pytest.approx([1.0, 2.0])
