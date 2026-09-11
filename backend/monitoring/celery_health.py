"""Celery queue / worker health and task instrumentation (workstream F).

Everything in this module degrades gracefully:

* ``redis`` is optional -- :func:`queue_depth` returns ``{}`` instead of raising
  when the package is missing or the broker is unreachable;
* ``celery`` is optional -- :func:`worker_health` reports ``status="unavailable"``
  instead of raising, and :func:`register_celery_signals` simply returns
  ``False``.

Public surface
--------------
``queue_depth(broker_url=None, redis_client=None, queues=None) -> dict[str, int]``
    Read ``LLEN`` for every known Celery queue key (Kombu Redis transport keeps a
    plain Redis list per queue) and refresh ``beacon_celery_queue_depth{queue}``.
    ``redis_client`` allows tests to inject a fake client.

``worker_health(...) -> dict``
    Snapshot of live workers and their active/reserved/scheduled task counts via
    the Celery control API (``celery_app.control.inspect()``).  A crashed pool is
    visible as ``pools["training"]["status"] == "dead"`` /
    ``status == "no_workers"`` -- see ``BEACON_EXPECTED_TRAINING_WORKERS``.

``register_celery_signals(celery_app) -> bool``
    Connect ``task_prerun`` / ``task_postrun`` / ``task_failure`` to the Celery
    counters, the task-duration histogram and (best effort) the pipeline job
    counters.

``install_scrape_hooks() -> bool``
    Ask :mod:`backend.monitoring.metrics` to refresh queue depth + worker health
    right before ``/metrics`` is rendered, so the backend process publishes a
    live Celery view without any worker-side HTTP endpoint.

Environment
-----------
``CELERY_BROKER_URL`` / ``REDIS_URL``
    Broker used when ``broker_url`` is not passed.
``BEACON_CELERY_QUEUES``
    Comma separated queue names to inspect (default: discovered from the Celery
    app / Kombu bindings, falling back to ``celery``).
``BEACON_EXPECTED_WORKER_POOLS``
    JSON mapping ``{"pool": ["hostname-or-queue-or-task-token", ...]}`` used to
    classify workers into pools.
``BEACON_EXPECTED_TRAINING_WORKERS``
    Number of training workers that *must* be alive; when > 0 a missing training
    pool is reported as ``"dead"`` and drags the overall status to ``degraded``.
``BEACON_WORKER_HEALTH_TTL``
    Cache TTL in seconds for :func:`worker_health` (default ``10``).
``BEACON_CELERY_METRICS_AT_SCRAPE``
    Set to ``0``/``false`` to disable :func:`install_scrape_hooks`.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .metrics import (
    KNOWN_JOB_TYPES,
    celery_queue_depth as celery_queue_depth_gauge,
    celery_task_duration_seconds,
    celery_tasks_total,
    celery_worker_tasks,
    celery_workers_online,
    record_pipeline_job_completed,
    record_pipeline_job_failed,
    record_pipeline_job_started,
    record_pipeline_job_duration,
    register_scrape_hook,
)

logger = logging.getLogger(__name__)

try:  # pragma: no cover - environment dependent
    import redis as _redis

    REDIS_AVAILABLE = True
except ImportError:  # pragma: no cover - environment dependent
    _redis = None  # type: ignore[assignment]
    REDIS_AVAILABLE = False

try:  # pragma: no cover - environment dependent
    from celery import signals as _celery_signals

    CELERY_AVAILABLE = True
except ImportError:  # pragma: no cover - environment dependent
    _celery_signals = None  # type: ignore[assignment]
    CELERY_AVAILABLE = False

__all__ = [
    "REDIS_AVAILABLE",
    "CELERY_AVAILABLE",
    "DEFAULT_QUEUES",
    "TRAINING_TOKENS",
    "queue_depth",
    "worker_health",
    "register_celery_signals",
    "install_scrape_hooks",
    "refresh_celery_gauges",
    "expected_pools",
]

DEFAULT_QUEUES: Tuple[str, ...] = ("celery",)

#: Tokens that identify a worker as part of the (PyTorch/GNN) training pool.
TRAINING_TOKENS: Tuple[str, ...] = ("train", "torch", "gpu", "inference", "predict")

_CONNECT_TIMEOUT = float(os.getenv("BEACON_REDIS_CONNECT_TIMEOUT", "0.5"))
_SOCKET_TIMEOUT = float(os.getenv("BEACON_REDIS_SOCKET_TIMEOUT", "0.5"))
_WORKER_HEALTH_TTL = float(os.getenv("BEACON_WORKER_HEALTH_TTL", "10"))
_INSPECT_TIMEOUT = float(os.getenv("BEACON_CELERY_INSPECT_TIMEOUT", "1.0"))

_REDIS_CLIENTS: Dict[str, Any] = {}
_REDIS_CLIENTS_LOCK = threading.Lock()

_QUEUE_DEPTH_CACHE: Dict[str, Any] = {"at": 0.0, "value": None}
_WORKER_HEALTH_CACHE: Dict[str, Any] = {"at": 0.0, "value": None}
_CACHE_LOCK = threading.Lock()

_KNOWN_POOLS: set[str] = set()
_KNOWN_QUEUES_GAUGED: set[str] = set()

_TASK_START_TIMES: Dict[str, float] = {}
_TASK_TIMES_LOCK = threading.Lock()

_SIGNAL_APPS: set[int] = set()
_SIGNAL_LOCK = threading.Lock()
_SCRAPE_HOOK_INSTALLED = False

_UNKNOWN = "unknown"


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _call(obj: Any, name: str, *args: Any, default: Any = None) -> Any:
    """Call ``obj.name(*args)`` returning ``default`` if it is missing/raises."""

    function = getattr(obj, name, None)
    if not callable(function):
        return default
    try:
        return function(*args)
    except Exception as exc:
        logger.debug("Celery/Redis call %s%s failed: %s", name, args, exc)
        return default


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _decode(value: Any) -> str:
    if isinstance(value, (bytes, bytearray)):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _resolve_broker_url(url_override: Optional[str] = None) -> str:
    """Resolve the broker URL from the argument, then the environment."""

    if url_override:
        return url_override
    return (
        os.getenv("CELERY_BROKER_URL")
        or os.getenv("REDIS_URL")
        or "redis://localhost:6379/0"
    )


def _env_tokens(name: str, default: Iterable[str] = ()) -> Tuple[str, ...]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return tuple(token.lower() for token in default)
    return tuple(token.strip().lower() for token in raw.split(",") if token.strip())


def expected_pools() -> Dict[str, Tuple[str, ...]]:
    """Configured worker pools from ``BEACON_EXPECTED_WORKER_POOLS``.

    Unset/invalid configuration yields ``{"default": ("celery",)}``.
    """

    raw = os.getenv("BEACON_EXPECTED_WORKER_POOLS", "").strip()
    if raw:
        try:
            data = json.loads(raw)
            if isinstance(data, Mapping):
                return {
                    str(pool): tuple(str(token).lower() for token in tokens)
                    for pool, tokens in data.items()
                }
            logger.warning(
                "BEACON_EXPECTED_WORKER_POOLS must be a JSON object, got %s",
                type(data).__name__,
            )
        except Exception as exc:
            logger.warning("Could not parse BEACON_EXPECTED_WORKER_POOLS: %s", exc)

    queues = _env_tokens("BEACON_CELERY_QUEUES", DEFAULT_QUEUES)
    return {"default": queues or DEFAULT_QUEUES}


def _load_celery_app() -> Any:
    """Best-effort import of the BEACON Celery application."""

    if not CELERY_AVAILABLE:
        return None
    for module_name in ("backend.tasks.celery_app", "tasks.celery_app"):
        try:
            module = __import__(module_name, fromlist=["celery_app"])
            app = getattr(module, "celery_app", None)
            if app is not None:
                return app
        except Exception as exc:
            logger.debug("Could not import %s: %s", module_name, exc)
    return None


# ---------------------------------------------------------------------------
# Redis / queue depth
# ---------------------------------------------------------------------------


def _make_redis_client(redis_url: str, redis_client: Any = None) -> Any:
    if redis_client is not None:
        return redis_client
    with _REDIS_CLIENTS_LOCK:
        cached = _REDIS_CLIENTS.get(redis_url)
    if cached is not None:
        return cached
    if not REDIS_AVAILABLE:
        return None
    try:
        client = _redis.Redis.from_url(
            redis_url,
            socket_timeout=_SOCKET_TIMEOUT,
            socket_connect_timeout=_CONNECT_TIMEOUT,
        )
    except Exception as exc:
        logger.warning("Could not create Redis client for %s: %s", redis_url, exc)
        return None
    with _REDIS_CLIENTS_LOCK:
        _REDIS_CLIENTS[redis_url] = client
    return client


def _configured_queues() -> List[str]:
    names: List[str] = list(_env_tokens("BEACON_CELERY_QUEUES", ()))

    app = _load_celery_app()
    if app is not None:
        try:
            task_queues = getattr(app.conf, "task_queues", None)
            if task_queues:
                for entry in task_queues:
                    name = getattr(entry, "name", None) or str(entry)
                    if name:
                        names.append(str(name))
            default_queue = getattr(app.conf, "task_default_queue", None)
            if default_queue:
                names.append(str(default_queue))
        except Exception as exc:  # pragma: no cover - defensive
            logger.debug("Could not read Celery queue configuration: %s", exc)

    if not names:
        names = list(DEFAULT_QUEUES)
    return names


def _discover_queue_names(client: Any, include_priority_steps: bool = True) -> List[str]:
    """Discover queue names from Kombu's ``_kombu.binding.<exchange>`` set."""

    names: List[str] = []
    bindings = _call(client, "smembers", "_kombu.binding.celery", default=None)
    for raw in bindings or ():
        text = _decode(raw)
        parts = [part for part in text.split("\x06\x16") if part]
        if parts:
            names.append(parts[0])

    if not include_priority_steps:
        return names

    # Kombu priority steps append "\x06\x16<step>" to the queue key.
    for base in list(dict.fromkeys(names)):
        iterator = getattr(client, "scan_iter", None)
        if not callable(iterator):
            continue
        try:
            for key in iterator(match=f"{base}\x06\x16*", count=100):
                text = _decode(key)
                if text:
                    names.append(text)
        except Exception as exc:
            logger.debug("Priority-step scan for queue %r failed: %s", base, exc)

    return names


