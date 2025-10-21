"""Pipeline job models for tracking DATA-ENGINE-RESULTS flow."""

from sqlalchemy import Integer, String, Float, DateTime, JSON, Text, ForeignKey, Enum as SQLEnum, func
from sqlalchemy.orm import relationship, Mapped, mapped_column
import enum
from datetime import datetime
from typing import Optional, List, Dict, Any

from database import Base


class PipelineStage(str, enum.Enum):
    """Pipeline stages."""
    DATA = "data"
    ENGINE = "engine"
    RESULTS = "results"


class JobStatus(str, enum.Enum):
    """Job execution status."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PipelineJob(Base):
    """Main pipeline job tracking."""

    __tablename__ = "pipeline_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Job identification
    job_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    name: Mapped[Optional[str]] = mapped_column(String(255))
    description: Mapped[Optional[str]] = mapped_column(Text)

    # Pipeline stage
    current_stage: Mapped[PipelineStage] = mapped_column(SQLEnum(PipelineStage), nullable=False)
    status: Mapped[JobStatus] = mapped_column(SQLEnum(JobStatus), default=JobStatus.PENDING, index=True)

    # Progress tracking
    progress: Mapped[float] = mapped_column(Float, default=0.0)  # 0-100
    current_step: Mapped[Optional[str]] = mapped_column(String(500))

    # Configuration
    config: Mapped[Dict[str, Any]] = mapped_column(JSON, default={})

    # Results
    data_package_path: Mapped[Optional[str]] = mapped_column(String(500))
    engine_result_path: Mapped[Optional[str]] = mapped_column(String(500))
    report_path: Mapped[Optional[str]] = mapped_column(String(500))

    # Metadata
    started_by: Mapped[Optional[str]] = mapped_column(String(100))
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[Optional[float]] = mapped_column(Float)

    # Error handling
    error_message: Mapped[Optional[str]] = mapped_column(Text)
    error_details: Mapped[Optional[Dict[str, Any]]] = mapped_column(JSON)

    # Relationships
    data_jobs: Mapped[List["DataJob"]] = relationship(back_populates="pipeline_job", cascade="all, delete-orphan")
    engine_jobs: Mapped[List["EngineJob"]] = relationship(back_populates="pipeline_job", cascade="all, delete-orphan")
    result_jobs: Mapped[List["ResultJob"]] = relationship(back_populates="pipeline_job", cascade="all, delete-orphan")

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<PipelineJob {self.job_id}: {self.current_stage.value} - {self.status.value}>"


class DataJob(Base):
    """DATA module job tracking."""

    __tablename__ = "data_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    pipeline_job_id: Mapped[int] = mapped_column(ForeignKey("pipeline_jobs.id"), nullable=False)

    # Status
    status: Mapped[JobStatus] = mapped_column(SQLEnum(JobStatus), default=JobStatus.PENDING)
    progress: Mapped[float] = mapped_column(Float, default=0.0)

    # Configuration
    catalogue_items: Mapped[List[int]] = mapped_column(JSON, default=[])  # List of item IDs
    start_date: Mapped[str] = mapped_column(String(20))
    end_date: Mapped[str] = mapped_column(String(20))

    # Quality metrics
    quality_score: Mapped[Optional[float]] = mapped_column(Float)
    completeness: Mapped[Optional[float]] = mapped_column(Float)
    consistency: Mapped[Optional[float]] = mapped_column(Float)
    fit_for_engine: Mapped[Optional[int]] = mapped_column(Integer)  # Boolean

    anomalies_detected: Mapped[int] = mapped_column(Integer, default=0)
    anomalies_fixed: Mapped[int] = mapped_column(Integer, default=0)

    # Output
    output_path: Mapped[Optional[str]] = mapped_column(String(500))

    # Timestamps
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationship
    pipeline_job: Mapped["PipelineJob"] = relationship(back_populates="data_jobs")

    def __repr__(self):
        return f"<DataJob {self.id}: {self.status.value}>"


class EngineJob(Base):
    """ENGINE module job tracking."""

    __tablename__ = "engine_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    pipeline_job_id: Mapped[int] = mapped_column(ForeignKey("pipeline_jobs.id"), nullable=False)

    # Status
    status: Mapped[JobStatus] = mapped_column(SQLEnum(JobStatus), default=JobStatus.PENDING)
    progress: Mapped[float] = mapped_column(Float, default=0.0)

    # Model info
    model_name: Mapped[Optional[str]] = mapped_column(String(100))
    model_version: Mapped[Optional[str]] = mapped_column(String(50))

    # Performance metrics
    mse: Mapped[Optional[float]] = mapped_column(Float)
    mae: Mapped[Optional[float]] = mapped_column(Float)
    r2: Mapped[Optional[float]] = mapped_column(Float)
    accuracy: Mapped[Optional[float]] = mapped_column(Float)

    # Risk scores
    overall_risk_score: Mapped[Optional[float]] = mapped_column(Float)
    risk_level: Mapped[Optional[str]] = mapped_column(String(50))

    # Compute stats
    device: Mapped[Optional[str]] = mapped_column(String(50))
    peak_memory_mb: Mapped[Optional[float]] = mapped_column(Float)

    # Output
    predictions_path: Mapped[Optional[str]] = mapped_column(String(500))
    explanations_path: Mapped[Optional[str]] = mapped_column(String(500))

    # Timestamps
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationship
    pipeline_job: Mapped["PipelineJob"] = relationship(back_populates="engine_jobs")

    def __repr__(self):
        return f"<EngineJob {self.id}: {self.model_name} - {self.status.value}>"


class ResultJob(Base):
    """RESULTS module job tracking."""

    __tablename__ = "result_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    pipeline_job_id: Mapped[int] = mapped_column(ForeignKey("pipeline_jobs.id"), nullable=False)

    # Status
    status: Mapped[JobStatus] = mapped_column(SQLEnum(JobStatus), default=JobStatus.PENDING)
    progress: Mapped[float] = mapped_column(Float, default=0.0)

    # Report info
    report_version: Mapped[Optional[str]] = mapped_column(String(50))
    num_recommendations: Mapped[int] = mapped_column(Integer, default=0)
    num_visualizations: Mapped[int] = mapped_column(Integer, default=0)

    # Output paths
    report_json_path: Mapped[Optional[str]] = mapped_column(String(500))
    report_pdf_path: Mapped[Optional[str]] = mapped_column(String(500))
    report_excel_path: Mapped[Optional[str]] = mapped_column(String(500))

    # Timestamps
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationship
    pipeline_job: Mapped["PipelineJob"] = relationship(back_populates="result_jobs")

    def __repr__(self):
        return f"<ResultJob {self.id}: {self.status.value}>"
