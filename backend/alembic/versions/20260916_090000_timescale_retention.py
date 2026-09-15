"""opt-in TimescaleDB retention policies for the time-series hypertables

Revision ID: timescale_retention_001
Revises: vintage_log_001
Create Date: 2026-09-16 09:00:00.000000

``20260911_000000_timescale_timeseries`` already declares the two maintenance
policies that are pure wins: a compression policy per hypertable
(``add_compression_policy``, 90 days) and an hourly refresh policy per
continuous aggregate (``add_continuous_aggregate_policy``). The one policy it
deliberately did *not* declare is a **retention** policy, because retention is
the only destructive one -- ``add_retention_policy`` drops whole chunks older
than the horizon, permanently deleting observations.

For a banking early-warning system that deletion is a *policy* decision, not a
schema decision: how long risk scores and indicator observations must be kept
is governed by internal retention rules and, for EU deployments, by audit
expectations. Baking a default horizon into a migration would silently discard
history an operator never agreed to lose.

So this migration is **opt-in and default-off**:

* With ``BEACON_TS_RETENTION_DAYS`` unset (the default) it is a no-op that only
  logs -- no data is ever dropped by upgrading.
* Set ``BEACON_TS_RETENTION_DAYS`` to a positive integer and it attaches
  ``add_retention_policy(table, INTERVAL '<N> days', if_not_exists => TRUE)``
  to each time-series hypertable, so old chunks are dropped automatically on
  the TimescaleDB background scheduler.

Like the migration it completes, it is idempotent (``if_not_exists``), applies
only when TimescaleDB is actually installed (plain PostgreSQL and SQLite keep
the tables unbounded, exactly as before), and degrades to a no-op in offline
``--sql`` mode unless forced with ``-x timescaledb=1``.

The audit half is unaffected: ``indicator_vintage_log`` (vintage_log_001) is an
append-only plain table, *not* one of these hypertables, so restatement history
is never dropped by this policy.
"""

import logging
import os
from typing import Optional

from alembic import context, op
import sqlalchemy as sa

revision = "timescale_retention_001"
down_revision = "vintage_log_001"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

TIMESCALE_EXTENSION = "timescaledb"

#: Environment variable that opts a deployment into automatic retention. Unset
#: (or non-positive / non-integer) means "keep everything", the safe default.
RETENTION_DAYS_ENV = "BEACON_TS_RETENTION_DAYS"

#: The unbounded-growth hypertables created by 20260911_000000. Kept in sync
#: with that migration's HYPERTABLES; the vintage log is intentionally absent
#: (append-only audit data, never dropped).
RETENTION_HYPERTABLES = (
    "indicator_observations",
    "risk_scores",
    "model_metrics",
)


def _timescale_available() -> bool:
    """True only on PostgreSQL with the extension installed.

    Mirrors the probe in 20260911_000000 so both migrations agree. Offline mode
    has no connection to probe, so it renders nothing unless forced.
    """
    if context.is_offline_mode():
        forced = context.get_x_argument(as_dictionary=True).get("timescaledb")
        return str(forced).strip().lower() in {"1", "true", "yes", "on"} if forced else False

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return False
    try:
        row = bind.execute(
            sa.text("SELECT 1 FROM pg_available_extensions WHERE name = :name"),
            {"name": TIMESCALE_EXTENSION},
        ).scalar()
    except Exception:  # noqa: BLE001 - an unavailable catalog query means "no"
        logger.warning("Could not probe for the %s extension; assuming absent", TIMESCALE_EXTENSION)
        return False
    return bool(row)


def _retention_interval() -> Optional[str]:
    """Return e.g. ``'730 days'`` when retention is opted into, else ``None``."""
    raw = os.getenv(RETENTION_DAYS_ENV, "").strip()
    if not raw:
        return None
    try:
        days = int(raw)
    except ValueError:
        logger.warning(
            "Ignoring %s=%r (not an integer number of days); no retention policy applied",
            RETENTION_DAYS_ENV, raw,
        )
        return None
    if days <= 0:
        logger.info("%s=%d is non-positive; treating as 'retain everything'", RETENTION_DAYS_ENV, days)
        return None
    return f"{days} days"


def upgrade() -> None:
    interval = _retention_interval()
    if interval is None:
        logger.info(
            "Retention not requested (set %s to a positive integer of days to "
            "enable automatic chunk drops). No time-series data will be deleted "
            "by this migration.",
            RETENTION_DAYS_ENV,
        )
        return

    if not _timescale_available():
        logger.warning(
            "TimescaleDB is not available on this database; retention policy "
            "(%s) requested via %s cannot be attached. Tables stay unbounded, "
            "as they already were.",
            interval, RETENTION_DAYS_ENV,
        )
        return

    for table in RETENTION_HYPERTABLES:
        op.execute(
            f"SELECT add_retention_policy('{table}', INTERVAL '{interval}', "
            f"if_not_exists => TRUE)"
        )
    logger.info("Attached a %s retention policy to %s", interval, ", ".join(RETENTION_HYPERTABLES))


def downgrade() -> None:
    # Removing a retention policy never deletes data; it only stops future
    # automatic drops. Guarded because the policy may never have been added.
    if not _timescale_available():
        return
    for table in RETENTION_HYPERTABLES:
        op.execute(f"SELECT remove_retention_policy('{table}', if_exists => TRUE)")
