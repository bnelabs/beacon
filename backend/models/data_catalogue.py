"""Data catalogue models for organizing financial data sources."""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON, Text, ForeignKey, Enum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

from backend.database import Base


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

    id = Column(Integer, primary_key=True, index=True)

    # Identification
    code = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)

    # Classification
    category = Column(Enum(DataCategory), nullable=False, index=True)
    region = Column(Enum(DataRegion), nullable=False, index=True)
    risk_types = Column(JSON, default=[])  # List of RiskType values

    # Data source information
    data_source_id = Column(Integer, ForeignKey("data_sources.id"), nullable=False)
    data_source = relationship("DataSource")

    # API/Query information
    endpoint = Column(String(500))  # API endpoint or query string
    parameters = Column(JSON, default={})  # Default parameters
    frequency = Column(String(50))  # daily, weekly, monthly, quarterly, annual

    # Metadata
    granularity = Column(String(50))  # micro, meso, macro
    unit = Column(String(100))  # USD, EUR, percentage, basis_points, etc.

    # Status
    enabled = Column(Boolean, default=True)
    default_selected = Column(Boolean, default=False)  # Included by default
    priority = Column(Integer, default=0)  # Higher = more important

    # Relationships and dependencies
    dependencies = Column(JSON, default=[])  # IDs of required catalogue items
    tags = Column(JSON, default=[])  # Additional searchable tags

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_data_update = Column(DateTime(timezone=True))

    def __repr__(self):
        return f"<DataCatalogueItem {self.code}: {self.name}>"
