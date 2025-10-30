"""Pydantic schemas for system configuration API."""

from pydantic import BaseModel, Field
from typing import Optional, Dict, Any


class SystemConfigResponse(BaseModel):
    """Schema for system configuration response."""
    model_config = {"protected_namespaces": ()}  # Allow model_ prefix

    model_params: Dict[str, Any] = Field(..., description="Model hyperparameters")
    data_params: Dict[str, Any] = Field(..., description="Data collection parameters")
    training_params: Dict[str, Any] = Field(..., description="Training parameters")
    system_info: Dict[str, Any] = Field(..., description="System information")


class ModelParamsUpdate(BaseModel):
    """Schema for updating model parameters."""
    hidden_dim: Optional[int] = Field(None, ge=16, le=1024)
    num_heads: Optional[int] = Field(None, ge=1, le=16)
    num_layers: Optional[int] = Field(None, ge=1, le=10)
    dropout: Optional[float] = Field(None, ge=0.0, le=0.9)
    learning_rate: Optional[float] = Field(None, ge=0.00001, le=0.1)


class DataParamsUpdate(BaseModel):
    """Schema for updating data parameters."""
    look_back: Optional[int] = Field(None, ge=1, le=365, description="Lookback window in days")
    correlation_threshold: Optional[float] = Field(None, ge=0.0, le=1.0)
    api_rate_limit_seconds: Optional[float] = Field(None, ge=0.1, le=60.0)


class TrainingParamsUpdate(BaseModel):
    """Schema for updating training parameters."""
    batch_size: Optional[int] = Field(None, ge=1, le=256)
    num_epochs: Optional[int] = Field(None, ge=1, le=1000)
    early_stopping_patience: Optional[int] = Field(None, ge=1, le=100)
    validation_split: Optional[float] = Field(None, ge=0.1, le=0.5)


class TrainingDefaultsResponse(BaseModel):
    """Default training configuration exposed to the frontend."""

    defaults: Dict[str, Any]
    recommended_ranges: Dict[str, Any]