def queue_depth(
    broker_url: Optional[str] = None,
    redis_client: Any = None,
    queues: Optional[Sequence[str]] = None,
    include_priority_steps: bool = True,
) -> Dict[str, int]:
    """Return ``{queue_name: pending_messages}`` for the Celery Redis broker.

    ``broker_url`` defaults to ``CELERY_BROKER_URL``/``REDIS_URL``.  Never
    raises: an unreachable broker, a missing ``redis`` package or a broken client
    all yield ``{}``.  When values are obtained the Prometheus gauge
    ``beacon_celery_queue_depth{queue}`` is updated; gauges for queues that
    disappear are removed.
    """

    resolved_url = _resolve_broker_url(broker_url)
    client = _make_redis_client(resolved_url, redis_client=redis_client)
    if client is None:
        logger.debug("queue_depth: Redis unavailable for %s", resolved_url)
        return {}

    if queues is not None:
        names = [str(name) for name in queues]
    else:
        names = list(_configured_queues())
        names.extend(_discover_queue_names(client, include_priority_steps))

    depths: Dict[str, int] = {}
    for name in dict.fromkeys(name for name in names if name):
        length = _call(client, "llen", name, default=None)
        if length is None:
            continue
        try:
            depths[name] = int(length)
        except (TypeError, ValueError):
            continue

    if depths:
        stale = _KNOWN_QUEUES_GAUGED - set(depths)
        for queue in stale:
            _call(celery_queue_depth_gauge, "remove", queue)
        _KNOWN_QUEUES_GAUGED.clear()
        _KNOWN_QUEUES_GAUGED.update(depths)
        for queue, depth in depths.items():
            try:
                celery_queue_depth_gauge.labels(queue=queue).set(depth)
            except Exception:  # pragma: no cover - metrics must never break health
                logger.debug("Could not publish queue depth gauge for %r", queue)

    return depths


