"""add datasource registration fields

Revision ID: 003
Revises: (root - no prior revision exists in this repository)
Create Date: 2025-10-30

Why this revision is guarded
----------------------------

``003`` is the root of the chain, so it is the *first* thing ``alembic upgrade
head`` runs on an empty database. But ``data_sources`` is not created until
``baseline_core_001``, five revisions later. The unguarded version of this file
therefore made a fresh install impossible:

    sqlalchemy.exc.ProgrammingError: (psycopg2.errors.UndefinedTable)
    relation "data_sources" does not exist
    [SQL: ALTER TABLE data_sources ADD COLUMN registration_url VARCHAR(500)]

Both backend and celery-worker ran it from their entrypoints, so both
restart-looped and the API never came up. Reproduced against PostgreSQL 15 on an
empty database before the fix, and verified after it (see
``backend/tests/test_migrations_live.py``).

The other direction matters too. A database built by the old
``Base.metadata.create_all()`` path already has these columns, because they are
declared on ``backend.models.data_source``; an unconditional ``add_column``
raises ``DuplicateColumn`` there. So the guard is not only "skip on fresh", it is
"add exactly the columns that are missing, whatever the database's history".

The revision id and ``down_revision`` are **not** changed. Deployed databases
record ``003`` in ``alembic_version`` and renumbering it would orphan them.

Nothing here catches an exception: a column is skipped only when the inspector
says it is already there. See ``backend/alembic/guards.py``.
"""
import sqlalchemy as sa

from backend.alembic.guards import (
    add_column_if_missing,
    drop_column_if_exists,
    has_table,
    skip_because_absent,
)


# revision identifiers
revision = '003'
down_revision = None
branch_labels = None
depends_on = None

#: Optional metadata columns added to ``data_sources``. Every one is nullable:
#: they were introduced after rows already existed, and a registration detail
#: that is absent is reported as absent rather than defaulted into meaning
#: something.
REGISTRATION_COLUMNS = (
    ('registration_url', sa.String(500)),
    ('registration_required', sa.Boolean()),
    ('free_tier_limits', sa.Text()),
    ('coverage_description', sa.Text()),
)


def upgrade():
    # On a fresh database the table does not exist yet and baseline_core_001
    # creates it five revisions later, from model metadata that already carries
    # these columns -- so there is nothing for this revision to do. That single
    # fact is what made a clean install impossible when it was not checked.
    #
    # Offline (--sql) rendering has no inspector, so it cannot make that
    # judgement; skip_because_absent() is False there and the ALTERs are rendered
    # as they were before the guard existed. An offline render is a review
    # artefact, not a correctness proof -- see test_migrations_live.py.
    if not has_table('data_sources') and skip_because_absent():
        return

    for name, column_type in REGISTRATION_COLUMNS:
        add_column_if_missing('data_sources', name, column_type, nullable=True)


def downgrade():
    if not has_table('data_sources'):
        return

    for name, _ in reversed(REGISTRATION_COLUMNS):
        drop_column_if_exists('data_sources', name)
