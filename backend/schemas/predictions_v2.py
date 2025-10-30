"""Schemas for prediction/backtest exploration."""

from __future__ import annotations

from datetime import datetime
from typing import List, Dict, Any, Optional

from pydantic import BaseModel


class PredictionNode(BaseModel):
    source: str
    risk: float
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
