"""Pipeline job models for tracking DATA-ENGINE-RESULTS flow."""

from sqlalchemy import Column, Integer, String, Float, DateTime, JSON, Text, ForeignKey, Enum as SQLEnum
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
import enum

from backend.database import Base


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

    id = Column(Integer, primary_key=True, index=True)

    # Job identification
    job_id = Column(String(100), unique=True, nullable=False, index=True)
    name = Column(String(255))
    description = Column(Text)

    # Pipeline stage
    current_stage = Column(SQLEnum(PipelineStage), nullable=False)
    status = Column(SQLEnum(JobStatus), default=JobStatus.PENDING, index=True)

    # Progress tracking
    progress = Column(Float, default=0.0)  # 0-100
    current_step = Column(String(500))

    # Configuration
    config = Column(JSON, default={})

    # Results
    data_package_path = Column(String(500))
    engine_result_path = Column(String(500))
    report_path = Column(String(500))

    # Metadata
    started_by = Column(String(100))
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
    duration_seconds = Column(Float)

    # Error handling
    error_message = Column(Text)
    error_details = Column(JSON)

    # Relationships
    data_jobs = relationship("DataJob", back_populates="pipeline_job", cascade="all, delete-orphan")
    engine_jobs = relationship("EngineJob", back_populates="pipeline_job", cascade="all, delete-orphan")
    result_jobs = relationship("ResultJob", back_populates="pipeline_job", cascade="all, delete-orphan")

    # Timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    def __repr__(self):
        return f"<PipelineJob {self.job_id}: {self.current_stage.value} - {self.status.value}>"


class DataJob(Base):
    """DATA module job tracking."""

    __tablename__ = "data_jobs"

    id = Column(Integer, primary_key=True, index=True)
    pipeline_job_id = Column(Integer, ForeignKey("pipeline_jobs.id"), nullable=False)

    # Status
    status = Column(SQLEnum(JobStatus), default=JobStatus.PENDING)
    progress = Column(Float, default=0.0)

    # Configuration
    catalogue_items = Column(JSON, default=[])  # List of item IDs
    start_date = Column(String(20))
    end_date = Column(String(20))

    # Quality metrics
    quality_score = Column(Float)
    completeness = Column(Float)
    consistency = Column(Float)
    fit_for_engine = Column(Integer)  # Boolean

    anomalies_detected = Column(Integer, default=0)
    anomalies_fixed = Column(Integer, default=0)

    # Output
    output_path = Column(String(500))

    # Timestamps
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))

    # Relationship
    pipeline_job = relationship("PipelineJob", back_populates="data_jobs")

    def __repr__(self):
        return f"<DataJob {self.id}: {self.status.value}>"


class EngineJob(Base):
    """ENGINE module job tracking."""

    __tablename__ = "engine_jobs"

    id = Column(Integer, primary_key=True, index=True)
    pipeline_job_id = Column(Integer, ForeignKey("pipeline_jobs.id"), nullable=False)

    # Status
    status = Column(SQLEnum(JobStatus), default=JobStatus.PENDING)
    progress = Column(Float, default=0.0)

    # Model info
    model_name = Column(String(100))
    model_version = Column(String(50))

    # Performance metrics
    mse = Column(Float)
    mae = Column(Float)
    r2 = Column(Float)
    accuracy = Column(Float)

    # Risk scores
    overall_risk_score = Column(Float)
    risk_level = Column(String(50))

    # Compute stats
    device = Column(String(50))
    peak_memory_mb = Column(Float)

    # Output
    predictions_path = Column(String(500))
    explanations_path = Column(String(500))

    # Timestamps
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))

    # Relationship
    pipeline_job = relationship("PipelineJob", back_populates="engine_jobs")

    def __repr__(self):
        return f"<EngineJob {self.id}: {self.model_name} - {self.status.value}>"


class ResultJob(Base):
    """RESULTS module job tracking."""

    __tablename__ = "result_jobs"

    id = Column(Integer, primary_key=True, index=True)
    pipeline_job_id = Column(Integer, ForeignKey("pipeline_jobs.id"), nullable=False)

    # Status
    status = Column(SQLEnum(JobStatus), default=JobStatus.PENDING)
    progress = Column(Float, default=0.0)

    # Report info
    report_version = Column(String(50))
    num_recommendations = Column(Integer, default=0)
    num_visualizations = Column(Integer, default=0)

    # Output paths
    report_json_path = Column(String(500))
    report_pdf_path = Column(String(500))
    report_excel_path = Column(String(500))

    # Timestamps
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))

    # Relationship
    pipeline_job = relationship("PipelineJob", back_populates="result_jobs")

    def __repr__(self):
        return f"<ResultJob {self.id}: {self.status.value}>"
