"""Schemas for prediction/backtest exploration."""

from __future__ import annotations

from datetime import datetime
from typing import List, Dict, Any, Optional

from pydantic import BaseModel


class PredictionNode(BaseModel):
    source: str
    # Optional because a refused prediction has no score: NaN is not a number
    # this API may turn into 0.0 (a fabricated calm) or into "whatever numeric
    # column happens to be last" -- absence travels as null, per the platform
    # rule. `additional` carries why (uncertainty_status/uncertainty_reasons).
    risk: Optional[float]
    confidence_lower: Optional[float]
    confidence_upper: Optional[float]
    additional: Dict[str, Any] = {}


class PredictionTimeline(BaseModel):
    timestamp: Optional[datetime]
    nodes: List[PredictionNode]


class PredictionReport(BaseModel):
    job_id: int
    status: str
    summary_metrics: Dict[str, Any]
    feature_importances: Dict[str, float]
    nodes: List[PredictionNode]
    timeline: List[PredictionTimeline]


class BacktestReport(BaseModel):
    job_id: int
    status: str
    metrics: Dict[str, Any]
    metadata: Dict[str, Any]
    quant_metrics: Optional[Dict[str, Any]] = None
    walk_forward: Optional[Dict[str, Any]] = None
