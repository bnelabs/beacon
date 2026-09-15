"""append-only vintage log for indicator observations

Revision ID: vintage_log_001
Revises: alert_evaluation_001
Create Date: 2026-09-15 13:30:00.000000

Official series are restated: the Q1 figure published in April is not the
June figure, and a table that keeps only "the value of Q1" keeps the June one
-- telling a backtest a number no market participant could have known in May.
``indicator_observations`` is a latest-value store (its primary key is the
period, so a restatement overwrites), and it stays one: it is a Timescale
hypertable partitioned on ``time``, and rebuilding its primary key to carry
vintages is a rebuild of the hypertable.

The vintage log is the audit half: every write to ``indicator_observations``
appends a row here with the value as written and the instant it was published
to this deployment, so any past number can be re-derived as of any date
(``TimeSeriesStore.observations_as_of``). Append-only by contract: nothing
updates or deletes these rows.
"""

from alembic import op
import sqlalchemy as sa

from backend.alembic.guards import (
    create_index_if_missing,
    create_table_if_missing,
    drop_table_if_exists,
)

revision = "vintage_log_001"
down_revision = "alert_evaluation_001"
branch_labels = None
depends_on = None


def upgrade():
    created = create_table_if_missing(
        "indicator_vintage_log",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_code", sa.String(length=100), nullable=False),
        sa.Column("indicator_code", sa.String(length=100), nullable=False),
        sa.Column("region", sa.String(length=50), nullable=False, server_default="GLOBAL"),
        sa.Column("time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Float(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingest_job_id", sa.String(length=100), nullable=True),
    )
    if created:
        create_index_if_missing(
            "ix_vintage_series_published",
            "indicator_vintage_log",
            ["source_code", "indicator_code", "published_at"],
        )


def downgrade():
    drop_table_if_exists("indicator_vintage_log")
