"""Content-addressed dataset lineage snapshots.

An attestation proves *that* a payload passed the quality gate. It does not let
anyone reproduce the risk score months later, because the rows themselves are
gone. A :class:`DatasetSnapshot` closes that gap: it fingerprints the exact
frames that were verified (per-dataset content hash, row/column counts, column
names, date span) and, when persisted, writes a byte-for-byte copy alongside a
JSON manifest.

The snapshot id is derived from the fingerprint, so it is a *content address*:
the same data always maps to the same id, and any change to any cell, column, or
row changes it. An attestation therefore carries a ``snapshot_id`` that names the
exact data it was issued against, and a prediction can be reproduced (or proven
irreproducible) later.

Content hashing uses :func:`pandas.util.hash_pandas_object`, the same value-based
hash pandas uses for duplicate detection. It is deterministic for a given pandas
build and dtype layout and is deliberately not claimed to be stable across major
pandas upgrades; the persisted copy is the durable artefact.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

logger = logging.getLogger(__name__)

SNAPSHOT_MANIFEST_NAME = "snapshot.json"
DEFAULT_SNAPSHOT_FORMAT = "parquet"
_FALLBACK_SNAPSHOT_FORMAT = "csv"
_HASH_PREFIX = "sha256:"


def canonical_json(payload: Any) -> str:
    """Serialise a payload deterministically so its hash is stable."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def sha256_bytes(payload: bytes) -> str:
    """Return a prefixed sha256 hex digest of ``payload``."""
    return _HASH_PREFIX + hashlib.sha256(payload).hexdigest()


def hash_frame(frame: pd.DataFrame) -> str:
    """Content hash of a DataFrame's values and index."""
    if frame is None:
        return sha256_bytes(b"<none>")
    hashed = pd.util.hash_pandas_object(frame, index=True, categorize=False)
    return sha256_bytes(hashed.to_numpy(dtype="uint64").tobytes())


def _date_span(frame: pd.DataFrame) -> Tuple[Optional[str], Optional[str]]:
    for column in ("Date", "date", "timestamp"):
        if column not in frame.columns:
            continue
        parsed = pd.to_datetime(frame[column], errors="coerce").dropna()
        if parsed.empty:
            continue
        return parsed.min().isoformat(), parsed.max().isoformat()
    return None, None


@dataclass(frozen=True)
class DatasetFingerprint:
    """Content and shape of one collected dataset."""

    code: str
    rows: int
    columns: int
    column_names: Tuple[str, ...]
    content_hash: str
    first_date: Optional[str] = None
    last_date: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "rows": int(self.rows),
            "columns": int(self.columns),
            "column_names": list(self.column_names),
            "content_hash": self.content_hash,
            "first_date": self.first_date,
            "last_date": self.last_date,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DatasetFingerprint":
        return cls(
            code=str(payload.get("code", "")),
            rows=int(payload.get("rows", 0)),
            columns=int(payload.get("columns", 0)),
            column_names=tuple(payload.get("column_names") or ()),
            content_hash=str(payload.get("content_hash", "")),
            first_date=payload.get("first_date"),
            last_date=payload.get("last_date"),
        )


