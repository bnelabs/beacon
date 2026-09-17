"""Pytest configuration for backend tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _ensure_repo_root_on_path() -> None:
    """Guarantee the repository root is available on ``sys.path``."""

    repo_root = Path(__file__).resolve().parents[2]
    repo_root_str = str(repo_root)
    if repo_root_str not in sys.path:
        sys.path.insert(0, repo_root_str)


def _pin_sqlite_before_first_database_import() -> None:
    """Bind the suite-wide database deterministically, before any test module.

    ``backend.database`` builds a process-global engine at first import, from
    the environment *as it stands at that instant*, and under
    ``USE_SQLITE=true`` it ignores ``DATABASE_URL`` entirely and binds
    ``sqlite:///./beacon.db``. Every module that imports afterwards gets the
    cached binding, so *which module happens to be collected first* silently
    chooses the database the whole suite shares.

    That is not hypothetical. ``test_api_smoke.py`` used to be the first
    importer and set ``USE_SQLITE=true`` at its module level, so the global
    engine bound ``./beacon.db`` and later tests -- including
    ``test_pipeline_integration``'s ``reload(database)`` -- landed on the same
    file whose schema earlier lifespans had created. When
    ``test_alert_evaluator.py`` arrived (collected before ``test_api_smoke``,
    setting ``DATABASE_URL`` but *not* ``USE_SQLITE``), the global engine
    bound that module's private file instead; the pipeline test's reload then
    landed on an empty ``./beacon.db`` (its reloaded ``Base`` has no tables
    registered, because every model module is already imported and bound to
    the original ``Base``, so its ``init_db()`` creates nothing) and failed
    with "no such table: data_sources" -- with ``test_provenance_disclosure``
    falling over the reloaded module state behind it. Main stayed red for two
    days looking like a schema bug while actually being an import-order bug.

    conftest is imported by pytest before every test module in this
    directory, which makes it the only place this can be pinned.
    """
    os.environ["USE_SQLITE"] = "true"


def _start_every_session_on_a_cold_database() -> None:
    """Delete the shared on-disk SQLite file before anything can connect.

    ``USE_SQLITE=true`` binds every test module in the suite to the same
    ``sqlite:///./beacon.db`` (cwd-relative), and several modules write rows
    their fixtures never delete -- alert rules, scheduled sources, vintage-log
    entries. That is invisible in CI (every run checks out a clean tree) and
    loud locally: the second ``pytest`` against the same working directory
    failed 17 tests across ``test_alert_evaluator``, ``test_sync_scheduler``,
    ``test_data_source_update`` and ``test_vintage_log`` purely because the
    first run's rows were still there. A suite that only passes against a
    freshly deleted database cannot be re-run, and "run it again" is the
    first thing anyone does after a failure.

    conftest is imported before every test module, and the engine binds
    lazily through NullPool (a new connection per checkout, no long-lived
    file handle), so removing the file here is the last moment it is both
    safe and guaranteed to precede the first connection. Modules keep their
    own within-run cleanup; this is the between-run half.

    NOT COMPATIBLE WITH pytest-xdist AS-IS: every worker process imports
    this conftest, so a worker starting late would unlink the database while
    earlier workers are mid-run -- open handles would survive the unlink but
    every later connection would see a fresh, empty file. Before enabling
    ``-n``, give each worker its own database (per-worker SQLite path, or
    ``sqlite:///:memory:`` with StaticPool) and gate this deletion to the
    controller. The same applies to anyone pointing a local app at
    ``USE_SQLITE=true``: running the test suite deletes that ``./beacon.db``.
    """
    from pathlib import Path

    for suffix in ("", "-wal", "-shm"):
        Path(f"beacon.db{suffix}").unlink(missing_ok=True)


_ensure_repo_root_on_path()
_pin_sqlite_before_first_database_import()
_start_every_session_on_a_cold_database()

