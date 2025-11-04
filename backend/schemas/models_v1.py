"""Schemas for trained model endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Any, List, Optional
from typing import Literal

from pydantic import BaseModel, Field


class ModelMetrics(BaseModel):
    """Model evaluation metrics."""

    mae: Optional[float] = None
    rmse: Optional[float] = None
    r2: Optional[float] = None
    accuracy: Optional[float] = None
    best_val_loss: Optional[float] = None


class ModelSummary(BaseModel):
    """Summary information for trained models."""

    model_config = {"protected_namespaces": ()}

    model_id: int
    name: str
    created_at: Optional[datetime]
    status: str
    model_type: Optional[str]
    model_version: Optional[str]
    metrics: ModelMetrics
    tags: List[str]
    data_job_id: Optional[int]
    predictions_available: bool


class ModelDetail(BaseModel):
    """Detailed information for a trained model."""

    model_config = {"protected_namespaces": ()}

    model_id: int
    created_at: Optional[datetime]
    completed_at: Optional[datetime]
    status: str
    parameters: Dict[str, Any]
    metrics: Dict[str, Any]
    result: Dict[str, Any]
    data_job_id: Optional[int]
    predictions_path: Optional[str]
    visualizations: Dict[str, Any]


class ScenarioAdjustment(BaseModel):
    """Adjustment for a scenario simulation."""

    source: str
    type: Literal['pct', 'bps', 'absolute'] = 'pct'
    value: float


class ScenarioRequest(BaseModel):
    """Scenario simulation input."""

    name: Optional[str] = None
    horizon_days: int = 30
    adjustments: List[ScenarioAdjustment] = Field(default_factory=list)


class ScenarioResponse(BaseModel):
    """Scenario simulation result."""

    scenario_id: str
    model_id: int
    name: str
    horizon_days: int
    created_at: datetime
    summary: Dict[str, Any]
    predictions: List[Dict[str, Any]]
    adjustments: List[ScenarioAdjustment] = Field(default_factory=list)
    executive_summary: Optional[str] = None
    feature_importances: Dict[str, float] = Field(default_factory=dict)
    storage_path: Optional[str] = None
