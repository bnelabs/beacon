"""Reproducibility manifest for trained model artefacts.

A risk score that cannot be traced back to the code, configuration, data and
model weights that produced it is not defensible in a regulated setting. Every
trained artefact therefore gets a small JSON manifest written next to it,
recording:

* ``git_sha`` -- the revision the training code came from,
* ``config_hash`` -- a content hash of the resolved training configuration,
* ``attestation_id`` -- the content address of the DATA quality verdict,
* ``snapshot_id`` -- the content address of the exact rows that were verified,
* ``model_artifact_hash`` -- the sha256 of the model file itself.

:meth:`ModelManifest.verify` re-hashes the artefact, so tampering or an
accidental overwrite is detectable rather than assumed away. This is deliberately
a file, not a service: it needs no database, survives a container restart, and
can be attached to an audit pack.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Union

from backend.modules.data.snapshots import canonical_json, sha256_bytes

logger = logging.getLogger(__name__)

MANIFEST_VERSION = 1
MANIFEST_FILENAME = "reproducibility.json"

_GIT_SHA_ENV_VARS = ("BEACON_GIT_SHA", "GITHUB_SHA", "GIT_COMMIT", "SOURCE_VERSION")


def sha256_file(path: Union[str, os.PathLike]) -> str:
    """Return a prefixed sha256 digest of a file's bytes."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def config_hash(config: Optional[Mapping[str, Any]]) -> str:
    """Content hash of a training configuration."""
    return sha256_bytes(canonical_json(dict(config or {})).encode("utf-8"))


def _git_directory(start: Path) -> Optional[Path]:
    for candidate in (start, *start.parents):
        dot_git = candidate / ".git"
        if dot_git.is_dir():
            return dot_git
        if dot_git.is_file():
            content = dot_git.read_text(encoding="utf-8", errors="replace").strip()
            if content.startswith("gitdir:"):
                target = Path(content.split(":", 1)[1].strip())
                return target if target.is_absolute() else (candidate / target)
    return None


def _read_git_head(start: Path) -> Optional[str]:
    git_dir = _git_directory(start)
    if git_dir is None:
        return None
    head = git_dir / "HEAD"
    if not head.exists():
        return None
    content = head.read_text(encoding="utf-8", errors="replace").strip()
    if not content:
        return None
    if content.startswith("ref:"):
        ref = content.split(":", 1)[1].strip()
        ref_file = git_dir / ref
        if ref_file.exists():
            resolved = ref_file.read_text(encoding="utf-8", errors="replace").strip()
            return resolved or None
        packed = git_dir / "packed-refs"
        if packed.exists():
            for line in packed.read_text(encoding="utf-8", errors="replace").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith("^"):
                    continue
                sha, _, name = line.partition(" ")
                if name.strip() == ref:
                    return sha
        return None
    return content


def git_sha(start: Optional[Union[str, os.PathLike]] = None) -> str:
    """Resolve the current revision from the environment, then from ``.git``."""
    for name in _GIT_SHA_ENV_VARS:
        value = os.getenv(name)
        if value is not None and value.strip():
            return value.strip()
    location = Path(start) if start is not None else Path(__file__).resolve().parent
    try:
        resolved = _read_git_head(location)
    except OSError:  # pragma: no cover - unreadable .git is not worth failing over
        logger.warning("Could not read git metadata from %s", location)
        return "unknown"
    return resolved or "unknown"


