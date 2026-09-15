"""Existence guards for migrations that have to run against databases they did not create.

Why this module exists
----------------------

BEACON has three historical schema paths, and a deployed database may have been
built by any of them:

1. ``alembic upgrade head`` from empty, in revision order;
2. ``Base.metadata.create_all()`` from ``backend.database.init_db``, which the
   API lifespan called unconditionally and which builds the *current* model
   metadata with no ``alembic_version`` row at all;
3. a mixture -- ``create_all`` on an older release, then migrations applied once
   the chain caught up, then ``create_all`` again on the next boot.

Under (2) and (3) every table and column already exists before the first
migration runs, so an unguarded ``op.create_table`` or ``op.add_column`` raises
``DuplicateTable`` / ``DuplicateColumn`` and the container restart-loops. Under
(1) the opposite failure existed: revision ``003`` added columns to
``data_sources`` while the table is not created until ``baseline_core_001``, five
revisions later, so a *fresh* database could not migrate at all --

    sqlalchemy.exc.ProgrammingError: (psycopg2.errors.UndefinedTable)
    relation "data_sources" does not exist
    [SQL: ALTER TABLE data_sources ADD COLUMN registration_url VARCHAR(500)]

-- which is what made the released image undeployable on a clean volume.

The rule this module enforces
-----------------------------

**Skip an object only when it demonstrably already exists.** Every guard here
inspects the live database and returns a boolean; none of them catches an
exception. A migration that wraps its DDL in ``try: ... except: pass`` hides
genuine schema errors -- a wrong column type, a missing foreign key target, a
permissions problem -- behind a green run, and the failure then surfaces later in
a query nobody connects to the migration. Real errors must still fail visibly and
stop the deploy.

Guards are deliberately narrow: ``has_table``, ``has_column``, ``has_index`` and
the ``*_if_missing`` wrappers around the corresponding ``op`` calls. Anything
richer belongs in the migration that needs it, where a reader can see it.

Offline (``--sql``) rendering
-----------------------------

``alembic upgrade head --sql`` has no connection to inspect, so there is nothing
a guard can look up. Rather than fail, the guards degrade to the behaviour the
unguarded migrations had: every existence probe answers "not present", so
create/add operations render their DDL and drop operations render nothing. That
keeps offline rendering usable as a review artefact -- which is all it is; CI
renders offline and applies for real in
``backend/tests/test_migrations_live.py``, because ``baseline_core_001`` renders
as a no-op and an offline render therefore cannot see a migration-ordering
defect at all.

Importing this module
---------------------

``backend/alembic/env.py`` puts the repository root on ``sys.path`` before the
migrations run, so a revision can ``from backend.alembic.guards import ...``
regardless of the caller's working directory. Nothing here imports the
application's models: a guard that needed ``Base.metadata`` would tie historical
migrations to the current schema, which is exactly the coupling that makes
``baseline_core_001`` a special case rather than a normal revision.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional, Sequence, Set

import sqlalchemy as sa
from alembic import op

__all__ = [
    "is_offline",
    "skip_because_absent",
    "has_table",
    "has_column",
    "table_columns",
    "has_index",
    "create_table_if_missing",
    "create_index_if_missing",
    "add_column_if_missing",
    "drop_table_if_exists",
    "drop_index_if_exists",
    "drop_column_if_exists",
    "missing_columns",
]


def is_offline() -> bool:
    """Whether alembic is rendering SQL rather than applying it.

    ``op.get_context().as_sql`` is what ``baseline_core_001`` already tests for
    the same reason: offline mode has no live inspector.
    """
    try:
        return bool(op.get_context().as_sql)
    except Exception:  # noqa: BLE001 - no context means nothing to inspect
        return True


def skip_because_absent() -> bool:
    """Whether a create/add guard should skip for want of a table to act on.

    Online, a guard skips when the enclosing table does not exist yet: a later
    revision creates it, from model metadata that already carries the object.
    Offline there is no way to know, so the DDL is rendered -- matching what the
    unguarded migrations emitted, which is what an offline render is reviewed
    against.
    """
    return not is_offline()


def _inspector() -> sa.Inspector:
    """Inspector bound to the migration's live connection."""
    return sa.inspect(op.get_bind())


