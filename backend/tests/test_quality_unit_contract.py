"""Every reader of a quality score must agree on what the number means.

Two defects, one root cause.

**The unit.** The quality gate works in 0-100 percentages:
``QualityPolicy.min_quality_score = 70.0``, ``min_completeness = 80.0``, and
``completeness = 100.0 * (1.0 - missing_ratio)``. ``Job.result`` stores those
numbers, ``/api/v1/data-quality/*`` returns them, and the frontend pages that
display them tested their own thresholds against 0.7 and 0.5 -- so a real
85.6 rendered as ``8560.0%`` and was coloured "excellent". ``Jobs.tsx`` guessed
per value (``numeric > 1 ? numeric : numeric * 100``), which made 0.9 and 92
both print as 90% and made the disagreement unprovable. The e2e mocks encoded
0-1 for ``avg_quality_score`` and 0-100 for ``avg_completeness`` *in the same
object*, which is why a green Tier-2 run could not see any of it: the specs
asserted headings and labels, never a number.

**The reader.** Finding F2 (#103) moved ``/api/v1/data-quality/*`` off
``DataJob ⋈ PipelineJob`` -- rows only ``POST /api/v1/pipeline`` writes -- onto
both writers. ``/api/v1/analytics/*`` was left on that table, in three places:
the overview card (permanently 0 on a deployment collecting through jobs), the
quality and completeness trend series, and the ``quality_degradation`` anomaly
detector, which could never fire because it had nothing to compare.

What this module pins:

* the policy floors are 0-100 values, not fractions -- they are where the
  frontend's 70/90 bands come from;
* ``/api/v1/analytics/overview`` and ``/trends/time-series`` aggregate BOTH
  writers and return the gate's scale verbatim;
* ``quality_degradation`` fires on job-path collections;
* an alert rule written as a fraction (``quality_score lt 0.8``) can never
  breach a gate-scale score, and the same floor written as ``lt 70`` breaches
  immediately -- the silent-guard consequence of an undeclared unit.

Runs in backend-tests.yml (nightly + ``workflow_dispatch``); Tier 1 does not
run pytest at all.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.database import SessionLocal, init_db
from backend.models.alert_rule import AlertRule
from backend.models.asset import Asset
from backend.models.data_catalogue import DataCatalogueItem
from backend.models.data_source import DataSource
from backend.models.job import Job
from backend.models.notification import Notification
from backend.models.pipeline_job import (
    DataJob,
    EngineJob,
    JobStatus,
    PipelineJob,
    PipelineStage,
    ResultJob,
)
from backend.modules.data.quality_gate import QualityPolicy
from backend.services import alert_evaluator

client = TestClient(app)

ANALYTICS = "/api/v1/analytics"
NOW = datetime.now(timezone.utc)


def _wipe_everything(db) -> None:
    """Children before parents, and every child of a parent this wipe takes.

    The ordering is not style: it is the class of failure #110 closed. A
    parent-only delete leaves rows pointing at ids SQLite then hands to the
    next module's INSERT, and the failure surfaces two modules away as an
    assert about completely unrelated data. conftest's session guard now
    proves the absence of orphans; this ordering is what keeps that guard
    quiet.
    """
    db.query(DataJob).delete()
    db.query(EngineJob).delete()
    db.query(ResultJob).delete()
    db.query(PipelineJob).delete()
    db.query(Job).delete()
    db.query(Notification).delete()
    db.query(AlertRule).delete()
    db.query(DataCatalogueItem).delete()
    db.query(Asset).delete()
    db.query(DataSource).delete()
    db.commit()


@pytest.fixture(autouse=True)
def _clean_tables():
    init_db()
    db = SessionLocal()

    _wipe_everything(db)
    yield
    _wipe_everything(db)
    db.close()


@pytest.fixture()
def db():
    session = SessionLocal()
    yield session
    session.close()


def _source(db, name: str = "unit-fred") -> DataSource:
    source = DataSource(
        name=name,
        plugin_type="fred",
        config={},
        enabled=True,
        status="active",
        last_successful_fetch=NOW - timedelta(hours=1),
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def _collection_job(db, source_id: int, quality_score: float, completeness: float,
                    created_at: datetime | None = None) -> Job:
    """A job exactly as the production path stores a gate verdict."""
    job = Job(
        job_type="data_collection",
        status="completed",
        parameters={"data_source_id": source_id, "catalogue_items": [1]},
        result={"quality_score": quality_score, "completeness": completeness, "fit_for_engine": True},
    )
    job.created_at = created_at or (NOW - timedelta(minutes=10))
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _pipeline_data_job(db, quality_score: float, completeness: float, tag: str) -> DataJob:
    pipeline = PipelineJob(
        job_id=f"pipeline_unit_{tag}",
        name="unit pipeline",
        current_stage=PipelineStage.DATA,
        status=JobStatus.COMPLETED,
    )
    db.add(pipeline)
    db.commit()
    db.refresh(pipeline)
    data_job = DataJob(
        pipeline_job_id=pipeline.id,
        status=JobStatus.COMPLETED,
        quality_score=quality_score,
        completeness=completeness,
    )
    db.add(data_job)
    db.commit()
    db.refresh(data_job)
    return data_job


def _rule(db, name: str, threshold: float) -> AlertRule:
    rule = AlertRule(
        name=name,
        category="data_quality",
        metric_type="quality_score",
        condition_operator="lt",
        threshold_value=threshold,
        evaluation_window_minutes=60,
        evaluation_frequency_minutes=15,
        is_enabled=True,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def _seed_three_writers(db) -> None:
    """Two job-path collections and one pipeline row: mean quality 75.4,
    mean completeness 92.3333, on the gate's scale."""
    source = _source(db)
    _collection_job(db, source.id, 91.2, 97.0)
    _collection_job(db, source.id, 55.0, 90.0)
    _pipeline_data_job(db, 80.0, 90.0, tag="mix")


