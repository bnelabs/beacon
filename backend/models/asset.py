"""SQLAlchemy model for assets."""

from sqlalchemy import Integer, String, Boolean, DateTime, Float, ForeignKey, func
from sqlalchemy.orm import relationship, Mapped, mapped_column
from datetime import datetime
from typing import Optional
from database import Base


class Asset(Base):
    """Asset configuration model.

    Tracks individual assets (stocks, bonds, commodities) to monitor.
    """
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(200))
    asset_type: Mapped[Optional[str]] = mapped_column(String(50))  # stock, bond, commodity, crypto, etc.

    # Data source reference
    data_source_id: Mapped[Optional[int]] = mapped_column(ForeignKey("data_sources.id"))
    data_source: Mapped["DataSource"] = relationship(back_populates="assets")

    # Configuration
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sector: Mapped[Optional[str]] = mapped_column(String(100))
    region: Mapped[Optional[str]] = mapped_column(String(100))

    # Monitoring thresholds
    liquidity_threshold: Mapped[Optional[float]] = mapped_column(Float)  # Alert threshold for liquidity risk

    # Metadata
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())
    last_data_update: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    def __repr__(self):
        return f"<Asset(symbol={self.symbol}, name={self.name}, type={self.asset_type})>"
