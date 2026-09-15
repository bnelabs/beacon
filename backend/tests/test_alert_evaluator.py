"""Alert-rule evaluation: rules must look at the numbers, once per frequency.

Alert rules shipped with full CRUD and no evaluator -- a rule could exist for
months without anything reading the metric it names, and the platform's
silence would read as health. These tests pin the evaluator's contract:

* a breached rule alerts once and then cools down for its window;
* a rule is only evaluated when its own frequency has elapsed;
* an unmeasurable metric or an unknown operator is a visible skip, never a
  guessed value;
* the alert lands as a notification a human can act on.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

os.environ.setdefault(
    "DATABASE_URL",
    f"sqlite:///{Path(__file__).resolve().parent / 'test_alert_evaluator.sqlite3'}",
)
(Path(__file__).resolve().parent / "test_alert_evaluator.sqlite3").unlink(missing_ok=True)

from backend.database import SessionLocal, init_db  # noqa: E402
from backend.models.alert_rule import AlertRule  # noqa: E402
from backend.models.job import Job  # noqa: E402
from backend.models.notification import Notification  # noqa: E402
from backend.services import alert_evaluator  # noqa: E402

NOW = datetime(2026, 9, 15, 12, 0, 0, tzinfo=timezone.utc)


@pytest.fixture(scope="module")
def db():
    init_db()
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture(autouse=True)
def _clean(db):
    """Jobs and notifications are the metric inputs; a leak between tests
    would make one test's breach another test's average."""
    db.query(Job).delete()
    db.query(Notification).delete()
    db.commit()
    yield


def _rule(db, **kwargs) -> AlertRule:
    defaults = dict(
        name="quality floor",
        category="data_quality",
        metric_type="quality_score",
        condition_operator="lt",
        threshold_value=0.8,
        evaluation_window_minutes=60,
        evaluation_frequency_minutes=15,
        is_enabled=True,
    )
    defaults.update(kwargs)
    rule = AlertRule(**defaults)
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


def _job(db, status="completed", result=None, created_at=None, started_at=None, completed_at=None):
    job = Job(
        job_type="data_collection",
        status=status,
        parameters={},
        result=result,
        created_at=created_at or NOW - timedelta(minutes=10),
        started_at=started_at or NOW - timedelta(minutes=9),
        completed_at=completed_at or NOW - timedelta(minutes=5),
    )
    db.add(job)
    db.commit()
    return job


def test_breached_rule_alerts_once_then_cools_down(db):
    rule = _rule(db, name="breach-once")
    _job(db, result={"quality_score": 0.5})

    first = alert_evaluator.evaluate_rule(db, rule, NOW)
    db.commit()
    assert first["outcome"] == "triggered"
    alerts = db.query(Notification).filter(Notification.title == f"Alert rule breached: {rule.name}").all()
    assert len(alerts) == 1
    assert alerts[0].notification_type == "alert"
    assert alerts[0].category == "data"
    assert alerts[0].priority == "high"

    # the same breach, five minutes later, is still the same breach
    again = alert_evaluator.evaluate_rule(db, rule, NOW + timedelta(minutes=5))
    db.commit()
    assert again["outcome"] == "cooldown"
    assert db.query(Notification).filter(Notification.title == f"Alert rule breached: {rule.name}").count() == 1

    # after the cooldown window it is a new breach and alerts again; the
    # new breach needs an observation inside the new window
    _job(db, result={"quality_score": 0.4}, created_at=NOW + timedelta(minutes=30))
    db.refresh(rule)
    later = alert_evaluator.evaluate_rule(db, rule, NOW + timedelta(minutes=61))
    db.commit()
    assert later["outcome"] == "triggered"
    assert db.query(Notification).filter(Notification.title == f"Alert rule breached: {rule.name}").count() == 2


def test_healthy_metric_does_not_alert(db):
    rule = _rule(db, name="healthy-floor")
    _job(db, result={"quality_score": 0.95})
    disposition = alert_evaluator.evaluate_rule(db, rule, NOW)
    db.commit()
    assert disposition["outcome"] == "ok"
    assert db.query(Notification).filter(Notification.title == f"Alert rule breached: {rule.name}").count() == 0


def test_unmeasurable_metric_is_a_visible_skip(db):
    rule = _rule(db, name="empty-window", metric_type="rmse")
    disposition = alert_evaluator.evaluate_rule(db, rule, NOW)
    db.commit()
    assert disposition["outcome"] == "skipped"
    assert "not measurable" in disposition["reason"]


def test_unknown_operator_refuses(db):
    rule = _rule(db, name="bad-operator", condition_operator="between")
    _job(db, result={"quality_score": 0.5})
    disposition = alert_evaluator.evaluate_rule(db, rule, NOW)
    db.commit()
    assert disposition["outcome"] == "skipped"
    assert "unknown operator" in disposition["reason"]


def test_success_rate_and_execution_time_metrics(db):
    _job(db, status="failed", result=None)
    _job(db, status="completed", result={"quality_score": 0.9})
    since = NOW - timedelta(minutes=60)
    rate = alert_evaluator._metric_value(db, "success_rate", since)
    assert rate == 0.5
    minutes = alert_evaluator._metric_value(db, "execution_time", since)
    assert minutes == pytest.approx(4.0)


def test_due_rules_honour_each_rules_frequency(db):
    fresh = _rule(db, name="fresh-rule")
    fresh.last_evaluated_at = NOW - timedelta(minutes=1)
    stale = _rule(db, name="stale-rule")
    stale.last_evaluated_at = NOW - timedelta(minutes=30)
    db.commit()

    summary = alert_evaluator.evaluate_due_rules(db, NOW)
    names = {r.id for r in db.query(AlertRule).all() if r.name == "stale-rule"}
    evaluated_ids = {d["rule"] for d in summary["details"]}
    assert names <= evaluated_ids
    fresh_ids = {r.id for r in db.query(AlertRule).all() if r.name == "fresh-rule"}
    assert not (fresh_ids & evaluated_ids)


def test_disabled_rules_are_never_evaluated(db):
    rule = _rule(db, name="disabled-rule", is_enabled=False)
    _job(db, result={"quality_score": 0.1})
    summary = alert_evaluator.evaluate_due_rules(db, NOW + timedelta(hours=2))
    assert rule.id not in {d["rule"] for d in summary["details"]}
