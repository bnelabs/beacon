"""add country profiles

Revision ID: country_profiles_001
Revises: add_datasource_registration_fields
Create Date: 2025-11-06 12:40:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision = 'country_profiles_001'
down_revision = 'add_datasource_registration_fields'
branch_labels = None
depends_on = None


def upgrade():
    # Create country_profiles table
    op.create_table(
        'country_profiles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('country_code', sa.String(length=3), nullable=False),
        sa.Column('country_name', sa.String(length=100), nullable=False),
        sa.Column('region', sa.String(length=50), nullable=True),
        sa.Column('sub_region', sa.String(length=100), nullable=True),
        sa.Column('iso_alpha_3', sa.String(length=3), nullable=True),
        sa.Column('capital', sa.String(length=100), nullable=True),
        sa.Column('currency', sa.String(length=50), nullable=True),
        sa.Column('latitude', sa.Numeric(10, 6), nullable=True),
        sa.Column('longitude', sa.Numeric(10, 6), nullable=True),
        sa.Column('population', sa.BigInteger(), nullable=True),
        sa.Column('gdp_usd', sa.Numeric(20, 2), nullable=True),
        sa.Column('gdp_per_capita', sa.Numeric(12, 2), nullable=True),
        sa.Column('gdp_growth_rate', sa.Numeric(5, 2), nullable=True),
        sa.Column('inflation_rate', sa.Numeric(5, 2), nullable=True),
        sa.Column('unemployment_rate', sa.Numeric(5, 2), nullable=True),
        sa.Column('credit_to_gdp', sa.Numeric(5, 2), nullable=True),
        sa.Column('debt_to_gdp', sa.Numeric(5, 2), nullable=True),
        sa.Column('fiscal_balance', sa.Numeric(5, 2), nullable=True),
        sa.Column('current_account_balance', sa.Numeric(5, 2), nullable=True),
        sa.Column('bank_count', sa.Integer(), nullable=True),
        sa.Column('total_bank_assets_usd', sa.Numeric(20, 2), nullable=True),
        sa.Column('risk_level', sa.String(length=20), nullable=True),  # low, medium, high, critical
        sa.Column('risk_score', sa.Numeric(5, 2), nullable=True),  # 0-100
        sa.Column('meta_data', JSONB, nullable=True),  # Additional flexible data
        sa.Column('last_updated', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('country_code')
    )

    # Create indexes
    op.create_index('idx_country_code', 'country_profiles', ['country_code'])
    op.create_index('idx_region', 'country_profiles', ['region'])
    op.create_index('idx_risk_level', 'country_profiles', ['risk_level'])
    op.create_index('idx_gdp_usd', 'country_profiles', ['gdp_usd'])

    # Create country_indicators table for time series data
    op.create_table(
        'country_indicators',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('country_code', sa.String(length=3), nullable=False),
        sa.Column('indicator_code', sa.String(length=50), nullable=False),
        sa.Column('indicator_name', sa.String(length=255), nullable=True),
        sa.Column('category', sa.String(length=50), nullable=True),  # economic, financial, social, infrastructure
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('value', sa.Numeric(20, 6), nullable=True),
        sa.Column('unit', sa.String(length=50), nullable=True),
        sa.Column('source', sa.String(length=100), nullable=True),  # World Bank, IMF, etc.
        sa.Column('last_updated', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['country_code'], ['country_profiles.country_code'], ondelete='CASCADE'),
        sa.UniqueConstraint('country_code', 'indicator_code', 'year', name='uq_country_indicator_year')
    )

    # Create indexes for efficient queries
    op.create_index('idx_country_indicators_country', 'country_indicators', ['country_code'])
    op.create_index('idx_country_indicators_code', 'country_indicators', ['indicator_code'])
    op.create_index('idx_country_indicators_year', 'country_indicators', ['year'])
    op.create_index('idx_country_indicators_category', 'country_indicators', ['category'])

    # Create country_comparisons table for cached comparisons
    op.create_table(
        'country_comparisons',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('country_codes', sa.ARRAY(sa.String(3)), nullable=False),
        sa.Column('comparison_type', sa.String(length=50), nullable=False),  # economic, financial, risk
        sa.Column('results', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_index('idx_country_codes', 'country_comparisons', ['country_codes'], postgresql_using='gin')


def downgrade():
    op.drop_index('idx_country_codes', table_name='country_comparisons')
    op.drop_table('country_comparisons')

    op.drop_index('idx_country_indicators_category', table_name='country_indicators')
    op.drop_index('idx_country_indicators_year', table_name='country_indicators')
    op.drop_index('idx_country_indicators_code', table_name='country_indicators')
    op.drop_index('idx_country_indicators_country', table_name='country_indicators')
    op.drop_table('country_indicators')

    op.drop_index('idx_gdp_usd', table_name='country_profiles')
    op.drop_index('idx_risk_level', table_name='country_profiles')
    op.drop_index('idx_region', table_name='country_profiles')
    op.drop_index('idx_country_code', table_name='country_profiles')
    op.drop_table('country_profiles')
