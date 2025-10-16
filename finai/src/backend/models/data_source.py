"""SQLAlchemy model for data sources."""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, JSON, Text
from sqlalchemy.sql import func
from ..database import Base


class DataSource(Base):
    """Data source configuration model.

    Stores configuration for external data sources (Yahoo Finance, FRED, etc.)
    that can be added/removed via UI without code changes.
    """
    __tablename__ = "data_sources"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)
    plugin_type = Column(String(50), nullable=False)  # yfinance, fred, alpha_vantage, etc.
    enabled = Column(Boolean, default=True, nullable=False)

    # Plugin-specific configuration as JSON
    config = Column(JSON, nullable=False)  # {api_key, rate_limit, etc.}

    # Metadata
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_successful_fetch = Column(DateTime(timezone=True))

    # Status tracking
    status = Column(String(20), default="active")  # active, error, disabled
    error_message = Column(Text)

    def __repr__(self):
        return f"<DataSource(name={self.name}, plugin={self.plugin_type}, enabled={self.enabled})>"
