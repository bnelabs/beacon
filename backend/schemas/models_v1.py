"""Schemas for trained model endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Dict, Any, List, Optional

from pydantic import BaseModel


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