def has_table(name: str) -> bool:
    """Whether ``name`` exists in the database being migrated.

    Always ``False`` offline, so create guards emit their DDL.
    """
    if is_offline():
        return False
    return bool(_inspector().has_table(name))


def table_columns(name: str) -> Optional[Set[str]]:
    """Column names of ``name``, or ``None`` when the table does not exist.

    ``None`` rather than an empty set so a caller can distinguish "no such
    table" from "table with no columns", which matter in opposite directions:
    the first means a later revision creates it, the second means something is
    badly wrong.
    """
    if is_offline():
        return None
    inspector = _inspector()
    if not inspector.has_table(name):
        return None
    return {column["name"] for column in inspector.get_columns(name)}


def has_column(table: str, column: str) -> bool:
    """Whether ``table.column`` exists. ``False`` when the table itself does not."""
    columns = table_columns(table)
    return columns is not None and column in columns


def has_index(table: str, index_name: str) -> bool:
    """Whether an index called ``index_name`` exists on ``table``.

    ``False`` when the table does not exist, so callers do not need to guard the
    table separately before guarding its indexes.
    """
    if is_offline():
        return False
    inspector = _inspector()
    if not inspector.has_table(table):
        return False
    return any(
        index.get("name") == index_name
        for index in inspector.get_indexes(table)
    )


def create_table_if_missing(name: str, *args: Any, **kwargs: Any) -> bool:
    """``op.create_table`` unless the table already exists.

    Returns whether the table was created, so a migration that must also create
    the table's indexes can tell "I own this table now" from "it was already
    here" -- indexes are guarded individually, because a legacy ``create_all``
    may have made the table with a different index set.
    """
    if has_table(name):
        return False
    op.create_table(name, *args, **kwargs)
    return True


def create_index_if_missing(
    name: str, table: str, columns: Sequence[str], **kwargs: Any
) -> bool:
    """``op.create_index`` unless the index already exists.

    Skips silently when the *table* is missing too: an index on a table this
    chain has not created yet belongs to whichever revision creates it.
    """
    if not has_table(table) or has_index(table, name):
        return False
    op.create_index(name, table, list(columns), **kwargs)
    return True


def add_column_if_missing(
    table: str, name: str, column_type: Any, **kwargs: Any
) -> bool:
    """``op.add_column`` unless the column already exists.

    Skips when the table is missing. That is the fresh-database case: a later
    revision creates the table from current model metadata, which already
    includes this column, so adding it here would be redundant at best and an
    error at worst.

    ``nullable=True`` is forced unless the caller states otherwise. A column
    added to a table that already holds rows cannot be ``NOT NULL`` without a
    default, and every column these guards protect is optional metadata.
    """
    columns = table_columns(table)
    if columns is not None and name in columns:
        return False
    if columns is None and skip_because_absent():
        # No such table: a later revision creates it from model metadata that
        # already declares this column.
        return False
    kwargs.setdefault("nullable", True)
    op.add_column(table, sa.Column(name, column_type, **kwargs))
    return True


def drop_table_if_exists(name: str) -> bool:
    """``op.drop_table`` only when the table is there. Downgrades stay runnable."""
    if not has_table(name):
        return False
    op.drop_table(name)
    return True


def drop_index_if_exists(name: str, table: str) -> bool:
    """``op.drop_index`` only when both the table and the index are there."""
    if not has_index(table, name):
        return False
    op.drop_index(name, table_name=table)
    return True


def drop_column_if_exists(table: str, name: str) -> bool:
    """``op.drop_column`` only when the column is there."""
    if not has_column(table, name):
        return False
    op.drop_column(table, name)
    return True


def missing_columns(table: str, names: Iterable[str]) -> Sequence[str]:
    """Which of ``names`` the table lacks. Empty when the table does not exist."""
    columns = table_columns(table)
    if columns is None:
        return ()
    return [name for name in names if name not in columns]
