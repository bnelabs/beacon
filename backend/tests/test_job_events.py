"""Tests for the cross-process job-update bus and its call sites.

These guard a defect that shipped silently: the job WebSocket was reachable and
answered its handshake, but nothing ever published a ``job_update``, so "live
updates" never happened. Two separate things were missing — a publisher, and a
transport that could reach the API process from the Celery worker — and neither
had a test.

Everything here runs without a Redis server. The bus is exercised against fakes
that mimic the two behaviours that matter: delivering a message, and being
unavailable.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

# Set before importing anything that builds the engine: the WebSocket test drives
# the real application, whose lifespan initialises the database. `setdefault`
# leaves test_api_smoke.py's configuration alone when it imported first.
os.environ.setdefault("USE_SQLITE", "true")
os.environ.setdefault(
    "DATABASE_URL",
    f"sqlite:///{Path(__file__).resolve().parent / 'test_job_events.sqlite3'}",
)

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.api import job_events
from backend.api.job_events import (
    JOB_UPDATES_CHANNEL,
    job_payload,
    publish_job_update,
    relay_job_updates,
)
from backend.database import Base
from backend.models.job import Job
from backend.services.job_service import JobService


@pytest.fixture()
def session():
    """A throwaway SQLite session holding the real ``jobs`` table."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=[Job.__table__])
    db = sessionmaker(bind=engine)()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


@pytest.fixture()
def job(session):
    record = Job(job_type="training", status="running", progress=42.5, current_step="fitting")
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


@pytest.fixture(autouse=True)
def _no_shared_publish_client(monkeypatch):
    """Keep the module-level Redis client out of every test.

    ``publish_job_update`` caches a client in a module global; without this a
    fake injected by one test would leak into the next.
    """
    monkeypatch.setattr(job_events, "_publish_client", None, raising=False)


class _RecordingClient:
    def __init__(self):
        self.published = []

    def publish(self, channel, payload):
        self.published.append((channel, payload))
        return 1


class _BrokenClient:
    def publish(self, channel, payload):
        raise ConnectionError("redis is not reachable")


class TestJobPayload:
    """The payload is what a browser receives, so its keys are a public contract."""

    def test_carries_both_id_keys(self, job):
        # The client keys one React Query cache by `job_id` and looks the other
        # up by either, so both must be present.
        payload = job_payload(job)
        assert payload["id"] == job.id
        assert payload["job_id"] == job.id

    def test_exposes_the_current_state(self, job):
        payload = job_payload(job)
        assert payload["job_type"] == "training"
        assert payload["status"] == "running"
        assert payload["progress"] == 42.5
        assert payload["current_step"] == "fitting"

    def test_omits_fields_that_are_not_columns(self, job):
        # The serializer this replaced emitted `model_id` and `config`. Neither is
        # a column on Job, so it would have raised AttributeError on first use —
        # which nobody saw, because nothing ever called it.
        payload = job_payload(job)
        assert "model_id" not in payload
        assert "config" not in payload

    def test_every_key_is_a_real_column_or_a_known_alias(self, job):
        columns = {c.name for c in Job.__table__.columns}
        aliases = {"job_id", "error"}  # renamed, not invented
        assert set(job_payload(job)) <= columns | aliases

    def test_timestamps_are_iso_strings(self, job):
        payload = job_payload(job)
        assert isinstance(payload["created_at"], str)
        assert payload["created_at"].startswith(str(job.created_at.year))

    def test_unset_timestamps_stay_none(self, session):
        record = Job(job_type="prediction", status="pending")
        session.add(record)
        session.commit()
        session.refresh(record)
        payload = job_payload(record)
        assert payload["started_at"] is None
        assert payload["completed_at"] is None


class TestPublishJobUpdate:
    def test_publishes_to_the_job_channel(self, monkeypatch):
        client = _RecordingClient()
        monkeypatch.setattr(job_events, "_get_publish_client", lambda: client)

        assert publish_job_update({"job_id": 7}) is True
        channel, raw = client.published[0]
        assert channel == JOB_UPDATES_CHANNEL
        assert json.loads(raw)["job_id"] == 7

    def test_a_redis_outage_is_reported_not_raised(self, monkeypatch):
        # A job must never fail because its progress could not be announced.
        monkeypatch.setattr(job_events, "_get_publish_client", lambda: _BrokenClient())
        assert publish_job_update({"job_id": 7}) is False

    def test_an_unserialisable_payload_does_not_raise(self, monkeypatch):
        monkeypatch.setattr(job_events, "_get_publish_client", lambda: _RecordingClient())

        class Opaque:
            pass

        # `default=str` is what keeps this on the wire rather than exploding.
        assert publish_job_update({"job_id": 7, "blob": Opaque()}) is True


