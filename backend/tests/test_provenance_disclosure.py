"""Provenance disclosure: the curated table must cover the runtime registry.

The disclosure endpoint answers an auditor's question -- where does every
input come from, and what is inferred rather than observed? Two failure
modes are guarded:

1. A plugin registers at runtime with no curated provenance entry: it would
   be served as "undisclosed". The guard asserts the curated table and the
   registry match in both directions, so a new feed cannot ship without a
   publisher, a class and a "provides" statement.
2. The endpoint describes a hypothetical deployment instead of this one: a
   created data source must show up in the configured counts.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("USE_SQLITE", "true")
os.environ.setdefault(
    "DATABASE_URL",
    f"sqlite:///{Path(__file__).resolve().parent / 'test_provenance.sqlite3'}",
)

from fastapi.testclient import TestClient  # noqa: E402

from backend.api.main import app  # noqa: E402
from backend.modules.data.provenance import (  # noqa: E402
    CURATED_PROVENANCE,
    PROVENANCE_CLASSES,
)
from backend.plugins import list_plugins  # noqa: E402

DISCLOSURE_URL = "/api/v1/data-sources/disclosure"


def _production_plugin_types() -> set:
    """Registry keys whose plugin class lives in ``backend.plugins``.

    Other test modules (``test_data_governance``) register throwaway plugin
    doubles into the process-global registry at import time. The guard must
    survive that pollution without weakening: it filters by the *class's*
    module, so a real plugin file that forgot its provenance entry still
    fails, while a test double cannot.
    """
    from backend.plugins.base import get_plugin

    types = set()
    for info in list_plugins():
        cls = get_plugin(info["type"])
        if cls is not None and cls.__module__.startswith("backend.plugins."):
            types.add(info["type"])
    return types


class TestCuratedRegistry:
    def test_every_registered_plugin_is_disclosed(self):
        registered = _production_plugin_types()
        missing = registered - set(CURATED_PROVENANCE)
        assert not missing, (
            f"registered plugins without curated provenance: {sorted(missing)}; "
            "declare publisher, class and provides in provenance.py"
        )

    def test_no_curated_entry_without_a_plugin(self):
        registered = _production_plugin_types()
        stale = set(CURATED_PROVENANCE) - registered
        assert not stale, (
            f"curated provenance for unregistered plugin types: {sorted(stale)}; "
            "a disclosure entry for a feed that cannot run is a false claim"
        )

    def test_classes_are_from_the_declared_vocabulary(self):
        for plugin_type, record in CURATED_PROVENANCE.items():
            assert record.provenance_class in PROVENANCE_CLASSES, plugin_type
            assert record.publisher and record.provides, plugin_type


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


class TestDisclosureEndpoint:
    def test_payload_shape(self, client):
        response = client.get(DISCLOSURE_URL)
        assert response.status_code == 200
        payload = response.json()
        production = _production_plugin_types()
        # Test doubles registered by other modules may appear as
        # "undisclosed"; a *production* plugin may never.
        assert not [t for t in payload["undocumented_plugins"] if t in production]
        assert "synthetic_data" in payload["policy"]
        assert payload["provenance_classes"] == PROVENANCE_CLASSES
        assert payload["sources"], "a deployment with zero disclosed feeds cannot exist"
        for source in payload["sources"]:
            if source["plugin_type"] not in production:
                continue
            for key in (
                "plugin_type", "name", "publisher", "provenance_class",
                "provides", "access", "deployment",
            ):
                assert key in source, f"{source.get('plugin_type')} lacks {key}"
            assert source["provenance_class"] in PROVENANCE_CLASSES
            assert "free" in source["access"] and "key_required" in source["access"]
            assert "configured_sources" in source["deployment"]

    def test_inferred_inputs_disclose_the_estimated_network(self, client):
        payload = client.get(DISCLOSURE_URL).json()
        names = {entry["name"] for entry in payload["inferred_inputs"]}
        assert "bilateral_exposure_network" in names
        entry = next(
            e for e in payload["inferred_inputs"]
            if e["name"] == "bilateral_exposure_network"
        )
        assert entry["produced_by"] == "POST /api/v1/network/estimate"
        assert "not_stored" in entry["status"]
        assert "prior" in entry["caveat"]

    def test_created_source_appears_in_deployment_counts(self, client):
        import uuid

        from backend.database import SessionLocal
        from backend.models.data_source import DataSource

        name = f"provenance-test-fred-{uuid.uuid4().hex[:8]}"
        created = client.post(
            "/api/v1/data-sources",
            json={
                "name": name,
                "plugin_type": "fred",
                "config": {},
                "description": "created by test_provenance_disclosure",
            },
        )
        try:
            assert created.status_code in (200, 201), created.text
            payload = client.get(DISCLOSURE_URL).json()
            fred = next(
                s for s in payload["sources"] if s["plugin_type"] == "fred"
            )
            assert fred["deployment"]["configured_sources"] >= 1
            assert fred["deployment"]["enabled_sources"] >= 1
        finally:
            db = SessionLocal()
            try:
                db.query(DataSource).filter(DataSource.name == name).delete()
                db.commit()
            finally:
                db.close()

    def test_orphaned_configurations_are_disclosed_not_dropped(self, client):
        # A data source row whose plugin_type is not registered cannot be
        # created through the API (the service validates against the
        # registry), so the orphan path is exercised at the builder level.
        from backend.database import SessionLocal
        from backend.models.data_source import DataSource
        from backend.modules.data.provenance import build_disclosure

        db = SessionLocal()
        try:
            orphan = DataSource(
                name="provenance-test-orphan",
                plugin_type="ghost_plugin",
                config={},
                enabled=False,
            )
            db.add(orphan)
            db.commit()
            payload = build_disclosure(db)
        finally:
            db.query(DataSource).filter(
                DataSource.name == "provenance-test-orphan"
            ).delete()
            db.commit()
            db.close()
        orphans = {o["plugin_type"] for o in payload["orphaned_configurations"]}
        assert "ghost_plugin" in orphans