# ---------------------------------------------------------------------------
# Worker health
# ---------------------------------------------------------------------------


def _classify_worker(
    hostname: str,
    queues: Sequence[str],
    registered: Sequence[str],
    pools: Mapping[str, Sequence[str]],
) -> Tuple[str, List[str]]:
    """Assign a worker to the first matching configured pool.

    Matching deliberately ignores the ``user@`` prefix of the hostname (every
    Celery node is ``celery@<nodename>``), otherwise the generic default-queue
    token ``celery`` would match every worker and shadow more specific pools such
    as ``training``.
    """

    node = hostname.split("@")[-1]
    haystack = " ".join(
        [node.lower()]
        + [str(q).lower() for q in queues]
        + [str(t).lower() for t in registered]
    )
    for pool, tokens in pools.items():
        for token in tokens:
            if token and token in haystack:
                return str(pool), [token]
    return "default", []


def _detect_training_workers(
    workers: Mapping[str, Mapping[str, Any]]
) -> Tuple[int, List[str]]:
    """Number of live workers that look like a PyTorch/GNN training pool."""

    matched: List[str] = []
    for hostname, info in workers.items():
        haystack = " ".join(
            [hostname.lower()]
            + [str(q).lower() for q in info.get("queues", [])]
            + [str(t).lower() for t in info.get("registered_tasks_sample", [])]
        )
        if any(token in haystack for token in TRAINING_TOKENS):
            matched.append(hostname)
    return len(matched), matched


