"""Pydantic schemas for data source API."""

from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, Dict, Any
from datetime import datetime


class DataSourceConfigBase(BaseModel):
    """Base configuration for data sources."""
    name: str = Field(..., min_length=1, max_length=100, description="Unique name for this data source")
    plugin_type: str = Field(..., description="Plugin type (yfinance, fred, alpha_vantage, etc.)")
    config: Dict[str, Any] = Field(..., description="Plugin-specific configuration")
    description: Optional[str] = Field(None, description="Human-readable description")
    enabled: bool = Field(default=True, description="Whether this data source is enabled")
    registration_url: Optional[str] = Field(None, description="URL where users can register for API access")
    registration_required: Optional[bool] = Field(None, description="Whether API key registration is required")
    free_tier_limits: Optional[str] = Field(None, description="Description of free tier limitations")
    coverage_description: Optional[str] = Field(None, description="Description of data coverage")


class DataSourceCreate(DataSourceConfigBase):
    """Schema for creating a new data source."""
    pass


class DataSourceUpdate(BaseModel):
    """Schema for updating an existing data source.

    Every field is optional and the semantics are ``exclude_unset``: a key
    absent from the request body leaves the stored value untouched (so the
    schedule dropdown's ``{"sync_interval_minutes": 60}`` cannot clobber the
    name), while a key sent as explicit null clears the nullable columns --
    ``{"sync_interval_minutes": null}`` is how the UI returns a feed to
    manual-only, and how the edit form clears a description. The disclosure
    metadata fields mirror ``DataSourceConfigBase``; before they existed here
    the edit form collected them and Pydantic silently dropped them, so
    "Save Changes" on those inputs was a no-op that still answered 200.
    """
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    plugin_type: Optional[str] = None
    config: Optional[Dict[str, Any]] = None
    description: Optional[str] = None
    enabled: Optional[bool] = None
    registration_url: Optional[str] = None
    registration_required: Optional[bool] = None
    free_tier_limits: Optional[str] = None
    coverage_description: Optional[str] = None
    sync_interval_minutes: Optional[int] = Field(
        None,
        ge=5,
        description="Collection cadence in minutes; null means manual-only",
    )


class DataSourceResponse(DataSourceConfigBase):
    """Schema for data source response."""
    id: int
    status: str = Field(..., description="Current status (active, error, disabled)")
    error_message: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_successful_fetch: Optional[datetime] = None
    sync_interval_minutes: Optional[int] = None
    consecutive_failures: int = 0
    last_sync_started_at: Optional[datetime] = None
    last_sync_duration_ms: Optional[int] = None
    last_sync_rows: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)


class DataSourceTestRequest(BaseModel):
    """Schema for testing a data source configuration."""
    plugin_type: str
    config: Dict[str, Any]


class DataSourceTestResponse(BaseModel):
    """Schema for data source test results."""
    success: bool
    message: str
    details: Optional[Dict[str, Any]] = None
