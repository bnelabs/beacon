"""BEACON observability package (workstream F).

Three independent, dependency-light building blocks live here:

``backend.monitoring.metrics``
    Prometheus instrumentation for HTTP, pipeline jobs, data ingestion, Celery
    tasks/queues, model inference and predictions.  ``prometheus_client`` is an
    *optional* dependency: without it every metric becomes a no-op shim so the
    application still boots and the test-suite still passes.

``backend.monitoring.drift``
    Pure-numpy data-drift detection: PSI, two-sample Kolmogorov-Smirnov (with an
    asymptotic p-value implemented from the Kolmogorov CDF series), Jensen-Shannon
    divergence, a JSON-serialisable drift report and a persistable
    :class:`~backend.monitoring.drift.FeatureDriftMonitor`.  No scipy.

``backend.monitoring.celery_health``
    Celery queue depth (Redis ``LLEN``) and worker health (Celery control API)
    plus ``task_prerun`` / ``task_postrun`` / ``task_failure`` signal hookup.
    Both ``redis`` and ``celery`` are optional at import time and every function
    degrades gracefully instead of raising.

Sub-modules are imported lazily (PEP 562) so that ``import backend.monitoring``
never pulls in an optional dependency by accident::

    from backend.monitoring import drift            # numpy only
    from backend.monitoring.metrics import setup_metrics
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

__version__ = "1.0.0"

__all__ = [
    "__version__",
    "metrics",
    "drift",
    "celery_health",
]

if TYPE_CHECKING:  # pragma: no cover - typing only
    from . import celery_health, drift, metrics


def __getattr__(name: str) -> Any:  # pragma: no cover - trivial lazy import
    """Import sub-modules on first attribute access (PEP 562)."""

    if name in {"metrics", "drift", "celery_health"}:
        import importlib

        module = importlib.import_module(f"{__name__}.{name}")
        globals()[name] = module
        return module
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:  # pragma: no cover - trivial
    return sorted(set(globals()) | set(__all__))
