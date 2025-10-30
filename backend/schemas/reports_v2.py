"""Schemas for v2 reporting endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class JobProgressResponse(BaseModel):
    """Progress payload returned when a job is still running."""

    job_id: int
    status: str
    progress: float
    current_step: Optional[str]


class BriefQualityMetrics(BaseModel):
    completeness: Optional[float]
    consistency: Optional[float]
    timeliness: Optional[float]


class BriefReportResponse(BaseModel):
    job_id: int
    status: str
    downloaded: int
    failed: int
    fit_for_purpose_score: Optional[float]
    quality_metrics: BriefQualityMetrics
    coverage_start: Optional[datetime]
    coverage_end: Optional[datetime]
    total_observations: int
    dataset_path: Optional[str]
    regions: List[str] = Field(default_factory=list)
    countries: List[str] = Field(default_factory=list)


class DetailedAssetReport(BaseModel):
    source_code: str
    records: int
    missing_values: int
    coverage_start: Optional[datetime]
    coverage_end: Optional[datetime]
    latest_timestamp: Optional[datetime]
    latest_value: Optional[float]
    value_mean: Optional[float]
    value_std: Optional[float]
    anomaly_ratio: Optional[float]


class DetailedReportResponse(BaseModel):
    job_id: int
    status: str
    fit_for_engine: bool
    assets: List[DetailedAssetReport]
    totals: BriefQualityMetrics
    regions: List[str] = Field(default_factory=list)
    countries: List[str] = Field(default_factory=list)
