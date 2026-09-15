#!/usr/bin/env python3
"""Assert the deployment invariants of the compose stack, without a Docker daemon.

Why this exists
---------------

``docker compose config`` validates that the files *parse*. It does not validate
that the stack boots, and it only runs in the manual ``docker-backend.yml``
workflow, whose own header says so:

    What that gives up, deliberately: nothing validates a Dockerfile or base-image
    change automatically any more. ... a broken Dockerfile or base image is found
    when someone runs this.

That is how two defects shipped in a release. ``backend/Dockerfile`` ended with
``COPY backend/entrypoint.sh`` while compose built it with ``context: ./backend``,
so the source path resolved to ``backend/backend/entrypoint.sh`` and the image
could not be built at all. And ``003`` was the root migration adding columns to a
table created five revisions later, so ``alembic upgrade head`` failed on an empty
database — which made backend and celery-worker restart-loop (64 restarts observed
on a real deployment) while ``docker compose ps`` reported ``Up``, because both
containers were up and neither had ever served a request.

Everything asserted here is a property of the merged YAML, so it needs no daemon
and can run in Backend CI on every pull request. ``docker compose config`` still
runs in the manual workflow for what only it can check.

Usage:  python scripts/validate_compose.py [--verbose]
Exit 0 when every invariant holds, 1 with a list of the ones that do not.
"""

from __future__ import annotations

import argparse
import copy
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import yaml

ROOT = Path(__file__).resolve().parents[1]

BASE = "docker-compose.yml"
OVERLAYS = (
    ("cpu", "docker-compose.cpu.yml"),
    ("gpu", "docker-compose.gpu.yml"),
)

EXPECTED_SERVICES = {
    "postgres",
    "redis",
    "migrate",
    "backend",
    "celery-worker",
    "frontend",
}

#: Services that run the backend image and therefore must not build their own.
BACKEND_SERVICES = ("migrate", "backend", "celery-worker")

VALID_CONDITIONS = {
    "service_started",
    "service_healthy",
    "service_completed_successfully",
    "service_healthy_or_restart_failed",
}


