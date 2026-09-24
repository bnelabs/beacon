"""Tests for the IMF DataMapper plugin transport.

The DataMapper endpoint ignores both the country path segment and the
``periods`` parameter (it returns every country and every year), so the
plugin selects the country key and date window locally. Transient provider
failures must surface as ``DataSourceUnavailableError`` so the collector's
bounded retry applies; a 4xx (unknown indicator/country) is a decision and
must return ``None`` without raising.
"""

from __future__ import annotations

from datetime import datetime

import pytest
import requests

import backend.plugins.imf_plugin as imf
from backend.exceptions import DataSourceUnavailableError
from backend.plugins.imf_plugin import IMFPlugin


def _datamapper_payload(indicator: str, values: dict) -> dict:
    return {"values": {indicator: {"USA": values}}}


def _response(payload, status=200):
    class Response:
        def raise_for_status(self):
            if status >= 400:
                raise requests.HTTPError(f"{status} error")

        def json(self):
            return payload

    response = Response()
    response.status_code = status
    return response


def test_fetch_parses_country_and_window(monkeypatch):
    values = {str(year): float(year - 2000) for year in range(2000, 2010)}
    monkeypatch.setattr(imf.requests, "get",
                        lambda *a, **k: _response(_datamapper_payload("NGDP_RPCH", values)))

    frame = IMFPlugin({}).fetch_indicator_data("NGDP_RPCH/USA", datetime(2002, 1, 1), datetime(2005, 12, 31))
    assert frame is not None
    assert len(frame) == 4
    assert frame["value"].tolist() == [2.0, 3.0, 4.0, 5.0]


def test_unknown_indicator_returns_none_not_error(monkeypatch):
    monkeypatch.setattr(imf.requests, "get", lambda *a, **k: _response({"values": {}}))
    assert IMFPlugin({}).fetch_indicator_data("NOPE/USA", datetime(2000, 1, 1), datetime(2005, 1, 1)) is None


def test_network_failure_raises_unavailable(monkeypatch):
    def boom(*args, **kwargs):
        raise requests.ConnectionError("boom")

    monkeypatch.setattr(imf.requests, "get", boom)
    with pytest.raises(DataSourceUnavailableError):
        IMFPlugin({}).fetch_indicator_data("NGDP_RPCH/USA", datetime(2000, 1, 1), datetime(2005, 1, 1))


def test_5xx_raises_unavailable(monkeypatch):
    monkeypatch.setattr(imf.requests, "get", lambda *a, **k: _response({}, status=503))
    with pytest.raises(DataSourceUnavailableError):
        IMFPlugin({}).fetch_indicator_data("NGDP_RPCH/USA", datetime(2000, 1, 1), datetime(2005, 1, 1))


def test_4xx_returns_none(monkeypatch):
    monkeypatch.setattr(imf.requests, "get", lambda *a, **k: _response({}, status=404))
    assert IMFPlugin({}).fetch_indicator_data("NOPE/USA", datetime(2000, 1, 1), datetime(2005, 1, 1)) is None