def _worker_health_uncached(
    pools: Mapping[str, Sequence[str]],
    timeout: Optional[float],
    include_queues: bool,
) -> Dict[str, Any]:
    report: Dict[str, Any] = {
        "status": "unavailable",
        "celery_available": CELERY_AVAILABLE,
        "redis_available": REDIS_AVAILABLE,
        "live_workers": 0,
        "total_workers": 0,
        "active_tasks": 0,
        "reserved_tasks": 0,
        "scheduled_tasks": 0,
        "workers": {},
        "pools": {},
        "training_pool": {"live_workers": 0, "status": _UNKNOWN, "detected_by": []},
        "queues": {},
        "detail": "",
        "checked_at": _now_iso(),
    }

    app = _load_celery_app()
    if app is None:
        report["detail"] = (
            "Celery is not importable in this process; worker health cannot be inspected."
        )
        _publish_worker_gauges(report)
        return report

    inspect_timeout = float(timeout) if timeout is not None else _INSPECT_TIMEOUT
    inspector = None
    try:
        inspector = app.control.inspect(timeout=inspect_timeout)
    except Exception as exc:
        report["detail"] = f"celery_app.control.inspect() failed: {exc}"
        _publish_worker_gauges(report)
        return report

    if inspector is None:
        report["status"] = "no_workers"
        report["detail"] = "Celery control API returned no inspector."
        if include_queues:
            report["queues"] = queue_depth()
        _publish_worker_gauges(report)
        return report

    ping = _call(inspector, "ping", default=None)
    active = _call(inspector, "active", default=None) or {}
    reserved = _call(inspector, "reserved", default=None) or {}
    scheduled = _call(inspector, "scheduled", default=None) or {}
    active_queues = _call(inspector, "active_queues", default=None) or {}
    registered = _call(inspector, "registered", default=None) or {}

    if ping is None and not active and not reserved and not scheduled:
        report["status"] = "no_workers"
        report["detail"] = (
            "No Celery workers responded to the control API (broker reachable, "
            "but the worker pools appear to be down)."
        )
        if include_queues:
            report["queues"] = queue_depth()
        _publish_worker_gauges(report)
        return report

    hostnames = set()
    for source in (ping, active, reserved, scheduled, active_queues, registered):
        if isinstance(source, Mapping):
            hostnames.update(str(name) for name in source)
    if isinstance(ping, Mapping):
        hostnames.update(str(name) for name in ping)

    workers: Dict[str, Dict[str, Any]] = {}
    pool_counter: Counter = Counter()

    for hostname in sorted(hostnames):
        queues: List[str] = []
        for entry in active_queues.get(hostname, []) or []:
            name = entry.get("name") if isinstance(entry, Mapping) else entry
            if name:
                queues.append(str(name))

        registered_tasks = registered.get(hostname, []) or []
        pool, _matched = _classify_worker(hostname, queues, list(registered_tasks), pools)
        pool_counter[pool] += 1

        workers[hostname] = {
            "pool": pool,
            "online": bool(ping is not None and hostname in (ping or {})),
            "active": len(active.get(hostname, []) or []),
            "reserved": len(reserved.get(hostname, []) or []),
            "scheduled": len(scheduled.get(hostname, []) or []),
            "queues": sorted(queues),
            "registered_tasks": len(registered_tasks),
            "registered_tasks_sample": [str(t) for t in list(registered_tasks)[:25]],
        }

    active_total = sum(info["active"] for info in workers.values())
    reserved_total = sum(info["reserved"] for info in workers.values())
    scheduled_total = sum(info["scheduled"] for info in workers.values())

    training_live, training_hosts = _detect_training_workers(workers)
    expected_training = int(os.getenv("BEACON_EXPECTED_TRAINING_WORKERS", "0") or 0)

    pool_report: Dict[str, Dict[str, Any]] = {}
    for pool in pools:
        live = int(pool_counter.get(str(pool), 0))
        pool_report[str(pool)] = {
            "live_workers": live,
            "expected_workers": None,
            "status": "healthy" if live > 0 else "dead",
            "matched_by": list(pools[pool]),
        }

    training_status = "healthy" if training_live > 0 else _UNKNOWN
    if training_live == 0 and expected_training > 0:
        training_status = "dead"

    if "training" in pool_report:
        pool_report["training"]["live_workers"] = training_live
        pool_report["training"]["expected_workers"] = expected_training or None
        if training_live == 0 and expected_training > 0:
            pool_report["training"]["status"] = "dead"
    else:
        pool_report["training"] = {
            "live_workers": training_live,
            "expected_workers": expected_training or None,
            "status": training_status,
            "matched_by": list(TRAINING_TOKENS),
        }

    degraded_reasons: List[str] = []
    report["status"] = "healthy" if workers else "no_workers"
    if not workers:
        degraded_reasons.append("no live workers")

    # A pool is only *required* when it was configured explicitly (anything but
    # the catch-all "default") or when a minimum size is declared through the
    # environment.  The always-present "training" entry is informational unless
    # BEACON_EXPECTED_TRAINING_WORKERS > 0, so a platform that runs a single
    # shared worker does not raise a false "dead training pool" alarm.
    configured_pools = {str(pool) for pool in pools}
    for pool, info in pool_report.items():
        if info.get("status") != "dead":
            continue
        required = pool in configured_pools and pool != "default"
        if pool == "training" and expected_training > 0:
            required = True
        if required:
            degraded_reasons.append(f"pool {pool!r} has no live workers")

    if degraded_reasons and report["status"] != "no_workers":
        report["status"] = "degraded"
    if expected_training > 0 and training_live < expected_training:
        degraded_reasons.append(
            f"training pool below expectation ({training_live}/{expected_training} live)"
        )

    report.update(
        {
            "live_workers": len(workers),
            "total_workers": len(workers),
            "active_tasks": active_total,
            "reserved_tasks": reserved_total,
            "scheduled_tasks": scheduled_total,
            "workers": workers,
            "pools": pool_report,
            "training_pool": pool_report.get(
                "training",
                {"live_workers": 0, "status": _UNKNOWN, "detected_by": []},
            ),
            "training_workers_live": training_live,
            "training_workers": training_hosts,
            "detail": "; ".join(degraded_reasons)
            if degraded_reasons
            else f"{len(workers)} live worker(s)",
        }
    )
    if include_queues:
        report["queues"] = queue_depth()

    _publish_worker_gauges(report)
    return report


