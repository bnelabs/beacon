"""Pydantic schemas for alert rules."""

from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Dict, Any
from datetime import datetime


class AlertRuleBase(BaseModel):
    """Base alert rule schema."""
    name: str = Field(..., max_length=200)
    description: Optional[str] = None
    category: str  # data_quality, model_performance, job_execution, system_health
    metric_type: str  # quality_score, success_rate, rmse, execution_time
    condition_operator: str  # lt, lte, gt, gte, eq, neq
    threshold_value: float
    evaluation_window_minutes: int = 60
    evaluation_frequency_minutes: int = 15
    notification_priority: str = 'medium'
    notification_message_template: Optional[str] = None
    rule_config: Optional[Dict[str, Any]] = None


class AlertRuleCreate(AlertRuleBase):
    """Schema for creating alert rule."""
    pass


class AlertRuleUpdate(BaseModel):
    """Schema for updating alert rule."""
    name: Optional[str] = Field(None, max_length=200)
    description: Optional[str] = None
    threshold_value: Optional[float] = None
    is_enabled: Optional[bool] = None
    notification_priority: Optional[str] = None
    evaluation_window_minutes: Optional[int] = None
    evaluation_frequency_minutes: Optional[int] = None


class AlertRuleResponse(AlertRuleBase):
    """Schema for alert rule response."""
    id: int
    is_enabled: bool
    is_active: bool
    trigger_count: int
    last_triggered_at: Optional[datetime] = None
    last_evaluated_at: Optional[datetime] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    created_by: str

    model_config = ConfigDict(from_attributes=True)


class AlertRuleListResponse(BaseModel):
    """Schema for alert rule list response."""
    rules: list[AlertRuleResponse]
    total: int
