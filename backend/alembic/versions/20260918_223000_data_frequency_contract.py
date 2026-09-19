"""align catalogue cadence labels with observed provider contracts

Revision ID: data_frequency_contract_001
Revises: catalogue_provider_fixes_001
Create Date: 2026-09-18 22:30:00.000000

The sixth major collection exposed several catalogue rows whose declared
frequency did not match the dates returned by the provider.  A daily label on
monthly or event observations makes freshness scoring and rolling features
misleading.  Keep the collected history intact and repair only the metadata
contract used by validation and downstream consumers.
"""

from alembic import op
import sqlalchemy as sa


revision = "data_frequency_contract_001"
down_revision = "catalogue_provider_fixes_001"
branch_labels = None
depends_on = None


FREQUENCY_FIXES = {
    "IR_FED_FUNDS": "monthly",
    "BANK_US_RESERVES": "monthly",
    "BANK_US_COMMERCIAL_LOANS": "monthly",
    "IR_EURIBOR_1M": "event",
    "IR_ECB_DEPOSIT": "event",
}

PREVIOUS_FREQUENCIES = {
    "IR_FED_FUNDS": "daily",
    "BANK_US_RESERVES": "weekly",
    "BANK_US_COMMERCIAL_LOANS": "weekly",
    "IR_EURIBOR_1M": "daily",
    "IR_ECB_DEPOSIT": "daily",
}


def _set_frequency(code: str, frequency: str) -> None:
    op.execute(
        sa.text(
            "UPDATE data_catalogue SET frequency = :frequency WHERE code = :code"
        ).bindparams(frequency=frequency, code=code)
    )


def upgrade() -> None:
    for code, frequency in FREQUENCY_FIXES.items():
        _set_frequency(code, frequency)


def downgrade() -> None:
    for code, frequency in PREVIOUS_FREQUENCIES.items():
        _set_frequency(code, frequency)
