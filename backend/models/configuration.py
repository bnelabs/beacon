"""SQLAlchemy models for configuration management."""

from sqlalchemy import Integer, String, DateTime, JSON, Boolean, ForeignKey, func
from sqlalchemy.orm import relationship, Mapped, mapped_column
from datetime import datetime
from typing import Optional, Dict, Any
from database import Base

class Configuration(Base):
    """Configuration model for storing versioned configurations."""
    __tablename__ = "configurations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    config_data: Mapped[Dict[str, Any]] = mapped_column(JSON, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    created_by: Mapped[Optional[str]] = mapped_column(String(100))

    __table_args__ = ({"unique_together": [("name", "version")]},)

class JobConfiguration(Base):
    """Association table between jobs and configurations."""
    __tablename__ = "job_configurations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id"))
    configuration_id: Mapped[Optional[int]] = mapped_column(ForeignKey("configurations.id"))

    job: Mapped["Job"] = relationship("Job", back_populates="configuration_association")
    configuration: Mapped["Configuration"] = relationship("Configuration")