def _publish_worker_gauges(report: Mapping[str, Any]) -> None:
    live = int(report.get("live_workers", 0) or 0)
    pools = report.get("pools") or {}

    try:
        celery_workers_online.labels(pool="all").set(live)
        wanted = {"all"}
        for pool, info in pools.items():
            pool_name = str(pool)
            celery_workers_online.labels(pool=pool_name).set(
                int(info.get("live_workers", 0) or 0)
            )
            wanted.add(pool_name)
            # Publish the declared expectation as `<pool>_expected` so alert rules
            # can compare live vs. expected without hardcoding the number.
            expected = info.get("expected_workers")
            if expected is not None:
                celery_workers_online.labels(pool=f"{pool_name}_expected").set(
                    int(expected)
                )
                wanted.add(f"{pool_name}_expected")

        stale = _KNOWN_POOLS - wanted
        for pool in stale:
            _call(celery_workers_online, "remove", pool)
        _KNOWN_POOLS.clear()
        _KNOWN_POOLS.update(wanted)

        celery_worker_tasks.labels(state="active").set(
            int(report.get("active_tasks", 0) or 0)
        )
        celery_worker_tasks.labels(state="reserved").set(
            int(report.get("reserved_tasks", 0) or 0)
        )
        celery_worker_tasks.labels(state="scheduled").set(
            int(report.get("scheduled_tasks", 0) or 0)
        )
    except Exception:  # pragma: no cover - metrics must never break health
        logger.debug("Could not publish Celery worker gauges", exc_info=True)


