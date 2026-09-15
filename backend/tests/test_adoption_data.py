"""Round-eight data adoption: semantics, plugins, LEI resolution.

Anchors: the sign registry refuses undeclared series rather than defaulting;
the event labeller accepts a registry-resolved direction per source; the new
keyless plugins parse their documented payload shapes and refuse unknown
ones; LEI resolution caches, searches and reports parents without guessing
matches.
"""

from __future__ import annotations

from datetime import datetime

import pandas as pd
import pytest

from backend.modules.data.event_labeller import EventDefinition
from backend.modules.data.semantics import event_direction, stress_direction


class TestSemantics:
    def test_stress_indices_rise_into_stress(self):
        assert stress_direction("FRED_STLFSI4") == +1
        assert event_direction("FRED_STLFSI4") == "up"

    def test_term_structure_inverts_into_stress(self):
        assert stress_direction("FRED_T10Y2Y") == -1
        assert event_direction("FRED_T10Y2Y") == "down"

    def test_undeclared_series_are_refused_not_defaulted(self):
        assert stress_direction("SOME_NEW_SERIES") is None
        assert event_direction("SOME_NEW_SERIES") is None

    def test_event_definition_accepts_deferred_direction(self):
        definition = EventDefinition(direction=None, quantile=0.95, horizon=5)
        assert definition.direction is None


class TestNYFedPlugin:
    def _plugin(self):
        from backend.plugins.nyfed_plugin import NYFedPlugin

        plugin = NYFedPlugin.__new__(NYFedPlugin)
        plugin.config = {}
        return plugin

    def test_documented_payload_shape_parses(self, monkeypatch):
        import backend.plugins.nyfed_plugin as nyfed

        records = [
            {"date": "2024-01-02", "percent": 5.31},
            {"date": "2024-01-03", "percent": 5.32},
        ]
        monkeypatch.setattr(nyfed.NYFedPlugin, "_records", lambda self, rate: records)
        frame = self._plugin().fetch_indicator_data("sofr", datetime(2024, 1, 1), datetime(2024, 1, 31))
        assert list(frame.columns) == ["Date", "Value"]
        assert len(frame) == 2

    def test_unknown_rate_is_refused(self):
        with pytest.raises(ValueError):
            self._plugin().fetch_indicator_data("not-a-rate", datetime(2024, 1, 1), datetime(2024, 2, 1))

    def test_missing_value_column_is_refused_not_invented(self, monkeypatch):
        import backend.plugins.nyfed_plugin as nyfed

        monkeypatch.setattr(nyfed.NYFedPlugin, "_records", lambda self, rate: [{"date": "2024-01-02"}])
        with pytest.raises(ValueError):
            self._plugin().fetch_indicator_data("sofr", datetime(2024, 1, 1), datetime(2024, 2, 1))


class TestCFTCPlugin:
    def test_config_validation(self):
        from backend.plugins.cftc_cot_plugin import CFTCCotPlugin

        plugin = CFTCCotPlugin.__new__(CFTCCotPlugin)
        plugin.config = {"resource_id": "6dca-aqww"}
        plugin.validate_config()  # no raise
        plugin.config = {"resource_id": ""}
        with pytest.raises(ValueError):
            plugin.validate_config()


class TestLEIService:
    def test_resolve_parses_and_caches(self, monkeypatch):
        from backend.services.lei_service import LEIService

        service = LEIService()
        payload = {"data": [{"id": "LEI1", "attributes": {
            "lei": "LEI1",
            "entity": {"legalName": {"name": "Bank One"}, "jurisdiction": "DE"},
            "status": "ISSUED",
        }}]}
        calls = {"n": 0}

        def fake_get(path, params=None):
            calls["n"] += 1
            return payload

        monkeypatch.setattr(service, "_get", fake_get)
        first = service.resolve("LEI1")
        second = service.resolve("LEI1")
        assert first["legal_name"] == "Bank One"
        assert second == first
        assert calls["n"] == 1  # cache hit

    def test_parents_report_direct_and_ultimate(self, monkeypatch):
        from backend.services.lei_service import LEIService

        service = LEIService()
        payload = {"data": [
            {"relationships": {"type": "direct", "parent": {"data": {"id": "P1"}}}},
            {"relationships": {"type": "ultimate", "parent": {"data": {"id": "U1"}}}},
        ]}
        monkeypatch.setattr(service, "_get", lambda path, params=None: payload)
        parents = service.parents("LEI1")
        assert parents == {"direct": "P1", "ultimate": "U1"}
