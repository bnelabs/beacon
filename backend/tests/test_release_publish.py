"""L-48 publish: the tag is the machine anchor, the GitHub Release is the public artifact.

``release.py publish`` publishes an already-pushed tag as a GitHub Release
whose notes are the versioned CHANGELOG.md block verbatim, maps pre-release
versions to ``--prerelease`` and refreshes an existing release instead of
recreating it. These tests never touch the live repository: a synthetic repo
with a local bare ``origin`` remote, and a fake ``gh`` on PATH that records
every invocation and the notes file it received.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

CHANGELOG = """# Changelog

## [Unreleased]

## [2.1.0-rc.1] - 2026-09-23

### Added
- the twenty-one pre-release feature (PR #101).

## [2.0.0] - 2026-09-23

### Added
- the twenty point zero feature (PR #99).

## [1.0.0] - 2026-01-01

### Added
- baseline (PR #1).
"""


def _git(cwd: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True
    )
    return result.stdout


def _load_release():
    spec = importlib.util.spec_from_file_location(
        "release_script", ROOT / "scripts" / "release.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A synthetic repo with a local bare origin and pushed release tags."""
    root = tmp_path / "work"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "Pub Test")
    _git(root, "config", "user.email", "pub@test.local")
    (root / "CHANGELOG.md").write_text(CHANGELOG, encoding="utf-8")
    (root / "VERSION").write_text("2.0.0\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "baseline")
    _git(root, "tag", "-a", "v2.0.0", "-m", "v2.0.0")
    _git(root, "tag", "-a", "v2.1.0-rc.1", "-m", "v2.1.0-rc.1")

    origin = tmp_path / "origin.git"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)
    _git(root, "remote", "add", "origin", str(origin))
    _git(root, "push", "-q", "origin", "v2.0.0")
    _git(root, "push", "-q", "origin", "v2.1.0-rc.1")
    return root


@pytest.fixture()
def fake_gh(tmp_path: Path, monkeypatch) -> dict:
    """A stand-in gh CLI: logs every invocation, captures --notes-file content.

    ``gh release view`` exits 1 (no release) unless the ``release-exists``
    marker file is present, so tests pin both the create and edit paths.
    """
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    log = tmp_path / "gh-log.txt"
    notes = tmp_path / "gh-notes.md"
    exists_marker = tmp_path / "release-exists"
    gh = bin_dir / "gh"
    gh.write_text(
        "#!/usr/bin/env bash\n"
        f'echo "$@" >> {log}\n'
        'if [ "$1" = "release" ] && [ "$2" = "view" ]; then\n'
        f"  if [ -f {exists_marker} ]; then exit 0; fi\n"
        "  exit 1\n"
        "fi\n"
        'prev=""\n'
        'for a in "$@"; do\n'
        f'  if [ "$prev" = "--notes-file" ]; then cp "$a" {notes} 2>/dev/null || true; fi\n'
        '  prev="$a"\n'
        "done\n"
        "exit 0\n",
        encoding="utf-8",
    )
    gh.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}:{os.environ['PATH']}")
    return {"log": log, "notes": notes, "exists_marker": exists_marker}


def test_version_block_extracts_the_versioned_block_verbatim(repo):
    module = _load_release()
    block = module.version_block(repo, "2.0.0")
    assert block == "### Added\n- the twenty point zero feature (PR #99)."


def test_version_block_refuses_an_unknown_version(repo):
    module = _load_release()
    with pytest.raises(SystemExit):
        module.version_block(repo, "9.9.9")


def test_publish_requires_the_tag_on_origin(repo, capsys):
    module = _load_release()
    with pytest.raises(SystemExit):
        module.publish_release(repo, "1.0.0", dry_run=True)  # v1.0.0 never pushed
    assert "push it first" in capsys.readouterr().err


def test_publish_dry_run_prints_the_planned_command(repo, fake_gh, capsys):
    module = _load_release()
    module.publish_release(repo, "2.0.0", dry_run=True)
    out = capsys.readouterr().out
    assert "would gh release create v2.0.0" in out
    assert "(PR #99)" in out


def test_publish_create_writes_the_notes_verbatim(repo, fake_gh):
    module = _load_release()
    module.publish_release(repo, "2.0.0", dry_run=False)
    log = fake_gh["log"].read_text()
    assert "release create v2.0.0 --title v2.0.0 --notes-file" in log
    notes = fake_gh["notes"].read_text()
    assert notes == "### Added\n- the twenty point zero feature (PR #99).\n"


def test_publish_prerelease_adds_the_flag(repo, fake_gh):
    module = _load_release()
    module.publish_release(repo, "2.1.0-rc.1", dry_run=False)
    log = fake_gh["log"].read_text()
    assert "release create v2.1.0-rc.1" in log
    assert "--prerelease" in log


def test_publish_is_idempotent_and_refreshes_notes(repo, fake_gh):
    module = _load_release()
    fake_gh["exists_marker"].touch()  # gh release view succeeds
    module.publish_release(repo, "2.0.0", dry_run=False)
    log = fake_gh["log"].read_text()
    assert "release edit v2.0.0" in log
    assert fake_gh["notes"].read_text().startswith("### Added")
