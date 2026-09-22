"""The observations writer for the DATA pipeline (pipeline-review finding F1).

``indicator_observations`` and its vintage log existed since the TimescaleDB
migration with no production caller -- ``record_observations`` was exercised
only by these store tests while the README claimed a writer "via the DATA
pipeline". ``persist_observations`` is that writer; these tests pin its
contract:

* scalar indicator rows are persisted with publisher/indicator/region from
  the catalogue contract, the gate's quality score and the ingest job id;
* panel rows, invalid rows and unmapped codes are skipped *and counted* --
  absence is recorded, never fabricated into a zero or an invented publisher;
* duplicate keys inside one payload are collapsed (last wins) before the
  upsert, because one ON CONFLICT statement may not touch a row twice;
* a re-run upserts the latest-value store and appends to the vintage log,
  which is the point-in-time contract the log exists for.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models.data_catalogue import (
    DataCatalogueItem,
    DataCategory,
    DataRegion,
)
from backend.models.data_source import DataSource
from backend.models.timeseries import IndicatorObservation, IndicatorVintageLog
from backend.tasks.job_tasks import persist_observations

_TABLES = [
    IndicatorObservation.__table__,
    IndicatorVintageLog.__table__,
    DataSource.__table__,
    DataCatalogueItem.__table__,
]


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=_TABLES)
    db = sessionmaker(bind=engine)()
    yield db
    db.close()


@pytest.fixture()
def catalogue(session):
    """One scalar FRED series and one panel feed, as the catalogue declares them."""
    fred = DataSource(name="FRED", plugin_type="fred", config={}, enabled=True)
    ai4risk = DataSource(name="AI4Risk Interbank", plugin_type="ai4risk_interbank", config={}, enabled=True)
    session.add_all([fred, ai4risk])
    session.commit()
    scalar_item = DataCatalogueItem(
        code="FRED_TEST",
        name="Test scalar series",
        category=DataCategory.ECONOMIC_INDICATORS,
        region=DataRegion.NORTH_AMERICA,
        data_source_id=fred.id,
        frequency="daily",
        unit="index",
    )
    panel_item = DataCatalogueItem(
        code="AI4RISK_TEST",
        name="Test interbank panel",
        category=DataCategory.BANKING,
        region=DataRegion.GLOBAL,
        data_source_id=ai4risk.id,
        frequency="quarterly",
        unit="usd",
    )
    session.add_all([scalar_item, panel_item])
    session.commit()
    return [scalar_item.id, panel_item.id]


def _package(tmp_path, frame: pd.DataFrame, quality_score=88.5):
    path = tmp_path / "timeseries.parquet"
    frame.to_parquet(path)
    return SimpleNamespace(
        timeseries_path=str(path),
        quality_report=SimpleNamespace(quality_score=quality_score),
    )


def _formatted_frame() -> pd.DataFrame:
    """Mimic the formatter's output: canonical columns plus the contract columns."""
    rows = [
        # scalar series: two valid dates, one duplicate key (last wins), one NaN value
        {"Date": "2024-01-01", "Value": 100.0, "source_code": "FRED_TEST", "series_id": "FRED_TEST", "unit": "index"},
        {"Date": "2024-01-01", "Value": 101.0, "source_code": "FRED_TEST", "series_id": "FRED_TEST", "unit": "index"},
        {"Date": "2024-01-02", "Value": float("nan"), "source_code": "FRED_TEST", "series_id": "FRED_TEST", "unit": "index"},
        {"Date": "2024-01-03", "Value": 102.0, "source_code": "FRED_TEST", "series_id": "FRED_TEST", "unit": "index"},
        # panel rows: entity identity inside series_id -> not scalar indicators
        {"Date": "2024-01-01", "Value": 5.0, "source_code": "AI4RISK_TEST", "series_id": "AI4RISK_TEST::A::B", "unit": "usd"},
        # a code that maps to no selected catalogue item
        {"Date": "2024-01-01", "Value": 7.0, "source_code": "UNMAPPED_CODE", "series_id": "UNMAPPED_CODE", "unit": None},
    ]
    frame = pd.DataFrame(rows)
    frame["Date"] = pd.to_datetime(frame["Date"])
    frame["value"] = pd.to_numeric(frame["Value"], errors="coerce")
    return frame


