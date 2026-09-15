"""The e2e API mock covers every endpoint the frontend calls.

`frontend/tests/apiMocks.js` answers `**/api/**` for the Playwright suite, and its
default for an unknown GET is a deliberate 404 -- "as the real API does", because
answering 200 with an empty object once let a wrong URL pass as a successful
empty result. That default is correct and is kept. Its consequence is that an
endpoint the frontend adopts and the mock does not cover produces a console
error, and `full-frontend.spec.js` fails the test on *any* console error -- at
whatever assertion happened to be executing when TanStack Query retried the
failed request, not at the thing that is missing.

That is not hypothetical. `GET /api/v1/data-sources/disclosure` was added by
#53 and never mocked, so from that merge onward frontend-ci was red on every run,
on main and on every branch cut from it, reporting a create-source form that would
not close. The POST had returned 201; the button was still `disabled` because
`onClose()` never ran, because the console handler had thrown first. Finding it
needed the trace's network log, where one 404 sat among 113 successful requests.

`scripts/check_e2e_api_coverage.mjs` runs the mock's real route handler against
every `fetchApi` endpoint in `frontend/src` and names the ones that fall through.
Frontend CI runs it before Playwright, so the failure says which endpoint is
missing instead of which assertion was interrupted. This test is the same check
for anyone running the backend suite locally, and skips when node is absent
rather than failing, because the backend suite has no node dependency of its own.

An endpoint may be listed in the script's `DECLARED_UNMOCKED` with the reason no
e2e path reaches it -- the same shape as the disposition census in
`test_reachability.py`. A declaration that stops being true fails the check, so
the register cannot go stale in the direction that matters.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CHECK = REPO_ROOT / "scripts" / "check_e2e_api_coverage.mjs"

node = shutil.which("node")

pytestmark = pytest.mark.skipif(
    node is None,
    reason=(
        "node is not installed, so the e2e API-coverage check cannot run. "
        "Frontend CI runs it unconditionally; this skip only affects a backend-only "
        "environment."
    ),
)


def test_the_check_script_exists():
    assert CHECK.exists(), f"{CHECK} is missing but this test and Frontend CI both run it"


def test_every_frontend_endpoint_is_answered_by_the_e2e_mock():
    result = subprocess.run(
        [node, str(CHECK)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, (
        "the e2e mock does not answer every endpoint the frontend calls:\n"
        f"{result.stdout}\n{result.stderr}"
    )
    assert "not answered" in result.stdout, result.stdout


def test_the_check_fails_on_an_endpoint_it_does_not_know():
    """A coverage check that cannot fail is not a check.

    Point it at a copy of the frontend with one extra `fetchApi` call and assert
    a non-zero exit naming that endpoint. Without this, "the check passed" and
    "the check ran" are indistinguishable -- the same distinction
    `test_compose_stack.py` makes for the compose validator.
    """
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "scripts").mkdir(parents=True)
        (root / "frontend" / "tests").mkdir(parents=True)
        (root / "frontend" / "src").mkdir(parents=True)
        shutil.copy(CHECK, root / "scripts" / CHECK.name)
        shutil.copy(
            REPO_ROOT / "frontend" / "tests" / "apiMocks.js",
            root / "frontend" / "tests" / "apiMocks.js",
        )
        (root / "frontend" / "src" / "invented.js").write_text(
            "import { fetchApi } from '../utils/apiClient'\n"
            "export const useInvented = () => fetchApi('/v1/definitely-not-mocked')\n",
            encoding="utf-8",
        )

        result = subprocess.run(
            [node, str(root / "scripts" / CHECK.name)],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=180,
        )
        assert result.returncode == 1, (
            "the coverage check accepted an endpoint nothing mocks:\n"
            f"{result.stdout}"
        )
        assert "/api/v1/definitely-not-mocked" in result.stdout, result.stdout
