"""FastAPI smoke tests that run under SQLite without external services."""

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# Ensure tests use lightweight SQLite storage so they can run in CI containers.
TEST_DB_PATH = Path(__file__).resolve().parent / "test_api.sqlite3"

# Remove any stale database from previous runs to guarantee a clean slate.
if TEST_DB_PATH.exists():
    TEST_DB_PATH.unlink()

os.environ["USE_SQLITE"] = "true"
os.environ["DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"


try:
    from backend.database import SessionLocal  # noqa: E402
    from backend.models.data_catalogue import (  # noqa: E402
        DataCatalogueItem,
        DataCategory,
        DataRegion,
        RiskType,
    )
    from backend.models.data_source import DataSource  # noqa: E402
except ModuleNotFoundError:
    from database import SessionLocal  # type: ignore
    from models.data_catalogue import (  # type: ignore
        DataCatalogueItem,
        DataCategory,
        DataRegion,
        RiskType,
    )
    from models.data_source import DataSource  # type: ignore

try:
    from backend.api.main import app  # noqa: E402
except ModuleNotFoundError:
    from api.main import app  # type: ignore


def _seed_minimal_catalogue():
    """Seed a single datasource & catalogue item if the database is empty."""
    session = SessionLocal()
    try:
        if session.query(DataCatalogueItem).count() > 0:
            return

        source = DataSource(
            name="Test Source",
            plugin_type="custom_api",
            description="Synthetic data source for smoke tests",
            enabled=True,
            status="active",
            config={},
        )
        session.add(source)
        session.commit()
        session.refresh(source)

        session.add(
            DataCatalogueItem(
                code="TEST_SERIES",
                name="Test Series",
                description="Synthetic catalogue entry for API smoke testing",
                category=DataCategory.EXCHANGE_RATES,
                region=DataRegion.NORTH_AMERICA,
                risk_types=[RiskType.MARKET_LIQUIDITY.value],
                data_source_id=source.id,
                endpoint="test/series",
                frequency="daily",
                granularity="macro",
                unit="index",
                enabled=True,
                default_selected=True,
                priority=1,
                parameters={"country_codes": ["USA"]},
            )
        )
        session.commit()
    finally:
        session.close()


@pytest.fixture(scope="session")
def client():
    """Yield a TestClient with FastAPI lifespan events executed once."""

    with TestClient(app) as test_client:
        _seed_minimal_catalogue()
        yield test_client


def test_suite_engine_is_the_shared_sqlite_file():
    """Pin the conftest invariant at the place a violation can be named.

    If this fails, some module imported ``backend.database`` before
    ``conftest.py`` pinned ``USE_SQLITE`` (or the pin was removed), which
    means the process-global engine is bound to whatever that module's
    environment said -- and failures will surface two dozen modules away as
    "no such table", as they did when test_alert_evaluator became the first
    importer. See the conftest comment for the full story.
    """
    try:
        from backend.database import engine
    except ModuleNotFoundError:
        from database import engine  # type: ignore

    url = str(engine.url)
    assert url.startswith("sqlite"), f"suite engine is not SQLite: {url}"
    assert url.endswith("beacon.db"), (
        f"suite engine is bound to {url!r}, not the shared ./beacon.db; "
        "a module imported backend.database before conftest pinned the env"
    )


def test_health_endpoint(client):
    response = client.get("/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "healthy"


def test_root_endpoint(client):
    response = client.get("/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["name"].startswith("BEACON API")


def test_catalogue_endpoint_returns_items(client):
    response = client.get("/api/v1/catalogue")
    assert response.status_code == 200
    items = response.json()
    assert isinstance(items, list)
    assert items, "Catalogue should contain seeded items"


def test_catalogue_country_filter_succeeds(client):
    response = client.get("/api/v1/catalogue", params={"countries": "USA"})
    assert response.status_code == 200
    assert isinstance(response.json(), list)
