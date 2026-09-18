"""repair stale catalogue contracts exposed by the full collection job

Revision ID: catalogue_provider_fixes_001
Revises: timescale_retention_001
Create Date: 2026-09-18 18:00:00.000000

The first full collection after the provider hardening release made several
stale catalogue rows visible: SEC's public submissions field changed name,
some FRED/IMF series were retired, BIS changed the current series keys, and
the mounted AI4Risk release has no ratings file.  Keep those rows in the
catalogue for auditability, but stop selecting entries that cannot produce
data.  The migration is deliberately targeted by stable catalogue code so it
does not delete jobs or rewrite collected observations.
"""

from alembic import op
import sqlalchemy as sa


revision = "catalogue_provider_fixes_001"
down_revision = "timescale_retention_001"
branch_labels = None
depends_on = None


DISABLED_CODES = (
    "BIS_DEBT_SERVICE_RATIO_EU",
    "IMF_FSI",
    "IMF_IFS_RESERVES",
    "WB_BANK_CAPITAL_RATIO_EU",
    "WB_BANK_NPL_EU",
    "FRED_LIBOR_OIS_SPREAD",
    "IR_LIBOR_3M",
    "FRED_MOVE_INDEX",
    "AI4RISK_CREDIT_RATINGS",
    "AI4RISK_SYSTEMIC_RISK",
)


def _set_catalogue_state(code: str, *, enabled: bool, default_selected: bool) -> None:
    op.execute(
        sa.text(
            "UPDATE data_catalogue "
            "SET enabled = :enabled, default_selected = :default_selected "
            "WHERE code = :code"
        ).bindparams(
            enabled=enabled,
            default_selected=default_selected,
            code=code,
        )
    )


def upgrade() -> None:
    bind = op.get_bind()

    # The public SEC submissions API uses filingDate, and the plugin fix is
    # code-only; these rows can safely participate in the default panel now.
    for code in ("SEC_BANK_FINANCIALS", "SEC_INSTITUTIONAL_HOLDINGS"):
        _set_catalogue_state(code, enabled=True, default_selected=True)

    bind.execute(
        sa.text(
            "UPDATE data_catalogue "
            "SET endpoint = :endpoint "
            "WHERE code = 'BIS_GLOBAL_LIQUIDITY'"
        ),
        {"endpoint": "WS_GLI/Q.USD.3P.N.A.I.B.USD"},
    )

    # The retired FRED London PM fixing has no public series replacement in
    # the keyless graph endpoint. Yahoo's GC=F contract is an explicit price
    # series and uses the asset transport already used by the stock panel.
    bind.execute(
        sa.text(
            "UPDATE data_catalogue "
            "SET name = :name, description = :description, endpoint = :endpoint, "
            "data_source_id = (SELECT id FROM data_sources WHERE name = :source) "
            "WHERE code = 'COMM_GOLD'"
        ),
        {
            "name": "Gold Futures Price",
            "description": "Gold futures price from Yahoo Finance (GC=F)",
            "endpoint": "GC=F",
            "source": "Yahoo Finance",
        },
    )

    for code in DISABLED_CODES:
        _set_catalogue_state(code, enabled=False, default_selected=False)


def downgrade() -> None:
    bind = op.get_bind()

    # Restore each row's pre-migration selection state.  These rows were not
    # all default-selected before the repair (for example LIBOR and the FRED
    # OIS spread were already opt-in), so a blanket TRUE/TRUE downgrade would
    # silently change the operator's catalogue defaults.
    previous_states = {
        "BIS_DEBT_SERVICE_RATIO_EU": (True, True),
        "IMF_FSI": (True, False),
        "IMF_IFS_RESERVES": (True, True),
        "WB_BANK_CAPITAL_RATIO_EU": (True, True),
        "WB_BANK_NPL_EU": (True, True),
        "FRED_LIBOR_OIS_SPREAD": (True, False),
        "IR_LIBOR_3M": (True, False),
        "FRED_MOVE_INDEX": (True, True),
        "AI4RISK_CREDIT_RATINGS": (True, True),
        "AI4RISK_SYSTEMIC_RISK": (True, True),
    }
    for code, (enabled, default_selected) in previous_states.items():
        _set_catalogue_state(code, enabled=enabled, default_selected=default_selected)

    # Restore the pre-migration catalogue values for operators who explicitly
    # choose to downgrade.  This is intentionally limited to catalogue rows;
    # no collected data or job history is touched.
    for code in ("SEC_BANK_FINANCIALS", "SEC_INSTITUTIONAL_HOLDINGS"):
        _set_catalogue_state(code, enabled=True, default_selected=False)

    bind.execute(
        sa.text(
            "UPDATE data_catalogue "
            "SET endpoint = :endpoint "
            "WHERE code = 'BIS_GLOBAL_LIQUIDITY'"
        ),
        {"endpoint": "WS_GLI/Q.5A.N.5J.N"},
    )
    bind.execute(
        sa.text(
            "UPDATE data_catalogue "
            "SET name = :name, description = :description, endpoint = :endpoint, "
            "data_source_id = (SELECT id FROM data_sources WHERE name = :source) "
            "WHERE code = 'COMM_GOLD'"
        ),
        {
            "name": "Gold Price",
            "description": "Gold fixing price (London PM)",
            "endpoint": "GOLDPMGBD228NLBM",
            "source": "FRED",
        },
    )
