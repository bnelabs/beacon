"""POST /api/v1/pipeline must dispatch to the worker pool, not run in-process.

Pipeline-review finding F3: the route executed the whole DATA → ENGINE →
RESULTS run as a FastAPI BackgroundTask inside the API process -- no queue
visibility, no worker supervision, the run lost silently on an API restart,
and torch stages competing with request handling. These tests pin the fixed
contract:

* a successful POST creates the PipelineJob/DataJob rows and hands the run
  to the ``run_pipeline`` Celery task (the same worker pool every other job
  uses), returning immediately with the queued status;
* a dispatch that cannot reach the broker marks the pipeline FAILED rather
  than leaving it pending forever -- a queued run that never queued must not
  read as health.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.database import SessionLocal, init_db
from backend.models.pipeline_job import DataJob, EngineJob, JobStatus, PipelineJob, ResultJob
from backend.tasks.job_tasks import run_pipeline

client = TestClient(app)

BODY = {
    "name": "dispatch-test",
    "catalogue_items": [1, 2],
    "start_date": "2024-01-01",
    "end_date": "2024-06-30",
    "config": {},
}


@pytest.fixture(autouse=True)
def _clean():
    """Within-run cleanup, per the conftest convention: this module creates
    PipelineJob/DataJob rows the status routes would otherwise keep serving."""
    init_db()
    db = SessionLocal()

    def _wipe() -> None:
        # Children first, and all of them: clearing PipelineJob while leaving
        # EngineJob/ResultJob behind is the same state-injection class that
        # reddened main through test_data_quality_routes (see conftest).
        db.query(DataJob).delete()
        db.query(EngineJob).delete()
        db.query(ResultJob).delete()
        db.query(PipelineJob).delete()
        db.commit()

    _wipe()
    yield
    _wipe()
    db.close()


def test_post_dispatches_to_celery_and_returns_queued(monkeypatch):
    calls = []

    def fake_delay(*args, **kwargs):
        calls.append((args, kwargs))

    monkeypatch.setattr(run_pipeline, "delay", fake_delay)

    response = client.post("/api/v1/pipeline", json=BODY)
    assert response.status_code == 201
    payload = response.json()
    assert payload["status"] == JobStatus.PENDING.value
    assert payload["current_step"] == "Pipeline queued for execution"

    # the run was handed to the worker pool with the declared inputs
    assert len(calls) == 1
    args, kwargs = calls[0]
    pipeline_job_id, catalogue_items, start_date, end_date, config = args
    assert catalogue_items == [1, 2]
    assert (start_date, end_date) == ("2024-01-01", "2024-06-30")
    assert config == {}

    db = SessionLocal()
    try:
        pipeline_job = db.get(PipelineJob, pipeline_job_id)
        assert pipeline_job is not None
        assert pipeline_job.status == JobStatus.PENDING
        data_job = (
            db.query(DataJob)
            .filter(DataJob.pipeline_job_id == pipeline_job_id)
            .one()
        )
        assert data_job.status == JobStatus.PENDING
        assert data_job.catalogue_items == [1, 2]
    finally:
        db.close()


def test_failed_dispatch_marks_the_pipeline_failed(monkeypatch):
    def broken_delay(*args, **kwargs):
        raise ConnectionError("broker unreachable")

    monkeypatch.setattr(run_pipeline, "delay", broken_delay)

    response = client.post("/api/v1/pipeline", json=BODY)
    assert response.status_code == 500

    db = SessionLocal()
    try:
        pipeline_job = (
            db.query(PipelineJob).filter(PipelineJob.name == "dispatch-test").one()
        )
        # a run that never reached the queue must not sit pending forever
        assert pipeline_job.status == JobStatus.FAILED
        assert "dispatch failed" in (pipeline_job.error_message or "")
    finally:
        db.close()
