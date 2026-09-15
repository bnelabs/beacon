"""align notifications.extra_data with the model

Revision ID: notifications_extra_data_001
Revises: baseline_core_001
Create Date: 2026-09-15

Why this revision exists
------------------------

``20251107_152125`` created ``notifications`` with a ``metadata`` JSON column.
The model has always declared ``extra_data``::

    backend/models/notification.py:46    extra_data = Column(JSON, nullable=True)
    backend/schemas/notification.py:20   extra_data: Optional[Dict[str, Any]] = None

So the two schema paths disagreed. A database built by
``Base.metadata.create_all()`` got ``extra_data``; a database built by
``alembic upgrade head`` got ``metadata`` -- a column no ORM query, schema or
route references, on a table whose declared column is therefore missing. Any
notification insert or select touching ``extra_data`` fails on a
migrated-from-empty database with ``UndefinedColumn``.

Found by comparing the two histories column by column rather than by reading
either one; ``backend/tests/test_migrations_live.py`` asserts they end at the
same schema. Nothing in the tree caught it, because the notification route tests
run on SQLite built by ``create_all`` -- the path that was already correct.

Editing ``20251107_152125`` alone would fix a database migrated from now on, but
a database that already ran it has ``metadata`` on disk and will never execute
that revision again. So the old revision now declares the column the model
declares, and this one renames it where the wrong name already landed. Every
branch is guarded, so on all three histories -- empty, ``create_all``,
already-migrated -- this is a rename or a no-op, never an error.
"""
from alembic import op
import sqlalchemy as sa

from backend.alembic.guards import add_column_if_missing, has_column, has_table

# revision identifiers, used by Alembic.
revision = 'notifications_extra_data_001'
down_revision = 'baseline_core_001'
branch_labels = None
depends_on = None

TABLE = 'notifications'
MODEL_COLUMN = 'extra_data'      # what backend/models/notification.py declares
MIGRATION_COLUMN = 'metadata'    # what 20251107_152125 used to create


def upgrade():
    if has_column(TABLE, MIGRATION_COLUMN) and not has_column(TABLE, MODEL_COLUMN):
        # Migrated from empty before this revision existed: rename, so the
        # notification payloads already stored in the column keep their contents.
        op.alter_column(TABLE, MIGRATION_COLUMN, new_column_name=MODEL_COLUMN)
        return

    if has_column(TABLE, MODEL_COLUMN):
        # Built by create_all, or already reconciled. Nothing to do.
        return

    if not has_table(TABLE):
        # Offline rendering, or a database where the table has not been created
        # yet. Either way 20251107_152125 has already declared the column with
        # the name the model uses, so emitting an ALTER here would render a
        # redundant statement -- and an offline render that adds a column the
        # CREATE TABLE above it already contains is not a script anyone should
        # be handed.
        return

    # Neither name is present on a live database, which no history should
    # produce. The column is nullable, so add it rather than fail: its absence
    # would break every notification write, and there is no data here that a
    # guess could be wrong about.
    add_column_if_missing(TABLE, MODEL_COLUMN, sa.JSON(), nullable=True)


def downgrade():
    # Reverse the rename only. Dropping the column would discard notification
    # payloads, and a downgrade that destroys data is not a downgrade.
    if has_column(TABLE, MODEL_COLUMN) and not has_column(TABLE, MIGRATION_COLUMN):
        op.alter_column(TABLE, MODEL_COLUMN, new_column_name=MIGRATION_COLUMN)
