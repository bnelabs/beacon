"""SQLAlchemy model for data sources."""

from sqlalchemy import Integer, String, Boolean, DateTime, JSON, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship
from datetime import datetime
from typing import Optional, Dict, Any, List

from models.data_catalogue import DataCatalogueItem # Assuming DataCatalogueItem model exists
from database import Base


class DataSource(Base):
    """Data source configuration model.

    Stores configuration for external data sources (Yahoo Finance, FRED, etc.)
    that can be added/removed via UI without code changes.
    """
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    plugin_type: Mapped[str] = mapped_column(String(50), nullable=False)  # yfinance, fred, alpha_vantage, etc.
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # Plugin-specific configuration as JSON
    config: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)  # {api_key, rate_limit, etc.}

    # Metadata
    description: Mapped[Optional[str]] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())
    last_successful_fetch: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Status tracking
    status: Mapped[str] = mapped_column(String(20), default="active")  # active, error, disabled
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    # Relationships
    assets: Mapped[List["Asset"]] = relationship("Asset", back_populates="data_source")
    catalogue_items: Mapped[List["DataCatalogueItem"]] = relationship("DataCatalogueItem", back_populates="data_source")