def worker_health(
    expected: Optional[Mapping[str, Sequence[str]]] = None,
    timeout: Optional[float] = None,
    refresh: bool = False,
    use_cache: bool = True,
    include_queues: bool = True,
) -> Dict[str, Any]:
    """Return a JSON-serialisable Celery worker/pool health snapshot.

    Never raises: when no worker responds, ``inspect()`` returns ``None``, Celery
    is not installed or the broker call fails, the report says so and carries
    zeroed counters.  The result is cached for ``BEACON_WORKER_HEALTH_TTL``
    seconds (default 10s) unless ``refresh=True``.
    """

    pools = dict(expected) if expected is not None else expected_pools()

    now = time.monotonic()
    if use_cache and not refresh:
        with _CACHE_LOCK:
            cached_at = _WORKER_HEALTH_CACHE.get("at", 0.0)
            cached_value = _WORKER_HEALTH_CACHE.get("value")
        if cached_value is not None and (now - float(cached_at or 0.0)) < _WORKER_HEALTH_TTL:
            return dict(cached_value)

    try:
        report = _worker_health_uncached(pools, timeout, include_queues)
    except Exception as exc:  # pragma: no cover - absolute safety net
        logger.exception("worker_health failed unexpectedly: %s", exc)
        report = {
            "status": "unavailable",
            "celery_available": CELERY_AVAILABLE,
            "redis_available": REDIS_AVAILABLE,
            "live_workers": 0,
            "total_workers": 0,
            "active_tasks": 0,
            "reserved_tasks": 0,
            "scheduled_tasks": 0,
            "workers": {},
            "pools": {},
            "training_pool": {"live_workers": 0, "status": _UNKNOWN, "detected_by": []},
            "queues": {},
            "detail": f"worker_health failed: {exc}",
            "checked_at": _now_iso(),
        }

    with _CACHE_LOCK:
        _WORKER_HEALTH_CACHE["at"] = now
        _WORKER_HEALTH_CACHE["value"] = report
    return report


