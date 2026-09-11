"""Time-series models for indicator observations and risk scores.

These are the tables that actually grow without bound: every indicator
observation and every per-entity risk score. On PostgreSQL they are converted
into TimescaleDB hypertables (time-partitioned, columnar-compressed) by the
``timescale_timeseries`` migration; on SQLite they are ordinary tables, which
keeps unit tests and single-node development working unchanged.

Every table uses a natural composite primary key that *includes* the time
column. TimescaleDB requires all unique indexes on a hypertable to contain the
partitioning column, so a surrogate auto-increment key would make the
hypertable conversion fail.
"""

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
)
from sqlalchemy.sql import func

from backend.database import Base


class IndicatorObservation(Base):
    """A single point of an economic/financial indicator series.

    One row per (time, source, indicator, region). ``region`` participates in
    the key because the same indicator is published per region and the
    dashboards aggregate by it.
    """

    __tablename__ = "indicator_observations"

    time = Column(DateTime(timezone=True), primary_key=True, nullable=False)
    source_code = Column(String(100), primary_key=True, nullable=False)
    indicator_code = Column(String(100), primary_key=True, nullable=False)
    region = Column(String(50), primary_key=True, nullable=False, server_default="GLOBAL")

    country = Column(String(100), nullable=True, index=True)
    value = Column(Float, nullable=False)
    unit = Column(String(50), nullable=True)
    quality_score = Column(Float, nullable=True)
    ingest_job_id = Column(String(100), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_indicator_observations_indicator_time", "indicator_code", "time"),
        Index("ix_indicator_observations_region_time", "region", "time"),
    )

    def __repr__(self) -> str:
        return f"<IndicatorObservation {self.indicator_code}@{self.time}={self.value}>"


class RiskScorePoint(Base):
    """A predicted liquidity-risk score for one entity at one point in time."""

    __tablename__ = "risk_scores"

    time = Column(DateTime(timezone=True), primary_key=True, nullable=False)
    entity_type = Column(String(20), primary_key=True, nullable=False)  # bank | region | country
    entity_id = Column(String(100), primary_key=True, nullable=False)
    model_version = Column(String(50), primary_key=True, nullable=False, server_default="v1")
    horizon_days = Column(Integer, primary_key=True, nullable=False, server_default="1")

    region = Column(String(50), nullable=True, index=True)
    country = Column(String(100), nullable=True)
    risk_score = Column(Float, nullable=False)
    risk_level = Column(String(20), nullable=True)
    prediction_job_id = Column(String(100), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_risk_scores_region_time", "region", "time"),
        Index("ix_risk_scores_entity_time", "entity_type", "entity_id", "time"),
    )

    def __repr__(self) -> str:
        return f"<RiskScorePoint {self.entity_type}:{self.entity_id}@{self.time}={self.risk_score}>"


class ModelMetricPoint(Base):
    """A model-evaluation metric recorded over time (training and backtests)."""

    __tablename__ = "model_metrics"

    time = Column(DateTime(timezone=True), primary_key=True, nullable=False)
    job_id = Column(String(100), primary_key=True, nullable=False)
    metric_name = Column(String(100), primary_key=True, nullable=False)

    metric_value = Column(Float, nullable=False)
    model_version = Column(String(50), nullable=True, index=True)
    model_type = Column(String(100), nullable=True)
    region = Column(String(50), nullable=True)
    horizon_days = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("ix_model_metrics_name_time", "metric_name", "time"),
    )

    def __repr__(self) -> str:
        return f"<ModelMetricPoint {self.metric_name}@{self.time}={self.metric_value}>"
