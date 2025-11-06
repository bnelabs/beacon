"""Pydantic schemas for job API."""

from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Dict, Any
from datetime import datetime


class JobBase(BaseModel):
    """Base schema for jobs."""
    job_type: str = Field(..., description="Type of job (data_collection, training, prediction, backtest)")
    parameters: Optional[Dict[str, Any]] = Field(None, description="Job parameters")


class JobCreate(JobBase):
    """Schema for creating a new job."""
    pass


class JobResponse(JobBase):
    """Schema for job response."""
    id: int
    celery_task_id: Optional[str] = None
    status: str = Field(..., description="Job status (pending, running, completed, failed)")
    progress: float = Field(default=0.0, ge=0.0, le=100.0, description="Progress percentage")
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    user_friendly_error: Optional[str] = None
    created_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    peak_memory_mb: Optional[float] = None
    execution_time_seconds: Optional[float] = None

    model_config = ConfigDict(from_attributes=True)


class JobStatusUpdate(BaseModel):
    """Schema for updating job status."""
    status: str
    progress: Optional[float] = None
    error_message: Optional[str] = None
    user_friendly_error: Optional[str] = None


class JobListFilter(BaseModel):
    """Schema for filtering job list."""
    job_type: Optional[str] = None
    status: Optional[str] = None
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)


class BatchCancelRequest(BaseModel):
    """Schema for batch canceling jobs."""
    job_ids: list[int] = Field(..., description="List of job IDs to cancel", min_length=1, max_length=50)


class BatchCancelResponse(BaseModel):
    """Schema for batch cancel response."""
    cancelled: list[int] = Field(..., description="List of successfully cancelled job IDs")
    failed: list[dict[str, Any]] = Field(..., description="List of jobs that failed to cancel with reasons")
    total_requested: int = Field(..., description="Total number of jobs requested to cancel")
    total_cancelled: int = Field(..., description="Total number of jobs successfully cancelled")
