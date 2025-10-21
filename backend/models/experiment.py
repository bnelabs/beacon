"""SQLAlchemy models for experiment tracking."""

from sqlalchemy import Integer, String, DateTime, JSON, Float, ForeignKey, func
from sqlalchemy.orm import relationship, Mapped, mapped_column
from datetime import datetime
from typing import Optional, List, Dict, Any
from database import Base

class Experiment(Base):
    """Experiment model for grouping runs."""
    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    runs: Mapped[List["Run"]] = relationship("Run", back_populates="experiment")

class Run(Base):
    """Run model for tracking a single training job."""
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    experiment_id: Mapped[Optional[int]] = mapped_column(ForeignKey("experiments.id"))
    job_id: Mapped[Optional[int]] = mapped_column(ForeignKey("jobs.id"))
    configuration_id: Mapped[Optional[int]] = mapped_column(ForeignKey("configurations.id"))

    parameters: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    metrics: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    artifacts: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(50), default="running")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    experiment: Mapped["Experiment"] = relationship("Experiment", back_populates="runs")
    job: Mapped["Job"] = relationship("Job")
    configuration: Mapped["Configuration"] = relationship("Configuration")
