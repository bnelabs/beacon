"""The release tooling introduced in round four must actually work (I4).

VERSION/package.json/CHANGELOG drift is exactly the class of defect this
repository keeps hunting, so the guards get a test: check_versioning passes
on a healthy tree, and release.py's dry run computes the next version from
VERSION without touching anything.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_check_versioning_passes_on_a_healthy_tree():
    result = subprocess.run(
        [sys.executable, "scripts/check_versioning.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_release_dry_run_computes_the_next_version_without_writing():
    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    major, minor, patch = (int(part) for part in version.split("."))
    expected = f"{major}.{minor + 1}.0"

    before = {
        p: p.read_text(encoding="utf-8")
        for p in (ROOT / "VERSION", ROOT / "CHANGELOG.md", ROOT / "frontend" / "package.json")
    }
    result = subprocess.run(
        [sys.executable, "scripts/release.py", "minor", "--dry-run"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert expected in result.stdout

    after = {
        p: p.read_text(encoding="utf-8")
        for p in (ROOT / "VERSION", ROOT / "CHANGELOG.md", ROOT / "frontend" / "package.json")
    }
    assert before == after, "dry run must not write"


def test_changelog_has_an_unreleased_block():
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    assert re.search(r"^## \[Unreleased\]", changelog, re.M)


def test_release_syncs_the_lockfile(tmp_path):
    """The lock carries the version twice; release.py must keep both equal.

    Regression: the lock sat at 3.0.0 while package.json moved to 3.1.1, so
    every npm install rewrote it as an uncommitted diff.
    """
    import importlib.util
    import json

    spec = importlib.util.spec_from_file_location(
        "release_script", ROOT / "scripts" / "release.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    lock = tmp_path / "package-lock.json"
    lock.write_text(
        json.dumps(
            {
                "name": "beacon-frontend",
                "version": "0.0.1",
                "lockfileVersion": 3,
                "packages": {"": {"name": "beacon-frontend", "version": "0.0.1"}},
            }
        ),
        encoding="utf-8",
    )
    assert module.sync_lockfile(lock, "9.9.9") is True
    data = json.loads(lock.read_text(encoding="utf-8"))
    assert data["version"] == "9.9.9"
    assert data["packages"][""]["version"] == "9.9.9"
    assert module.sync_lockfile(lock, "9.9.9") is False, "sync must be idempotent"
    assert module.sync_lockfile(tmp_path / "missing.json", "1.0.0") is False


def test_lock_and_package_json_agree_with_version():
    """The live tree guard: the drift release.py once produced is visible now."""
    import json

    version = (ROOT / "VERSION").read_text(encoding="utf-8").strip()
    lock_path = ROOT / "frontend" / "package-lock.json"
    if not lock_path.exists():
        return
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    assert lock.get("version") == version
    assert lock.get("packages", {}).get("", {}).get("version") == version
