#!/usr/bin/env python3
"""CI guard for the versioning policy in docs/VERSIONING.md.

Fails when:
  1. VERSION is missing or not strict semver;
  2. frontend/package.json disagrees with VERSION;
  3. the top block of CHANGELOG.md is neither [Unreleased] nor VERSION;
  4. backend.__version__ disagrees with VERSION.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.-]+))?$")

errors: list[str] = []

version_file = ROOT / "VERSION"
if not version_file.exists():
    print("VERSION file missing")
    raise SystemExit(1)
version = version_file.read_text(encoding="utf-8").strip()
if not SEMVER.match(version):
    errors.append(f"VERSION is not strict semver: {version!r}")

package = json.loads((ROOT / "frontend" / "package.json").read_text(encoding="utf-8"))
if package.get("version") != version:
    errors.append(
        f"frontend/package.json version {package.get('version')!r} != VERSION {version!r}"
    )

changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
blocks = re.findall(r"^## \[([^\]]+)\]", changelog, flags=re.M)
if not blocks:
    errors.append("CHANGELOG.md has no version blocks")
elif blocks[0] not in ("Unreleased", version):
    errors.append(
        f"top CHANGELOG block is [{blocks[0]}]; expected [Unreleased] or [{version}]"
    )

backend_init = (ROOT / "backend" / "__init__.py").read_text(encoding="utf-8")
if f'__version__ = "{version}"' not in backend_init and "__version__" not in backend_init:
    errors.append("backend/__init__.py does not expose __version__")

if errors:
    for error in errors:
        print(f"versioning: {error}", file=sys.stderr)
    raise SystemExit(1)
print(f"versioning: OK ({version})")
