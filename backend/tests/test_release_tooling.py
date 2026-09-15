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
