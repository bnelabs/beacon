"""Relabel FRED_REPO_RATE as an RRP dollar volume (L-65)

Revision ID: fred_repo_rate_relabel_001
Revises: vintage_provenance_001
Create Date: 2026-09-30 12:00:00.000000

L-65 (docs/FAILURE_LEDGER.md): the catalogue item FRED_REPO_RATE stores the
Fed's Overnight Reverse Repo Facility dollar VOLUME (FRED RRPONTSYD,
billions of USD, daily) but was catalogued and trained as a repo RATE
(percentage). The stored observations are the genuine upstream values (the
2022 peak ~2,553.7 is the ~$2.55T RRP balance; a live unit/magnitude
cross-check against the FRED endpoint description confirmed the identity),
so this migration keeps the historical identity — no re-point, no deletion,
no value rewrite — and corrects the semantics on the metadata instead:

* catalogue FRED_REPO_RATE: name/description/unit -> the true RRP volume
  semantics; risk_types aligned with the canonical FRED_RRPONTSYD entry
  (funding only, market_liquidity removed); default_selected -> False, so
  future default panels no longer carry a dollar volume presented as a rate
  and no collection duplicates the endpoint the canonical entry serves.
* indicator_observations rows under FRED_REPO_RATE: unit label corrected
  from 'percentage' to 'billions_usd'. Values are untouched; the vintage
  log is untouched.
* catalogue FRED_RRPONTSYD: description notes that FRED_REPO_RATE is the
  legacy identity for the same upstream series.

Neither change touches collected values, jobs, or models. Retraining with
the corrected semantics is a separate step (the deployed model still carries
the series trained as a rate).
"""

from alembic import op
import sqlalchemy as sa


revision = "fred_repo_rate_relabel_001"
down_revision = "vintage_provenance_001"
branch_labels = None
depends_on = None


REPO_RATE = "FRED_REPO_RATE"
RRPONTSYD = "FRED_RRPONTSYD"

REPO_RATE_NAME = "US Overnight RRP Facility: Volume of Residual Collateral"
REPO_RATE_DESCRIPTION = (
    "FRED RRPONTSYD - dollar volume of residual collateral in the NY Fed "
    "overnight reverse-repo facility, in billions of USD, daily. This is a "
    "dollar volume, not an interest rate. It was historically catalogued as "
    "'US Overnight Repo Rate' (percentage); the stored observations under "
    "this code are the genuine RRPONTSYD values, and the identity is "
    "preserved (see L-65 in docs/FAILURE_LEDGER.md). Not default-selected: "
    "the same upstream series is available under the canonical code "
    "FRED_RRPONTSYD, and a second default collection of the same endpoint "
    "would only duplicate data. Do not use as a rate-family feature."
)
RRPONTSYD_DESCRIPTION = (
    "Daily balances in the NY Fed overnight reverse-repo facility; a gauge "
    "of system-wide safe-asset demand and cash abundance. Canonical "
    "catalogue identity for FRED RRPONTSYD; the legacy code FRED_REPO_RATE "
    "carries the same upstream series under a preserved historical identity "
    "(see L-65 in docs/FAILURE_LEDGER.md)."
)


def upgrade() -> None:
    bind = op.get_bind()

    bind.execute(
        sa.text(
            "UPDATE data_catalogue "
            "SET name = :name, description = :description, unit = :unit, "
            "risk_types = CAST(:risk_types AS json), default_selected = :default_selected "
            "WHERE code = :code"
        ),
        {
            "name": REPO_RATE_NAME,
            "description": REPO_RATE_DESCRIPTION,
            "unit": "billions_usd",
            "risk_types": '["funding_liquidity"]',
            "default_selected": False,
            "code": REPO_RATE,
        },
    )

    # The stored rows are the genuine RRPONTSYD values; only the unit label
    # was wrong. Values and the vintage log are untouched.
    bind.execute(
        sa.text(
            "UPDATE indicator_observations "
            "SET unit = :unit "
            "WHERE indicator_code = :code AND unit = :old_unit"
        ),
        {"unit": "billions_usd", "code": REPO_RATE, "old_unit": "percentage"},
    )

    bind.execute(
        sa.text(
            "UPDATE data_catalogue SET description = :description WHERE code = :code"
        ),
        {"description": RRPONTSYD_DESCRIPTION, "code": RRPONTSYD},
    )


def downgrade() -> None:
    bind = op.get_bind()

    # Restore the pre-migration catalogue row and unit labels. The stored
    # values never changed, so no data is touched either way.
    bind.execute(
        sa.text(
            "UPDATE data_catalogue "
            "SET name = :name, description = :description, unit = :unit, "
            "risk_types = CAST(:risk_types AS json), default_selected = :default_selected "
            "WHERE code = :code"
        ),
        {
            "name": "US Overnight Repo Rate",
            "description": "Overnight repurchase agreement rate",
            "unit": "percentage",
            "risk_types": '["funding_liquidity", "market_liquidity"]',
            "default_selected": True,
            "code": REPO_RATE,
        },
    )
    bind.execute(
        sa.text(
            "UPDATE indicator_observations "
            "SET unit = :unit "
            "WHERE indicator_code = :code AND unit = :new_unit"
        ),
        {"unit": "percentage", "code": REPO_RATE, "new_unit": "billions_usd"},
    )
    bind.execute(
        sa.text(
            "UPDATE data_catalogue SET description = :description WHERE code = :code"
        ),
        {
            "description": (
                "Daily balances in the NY Fed overnight reverse-repo facility; "
                "a gauge of system-wide safe-asset demand and cash abundance."
            ),
            "code": RRPONTSYD,
        },
    )
