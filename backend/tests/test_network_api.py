"""Tests for the dynamic network graph and the bilateral exposure upload API.

These guard three defects that would otherwise be invisible:

1. The risk map was drawn from a bundled JavaScript fixture, so "the network"
   was a constant that no upload could change. The graph endpoint must serve the
   matrix that was actually uploaded, and must say so explicitly when nothing
   has been.
2. An upload endpoint is a trust boundary. Every malformed, negative,
   self-referential, oversized or ambiguous payload must be refused with a typed
   error rather than repaired.
3. An upload that lands in a file the engine cannot read is not an upload. The
   last test proves the stored matrix reaches the clearing path through the same
   reader (`load_bank_exposures`) the engine consumes.
"""

from __future__ import annotations

import io
import os
from pathlib import Path

import pandas as pd
import pytest

# Must be set before the application is imported: the lifespan builds the
# database. `setdefault` leaves test_api_smoke.py's configuration alone when
# that module imported first.
os.environ.setdefault("USE_SQLITE", "true")
os.environ.setdefault(
    "DATABASE_URL",
    f"sqlite:///{Path(__file__).resolve().parent / 'test_network_api.sqlite3'}",
)

from fastapi.testclient import TestClient  # noqa: E402

from backend.api.main import app  # noqa: E402
from backend.api.routes.network import get_bilateral_exposure_store  # noqa: E402
from backend.modules.engine.multiplex import (  # noqa: E402
    build_interbank_exposure_layer,
    require_exposure,
)
from backend.modules.risk.clearing import clear_multiplex  # noqa: E402
from backend.services.bilateral_exposure_store import (  # noqa: E402
    BilateralExposureStore,
)

GRAPH_URL = "/api/v1/network/graph"
UPLOAD_URL = "/api/v1/network/exposures"

# Four rows, three distinct edges: BANK_A -> BANK_B appears twice and must be
# summed to 50 rather than rejected or silently dropped.
CSV_MATRIX = (
    b"debtor,creditor,amount\n"
    b"BANK_A,BANK_B,40\n"
    b"BANK_B,BANK_C,25\n"
    b"BANK_C,BANK_A,30\n"
    b"BANK_A,BANK_B,10\n"
)
EXPECTED_EXPOSURES = {
    ("BANK_A", "BANK_B"): 50.0,
    ("BANK_B", "BANK_C"): 25.0,
    ("BANK_C", "BANK_A"): 30.0,
}


