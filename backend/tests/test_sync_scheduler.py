"""Per-source collection scheduling: due maths, backoff, enqueueing, health.

The scheduler is the clock side of data connectivity, so the things that must
never silently change are asserted here:

* a null interval means manual-only -- the absence of a schedule is a
  decision, not a default waiting to be invented;
* failure doubles the interval (capped), and one success ends the backoff;
* jitter is stable per source, so ``next_due_at`` is readable in the health
  payload and a restart does not reshuffle the fleet;
* the scheduler enqueues the same job a human does (``data_collection`` with
  ``data_source_id``), and never queues behind an open collection;
* ``Sync Now`` queues a real collection instead of stamping a timestamp, and
  the probe route tests the saved config with environment keys injected.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

# No private DATABASE_URL here: conftest.py pins USE_SQLITE=true suite-wide,
# and backend.database under that flag ignores DATABASE_URL and binds the
# shared on-disk ``./beacon.db`` -- which conftest also deletes at session
# start, so every run begins cold. Isolation inside a run comes from the
# fixtures below, not from a private file that would never be opened.

from fastapi.testclient import TestClient  # noqa: E402

from backend.api.main import app  # noqa: E402
from backend.database import SessionLocal, init_db  # noqa: E402
from backend.models.data_catalogue import DataCatalogueItem  # noqa: E402
from backend.models.data_source import DataSource  # noqa: E402
from backend.models.job import Job  # noqa: E402
from backend.services import scheduling  # noqa: E402
from backend.tasks.schedule_tasks import dispatch_due_collections  # noqa: E402

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def db():
    init_db()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def _source(db, name, **kwargs) -> DataSource:
    kwargs.setdefault("plugin_type", "csv")
    kwargs.setdefault("config", {})
    kwargs.setdefault("enabled", True)
    kwargs.setdefault("created_at", NOW - timedelta(days=30))
    source = DataSource(name=name, **kwargs)
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


# ---------------------------------------------------------------------------
# due maths
# ---------------------------------------------------------------------------


def test_manual_source_is_never_due(db):
    source = _source(db, "manual-feed", sync_interval_minutes=None)
    assert scheduling.next_due_at(source, NOW) is None
    source.last_sync_started_at = NOW - timedelta(days=3)
    assert scheduling.due_sources(db, NOW) == []


def test_disabled_source_is_never_due(db):
    source = _source(
        db, "disabled-feed", enabled=False, sync_interval_minutes=60
    )
    assert scheduling.next_due_at(source, NOW) is None


def test_due_date_anchors_on_last_start_with_jitter(db):
    source = _source(
        db, "hourly-feed",
        sync_interval_minutes=60,
        last_sync_started_at=NOW - timedelta(minutes=30),
    )
    due = scheduling.next_due_at(source, NOW)
    jitter = scheduling.jitter_seconds(source.id, 60)
    # SQLite returns tz-naive stamps; next_due_at normalises to UTC.
    anchor = scheduling._as_utc(source.last_sync_started_at)
    assert due == anchor + timedelta(minutes=60, seconds=jitter)
    # jitter is a stable function of the source, not of the clock
    assert scheduling.jitter_seconds(source.id, 60) == jitter
    assert 0 <= jitter <= 60 * 60 * scheduling.JITTER_FRACTION


def test_backoff_doubles_per_failure_and_caps(db):
    source = _source(
        db, "failing-feed",
        sync_interval_minutes=60,
        last_sync_started_at=NOW - timedelta(hours=4),
    )
    healthy = scheduling.next_due_at(source, NOW)
    # four hours since the last start on an hourly cadence: overdue even
    # with the worst-case jitter added.
    assert healthy < NOW

    source.consecutive_failures = 1
    db.commit()
    once = scheduling.next_due_at(source, NOW)
    assert once == scheduling._as_utc(source.last_sync_started_at) + timedelta(
        minutes=120, seconds=scheduling.jitter_seconds(source.id, 60)
    )

    source.consecutive_failures = 9
    db.commit()
    capped = scheduling.next_due_at(source, NOW)
    assert scheduling.backoff_factor(9) == scheduling.MAX_BACKOFF_FACTOR
    assert capped == scheduling._as_utc(source.last_sync_started_at) + timedelta(
        minutes=60 * scheduling.MAX_BACKOFF_FACTOR,
        seconds=scheduling.jitter_seconds(source.id, 60),
    )


def test_success_clears_the_backoff(db):
    source = _source(db, "recovering-feed", sync_interval_minutes=60, consecutive_failures=4)
    scheduling.record_sync_success(db, source.id, NOW - timedelta(minutes=2), rows=17)
    db.refresh(source)
    assert source.consecutive_failures == 0
    assert source.last_sync_rows == 17
    assert source.last_successful_fetch is not None
    assert scheduling.backoff_factor(source.consecutive_failures) == 1


def test_degraded_success_delivers_data_but_keeps_the_backoff(db):
    """A cache-served success is not evidence of provider health (F9).

    The data reached the pipeline, so duration/rows/last_successful_fetch are
    stamped and the source stays active -- but the failure streak *is* the
    backoff, and the stale fallback exists precisely because the provider
    was unreachable, so the streak (and a note beside the source) must
    survive until a genuinely fresh success.
    """
    source = _source(db, "degraded-feed", sync_interval_minutes=60, consecutive_failures=3)
    scheduling.record_sync_success(
        db, source.id, NOW - timedelta(minutes=2), rows=17, degraded=True
    )
    db.refresh(source)
    assert source.last_successful_fetch is not None
    assert source.last_sync_rows == 17
    assert source.status == "active"
    assert source.consecutive_failures == 3  # the backoff stays
    assert "stale cache" in source.error_message

    # a fresh success clears both the streak and the note
    scheduling.record_sync_success(db, source.id, NOW - timedelta(minutes=1), rows=20)
    db.refresh(source)
    assert source.consecutive_failures == 0
    assert source.error_message is None
    assert source.last_sync_rows == 20


def test_failure_grows_the_streak(db):
    source = _source(db, "streak-feed", sync_interval_minutes=60)
    scheduling.record_sync_failure(db, source.id, "connection reset")
    scheduling.record_sync_failure(db, source.id, "connection reset")
    db.refresh(source)
    assert source.consecutive_failures == 2
    assert source.status == "error"
    assert source.error_message == "connection reset"


# ---------------------------------------------------------------------------
# enqueueing
# ---------------------------------------------------------------------------


def test_enqueue_creates_the_same_job_a_human_does(db):
    source = _source(db, "enqueue-feed", sync_interval_minutes=15)

    # Stated, not assumed: every assertion below holds only if the source id
    # this test was just handed is fresh. A module that deletes DataSource rows
    # without the rows pointing at them frees ids for reuse, and this test then
    # fails as if the scheduler had selected the wrong series. Name the state
    # problem here, where a reader can see it, instead of letting it read as a
    # product bug two modules from its cause.
    stale_items = (
        db.query(DataCatalogueItem.id)
        .filter(DataCatalogueItem.data_source_id == source.id)
        .all()
    )
    assert stale_items == [], (
        f"source id {source.id} is not fresh: catalogue items {stale_items} point "
        "at a source an earlier module deleted without them"
    )

    item = DataCatalogueItem(
        code="ENQ-1",
        name="Enqueue series",
        data_source_id=source.id,
        enabled=True,
        default_selected=True,
        category="economic_indicators",
        region="global",
    )
    db.add(item)
    db.commit()

    before = db.query(Job).count()
    job = scheduling.enqueue_collection(db, source, origin="schedule")
    assert job.job_type == "data_collection"
    assert job.parameters["data_source_id"] == source.id
    assert job.parameters["catalogue_items"] == [item.id]
    assert job.parameters["origin"] == "schedule"
    assert db.query(Job).count() == before + 1
    db.refresh(source)
    assert source.last_sync_started_at is not None


def test_open_collection_blocks_a_second_enqueue(db):
    source = _source(db, "busy-feed", sync_interval_minutes=15)
    open_job = Job(
        job_type="data_collection",
        status="running",
        parameters={"data_source_id": source.id, "catalogue_items": []},
    )
    db.add(open_job)
    db.commit()
    assert scheduling.has_open_collection(db, source.id) is True

    source.sync_interval_minutes = 15
    source.last_sync_started_at = NOW - timedelta(hours=1)
    db.commit()
    assert source in scheduling.due_sources(db, NOW)

    tick = dispatch_due_collections()
    assert tick["due"] >= 1
    assert tick["skipped_open"] >= 1
    assert job_ids_exclude(db, open_job.id, tick["enqueued"])


def job_ids_exclude(db, blocked_id, enqueued) -> bool:
    return blocked_id not in enqueued


# ---------------------------------------------------------------------------
# routes
# ---------------------------------------------------------------------------


def test_health_payload_describes_cadence_and_outcome(db):
    source = _source(
        db,
        "health-feed",
        sync_interval_minutes=60,
        last_sync_started_at=NOW - timedelta(hours=5),
        consecutive_failures=2,
    )
    client = TestClient(app)
    response = client.get("/api/v1/data-sources/health")
    assert response.status_code == 200
    row = next(s for s in response.json()["sources"] if s["id"] == source.id)
    assert row["scheduled"] is True
    assert row["sync_interval_minutes"] == 60
    assert row["consecutive_failures"] == 2
    assert row["backoff_factor"] == 4
    assert row["overdue"] is True
    assert row["next_due_at"] is not None
    assert row["collection_running"] is False


def test_sync_queues_a_real_collection(db):
    source = _source(db, "sync-now-feed", sync_interval_minutes=None)
    client = TestClient(app)
    response = client.post(f"/api/v1/data-sources/{source.id}/sync")
    assert response.status_code == 202
    job = response.json()
    assert job["job_type"] == "data_collection"
    assert job["parameters"]["data_source_id"] == source.id
    assert job["parameters"]["origin"] == "manual"


def test_sync_conflicts_while_a_collection_is_open(db):
    source = _source(db, "sync-busy-feed")
    db.add(
        Job(
            job_type="data_collection",
            status="pending",
            parameters={"data_source_id": source.id, "catalogue_items": []},
        )
    )
    db.commit()
    client = TestClient(app)
    response = client.post(f"/api/v1/data-sources/{source.id}/sync")
    assert response.status_code == 409


def test_sync_rejects_disabled_source(db):
    source = _source(db, "sync-disabled-feed", enabled=False)
    client = TestClient(app)
    assert client.post(f"/api/v1/data-sources/{source.id}/sync").status_code == 409


def test_probe_uses_saved_config_with_env_keys(db, monkeypatch):
    source = _source(db, "probe-feed", config={"timeout": 5})
    seen = {}

    class Double:
        def __init__(self, config):
            seen["config"] = config

        def test_connection(self):
            return {"success": True, "message": "reachable", "details": {"rows": 1}}

    monkeypatch.setenv("FRED_API_KEY", "")  # csv has no env var; keep env clean
    monkeypatch.setattr(
        "backend.plugins.base.get_plugin", lambda plugin_type: Double
    )
    client = TestClient(app)
    response = client.post(f"/api/v1/data-sources/{source.id}/probe")
    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    # the service rewords a successful probe into its own user-facing
    # sentence; the double's own message is not the contract.
    assert body["message"]
    assert seen["config"] == {"timeout": 5}


def test_probe_injects_environment_key_like_the_collector(db, monkeypatch):
    source = _source(db, "probe-keyed-feed", plugin_type="fred", config={})
    seen = {}

    class Double:
        def __init__(self, config):
            seen["config"] = config

        def test_connection(self):
            return {"success": True, "message": "ok"}

    monkeypatch.setenv("FRED_API_KEY", "from-env")
    monkeypatch.setattr("backend.plugins.base.get_plugin", lambda plugin_type: Double)
    client = TestClient(app)
    assert client.post(f"/api/v1/data-sources/{source.id}/probe").status_code == 200
    assert seen["config"]["api_key"] == "from-env"
