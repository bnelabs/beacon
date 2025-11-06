"""Country profile models."""

from sqlalchemy import Column, Integer, String, BigInteger, Numeric, DateTime, ForeignKey, ARRAY
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from backend.database import Base


class CountryProfile(Base):
    """Country profile with economic and financial metrics."""

    __tablename__ = "country_profiles"

    id = Column(Integer, primary_key=True, index=True)
    country_code = Column(String(3), unique=True, nullable=False, index=True)
    country_name = Column(String(100), nullable=False)
    region = Column(String(50), index=True)
    sub_region = Column(String(100))
    iso_alpha_3 = Column(String(3))
    capital = Column(String(100))
    currency = Column(String(50))
    latitude = Column(Numeric(10, 6))
    longitude = Column(Numeric(10, 6))

    # Economic indicators
    population = Column(BigInteger)
    gdp_usd = Column(Numeric(20, 2), index=True)
    gdp_per_capita = Column(Numeric(12, 2))
    gdp_growth_rate = Column(Numeric(5, 2))
    inflation_rate = Column(Numeric(5, 2))
    unemployment_rate = Column(Numeric(5, 2))

    # Financial indicators
    credit_to_gdp = Column(Numeric(5, 2))
    debt_to_gdp = Column(Numeric(5, 2))
    fiscal_balance = Column(Numeric(5, 2))
    current_account_balance = Column(Numeric(5, 2))

    # Banking sector
    bank_count = Column(Integer)
    total_bank_assets_usd = Column(Numeric(20, 2))

    # Risk assessment
    risk_level = Column(String(20), index=True)  # low, medium, high, critical
    risk_score = Column(Numeric(5, 2))  # 0-100

    # Flexible metadata storage
    meta_data = Column(JSONB)

    # Timestamps
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    indicators = relationship("CountryIndicator", back_populates="country", cascade="all, delete-orphan")


class CountryIndicator(Base):
    """Time series indicators for countries."""

    __tablename__ = "country_indicators"

    id = Column(Integer, primary_key=True, index=True)
    country_code = Column(String(3), ForeignKey("country_profiles.country_code", ondelete="CASCADE"), nullable=False, index=True)
    indicator_code = Column(String(50), nullable=False, index=True)
    indicator_name = Column(String(255))
    category = Column(String(50), index=True)  # economic, financial, social, infrastructure
    year = Column(Integer, nullable=False, index=True)
    value = Column(Numeric(20, 6))
    unit = Column(String(50))
    source = Column(String(100))
    last_updated = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    # Relationships
    country = relationship("CountryProfile", back_populates="indicators")


class CountryComparison(Base):
    """Cached country comparisons."""

    __tablename__ = "country_comparisons"

    id = Column(Integer, primary_key=True, index=True)
    country_codes = Column(ARRAY(String(3)), nullable=False)
    comparison_type = Column(String(50), nullable=False)  # economic, financial, risk
    results = Column(JSONB, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True))
