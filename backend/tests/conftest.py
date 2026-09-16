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


_ensure_repo_root_on_path()
_pin_sqlite_before_first_database_import()

