"""Schemas for v2 data exploration endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel


class DataSourceCoverage(BaseModel):
    """Coverage metadata for a data source."""

    start: Optional[datetime]
    end: Optional[datetime]
    frequency: List[str]
    asset_count: int


class DataSourceV2Response(BaseModel):
    """Enriched response for data sources used in the v2 UI."""

    id: int
    name: str
    plugin_type: str
    enabled: bool
    status: Optional[str]
    description: Optional[str]
    regions: List[str]
    categories: List[str]
    risk_types: List[str]
    coverage: DataSourceCoverage
    payload_capabilities: Dict[str, Any]


class DataSourceListResponse(BaseModel):
    """Wrapper for datasource list response."""

    regions: List[str]
    sources: List[DataSourceV2Response]
    other_connectors_supported: bool = True


class CatalogueCoverage(BaseModel):
    """Coverage metadata for a specific catalogue asset."""

    start: Optional[datetime]
    end: Optional[datetime]
    frequency: Optional[str]
    missing_ratio: Optional[float]
    anomaly_score: Optional[float]


class CatalogueAssetResponse(BaseModel):
    """Response model for catalogue items in v2 UI."""

    id: int
    code: str
    name: str
    description: Optional[str]
    category: str
    region: str
    risk_types: List[str]
    data_source_id: int
    data_source_name: Optional[str]
    frequency: Optional[str]
    granularity: Optional[str]
    unit: Optional[str]
    enabled: bool
    default_selected: bool
    tags: List[str]
    priority: int
    coverage: CatalogueCoverage


class CatalogueListResponse(BaseModel):
    """Paginated response for catalogue listing."""

    page: int
    page_size: int
    total: int
    assets: List[CatalogueAssetResponse]

