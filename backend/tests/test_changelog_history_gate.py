"""L-41 gate: a release must not cut over a merge the changelog has not recorded.

Five merges landed after v4.0.0 with no changelog entry, and nothing would
have noticed a sixth (L-41). The backfill fixed the damage; the durable fix
is the release-time check in ``scripts/check_changelog_history.py``, wired
into ``release.py`` before the cut. These tests build throwaway repositories
and pin both dispositions:

* a consumer merge (touches ``backend/``, ``frontend/`` or ``scripts/``)
  without its PR number in the ``[Unreleased]`` block refuses;
* the same merge with an entry passes;
* docs-only merges need no entry;
* the release-branch merge the cycle itself creates never demands one of
  itself -- its entries sit in the dated block the cut creates;
* the wiring in ``release.py`` turns the gap into a failed cut.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *args], capture_output=True, text=True, check=True
    )
    return result.stdout


def _check(root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_changelog_history.py"), "--root", str(root)],
        capture_output=True,
        text=True,
    )


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    """A throwaway repo: one tagged release, then a clean mainline."""
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.name", "Gate Test")
    _git(root, "config", "user.email", "gate@test.local")
    (root / "backend").mkdir()
    (root / "backend" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")
    (root / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [Unreleased]\n\n## [1.0.0] - 2026-01-01\n\n### Added\n"
        "- baseline (PR #1)\n",
        encoding="utf-8",
    )
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "baseline")
    _git(root, "tag", "-a", "v1.0.0", "-m", "v1.0.0")
    return root


def _merge(repo: Path, pr: int, path: str, content: str, entry: bool, source: str | None = None) -> None:
    """Merge a one-commit feature branch with a PR-style merge subject."""
    _git(repo, "checkout", "-q", "-b", f"feature-{pr}")
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    if entry:
        text = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
        text = text.replace("## [Unreleased]\n", f"## [Unreleased]\n\n### Fixed\n- entry (PR #{pr})\n", 1)
        (repo / "CHANGELOG.md").write_text(text, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", f"feat: change #{pr}")
    _git(repo, "checkout", "-q", "main")
    _git(
        repo,
        "merge",
        "-q",
        "--no-ff",
        f"feature-{pr}",
        "-m", f"Merge pull request #{pr} from {source or f'test/feature-{pr}'}",
    )


def test_a_consumer_merge_without_an_entry_refuses(repo):
    _merge(repo, 7, "backend/app.py", "VALUE = 2\n", entry=False)
    result = _check(repo)
    assert result.returncode == 1, result.stdout
    assert "#7" in result.stderr


def test_the_same_merge_with_an_entry_passes(repo):
    _merge(repo, 8, "backend/app.py", "VALUE = 2\n", entry=True)
    result = _check(repo)
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout


def test_a_docs_only_merge_needs_no_entry(repo):
    _merge(repo, 9, "docs/README.md", "docs\n", entry=False)
    result = _check(repo)
    assert result.returncode == 0, result.stderr


def test_a_release_branch_merge_needs_no_entry_of_itself(repo):
    """The cycle's own release merge touches frontend/ (version sync) but its
    entries sit in the dated block the cut creates -- it must never block
    the cut it belongs to."""
    _merge(
        repo, 11, "frontend/index.html", "<html></html>\n", entry=False,
        source="test/release/1.1.0",
    )
    result = _check(repo)
    assert result.returncode == 0, result.stderr


def test_release_wiring_refuses_the_cut(repo, capsys):
    spec = importlib.util.spec_from_file_location(
        "release_script", ROOT / "scripts" / "release.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    _merge(repo, 10, "scripts/tool.py", "print('tool')\n", entry=False)
    with pytest.raises(SystemExit) as excinfo:
        module.check_changelog_history(repo)
    assert excinfo.value.code == 1
    assert "#10" in capsys.readouterr().err


def test_live_tree_is_covered():
    """The real repository must always satisfy its own gate."""
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "check_changelog_history.py")],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert "OK" in result.stdout
