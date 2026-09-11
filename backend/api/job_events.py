"""Cross-process transport for job updates.

Why this exists
---------------
The job WebSocket lives in the API process, but most job progress is written by
the Celery worker, which is a **different process**. A process-local set of
connections cannot observe those writes, so the previous
``broadcast_job_update`` — which had no caller anywhere in the repository — could
never have delivered an update even if something had called it. That is the
defect this module closes.

Redis is already a hard dependency (it is the Celery broker), so it is the
natural bus. ``JobService.update_job_status`` is the single choke point through
which every status and progress change passes, in *both* processes, so it
publishes there; the API process subscribes and fans out to its own sockets.

What this is NOT
----------------
* **Not durable.** Pub/sub drops messages when no subscriber is attached. That is
  acceptable because the client also polls (see ``useJobsWebSocket.js``): a
  missed frame delays a refresh rather than losing it.
* **Not a queue.** Nothing is retried or replayed, and there is no delivery
  guarantee. Ordering between two publishers is not enforced.
* **Not required for correctness.** Publishing is best-effort and never raises;
  the subscriber reconnects in a loop. A Redis outage degrades the feed to the
  client's polling fallback rather than failing a job.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
from typing import Any, Awaitable, Callable, Mapping, Optional

logger = logging.getLogger(__name__)

#: Redis channel carrying job payloads between processes.
JOB_UPDATES_CHANNEL = "beacon:job_updates"

#: Delay before the subscriber retries a lost subscription.
RECONNECT_DELAY_SECONDS = 5.0

__all__ = [
    "JOB_UPDATES_CHANNEL",
    "RECONNECT_DELAY_SECONDS",
    "job_payload",
    "publish_job_update",
    "relay_job_updates",
]

_publish_client: Optional[Any] = None
_publish_lock = threading.Lock()


def _redis_url() -> str:
    """The broker URL, matching ``backend/tasks/celery_app.py``."""
    return os.getenv("REDIS_URL", "redis://localhost:6379/0")


def job_payload(job: Any) -> dict:
    """Serialise a ``Job`` row into the payload clients receive.

    Only columns that exist on ``backend/models/job.py`` are read. The function
    this replaces also emitted ``model_id`` and ``config``, neither of which is a
    column on that model — it would have raised ``AttributeError`` on first use.

    ``id`` and ``job_id`` are both present because the client keys one React
    Query cache by ``job_id`` and looks up another by either.
    """
    return {
        "id": job.id,
        "job_id": job.id,
        "job_type": job.job_type,
        "status": job.status,
        "progress": job.progress,
        "current_step": job.current_step,
        "parameters": job.parameters,
        "result": job.result,
        "error": job.error_message,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


def _get_publish_client() -> Any:
    """A lazily created, reused Redis client for publishing.

    Created on first use rather than at import so that importing this module
    never opens a socket — tests and the migration path import it without Redis
    present. Redis clients are thread-safe, and because creation happens after
    any Celery fork the connection is not shared across processes.
    """
    global _publish_client
    if _publish_client is None:
        with _publish_lock:
            if _publish_client is None:
                import redis  # imported here so the dependency is optional at import time

                _publish_client = redis.from_url(_redis_url())
    return _publish_client


def publish_job_update(payload: Mapping[str, Any]) -> bool:
    """Publish a job payload to the bus. Best-effort; never raises.

    Returns ``True`` when Redis accepted the message. ``False`` means the update
    was not broadcast — the job is unaffected, and clients fall back to polling —
    so callers should not treat it as a failure worth surfacing to a user.
    """
    try:
        client = _get_publish_client()
        client.publish(JOB_UPDATES_CHANNEL, json.dumps(payload, default=str))
        return True
    except Exception as exc:  # pragma: no cover - depends on a live Redis
        logger.debug(
            "Could not publish job update (%s: %s); clients will fall back to polling",
            type(exc).__name__,
            exc,
        )
        return False


async def relay_job_updates(broadcast: Callable[[dict], Awaitable[None]]) -> None:
    """Subscribe to the bus and fan each message out through ``broadcast``.

    Runs until cancelled. A lost subscription is retried rather than ending the
    task, because the alternative — one transient Redis blip permanently
    disabling live updates until a restart — is indistinguishable from the bug
    this module was written to fix.
    """
    try:
        import redis.asyncio as aioredis
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning(
            "Job update relay disabled: redis.asyncio is unavailable (%s: %s)",
            type(exc).__name__,
            exc,
        )
        return

    while True:
        client = None
        pubsub = None
        try:
            client = aioredis.from_url(_redis_url(), decode_responses=True)
            pubsub = client.pubsub()
            await pubsub.subscribe(JOB_UPDATES_CHANNEL)
            logger.info("Job update relay subscribed to %s", JOB_UPDATES_CHANNEL)

            async for message in pubsub.listen():
                if message.get("type") != "message":
                    continue  # subscribe/unsubscribe confirmations
                try:
                    payload = json.loads(message["data"])
                except (TypeError, ValueError):
                    logger.warning(
                        "Discarding malformed job update on %s", JOB_UPDATES_CHANNEL
                    )
                    continue
                await broadcast({"type": "job_update", "job": payload})
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning(
                "Job update relay lost its subscription (%s: %s); retrying in %ss",
                type(exc).__name__,
                exc,
                RECONNECT_DELAY_SECONDS,
            )
            await asyncio.sleep(RECONNECT_DELAY_SECONDS)
        finally:
            if pubsub is not None:
                try:
                    await pubsub.aclose()
                except Exception:  # pragma: no cover - best effort
                    pass
            if client is not None:
                try:
                    await client.aclose()
                except Exception:  # pragma: no cover - best effort
                    pass
