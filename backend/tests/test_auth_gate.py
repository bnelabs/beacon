"""The optional bearer-token gate (P4) must be closed by default and exact when set.

BEACON ships single-operator and unauthenticated; deployments that need
multi-tenant hygiene set BEACON_API_TOKEN. The gate therefore has three
contracts: absent token changes nothing; present token refuses every /api/*
call without a matching bearer header (constant-time comparison); and the
discovery surfaces (docs/openapi/health) stay open so the gate is
discoverable rather than a brick wall.
"""

from __future__ import annotations

import os

import pytest


@pytest.fixture()
def client(monkeypatch):
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


class TestGateDefault:
    def test_no_token_means_no_gate(self, client, monkeypatch):
        monkeypatch.delenv("BEACON_API_TOKEN", raising=False)
        response = client.get("/api/v1/jobs")
        assert response.status_code != 401


class TestGateActive:
    def test_api_refused_without_header(self, client, monkeypatch):
        monkeypatch.setenv("BEACON_API_TOKEN", "drill-token")
        assert client.get("/api/v1/jobs").status_code == 401

    def test_api_refused_with_wrong_token(self, client, monkeypatch):
        monkeypatch.setenv("BEACON_API_TOKEN", "drill-token")
        response = client.get("/api/v1/jobs", headers={"Authorization": "Bearer nope"})
        assert response.status_code == 401

    def test_api_accepted_with_token(self, client, monkeypatch):
        monkeypatch.setenv("BEACON_API_TOKEN", "drill-token")
        response = client.get("/api/v1/jobs", headers={"Authorization": "Bearer drill-token"})
        assert response.status_code != 401

    def test_discovery_surfaces_stay_open(self, client, monkeypatch):
        monkeypatch.setenv("BEACON_API_TOKEN", "drill-token")
        assert client.get("/openapi.json").status_code == 200
        assert client.get("/docs").status_code == 200
