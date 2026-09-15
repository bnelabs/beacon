"""add country profiles

Revision ID: country_profiles_001
Revises: add_datasource_registration_fields
Create Date: 2025-11-06 12:40:00.000000

"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from backend.alembic.guards import (
    create_index_if_missing,
    create_table_if_missing,
    drop_index_if_exists,
    drop_table_if_exists,
)

# revision identifiers, used by Alembic.
revision = 'country_profiles_001'
down_revision = '003'
branch_labels = None
depends_on = None


def upgrade():
    # Create country_profiles table
    create_table_if_missing(
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
    create_index_if_missing('idx_country_code', 'country_profiles', ['country_code'])
    create_index_if_missing('idx_region', 'country_profiles', ['region'])
    create_index_if_missing('idx_risk_level', 'country_profiles', ['risk_level'])
    create_index_if_missing('idx_gdp_usd', 'country_profiles', ['gdp_usd'])

    # Create country_indicators table for time series data
    create_table_if_missing(
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
    create_index_if_missing('idx_country_indicators_country', 'country_indicators', ['country_code'])
    create_index_if_missing('idx_country_indicators_code', 'country_indicators', ['indicator_code'])
    create_index_if_missing('idx_country_indicators_year', 'country_indicators', ['year'])
    create_index_if_missing('idx_country_indicators_category', 'country_indicators', ['category'])

    # Create country_comparisons table for cached comparisons
    create_table_if_missing(
        'country_comparisons',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('country_codes', sa.ARRAY(sa.String(3)), nullable=False),
        sa.Column('comparison_type', sa.String(length=50), nullable=False),  # economic, financial, risk
        sa.Column('results', JSONB, nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )

    create_index_if_missing('idx_country_codes', 'country_comparisons', ['country_codes'], postgresql_using='gin')


def downgrade():
    drop_index_if_exists('idx_country_codes', 'country_comparisons')
    drop_table_if_exists('country_comparisons')

    drop_index_if_exists('idx_country_indicators_category', 'country_indicators')
    drop_index_if_exists('idx_country_indicators_year', 'country_indicators')
    drop_index_if_exists('idx_country_indicators_code', 'country_indicators')
    drop_index_if_exists('idx_country_indicators_country', 'country_indicators')
    drop_table_if_exists('country_indicators')

    drop_index_if_exists('idx_gdp_usd', 'country_profiles')
    drop_index_if_exists('idx_risk_level', 'country_profiles')
    drop_index_if_exists('idx_region', 'country_profiles')
    drop_index_if_exists('idx_country_code', 'country_profiles')
    drop_table_if_exists('country_profiles')
