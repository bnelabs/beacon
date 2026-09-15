"""alert rules: remember when each rule was last evaluated and triggered

Revision ID: alert_evaluation_001
Revises: source_sync_schedule_001
Create Date: 2026-09-15 13:00:00.000000

Rule evaluation runs on a clock (celery beat). Without a per-rule memory of
"last evaluated" the tick would re-evaluate every rule every five minutes
regardless of each rule's own frequency, and without "last triggered" the
cooldown (do not re-alert while a breach is still fresh) would have nothing
to read. Guarded: an existing database may predate the evaluator entirely.
"""

from alembic import op
import sqlalchemy as sa

from backend.alembic.guards import add_column_if_missing, drop_column_if_exists

revision = "alert_evaluation_001"
down_revision = "source_sync_schedule_001"
branch_labels = None
depends_on = None


def upgrade():
    add_column_if_missing("alert_rules", "last_evaluated_at", sa.DateTime(timezone=True), nullable=True)
    add_column_if_missing("alert_rules", "last_triggered_at", sa.DateTime(timezone=True), nullable=True)


def downgrade():
    drop_column_if_exists("alert_rules", "last_triggered_at")
    drop_column_if_exists("alert_rules", "last_evaluated_at")
