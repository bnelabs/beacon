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

from datetime import timezone

from sqlalchemy import (
    Column,
    DateTime,
    Float,
    Index,
    Integer,
    String,
    TypeDecorator,
)
from sqlalchemy.sql import func

from backend.database import Base


class UTCDateTime(TypeDecorator):
    """A timestamp that reads back as *aware* UTC, on every backend.

    PostgreSQL's ``TIMESTAMP WITH TIME ZONE`` hands back an aware datetime;
    SQLite's ``DATETIME`` has no timezone support at all and hands back a naive
    one. So ``row.published_at == the_instant_that_was_written`` is True in CI
    and False on a SQLite deployment -- and comparing an aware and a naive
    datetime is worse than False: ``sorted()`` over a mix of them raises
    ``TypeError``, and ``aware - naive`` raises it outright. The vintage log is
    read exactly that way (``observations_as_of`` keys a dict on ``row.time``
    and sorts it), so the answer an as-of query gives would depend on which
    database the deployment happened to use.

    The convention the rest of this backend already states -- a naive stored
    stamp *is* UTC, see ``_iso`` in ``routes/observations.py`` and the
    ``tzinfo is None`` guards in ``services/alert_evaluator.py`` -- is applied
    here instead of being re-derived at every read site.

    Storage is unchanged: the bind side normalises to UTC, and SQLite still
    writes the same naive-UTC string it wrote before. Only the read side
    changes, and only for the two tables that carry as-of semantics. The
    latest-value tables are deliberately left alone: widening this to every
    timestamp in this file would change what *every* analytics read sees, and
    a comparison against a ``datetime.utcnow()`` value elsewhere would start
    raising where it used to silently mismatch.

    ``impl`` keeps ``timezone=True``, so the DDL a migration renders and the
    DDL ``create_all()`` renders stay identical.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            # Naive input is read as UTC, which is the collector/validator
            # convention; leaving it naive keeps the stored string identical.
            return value
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


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

class IndicatorVintageLog(Base):
    """Append-only vintages of indicator observations.

    Every write to ``indicator_observations`` appends here: the value as
    written, and when this deployment published it. Restatements therefore
    leave both the new value (latest-value store) and the history of what was
    believed before (this log), which is what makes a number re-derivable as
    of a past date instead of silently revised under yesterday's backtest.

    ``published_at`` means different things for different rows, and the row now
    says which: a live pipeline write stamps the instant of the write, a
    backfill stamps the certified snapshot's capture instant. See
    ``publication_basis`` below and ``TimeSeriesStore``'s basis constants.
    """

    __tablename__ = "indicator_vintage_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source_code = Column(String(100), nullable=False, index=False)
    indicator_code = Column(String(100), nullable=False, index=False)
    region = Column(String(50), nullable=False, server_default="GLOBAL")
    time = Column(UTCDateTime(), nullable=False)
    value = Column(Float, nullable=False)
    published_at = Column(UTCDateTime(), nullable=False, index=False)
    ingest_job_id = Column(String(100), nullable=True, index=True)

    #: Content address of the certified dataset snapshot this vintage was read
    #: from, when it came from one. ``None`` for a live pipeline write.
    snapshot_id = Column(String(80), nullable=True)
    #: *Why* ``published_at`` is what it is: the instant this deployment wrote
    #: the row (``ingest_instant``), or the capture instant of a certified
    #: snapshot it was backfilled from (``certified_snapshot``). ``NULL`` means
    #: the row predates provenance, and an as-of answer must report it as
    #: unknown rather than guess which of the two it was.
    publication_basis = Column(String(32), nullable=True)

    __table_args__ = (
        # Declared here as well as created by ``vintage_log_001`` so that a
        # database built by ``create_all()`` gets the same index a migrated one
        # does: an as-of query's access path should not depend on which history
        # the volume followed.
        Index("ix_vintage_series_published", "source_code", "indicator_code", "published_at"),
        Index("ix_vintage_log_snapshot", "snapshot_id"),
    )

    def __repr__(self) -> str:
        return (
            f"<IndicatorVintageLog {self.indicator_code}@{self.time}="
            f"{self.value} published_at={self.published_at}>"
        )


class VintageBackfillRun(Base):
    """Which certified snapshots have already been read into the vintage log.

    ``indicator_vintage_log`` is append-only, so the idempotency of a backfill
    cannot come from rewriting rows it already wrote. It comes from this ledger:
    one row per applied snapshot, carrying the counts it produced. A snapshot
    that produced nothing is still recorded -- "nothing to do" and "already
    done" are different answers, and an operator deciding whether the backfill
    finished has to be able to tell them apart.

    Deliberately *not* a unique constraint on the vintage log itself: adding one
    would mean computing an identity for rows the log already holds, and an
    UPDATE on the audit table to make a tool idempotent is the thing the audit
    table exists to prevent.
    """

    __tablename__ = "vintage_backfill_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    snapshot_id = Column(String(80), nullable=False, unique=True)
    job_id = Column(String(100), nullable=True)
    snapshot_created_at = Column(UTCDateTime(), nullable=False)
    applied_at = Column(UTCDateTime(), nullable=False)
    rows_written = Column(Integer, nullable=False, default=0)
    rows_skipped = Column(Integer, nullable=False, default=0)
    source_directory = Column(String(500), nullable=True)

    __table_args__ = (
        Index("ix_vintage_backfill_applied", "applied_at"),
    )

    def __repr__(self) -> str:
        return f"<VintageBackfillRun {self.snapshot_id} rows_written={self.rows_written}>"

