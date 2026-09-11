"""Tests for the Form PF connector.

The point of this module is that it refuses, so most of these tests assert that
the refusal happens, is typed, and carries a stable code -- rather than asserting
that some payload was parsed.
"""

from __future__ import annotations

import pandas as pd
import pytest

from backend.exceptions import (
    BeaconError,
    RestrictedSourceError,
    SchemaValidationError,
)
from backend.modules.data.connectors import (
    CONNECTORS,
    available_connectors,
    build_connector,
)
from backend.modules.data.connectors.base import FetchRequest
from backend.modules.data.connectors.sec_form_pf import (
    PUBLIC_ALTERNATIVE_URL,
    SecFormPfConnector,
)
from backend.modules.data.pit import PITStore


@pytest.fixture()
def connector() -> SecFormPfConnector:
    return SecFormPfConnector()


def _valid_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "entity_id": ["FUND_A", "FUND_A"],
            "series_id": ["FORM_PF:GROSS_ASSETS", "FORM_PF:GROSS_ASSETS"],
            "valid_time": pd.to_datetime(["2025-03-31", "2025-06-30"]),
            "observed_at": pd.to_datetime(["2025-05-14", "2025-08-14"]),
            "value": [1.5e9, 1.7e9],
            "revision": [0, 0],
        }
    )


class TestSpec:
    def test_is_marked_as_requiring_credentials(self, connector):
        # A caller must be able to tell "restricted" from "reachable" without
        # attempting a fetch.
        assert connector.spec.requires_credentials is True

    def test_codes_and_identity(self, connector):
        assert connector.spec.name == "sec_form_pf"
        assert connector.spec.kind == "sec"

    def test_points_at_the_public_alternative(self, connector):
        assert connector.spec.source_url == PUBLIC_ALTERNATIVE_URL


class TestRefusesToFetch:
    def test_build_url_raises_restricted(self, connector):
        with pytest.raises(RestrictedSourceError) as excinfo:
            connector.build_url(FetchRequest())
        assert excinfo.value.code == "DATA_SOURCE_RESTRICTED"
        assert excinfo.value.http_status == 451

    def test_parse_raises_restricted(self, connector):
        with pytest.raises(RestrictedSourceError):
            connector.parse(b"<xml/>", FetchRequest())

    def test_fetch_raises_restricted(self, connector):
        with pytest.raises(RestrictedSourceError):
            connector.fetch()

    def test_load_raises_restricted(self, connector):
        store = PITStore()
        with pytest.raises(RestrictedSourceError):
            connector.load(store, FetchRequest())
        assert len(store) == 0

    def test_error_is_a_beacon_error_with_context(self, connector):
        # The message has to name the actual filing system, not just say "denied".
        with pytest.raises(RestrictedSourceError) as excinfo:
            connector.fetch()
        error = excinfo.value
        assert isinstance(error, BeaconError)
        assert "PFRD" in error.context["filing_system"]
        assert error.context["connector"] == "sec_form_pf"
        assert "FINRA" in str(error)
        assert error.to_dict()["code"] == "DATA_SOURCE_RESTRICTED"

    def test_refusal_is_not_an_empty_result(self, connector):
        # The failure mode being guarded against is returning an empty frame that
        # a caller cannot distinguish from "no funds reported".
        with pytest.raises(RestrictedSourceError):
            connector.fetch()
        with pytest.raises(RestrictedSourceError):
            connector.parse(b"", FetchRequest())


class TestAvailability:
    def test_reports_what_is_and_is_not_obtainable(self, connector):
        payload = connector.availability().to_dict()
        assert payload["public_filings"] is False
        assert payload["public_aggregates"] is True
        assert payload["public_alternative"] == PUBLIC_ALTERNATIVE_URL
        assert "FINRA" in payload["filing_system"]

    def test_serialises(self, connector):
        import json

        json.dumps(connector.availability().to_dict())


class TestAuthorisedExport:
    def test_loads_a_valid_extract(self, connector):
        store = PITStore()
        report = connector.load_authorised_export(
            store, _valid_frame(), source_reference="PFRD receipt 12345"
        )
        assert report.connector == "sec_form_pf"
        assert report.fetched == 2
        assert report.added == 2
        assert report.series == ("FORM_PF:GROSS_ASSETS",)
        assert report.entities == ("FUND_A",)
        assert len(store) == 2
        assert str(report.first_valid_time) == "2025-03-31 00:00:00"
        assert str(report.last_valid_time) == "2025-06-30 00:00:00"

    def test_reload_is_idempotent(self, connector):
        store = PITStore()
        connector.load_authorised_export(store, _valid_frame(), source_reference="r1")
        second = connector.load_authorised_export(
            store, _valid_frame(), source_reference="r1"
        )
        assert second.fetched == 2
        assert second.added == 0
        assert len(store) == 2

    def test_requires_a_source_reference(self, connector):
        with pytest.raises(ValueError, match="source_reference"):
            connector.load_authorised_export(PITStore(), _valid_frame(), source_reference="   ")

    def test_rejects_a_frame_claiming_public_retrieval(self, connector):
        frame = _valid_frame()
        frame["retrieved_publicly"] = True
        with pytest.raises(RestrictedSourceError):
            connector.load_authorised_export(
                PITStore(), frame, source_reference="PFRD receipt 12345"
            )

    def test_rejects_a_frame_that_violates_the_schema(self, connector):
        frame = _valid_frame()
        # A value known before the period it describes: the two-clock violation
        # that makes a backtest clairvoyant.
        frame.loc[0, "observed_at"] = pd.Timestamp("2025-01-01")
        with pytest.raises(SchemaValidationError):
            connector.load_authorised_export(
                PITStore(), frame, source_reference="PFRD receipt 12345"
            )

    def test_store_returns_the_loaded_value(self, connector):
        store = PITStore()
        connector.load_authorised_export(store, _valid_frame(), source_reference="r1")
        frame = store.to_frame()
        assert frame.shape[0] == 2
        assert set(frame["series_id"]) == {"FORM_PF:GROSS_ASSETS"}


class TestRegistry:
    def test_is_registered(self):
        assert "sec_form_pf" in CONNECTORS

    def test_builds_from_the_registry(self):
        assert isinstance(build_connector("sec_form_pf"), SecFormPfConnector)

    def test_appears_in_discovery(self):
        listing = available_connectors()
        assert "sec_form_pf" in listing
        assert "confidential" in listing["sec_form_pf"].lower()

    def test_unknown_name_lists_the_alternatives(self):
        with pytest.raises(ValueError, match="unknown connector"):
            build_connector("nope")