# ---------------------------------------------------------------------------
# The unit, stated once
# ---------------------------------------------------------------------------


def test_the_gate_is_written_in_percentages_not_fractions():
    """The bands the frontend mirrors come from here, not from taste."""
    policy = QualityPolicy()
    assert policy.min_quality_score > 1.0, (
        "min_quality_score is a percentage (70.0); if it ever becomes 0.7 the "
        "scale changed under every reader that compares against it"
    )
    assert policy.min_completeness > 1.0
    assert policy.min_quality_score == pytest.approx(70.0)
    assert policy.min_completeness == pytest.approx(80.0)


def test_a_gate_score_is_never_a_fraction(db):
    """A real verdict on a healthy dataset is a number like 92.33, not 0.9233.

    Seeded through the production writer and read back through the endpoint
    that the Data Quality page calls: the value must survive the trip with no
    rescaling in either direction.
    """
    source = _source(db, name="unit-roundtrip")
    _collection_job(db, source.id, 92.33, 96.5)

    payload = client.get("/api/v1/data-quality/stats").json()
    avg_quality = payload["quality"]["avg_quality_score"]
    avg_completeness = payload["quality"]["avg_completeness"]

    assert avg_quality == pytest.approx(92.33, abs=1e-3)
    assert avg_completeness == pytest.approx(96.5, abs=1e-3)
    assert 1.0 < avg_quality <= 100.0
    assert 1.0 < avg_completeness <= 100.0


# ---------------------------------------------------------------------------
# The analytics readers: both writers, same scale
# ---------------------------------------------------------------------------


def test_analytics_overview_sees_the_production_job_path(db):
    """Finding F2's twin. Until now this endpoint read only DataJob ⋈
    PipelineJob, so on a deployment collecting through the jobs API the
    Analytics "Data Quality Metrics" card showed 0 while collections
    succeeded and their verdicts sat in Job.result."""
    _seed_three_writers(db)

    payload = client.get(f"{ANALYTICS}/overview").json()
    quality = payload["data_quality"]

    assert quality["jobs_analyzed"] == 3, "both writers, one aggregate"
    assert quality["avg_quality_score"] == pytest.approx(75.4, abs=1e-3)
    assert quality["avg_completeness"] == pytest.approx(92.3333, abs=1e-3)
    assert quality["avg_quality_score"] > 1.0, "gate scale, not a fraction"
    assert quality["avg_completeness"] <= 100.0, "not double-scaled on the way out"


def test_analytics_trends_bucket_both_writers(db):
    for metric, expected in (("quality", 75.4), ("completeness", 92.3333)):
        _wipe_everything(db)
        _seed_three_writers(db)

        payload = client.get(f"{ANALYTICS}/trends/time-series", params={"metric": metric}).json()

        assert payload["data_points"] == 1, "one day, three scores"
        point = payload["series"][0]
        assert point["count"] == 3
        assert point["value"] == pytest.approx(expected, abs=1e-3)
        assert point["value"] > 1.0, f"{metric} is reported on the 0-100 scale"


def test_quality_degradation_can_fire_on_job_path_collections(db):
    """The anomaly detector compared the newest five scores against the older
    ones -- on a table production never writes. Eight job-path collections,
    recent ones at 40.0 and older ones at 90.0, is an unambiguous degradation;
    before this fix the detector had nothing to compare and stayed silent."""
    source = _source(db, name="unit-degrading")

    for offset in range(5):
        _collection_job(
            db, source.id, 90.0, 95.0,
            created_at=NOW - timedelta(days=2, minutes=offset * 5),
        )
    for offset in range(3):
        _collection_job(
            db, source.id, 40.0, 50.0,
            created_at=NOW - timedelta(hours=1, minutes=offset * 5),
        )

    payload = client.get(f"{ANALYTICS}/insights/anomalies").json()
    kinds = [item["type"] for item in payload["anomalies"]]

    assert "quality_degradation" in kinds, (
        f"a 90 -> 40 slide across eight collections must be reported; saw {kinds}"
    )


# ---------------------------------------------------------------------------
# What an undeclared unit does to a guard
# ---------------------------------------------------------------------------


def test_a_quality_floor_written_as_a_fraction_can_never_breach(db):
    """`quality_score lt 0.8` reads like a floor and is unreachable.

    The only rule this repository ever seeded for evaluation used 0.8, and the
    scores it was compared against are 0-100 -- so the rule reports "ok" for
    any dataset the gate would refuse. The same floor written as `lt 70`
    breaches on the same data. Both dispositions are pinned so the difference
    is a fact in the suite rather than a paragraph in a review.
    """
    source = _source(db, name="unit-alert")
    _collection_job(db, source.id, 42.0, 60.0)  # far below the gate's 70 floor

    fraction_rule = _rule(db, "quality floor written as a fraction", 0.8)
    gate_rule = _rule(db, "quality floor on the gate scale", 70.0)

    fraction_outcome = alert_evaluator.evaluate_rule(db, fraction_rule, NOW)
    gate_outcome = alert_evaluator.evaluate_rule(db, gate_rule, NOW)

    assert fraction_outcome["outcome"] == "ok", (
        "a gate-scale score is never < 0.8: this rule is a guard that cannot fire"
    )
    assert gate_outcome["outcome"] == "triggered"
    assert gate_outcome["value"] == pytest.approx(42.0)

    fired = db.query(Notification).filter(
        Notification.title.like("Alert rule breached%")
    ).count()
    assert fired == 1, "exactly one human-visible alert: the rule written in the right unit"
