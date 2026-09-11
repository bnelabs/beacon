"""add datasource registration fields

Revision ID: 003
Revises: (root - no prior revision exists in this repository)
Create Date: 2025-10-30

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers
revision = '003'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Add new columns to data_sources table
    op.add_column('data_sources', sa.Column('registration_url', sa.String(500), nullable=True))
    op.add_column('data_sources', sa.Column('registration_required', sa.Boolean(), default=False, nullable=True))
    op.add_column('data_sources', sa.Column('free_tier_limits', sa.Text(), nullable=True))
    op.add_column('data_sources', sa.Column('coverage_description', sa.Text(), nullable=True))


def downgrade():
    # Remove columns
    op.drop_column('data_sources', 'coverage_description')
    op.drop_column('data_sources', 'free_tier_limits')
    op.drop_column('data_sources', 'registration_required')
    op.drop_column('data_sources', 'registration_url')
