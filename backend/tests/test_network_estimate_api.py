"""Tests for ``POST /api/v1/network/estimate``.

The endpoint turns declared aggregate marginals into an estimated bilateral
network with uncertainty-propagated clearing bands. Three properties are
guarded here:

1. The response is honest about provenance: ``status: "estimated"``, the
   estimator's uncertainty caveat, and an explicit ``persistence:
   "not_stored"`` -- and the exposure store really is untouched afterwards
   (``GET /graph`` still reports unavailable).
2. Declaration violations are typed 422s, never repaired: fewer than two
   institutions, negative totals, non-finite values, out-of-range shock
   fractions and unknown payload keys.
3. The bands are reproducible: the same seed returns the same numbers,
   because an uncertainty band nobody can reproduce is an anecdote.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Must be set before the application is imported: the lifespan builds the
# database. `setdefault` leaves other modules' configuration alone when they
# imported first.
os.environ.setdefault("USE_SQLITE", "true")
os.environ.setdefault(
    "DATABASE_URL",
    f"sqlite:///{Path(__file__).resolve().parent / 'test_network_estimate_api.sqlite3'}",
)

from fastapi.testclient import TestClient  # noqa: E402

from backend.api.main import app  # noqa: E402
from backend.api.routes.network import get_bilateral_exposure_store  # noqa: E402
from backend.services.bilateral_exposure_store import (  # noqa: E402
    BilateralExposureStore,
)

ESTIMATE_URL = "/api/v1/network/estimate"
GRAPH_URL = "/api/v1/network/graph"

PAYLOAD = {
    "interbank_assets": {"BANK_A": 60.0, "BANK_B": 30.0, "BANK_C": 10.0},
    "interbank_liabilities": {"BANK_A": 40.0, "BANK_B": 35.0, "BANK_C": 25.0},
    "endowment_ratio": 0.1,
    "shocks": {"BANK_C": 0.5},
    "n_draws": 8,
    "seed": 7,
}


@pytest.fixture(scope="session")
def client():
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def store(tmp_path):
    return BilateralExposureStore(tmp_path / "bilateral_exposures")


@pytest.fixture()
def api(client, store):
    app.dependency_overrides[get_bilateral_exposure_store] = lambda: store
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_bilateral_exposure_store, None)


def test_estimate_returns_bands_with_provenance(api):
    response = api.post(ESTIMATE_URL, json=PAYLOAD)
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "estimated"
    assert payload["source"] == "estimated_from_declared_marginals"
    assert payload["persistence"] == "not_stored"
    assert "prior" in payload["uncertainty"]

    clearing = payload["clearing"]
    assert clearing["n_draws"] == 8
    assert clearing["shocks"] == {"BANK_C": 0.5}
    bands = clearing["bands"]["total_shortfall"]
    assert bands["p5"] <= bands["p50"] <= bands["p95"]
    assert clearing["point"]["total_shortfall"] > 0

    bounds = payload["bounds"]
    assert bounds["maximum_entropy"]["method"] == "maximum_entropy_ras"
    assert bounds["minimum_density"]["method"] == "minimum_density_greedy"
    # the concentrated corner is never denser than the dense one
    assert bounds["minimum_density"]["n_links"] <= bounds["maximum_entropy"]["n_links"]
    assert payload["marginals"]["n_institutions"] == 3
    assert payload["marginals"]["marginal_mismatch"] == 0.0


def test_estimate_never_writes_to_the_exposure_store(api):
    response = api.post(ESTIMATE_URL, json=PAYLOAD)
    assert response.status_code == 200
    graph = api.get(GRAPH_URL).json()
    assert graph["status"] == "unavailable"
    assert graph["nodes"] == []


def test_same_seed_reproduces_same_bands(api):
    first = api.post(ESTIMATE_URL, json=PAYLOAD).json()
    second = api.post(ESTIMATE_URL, json=PAYLOAD).json()
    assert first["clearing"]["bands"] == second["clearing"]["bands"]


def test_min_density_can_be_excluded(api):
    payload = {**PAYLOAD, "include_min_density": False}
    response = api.post(ESTIMATE_URL, json=payload)
    assert response.status_code == 200
    assert list(response.json()["bounds"].keys()) == ["maximum_entropy"]


@pytest.mark.parametrize(
    "mutation",
    [
        {"interbank_assets": {"BANK_A": 60.0}},  # a single institution
        {"interbank_assets": {"BANK_A": -1.0, "BANK_B": 10.0}},  # negative total
        {"interbank_assets": {"BANK_A": 0.0, "BANK_B": 0.0},
         "interbank_liabilities": {"BANK_A": 0.0, "BANK_B": 0.0}},  # nothing declared
        {"endowment_ratio": 1.5},  # buffer above obligations is not a ratio
        {"shocks": {"BANK_A": 1.5}},  # shock fraction outside [0, 1]
        {"n_draws": 0},  # no draws to propagate
        {"unexpected": True},  # unknown keys are refused, not ignored
    ],
)
def test_declaration_violations_are_refused(api, mutation):
    payload = {**PAYLOAD, **mutation}
    response = api.post(ESTIMATE_URL, json=payload)
    assert response.status_code == 422


def test_estimator_refusals_surface_as_422(api):
    # Schema-valid declarations the estimator itself refuses: a shock naming
    # an institution that declared no totals.
    payload = {**PAYLOAD, "shocks": {"BANK_GHOST": 0.5}}
    response = api.post(ESTIMATE_URL, json=payload)
    assert response.status_code == 422
    assert "unknown institutions" in str(response.json()["detail"])
