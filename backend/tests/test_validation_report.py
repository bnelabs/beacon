"""The predictive-validity report must distinguish validated from not-validated.

Absence of validation is a status, not an error and not a zero: a backtest
without an event_definition has no labelled events and therefore no
precision/recall/lead-time statistics, and the report says exactly that.
"""

from __future__ import annotations

import os
from importlib import reload

import pytest


@pytest.fixture()
def db(tmp_path):
    os.environ["USE_SQLITE"] = "true"
    os.environ["DATABASE_URL"] = f"sqlite:///{tmp_path / 'validation.sqlite3'}"
    import backend.database as database

    database = reload(database)
    database.init_db()
    session = database.SessionLocal()
    yield session
    session.close()


def _job(session, job_type, result):
    from backend.models.job import Job

    job = Job(job_type=job_type, status="completed", result=result)
    session.add(job)
    session.commit()
    session.refresh(job)
    return job


def _client():
    from fastapi.testclient import TestClient

    from backend.api.main import app

    return TestClient(app)


class TestValidationReport:
    def test_validated_backtest_returns_statistics(self, db):
        job = _job(db, "backtest", {
            "backtest_metrics": {
                "event_metrics": {
                    "definition": {"direction": "up", "quantile": 0.95, "horizon": 5, "min_duration": 2},
                    "by_series": {
                        "SRC_A": {
                            "n_events": 2,
                            "roc_auc": 0.81,
                            "average_precision": 0.44,
                            "lead_time": {"median_lead": 3, "n_zero_lead": 1},
                        },
                        "SRC_B": {"skipped": "no_events_in_window"},
                    },
                },
                "directional_accuracy": 0.6,
            }
        })
        response = _client().get(f"/api/v2/reports/validation/{job.id}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "validated"
        assert payload["validation"]["mean_roc_auc"] == pytest.approx(0.81)
        assert payload["validation"]["by_series"]["SRC_B"]["skipped"] == "no_events_in_window"
        assert payload["validation"]["quant_metrics"]["directional_accuracy"] == 0.6

    def test_unvalidated_backtest_reports_absence(self, db):
        job = _job(db, "backtest", {"backtest_metrics": {}})
        payload = _client().get(f"/api/v2/reports/validation/{job.id}").json()
        assert payload["status"] == "not_validated"
        assert payload["validation"] is None
        assert "event_definition" in payload["reason"]

    def test_non_backtest_jobs_are_refused(self, db):
        job = _job(db, "training", {})
        response = _client().get(f"/api/v2/reports/validation/{job.id}")
        assert response.status_code == 400

    def test_unknown_job_is_404(self, db):
        assert _client().get("/api/v2/reports/validation/99999").status_code == 404
