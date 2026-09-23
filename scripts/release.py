#!/usr/bin/env python3
"""Cut a BEACON release: bump VERSION, date the changelog, sync the frontend.

Usage:
    python scripts/release.py patch|minor|major [--tag] [--dry-run]

Moves the ``[Unreleased]`` block of CHANGELOG.md under a dated ``[X.Y.Z]``
heading, writes the new version to VERSION, keeps frontend/package.json and
docs/api-endpoints.md (which embed the version) equal to it, and commits
atomically. ``--tag`` creates the annotated git tag locally (pushing tags is
a maintainer act).

See docs/VERSIONING.md for the policy this script enforces.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[1]
VERSION_FILE = ROOT / "VERSION"
CHANGELOG = ROOT / "CHANGELOG.md"
PACKAGE_JSON = ROOT / "frontend" / "package.json"
PACKAGE_LOCK = ROOT / "frontend" / "package-lock.json"

SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")


def fail(message: str) -> NoReturn:
    print(f"release: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_version() -> tuple[int, int, int]:
    raw = VERSION_FILE.read_text(encoding="utf-8").strip()
    match = SEMVER.match(raw)
    if not match:
        fail(f"VERSION file is not strict semver: {raw!r}")
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def bump(current: tuple[int, int, int], part: str) -> tuple[int, int, int]:
    major, minor, patch = current
    if part == "major":
        return major + 1, 0, 0
    if part == "minor":
        return major, minor + 1, 0
    return major, minor, patch + 1


def move_changelog_block(text: str, new_version: str) -> str:
    if "[Unreleased]" not in text:
        fail("CHANGELOG.md has no [Unreleased] block to release")
    today = _dt.date.today().isoformat()
    dated = f"## [{new_version}] - {today}"
    return text.replace("## [Unreleased]", f"## [Unreleased]\n\n{dated}", 1)


def sync_lockfile(lock_path: Path, new_version: str) -> bool:
    """Keep frontend/package-lock.json's version fields equal to the release.

    The lockfile carries the package version twice (top level and under
    ``packages[""]``). Skipping it left the lock at 3.0.0 while package.json
    moved to 3.1.1 -- every ``npm install`` then rewrote the lock as an
    uncommitted diff. Returns whether anything was written.
    """
    if not lock_path.exists():
        return False
    lock = json.loads(lock_path.read_text(encoding="utf-8"))
    changed = False
    if lock.get("version") != new_version:
        lock["version"] = new_version
        changed = True
    root_package = lock.get("packages", {}).get("")
    if isinstance(root_package, dict) and root_package.get("version") != new_version:
        root_package["version"] = new_version
        changed = True
    if changed:
        lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return changed


def check_changelog_history(root: Path) -> None:
    """L-41 gate: refuse the cut if the changelog has drifted from the history.

    Since the last release tag, every merge that touched backend/, frontend/
    or scripts/ must carry its PR number in the [Unreleased] block. The
    backfill that fixed L-41's five silent merges is not a process; this is.
    """
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_changelog_history.py"), "--root", str(root)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        fail(result.stderr.strip())
    print(result.stdout.strip())


def regen_api_docs() -> None:
    """Regenerate docs/api-endpoints.md so the release commit carries the new version.

    The docs embed the app version, which ``backend`` reads from the root
    ``VERSION`` file at import time. A release that bumps ``VERSION`` without
    regenerating the docs leaves them stale -- the api-docs check (Tier 2 and
    CI) then fails. The generator is import-only (no DB), so it runs
    self-contained under ``USE_SQLITE``. Runs after ``VERSION`` is written, so
    the regenerated doc already shows the new version.
    """
    env = {**os.environ, "PYTHONPATH": str(ROOT), "USE_SQLITE": "true"}
    subprocess.run(
        [sys.executable, "scripts/generate_api_docs.py"],
        cwd=ROOT,
        env=env,
        check=True,
    )


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("part", choices=["patch", "minor", "major"])
    parser.add_argument("--tag", action="store_true", help="create annotated git tag")
    parser.add_argument("--dry-run", action="store_true", help="print, do not write")
    args = parser.parse_args()

    if subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                      capture_output=True, text=True).stdout.strip() and not args.dry_run:
        fail("working tree is not clean; commit or stash first")

    check_changelog_history(ROOT)

    new = bump(read_version(), args.part)
    new_version = f"{new[0]}.{new[1]}.{new[2]}"

    changelog = move_changelog_block(CHANGELOG.read_text(encoding="utf-8"), new_version)
    package = json.loads(PACKAGE_JSON.read_text(encoding="utf-8"))
    package["version"] = new_version

    if args.dry_run:
        print(f"would release {new_version}")
        print(changelog[:400])
        return

    VERSION_FILE.write_text(new_version + "\n", encoding="utf-8")
    CHANGELOG.write_text(changelog, encoding="utf-8")
    PACKAGE_JSON.write_text(json.dumps(package, indent=2) + "\n", encoding="utf-8")
    sync_lockfile(PACKAGE_LOCK, new_version)
    regen_api_docs()

    run(["git", "add", "VERSION", "CHANGELOG.md", "frontend/package.json", "docs/api-endpoints.md"])
    if PACKAGE_LOCK.exists():
        run(["git", "add", "frontend/package-lock.json"])
    run(["git", "commit", "-m", f"release: v{new_version}"])
    if args.tag:
        run(["git", "tag", "-a", f"v{new_version}",
             "-m", f"BEACON v{new_version}"])
    print(f"released v{new_version}" + (" (tagged)" if args.tag else ""))


if __name__ == "__main__":
    main()
