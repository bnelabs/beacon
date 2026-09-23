"""say where a vintage came from, and remember which snapshots were already read

Revision ID: vintage_provenance_001
Revises: data_frequency_contract_001
Create Date: 2026-09-19 09:00:00.000000

``vintage_log_001`` created the audit table but not the provenance the audit
needs. Every row it wrote carries a ``published_at`` produced by
``TimeSeriesStore._append_vintages``, which stamps the instant *this deployment*
wrote the row -- correct for a live ingest, and wrong for anything read back out
of a certified dataset snapshot. Meanwhile ``DatasetSnapshotter`` had been filing
a content-addressed directory per certification for as long as it has existed,
and nothing read those directories. So "what did this deployment know on 3 March"
was answerable only for whatever had been collected since the log was created,
while the payload that proves the answer sat on the job volume unqueried.

This revision lets ``backend.modules.results.vintage_backfill`` close that gap:

``indicator_vintage_log.snapshot_id``
    the content address of the certified snapshot a vintage was read from; NULL
    for a live pipeline write.
``indicator_vintage_log.publication_basis``
    *why* ``published_at`` is what it is: ``ingest_instant`` (this deployment
    wrote it), ``certified_snapshot`` (the snapshot's capture instant), or NULL,
    which means the row predates provenance. NULL is deliberately not backfilled
    to either real value -- guessing would let an as-of answer claim a publication
    the deployment never witnessed, which is the defect the log exists to expose.
    The reader reports those rows as ``unknown``.
``vintage_backfill_runs``
    the idempotency ledger: one row per certified snapshot already read in, with
    the counts it produced. Idempotency is *not* a unique constraint on
    ``indicator_vintage_log``: the vintage log is append-only, and making it
    idempotent by keying and updating its rows is precisely the write the audit
    table exists to forbid. An application that wrote nothing is still recorded,
    because "nothing to do" and "already done" are different answers for an
    operator deciding whether the backfill finished.

Two indexes travel with it. ``ix_vintage_series_published`` was already declared
by ``vintage_log_001`` (only when it created the table) and by the model, so a
volume that has it keeps it; a legacy ``create_all()`` volume that predates the
model declaration gets it here, because an as-of query's access path should not
depend on which history the volume followed. ``ix_vintage_log_snapshot`` makes
"which vintages came from snapshot X" a lookup rather than a scan of an
append-only table that grows with every restatement.

Guarded throughout: the columns are nullable, so a database that already carries
them (built by ``create_all()`` on this release, then upgraded) is skipped rather
than failed, and a re-upgrade is a no-op.
"""

from alembic import op
import sqlalchemy as sa

from backend.alembic.guards import (
    add_column_if_missing,
    create_index_if_missing,
    create_table_if_missing,
    drop_column_if_exists,
    drop_index_if_exists,
    drop_table_if_exists,
)

revision = "vintage_provenance_001"
down_revision = "data_frequency_contract_001"
branch_labels = None
depends_on = None


def upgrade():
    add_column_if_missing("indicator_vintage_log", "snapshot_id", sa.String(length=80), nullable=True)
    add_column_if_missing("indicator_vintage_log", "publication_basis", sa.String(length=32), nullable=True)

    # Both indexes are asserted unconditionally: a volume whose
    # indicator_vintage_log predates the model's __table_args__ has neither, and
    # ``create_index_if_missing`` skips the ones that already exist.
    create_index_if_missing(
        "ix_vintage_series_published",
        "indicator_vintage_log",
        ["source_code", "indicator_code", "published_at"],
    )
    create_index_if_missing("ix_vintage_log_snapshot", "indicator_vintage_log", ["snapshot_id"])

    create_table_if_missing(
        "vintage_backfill_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("snapshot_id", sa.String(length=80), nullable=False, unique=True),
        sa.Column("job_id", sa.String(length=100), nullable=True),
        sa.Column("snapshot_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rows_written", sa.Integer(), nullable=False),
        sa.Column("rows_skipped", sa.Integer(), nullable=False),
        sa.Column("source_directory", sa.String(length=500), nullable=True),
    )
    create_index_if_missing("ix_vintage_backfill_applied", "vintage_backfill_runs", ["applied_at"])


def downgrade():
    # The ledger first: without it a re-run cannot tell "already applied" from
    # "nothing to do", which is the answer the backfill's idempotency rests on.
    drop_index_if_exists("ix_vintage_backfill_applied", "vintage_backfill_runs")
    drop_table_if_exists("vintage_backfill_runs")

    # The provenance columns, but not the rows written under them. A backfilled
    # vintage is history that was *recovered*, not invented: dropping the label
    # that says so is a downgrade, deleting the history would be a loss. Those
    # rows stay, and with their basis gone the as-of reader reports them as
    # ``unknown`` rather than silently presenting them as live ingests.
    drop_index_if_exists("ix_vintage_log_snapshot", "indicator_vintage_log")
    drop_column_if_exists("indicator_vintage_log", "publication_basis")
    drop_column_if_exists("indicator_vintage_log", "snapshot_id")