class TestPersistObservations:
    def test_scalar_rows_are_persisted_with_their_contract(self, session, catalogue, tmp_path):
        package = _package(tmp_path, _formatted_frame())

        counts = persist_observations(session, 7, package, catalogue)

        assert counts == {
            "persisted": 2,
            "skipped_panel": 1,
            "skipped_invalid": 1,
            "skipped_unmapped": 1,
            "collapsed_duplicates": 1,
        }

        observations = session.query(IndicatorObservation).order_by(IndicatorObservation.time).all()
        assert len(observations) == 2
        first, second = observations
        assert first.source_code == "fred"  # publisher plugin type, not the catalogue code
        assert first.indicator_code == "FRED_TEST"
        assert first.region == "north_america"
        assert first.value == 101.0  # duplicate collapsed, last wins
        assert first.unit == "index"
        assert first.quality_score == pytest.approx(88.5)
        assert first.ingest_job_id == "job_7"
        # written as tz-aware UTC; SQLite hands back naive datetimes, Postgres
        # timestamptz keeps the zone, so compare the instant dialect-tolerantly
        assert first.time.replace(tzinfo=None) == datetime(2024, 1, 1)
        assert second.value == 102.0

    def test_every_persisted_row_appends_a_vintage(self, session, catalogue, tmp_path):
        package = _package(tmp_path, _formatted_frame())
        persist_observations(session, 7, package, catalogue)

        vintages = session.query(IndicatorVintageLog).all()
        assert len(vintages) == 2
        assert {v.value for v in vintages} == {101.0, 102.0}
        assert all(v.ingest_job_id == "job_7" for v in vintages)
        assert all(v.published_at is not None for v in vintages)

    def test_rerun_upserts_latest_value_and_grows_the_vintage_log(self, session, catalogue, tmp_path):
        first_run = _package(tmp_path, _formatted_frame(), quality_score=80.0)
        persist_observations(session, 7, first_run, catalogue)

        revised = _formatted_frame()
        revised.loc[revised["Date"] == pd.Timestamp("2024-01-03"), "Value"] = 999.0
        revised["value"] = pd.to_numeric(revised["Value"], errors="coerce")
        second_run = _package(tmp_path, revised, quality_score=81.0)
        counts = persist_observations(session, 8, second_run, catalogue)

        assert counts["persisted"] == 2
        observations = session.query(IndicatorObservation).order_by(IndicatorObservation.time).all()
        assert len(observations) == 2  # latest-value store: still one row per key
        assert observations[1].value == 999.0
        assert observations[1].quality_score == pytest.approx(81.0)
        assert observations[1].ingest_job_id == "job_8"
        # the vintage log keeps what was believed before: 2 + 2
        assert session.query(IndicatorVintageLog).count() == 4

    def test_empty_payload_persists_nothing(self, session, catalogue, tmp_path):
        empty = pd.DataFrame(columns=["Date", "Value", "value", "source_code", "series_id", "unit"])
        counts = persist_observations(session, 9, _package(tmp_path, empty), catalogue)
        assert counts["persisted"] == 0
        assert session.query(IndicatorObservation).count() == 0

    def test_payload_without_a_value_column_is_refused_not_guessed(self, session, catalogue, tmp_path):
        frame = pd.DataFrame({
            "Date": pd.to_datetime(["2024-01-01"]),
            "source_code": ["FRED_TEST"],
            "series_id": ["FRED_TEST"],
        })
        counts = persist_observations(session, 10, _package(tmp_path, frame), catalogue)
        assert counts["persisted"] == 0
        assert session.query(IndicatorObservation).count() == 0
