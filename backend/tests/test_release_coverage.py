"""L-48 coverage: every release tag on the remote must have a GitHub Release.

The remote pieces are live in CI (the required "check" job runs the script
against origin); the parsing and both dispositions are pinned here with
offline file inputs.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

RAW_TAGS = (
    "abc123\trefs/tags/v6.0.3\n"
    "def456\trefs/tags/v6.0.3^{}\n"
    "111111\trefs/tags/v6.0.4\n"
    "222222\trefs/tags/prereg-early-warning-v5\n"
    "333333\trefs/tags/v6.1.0-rc.1\n"
    "444444\trefs/tags/not-a-version\n"
)


def _check(tmp_path: Path, tags: str, releases: str) -> subprocess.CompletedProcess:
    tags_file = tmp_path / "tags.txt"
    releases_file = tmp_path / "releases.txt"
    tags_file.write_text(tags, encoding="utf-8")
    releases_file.write_text(releases, encoding="utf-8")
    return subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "check_release_coverage.py"),
            "--tags-file", str(tags_file),
            "--releases-file", str(releases_file),
        ],
        capture_output=True,
        text=True,
    )


def test_filter_excludes_non_release_tags_and_pendants(tmp_path):
    result = _check(tmp_path, RAW_TAGS, "v6.0.3\nv6.0.4\nv6.1.0-rc.1\n")
    assert result.returncode == 0, result.stderr
    assert "3 release tags" in result.stdout


def test_a_tag_without_a_release_refuses(tmp_path):
    result = _check(tmp_path, RAW_TAGS, "v6.0.3\nv6.1.0-rc.1\n")
    assert result.returncode == 1
    assert "v6.0.4" in result.stderr
    assert "prereg" not in result.stderr


def test_an_empty_release_list_names_every_tag(tmp_path):
    result = _check(tmp_path, RAW_TAGS, "")
    assert result.returncode == 1
    assert "v6.0.3" in result.stderr
    assert "v6.0.4" in result.stderr
    assert "v6.1.0-rc.1" in result.stderr
