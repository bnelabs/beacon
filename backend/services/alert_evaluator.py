"""Alert-rule evaluation: the loop that closes between metrics and people.

Why this module exists
----------------------

Alert rules had full CRUD and no evaluator: a rule like "quality score below
70 over the last hour" could be created, listed, edited and deleted, and
nothing ever looked at the numbers. A monitoring platform whose alerts never
fire is quieter than one with no alert feature at all, because the silence
looks like health.

Contract
--------

* Each rule carries its own frequency (``evaluation_frequency_minutes``) and
  window (``evaluation_window_minutes``); the beat tick only evaluates rules
  whose frequency has elapsed, so a 15-minute rule is not re-run every five
  minutes and an hourly rule is not spam-evaluated.
* A breach alerts once per cooldown (``evaluation_window_minutes``): while a
  breach is still the same breach, re-alerting is noise. A rule that recovers
  and breaches again alerts again, because ``last_triggered_at`` ages past
  the cooldown in between.
* Metrics are measured, never assumed: a metric the platform cannot compute
  for the window (no jobs in it, an unknown metric name) evaluates to None
  and the rule is skipped with its reason recorded in the return summary.
  Skipping is visible; guessing is not an option.
* Operators are the boring six (lt, lte, gt, gte, eq, neq); an unknown
  operator is a refusal, not a default.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from backend.models.alert_rule import AlertRule
from backend.models.job import Job

logger = logging.getLogger(__name__)

_OPERATORS = {
    "lt": lambda value, threshold: value < threshold,
    "lte": lambda value, threshold: value <= threshold,
    "gt": lambda value, threshold: value > threshold,
    "gte": lambda value, threshold: value >= threshold,
    "eq": lambda value, threshold: value == threshold,
    "neq": lambda value, threshold: value != threshold,
}

#: rule.category -> notification category vocabulary (model, data, job, system, risk)
_CATEGORY_MAP = {
    "data_quality": "data",
    "model_performance": "model",
    "job_execution": "job",
    "system_health": "system",
}


def _window_jobs(db: Session, since: datetime) -> list:
    return db.query(Job).filter(Job.created_at >= since).all()


def _metric_value(db: Session, metric_type: str, since: datetime) -> Optional[float]:
    """The measured value of ``metric_type`` over the window, or None.

    None means "not measurable right now" (no completed jobs in the window,
    an unknown metric): the caller skips the rule and says why.
    """
    jobs = _window_jobs(db, since)
    if metric_type == "success_rate":
        terminal = [j for j in jobs if j.status in ("completed", "failed")]
        if not terminal:
            return None
        ok = sum(1 for j in terminal if j.status == "completed")
        return ok / len(terminal)
    if metric_type == "execution_time":
        durations = [
            (j.completed_at - j.started_at).total_seconds() / 60.0
            for j in jobs
            if j.status == "completed" and j.started_at and j.completed_at
        ]
        return sum(durations) / len(durations) if durations else None
    if metric_type == "quality_score":
        scores = [
            float(j.result["quality_score"])
            for j in jobs
            if j.status == "completed"
            and isinstance(j.result, dict)
            and isinstance(j.result.get("quality_score"), (int, float))
        ]
        return sum(scores) / len(scores) if scores else None
    if metric_type == "rmse":
        values = []
        for j in jobs:
            if j.status != "completed" or not isinstance(j.result, dict):
                continue
            metrics = j.result.get("metrics") or {}
            candidate = j.result.get("rmse", metrics.get("rmse"))
            if isinstance(candidate, (int, float)):
                values.append(float(candidate))
        return sum(values) / len(values) if values else None
    return None


def evaluate_rule(db: Session, rule: AlertRule, now: datetime) -> Dict[str, Any]:
    """Evaluate one rule once. Returns a disposition dict for the summary."""
    since = now - timedelta(minutes=rule.evaluation_window_minutes or 60)
    value = _metric_value(db, rule.metric_type, since)
    rule.last_evaluated_at = now

    if value is None:
        return {"rule": rule.id, "outcome": "skipped", "reason": f"{rule.metric_type} not measurable over the window"}

    compare = _OPERATORS.get(rule.condition_operator)
    if compare is None:
        return {"rule": rule.id, "outcome": "skipped", "reason": f"unknown operator {rule.condition_operator}"}

    breached = bool(compare(value, rule.threshold_value))
    if not breached:
        return {"rule": rule.id, "outcome": "ok", "value": value}

    cooldown = timedelta(minutes=rule.evaluation_window_minutes or 60)
    if rule.last_triggered_at is not None:
        last = rule.last_triggered_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if now - last < cooldown:
            return {"rule": rule.id, "outcome": "cooldown", "value": value}

    rule.last_triggered_at = now
    _notify(db, rule, value)
    return {"rule": rule.id, "outcome": "triggered", "value": value}


def _notify(db: Session, rule: AlertRule, value: float) -> None:
    from backend.schemas.notification import NotificationCreate
    from backend.services.notification_service import NotificationService

    service = NotificationService(db)
    service.create_notification(
        NotificationCreate(
            title=f"Alert rule breached: {rule.name}",
            message=(
                f"{rule.metric_type} measured {value:.4f} over the last "
                f"{rule.evaluation_window_minutes} minute(s), which is "
                f"{rule.condition_operator} the threshold {rule.threshold_value}."
            ),
            notification_type="alert",
            category=_CATEGORY_MAP.get(rule.category, "system"),
            priority="high",
            is_urgent=rule.category in ("system_health", "data_quality"),
            action_url="/jobs" if rule.category == "job_execution" else None,
            action_label="Open Jobs" if rule.category == "job_execution" else None,
            related_entity_type="alert_rule",
            related_entity_id=rule.id,
            extra_data={"metric_type": rule.metric_type, "value": value, "threshold": rule.threshold_value},
        )
    )


def evaluate_due_rules(db: Session, now: datetime) -> Dict[str, Any]:
    """Evaluate every enabled rule whose own frequency has elapsed."""
    rules = db.query(AlertRule).filter(AlertRule.is_enabled.is_(True)).all()
    summary: Dict[str, Any] = {"evaluated": 0, "triggered": 0, "skipped": 0, "details": []}
    for rule in rules:
        frequency = rule.evaluation_frequency_minutes or 15
        last = rule.last_evaluated_at
        if last is not None:
            if last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            if now - last < timedelta(minutes=frequency):
                continue
        disposition = evaluate_rule(db, rule, now)
        db.commit()
        summary["evaluated"] += 1
        summary["details"].append(disposition)
        if disposition["outcome"] == "triggered":
            summary["triggered"] += 1
        elif disposition["outcome"] == "skipped":
            summary["skipped"] += 1
    return summary
