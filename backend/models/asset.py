"""SQLAlchemy model for assets."""

from sqlalchemy import Column, Integer, String, Boolean, DateTime, Float, ForeignKey
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from database import Base


class Asset(Base):
    """Asset configuration model.

    Tracks individual assets (stocks, bonds, commodities) to monitor.
    """
    __tablename__ = "assets"

    id = Column(Integer, primary_key=True, index=True)
    symbol = Column(String(20), unique=True, nullable=False, index=True)
    name = Column(String(200))
    asset_type = Column(String(50))  # stock, bond, commodity, crypto, etc.

    # Data source reference
    data_source_id = Column(Integer, ForeignKey("data_sources.id"))
    data_source = relationship("DataSource")

    # Configuration
    enabled = Column(Boolean, default=True, nullable=False)
    sector = Column(String(100))
    region = Column(String(100))

    # Monitoring thresholds
    liquidity_threshold = Column(Float)  # Alert threshold for liquidity risk

    # Metadata
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    last_data_update = Column(DateTime(timezone=True))

    def __repr__(self):
        return f"<Asset(symbol={self.symbol}, name={self.name}, type={self.asset_type})>"
