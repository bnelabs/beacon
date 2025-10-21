"""Schemas for data catalogue."""

from pydantic import BaseModel, ConfigDict
from typing import List, Optional
from datetime import datetime
from models.data_catalogue import DataCategory, DataRegion, RiskType


class DataSourceInfo(BaseModel):
    """Data source basic information."""
    id: int
    name: str
    plugin_type: str
    model_config = ConfigDict(from_attributes=True)


class DataCatalogueItemResponse(BaseModel):
    """Response model for catalogue item."""

    id: int
    code: str
    name: str
    description: Optional[str]

    category: DataCategory
    region: DataRegion
    risk_types: List[str]

    data_source_id: int
    data_source: Optional[DataSourceInfo] = None
    endpoint: Optional[str]
    frequency: Optional[str]
    granularity: Optional[str]
    unit: Optional[str]

    enabled: bool
    default_selected: bool
    priority: int

    tags: List[str]

    created_at: datetime
    updated_at: Optional[datetime]
    last_data_update: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class CatalogueFilterRequest(BaseModel):
    """Request model for filtering catalogue."""

    categories: Optional[List[DataCategory]] = None
    regions: Optional[List[DataRegion]] = None
    risk_types: Optional[List[RiskType]] = None
    search: Optional[str] = None
    enabled_only: bool = True
    default_only: bool = False


class CatalogueSummaryResponse(BaseModel):
    """Summary statistics for catalogue."""

    total_items: int
    by_category: dict
    by_region: dict
    by_risk_type: dict
    default_selected_count: int
    enabled_count: int


class BulkCatalogueSelectRequest(BaseModel):
    """Request to select/deselect multiple catalogue items."""

    item_codes: List[str]
    action: str  # "enable" or "disable"