@pytest.fixture(scope="session")
def client():
    """A TestClient with lifespan executed once for the module."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def store(tmp_path):
    """A store rooted in a temporary directory, empty at the start of a test."""
    return BilateralExposureStore(tmp_path / "bilateral_exposures")


@pytest.fixture()
def api(client, store):
    """The client wired to the throwaway store.

    The override is installed per test and removed afterwards so it cannot leak
    into any other module sharing the application object.
    """
    app.dependency_overrides[get_bilateral_exposure_store] = lambda: store
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_bilateral_exposure_store, None)


def _upload(api, body, *, fmt="csv", source="BANK_A", as_of=None, headers=None):
    params = {"source_institution": source, "format": fmt}
    if as_of is not None:
        params["as_of"] = as_of
    return api.post(UPLOAD_URL, params=params, content=body, headers=headers or {})


def _parquet_bytes(frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.to_parquet(buffer, engine="pyarrow", index=False)
    return buffer.getvalue()


# ---------------------------------------------------------------------------
# Graph endpoint
# ---------------------------------------------------------------------------


def test_graph_reports_explicit_unavailable_state(api):
    """No upload means "unavailable", not an empty network and not an error."""
    response = api.get(GRAPH_URL)
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "unavailable"
    assert payload["nodes"] == []
    assert payload["edges"] == []
    assert payload["layers"] == []
    assert payload["unavailable_reason"]
    assert payload["metadata"]["n_edges"] == 0


def test_upload_then_graph_serves_the_real_network(api):
    """The graph must reflect the uploaded obligations, deduplicated by pair."""
    upload = _upload(api, CSV_MATRIX, as_of="2024-06-30")
    assert upload.status_code == 201
    stored = upload.json()
    assert stored["status"] == "stored"
    assert stored["n_institutions"] == 3
    assert stored["n_edges"] == 3
    assert stored["gross_notional"] == 105.0
    assert stored["duplicate_edges_aggregated"] == 1
    assert ["BANK_A", "BANK_B"] in stored["duplicate_pairs"]
    assert stored["content_hash"].startswith("sha256:")

    graph = api.get(GRAPH_URL).json()
    assert graph["status"] == "available"
    assert graph["source"] == "bilateral_exposure_store"
    assert graph["as_of"].startswith("2024-06-30")
    assert {node["id"] for node in graph["nodes"]} == {"BANK_A", "BANK_B", "BANK_C"}
    edges = {(edge["source"], edge["target"]): edge["exposure"] for edge in graph["edges"]}
    assert edges == EXPECTED_EXPOSURES
    assert all(edge["kind"] == "exposure" for edge in graph["edges"])
    assert all(edge["is_clearing_eligible"] for edge in graph["edges"])
    assert graph["metadata"]["gross_notional"] == 105.0
    assert graph["metadata"]["content_hash"] == stored["content_hash"]
    assert graph["metadata"]["geography_resolution"] == "client_reference_data"
    # Risk is not derivable from an exposure matrix and must be reported absent.
    assert all(edge["risk_score"] is None for edge in graph["edges"])
    assert graph["metadata"]["risk_score_available"] is False


def test_graph_reflects_a_replacement_upload(api):
    """A second upload replaces the first; the graph is never a merge of both."""
    _upload(api, CSV_MATRIX, as_of="2024-06-30")
    replacement = b"debtor,creditor,amount\nX,Y,7\n"
    assert _upload(api, replacement, source="BANK_X").status_code == 201
    graph = api.get(GRAPH_URL).json()
    assert {node["id"] for node in graph["nodes"]} == {"X", "Y"}
    assert [(edge["source"], edge["target"], edge["exposure"]) for edge in graph["edges"]] == [
        ("X", "Y", 7.0)
    ]


def test_upload_accepts_parquet(api):
    frame = pd.DataFrame(
        {"debtor": ["A", "B"], "creditor": ["B", "A"], "amount": [10.0, 20.0]}
    )
    response = _upload(api, _parquet_bytes(frame), fmt="parquet")
    assert response.status_code == 201
    assert response.json()["format"] == "parquet"
    assert response.json()["n_edges"] == 2


def test_upload_infers_format_from_content_type(api):
    response = api.post(
        UPLOAD_URL,
        params={"source_institution": "BANK_A"},
        content=CSV_MATRIX,
        headers={"Content-Type": "text/csv"},
    )
    assert response.status_code == 201
    assert response.json()["format"] == "csv"


def test_upload_infers_format_from_filename_header(api):
    response = api.post(
        UPLOAD_URL,
        params={"source_institution": "BANK_A"},
        content=CSV_MATRIX,
        headers={"X-Filename": "exposures.csv"},
    )
    assert response.status_code == 201


# ---------------------------------------------------------------------------
# Upload rejection
# ---------------------------------------------------------------------------


def test_upload_rejects_negative_amounts(api):
    response = _upload(api, b"debtor,creditor,amount\nA,B,-5\n")
    assert response.status_code == 422
    assert response.json()["code"] == "EXPOSURE_VALIDATION_FAILED"
    assert "negative" in response.json()["message"]


def test_upload_rejects_self_exposure(api):
    response = _upload(api, b"debtor,creditor,amount\nA,A,5\n")
    assert response.status_code == 422
    assert response.json()["code"] == "EXPOSURE_VALIDATION_FAILED"
    assert "itself" in response.json()["message"]


def test_upload_rejects_missing_columns(api):
    response = _upload(api, b"debtor,amount\nA,5\n")
    assert response.status_code == 422
    assert response.json()["code"] == "EXPOSURE_SCHEMA_INVALID"
    assert "creditor" in response.json()["message"]


def test_upload_rejects_unrecognised_columns(api):
    response = _upload(api, b"debtor,creditor,amount,currency\nA,B,5,USD\n")
    assert response.status_code == 422
    assert response.json()["code"] == "EXPOSURE_SCHEMA_INVALID"


def test_upload_rejects_inconsistent_identifier_casing(api):
    """``BANK_A`` and ``bank_a`` would split one institution into two nodes."""
    response = _upload(api, b"debtor,creditor,amount\nBANK_A,bank_a,5\n")
    assert response.status_code == 422
    assert response.json()["code"] == "EXPOSURE_VALIDATION_FAILED"


def test_upload_rejects_empty_body(api):
    response = _upload(api, b"")
    assert response.status_code == 422
    assert response.json()["code"] == "EXPOSURE_EMPTY"


def test_upload_rejects_unsupported_format(api):
    response = _upload(api, b"debtor,creditor,amount\nA,B,5\n", fmt="xlsx")
    assert response.status_code == 415
    assert response.json()["code"] == "EXPOSURE_FORMAT_UNSUPPORTED"


def test_upload_rejects_future_vintage(api):
    response = _upload(api, CSV_MATRIX, as_of="2999-01-01")
    assert response.status_code == 422
    assert response.json()["code"] == "EXPOSURE_VALIDATION_FAILED"


def test_upload_rejects_oversized_payload(client, tmp_path):
    small = BilateralExposureStore(tmp_path / "small", max_upload_bytes=32)
    app.dependency_overrides[get_bilateral_exposure_store] = lambda: small
    try:
        response = client.post(
            UPLOAD_URL,
            params={"source_institution": "BANK_A", "format": "csv"},
            content=b"debtor,creditor,amount\n" + b"A,B,1\n" * 20,
        )
    finally:
        app.dependency_overrides.pop(get_bilateral_exposure_store, None)
    assert response.status_code == 413
    assert response.json()["code"] == "EXPOSURE_UPLOAD_TOO_LARGE"


def test_upload_requires_source_institution(api):
    response = api.post(UPLOAD_URL, params={"format": "csv"}, content=CSV_MATRIX)
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Reachability: the uploaded matrix must drive the clearing path
# ---------------------------------------------------------------------------


def test_uploaded_matrix_is_consumable_by_the_clearing_path(api, store):
    """Prove the stored file reaches the network/clearing analysis path.

    The reader used here is ``load_bank_exposures`` -- the same mapping shape
    ``BankRiskAnalyzer.analyze_multiple_banks`` accepts -- and the layer is built
    through the multiplex module the engine uses. The graph endpoint is asserted
    to describe exactly that matrix, so the map and the clearing engine cannot
    diverge.
    """
    assert _upload(api, CSV_MATRIX, as_of="2024-06-30").status_code == 201

    exposures = store.load_bank_exposures()
    assert exposures == EXPECTED_EXPOSURES

    frame = store.load()
    node_ids = sorted(set(frame["debtor"]) | set(frame["creditor"]))
    layer = build_interbank_exposure_layer(
        frame.drop(columns=["as_of"]),
        node_ids,
        as_of=pd.Timestamp("2024-06-30"),
    )
    network_layer = require_exposure(layer)
    assert network_layer.liabilities.shape == (3, 3)

    # Endowments high enough that the network clears without defaults: the point
    # is that the uploaded obligations are admitted to the engine at all.
    result = clear_multiplex(
        [network_layer], endowments=[100.0, 100.0, 100.0], node_ids=node_ids
    )
    # ``nominal_liabilities`` is the per-institution obligation total; the
    # matrix itself is the layer that was admitted.
    assert result.nominal_liabilities.shape == (3,)
    assert float(result.total_shortfall) == 0.0

    graph = api.get(GRAPH_URL).json()
    served = {(edge["source"], edge["target"]): edge["exposure"] for edge in graph["edges"]}
    assert served == exposures == EXPECTED_EXPOSURES
