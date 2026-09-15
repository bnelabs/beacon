"""The compose stack's deployment invariants, checked without a Docker daemon.

``docker compose config`` validates that the files parse. It does not validate
that the stack boots, and it only runs in the manual ``docker-backend.yml``
workflow -- whose header states the consequence plainly: "nothing validates a
Dockerfile or base-image change automatically any more."

That is how two defects reached a release. ``backend/Dockerfile`` ended with
``COPY backend/entrypoint.sh`` while compose built it with ``context: ./backend``,
so the source resolved to ``backend/backend/entrypoint.sh`` and the image could
not be built. And revision ``003`` was the root migration adding columns to a
table created five revisions later, so ``alembic upgrade head`` failed on an empty
database; backend and celery-worker each ran it from their entrypoints and both
restart-looped (64 restarts observed) while ``docker compose ps`` reported ``Up``,
because both containers were up and neither had ever served a request.

``scripts/validate_compose.py`` asserts the invariants that would have caught
both. It is a script as well as a test so it can be run by hand against a modified
stack; this test is what makes running it non-optional.

The live half -- migrations actually applied to a real PostgreSQL from each of
the three histories a deployed database can have -- is
``backend/tests/test_migrations_live.py``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts" / "validate_compose.py"


def test_the_compose_stack_holds_its_deployment_invariants():
    result = subprocess.run(
        [sys.executable, str(VALIDATOR)],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        "compose/dockerfile invariants failed:\n"
        f"{result.stdout}\n{result.stderr}"
    )
    assert "invariants hold" in result.stdout, result.stdout


def test_the_validator_reports_a_broken_stack_rather_than_passing_it():
    """A validator that cannot fail is not a check.

    Point it at a copy of the stack with one invariant broken -- celery-worker
    given its own build, which is the duplicate-CUDA-download defect -- and
    assert a non-zero exit naming it. Without this, "the validator passes" and
    "the validator ran" are indistinguishable.
    """
    import shutil
    import tempfile

    import yaml

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        for name in (
            "docker-compose.yml",
            "docker-compose.cpu.yml",
            "docker-compose.gpu.yml",
        ):
            shutil.copy(REPO_ROOT / name, root / name)
        shutil.copytree(REPO_ROOT / "backend", root / "backend", dirs_exist_ok=True)
        shutil.copy(REPO_ROOT / "alembic.ini", root / "alembic.ini")
        # The validator derives REPO_ROOT from its own __file__ as parents[1],
        # so it has to sit in <root>/scripts/ for it to inspect <root>.
        (root / "scripts").mkdir()
        shutil.copy(VALIDATOR, root / "scripts" / "validate_compose.py")

        path = root / "docker-compose.yml"
        stack = yaml.safe_load(path.read_text(encoding="utf-8"))
        stack["services"]["celery-worker"]["build"] = {
            "context": ".",
            "dockerfile": "backend/Dockerfile.cpu",
        }
        path.write_text(yaml.safe_dump(stack, sort_keys=False), encoding="utf-8")

        result = subprocess.run(
            [sys.executable, str(root / "scripts" / "validate_compose.py")],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=120,
        )
        assert result.returncode == 1, (
            "the validator accepted a stack where celery-worker builds its own "
            f"image:\n{result.stdout}"
        )
        assert "exactly one of the backend services carries a build" in result.stdout
