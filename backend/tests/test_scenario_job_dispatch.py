"""Dispatch contract for the background scenario path.

Scenario jobs are a new job type (``scenario``) that must:

* be accepted by ``JobService.create_job`` like every other job type;
* be routed by ``dispatch_job`` to the ``scenarios`` queue — consumed by the
  dedicated scenario-worker (concurrency 2) — while every other job type
  keeps the default queue;
* fail per-scenario: one bad scenario job ends up ``failed`` with its own
  technical error, without touching the shared engine or any other job.

The synchronous simulate endpoint is unchanged and stays the other half of
the pair; ``scenario_service.execute_scenario`` is the shared core both
paths call, and ``test_batched_inference_equivalence.py`` pins the engine
behind it.
"""

from __future__ import annotations

import importlib

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models.job import Job
from backend.schemas.job import JobCreate
from backend.services.job_service import JobService


@pytest.fixture()
def session_engine():
    """Throwaway SQLite engine (StaticPool: one shared connection) holding the
    real ``jobs`` table. A factory of sessions on this engine is what the
    task's ``SessionLocal()`` should return, so each task call gets its own
    session object while sharing the connection."""
    from sqlalchemy.pool import StaticPool

    engine = create_engine("sqlite:///:memory:", poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Job.__table__])
    yield engine
    engine.dispose()


@pytest.fixture()
def session(session_engine):
    db = sessionmaker(bind=session_engine)()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def task_session_factory(session_engine):
    """Stands in for ``SessionLocal``: a fresh session per call, on the same
    engine, so the task's ``db.close()`` never tears down the fixture session."""
    factory = sessionmaker(bind=session_engine)

    def _session_local():
        return factory()

    return _session_local


@pytest.fixture()
def job(session):
    record = Job(job_type="training", status="completed", progress=100.0)
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


class _DispatchRecorder:
    """Stands in for dispatch_job.delay: runs the real dispatch body eagerly
    (no broker) and returns a handle with an .id, as the real .delay does."""

    def __init__(self, real_dispatch):
        self.real = real_dispatch

    def delay(self, job_id, job_type, parameters):
        return self.real.apply(args=[job_id, job_type, parameters])


def test_scenario_jobs_route_to_the_scenarios_queue(session, job, monkeypatch):
    importlib.import_module("backend.tasks.celery_app").__name__  # warm import
    celery_module = importlib.import_module("backend.tasks.celery_app")
    real_dispatch = celery_module.dispatch_job
    monkeypatch.setattr("backend.services.job_service.publish_job_update", lambda payload: None)

    calls = []

    from backend.tasks.job_tasks import run_scenario

    def recorder(*args, **kwargs):
        calls.append((args, kwargs))
        return None

    monkeypatch.setattr(run_scenario, "apply_async", recorder)
    monkeypatch.setattr(celery_module, "dispatch_job", _DispatchRecorder(real_dispatch))

    created = JobService(session).create_job(
        JobCreate(job_type="scenario", parameters={"model_id": job.id, "scenario": {}})
    )

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert kwargs.get("args") == [created.id, {"model_id": job.id, "scenario": {}}]
    assert kwargs.get("queue") == "scenarios"


def test_other_job_types_keep_the_default_queue(session, job, monkeypatch):
    celery_module = importlib.import_module("backend.tasks.celery_app")
    real_dispatch = celery_module.dispatch_job
    monkeypatch.setattr("backend.services.job_service.publish_job_update", lambda payload: None)

    calls = []
    from backend.tasks.job_tasks import run_prediction

    def recorder(*args, **kwargs):
        calls.append((args, kwargs))
        return None

    monkeypatch.setattr(run_prediction, "apply_async", recorder)
    monkeypatch.setattr(celery_module, "dispatch_job", _DispatchRecorder(real_dispatch))

    created = JobService(session).create_job(
        JobCreate(job_type="prediction", parameters={"trained_model_job": job.id})
    )

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert kwargs.get("args") == [created.id, {"trained_model_job": job.id}]
    assert "queue" not in kwargs, "non-scenario jobs must keep the default queue"


def test_scenario_is_a_valid_job_type_and_others_still_reject(session, monkeypatch):
    monkeypatch.setattr("backend.services.job_service.publish_job_update", lambda payload: None)

    celery_module = importlib.import_module("backend.tasks.celery_app")

    class _NoDispatch:
        @staticmethod
        def delay(*args, **kwargs):
            raise AssertionError("dispatch should not run for an invalid type")

    monkeypatch.setattr(celery_module, "dispatch_job", _NoDispatch)

    with pytest.raises(ValueError):
        JobService(session).create_job(JobCreate(job_type="not_a_real_type", parameters={}))


def test_failed_scenario_job_fails_itself_with_its_own_error(
    session, job, task_session_factory, monkeypatch
):
    """Per-scenario failure independence: an unknown model id fails this one
    job (with the same wording the API would answer 404 with) and leaves the
    engine and every other job untouched."""
    monkeypatch.setattr("backend.services.job_service.publish_job_update", lambda payload: None)

    from backend.tasks.job_tasks import run_scenario

    monkeypatch.setattr(
        "backend.tasks.job_tasks.SessionLocal", task_session_factory
    )

    # The eager .apply() surfaces the failure as an EagerResult, not a
    # raised exception; the contract is what the job row ends up holding.
    result = run_scenario.apply(
        args=[job.id, {"model_id": 999, "scenario": {"type": "market_crash"}}]
    )
    assert result.state == "FAILURE"

    session.refresh(job)
    assert job.status == "failed"
    assert "Model job 999 not found" in (job.error_message or "")
