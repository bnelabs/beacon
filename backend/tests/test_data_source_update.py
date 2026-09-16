"""PUT /api/v1/data-sources/{id} must persist what the UI actually sends.

Regression coverage for a silent no-op: the ``DataSourceUpdate`` schema and
the service once disagreed with the edit form in three ways at once --

1. the service never applied ``sync_interval_minutes``, so the schedule
   dropdown (and with it the whole "put a feed on a schedule" flow the
   first-run checklist prompts and the Refresh Cadence panel displays)
   wrote nowhere while the API answered 200;
2. the schema lacked the disclosure metadata columns (``registration_url``,
   ``registration_required``, ``free_tier_limits``, ``coverage_description``),
   so Pydantic dropped whatever the form sent;
3. the frontend nested the whole form payload under a ``data`` key, which
   Pydantic dropped wholesale (fixed frontend-side; the flat body this test
   sends is the shape ``useUpdateDataSource`` produces).

The contract pinned here is ``exclude_unset``: keys absent from the body
leave stored values untouched; keys present are applied, and an explicit
null clears a nullable column (``sync_interval_minutes: null`` returns a
feed to manual-only).
"""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# Ensure tests use lightweight SQLite storage so they can run in CI containers.
TEST_DB_PATH = Path(__file__).resolve().parent / "test_data_source_update.sqlite3"

# Remove any stale database from previous runs to guarantee a clean slate.
if TEST_DB_PATH.exists():
    TEST_DB_PATH.unlink()

os.environ["USE_SQLITE"] = "true"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"


try:
    from backend.database import SessionLocal  # noqa: E402
    from backend.models.data_source import DataSource  # noqa: E402
except ModuleNotFoundError:
    from database import SessionLocal  # type: ignore
    from models.data_source import DataSource  # type: ignore

try:
    from backend.api.main import app  # noqa: E402
except ModuleNotFoundError:
    from api.main import app  # type: ignore


UPDATE_TEST_SOURCE_NAME = "Update Semantics Source"


@pytest.fixture(scope="module")
def client():
    """Yield a TestClient with FastAPI lifespan events executed once."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def source_id(client):
    """A fresh data source row per test, cleaned up afterwards."""
    session = SessionLocal()
    try:
        session.query(DataSource).filter(
            DataSource.name == UPDATE_TEST_SOURCE_NAME
        ).delete()
        session.commit()
        source = DataSource(
            name=UPDATE_TEST_SOURCE_NAME,
            plugin_type="custom_api",
            description="Row under test",
            enabled=True,
            status="active",
            config={"api_key": "demo"},
        )
        session.add(source)
        session.commit()
        session.refresh(source)
        yield source.id
        session.query(DataSource).filter(
            DataSource.name == UPDATE_TEST_SOURCE_NAME
        ).delete()
        session.commit()
    finally:
        session.close()


def _stored(source_id: int) -> DataSource:
    session = SessionLocal()
    try:
        return session.query(DataSource).filter(DataSource.id == source_id).one()
    finally:
        session.close()


def test_put_applies_sync_interval_minutes(client, source_id):
    """The schedule dropdown's body must reach the column it names."""
    response = client.put(
        f"/api/v1/data-sources/{source_id}",
        json={"sync_interval_minutes": 60},
    )
    assert response.status_code == 200
    assert _stored(source_id).sync_interval_minutes == 60

    # ...and the scheduler's health view agrees the feed is now scheduled.
    health = client.get("/api/v1/data-sources/health")
    assert health.status_code == 200
    row = next(
        (row for row in health.json()["sources"] if row["id"] == source_id),
        None,
    )
    assert row is not None and row["scheduled"] is True


def test_put_explicit_null_returns_feed_to_manual(client, source_id):
    """`sync_interval_minutes: null` is the UI's 'Manual only' option."""
    assert client.put(
        f"/api/v1/data-sources/{source_id}", json={"sync_interval_minutes": 60}
    ).status_code == 200
    response = client.put(
        f"/api/v1/data-sources/{source_id}", json={"sync_interval_minutes": None}
    )
    assert response.status_code == 200
    assert _stored(source_id).sync_interval_minutes is None


def test_put_persists_the_full_edit_form(client, source_id):
    """Every field the edit form collects is a field the API stores."""
    payload = {
        "name": "Renamed Source",
        "plugin_type": "fred",
        "description": "Edited description",
        "enabled": True,
        "registration_url": "https://fred.stlouisfed.org/docs/api/api_key.html",
        "registration_required": True,
        "free_tier_limits": "120 requests/minute",
        "coverage_description": "US macro series",
        "config": {"api_key": "edited"},
    }
    response = client.put(f"/api/v1/data-sources/{source_id}", json=payload)
    assert response.status_code == 200
    row = _stored(source_id)
    assert row.name == "Renamed Source"
    assert row.plugin_type == "fred"
    assert row.description == "Edited description"
    assert row.registration_url == payload["registration_url"]
    assert row.registration_required is True
    assert row.free_tier_limits == "120 requests/minute"
    assert row.coverage_description == "US macro series"
    assert row.config == {"api_key": "edited"}


def test_put_with_absent_keys_changes_nothing(client, source_id):
    """exclude_unset: an unrelated partial update cannot clobber the rest."""
    before = _stored(source_id)
    snapshot = {
        "name": before.name,
        "description": before.description,
        "config": dict(before.config or {}),
        "sync_interval_minutes": before.sync_interval_minutes,
    }

    response = client.put(f"/api/v1/data-sources/{source_id}", json={"enabled": True})
    assert response.status_code == 200

    after = _stored(source_id)
    assert after.name == snapshot["name"]
    assert after.description == snapshot["description"]
    assert dict(after.config or {}) == snapshot["config"]
    assert after.sync_interval_minutes == snapshot["sync_interval_minutes"]


def test_put_explicit_null_clears_nullable_text(client, source_id):
    """An emptied description in the form arrives as null and must clear."""
    response = client.put(
        f"/api/v1/data-sources/{source_id}", json={"description": None}
    )
    assert response.status_code == 200
    assert _stored(source_id).description is None


def test_put_rejects_impossible_cadence(client, source_id):
    """The schema's ge=5 guard survives the rewrite: sub-5-minute cadences 422."""
    response = client.put(
        f"/api/v1/data-sources/{source_id}", json={"sync_interval_minutes": 1}
    )
    assert response.status_code == 422
