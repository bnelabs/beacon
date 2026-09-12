"""Point-in-time retrieval of the uploaded exposure matrix.

An exposure upload is not just "the current network". It has two clocks, and the
store has always carried both in its manifest: ``as_of`` is the vintage the matrix
*describes*, and ``uploaded_at`` is when it *became known*. This file asserts that
they are actually used as clocks rather than as metadata.

The property that matters is the one the whole platform is built around: a caller
asking for the network as of a date **before the matrix was uploaded** must get
nothing. Returning the current matrix for a past cut-off would be look-ahead --
the same clairvoyance `backend/modules/data/pit.py` exists to prevent, and the
reason the risk map's arcs must not silently repaint themselves into the past.

These tests exist because the alternative is a graph endpoint that *looks*
point-in-time aware (it accepts ``as_of``) while quietly ignoring it.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

# Must be set before the application is imported: the lifespan builds the
# database. `setdefault` leaves test_network_api.py's configuration alone when
# that module imported first.
os.environ.setdefault("USE_SQLITE", "true")
os.environ.setdefault(
    "DATABASE_URL",
    f"sqlite:///{Path(__file__).resolve().parent / 'test_network_api.sqlite3'}",
)

from fastapi.testclient import TestClient  # noqa: E402

from backend.api.main import app  # noqa: E402
from backend.api.routes.network import get_bilateral_exposure_store  # noqa: E402
from backend.services.bilateral_exposure_store import (  # noqa: E402
    BilateralExposureStore,
    ExposureSchemaError,
)

GRAPH_URL = "/api/v1/network/graph"
UPLOAD_URL = "/api/v1/network/exposures"

CSV_MATRIX = (
    b"debtor,creditor,amount\n"
    b"BANK_A,BANK_B,40\n"
    b"BANK_B,BANK_C,25\n"
    b"BANK_C,BANK_A,30\n"
)

#: A vintage the matrix describes, comfortably in the past.
DECLARED_VINTAGE = "2024-06-30"


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
    """The client wired to the throwaway store."""
    app.dependency_overrides[get_bilateral_exposure_store] = lambda: store
    try:
        yield client
    finally:
        app.dependency_overrides.pop(get_bilateral_exposure_store, None)


def _uploaded(store) -> dict:
    """Store the sample matrix and return the manifest it wrote."""
    return store.ingest(
        CSV_MATRIX,
        data_format="csv",
        source_institution="BANK_A",
        as_of=DECLARED_VINTAGE,
    )


def _after_upload() -> str:
    """A cut-off that is unambiguously after the upload."""
    return (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()


# ---------------------------------------------------------------------------
# The two clocks
# ---------------------------------------------------------------------------


class TestObservationsCarryBothClocks:
    def test_the_matrix_becomes_observations_with_manifest_clocks(self, store):
        manifest = _uploaded(store)
        observations = store.load_observations()

        assert observations is not None
        assert len(observations) == 3

        # The debtor/creditor pair becomes the entity/series key, so a matrix
        # cell is addressable by the same schema as any other PIT series.
        pairs = {(o.entity_id, o.series_id) for o in observations}
        assert ("BANK_A", "BANK_B") in pairs
        assert ("BANK_C", "BANK_A") in pairs

        for observation in observations:
            # Observation normalises to UTC-naive; the manifest records UTC-aware.
            # Compare the instant, not the repr.
            assert observation.valid_time == pd.Timestamp(
                manifest["as_of"]
            ).tz_convert("UTC").tz_localize(None)
            assert observation.observed_at == pd.Timestamp(
                manifest["uploaded_at"]
            ).tz_convert("UTC").tz_localize(None)

    def test_without_a_declared_vintage_the_upload_clock_is_both(self, store):
        """An undated matrix describes the instant it was supplied."""
        store.ingest(CSV_MATRIX, data_format="csv", source_institution="BANK_A")
        observations = store.load_observations()

        assert observations is not None
        for observation in observations:
            assert observation.valid_time == observation.observed_at

    def test_nothing_stored_yields_nothing(self, store):
        assert store.load_observations() is None

    def test_a_manifest_without_an_upload_clock_is_refused(self, store):
        """The two-clock rule needs both clocks; a missing one is an error."""
        _uploaded(store)
        manifest = json.loads(store.manifest_path.read_text(encoding="utf-8"))
        del manifest["uploaded_at"]
        store.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with pytest.raises(ExposureSchemaError):
            store.load_observations()

    def test_a_vintage_after_its_own_upload_is_refused(self, store):
        """A matrix cannot describe a period that had not begun when it arrived.

        Upload refuses a future vintage, so this can only be reached by a
        manifest that was edited afterwards -- which is exactly the case the
        two-clock rule has to catch rather than trust.
        """
        _uploaded(store)
        manifest = json.loads(store.manifest_path.read_text(encoding="utf-8"))
        manifest["as_of"] = (
            datetime.now(timezone.utc) + timedelta(days=365)
        ).isoformat()
        store.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with pytest.raises(ExposureSchemaError):
            store.load_observations()


# ---------------------------------------------------------------------------
# As-of retrieval
# ---------------------------------------------------------------------------


class TestAsOfRetrieval:
    def test_a_cut_off_after_the_upload_returns_the_matrix(self, store):
        _uploaded(store)
        frame = store.load_as_of(_after_upload())

        assert frame is not None
        assert set(frame.columns) >= {"debtor", "creditor", "amount"}
        pairs = set(zip(frame["debtor"], frame["creditor"]))
        assert pairs == {
            ("BANK_A", "BANK_B"),
            ("BANK_B", "BANK_C"),
            ("BANK_C", "BANK_A"),
        }
        assert float(frame.loc[frame["debtor"] == "BANK_A", "amount"].iloc[0]) == 40.0

    def test_a_cut_off_before_the_upload_returns_nothing(self, store):
        """The property this file exists for: no look-ahead.

        The matrix *describes* 2024-06-30 but was uploaded today. A caller asking
        for the network as of the date it describes did not have it, and must not
        be handed it.
        """
        _uploaded(store)

        assert store.load_as_of(DECLARED_VINTAGE) is None
        assert store.load_as_of("2024-12-31") is None

    def test_nothing_stored_returns_nothing(self, store):
        assert store.load_as_of(_after_upload()) is None

    def test_a_non_timestamp_is_rejected(self, store):
        _uploaded(store)
        with pytest.raises(ValueError):
            store.load_as_of("not-a-timestamp")

    def test_the_declared_vintage_travels_with_the_frame(self, store):
        _uploaded(store)
        frame = store.load_as_of(_after_upload())
        assert frame is not None
        # The frame's as_of is UTC-aware, matching what load() returns.
        assert pd.Timestamp(frame["as_of"].iloc[0]).tz_localize(None) == pd.Timestamp(
            DECLARED_VINTAGE
        )


# ---------------------------------------------------------------------------
# The endpoint
# ---------------------------------------------------------------------------


class TestGraphAsOf:
    def test_as_of_before_upload_is_unavailable_not_the_current_matrix(self, api):
        """The endpoint must refuse rather than repaint the past."""
        upload = api.post(
            UPLOAD_URL,
            params={
                "source_institution": "BANK_A",
                "format": "csv",
                "as_of": DECLARED_VINTAGE,
            },
            content=CSV_MATRIX,
        )
        assert upload.status_code == 201

        # The current matrix is available...
        assert api.get(GRAPH_URL).json()["status"] == "available"

        # ...but not as of the date it describes, because it had not been
        # supplied then.
        response = api.get(GRAPH_URL, params={"as_of": DECLARED_VINTAGE})
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "unavailable"
        assert payload["nodes"] == []
        assert payload["edges"] == []
        assert DECLARED_VINTAGE in payload["unavailable_reason"]
        assert payload["as_of"] == DECLARED_VINTAGE

    def test_as_of_after_upload_serves_the_matrix(self, api):
        api.post(
            UPLOAD_URL,
            params={
                "source_institution": "BANK_A",
                "format": "csv",
                "as_of": DECLARED_VINTAGE,
            },
            content=CSV_MATRIX,
        )
        payload = api.get(GRAPH_URL, params={"as_of": _after_upload()}).json()

        assert payload["status"] == "available"
        assert len(payload["layers"]) == 1
        assert {edge["exposure"] for edge in payload["edges"]} == {40.0, 25.0, 30.0}

    def test_as_of_with_nothing_uploaded_is_unavailable(self, api):
        payload = api.get(GRAPH_URL, params={"as_of": _after_upload()}).json()
        assert payload["status"] == "unavailable"
        assert payload["nodes"] == []

    def test_a_malformed_as_of_is_a_422(self, api):
        response = api.get(GRAPH_URL, params={"as_of": "not-a-timestamp"})
        assert response.status_code == 422

    def test_without_as_of_the_current_matrix_is_unchanged(self, api):
        """The parameter is additive: the default path keeps its old meaning."""
        api.post(
            UPLOAD_URL,
            params={"source_institution": "BANK_A", "format": "csv"},
            content=CSV_MATRIX,
        )
        payload = api.get(GRAPH_URL).json()
        assert payload["status"] == "available"
        assert payload["as_of"] is None
