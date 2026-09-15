"""The clock side of data collection: beat tasks that enqueue due work.

``dispatch_due_collections`` is the only scheduled entry point for collection.
It runs every five minutes from Celery beat (see ``celery_app.beat_schedule``
and the ``celery-beat`` compose service), asks
``backend.services.scheduling`` which sources are due, and enqueues exactly
the job a human would create from the UI -- same task, same parameters shape,
same jobs list, same failure matrix.

It is deliberately thin: due-date maths, backoff, jitter and the open-job
guard all live in ``scheduling.py`` where they can be tested without Celery,
and the collection itself lives in ``run_data_collection`` where it already
was. A beat task with policy in it is a policy nobody can unit-test.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from backend.database import SessionLocal
from backend.services.scheduling import (
    due_sources,
    enqueue_collection,
    has_open_collection,
)
from backend.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="dispatch_due_collections")
def dispatch_due_collections() -> dict:
    """Enqueue a collection job for every source whose due date has passed.

    Returns a small summary dict so ``celery inspect`` and the beat log show
    what each tick decided; an operator debugging "why did nothing sync"
    reads ``{"due": 2, "skipped_open": 1, "enqueued": [41]}`` instead of
    grepping four modules.
    """
    db = SessionLocal()
    try:
        now = datetime.now(timezone.utc)
        due = due_sources(db, now)
        enqueued: list = []
        skipped_open = 0
        for source in due:
            if has_open_collection(db, source.id):
                skipped_open += 1
                continue
            job = enqueue_collection(db, source, origin="schedule")
            enqueued.append(job.id)
            logger.info(
                "scheduled collection for source %s (%s) as job %s",
                source.id,
                source.name,
                job.id,
            )
        return {"due": len(due), "skipped_open": skipped_open, "enqueued": enqueued}
    except Exception:  # noqa: BLE001 - a broken tick must not kill the beat
        logger.exception("dispatch_due_collections tick failed")
        raise
    finally:
        db.close()