def _resolve_identifier(value: Any, attribute: str) -> Optional[str]:
    """Accept ``None``, a plain string, or an object exposing ``attribute``."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    identifier = getattr(value, attribute, None)
    return None if identifier is None else str(identifier)


@dataclass
class ModelManifest:
    """Everything needed to re-derive how a model artefact came to exist."""

    manifest_version: int = MANIFEST_VERSION
    created_at: str = ""
    model_path: str = ""
    model_artifact_hash: Optional[str] = None
    config_hash: Optional[str] = None
    git_sha: str = "unknown"
    attestation_id: Optional[str] = None
    snapshot_id: Optional[str] = None
    job_id: Optional[str] = None
    model_type: Optional[str] = None
    dataset_row_counts: Dict[str, int] = field(default_factory=dict)
    training_metrics: Dict[str, Any] = field(default_factory=dict)
    backtest: Optional[Dict[str, Any]] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    # -- construction -------------------------------------------------------

    @classmethod
    def capture(
        cls,
        model_path: Union[str, os.PathLike],
        config: Optional[Mapping[str, Any]] = None,
        *,
        job_id: Optional[str] = None,
        model_type: Optional[str] = None,
        attestation: Any = None,
        attestation_id: Optional[str] = None,
        snapshot: Any = None,
        snapshot_id: Optional[str] = None,
        dataset_row_counts: Optional[Mapping[str, int]] = None,
        training_metrics: Optional[Mapping[str, Any]] = None,
        backtest: Optional[Mapping[str, Any]] = None,
        extra: Optional[Mapping[str, Any]] = None,
    ) -> "ModelManifest":
        """Build a manifest for ``model_path``, hashing it if it exists."""
        resolved_path = Path(model_path)
        artifact_hash: Optional[str] = None
        if resolved_path.exists() and resolved_path.is_file():
            artifact_hash = sha256_file(resolved_path)
        else:
            logger.warning(
                "Model artefact %s does not exist; the manifest will carry no artifact hash",
                resolved_path,
            )

        return cls(
            manifest_version=MANIFEST_VERSION,
            created_at=datetime.now(timezone.utc).isoformat(),
            model_path=str(resolved_path),
            model_artifact_hash=artifact_hash,
            config_hash=config_hash(config),
            git_sha=git_sha(),
            attestation_id=_resolve_identifier(attestation, "attestation_id") or attestation_id,
            snapshot_id=(
                _resolve_identifier(snapshot, "snapshot_id") or snapshot_id
            ),
            job_id=None if job_id is None else str(job_id),
            model_type=model_type,
            dataset_row_counts={str(k): int(v) for k, v in (dataset_row_counts or {}).items()},
            training_metrics=json.loads(canonical_json(dict(training_metrics or {}))),
            backtest=None if backtest is None else json.loads(canonical_json(dict(backtest))),
            extra=json.loads(canonical_json(dict(extra or {}))),
        )

    # -- serialisation ------------------------------------------------------

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ModelManifest":
        return cls(
            manifest_version=int(payload.get("manifest_version", MANIFEST_VERSION)),
            created_at=str(payload.get("created_at", "")),
            model_path=str(payload.get("model_path", "")),
            model_artifact_hash=payload.get("model_artifact_hash"),
            config_hash=payload.get("config_hash"),
            git_sha=str(payload.get("git_sha", "unknown")),
            attestation_id=payload.get("attestation_id"),
            snapshot_id=payload.get("snapshot_id"),
            job_id=payload.get("job_id"),
            model_type=payload.get("model_type"),
            dataset_row_counts={
                str(k): int(v) for k, v in (payload.get("dataset_row_counts") or {}).items()
            },
            training_metrics=dict(payload.get("training_metrics") or {}),
            backtest=payload.get("backtest"),
            extra=dict(payload.get("extra") or {}),
        )

    def write(self, path: Optional[Union[str, os.PathLike]] = None) -> str:
        """Write the manifest, defaulting to ``<model dir>/reproducibility.json``."""
        if path is None:
            directory = Path(self.model_path).parent if self.model_path else Path(".")
            target = directory / MANIFEST_FILENAME
        else:
            target = Path(path)
            if target.is_dir():
                target = target / MANIFEST_FILENAME
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(self.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
        logger.info("Wrote model manifest to %s", target)
        return str(target)

    @classmethod
    def load(cls, path: Union[str, os.PathLike]) -> "ModelManifest":
        """Load a manifest from a file, a directory, or a model artefact path."""
        candidate = Path(path)
        if candidate.is_dir():
            candidate = candidate / MANIFEST_FILENAME
        elif candidate.name != MANIFEST_FILENAME:
            sibling = candidate.parent / MANIFEST_FILENAME
            if sibling.exists():
                candidate = sibling
        if not candidate.exists():
            raise FileNotFoundError(f"No reproducibility manifest at {candidate}")
        return cls.from_dict(json.loads(candidate.read_text(encoding="utf-8")))

    # -- verification -------------------------------------------------------

    def verify(self, model_path: Optional[Union[str, os.PathLike]] = None) -> bool:
        """Re-hash the artefact and compare it with the recorded digest."""
        if not self.model_artifact_hash:
            logger.warning("Manifest for %s recorded no artifact hash", self.model_path)
            return False
        target = Path(model_path) if model_path is not None else Path(self.model_path)
        if not target.exists() or not target.is_file():
            logger.error("Cannot verify %s: artefact is missing", target)
            return False
        actual = sha256_file(target)
        if actual != self.model_artifact_hash:
            logger.error(
                "Artefact hash mismatch for %s: recorded %s, found %s",
                target,
                self.model_artifact_hash,
                actual,
            )
            return False
        return True

    def describe(self) -> str:
        """One-line provenance summary suitable for a log or job result."""
        return (
            f"git={self.git_sha} config={self.config_hash} "
            f"attestation={self.attestation_id} snapshot={self.snapshot_id} "
            f"artifact={self.model_artifact_hash}"
        )