class _FakePubSub:
    def __init__(self, messages, *, fail_first_subscribe=False):
        self._messages = list(messages)
        self._fail_first = fail_first_subscribe
        self.subscribe_calls = 0
        self.subscribed_to = None

    async def subscribe(self, channel):
        self.subscribe_calls += 1
        if self._fail_first and self.subscribe_calls == 1:
            raise ConnectionError("subscription lost")
        self.subscribed_to = channel

    async def listen(self):
        for message in self._messages:
            yield message
        # A real subscription stays open indefinitely; block so the relay's retry
        # loop does not spin through these messages over and over.
        await asyncio.Event().wait()

    async def aclose(self):
        pass


class _FakeAsyncRedis:
    def __init__(self, pubsub):
        self.pubsub_instance = pubsub

    def pubsub(self):
        return self.pubsub_instance

    async def aclose(self):
        pass


def _install_fake_redis(monkeypatch, pubsub):
    import redis.asyncio as aioredis

    monkeypatch.setattr(aioredis, "from_url", lambda *a, **k: _FakeAsyncRedis(pubsub))
    # Keep the retry path fast so a test does not sleep for the real backoff.
    monkeypatch.setattr(job_events, "RECONNECT_DELAY_SECONDS", 0.01)


async def _drain(task, received, expected=1, timeout=2.0):
    """Wait until ``expected`` messages arrive, then stop the relay."""
    deadline = asyncio.get_running_loop().time() + timeout
    while len(received) < expected and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.01)
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass


class TestRelayJobUpdates:
    def test_fans_a_published_payload_out_to_clients(self, monkeypatch):
        async def scenario():
            received = []

            async def broadcast(message):
                received.append(message)

            pubsub = _FakePubSub([
                {"type": "message", "data": json.dumps({"job_id": 11, "progress": 70.0})}
            ])
            _install_fake_redis(monkeypatch, pubsub)

            task = asyncio.create_task(relay_job_updates(broadcast))
            await _drain(task, received)
            return received, pubsub

        received, pubsub = asyncio.run(scenario())

        assert pubsub.subscribed_to == JOB_UPDATES_CHANNEL
        assert received[0]["type"] == "job_update"
        assert received[0]["job"]["job_id"] == 11
        assert received[0]["job"]["progress"] == 70.0

    def test_ignores_subscription_confirmations(self, monkeypatch):
        async def scenario():
            received = []

            async def broadcast(message):
                received.append(message)

            pubsub = _FakePubSub([
                {"type": "subscribe", "data": JOB_UPDATES_CHANNEL},
                {"type": "message", "data": json.dumps({"job_id": 12})},
            ])
            _install_fake_redis(monkeypatch, pubsub)

            task = asyncio.create_task(relay_job_updates(broadcast))
            await _drain(task, received)
            return received

        received = asyncio.run(scenario())
        assert len(received) == 1
        assert received[0]["job"]["job_id"] == 12

    def test_discards_a_malformed_payload_and_keeps_going(self, monkeypatch):
        async def scenario():
            received = []

            async def broadcast(message):
                received.append(message)

            pubsub = _FakePubSub([
                {"type": "message", "data": "{not json"},
                {"type": "message", "data": json.dumps({"job_id": 13})},
            ])
            _install_fake_redis(monkeypatch, pubsub)

            task = asyncio.create_task(relay_job_updates(broadcast))
            await _drain(task, received)
            return received

        received = asyncio.run(scenario())
        assert [m["job"]["job_id"] for m in received] == [13]

    def test_recovers_from_a_lost_subscription(self, monkeypatch):
        async def scenario():
            received = []

            async def broadcast(message):
                received.append(message)

            pubsub = _FakePubSub(
                [{"type": "message", "data": json.dumps({"job_id": 14})}],
                fail_first_subscribe=True,
            )
            _install_fake_redis(monkeypatch, pubsub)

            task = asyncio.create_task(relay_job_updates(broadcast))
            await _drain(task, received)
            return received, pubsub

        received, pubsub = asyncio.run(scenario())
        # The first subscribe raised, so a retry is what made delivery possible.
        assert pubsub.subscribe_calls >= 2
        assert received[0]["job"]["job_id"] == 14


