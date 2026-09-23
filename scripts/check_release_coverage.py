#!/usr/bin/env python3
"""CI guard: every release tag on the remote must have a GitHub Release (L-48).

In the Semver release design the tag is the machine anchor and the GitHub
Release is the public artifact. A tag pushed without its release leaves the
Releases page lying about what exists -- the pre-L-48 state shipped 13 tags
with zero releases. This guard runs in the required "check" job and fails,
naming every release tag on the remote without a matching GitHub Release.

The parsing pieces are offline-testable via --tags-file / --releases-file;
in CI the script reads the remote directly.

Usage:
    python scripts/check_release_coverage.py
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

RELEASE_TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)(?:-[0-9A-Za-z.-]+)?$")


def filter_release_tags(names: list[str]) -> list[str]:
    """Release tags out of a raw name list: vX.Y.Z (or -prerelease), no ^{} pendants."""
    out = []
    for name in names:
        name = name.strip()
        if not name or name.endswith("^{}"):
            continue
        if RELEASE_TAG.match(name):
            out.append(name)
    return sorted(out)


def _tag_name(line: str) -> str:
    """The tag name out of a ``git ls-remote --tags`` line (sha<TAB>refs/tags/<name>)."""
    name = line.rsplit("\t", 1)[-1].strip()
    if name.startswith("refs/tags/"):
        name = name[len("refs/tags/"):]
    return name


def remote_release_tags() -> list[str]:
    result = subprocess.run(
        ["git", "ls-remote", "--tags", "origin"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"release-coverage: git ls-remote failed: {result.stderr.strip()}")
    lines = [_tag_name(line) for line in result.stdout.splitlines() if line.strip()]
    return filter_release_tags(lines)


def _repo_slug() -> str:
    """``owner/repo`` from the origin remote URL — no API round-trip, no
    ``gh`` placeholder substitution (which the CI ``gh`` version lacks)."""
    result = subprocess.run(
        ["git", "remote", "get-url", "origin"], capture_output=True, text=True
    )
    if result.returncode != 0:
        raise SystemExit(f"release-coverage: no origin remote ({result.stderr.strip()})")
    match = re.search(r"github\.com[:/]([\w.-]+)/([\w.-]+?)(?:\.git)?/?$", result.stdout.strip())
    if not match:
        raise SystemExit(f"release-coverage: cannot resolve owner/repo from origin URL")
    return f"{match.group(1)}/{match.group(2)}"


def remote_releases() -> list[str]:
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{_repo_slug()}/releases?per_page=100",
             "--paginate", "--jq", ".[].tag_name"],
            capture_output=True, text=True,
        )
    except FileNotFoundError:
        raise SystemExit("release-coverage: the gh CLI is not available")
    if result.returncode != 0:
        raise SystemExit(f"release-coverage: gh api failed: {result.stderr.strip()}")
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def missing_releases(tags: list[str], releases: list[str]) -> list[str]:
    release_set = set(releases)
    return [tag for tag in tags if tag not in release_set]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tags-file", default=None,
                        help="offline test: file of raw tag lines (git ls-remote format)")
    parser.add_argument("--releases-file", default=None,
                        help="offline test: file of release tag names")
    args = parser.parse_args()

    if args.tags_file is not None or args.releases_file is not None:
        if args.tags_file is None or args.releases_file is None:
            parser.error("--tags-file and --releases-file must be given together")
        raw = Path(args.tags_file).read_text(encoding="utf-8").splitlines()
        tags = filter_release_tags([_tag_name(line) for line in raw])
        releases = [line.strip() for line in
                    Path(args.releases_file).read_text(encoding="utf-8").splitlines()
                    if line.strip()]
    else:
        tags = remote_release_tags()
        releases = remote_releases()

    missing = missing_releases(tags, releases)
    if missing:
        for tag in missing:
            print(f"release-coverage: {tag} has no GitHub Release", file=sys.stderr)
        return 1
    print(f"release-coverage: OK ({len(tags)} release tags, all have GitHub Releases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