@dataclass(frozen=True)
class DatasetSnapshot:
    """Frozen reference to the exact data a verdict was issued against."""

    snapshot_id: str
    job_id: str
    created_at: str
    rows: int
    columns: int
    datasets: Tuple[DatasetFingerprint, ...] = ()
    root: Optional[str] = None
    files: Dict[str, str] = field(default_factory=dict)
    payload_bytes: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "snapshot_id": self.snapshot_id,
            "job_id": self.job_id,
            "created_at": self.created_at,
            "rows": int(self.rows),
            "columns": int(self.columns),
            "root": self.root,
            "files": dict(self.files),
            "payload_bytes": self.payload_bytes,
            "datasets": [fingerprint.to_dict() for fingerprint in self.datasets],
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "DatasetSnapshot":
        return cls(
            snapshot_id=str(payload.get("snapshot_id", "")),
            job_id=str(payload.get("job_id", "unknown")),
            created_at=str(payload.get("created_at", "")),
            rows=int(payload.get("rows", 0)),
            columns=int(payload.get("columns", 0)),
            datasets=tuple(
                DatasetFingerprint.from_dict(item) for item in payload.get("datasets") or ()
            ),
            root=payload.get("root"),
            files=dict(payload.get("files") or {}),
            payload_bytes=payload.get("payload_bytes"),
        )

    def fingerprint(self) -> Dict[str, Any]:
        """The canonical payload whose hash *is* the snapshot id."""
        return {
            "job_id": self.job_id,
            "rows": int(self.rows),
            "columns": int(self.columns),
            "datasets": [
                fingerprint.to_dict()
                for fingerprint in sorted(self.datasets, key=lambda item: item.code)
            ],
        }

    def verify(self, datasets: Optional[Mapping[str, pd.DataFrame]] = None) -> bool:
        """Check the id against the fingerprint and, optionally, the live frames.

        Returns ``False`` when the id does not match its own fingerprint, or when
        any supplied frame's content hash differs from the recorded one.
        """
        if self.snapshot_id != compute_snapshot_id(self):
            return False
        if datasets is None:
            return True
        recorded = {fingerprint.code: fingerprint for fingerprint in self.datasets}
        for code, frame in datasets.items():
            fingerprint = recorded.get(code)
            if fingerprint is None or fingerprint.content_hash != hash_frame(frame):
                return False
        return True


def compute_snapshot_id(snapshot: DatasetSnapshot) -> str:
    """Content address of the fingerprint carried by ``snapshot``."""
    return sha256_bytes(canonical_json(snapshot.fingerprint()).encode("utf-8"))


