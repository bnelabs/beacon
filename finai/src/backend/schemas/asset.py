"""Pydantic schemas for asset API."""

from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class AssetBase(BaseModel):
    """Base schema for assets."""
    symbol: str = Field(..., min_length=1, max_length=20, description="Asset ticker symbol")
    name: Optional[str] = Field(None, max_length=200, description="Full name of the asset")
    asset_type: Optional[str] = Field(None, max_length=50, description="Type of asset (stock, bond, crypto, etc.)")
    sector: Optional[str] = Field(None, max_length=100, description="Sector/industry")
    region: Optional[str] = Field(None, max_length=100, description="Geographic region")
    liquidity_threshold: Optional[float] = Field(None, description="Alert threshold for liquidity risk")
    enabled: bool = Field(default=True, description="Whether this asset is being monitored")


class AssetCreate(AssetBase):
    """Schema for creating a new asset."""
    data_source_id: int = Field(..., description="ID of the data source to use")


class AssetUpdate(BaseModel):
    """Schema for updating an existing asset."""
    symbol: Optional[str] = Field(None, min_length=1, max_length=20)
    name: Optional[str] = Field(None, max_length=200)
    asset_type: Optional[str] = Field(None, max_length=50)
    sector: Optional[str] = Field(None, max_length=100)
    region: Optional[str] = Field(None, max_length=100)
    liquidity_threshold: Optional[float] = None
    enabled: Optional[bool] = None
    data_source_id: Optional[int] = None


class AssetResponse(AssetBase):
    """Schema for asset response."""
    id: int
    data_source_id: Optional[int] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_data_update: Optional[datetime] = None

    class Config:
        from_attributes = True


class AssetBulkCreate(BaseModel):
    """Schema for bulk creating assets."""
    assets: list[AssetCreate] = Field(..., description="List of assets to create")


class AssetBulkResponse(BaseModel):
    """Schema for bulk creation response."""
    created: int
    failed: int
    errors: list[str]
