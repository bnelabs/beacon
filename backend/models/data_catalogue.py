"""Data catalogue models for organizing financial data sources."""

from sqlalchemy import Integer, String, Boolean, DateTime, JSON, Text, ForeignKey, Enum as SQLEnum, func
from sqlalchemy.orm import relationship, Mapped, mapped_column
import enum
from datetime import datetime
from typing import List, Optional, Dict, Any

from database import Base


class DataCategory(str, enum.Enum):
    """Categories of financial data."""
    EXCHANGE_RATES = "exchange_rates"
    INTEREST_RATES = "interest_rates"
    BANKING = "banking"
    STOCKS = "stocks"
    BONDS = "bonds"
    COMMODITIES = "commodities"
    ECONOMIC_INDICATORS = "economic_indicators"
    MONEY_MARKET = "money_market"
    CREDIT_MARKETS = "credit_markets"
    DERIVATIVES = "derivatives"
    FOREX = "forex"
    CENTRAL_BANK = "central_bank"


class DataRegion(str, enum.Enum):
    """Geographic regions for data."""
    GLOBAL = "global"
    NORTH_AMERICA = "north_america"
    EUROPE = "europe"
    ASIA = "asia"
    LATIN_AMERICA = "latin_america"
    MIDDLE_EAST = "middle_east"
    AFRICA = "africa"


class RiskType(str, enum.Enum):
    """Types of liquidity risk."""
    MARKET_LIQUIDITY = "market_liquidity"
    FUNDING_LIQUIDITY = "funding_liquidity"
    SYSTEMIC_RISK = "systemic_risk"
    OPERATIONAL_RISK = "operational_risk"
    CREDIT_RISK = "credit_risk"


class DataCatalogueItem(Base):
    """Catalogue of available financial data items."""

    __tablename__ = "data_catalogue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Identification
    code: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)

    # Classification
    category: Mapped[DataCategory] = mapped_column(SQLEnum(DataCategory), nullable=False, index=True)
    region: Mapped[DataRegion] = mapped_column(SQLEnum(DataRegion), nullable=False, index=True)
    risk_types: Mapped[List[str]] = mapped_column(JSON, default=[])  # List of RiskType values

    # Data source information
    data_source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"), nullable=False)
    data_source: Mapped["DataSource"] = relationship(back_populates="catalogue_items")

    # API/Query information
    endpoint: Mapped[Optional[str]] = mapped_column(String(500))  # API endpoint or query string
    parameters: Mapped[Dict[str, Any]] = mapped_column(JSON, default={})  # Default parameters
    frequency: Mapped[Optional[str]] = mapped_column(String(50))  # daily, weekly, monthly, quarterly, annual

    # Metadata
    granularity: Mapped[Optional[str]] = mapped_column(String(50))  # micro, meso, macro
    unit: Mapped[Optional[str]] = mapped_column(String(100))  # USD, EUR, percentage, basis_points, etc.

    # Status
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    default_selected: Mapped[bool] = mapped_column(Boolean, default=False)  # Included by default
    priority: Mapped[int] = mapped_column(Integer, default=0)  # Higher = more important

    # Relationships and dependencies
    dependencies: Mapped[List[int]] = mapped_column(JSON, default=[])  # IDs of required catalogue items
    tags: Mapped[List[str]] = mapped_column(JSON, default=[])  # Additional searchable tags

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())
    last_data_update: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    def __repr__(self):
        return f"<DataCatalogueItem {self.code}: {self.name}>"
