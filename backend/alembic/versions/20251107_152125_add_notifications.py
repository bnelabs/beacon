"""add notifications table

Revision ID: 20251107_152125
Revises: add_country_profiles
Create Date: 2025-11-07 15:21:25
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON

# revision identifiers, used by Alembic.
revision = '20251107_152125'
down_revision = 'add_country_profiles'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'notifications',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('notification_type', sa.String(length=50), nullable=False),
        sa.Column('category', sa.String(length=50), nullable=True),
        sa.Column('priority', sa.String(length=20), nullable=False, server_default='medium'),
        sa.Column('is_urgent', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_read', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_dismissed', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('is_archived', sa.Boolean(), nullable=False, server_default='false'),
        sa.Column('action_url', sa.String(length=500), nullable=True),
        sa.Column('action_label', sa.String(length=100), nullable=True),
        sa.Column('related_entity_type', sa.String(length=50), nullable=True),
        sa.Column('related_entity_id', sa.Integer(), nullable=True),
        sa.Column('metadata', JSON, nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column('read_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('dismissed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_index('ix_notifications_id', 'notifications', ['id'])
    op.create_index('ix_notifications_is_read', 'notifications', ['is_read'])
    op.create_index('ix_notifications_priority', 'notifications', ['priority'])
    op.create_index('ix_notifications_category', 'notifications', ['category'])
    op.create_index('ix_notifications_created_at', 'notifications', ['created_at'])
    op.create_index('ix_notifications_entity', 'notifications', ['related_entity_type', 'related_entity_id'])


def downgrade():
    op.drop_index('ix_notifications_entity', table_name='notifications')
    op.drop_index('ix_notifications_created_at', table_name='notifications')
    op.drop_index('ix_notifications_category', table_name='notifications')
    op.drop_index('ix_notifications_priority', table_name='notifications')
    op.drop_index('ix_notifications_is_read', table_name='notifications')
    op.drop_index('ix_notifications_id', table_name='notifications')
    op.drop_table('notifications')
