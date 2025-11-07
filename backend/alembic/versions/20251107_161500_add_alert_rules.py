"""Add alert_rules table

Revision ID: 20251107_161500
Create Date: 2025-11-07 16:15:00
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers
revision = '20251107_161500'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('alert_rules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=200), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('category', sa.String(length=50), nullable=False),
        sa.Column('metric_type', sa.String(length=100), nullable=False),
        sa.Column('condition_operator', sa.String(length=20), nullable=False),
        sa.Column('threshold_value', sa.Float(), nullable=False),
        sa.Column('evaluation_window_minutes', sa.Integer(), nullable=True),
        sa.Column('evaluation_frequency_minutes', sa.Integer(), nullable=True),
        sa.Column('is_enabled', sa.Boolean(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=True),
        sa.Column('notification_priority', sa.String(length=20), nullable=True),
        sa.Column('notification_message_template', sa.Text(), nullable=True),
        sa.Column('rule_config', sa.JSON(), nullable=True),
        sa.Column('last_triggered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_evaluated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('trigger_count', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_by', sa.String(length=100), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_alert_rules_id'), 'alert_rules', ['id'], unique=False)


def downgrade():
    op.drop_index(op.f('ix_alert_rules_id'), table_name='alert_rules')
    op.drop_table('alert_rules')
