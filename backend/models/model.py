"""SQLAlchemy models for model registry."""

from sqlalchemy import Integer, String, DateTime, JSON, Float, ForeignKey, func
from sqlalchemy.orm import relationship, Mapped, mapped_column
from datetime import datetime
from typing import Optional, List, Dict, Any
from database import Base

class Model(Base):
    """Model for grouping model versions."""
    __tablename__ = "models"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    versions: Mapped[List["ModelVersion"]] = relationship("ModelVersion", back_populates="model")

class ModelVersion(Base):

    """Model version, representing a trained model artifact."""

    __tablename__ = "model_versions"



    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    model_id: Mapped[Optional[int]] = mapped_column(ForeignKey("models.id"))

    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id"))

    configuration_id: Mapped[Optional[int]] = mapped_column(ForeignKey("configurations.id"))



    version: Mapped[int] = mapped_column(Integer, nullable=False)

    stage: Mapped[str] = mapped_column(String(50), default="Staging")  # Staging, Production, Archived

    metrics: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)

    model_path: Mapped[Optional[str]] = mapped_column(String(255))

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))



    model: Mapped["Model"] = relationship("Model", back_populates="versions")

    job: Mapped["Job"] = relationship("Job")

    configuration: Mapped["Configuration"] = relationship("Configuration")