# ---------------------------------------------------------------------------
# Celery signals
# ---------------------------------------------------------------------------


def _task_name(task: Any = None, sender: Any = None) -> str:
    for candidate in (task, sender):
        name = getattr(candidate, "name", None)
        if isinstance(name, str) and name:
            return name
    return _UNKNOWN


def _job_type_from_task_name(task_name: str) -> Optional[str]:
    lowered = (task_name or "").lower()
    if "data_collection" in lowered or "collect" in lowered or "ingest" in lowered:
        return "data_collection"
    if "train" in lowered:
        return "training"
    if "predict" in lowered or "inference" in lowered or "infer" in lowered:
        return "prediction"
    if "backtest" in lowered:
        return "backtest"
    return None


def _stage_from_job_type(job_type: Optional[str]) -> str:
    return {
        "data_collection": "ingestion",
        "training": "training",
        "prediction": "inference",
        "backtest": "backtest",
    }.get(job_type or "", "pipeline")


def _extract_job_type(args: Any = None, kwargs: Any = None) -> Optional[str]:
    """Best-effort discovery of ``job_type`` in the task arguments."""

    candidates: List[Mapping[str, Any]] = []
    if isinstance(kwargs, Mapping):
        candidates.append(kwargs)
        parameters = kwargs.get("parameters")
        if isinstance(parameters, Mapping):
            candidates.append(parameters)
    if isinstance(args, (list, tuple)):
        for item in args:
            if isinstance(item, Mapping):
                candidates.append(item)

    for candidate in candidates:
        job_type = candidate.get("job_type")
        if isinstance(job_type, str) and job_type in KNOWN_JOB_TYPES:
            return job_type
    return None


def _on_task_prerun(
    sender: Any = None,
    task_id: Optional[str] = None,
    task: Any = None,
    args: Any = None,
    kwargs: Any = None,
    **_extra: Any,
) -> None:
    name = _task_name(task, sender)
    if task_id:
        with _TASK_TIMES_LOCK:
            if len(_TASK_START_TIMES) > 10000:  # pragma: no cover - runaway guard
                _TASK_START_TIMES.clear()
            _TASK_START_TIMES[str(task_id)] = time.perf_counter()

    celery_tasks_total.labels(task_name=name, status="started").inc()

    job_type = _extract_job_type(args, kwargs) or _job_type_from_task_name(name)
    if job_type:
        record_pipeline_job_started(_stage_from_job_type(job_type), job_type)


def _take_started(task_id: Optional[str]) -> Optional[float]:
    if not task_id:
        return None
    with _TASK_TIMES_LOCK:
        started = _TASK_START_TIMES.pop(str(task_id), None)
    if started is None:
        return None
    return max(time.perf_counter() - started, 0.0)


def _on_task_postrun(
    sender: Any = None,
    task_id: Optional[str] = None,
    task: Any = None,
    args: Any = None,
    kwargs: Any = None,
    retval: Any = None,
    state: Optional[str] = None,
    **_extra: Any,
) -> None:
    name = _task_name(task, sender)
    duration = _take_started(task_id)

    celery_tasks_total.labels(task_name=name, status="completed").inc()
    if duration is not None:
        celery_task_duration_seconds.labels(task_name=name).observe(duration)

    job_type = _extract_job_type(args, kwargs) or _job_type_from_task_name(name)
    if job_type:
        stage = _stage_from_job_type(job_type)
        record_pipeline_job_completed(stage, job_type)
        record_pipeline_job_duration(stage, job_type, duration)


