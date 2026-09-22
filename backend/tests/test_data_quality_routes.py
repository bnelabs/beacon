"""The data-quality endpoints must see the production collection path.

Pipeline-review finding F2: ``/api/v1/data-quality/*`` read quality scores
exclusively from ``DataJob ⋈ PipelineJob`` -- rows only ``POST
/api/v1/pipeline`` writes, and a route the frontend never calls. Every real
collection (jobs API, manual sync, scheduler) stores the gate's verdict in
``Job.result`` and its source link in ``Job.parameters.data_source_id``, so
the Data Quality page showed zeros on any deployment collecting through the
documented path while collections succeeded.

These tests pin the fixed contract:

* ``stats`` aggregates BOTH writers, reports completeness on the gate's
  0-100 scale verbatim (the old ``*100`` rendered a 97% panel as 9700%),
  and counts "low quality" below the gate's certification floor (the old
  0.5 threshold on a 0-100 scale counted nothing, ever -- a vacuous
  metric);
* ``sources`` links production jobs to their source via the parameter the
  scheduler has always written;
* ``trends`` buckets both writers by day and counts failed collections from
  the production path too.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.database import SessionLocal, init_db
from backend.models.data_source import DataSource
from backend.models.job import Job
from backend.models.pipeline_job import DataJob, JobStatus, PipelineJob, PipelineStage

client = TestClient(app)

START = "/api/v1/data-quality"


@pytest.fixture(autouse=True)
def _clean_tables():
    """A cold start and a cold finish for the tables this module reads.

    The endpoints aggregate globally (that is their job), so the assertions
    below are only deterministic against a known-empty set of writers --
    per test, not just per module; and the rows this module seeds would
    silently inflate every later module that counts sources or jobs.
    conftest documents the convention: modules keep their own within-run
    cleanup.
    """
    init_db()
    db = SessionLocal()

    def _wipe() -> None:
        db.query(DataJob).delete()
        db.query(PipelineJob).delete()
        db.query(Job).delete()
        db.query(DataSource).delete()
        db.commit()

    _wipe()
    yield
    _wipe()
    db.close()


@pytest.fixture()
def db():
    session = SessionLocal()
    yield session
    session.close()


def _source(db, name: str = "dq-fred") -> DataSource:
    now = datetime.now(timezone.utc)
    source = DataSource(
        name=name,
        plugin_type="fred",
        config={},
        enabled=True,
        status="active",
        last_successful_fetch=now - timedelta(hours=1),
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _collection_job(db, source_id: int, status: str, quality_score=None, completeness=None,
                    created_at=None) -> Job:
    job = Job(
        job_type="data_collection",
        status=status,
        parameters={"data_source_id": source_id, "catalogue_items": [1]},
        result=(
            {"quality_score": quality_score, "completeness": completeness, "fit_for_engine": True}
            if quality_score is not None else None
        ),
        error_message="provider down" if status == "failed" else None,
    )
    if created_at is not None:
        job.created_at = created_at
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _pipeline_data_job(db, quality_score: float, completeness: float) -> DataJob:
    pipeline = PipelineJob(
        job_id=f"pipeline_dq_{quality_score}",
        name="dq pipeline",
        current_stage=PipelineStage.DATA,
        status=JobStatus.COMPLETED,
    )
    db.add(pipeline)
    db.commit()
    db.refresh(pipeline)
    data_job = DataJob(
        pipeline_job_id=pipeline.id,
        status=JobStatus.COMPLETED,
        quality_score=quality_score,
        completeness=completeness,
    )
    db.add(data_job)
    db.commit()
    db.refresh(data_job)
    return data_job


def test_stats_aggregates_both_writers_on_the_gate_scale(db):
    source = _source(db)
    _collection_job(db, source.id, "completed", quality_score=91.2, completeness=97.0)
    _collection_job(db, source.id, "completed", quality_score=55.0, completeness=90.0)
    _pipeline_data_job(db, quality_score=80.0, completeness=90.0)

    response = client.get(f"{START}/stats")
    assert response.status_code == 200
    payload = response.json()

    # (91.2 + 55.0 + 80.0) / 3 -- the production path is IN the aggregate
    assert payload["overview"]["avg_quality_score"] == pytest.approx(75.4, abs=1e-4)
    assert payload["quality"]["jobs_analyzed"] == 3
    # completeness is the gate's 0-100 scale, verbatim: (97 + 90 + 90) / 3.
    # The old *100 rendered this as 9233.3%.
    assert payload["quality"]["avg_completeness"] == pytest.approx(92.3333, abs=1e-3)
    assert payload["quality"]["avg_completeness"] <= 100.0
    # 55.0 is below the gate's certification floor (70); the old 0.5 threshold
    # on a 0-100 scale never counted anything.
    assert payload["quality"]["low_quality_count"] == 1
    assert payload["anomalies"]["low_quality_jobs"] == 1


def test_stats_counts_failed_collections_from_the_production_path(db):
    source = _source(db, name="dq-failing")
    _collection_job(db, source.id, "completed", quality_score=88.0, completeness=95.0)
    _collection_job(db, source.id, "failed")

    payload = client.get(f"{START}/stats").json()
    assert payload["quality"]["recent_errors"] >= 1
    assert payload["anomalies"]["recent_failures"] >= 1


def test_sources_links_production_jobs_via_parameters(db):
    source = _source(db, name="dq-linked")
    other = _source(db, name="dq-unlinked")
    _collection_job(db, source.id, "completed", quality_score=91.2, completeness=97.0)
    _collection_job(db, source.id, "completed", quality_score=80.0, completeness=93.0)

    response = client.get(f"{START}/sources")
    assert response.status_code == 200
    rows = {row["name"]: row for row in response.json()}

    linked = rows["dq-linked"]
    assert linked["avg_quality_score"] == pytest.approx(85.6, abs=1e-4)
    assert linked["recent_job_count"] == 2
    assert linked["freshness_status"] == "fresh"

    unlinked = rows["dq-unlinked"]
    assert unlinked["avg_quality_score"] is None
    assert unlinked["recent_job_count"] == 0


def test_trends_buckets_both_writers_and_counts_failures(db):
    source = _source(db, name="dq-trend")
    _collection_job(db, source.id, "completed", quality_score=91.2, completeness=97.0)
    _collection_job(db, source.id, "failed")
    _pipeline_data_job(db, quality_score=80.0, completeness=90.0)

    response = client.get(f"{START}/trends", params={"days": 30})
    assert response.status_code == 200
    payload = response.json()

    today = datetime.now(timezone.utc).date().isoformat()
    buckets = {entry["date"]: entry for entry in payload["trends"]}
    assert today in buckets
    bucket = buckets[today]
    assert bucket["job_count"] == 2  # one completed collection + one pipeline DATA job
    assert bucket["avg_quality_score"] == pytest.approx(85.6, abs=1e-4)
    assert bucket["error_count"] == 1  # the failed collection, from the production path
    assert payload["summary"]["total_jobs"] == 2
