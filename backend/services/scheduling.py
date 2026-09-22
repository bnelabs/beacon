"""Per-source collection scheduling: due dates, backoff, jitter, enqueueing.

Why this module exists
----------------------

Collection was entirely manual: a "Sync Now" button that recorded a timestamp
and a job API nothing invoked on a clock. A deployment that monitors feeds had
no way to say "refresh this feed every six hours and tell me when it last
succeeded", which is the minimum meaning of "connected". This module is the
clock side of that contract; the worker side stays ``run_data_collection``,
unchanged except for telemetry.

Three decisions, stated so the next reader does not reverse them by accident:

* **Backoff on failure.** A feed that is down must not be hammered at its
  normal cadence, and must not be abandoned either. The interval doubles per
  consecutive failure up to ``MAX_BACKOFF_FACTOR``, then holds: a day-long
  outage retries every interval*8, forever, and recovers the moment one
  collection succeeds.
* **Stable per-source jitter.** N sources sharing an interval must not all
  land on the same beat tick and serialise behind each other. The offset is a
  hash of the source id, so it is stable across restarts -- random jitter
  would make ``next_due_at`` unreadable in the health payload.
* **The scheduler enqueues the same job a human does.** ``enqueue_collection``
  goes through ``JobService.create_job`` with ``data_collection`` parameters,
  so scheduled and manual collections are indistinguishable in the jobs list,
  the WebSocket relay and the failure matrix. There is exactly one collection
  path.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from sqlalchemy.orm import Session

from backend.models.data_source import DataSource

#: 2**3: eight intervals is the ceiling. A feed down for a day on an hourly
#: schedule retries every eight hours, not every eight days.
MAX_BACKOFF_FACTOR = 8

#: Up to a quarter of the interval, so a fleet of hourly sources spreads over
#: fifteen minutes instead of firing together.
JITTER_FRACTION = 0.25


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def jitter_seconds(source_id: int, interval_minutes: int) -> int:
    """A stable per-source offset in [0, interval * JITTER_FRACTION]."""
    span = int(interval_minutes * 60 * JITTER_FRACTION)
    if span <= 0:
        return 0
    digest = hashlib.sha256(f"beacon:sync:{source_id}".encode("utf-8")).hexdigest()
    return int(digest, 16) % (span + 1)


def backoff_factor(consecutive_failures: Optional[int]) -> int:
    """1 when healthy, doubling per failure, capped at MAX_BACKOFF_FACTOR."""
    failures = max(0, int(consecutive_failures or 0))
    return min(2 ** failures, MAX_BACKOFF_FACTOR)


def next_due_at(source: DataSource, now: datetime) -> Optional[datetime]:
    """When this source is next due, or None when it is manual-only.

    Manual means ``sync_interval_minutes`` is null or the source is disabled:
    the absence of a schedule is a decision, and this function honours it
    rather than inventing a default cadence.
    """
    interval = getattr(source, "sync_interval_minutes", None)
    if not interval or not source.enabled:
        return None
    anchor = (
        source.last_sync_started_at
        or source.last_successful_fetch
        or source.created_at
        or now
    )
    step = timedelta(minutes=interval) * backoff_factor(source.consecutive_failures)
    return _as_utc(anchor) + step + timedelta(seconds=jitter_seconds(source.id, interval))


def due_sources(db: Session, now: datetime) -> List[DataSource]:
    """Enabled, scheduled sources whose due date has passed."""
    scheduled = (
        db.query(DataSource)
        .filter(
            DataSource.enabled.is_(True),
            DataSource.sync_interval_minutes.isnot(None),
        )
        .all()
    )
    return [source for source in scheduled if now >= next_due_at(source, now)]


def collection_parameters(db: Session, source: DataSource, origin: str) -> dict:
    """The parameters ``run_data_collection`` expects, scoped to one source."""
    from backend.models.data_catalogue import DataCatalogueItem

    item_ids = [
        item_id
        for (item_id,) in db.query(DataCatalogueItem.id)
        .filter(
            DataCatalogueItem.data_source_id == source.id,
            DataCatalogueItem.enabled.is_(True),
        )
        .all()
    ]
    return {
        "data_source_id": source.id,
        "catalogue_items": item_ids,
        "origin": origin,
    }


def enqueue_collection(db: Session, source: DataSource, origin: str):
    """Create and dispatch a collection job for one source; stamp the start.

    ``last_sync_started_at`` is stamped here rather than in the worker so the
    health payload can distinguish "running now" from "idle" without reading
    the jobs table, and so the next due date moves the moment a collection is
    queued -- otherwise a long collection would look overdue while it ran.
    """
    from backend.schemas.job import JobCreate
    from backend.services.job_service import JobService

    parameters = collection_parameters(db, source, origin)
    source.last_sync_started_at = datetime.now(timezone.utc)
    db.commit()
    return JobService(db).create_job(
        JobCreate(job_type="data_collection", parameters=parameters)
    )


def has_open_collection(db: Session, source_id: int) -> bool:
    """True while a collection job for this source is pending or running.

    The scheduler must not queue a second collection behind a slow one: the
    queue would grow every beat tick while a feed is hung, and the two runs
    would race the same catalogue items through the quality gate.
    """
    from backend.models.job import Job

    open_job = (
        db.query(Job.id)
        .filter(
            Job.job_type == "data_collection",
            Job.status.in_(["pending", "running"]),
            Job.parameters["data_source_id"].as_integer() == source_id,
        )
        .first()
    )
    return open_job is not None


def record_sync_success(
    db: Session,
    source_id: int,
    started_at: datetime,
    rows: Optional[int] = None,
    degraded: bool = False,
) -> None:
    """Stamp duration/rows on success; clear the failure streak unless degraded.

    A *degraded* success (the HTTP layer served the fetch from stale cache
    because the provider was unreachable) still records
    ``last_successful_fetch``, duration and rows -- the data reached the
    pipeline, and the run genuinely completed. But it does **not** clear the
    failure streak and leaves a note beside the source: the streak is the
    backoff, the backoff exists because the provider was unreachable, and a
    cache-served success is not evidence of reachability. Clearing it
    silently would pin a down feed to its healthy cadence while every "green"
    sync actually read yesterday's cache (pipeline-review finding F9). The
    next genuinely fresh success clears the streak and the note.
    """
    source = db.get(DataSource, source_id)
    if source is None:
        return
    now = datetime.now(timezone.utc)
    source.last_successful_fetch = now
    source.last_sync_duration_ms = int((now - _as_utc(started_at)).total_seconds() * 1000)
    source.last_sync_rows = rows
    source.status = "active"
    if degraded:
        source.error_message = (
            "last sync was served (in part) from stale cache: provider "
            "unreachable; failure backoff kept"
        )
    else:
        source.consecutive_failures = 0
        source.error_message = None
    db.commit()


def record_sync_failure(db: Session, source_id: int, message: str) -> None:
    """Grow the failure streak (which is the backoff) and keep the reason."""
    source = db.get(DataSource, source_id)
    if source is None:
        return
    source.consecutive_failures = int(source.consecutive_failures or 0) + 1
    source.status = "error"
    source.error_message = message
    db.commit()
