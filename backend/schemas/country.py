"""Pydantic schemas for country profiles."""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from decimal import Decimal


class CountryProfileBase(BaseModel):
    """Base country profile schema."""

    country_code: str = Field(..., min_length=2, max_length=3, description="ISO 3166-1 alpha-2 or alpha-3 code")
    country_name: str = Field(..., max_length=100)
    region: Optional[str] = Field(None, max_length=50)
    sub_region: Optional[str] = Field(None, max_length=100)
    iso_alpha_3: Optional[str] = Field(None, max_length=3)
    capital: Optional[str] = Field(None, max_length=100)
    currency: Optional[str] = Field(None, max_length=50)
    latitude: Optional[Decimal] = None
    longitude: Optional[Decimal] = None


class CountryProfileCreate(CountryProfileBase):
    """Schema for creating a country profile."""

    population: Optional[int] = None
    gdp_usd: Optional[Decimal] = None
    gdp_per_capita: Optional[Decimal] = None
    gdp_growth_rate: Optional[Decimal] = None
    inflation_rate: Optional[Decimal] = None
    unemployment_rate: Optional[Decimal] = None
    credit_to_gdp: Optional[Decimal] = None
    debt_to_gdp: Optional[Decimal] = None
    fiscal_balance: Optional[Decimal] = None
    current_account_balance: Optional[Decimal] = None
    bank_count: Optional[int] = None
    total_bank_assets_usd: Optional[Decimal] = None
    risk_level: Optional[str] = Field(None, pattern="^(low|medium|high|critical)$")
    risk_score: Optional[Decimal] = Field(None, ge=0, le=100)
    meta_data: Optional[Dict[str, Any]] = None


class CountryProfileResponse(CountryProfileCreate):
    """Schema for country profile responses."""

    id: int
    last_updated: datetime
    created_at: datetime

    class Config:
        from_attributes = True


class CountryIndicatorBase(BaseModel):
    """Base country indicator schema."""

    country_code: str = Field(..., max_length=3)
    indicator_code: str = Field(..., max_length=50)
    indicator_name: Optional[str] = Field(None, max_length=255)
    category: Optional[str] = Field(None, max_length=50)
    year: int = Field(..., ge=1960, le=2050)
    value: Optional[Decimal] = None
    unit: Optional[str] = Field(None, max_length=50)
    source: Optional[str] = Field(None, max_length=100)


class CountryIndicatorCreate(CountryIndicatorBase):
    """Schema for creating country indicators."""
    pass


class CountryIndicatorResponse(CountryIndicatorBase):
    """Schema for country indicator responses."""

    id: int
    last_updated: datetime

    class Config:
        from_attributes = True


class CountryComparisonRequest(BaseModel):
    """Request schema for country comparisons."""

    country_codes: List[str] = Field(..., min_length=2, max_length=10, description="List of country codes to compare")
    comparison_type: str = Field(..., pattern="^(economic|financial|risk|all)$")
    indicators: Optional[List[str]] = Field(None, description="Specific indicators to compare")


class CountryComparisonResponse(BaseModel):
    """Response schema for country comparisons."""

    countries: List[CountryProfileResponse]
    comparison_matrix: Dict[str, Dict[str, Any]]
    insights: List[str]
    created_at: datetime


class CountrySearchFilters(BaseModel):
    """Search/filter schema for countries."""

    search: Optional[str] = Field(None, description="Search by country name or code")
    region: Optional[str] = None
    risk_level: Optional[str] = Field(None, pattern="^(low|medium|high|critical)$")
    min_gdp: Optional[Decimal] = Field(None, ge=0)
    max_gdp: Optional[Decimal] = None
    min_population: Optional[int] = Field(None, ge=0)
    max_population: Optional[int] = None
    has_banking_data: Optional[bool] = None


class CountryListResponse(BaseModel):
    """Response schema for country listings."""

    total: int
    countries: List[CountryProfileResponse]
    filters_applied: CountrySearchFilters


class WorldBankSyncRequest(BaseModel):
    """Request schema for World Bank data sync."""

    country_codes: Optional[List[str]] = Field(None, description="Specific countries to sync, or None for all")
    indicators: Optional[List[str]] = Field(None, description="Specific indicators to sync")
    start_year: int = Field(2000, ge=1960, le=2050)
    end_year: Optional[int] = Field(None, ge=1960, le=2050)
    force_refresh: bool = Field(False, description="Force refresh even if data exists")


class WorldBankSyncResponse(BaseModel):
    """Response schema for World Bank sync."""

    status: str
    countries_synced: int
    indicators_synced: int
    records_created: int
    records_updated: int
    errors: List[str]
    started_at: datetime
    completed_at: datetime
    duration_seconds: float
