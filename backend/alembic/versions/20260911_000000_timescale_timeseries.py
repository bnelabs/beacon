"""add timescaledb time-series tables

Creates the three unbounded-growth tables (indicator observations, per-entity
risk scores, model metrics) and, when the TimescaleDB extension is available,
converts them into compressed hypertables with continuous aggregates.

The migration is deliberately tiered:

* The base tables are created unconditionally and idempotently, so plain
  PostgreSQL and SQLite (development, unit tests) work identically.
* Hypertable conversion and compression policies are applied - and any failure
  is raised - only when TimescaleDB is actually installed. When it is absent the
  migration logs a warning and continues, because partitioning is a performance
  optimisation rather than a correctness requirement.
* Continuous aggregates are best-effort: some TimescaleDB versions refuse to
  create them inside the transaction Alembic opens. A failure is logged loudly
  with the path of the standalone SQL script, and the store falls back to plain
  aggregation, so a missing pre-aggregate degrades performance but never
  returns wrong numbers.

Revision ID: timescale_001
Revises: 20251107_161500
Create Date: 2026-09-11 00:00:00.000000

"""
import logging

from alembic import context, op
import sqlalchemy as sa

from backend.models.timeseries import (
    IndicatorObservation,
    ModelMetricPoint,
    RiskScorePoint,
)

# revision identifiers, used by Alembic.
revision = 'timescale_001'
down_revision = '20251107_161500'
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

TIMESCALE_EXTENSION = "timescaledb"

# (table, time column, compress_segmentby)
HYPERTABLES = (
    ("indicator_observations", "time", "source_code,region"),
    ("risk_scores", "time", "region,entity_type"),
    ("model_metrics", "time", "metric_name"),
)

COMPRESS_AFTER = "90 days"

CONTINUOUS_AGGREGATES = (
    (
        "risk_scores_daily",
        """
        CREATE MATERIALIZED VIEW IF NOT EXISTS risk_scores_daily
        WITH (timescaledb.continuous) AS
        SELECT time_bucket(INTERVAL '1 day', time) AS bucket,
               region,
               entity_type,
               count(*)            AS observation_count,
               avg(risk_score)     AS avg_risk_score,
               max(risk_score)     AS max_risk_score,
               min(risk_score)     AS min_risk_score
        FROM risk_scores
        GROUP BY bucket, region, entity_type
        WITH NO DATA
        """,
        """
        SELECT add_continuous_aggregate_policy('risk_scores_daily',
            start_offset      => INTERVAL '90 days',
            end_offset        => INTERVAL '1 hour',
            schedule_interval => INTERVAL '1 hour',
            if_not_exists     => TRUE)
        """,
    ),
    (
        "indicator_observations_daily",
        """
        CREATE MATERIALIZED VIEW IF NOT EXISTS indicator_observations_daily
        WITH (timescaledb.continuous) AS
        SELECT time_bucket(INTERVAL '1 day', time) AS bucket,
               indicator_code,
               region,
               avg(value) AS avg_value,
               min(value) AS min_value,
               max(value) AS max_value,
               count(*)   AS observation_count
        FROM indicator_observations
        GROUP BY bucket, indicator_code, region
        WITH NO DATA
        """,
        """
        SELECT add_continuous_aggregate_policy('indicator_observations_daily',
            start_offset      => INTERVAL '90 days',
            end_offset        => INTERVAL '1 hour',
            schedule_interval => INTERVAL '1 hour',
            if_not_exists     => TRUE)
        """,
    ),
)

TABLES = (
    IndicatorObservation.__table__,
    RiskScorePoint.__table__,
    ModelMetricPoint.__table__,
)


def _timescale_available() -> bool:
    """Return True only when running on PostgreSQL with the extension installed.

    Offline mode (``alembic upgrade head --sql``) has no connection to probe, so
    it emits plain-table DDL unless the operator forces hypertables with
    ``-x timescaledb=1``.
    """
    if context.is_offline_mode():
        forced = context.get_x_argument(as_dictionary=True).get("timescaledb")
        return str(forced).strip().lower() in {"1", "true", "yes", "on"} if forced else False

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return False
    try:
        row = bind.execute(
            sa.text("SELECT 1 FROM pg_available_extensions WHERE name = :name"),
            {"name": TIMESCALE_EXTENSION},
        ).scalar()
    except Exception:  # noqa: BLE001 - an unavailable catalog query means "no"
        logger.warning("Could not probe for the %s extension; assuming absent", TIMESCALE_EXTENSION)
        return False
    return bool(row)


def _create_tables() -> None:
    """Create the time-series tables, tolerating those init_db already made."""
    bind = op.get_bind()
    for table in TABLES:
        table.create(bind, checkfirst=True)


def _apply_timescale() -> None:
    """Convert the tables into hypertables and attach compression policies."""
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    for table, time_column, segment_by in HYPERTABLES:
        try:
            op.execute(
                f"SELECT create_hypertable('{table}', '{time_column}', "
                f"if_not_exists => TRUE, migrate_data => TRUE)"
            )
            op.execute(
                f"ALTER TABLE {table} SET (timescaledb.compress, "
                f"timescaledb.compress_segmentby = '{segment_by}', "
                f"timescaledb.compress_orderby = '{time_column} DESC')"
            )
            op.execute(
                f"SELECT add_compression_policy('{table}', INTERVAL '{COMPRESS_AFTER}', "
                f"if_not_exists => TRUE)"
            )
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"TimescaleDB is installed but converting '{table}' to a hypertable failed: {exc}. "
                "Fix the table definition or apply configs/timescaledb/timescale_setup.sql manually."
            ) from exc

    for name, create_sql, policy_sql in CONTINUOUS_AGGREGATES:
        try:
            op.execute(create_sql)
            op.execute(policy_sql)
        except Exception:  # noqa: BLE001
            # Older TimescaleDB releases cannot build a continuous aggregate
            # inside the transaction Alembic opens. The base tables and the
            # hypertables are already correct, and TimeSeriesStore falls back to
            # plain aggregation, so this is a performance regression only.
            logger.error(
                "Could not create continuous aggregate '%s'. Apply "
                "configs/timescaledb/timescale_setup.sql manually to enable "
                "pre-aggregated dashboard queries.",
                name,
                exc_info=True,
            )


def upgrade():
    _create_tables()

    if _timescale_available():
        _apply_timescale()
    else:
        logger.warning(
            "TimescaleDB extension is not available on this database; the "
            "time-series tables were created as plain tables. Use the "
            "TimescaleDB-enabled image (see docker-compose.yml) for hypertable "
            "partitioning and compression."
        )


def downgrade():
    bind = op.get_bind()
    if _timescale_available():
        for name, _create_sql, _policy_sql in CONTINUOUS_AGGREGATES:
            # CASCADE is required: a continuous aggregate owns internal objects.
            op.execute(f"DROP MATERIALIZED VIEW IF EXISTS {name} CASCADE")

    for table in reversed(TABLES):
        table.drop(bind, checkfirst=True)
