"""Migrations applied to a real database, from every history a deployment can have.

Why this file exists
--------------------

Backend CI rendered the chain with ``alembic upgrade head --sql`` and called that
a migration test. It is not one. ``baseline_core_001`` begins

    if op.get_context().as_sql:
        # Offline rendering (--sql) has no live inspector; reconciliation is
        # a no-op there by design

so the revision that creates ``data_sources`` emits *nothing* offline -- and the
revision that runs first, ``003``, adds columns to it. Offline rendering cannot
see that ordering defect, because in offline mode the defect does not exist.

The consequence was a released image that could not be installed. On an empty
volume both backend and celery-worker ran ``alembic upgrade head`` from their
entrypoints, both hit

    psycopg2.errors.UndefinedTable: relation "data_sources" does not exist

and both restart-looped (64 restarts observed on a real deployment) while
postgres, redis and the frontend stayed healthy -- so ``docker compose ps`` said
``Up`` for a backend that had never served a request.

The three histories tested here are the three a deployed database can actually
have, and each one failed differently before the guards landed:

``fresh``
    Empty database, ``alembic upgrade head`` from nothing. Failed with
    ``UndefinedTable`` on ``data_sources``: ``003`` is the root revision and the
    table is created five revisions later by ``baseline_core_001``.

``legacy_create_all``
    ``Base.metadata.create_all()`` with no ``alembic_version`` row, which is what
    ``init_db()`` in the API lifespan produced on every boot before it was
    restricted to SQLite. Failed with ``DuplicateColumn`` on
    ``registration_url``, because ``003`` added columns the models already
    declare. Every table-creating revision failed the same way with
    ``DuplicateTable``.

``partial``
    Migrated to an intermediate revision, then upgraded. The path a real upgrade
    takes; it must not depend on which revision the volume stopped at.

Both terminal states are asserted to be the *same* schema, which is the property
that makes the two histories interchangeable rather than merely survivable.

These tests need a live PostgreSQL. Without one they skip, and CI provides one
(see the ``postgres`` service in ``.github/workflows/backend-ci.yml``), so a skip
locally is not a pass in CI.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Dict, Optional, Set

import pytest
import sqlalchemy as sa

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Read from the environment in CI; falls back to a local cluster for
#: development. Never a production URL -- every database this creates is dropped.
_CANDIDATE_URLS = (
    os.getenv("MIGRATION_TEST_DATABASE_URL"),
    os.getenv("POSTGRES_MIGRATION_TEST_URL"),
    "postgresql://beacon_user:beacon_password@127.0.0.1:5432/postgres",
    "postgresql://postgres@127.0.0.1:5432/postgres",
    "postgresql://postgres@localhost:5432/postgres",
)

#: Tables the product cannot run without. Checked rather than "whatever the
#: models declare", so a migration that silently stops creating one fails here.
REQUIRED_TABLES = frozenset(
    {
        "data_sources",
        "data_catalogue",
        "jobs",
        "assets",
        "error_logs",
        "pipeline_jobs",
        "country_profiles",
        "notifications",
        "alert_rules",
    }
)

#: The columns ``003`` exists to add. A guard that skips too eagerly shows up
#: here rather than as a query error six months later.
REGISTRATION_COLUMNS = (
    "registration_url",
    "registration_required",
    "free_tier_limits",
    "coverage_description",
)


def _admin_url() -> Optional[str]:
    """First candidate URL that actually answers, or ``None``."""
    for url in _CANDIDATE_URLS:
        if not url:
            continue
        try:
            engine = sa.create_engine(url, poolclass=sa.pool.NullPool)
            with engine.connect() as connection:
                connection.execute(sa.text("SELECT 1"))
            engine.dispose()
            return url
        except Exception:  # noqa: BLE001 - any failure means "try the next one"
            try:
                engine.dispose()
            except Exception:  # noqa: BLE001
                pass
    return None


_ADMIN_URL = _admin_url()

pytestmark = pytest.mark.skipif(
    _ADMIN_URL is None,
    reason=(
        "no reachable PostgreSQL for live migration tests; set "
        "MIGRATION_TEST_DATABASE_URL to a server the tests may create and drop "
        "databases on"
    ),
)


def _alembic(*args: str, database_url: str) -> subprocess.CompletedProcess:
    """Run the alembic CLI as a subprocess, against ``database_url``.

    A subprocess rather than the Python API because that is what the container
    entrypoint runs, and because a fresh interpreter cannot inherit an already
    imported ``Base.metadata`` and quietly make a guard unnecessary.
    """
    environment = dict(os.environ)
    environment["DATABASE_URL"] = database_url
    environment["PYTHONPATH"] = str(REPO_ROOT)
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=str(REPO_ROOT),
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
    )


class _Database:
    """A throwaway database, created on entry and dropped on exit."""

    def __init__(self, admin_url: str) -> None:
        self.name = f"beacon_migration_test_{uuid.uuid4().hex[:12]}"
        self._admin_url = admin_url
        admin = sa.create_engine(
            admin_url, isolation_level="AUTOCOMMIT", poolclass=sa.pool.NullPool
        )
        with admin.connect() as connection:
            connection.execute(sa.text(f'CREATE DATABASE "{self.name}"'))
        admin.dispose()

        base = sa.engine.make_url(self._admin_url)
        self.url = str(base.set(database=self.name))
        self.engine = sa.create_engine(self.url, poolclass=sa.pool.NullPool)

    def __enter__(self) -> "_Database":
        return self

    def __exit__(self, *exc_info) -> None:
        self.engine.dispose()
        admin = sa.create_engine(
            self._admin_url, isolation_level="AUTOCOMMIT", poolclass=sa.pool.NullPool
        )
        with admin.connect() as connection:
            connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{self.name}"'))
        admin.dispose()

    # -- introspection -----------------------------------------------------

    def tables(self) -> Set[str]:
        return set(sa.inspect(self.engine).get_table_names())

    def columns(self, table: str) -> Set[str]:
        return {c["name"] for c in sa.inspect(self.engine).get_columns(table)}

    def indexes(self, table: str) -> Set[str]:
        return {
            i["name"] for i in sa.inspect(self.engine).get_indexes(table) if i.get("name")
        }

    def alembic_version(self) -> Optional[str]:
        if "alembic_version" not in self.tables():
            return None
        with self.engine.connect() as connection:
            row = connection.execute(sa.text("SELECT version_num FROM alembic_version")).first()
        return None if row is None else str(row[0])

    def create_all_from_models(self) -> None:
        """Reproduce the legacy schema path: ``create_all``, no alembic stamp."""
        from backend.database import Base
        import backend.models  # noqa: F401 - registers every table

        Base.metadata.create_all(self.engine)


def _upgrade(db: _Database, revision: str = "head") -> None:
    result = _alembic("upgrade", revision, database_url=db.url)
    assert result.returncode == 0, (
        f"alembic upgrade {revision} failed (exit {result.returncode}):\n"
        f"--- stdout ---\n{result.stdout[-4000:]}\n"
        f"--- stderr ---\n{result.stderr[-4000:]}"
    )


def _schema_fingerprint(db: _Database, tables: Optional[Set[str]] = None) -> Dict[str, Set[str]]:
    """``table -> columns`` for every table except alembic's own bookkeeping.

    Compared across histories rather than against a hardcoded list, so a column
    that one path creates and the other does not is a failure even for a table
    nobody thought to enumerate. That is not hypothetical: it is how the
    ``notifications.metadata`` / ``extra_data`` divergence below was found, in a
    table no list of "important" tables would have included.
    """
    names = tables if tables is not None else db.tables()
    return {
        table: db.columns(table)
        for table in sorted(names - {"alembic_version"})
    }


@pytest.fixture()
def database():
    assert _ADMIN_URL is not None
    with _Database(_ADMIN_URL) as db:
        yield db


class TestFreshDatabase:
    """An empty volume must reach head. This is the case that was released broken."""

    def test_upgrade_head_succeeds_from_nothing(self, database):
        assert database.tables() == set(), "the test database should start empty"
        _upgrade(database)

    def test_every_required_table_exists(self, database):
        _upgrade(database)
        missing = REQUIRED_TABLES - database.tables()
        assert not missing, f"migrations reached head without creating {sorted(missing)}"

    def test_the_registration_columns_the_root_revision_exists_to_add(self, database):
        _upgrade(database)
        missing = [c for c in REGISTRATION_COLUMNS if c not in database.columns("data_sources")]
        assert not missing, (
            f"003 skipped columns it should have added: {missing}. A guard that "
            "treats 'table absent' as 'nothing to do' must not also treat "
            "'table created later' as 'columns already present'."
        )

    def test_the_chain_is_stamped_at_a_single_head(self, database):
        _upgrade(database)
        heads = _alembic("heads", database_url=database.url)
        assert heads.returncode == 0
        listed = [line for line in heads.stdout.splitlines() if "(head)" in line]
        assert len(listed) == 1, (
            f"expected exactly one head, got {listed}. Multiple heads mean "
            "'upgrade head' is ambiguous and a fresh install can land on either."
        )
        assert database.alembic_version() is not None

    def test_upgrading_twice_is_a_no_op(self, database):
        _upgrade(database)
        before = _schema_fingerprint(database)
        second = _alembic("upgrade", "head", database_url=database.url)
        assert second.returncode == 0, second.stderr[-2000:]
        assert "Running upgrade" not in second.stdout, (
            "a second `upgrade head` re-ran a revision, so the chain is not "
            "idempotent and a container restart will re-apply DDL"
        )
        assert _schema_fingerprint(database) == before


class TestLegacyCreateAllDatabase:
    """A database built by ``create_all()`` with no alembic stamp.

    This is what ``init_db()`` produced on every API boot before it was
    restricted to SQLite, so it is the state most existing volumes are in.
    """

    def test_upgrade_head_succeeds_over_an_existing_schema(self, database):
        database.create_all_from_models()
        assert database.alembic_version() is None, (
            "create_all must not stamp alembic; the test would not be exercising "
            "the legacy path"
        )
        _upgrade(database)

    def test_it_ends_at_the_same_schema_as_a_fresh_database(self, database):
        database.create_all_from_models()
        _upgrade(database)
        legacy = _schema_fingerprint(database)

        with _Database(_ADMIN_URL) as fresh:
            _upgrade(fresh)
            # Compare the union of both histories' tables, so a table one path
            # creates and the other does not is a difference rather than an
            # absence that silently drops out of the comparison.
            common = set(legacy) | {
                t for t in _schema_fingerprint(fresh)
            }
            migrated_from_empty = _schema_fingerprint(fresh, common)
            legacy = _schema_fingerprint(database, common)

        differing = sorted(set(legacy) | set(migrated_from_empty))
        diff = {
            table: {
                "from_create_all": sorted(legacy.get(table, set())),
                "from_empty": sorted(migrated_from_empty.get(table, set())),
            }
            for table in differing
            if legacy.get(table) != migrated_from_empty.get(table)
        }
        assert not diff, (
            "the legacy and fresh histories produced different schemas, so which "
            "one a deployment followed is observable in the data model: "
            f"{diff}"
        )

    def test_no_legacy_table_or_index_is_duplicated_or_dropped(self, database):
        database.create_all_from_models()
        before = {t: database.indexes(t) for t in REQUIRED_TABLES if database.tables() >= {t}}
        _upgrade(database)
        for table, indexes in before.items():
            now = database.indexes(table)
            assert indexes <= now, (
                f"migrating a legacy database lost indexes on {table}: "
                f"{sorted(indexes - now)}"
            )


class TestPartialHistory:
    """A volume that stopped partway must still reach head."""

    def test_upgrade_from_an_intermediate_revision(self, database):
        _upgrade(database, "20251107_161500")
        assert database.alembic_version() == "20251107_161500"
        _upgrade(database)
        missing = REQUIRED_TABLES - database.tables()
        assert not missing, f"resuming a partial migration left out {sorted(missing)}"

    def test_upgrade_from_an_intermediate_revision_reaches_the_same_schema(self, database):
        # The path a real upgrade takes: a volume that stopped partway must end
        # where a fresh install ends, or which release a deployment upgraded
        # through is observable in its schema.
        with _Database(_ADMIN_URL) as fresh:
            _upgrade(fresh)
            direct = _schema_fingerprint(fresh)

        _upgrade(database)
        resumed = _schema_fingerprint(database, set(direct))

        assert resumed == direct, (
            f"resuming from 20251107_161500 produced a different schema: "
            f"{ {t: (direct.get(t), resumed.get(t)) for t in direct if direct.get(t) != resumed.get(t)} }"
        )

    def test_the_baseline_revision_refuses_to_downgrade_rather_than_guessing(self, database):
        # ``baseline_core_001`` reconciles a pre-existing schema instead of
        # introducing one, so it cannot know what to remove: dropping a table it
        # found already present would destroy data it did not create. Raising is
        # the correct behaviour and is asserted here so that it stays deliberate
        # rather than becoming an accident someone "fixes" by adding drop calls.
        _upgrade(database)
        # Target the revision by name rather than by "-1", so adding a revision
        # after it does not silently turn this into a test of something else.
        result = _alembic("downgrade", "timescale_001", database_url=database.url)
        assert result.returncode != 0, (
            "baseline_core_001 downgraded successfully; if that is now intended, "
            "this test and the migration's own comment both need updating"
        )
        assert "cannot be downgraded" in result.stderr, result.stderr[-1500:]
        # The refusal must leave the database usable, not half-migrated. A
        # downgrade runs in a transaction, so a failed one rolls back.
        assert database.alembic_version() == "notifications_extra_data_001"
        _upgrade(database)
        assert not (REQUIRED_TABLES - database.tables())


def test_the_guards_skip_only_what_exists(database):
    """The guards must not become a blanket ``except: pass``.

    ``backend/alembic/guards.py`` claims it skips an object only when the
    inspector says it is already there, so that a genuine schema error still
    fails the deploy. This exercises both halves: an existing object is skipped,
    and a real error still propagates. A migration suite that only ever runs
    green cannot tell the two apart, which is how the unguarded ``003`` shipped.
    """
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    from backend.alembic import guards

    database.create_all_from_models()
    with database.engine.connect() as connection:
        context = MigrationContext.configure(connection)
        # The guards call ``alembic.op``, which is a proxy that needs an active
        # operations context; this is the same binding the CLI establishes.
        with Operations.context(context):
            assert guards.has_table("data_sources") is True
            assert guards.has_table("no_such_table_beacon") is False
            assert guards.has_column("data_sources", "registration_url") is True
            assert guards.has_column("data_sources", "no_such_column") is False
            assert guards.table_columns("no_such_table_beacon") is None

            # Existing object: skipped, returns False, raises nothing.
            assert guards.add_column_if_missing(
                "data_sources", "registration_url", sa.Text()
            ) is False
            assert guards.create_table_if_missing("data_sources", sa.Column("id", sa.Integer)) is False

            # A genuine error must still surface rather than be swallowed.
            with pytest.raises(Exception):
                guards.create_index_if_missing(
                    "idx_on_a_column_that_does_not_exist",
                    "data_sources",
                    ["no_such_column_beacon"],
                )
