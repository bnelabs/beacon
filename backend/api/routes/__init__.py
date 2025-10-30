"""API routes."""

from . import (
    data_sources,
    assets,
    jobs,
    config,
    system,
    errors,
    catalogue,
    pipeline,
    results,
    explainability,
    data_explorer_v2,
    reports_v2,
    models_v1,
    predictions_v2,
)

__all__ = [
    "data_sources",
    "assets",
    "jobs",
    "config",
    "system",
    "errors",
    "catalogue",
    "pipeline",
    "results",
    "explainability",
    "data_explorer_v2",
    "reports_v2",
    "models_v1",
    "predictions_v2",
]