def fingerprint_frame(code: str, frame: pd.DataFrame) -> DatasetFingerprint:
    """Fingerprint a single named dataset."""
    first_date, last_date = _date_span(frame)
    return DatasetFingerprint(
        code=str(code),
        rows=int(frame.shape[0]),
        columns=int(frame.shape[1]),
        column_names=tuple(str(column) for column in frame.columns),
        content_hash=hash_frame(frame),
        first_date=first_date,
        last_date=last_date,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return _HASH_PREFIX + digest.hexdigest()


class DatasetSnapshotter:
    """Capture, persist and verify content-addressed dataset snapshots."""

    def __init__(self, root: Optional[str] = None, *, format: Optional[str] = None) -> None:
        self.root = Path(root) if root else None
        self.format = (format or DEFAULT_SNAPSHOT_FORMAT).lower()

    def snapshot_dir(self, snapshot_id: str) -> Optional[Path]:
        if self.root is None:
            return None
        return self.root / snapshot_id.replace(_HASH_PREFIX, "").replace(":", "_")

    def capture(
        self,
        datasets: Mapping[str, pd.DataFrame],
        *,
        job_id: str,
        persist: bool = True,
    ) -> DatasetSnapshot:
        """Fingerprint ``datasets`` and optionally write a copy plus a manifest."""
        frames = {str(code): frame for code, frame in (datasets or {}).items() if frame is not None}
        fingerprints = tuple(
            fingerprint_frame(code, frame) for code, frame in sorted(frames.items())
        )
        rows = int(sum(fingerprint.rows for fingerprint in fingerprints))
        columns = int(max((fingerprint.columns for fingerprint in fingerprints), default=0))

        placeholder = DatasetSnapshot(
            snapshot_id="",
            job_id=str(job_id),
            created_at=datetime.now(timezone.utc).isoformat(),
            rows=rows,
            columns=columns,
            datasets=fingerprints,
        )
        snapshot_id = compute_snapshot_id(placeholder)

        files: Dict[str, str] = {}
        payload_bytes: Optional[int] = None
        root: Optional[str] = None
        if persist and self.root is not None:
            directory = self.snapshot_dir(snapshot_id)
            assert directory is not None  # narrowed by the root check above
            directory.mkdir(parents=True, exist_ok=True)
            total_bytes = 0
            for code, frame in sorted(frames.items()):
                path, written_bytes = self._write_frame(directory, code, frame)
                files[code] = str(path)
                total_bytes += written_bytes
            payload_bytes = int(total_bytes)
            root = str(directory)

        snapshot = DatasetSnapshot(
            snapshot_id=snapshot_id,
            job_id=str(job_id),
            created_at=placeholder.created_at,
            rows=rows,
            columns=columns,
            datasets=fingerprints,
            root=root,
            files=files,
            payload_bytes=payload_bytes,
        )

        if root is not None:
            manifest_path = Path(root) / SNAPSHOT_MANIFEST_NAME
            manifest_path.write_text(canonical_json(snapshot.to_dict()), encoding="utf-8")
            files[SNAPSHOT_MANIFEST_NAME] = str(manifest_path)
            snapshot = DatasetSnapshot(
                snapshot_id=snapshot.snapshot_id,
                job_id=snapshot.job_id,
                created_at=snapshot.created_at,
                rows=snapshot.rows,
                columns=snapshot.columns,
                datasets=snapshot.datasets,
                root=snapshot.root,
                files=files,
                payload_bytes=snapshot.payload_bytes,
            )

        logger.info(
            "Captured dataset snapshot %s for job %s (%d dataset(s), %d rows)",
            snapshot_id,
            job_id,
            len(fingerprints),
            rows,
        )
        return snapshot

    def _write_frame(self, directory: Path, code: str, frame: pd.DataFrame) -> Tuple[Path, int]:
        """Write one frame, degrading from parquet to csv when the engine is absent."""
        safe_code = "".join(character if character.isalnum() or character in "-_." else "_" for character in code)
        attempts: Sequence[str] = (self.format, _FALLBACK_SNAPSHOT_FORMAT)
        last_error: Optional[Exception] = None
        for candidate in attempts:
            path = directory / f"{safe_code}.{candidate}"
            try:
                if candidate == "parquet":
                    frame.to_parquet(path, compression="snappy")
                elif candidate == "csv":
                    frame.to_csv(path, index=True)
                else:
                    raise ValueError(f"Unsupported snapshot format {candidate!r}")
                return path, int(path.stat().st_size)
            except Exception as exc:  # noqa: BLE001 - try the next format, then surface the failure
                last_error = exc
                logger.warning(
                    "Snapshot write as %s failed for dataset %s (%s); trying the next format",
                    candidate,
                    code,
                    exc,
                )
        raise RuntimeError(f"Could not persist dataset snapshot for {code}: {last_error}")

    def load(self, snapshot: DatasetSnapshot) -> Dict[str, pd.DataFrame]:
        """Read back the persisted frames named by a snapshot."""
        if not snapshot.root:
            raise ValueError("Snapshot was captured without persistence (root is None)")
        loaded: Dict[str, pd.DataFrame] = {}
        for code, path in snapshot.files.items():
            if str(path).endswith(SNAPSHOT_MANIFEST_NAME):
                continue
            suffix = Path(path).suffix.lower().lstrip(".")
            if suffix == "parquet":
                loaded[code] = pd.read_parquet(path)
            elif suffix == "csv":
                loaded[code] = pd.read_csv(path)
            else:
                logger.warning("Skipping snapshot file with unknown format: %s", path)
        return loaded

    def load_manifest(self, snapshot_id: str) -> Optional[DatasetSnapshot]:
        """Read a persisted manifest by content address."""
        directory = self.snapshot_dir(snapshot_id)
        if directory is None:
            return None
        manifest_path = directory / SNAPSHOT_MANIFEST_NAME
        if not manifest_path.exists():
            return None
        return DatasetSnapshot.from_dict(json.loads(manifest_path.read_text(encoding="utf-8")))

    def verify(self, snapshot: DatasetSnapshot) -> bool:
        """Re-hash the persisted files and compare them with the fingerprint."""
        if snapshot.snapshot_id != compute_snapshot_id(snapshot):
            return False
        for fingerprint in snapshot.datasets:
            path = snapshot.files.get(fingerprint.code)
            if path is None:
                continue
            candidate = Path(path)
            if not candidate.exists():
                return False
            try:
                if candidate.suffix.lower() == ".parquet":
                    frame = pd.read_parquet(candidate)
                else:
                    frame = pd.read_csv(candidate, index_col=0)
            except Exception:  # noqa: BLE001 - an unreadable snapshot is a failed verification
                logger.exception("Could not read snapshot file %s", candidate)
                return False
            if hash_frame(frame) != fingerprint.content_hash:
                return False
        return True


def snapshot_root_for(output_dir: str, configured: Optional[str] = None) -> str:
    """Resolve where snapshots for a job should live."""
    if configured:
        return configured
    return os.path.join(output_dir, "snapshots")
