#!/usr/bin/env python3
"""Release gate: the changelog must agree with the merge history (L-41).

Five merges landed after v4.0.0 with no changelog entry, and a release cut
from that block would have omitted them silently (L-41). The backfill fixed
the damage; this check is the durable guard, and it runs inside
``release.py`` before the cut.

The contract, stated once:

* the range is ``<last-release-tag>..HEAD``;
* a merge counts when its subject is ``Merge pull request #N`` and its
  first-parent diff touches ``backend/``, ``frontend/`` or ``scripts/`` --
  anything a consumer or the release pipeline reads;
* the entry is the PR number: ``#N`` anywhere in the ``[Unreleased]`` block.
  An entry can only be written after the PR exists, so a match is always a
  same-cycle entry, never a stale one;
* merges off ``release/`` branches need no entry -- their entries sit in the
  dated block ``release.py`` is about to create, by definition;
* docs-only merges (ledger, docs) need no entry either.

Usage:
    python scripts/check_changelog_history.py [--root PATH]

Exit 0 with an OK line when the history is covered; exit 1 naming every
uncovered merge otherwise.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

MERGE_SUBJECT = re.compile(r"Merge pull request #(\d+) from (\S+)")
RELEASE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")
CONSUMER_PREFIXES = ("backend/", "frontend/", "scripts/")


def _semver_key(tag: str) -> tuple:
    """Order release tags per SemVer: pre-releases sort before their release."""
    match = RELEASE_TAG.match(tag)
    numbers = tuple(int(g) for g in match.groups()[:3])
    prerelease = match.group(4)
    return (numbers, 0 if prerelease else 1, prerelease or "")


def run_git(root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise SystemExit(f"changelog-history: git {' '.join(args)} failed: {result.stderr.strip()}")
    return result


def last_release_tag(root: Path) -> str:
    """The highest-semver release tag reachable from HEAD (L-48).

    Not ``git describe``'s nearest tag: a non-release tag placed on main after
    the last release (the ``prereg-early-warning-v*`` marks are ancestors of
    main today) would otherwise become the base and break the cut. The base
    is the newest *release* tag in reach, ordered per SemVer.
    """
    result = run_git(root, "tag", "--list", "v*")
    candidates = []
    for tag in result.stdout.split():
        if not RELEASE_TAG.match(tag):
            continue
        ancestor = run_git(root, "merge-base", "--is-ancestor", tag, "HEAD", check=False)
        if ancestor.returncode == 0:
            candidates.append(tag)
    if not candidates:
        raise SystemExit("changelog-history: no release tag reachable from HEAD")
    return max(candidates, key=_semver_key)


def unreleased_block(root: Path) -> str:
    text = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    match = re.search(r"^## \[Unreleased\]$(.*?)(?=^## \[)", text, flags=re.M | re.S)
    return match.group(1) if match else ""


def merged_prs(root: Path, base: str) -> list[tuple[int, str, bool]]:
    """``(pr_number, source_branch, touches_consumer_code)`` per counted merge."""
    log = run_git(root, "log", f"{base}..HEAD", "--merges", "--format=%H%x00%s").stdout
    out: list[tuple[int, str, bool]] = []
    for line in log.splitlines():
        if not line.strip():
            continue
        sha, subject = line.split("\x00", 1)
        match = MERGE_SUBJECT.search(subject)
        if not match:
            continue
        names = run_git(root, "diff", "--name-only", f"{sha}^1", sha).stdout
        touches = any(name.startswith(CONSUMER_PREFIXES) for name in names.splitlines() if name)
        out.append((int(match.group(1)), match.group(2), touches))
    return out


def uncovered(root: Path) -> tuple[str, list[int]]:
    """``(base_tag, pr_numbers)`` for merges the [Unreleased] block does not cover."""
    base = last_release_tag(root)
    block = unreleased_block(root)
    missing = [
        pr
        for pr, source, touches in merged_prs(root, base)
        if touches
        and "/release/" not in source
        and not re.search(rf"(?<!\d)#{pr}(?!\d)", block)
    ]
    return base, missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    args = parser.parse_args()
    root = Path(args.root)

    base, missing = uncovered(root)
    if missing:
        for pr in missing:
            print(
                f"changelog-history: merge #{pr} since {base} touches backend/, "
                f"frontend/ or scripts/ but the [Unreleased] block has no entry "
                f"mentioning #{pr}",
                file=sys.stderr,
            )
        return 1
    print(f"changelog-history: OK ({base}..HEAD covered by the [Unreleased] block)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
