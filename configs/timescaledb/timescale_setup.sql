-- BEACON TimescaleDB setup
--
-- Idempotent: safe to run repeatedly by hand or from a provisioning step.
-- The Alembic migration `timescale_001` applies the same changes; this script
-- exists because some TimescaleDB releases refuse to create continuous
-- aggregates inside the transaction Alembic opens, and because DBAs generally
-- prefer to review partitioning/compression DDL before it runs.
--
-- Usage:
--   psql "$DATABASE_URL" -f configs/timescaledb/timescale_setup.sql

CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ---------------------------------------------------------------------------
-- Hypertables: partition by time, compress older chunks
-- ---------------------------------------------------------------------------

SELECT create_hypertable('indicator_observations', 'time',
                         if_not_exists => TRUE, migrate_data => TRUE);
ALTER TABLE indicator_observations SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'source_code,region',
    timescaledb.compress_orderby   = 'time DESC'
);
SELECT add_compression_policy('indicator_observations', INTERVAL '90 days', if_not_exists => TRUE);

SELECT create_hypertable('risk_scores', 'time',
                         if_not_exists => TRUE, migrate_data => TRUE);
ALTER TABLE risk_scores SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'region,entity_type',
    timescaledb.compress_orderby   = 'time DESC'
);
SELECT add_compression_policy('risk_scores', INTERVAL '90 days', if_not_exists => TRUE);

SELECT create_hypertable('model_metrics', 'time',
                         if_not_exists => TRUE, migrate_data => TRUE);
ALTER TABLE model_metrics SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'metric_name',
    timescaledb.compress_orderby   = 'time DESC'
);
SELECT add_compression_policy('model_metrics', INTERVAL '90 days', if_not_exists => TRUE);

-- ---------------------------------------------------------------------------
-- Continuous aggregates: pre-computed rollups for the dashboards
-- ---------------------------------------------------------------------------

CREATE MATERIALIZED VIEW IF NOT EXISTS risk_scores_daily
WITH (timescaledb.continuous) AS
SELECT time_bucket(INTERVAL '1 day', time) AS bucket,
       region,
       entity_type,
       count(*)        AS observation_count,
       avg(risk_score) AS avg_risk_score,
       max(risk_score) AS max_risk_score,
       min(risk_score) AS min_risk_score
FROM risk_scores
GROUP BY bucket, region, entity_type
WITH NO DATA;

SELECT add_continuous_aggregate_policy('risk_scores_daily',
    start_offset      => INTERVAL '90 days',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists     => TRUE);

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
WITH NO DATA;

SELECT add_continuous_aggregate_policy('indicator_observations_daily',
    start_offset      => INTERVAL '90 days',
    end_offset        => INTERVAL '1 hour',
    schedule_interval => INTERVAL '1 hour',
    if_not_exists     => TRUE);
