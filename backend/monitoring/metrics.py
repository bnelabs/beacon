"""Prometheus instrumentation for the BEACON platform (workstream F).

Chosen client library
---------------------
This module uses **``prometheus_client`` directly** (the official Python client)
rather than ``prometheus-fastapi-instrumentator``.  Reasons:

* BEACON needs a large set of *domain* metrics (pipeline stages, ingestion
  failures per plugin, feature drift, predictions per region/risk level) that an
  out-of-the-box instrumentator does not provide, so the instrumentator would
  only replace ~30 lines of HTTP middleware while adding a dependency.
* The module must degrade to no-op shims when ``prometheus_client`` is not
  installed (hard requirement: the app must boot and the test-suite must pass
  without it), which is far easier to guarantee when we control metric
  construction ourselves.

Optional dependency
-------------------
``prometheus_client`` is *optional* here.  Every metric in this module is either
a real client metric or a silently-discarding shim, so the FastAPI application
and the Celery worker import fine without it -- ``/metrics`` simply reports that
metrics are disabled.

Celery multiprocess mode
------------------------
Celery prefork workers execute tasks in several processes.  To aggregate those
processes into one exposition set ``PROMETHEUS_MULTIPROC_DIR`` must be set
**before the Python process starts** (``prometheus_client`` reads it at import
time to select its mmap value backend) and must point at a directory that every
worker process can write to::

    ENV PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus-multiproc
    # created once at container start, wiped between restarts:
    CMD mkdir -p "$PROMETHEUS_MULTIPROC_DIR" && \
        celery -A backend.tasks.celery_app worker --loglevel=info

When the variable is set this module registers
``prometheus_client.multiprocess.MultiProcessCollector`` on its registry and the
gauges are declared with an explicit ``multiprocess_mode`` (``max`` for PSI and
worker counts, so a single high-drifting/one-live-worker sample is not
diluted).  A scrape of any single worker process then returns values aggregated
across all worker processes.

Do **not** set ``PROMETHEUS_MULTIPROC_DIR`` for the API process: it would make
``process_*`` metrics meaningless and requires the same directory to be shared.
The API is single-process (uvicorn), so it exposes its registry directly.

Scrape-time hooks
-----------------
Some metrics are naturally sampled "at scrape time" (Celery queue depth, worker
liveness).  :func:`register_scrape_hook` lets other modules -- notably
:mod:`backend.monitoring.celery_health` -- refresh those gauges just before the
exposition is rendered.  Hooks are run inside a ``try/except`` so a broken hook
can never break ``/metrics``.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterable, Iterator, Optional, Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Optional dependency detection / shims
# ---------------------------------------------------------------------------

try:  # pragma: no cover - exercised implicitly by both environments
    import prometheus_client as _prometheus_client
    from prometheus_client import (
        CONTENT_TYPE_LATEST as _CONTENT_TYPE_LATEST,
        CollectorRegistry as _CollectorRegistry,
        Counter as _Counter,
        Gauge as _Gauge,
        Histogram as _Histogram,
        generate_latest as _generate_latest,
    )

    PROMETHEUS_AVAILABLE = True
except ImportError:  # pragma: no cover - environment dependent
    _prometheus_client = None  # type: ignore[assignment]
    PROMETHEUS_AVAILABLE = False
    _CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    _CollectorRegistry = None  # type: ignore[assignment]
    _Counter = None  # type: ignore[assignment]
    _Gauge = None  # type: ignore[assignment]
    _Histogram = None  # type: ignore[assignment]
    _generate_latest = None  # type: ignore[assignment]

CONTENT_TYPE_LATEST = _CONTENT_TYPE_LATEST

#: Human readable reason used by :func:`render_metrics` when metrics are off.
DISABLED_NOTICE = (
    b"# prometheus_client is not installed; BEACON metrics are disabled.\n"
    b"# Install the optional dependency (prometheus-client) to enable them.\n"
)

# ---------------------------------------------------------------------------
# Registry (multiprocess aware)
# ---------------------------------------------------------------------------

#: ``prometheus_client`` reads this at *its* import time; we only read it to
#: decide whether to install the multiprocess collector.
MULTIPROCESS_DIR: Optional[str] = os.getenv("PROMETHEUS_MULTIPROC_DIR") or os.getenv(
    "prometheus_multiproc_dir"
)


def _build_registry() -> Any:
    """Create an isolated collector registry (reload-safe, multiprocess aware)."""

    if not PROMETHEUS_AVAILABLE:
        return None

    registry = _CollectorRegistry()

    if MULTIPROCESS_DIR:
        try:
            os.makedirs(MULTIPROCESS_DIR, exist_ok=True)
            from prometheus_client.multiprocess import MultiProcessCollector

            MultiProcessCollector(registry, path=MULTIPROCESS_DIR)
            logger.info(
                "BEACON metrics: Celery multiprocess mode enabled (PROMETHEUS_MULTIPROC_DIR=%s)",
                MULTIPROCESS_DIR,
            )
            return registry
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning(
                "BEACON metrics: multiprocess directory %r unusable (%s); "
                "falling back to in-process metrics",
                MULTIPROCESS_DIR,
                exc,
            )

    try:
        from prometheus_client import PlatformCollector, ProcessCollector

        ProcessCollector(registry=registry)
        PlatformCollector(registry=registry)
    except Exception as exc:  # pragma: no cover - defensive
        logger.debug("BEACON metrics: process/platform collectors unavailable: %s", exc)

    return registry


#: Registry used by every BEACON metric.  A private registry (instead of the
#: client's global one) keeps the module reload-safe and multiprocess friendly.
REGISTRY = _build_registry()

MULTIPROCESS_ENABLED = bool(MULTIPROCESS_DIR) and PROMETHEUS_AVAILABLE


class _NoOpMetric:
    """Stand-in for a prometheus_client metric when the package is missing.

    Mirrors just enough of the client API (``labels``/``inc``/``observe``/
    ``set``/``remove``) for application code and tests to run unchanged.
    """

    __slots__ = ("_name", "_documentation", "_labelnames")

    def __init__(
        self,
        name: str,
        documentation: str = "",
        labelnames: Sequence[str] = (),
    ) -> None:
        self._name = name
        self._documentation = documentation
        self._labelnames = tuple(labelnames)

    # -- prometheus_client surface -----------------------------------------
    @property
    def _name_(self) -> str:
        return self._name

    def labels(self, *args: Any, **kwargs: Any) -> "_NoOpMetric":
        return self

    def inc(self, amount: float = 1.0) -> None:
        return None

    def dec(self, amount: float = 1.0) -> None:
        return None

    def observe(self, amount: float) -> None:
        return None

    def set(self, value: float) -> None:
        return None

    def set_to_current_time(self) -> None:
        return None

    def reset(self) -> None:
        return None

    def remove(self, *args: Any, **kwargs: Any) -> None:
        return None

    def collect(self) -> Iterator[Any]:
        return iter(())

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<_NoOpMetric {self._name}>"


def _counter(
    name: str,
    documentation: str,
    labelnames: Sequence[str] = (),
) -> Any:
    if PROMETHEUS_AVAILABLE:
        try:
            return _Counter(name, documentation, labelnames, registry=REGISTRY)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("BEACON metrics: could not create counter %s: %s", name, exc)
    return _NoOpMetric(name, documentation, labelnames)


def _histogram(
    name: str,
    documentation: str,
    labelnames: Sequence[str] = (),
    buckets: Optional[Sequence[float]] = None,
) -> Any:
    if PROMETHEUS_AVAILABLE:
        try:
            kwargs: dict[str, Any] = {"registry": REGISTRY}
            if buckets:
                kwargs["buckets"] = tuple(buckets)
            return _Histogram(name, documentation, labelnames, **kwargs)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("BEACON metrics: could not create histogram %s: %s", name, exc)
    return _NoOpMetric(name, documentation, labelnames)


def _gauge(
    name: str,
    documentation: str,
    labelnames: Sequence[str] = (),
    multiprocess_mode: Optional[str] = None,
) -> Any:
    if PROMETHEUS_AVAILABLE:
        kwargs: dict[str, Any] = {"registry": REGISTRY}
        if multiprocess_mode:
            kwargs["multiprocess_mode"] = multiprocess_mode
        try:
            return _Gauge(name, documentation, labelnames, **kwargs)
        except TypeError:
            # Older/other client builds without multiprocess_mode support.
            kwargs.pop("multiprocess_mode", None)
            try:
                return _Gauge(name, documentation, labelnames, **kwargs)
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(
                    "BEACON metrics: could not create gauge %s: %s", name, exc
                )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("BEACON metrics: could not create gauge %s: %s", name, exc)
    return _NoOpMetric(name, documentation, labelnames)


# ---------------------------------------------------------------------------
# Bucket definitions
# ---------------------------------------------------------------------------

#: HTTP latency buckets in seconds (5ms .. 10s).
HTTP_LATENCY_BUCKETS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)

#: Model inference latency buckets in seconds (10ms .. 30s; GNN inference is slow).
INFERENCE_LATENCY_BUCKETS: tuple[float, ...] = (
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
)

#: Celery / pipeline job duration buckets in seconds (0.1s .. 1h).
JOB_DURATION_BUCKETS: tuple[float, ...] = (
    0.1,
    0.5,
    1.0,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
    300.0,
    900.0,
    1800.0,
    3600.0,
)

# ---------------------------------------------------------------------------
# HTTP metrics
# ---------------------------------------------------------------------------

http_requests_total = _counter(
    "beacon_http_requests_total",
    "Total HTTP requests handled by the BEACON API.",
    ("method", "route", "status"),
)

http_request_duration_seconds = _histogram(
    "beacon_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ("method", "route"),
    HTTP_LATENCY_BUCKETS,
)

# ---------------------------------------------------------------------------
# Pipeline job metrics
# ---------------------------------------------------------------------------

pipeline_jobs_started_total = _counter(
    "beacon_pipeline_jobs_started_total",
    "Total pipeline jobs started.",
    ("stage", "job_type"),
)

pipeline_jobs_completed_total = _counter(
    "beacon_pipeline_jobs_completed_total",
    "Total pipeline jobs completed successfully.",
    ("stage", "job_type"),
)

pipeline_jobs_failed_total = _counter(
    "beacon_pipeline_jobs_failed_total",
    "Total pipeline jobs that failed.",
    ("stage", "job_type"),
)

pipeline_job_duration_seconds = _histogram(
    "beacon_pipeline_job_duration_seconds",
    "Pipeline job wall-clock duration in seconds.",
    ("stage", "job_type"),
    JOB_DURATION_BUCKETS,
)

# ---------------------------------------------------------------------------
# Data ingestion metrics
# ---------------------------------------------------------------------------

data_ingestion_attempts_total = _counter(
    "beacon_data_ingestion_attempts_total",
    "Total data ingestion attempts by plugin and outcome.",
    ("plugin", "status"),
)

data_ingestion_failures_total = _counter(
    "beacon_data_ingestion_failures_total",
    "Total data ingestion failures by plugin and error code.",
    ("plugin", "error_code"),
)

data_ingestion_records_total = _counter(
    "beacon_data_ingestion_records_total",
    "Total records successfully ingested by plugin.",
    ("plugin",),
)

# ---------------------------------------------------------------------------
# Celery metrics
# ---------------------------------------------------------------------------

celery_tasks_total = _counter(
    "beacon_celery_tasks_total",
    "Total Celery tasks observed, by task name and terminal/running status.",
    ("task_name", "status"),
)

celery_task_duration_seconds = _histogram(
    "beacon_celery_task_duration_seconds",
    "Celery task execution duration in seconds.",
    ("task_name",),
    JOB_DURATION_BUCKETS,
)

celery_queue_depth = _gauge(
    "beacon_celery_queue_depth",
    "Number of pending messages per Celery queue (Redis LLEN).",
    ("queue",),
    multiprocess_mode="max",
)

celery_workers_online = _gauge(
    "beacon_celery_workers_online",
    "Number of live Celery workers (pool='all' plus each configured/derived pool).",
    ("pool",),
    multiprocess_mode="max",
)

celery_worker_tasks = _gauge(
    "beacon_celery_worker_tasks",
    "In-flight Celery task counts across live workers, by state.",
    ("state",),
    multiprocess_mode="max",
)

# ---------------------------------------------------------------------------
# Model inference / prediction metrics
# ---------------------------------------------------------------------------

model_inference_latency_seconds = _histogram(
    "beacon_model_inference_latency_seconds",
    "Model inference latency in seconds.",
    ("model",),
    INFERENCE_LATENCY_BUCKETS,
)

model_inference_errors_total = _counter(
    "beacon_model_inference_errors_total",
    "Total model inference errors by model and error code.",
    ("model", "error_code"),
)

predictions_total = _counter(
    "beacon_predictions_total",
    "Total individual predictions produced, by region and risk level.",
    ("region", "risk_level"),
)

# ---------------------------------------------------------------------------
# Data drift metric (written by backend.monitoring.drift)
# ---------------------------------------------------------------------------

feature_drift_psi = _gauge(
    "beacon_feature_drift_psi",
    "Population Stability Index of the live feature distribution versus the "
    "training reference distribution (PSI < 0.1 none, 0.1-0.25 moderate, > 0.25 major).",
    ("feature",),
    multiprocess_mode="max",
)

# ---------------------------------------------------------------------------
# Scrape-time hooks
# ---------------------------------------------------------------------------

_scrape_hooks: list[Callable[[], Any]] = []
_scrape_hooks_lock = threading.Lock()


def register_scrape_hook(hook: Callable[[], Any]) -> None:
    """Register ``hook`` to run right before the exposition is rendered.

    Hooks are best-effort: exceptions are logged and swallowed so a broken
    integration can never take ``/metrics`` down.
    """

    if not callable(hook):
        raise TypeError("scrape hook must be callable")
    with _scrape_hooks_lock:
        if hook not in _scrape_hooks:
            _scrape_hooks.append(hook)


def clear_scrape_hooks() -> None:
    """Remove every registered scrape hook (used by tests)."""

    with _scrape_hooks_lock:
        _scrape_hooks.clear()


def _run_scrape_hooks() -> None:
    with _scrape_hooks_lock:
        hooks = list(_scrape_hooks)
    for hook in hooks:
        try:
            hook()
        except Exception:  # pragma: no cover - hooks must never break /metrics
            logger.warning("BEACON metrics: scrape hook %r failed", hook, exc_info=True)


# ---------------------------------------------------------------------------
# Recording helpers used by application / worker code
# ---------------------------------------------------------------------------

#: Canonical BEACON pipeline stages.
PIPELINE_STAGES: tuple[str, ...] = (
    "ingestion",
    "training",
    "inference",
    "backtest",
    "explainability",
)

#: Canonical BEACON job types (see backend/tasks/celery_app.dispatch_job).
KNOWN_JOB_TYPES: tuple[str, ...] = (
    "data_collection",
    "training",
    "prediction",
    "backtest",
)

#: Canonical risk levels used by the risk engine.
KNOWN_RISK_LEVELS: tuple[str, ...] = ("low", "medium", "high", "critical")


def record_http_request(
    method: str,
    route: str,
    status: Any,
    duration_seconds: Optional[float] = None,
) -> None:
    """Record one HTTP request (used by the middleware, also handy in tests)."""

    status_label = str(status)
    http_requests_total.labels(method=method, route=route, status=status_label).inc()
    if duration_seconds is not None:
        http_request_duration_seconds.labels(method=method, route=route).observe(
            max(float(duration_seconds), 0.0)
        )


def record_pipeline_job_started(stage: str, job_type: str) -> None:
    pipeline_jobs_started_total.labels(stage=stage, job_type=job_type).inc()


def record_pipeline_job_completed(
    stage: str, job_type: str, duration_seconds: Optional[float] = None
) -> None:
    pipeline_jobs_completed_total.labels(stage=stage, job_type=job_type).inc()
    record_pipeline_job_duration(stage, job_type, duration_seconds)


def record_pipeline_job_failed(
    stage: str, job_type: str, duration_seconds: Optional[float] = None
) -> None:
    pipeline_jobs_failed_total.labels(stage=stage, job_type=job_type).inc()
    record_pipeline_job_duration(stage, job_type, duration_seconds)


def record_pipeline_job_duration(
    stage: str, job_type: str, duration_seconds: Optional[float]
) -> None:
    if duration_seconds is None:
        return
    pipeline_job_duration_seconds.labels(stage=stage, job_type=job_type).observe(
        max(float(duration_seconds), 0.0)
    )


@contextmanager
def pipeline_job_timer(stage: str, job_type: str) -> Iterator[None]:
    """Context manager recording started/completed/failed + duration::

        with pipeline_job_timer("training", "training"):
            run_training(...)
    """

    started = time.perf_counter()
    record_pipeline_job_started(stage, job_type)
    try:
        yield
    except BaseException:
        record_pipeline_job_failed(stage, job_type, time.perf_counter() - started)
        raise
    else:
        record_pipeline_job_completed(stage, job_type, time.perf_counter() - started)


def record_ingestion_attempt(
    plugin: str,
    success: bool = True,
    error_code: Optional[str] = None,
    records: Optional[int] = None,
) -> None:
    """Record one ingestion attempt, optionally a failure with an error code."""

    plugin_label = plugin or "unknown"
    status = "success" if success else "failure"
    data_ingestion_attempts_total.labels(plugin=plugin_label, status=status).inc()
    if success:
        if records:
            data_ingestion_records_total.labels(plugin=plugin_label).inc(int(records))
        return
    record_ingestion_failure(plugin_label, error_code or "unknown")


def record_ingestion_failure(plugin_type: str, error_code: str) -> None:
    """Increment the data-ingestion failure counter for a plugin/error code.

    Public interface used by ``backend/modules/data/collector.py``:

        from backend.monitoring.metrics import record_ingestion_failure

        record_ingestion_failure(plugin_type, error_code)

    Emits ``beacon_data_ingestion_failures_total{plugin, error_code}``.  It is a
    safe no-op when ``prometheus_client`` is not installed.
    """

    data_ingestion_failures_total.labels(
        plugin=plugin_type or "unknown", error_code=error_code or "unknown"
    ).inc()


def record_celery_task(
    task_name: str, status: str, duration_seconds: Optional[float] = None
) -> None:
    name = task_name or "unknown"
    celery_tasks_total.labels(task_name=name, status=status or "unknown").inc()
    if duration_seconds is not None:
        celery_task_duration_seconds.labels(task_name=name).observe(
            max(float(duration_seconds), 0.0)
        )


def record_inference(
    model: str,
    duration_seconds: Optional[float] = None,
    success: bool = True,
    error_code: Optional[str] = None,
) -> None:
    model_label = model or "unknown"
    if duration_seconds is not None:
        model_inference_latency_seconds.labels(model=model_label).observe(
            max(float(duration_seconds), 0.0)
        )
    if not success:
        model_inference_errors_total.labels(
            model=model_label, error_code=error_code or "unknown"
        ).inc()


def record_prediction(
    region: str,
    risk_level: str,
    count: int = 1,
    model: Optional[str] = None,
    duration_seconds: Optional[float] = None,
    success: bool = True,
) -> None:
    """Record ``count`` predictions for a region/risk-level bucket."""

    predictions_total.labels(
        region=region or "unknown", risk_level=risk_level or "unknown"
    ).inc(int(count))
    if model is not None or duration_seconds is not None:
        record_inference(
            model or "unknown",
            duration_seconds=duration_seconds,
            success=success,
        )


# ---------------------------------------------------------------------------
# Exposition
# ---------------------------------------------------------------------------


def render_metrics() -> bytes:
    """Return the Prometheus exposition payload as bytes (no HTTP involved)."""

    _run_scrape_hooks()
    if not PROMETHEUS_AVAILABLE:
        return DISABLED_NOTICE
    return _generate_latest(REGISTRY)


class _SimpleResponse:
    """Minimal Starlette-compatible response used when Starlette is absent."""

    status_code = 200

    def __init__(self, content: bytes, media_type: str) -> None:
        self.body = content
        self.media_type = media_type
        self.content_type = media_type
        self.headers: dict[str, str] = {"content-type": media_type}

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<_SimpleResponse {self.status_code} {self.media_type!r} {len(self.body)}B>"


def metrics_endpoint() -> Any:
    """``/metrics`` handler: return the Prometheus exposition response.

    Works with Starlette/FastAPI when installed and degrades to a tiny response
    object otherwise, so the function is unit-testable without FastAPI.
    """

    payload = render_metrics()
    media_type = CONTENT_TYPE_LATEST
    try:
        from starlette.responses import Response  # type: ignore

        return Response(content=payload, media_type=media_type)
    except ImportError:
        pass
    try:
        from fastapi import Response  # type: ignore

        return Response(content=payload, media_type=media_type)
    except ImportError:
        return _SimpleResponse(payload, media_type)


# ---------------------------------------------------------------------------
# FastAPI wiring
# ---------------------------------------------------------------------------

_ID_SEGMENT = re.compile(
    r"^(?:\d+|[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"|[0-9a-fA-F]{16,})$"
)


def _normalise_path(path: str, max_segments: int = 12) -> str:
    """Collapse high-cardinality path segments (ids/uuids/hashes) to ``:id``."""

    segments = [segment for segment in (path or "/").split("/")]
    normalised = [":id" if _ID_SEGMENT.match(segment) else segment for segment in segments]
    if len(normalised) > max_segments:
        normalised = normalised[:max_segments] + ["..."]
    collapsed = "/".join(normalised)
    if not collapsed.startswith("/"):
        collapsed = "/" + collapsed
    # Cap pathological single-segment paths such as free-form slugs.
    return collapsed[:200]


def _route_label(request: Any) -> str:
    """Best-effort *templated* route label for a Starlette request."""

    try:
        route = request.scope.get("route")
    except Exception:  # pragma: no cover - defensive
        route = None
    template = getattr(route, "path", None)
    if template:
        return template
    try:
        return _normalise_path(request.url.path)
    except Exception:  # pragma: no cover - defensive
        return "<unmatched>"


def _build_middleware(base_class: Any, exclude_paths: Iterable[str]) -> Any:
    """Create the ASGI/based HTTP middleware class measuring request latency."""

    excluded = frozenset(exclude_paths or ())

    class _BeaconMetricsMiddleware(base_class):  # type: ignore[misc, valid-type]
        async def dispatch(self, request: Any, call_next: Any) -> Any:
            if request.url.path in excluded:
                return await call_next(request)

            method = request.method
            started = time.perf_counter()
            try:
                response = await call_next(request)
            except Exception:
                route = _route_label(request)
                record_http_request(
                    method, route, "500", time.perf_counter() - started
                )
                raise
            route = _route_label(request)
            record_http_request(
                method, route, response.status_code, time.perf_counter() - started
            )
            return response

    _BeaconMetricsMiddleware.__name__ = "BeaconMetricsMiddleware"
    return _BeaconMetricsMiddleware


def setup_metrics(
    app: Any,
    *,
    service: str = "beacon-api",
    exclude_paths: Sequence[str] = ("/metrics",),
    instrument_http: bool = True,
) -> Any:
    """Attach HTTP instrumentation and the ``/metrics`` route to ``app``.

    Safe to call when ``prometheus_client`` is missing (the endpoint then
    reports that metrics are disabled) and safe to call twice (the route is not
    duplicated).  Never raises: a failure to instrument must not stop the API
    from booting.
    """

    if app is None:
        return app

    if instrument_http and PROMETHEUS_AVAILABLE:
        try:
            from starlette.middleware.base import BaseHTTPMiddleware

            app.add_middleware(_build_middleware(BaseHTTPMiddleware, exclude_paths))
        except Exception:  # pragma: no cover - defensive
            logger.warning("BEACON metrics: HTTP middleware not installed", exc_info=True)

    # Register GET /metrics exactly once.
    try:
        routes = getattr(app, "routes", None) or []
        already = any(getattr(route, "path", None) == "/metrics" for route in routes)
        if not already and hasattr(app, "get"):

            async def _metrics_route() -> Any:  # pragma: no cover - exercised via HTTP
                return metrics_endpoint()

            _metrics_route.__name__ = "beacon_metrics"
            app.get("/metrics", include_in_schema=False, name="beacon_metrics")(
                _metrics_route
            )
    except Exception:  # pragma: no cover - defensive
        logger.warning("BEACON metrics: /metrics route not registered", exc_info=True)

    logger.info(
        "BEACON metrics: service=%s prometheus_client=%s multiprocess=%s",
        service,
        PROMETHEUS_AVAILABLE,
        MULTIPROCESS_ENABLED,
    )
    return app


#: Names of every metric exposed by this module (dashboards/alerts/tests).
METRIC_NAMES: tuple[str, ...] = (
    "beacon_http_requests_total",
    "beacon_http_request_duration_seconds",
    "beacon_pipeline_jobs_started_total",
    "beacon_pipeline_jobs_completed_total",
    "beacon_pipeline_jobs_failed_total",
    "beacon_pipeline_job_duration_seconds",
    "beacon_data_ingestion_attempts_total",
    "beacon_data_ingestion_failures_total",
    "beacon_data_ingestion_records_total",
    "beacon_celery_tasks_total",
    "beacon_celery_task_duration_seconds",
    "beacon_celery_queue_depth",
    "beacon_celery_workers_online",
    "beacon_celery_worker_tasks",
    "beacon_model_inference_latency_seconds",
    "beacon_model_inference_errors_total",
    "beacon_predictions_total",
    "beacon_feature_drift_psi",
)

__all__ = [
    "PROMETHEUS_AVAILABLE",
    "MULTIPROCESS_DIR",
    "MULTIPROCESS_ENABLED",
    "REGISTRY",
    "CONTENT_TYPE_LATEST",
    "DISABLED_NOTICE",
    "METRIC_NAMES",
    "HTTP_LATENCY_BUCKETS",
    "INFERENCE_LATENCY_BUCKETS",
    "JOB_DURATION_BUCKETS",
    "PIPELINE_STAGES",
    "KNOWN_JOB_TYPES",
    "KNOWN_RISK_LEVELS",
    # metrics
    "http_requests_total",
    "http_request_duration_seconds",
    "pipeline_jobs_started_total",
    "pipeline_jobs_completed_total",
    "pipeline_jobs_failed_total",
    "pipeline_job_duration_seconds",
    "data_ingestion_attempts_total",
    "data_ingestion_failures_total",
    "data_ingestion_records_total",
    "celery_tasks_total",
    "celery_task_duration_seconds",
    "celery_queue_depth",
    "celery_workers_online",
    "celery_worker_tasks",
    "model_inference_latency_seconds",
    "model_inference_errors_total",
    "predictions_total",
    "feature_drift_psi",
    # helpers
    "record_http_request",
    "record_pipeline_job_started",
    "record_pipeline_job_completed",
    "record_pipeline_job_failed",
    "record_pipeline_job_duration",
    "pipeline_job_timer",
    "record_ingestion_attempt",
    "record_ingestion_failure",
    "record_celery_task",
    "record_inference",
    "record_prediction",
    "render_metrics",
    "metrics_endpoint",
    "setup_metrics",
    "register_scrape_hook",
    "clear_scrape_hooks",
]
