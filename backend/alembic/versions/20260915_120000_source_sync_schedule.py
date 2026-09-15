"""per-source collection schedule and sync telemetry

Revision ID: source_sync_schedule_001
Revises: notifications_extra_data_001
Create Date: 2026-09-15 12:00:00.000000

Collection was manual-only: a "Sync Now" button that stamped a time, and a
job API nothing invoked on a clock. The scheduler needs somewhere to keep a
source's cadence and its last outcome, and the health payload needs the same
columns to answer "when did this feed last succeed, and is it overdue".

Guarded like every revision that can meet a database it did not create: each
column is added only when the inspector says it is missing, so an existing
deployment and a fresh one reach the same schema.
"""

from alembic import op
import sqlalchemy as sa

from backend.alembic.guards import add_column_if_missing, drop_column_if_exists

revision = "source_sync_schedule_001"
down_revision = "notifications_extra_data_001"
branch_labels = None
depends_on = None

COLUMNS = (
    ("sync_interval_minutes", sa.Integer(), {"nullable": True}),
    (
        "consecutive_failures",
        sa.Integer(),
        {"nullable": False, "server_default": "0"},
    ),
    ("last_sync_started_at", sa.DateTime(timezone=True), {"nullable": True}),
    ("last_sync_duration_ms", sa.Integer(), {"nullable": True}),
    ("last_sync_rows", sa.Integer(), {"nullable": True}),
)


def upgrade():
    for name, column_type, kwargs in COLUMNS:
        add_column_if_missing("data_sources", name, column_type, **kwargs)


def downgrade():
    for name, _column_type, _kwargs in reversed(COLUMNS):
        drop_column_if_exists("data_sources", name)
