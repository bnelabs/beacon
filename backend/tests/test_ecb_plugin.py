"""ECB plugin tests for the bounded exchange-rate transport."""

from datetime import datetime, timedelta

import pandas as pd
import requests


def _ecb_page(start: datetime, count: int) -> dict:
    dates = [start + timedelta(days=index) for index in range(count)]
    return {
        "structure": {
            "dimensions": {
                "observation": [
                    {"values": [{"id": date.strftime("%Y-%m-%d")} for date in dates]}
                ]
            }
        },
        "dataSets": [
            {
                "series": {
                    "0": {
                        "observations": {
                            str(index): [float(index)] for index in range(count)
                        }
                    }
                }
            }
        ],
    }


def test_exchange_rate_history_is_fetched_in_bounded_pages(monkeypatch):
    import backend.plugins.ecb_plugin as ecb

    first_start = datetime(2000, 1, 18)
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append(dict(params))
        if len(calls) == 1:
            payload = _ecb_page(first_start, 1000)
        else:
            payload = _ecb_page(datetime(2002, 10, 15), 2)

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return payload

        return Response()

    monkeypatch.setattr(ecb.requests, "get", fake_get)

    frame = ecb.ECBPlugin({}).fetch_asset_data(
        ["EXR/D.USD.EUR.SP00.A"],
        first_start,
        datetime(2002, 10, 16),
    )

    assert frame is not None
    assert len(frame) == 1002
    assert len(calls) == 2
    assert calls[0]["firstNObservations"] == 1000
    assert calls[1]["startPeriod"] > calls[0]["startPeriod"]
    assert frame["Asset"].unique().tolist() == ["USD/EUR"]


def test_exchange_rate_uses_ecb_backed_mirror_when_portal_is_down(monkeypatch):
    import backend.plugins.ecb_plugin as ecb

    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append(url)
        if url.startswith("https://data-api.ecb.europa.eu"):
            raise requests.Timeout("ECB portal unavailable")

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "rates": {
                        "2024-01-02": {"USD": 1.095},
                        "2024-01-03": {"USD": 1.092},
                    }
                }

        return Response()

    monkeypatch.setattr(ecb.requests, "get", fake_get)

    frame = ecb.ECBPlugin({}).fetch_asset_data(
        ["EXR/D.USD.EUR.SP00.A"],
        datetime(2024, 1, 1),
        datetime(2024, 1, 4),
    )

    assert frame is not None
    assert frame["Close"].tolist() == [1.095, 1.092]
    assert calls[-1] == "https://api.frankfurter.app/2024-01-01..2024-01-04"
    assert len(calls) >= 3
    assert all(url.startswith("https://data-api.ecb.europa.eu") for url in calls[:-1])


def test_indicator_history_uses_bounded_observation_request(monkeypatch):
    import backend.plugins.ecb_plugin as ecb

    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append(dict(params))

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return _ecb_page(datetime(2024, 1, 1), 2)

        return Response()

    monkeypatch.setattr(ecb.requests, "get", fake_get)
    frame = ecb.ECBPlugin({}).fetch_indicator_data(
        "FM/B.U2.EUR.4F.KR.MRR_FR.LEV",
        datetime(2024, 1, 1),
        datetime(2024, 1, 2),
    )

    assert frame is not None and len(frame) == 2
    assert calls[0]["firstNObservations"] == 1000
    assert len(calls) == 1


def test_indicator_retries_transient_ecb_failure(monkeypatch):
    import backend.plugins.ecb_plugin as ecb

    attempts = {"count": 0}

    def fake_get(url, headers=None, params=None, timeout=None):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise requests.Timeout("temporary ECB timeout")

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return _ecb_page(datetime(2024, 1, 1), 2)

        return Response()

    monkeypatch.setattr(ecb.requests, "get", fake_get)
    frame = ecb.ECBPlugin({}).fetch_indicator_data(
        "FM/B.U2.EUR.4F.KR.MRR_FR.LEV",
        datetime(2024, 1, 1),
        datetime(2024, 1, 2),
    )

    assert frame is not None and len(frame) == 2
    assert attempts["count"] == 2


def test_indicator_falls_back_to_backward_paging_when_oldest_page_fails(monkeypatch):
    import backend.plugins.ecb_plugin as ecb

    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append(dict(params))
        if "firstNObservations" in params:
            raise requests.Timeout("oldest ECB page unavailable")

        class Response:
            def raise_for_status(self):
                return None

            def json(self):
                return _ecb_page(datetime(2024, 1, 1), 2)

        return Response()

    monkeypatch.setattr(ecb.requests, "get", fake_get)
    frame = ecb.ECBPlugin({}).fetch_indicator_data(
        "CISS/D.U2.Z0Z.4F.EC.SS_CI.IDX",
        datetime(2024, 1, 1),
        datetime(2024, 1, 2),
    )

    assert frame is not None and len(frame) == 2
    assert any("lastNObservations" in params for params in calls)