class TestJobServicePublishes:
    """Every status change passes through JobService, in both processes."""

    @staticmethod
    def _patch_dispatch(monkeypatch, replacement):
        """Replace the real ``dispatch_job`` on its own module.

        ``backend/tasks/__init__.py`` rebinds the name ``celery_app`` to the
        Celery *instance*, which shadows the submodule of the same name. A dotted
        monkeypatch target of ``backend.tasks.celery_app`` therefore resolves to
        the task registry, not the module, and fails with a confusing
        AttributeError. Importing the module explicitly avoids that.
        """
        import importlib

        module = importlib.import_module("backend.tasks.celery_app")
        monkeypatch.setattr(module, "dispatch_job", replacement)

    def test_update_job_status_publishes_the_committed_state(self, session, job, monkeypatch):
        sent = []
        monkeypatch.setattr(
            "backend.services.job_service.publish_job_update", lambda payload: sent.append(payload)
        )

        JobService(session).update_job_status(job.id, status="completed", progress=100.0)

        assert len(sent) == 1
        assert sent[0]["status"] == "completed"
        assert sent[0]["progress"] == 100.0

    def test_update_job_status_publishes_nothing_for_an_unknown_job(self, session, monkeypatch):
        sent = []
        monkeypatch.setattr(
            "backend.services.job_service.publish_job_update", lambda payload: sent.append(payload)
        )

        assert JobService(session).update_job_status(999_999, status="running") is None
        assert sent == []

    def test_cancel_job_publishes(self, session, job, monkeypatch):
        sent = []
        monkeypatch.setattr(
            "backend.services.job_service.publish_job_update", lambda payload: sent.append(payload)
        )

        assert JobService(session).cancel_job(job.id) is True
        assert sent[0]["status"] == "failed"
        assert "cancelled" in sent[0]["error"].lower()

    def test_create_job_publishes_even_when_dispatch_fails(self, session, monkeypatch):
        """A broker outage still has to reach the UI, as a failed job."""
        sent = []
        monkeypatch.setattr(
            "backend.services.job_service.publish_job_update", lambda payload: sent.append(payload)
        )

        class _Boom:
            @staticmethod
            def delay(*args, **kwargs):
                raise RuntimeError("broker down")

        TestJobServicePublishes._patch_dispatch(monkeypatch, _Boom)

        from backend.schemas.job import JobCreate

        JobService(session).create_job(JobCreate(job_type="data_collection", parameters={}))

        assert len(sent) == 1
        assert sent[0]["status"] == "failed"

    def test_create_job_publishes_the_dispatched_job(self, session, monkeypatch):
        sent = []
        monkeypatch.setattr(
            "backend.services.job_service.publish_job_update", lambda payload: sent.append(payload)
        )

        class _Handle:
            id = "celery-abc"

        class _Ok:
            @staticmethod
            def delay(*args, **kwargs):
                return _Handle()

        TestJobServicePublishes._patch_dispatch(monkeypatch, _Ok)

        from backend.schemas.job import JobCreate

        created = JobService(session).create_job(
            JobCreate(job_type="training", parameters={"x": 1})
        )

        assert sent[0]["job_id"] == created.id
        assert sent[0]["status"] == "pending"


class TestWebSocketEndpoint:
    """The socket itself: it must still accept and greet a client."""

    def test_handshake_sends_connected(self):
        from fastapi.testclient import TestClient

        from backend.api.main import app

        with TestClient(app) as client:
            with client.websocket_connect("/api/v1/jobs/ws") as ws:
                message = ws.receive_json()
                assert message["type"] == "connected"

    def test_ping_is_answered_with_pong(self):
        from fastapi.testclient import TestClient

        from backend.api.main import app

        with TestClient(app) as client:
            with client.websocket_connect("/api/v1/jobs/ws") as ws:
                ws.receive_json()  # the "connected" greeting
                ws.send_text("ping")
                assert ws.receive_json()["type"] == "pong"
