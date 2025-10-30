import json
import os
import subprocess
import time
from pathlib import Path

import pytest
import shutil

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKER_COMPOSE_CMD = os.environ.get("DOCKER_COMPOSE_CMD", "docker compose").split()

if shutil.which("docker") is None:
    pytest.skip("docker CLI not available inside container", allow_module_level=True)


def _run(command, *, check=True, capture_output=False):
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        check=check,
        capture_output=capture_output,
        text=True,
    )
    return result.stdout if capture_output else result


def _wait_for_job(job_id: int, timeout: float = 180.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        output = _run(
            ["curl", "-s", f"http://localhost:3456/api/v1/jobs/{job_id}"],
            capture_output=True,
        )
        payload = json.loads(output)
        status = payload.get("status")
        if status in {"completed", "failed"}:
            return payload
        time.sleep(3.0)
    raise TimeoutError(f"Timed out waiting for job {job_id}")


@pytest.mark.skipif(
    os.environ.get("RUN_DOCKER_SCOPE_TESTS") != "1",
    reason="Set RUN_DOCKER_SCOPE_TESTS=1 to run Docker-based integration scope tests.",
)
def test_country_scope_roundtrip():
    if shutil.which("docker") is None:
        pytest.skip("docker CLI not available for integration test")
    try:
        _run(DOCKER_COMPOSE_CMD + ["up", "-d", "postgres", "redis", "backend", "celery-worker"])

        response = _run(
            [
                "curl",
                "-s",
                "-X",
                "POST",
                "http://localhost:3456/api/v1/jobs",
                "-H",
                "Content-Type: application/json",
                "-d",
                json.dumps(
                    {
                        "job_type": "data_collection",
                        "parameters": {
                            "regions": ["PACIFIC"],
                            "countries": ["Japan"],
                            "start_date": "2022-01-01",
                            "end_date": "2022-06-30",
                        },
                    }
                ),
            ],
            capture_output=True,
        )
        job_info = json.loads(response)
        job_id = job_info["id"]

        job_payload = _wait_for_job(job_id)
        assert job_payload["status"] == "completed", job_payload

        brief = _run(
            ["curl", "-s", f"http://localhost:3456/api/v2/reports/brief/{job_id}"],
            capture_output=True,
        )
        brief_payload = json.loads(brief)

        assert brief_payload["regions"] == ["PACIFIC"]
        assert brief_payload["countries"] == ["Japan"]
        assert brief_payload["downloaded"] >= 1

    finally:
        _run(DOCKER_COMPOSE_CMD + ["down"])