def deep_merge(base: Dict[str, Any], overlay: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Merge the way compose does: mappings recursively, everything else replaced."""
    out = copy.deepcopy(base)
    for key, value in (overlay or {}).items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def load_stacks() -> List[Tuple[str, Dict[str, Any]]]:
    base = yaml.safe_load((ROOT / BASE).read_text(encoding="utf-8"))
    stacks = [("base", base)]
    for name, path in OVERLAYS:
        overlay = yaml.safe_load((ROOT / path).read_text(encoding="utf-8"))
        stacks.append((f"base+{name}", deep_merge(base, overlay)))
    return stacks


class Report:
    def __init__(self, verbose: bool) -> None:
        self.verbose = verbose
        self.failures: List[str] = []
        self.passed = 0

    def check(self, ok: bool, message: str, scope: str = "") -> None:
        if ok:
            self.passed += 1
            if self.verbose:
                print(f"  OK   [{scope}] {message}")
        else:
            self.failures.append(f"[{scope}] {message}" if scope else message)
            print(f"  FAIL [{scope}] {message}")


def _depends_on(service: Dict[str, Any]) -> Dict[str, Any]:
    """``depends_on`` normalised to the mapping form."""
    raw = service.get("depends_on") or {}
    if isinstance(raw, list):
        return {name: {} for name in raw}
    return raw


def check_stack(name: str, merged: Dict[str, Any], report: Report) -> None:
    services = merged.get("services") or {}

    report.check(
        set(services) == EXPECTED_SERVICES,
        f"services are exactly {sorted(EXPECTED_SERVICES)} (got {sorted(services)})",
        name,
    )

    # -- one image, one build ------------------------------------------------
    images = {n: services.get(n, {}).get("image") for n in BACKEND_SERVICES}
    report.check(
        len(set(images.values())) == 1 and None not in images.values(),
        f"migrate/backend/celery-worker share one image (got {sorted(set(map(str, images.values())))})",
        name,
    )
    builders = [n for n in BACKEND_SERVICES if "build" in services.get(n, {})]
    report.check(
        builders == ["backend"],
        f"exactly one of the backend services carries a build (got {builders}); "
        "two builds download the multi-GB CUDA torch wheel twice and can drift",
        name,
    )

    build = services.get("backend", {}).get("build") or {}
    report.check(
        build.get("context") == ".",
        "backend build context is the repository root, so alembic.ini is in the image",
        name,
    )
    dockerfile = str(build.get("dockerfile") or "")
    report.check(
        dockerfile.startswith("backend/Dockerfile") and (ROOT / dockerfile).exists(),
        f"dockerfile path is context-relative and exists ({dockerfile!r})",
        name,
    )

    # -- exactly one migrator ------------------------------------------------
    migrate = services.get("migrate", {})
    report.check(
        migrate.get("command") == ["alembic", "upgrade", "head"],
        "migrate runs `alembic upgrade head` and nothing else",
        name,
    )
    report.check(
        migrate.get("restart") == "no",
        "migrate is one-shot; a migrating service that restarts hides its own failure",
        name,
    )
    for svc in BACKEND_SERVICES:
        env = services.get(svc, {}).get("environment") or {}
        report.check(
            str(env.get("BEACON_RUN_MIGRATIONS")) == "0",
            f"{svc} sets BEACON_RUN_MIGRATIONS=0 so the entrypoint cannot migrate too",
            name,
        )

    # -- ordering ------------------------------------------------------------
    for svc in ("backend", "celery-worker"):
        deps = _depends_on(services.get(svc, {}))
        report.check(
            deps.get("migrate", {}).get("condition") == "service_completed_successfully",
            f"{svc} waits for migrate to exit 0, not merely to start",
            name,
        )
    report.check(
        _depends_on(services.get("frontend", {})).get("backend", {}).get("condition")
        == "service_healthy",
        "frontend waits for a *healthy* backend; service_started is what produced "
        "a healthy nginx in front of a restart-looping API",
        name,
    )

    # every depends_on names a real service with a valid condition
    for svc_name, service in services.items():
        for dep, cfg in _depends_on(service).items():
            report.check(dep in services, f"{svc_name}.depends_on.{dep} is a real service", name)
            condition = (cfg or {}).get("condition")
            report.check(
                condition in VALID_CONDITIONS,
                f"{svc_name}.depends_on.{dep}.condition is valid ({condition!r})",
                name,
            )

    # -- healthchecks --------------------------------------------------------
    pg_test = " ".join(
        (services.get("postgres", {}).get("healthcheck") or {}).get("test") or []
    )
    report.check(
        "$${POSTGRES_USER" in pg_test and "$${POSTGRES_DB" in pg_test,
        "postgres healthcheck interpolates POSTGRES_USER/POSTGRES_DB rather than "
        "hardcoding them; a hardcoded value makes postgres permanently unhealthy "
        "for anyone who sets them in .env, and the whole stack then waits on it",
        name,
    )
    report.check(
        "healthcheck" in services.get("backend", {}),
        "backend declares a healthcheck, which is what frontend waits on",
        name,
    )

    # -- naming --------------------------------------------------------------
    report.check(
        not any("container_name" in s for s in services.values()),
        "no fixed container_name; a fixed name collides with a second checkout, "
        "release or compose project on the same host",
        name,
    )


def check_overlay_specifics(stacks: Dict[str, Dict[str, Any]], report: Report) -> None:
    gpu = stacks["base+gpu"]["services"]
    report.check(
        gpu["backend"]["build"]["dockerfile"] == "backend/Dockerfile",
        "gpu overlay swaps in the CUDA Dockerfile",
        "gpu",
    )
    report.check(
        "build" not in gpu["celery-worker"],
        "gpu overlay does not give celery-worker its own build",
        "gpu",
    )
    report.check(
        "deploy" in gpu["celery-worker"],
        "gpu overlay still reserves the GPU for the worker",
        "gpu",
    )

    # `all` is valid for NVIDIA_VISIBLE_DEVICES (container runtime device
    # selection) and invalid for CUDA_VISIBLE_DEVICES (torch parses it as a
    # device list, matches nothing, and reports no GPU). Baking `all` into the
    # image produced a container that could see the RTX 3090 via nvidia-smi and
    # not via torch.
    for scope, svc in (("gpu", gpu),):
        for name in ("backend", "celery-worker"):
            env = svc[name].get("environment") or {}
            cuda = str(env.get("CUDA_VISIBLE_DEVICES", ""))
            report.check(
                "all" not in cuda,
                f"{name} runtime CUDA_VISIBLE_DEVICES is an index list, not 'all' ({cuda!r})",
                scope,
            )
    args = gpu["backend"]["build"].get("args") or {}
    report.check(
        "all" not in str(args.get("CUDA_VISIBLE_DEVICES", "")),
        f"gpu build arg CUDA_VISIBLE_DEVICES is not 'all' ({args.get('CUDA_VISIBLE_DEVICES')!r})",
        "gpu",
    )

    cpu = stacks["base+cpu"]["services"]
    report.check(
        cpu["backend"]["build"]["dockerfile"] == "backend/Dockerfile.cpu",
        "cpu overlay uses the CPU Dockerfile",
        "cpu",
    )
    report.check(
        "deploy" not in cpu["backend"],
        "cpu overlay reserves no GPU",
        "cpu",
    )


def check_dockerfiles(report: Report) -> None:
    """The COPY sources must exist relative to the build context, not the file."""
    context = ROOT  # compose builds backend images with `context: .`
    for rel in ("backend/Dockerfile", "backend/Dockerfile.cpu"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        for lineno, line in enumerate(text.splitlines(), 1):
            stripped = line.strip()
            if not stripped.startswith("COPY") or "--from=" in stripped:
                continue
            parts = stripped.split()
            sources = parts[1:-1]  # last token is the destination
            for source in sources:
                candidate = context / source
                report.check(
                    candidate.exists(),
                    f"{rel}:{lineno} COPY source {source!r} exists under the build context",
                    "dockerfile",
                )
        report.check(
            "COPY alembic.ini" in text,
            f"{rel} copies alembic.ini, which the entrypoint's `alembic upgrade head` needs",
            "dockerfile",
        )


def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="print passing checks too")
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = Report(args.verbose)
    stacks = dict(load_stacks())
    for name, merged in stacks.items():
        check_stack(name, merged, report)
    check_overlay_specifics(stacks, report)
    check_dockerfiles(report)

    print()
    if report.failures:
        print(f"{len(report.failures)} FAILED, {report.passed} passed")
        for failure in report.failures:
            print(f"  - {failure}")
        return 1
    print(f"all {report.passed} compose/dockerfile invariants hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
