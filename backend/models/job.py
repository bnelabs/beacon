"""SQLAlchemy model for background jobs."""

from sqlalchemy import Column, Integer, String, DateTime, JSON, Text, Float
from sqlalchemy.sql import func
from database import Base


class Job(Base):
    """Background job tracking model.

    Tracks execution of data collection, training, and prediction jobs.
    """
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    job_type = Column(String(50), nullable=False, index=True)  # data_collection, training, prediction, backtest
    celery_task_id = Column(String(100), unique=True, index=True)

    # Job status
    status = Column(String(20), default="pending", nullable=False)  # pending, running, completed, failed
    progress = Column(Float, default=0.0)  # 0.0 to 100.0

    # Job parameters
    parameters = Column(JSON)  # Input parameters for the job

    # Results
    result = Column(JSON)  # Job output/results
    error_message = Column(Text)
    user_friendly_error = Column(Text)  # Translated error for non-technical users

    # Timing
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))

    # Resource usage tracking
    peak_memory_mb = Column(Float)
    execution_time_seconds = Column(Float)

    def __repr__(self):
        return f"<Job(id={self.id}, type={self.job_type}, status={self.status})>"
