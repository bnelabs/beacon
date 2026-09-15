"""baseline core schema: one Alembic owns the whole schema

Revision ID: baseline_core_001
Revises: timescale_001

Before this migration the repository had two schema sources of truth and
neither was complete:

* ``init_db()`` (``Base.metadata.create_all``) created most tables but no
  hypertables or continuous aggregates, and ran from the API lifespan;
* the Alembic chain created notifications/alert_rules/country profiles and
  the time-series tables, but had **no migration at all** for jobs,
  data_sources, data_catalogue, assets, error_logs or the four job tables --
  so ``alembic upgrade head`` on a fresh database produced a schema the
  application could not run against, while running it against a database
  the API had already booted crashed on unguarded ``create_table`` calls.

This baseline closes the gap in the only direction that does not fork the
truth again: for every table still missing from the database, create it from
the model metadata (``checkfirst=True``), and from here on schema changes
arrive as explicit migrations. Containers run ``alembic upgrade head`` from
``backend/entrypoint.sh`` before the API or worker starts, so deployments
get hypertables and continuous aggregates instead of silently living on the
base-table fallback.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "baseline_core_001"
down_revision = "timescale_001"
branch_labels = None
depends_on = None

#: Tables the old create_all path owned and the migration chain never had.
CORE_TABLES = (
    "jobs",
    "data_sources",
    "data_catalogue",
    "assets",
    "error_logs",
    "pipeline_jobs",
    "data_jobs",
    "engine_jobs",
    "result_jobs",
)


def upgrade() -> None:
    if op.get_context().as_sql:
        # Offline rendering (--sql) has no live inspector; reconciliation is
        # a no-op there by design, and saying so keeps renders honest.
        op.execute(sa.text(
            "-- baseline_core_001: schema reconciliation requires a live "
            "database; nothing to render offline"
        ))
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    existing = set(inspector.get_table_names())

    # Importing the models registers every table on Base.metadata; creating
    # only the missing ones keeps this migration safe on databases built by
    # either historical path (fresh, create_all-ed, or partially migrated).
    from backend.database import Base
    from backend.models import (  # noqa: F401 - registration imports
        asset,
        data_catalogue,
        data_source,
        error_log,
        job,
        pipeline_job,
        timeseries,
    )

    for name in CORE_TABLES:
        if name in existing:
            continue
        table = Base.metadata.tables.get(name)
        if table is None:
            raise RuntimeError(
                f"baseline migration expects table {name!r} in Base.metadata"
            )
        table.create(bind, checkfirst=True)


def downgrade() -> None:
    # The baseline is a reconciliation, not a feature: dropping core tables
    # in a downgrade would destroy data on databases that predate it.
    raise RuntimeError(
        "baseline_core_001 cannot be downgraded: it reconciles pre-existing "
        "schema rather than introducing it"
    )