def _on_task_failure(
    sender: Any = None,
    task_id: Optional[str] = None,
    task: Any = None,
    args: Any = None,
    kwargs: Any = None,
    exception: Optional[BaseException] = None,
    **_extra: Any,
) -> None:
    name = _task_name(task, sender)
    duration = _take_started(task_id)

    celery_tasks_total.labels(task_name=name, status="failed").inc()
    if duration is not None:
        celery_task_duration_seconds.labels(task_name=name).observe(duration)

    job_type = _extract_job_type(args, kwargs) or _job_type_from_task_name(name)
    if job_type:
        stage = _stage_from_job_type(job_type)
        record_pipeline_job_failed(stage, job_type)
        record_pipeline_job_duration(stage, job_type, duration)

    logger.warning(
        "Celery task %s failed (%s): %s",
        name,
        task_id or "no task id",
        type(exception).__name__ if exception is not None else "unknown error",
    )


#: Signal name -> receiver, connected by :func:`register_celery_signals`.
_SIGNAL_RECEIVERS: Dict[str, Any] = {
    "task_prerun": _on_task_prerun,
    "task_postrun": _on_task_postrun,
    "task_failure": _on_task_failure,
}


def register_celery_signals(celery_app: Any) -> bool:
    """Connect BEACON's Celery signal handlers.  Returns ``True`` on success.

    Safe to call multiple times (idempotent per app) and tolerates ``None`` /
    a Celery-less environment by returning ``False`` without raising.
    """

    if celery_app is None:
        logger.debug("register_celery_signals called without a Celery app")
        return False
    if _celery_signals is None:
        logger.warning(
            "register_celery_signals: celery is not installed; Celery task metrics "
            "will not be collected in this process"
        )
        return False

    app_key = id(celery_app)
    with _SIGNAL_LOCK:
        if app_key in _SIGNAL_APPS:
            return True

    try:
        connected = 0
        for signal_name, receiver in _SIGNAL_RECEIVERS.items():
            signal = getattr(_celery_signals, signal_name, None)
            if signal is None:  # pragma: no cover - very old Celery
                logger.warning("Celery signal %s is not available", signal_name)
                continue
            signal.connect(receiver, weak=False)
            connected += 1
        with _SIGNAL_LOCK:
            _SIGNAL_APPS.add(app_key)
        logger.info("Registered BEACON Celery signals (%d handlers)", connected)
        return connected > 0
    except Exception as exc:
        logger.warning("Could not register Celery signals: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Scrape-time integration
# ---------------------------------------------------------------------------


def refresh_celery_gauges() -> Dict[str, Any]:
    """Refresh queue-depth + worker-health gauges (used as a scrape hook)."""

    depths: Dict[str, int] = {}
    health: Dict[str, Any] = {}
    try:
        depths = queue_depth()
    except Exception:  # pragma: no cover - absolute safety net
        logger.debug("queue_depth refresh failed", exc_info=True)
    try:
        health = worker_health(refresh=True)
    except Exception:  # pragma: no cover - absolute safety net
        logger.debug("worker_health refresh failed", exc_info=True)
    return {"queues": depths, "worker_health": health}


def install_scrape_hooks() -> bool:
    """Refresh Celery gauges at scrape time.

    Controlled by ``BEACON_CELERY_METRICS_AT_SCRAPE`` (default enabled).  Returns
    ``True`` when the hook is installed.
    """

    global _SCRAPE_HOOK_INSTALLED

    enabled = os.getenv("BEACON_CELERY_METRICS_AT_SCRAPE", "1").strip().lower()
    if enabled in {"0", "false", "no", "off"}:
        return False
    if _SCRAPE_HOOK_INSTALLED:
        return True
    register_scrape_hook(refresh_celery_gauges)
    _SCRAPE_HOOK_INSTALLED = True
    logger.info(
        "BEACON metrics: Celery queue-depth/worker-health scrape hook installed "
        "(set BEACON_CELERY_METRICS_AT_SCRAPE=0 to disable)"
    )
    return True
