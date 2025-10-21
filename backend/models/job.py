"""SQLAlchemy model for background jobs."""

from sqlalchemy import Integer, String, DateTime, Text, Float, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import relationship, Mapped, mapped_column
from datetime import datetime
from typing import Optional, Dict, Any
from database import Base


class Job(Base):
    """Background job tracking model.

    Tracks execution of data collection, training, and prediction jobs.
    """
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)  # data_collection, training, prediction, backtest
    celery_task_id: Mapped[Optional[str]] = mapped_column(String(100), unique=True, index=True)

    # Job status
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # pending, running, completed, failed
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0.0 to 100.0
    current_step: Mapped[Optional[str]] = mapped_column(String(255))  # Descriptive message of current operation

    # Job parameters
    parameters: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)  # Input parameters for the job

    # Results
    result: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)  # Job output/results
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    user_friendly_error: Mapped[Optional[str]] = mapped_column(Text)  # Translated error for non-technical users

    # Timing
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Resource usage tracking
    peak_memory_mb: Mapped[Optional[float]] = mapped_column(Float)
    execution_time_seconds: Mapped[Optional[float]] = mapped_column(Float)

    configuration_association: Mapped["JobConfiguration"] = relationship(back_populates="job")

    def __repr__(self):
        return f"<Job(id={self.id}, type={self.job_type}, status={self.status})>"
