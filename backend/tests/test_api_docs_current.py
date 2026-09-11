"""The generated API inventory must match the application.

``docs/api-endpoints.md`` is generated from the live FastAPI OpenAPI schema
precisely because a hand-maintained inventory drifts silently: the generator's own
docstring records that the file it replaced documented seven endpoints that did
not exist. But a generated artefact drifts too, just differently -- it goes stale
the moment a route is added and nobody reruns the script.

That is not hypothetical. Adding the network router left this file stale, and the
CI job that checks it is not part of ``pytest`` or the ruff gate, so every local
signal was green while ``main`` was red. This test closes that gap by running the
same ``--check`` mode CI uses, so the failure surfaces locally.

The check is a subprocess rather than an import: the script reads the OpenAPI
schema the app actually serves, and importing it into the test process would test
a different app instance than the one CI regenerates from.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
GENERATOR = REPOSITORY_ROOT / "scripts" / "generate_api_docs.py"


@pytest.mark.skipif(
    not GENERATOR.is_file(), reason="the API docs generator is not present"
)
def test_api_endpoints_inventory_is_current():
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(REPOSITORY_ROOT)

    completed = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        cwd=str(REPOSITORY_ROOT),
        env=environment,
        capture_output=True,
        text=True,
        timeout=300,
    )

    assert completed.returncode == 0, (
        "docs/api-endpoints.md is stale: a route was added or removed and the "
        "inventory was not regenerated. Run\n"
        "    PYTHONPATH=. python scripts/generate_api_docs.py\n"
        "and commit the result.\n\n"
        f"stdout:\n{completed.stdout}\n\nstderr:\n{completed.stderr}"
    )
