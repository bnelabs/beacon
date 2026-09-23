"""Read certified dataset snapshots back into the indicator vintage log.

Why this exists
---------------

The pipeline certifies data twice over. ``DatasetSnapshotter`` writes a
content-addressed directory per certification -- ``<snapshot_id>/snapshot.json``
plus one persisted frame per dataset -- and ``quality_gate.enforce`` issues its
attestation against that same id. ``TimeSeriesStore.record_observations`` writes
the scalar rows into ``indicator_observations`` and appends the vintage log with
``published_at`` set to the instant of the write.

Neither half could answer the question the other half was built for. The
snapshot directories hold what the deployment certified on a given day and are
never read back by anything; the vintage log holds publication instants that all
say "the day we re-ran the pipeline". So "what did BEACON know about this series
on 3 March?" was answerable only for whatever happened to have been collected
since the log existed, while the certified payload that proves the answer sat on
disk unqueried.

This module is the bridge, and it is deliberately narrow.

What it refuses to do
---------------------

* **It never applies a snapshot that does not verify.** ``verify()`` re-hashes
  the persisted frames against the fingerprint whose hash *is* the directory
  name. A mismatch means the payload is not the one that was certified, and
  writing rows from it would put uncertified numbers into the table whose
  purpose is attestation. A refused snapshot is reported, and is *not* recorded
  as applied, so fixing the payload lets it be applied later.
* **It never stamps ``now()`` on historical data.** A backfilled vintage's
  publication instant is the snapshot's ``created_at``, and the row carries
  ``publication_basis = "certified_snapshot"`` to say so. Stamping the write
  instant would make the series unqueryable at every earlier as-of -- the
  look-ahead defect in reverse, and invisible in the data.
* **It never touches ``indicator_observations``.** That table means "what is
  believed now". A certification from March must not overwrite it, or a
  backfill would change what today's dashboards and analytics read while
  looking like a bookkeeping operation.
* **It never collapses a dataset that is not one scalar series.** A frame with
  two rows for the same period carries an identity the store's
  (period, source, indicator, region) key cannot hold; those rows are skipped
  and counted, which is the same rule ``persist_observations`` applies to panel
  rows for the same reason.
* **It never re-applies silently.** Idempotency is a ledger
  (``vintage_backfill_runs``), written in the same commit as the rows it
  covers, so a second run reports "already applied" rather than duplicating
  history -- and an application that wrote nothing is still recorded, because
  an operator deciding whether the backfill finished needs that answer too.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

from backend.modules.data.snapshots import (
    SNAPSHOT_MANIFEST_NAME,
    DatasetSnapshot,
    compute_snapshot_id,
)
from backend.modules.results.timeseries_store import TimeSeriesStore

logger = logging.getLogger(__name__)

#: The columns a collected frame is expected to carry. ``collector`` documents
#: the plugin contract as canonical ``Date``/``Value`` (or ``Close``); the extra
#: spellings are what older persisted snapshots contain.
DATE_COLUMNS = ("Date", "date", "timestamp", "time")
VALUE_COLUMNS = ("Value", "value", "Close", "close")

ALREADY_APPLIED = "already applied"

MAX_CODE_LENGTH = 100
MAX_REGION_LENGTH = 50


@dataclass
class BackfillReport:
    """What a backfill did, in the terms an operator has to act on."""

    dry_run: bool = False
    roots: Tuple[str, ...] = ()
    snapshots_found: int = 0
    snapshots_applied: int = 0
    snapshots_skipped: int = 0
    verification_failures: int = 0
    rows_seen: int = 0
    rows_written: int = 0
    would_write: int = 0
    rows_skipped_invalid: int = 0
    rows_skipped_ambiguous: int = 0
    datasets_skipped_unmapped: int = 0
    datasets_skipped_unreadable: int = 0
    applied: List[Dict[str, Any]] = field(default_factory=list)
    skipped: List[Dict[str, Any]] = field(default_factory=list)
    failed: List[Dict[str, Any]] = field(default_factory=list)
    unmapped: List[Dict[str, Any]] = field(default_factory=list)
    unreadable: List[Dict[str, Any]] = field(default_factory=list)

    @property
    def publication_basis(self) -> str:
        """Every row this tool writes carries this basis, and only this one."""
        return "certified_snapshot"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "roots": list(self.roots),
            "publication_basis": self.publication_basis,
            "latest_value_table_touched": False,
            "snapshots_found": self.snapshots_found,
            "snapshots_applied": self.snapshots_applied,
            "snapshots_skipped": self.snapshots_skipped,
            "verification_failures": self.verification_failures,
            "rows_seen": self.rows_seen,
            "rows_written": self.rows_written,
            "would_write": self.would_write,
            "rows_skipped_invalid": self.rows_skipped_invalid,
            "rows_skipped_ambiguous": self.rows_skipped_ambiguous,
            "datasets_skipped_unmapped": self.datasets_skipped_unmapped,
            "datasets_skipped_unreadable": self.datasets_skipped_unreadable,
            "applied": list(self.applied),
            "skipped": list(self.skipped),
            "failed": list(self.failed),
            "unmapped": list(self.unmapped),
            "unreadable": list(self.unreadable),
        }


def discover_snapshot_manifests(roots: Any) -> List[Path]:
    """Every ``snapshot.json`` under ``roots``, deepest job directories included.

    Snapshots are filed per job output directory
    (``snapshot_root_for`` resolves to ``<output_dir>/snapshots``), so a scan
    that only reads one level finds none of them on a real volume.
    """
    if isinstance(roots, (str, Path)):
        roots = [roots]
    found: List[Path] = []
    for root in roots:
        root = Path(root)
        if not root.exists():
            logger.warning("Snapshot backfill root %s does not exist", root)
            continue
        if root.is_file() and root.name == SNAPSHOT_MANIFEST_NAME:
            found.append(root)
            continue
        found.extend(path for path in root.rglob(SNAPSHOT_MANIFEST_NAME) if path.is_file())
    return sorted(set(found))


def publishers_from_catalogue(session) -> Dict[str, Tuple[str, str]]:
    """Indicator code -> (publisher plugin type, region), from the catalogue.

    The same mapping ``persist_observations`` applies: a code that no configured
    source publishes is skipped rather than written under an invented publisher.
    A snapshot names its datasets by catalogue code and records no publisher of
    its own, so the catalogue is the only honest source of that identity.
    """
    from backend.models.data_catalogue import DataCatalogueItem

    publishers: Dict[str, Tuple[str, str]] = {}
    for item in session.query(DataCatalogueItem).all():
        source = item.data_source
        plugin_type = getattr(source, "plugin_type", None) if source else None
        if not plugin_type:
            continue
        region = getattr(getattr(item, "region", None), "value", None) or "GLOBAL"
        publishers[str(item.code)] = (str(plugin_type), str(region))
    return publishers


class VintageBackfiller:
    """Apply verified certified snapshots to the indicator vintage log."""

    def __init__(
        self,
        session,
        roots: Any,
        publishers: Mapping[str, Tuple[str, str]],
        *,
        dry_run: bool = False,
    ) -> None:
        self.store = TimeSeriesStore(session)
        self.roots = [str(root) for root in ([roots] if isinstance(roots, (str, Path)) else list(roots))]
        self.publishers = dict(publishers or {})
        self.dry_run = dry_run

    @classmethod
    def discover(cls, roots: Any) -> List[Tuple[DatasetSnapshot, Path]]:
        """The snapshots a backfill would look at, as (manifest, manifest path)."""
        found: List[Tuple[DatasetSnapshot, Path]] = []
        for manifest_path in discover_snapshot_manifests(roots):
            snapshot = cls._read_manifest(manifest_path)
            if snapshot is None:
                continue
            found.append((snapshot, manifest_path))
        return found

    @staticmethod
    def _read_manifest(manifest_path: Path) -> Optional[DatasetSnapshot]:
        import json

        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("Snapshot manifest %s is unreadable; not treated as a snapshot", manifest_path)
            return None
        if not isinstance(payload, dict) or not payload.get("snapshot_id"):
            logger.warning(
                "%s carries no snapshot id; it is a directory, not a certified snapshot",
                manifest_path,
            )
            return None
        return DatasetSnapshot.from_dict(payload)

    @staticmethod
    def _resolve_frames(snapshot: DatasetSnapshot, manifest_path: Path) -> DatasetSnapshot:
        """Point the manifest's frame paths at where they actually are.

        ``capture`` records absolute paths. A volume copied, remounted, or
        restored elsewhere would then fail verification for a reason that has
        nothing to do with its contents, so each frame is resolved against the
        manifest's own directory.
        """
        directory = manifest_path.parent
        files: Dict[str, str] = {}
        for code, path in snapshot.files.items():
            candidate = Path(path)
            if candidate.exists():
                files[code] = str(candidate)
                continue
            local = directory / candidate.name
            if local.exists():
                files[code] = str(local)
        return DatasetSnapshot(
            snapshot_id=snapshot.snapshot_id,
            job_id=snapshot.job_id,
            created_at=snapshot.created_at,
            rows=snapshot.rows,
            columns=snapshot.columns,
            datasets=snapshot.datasets,
            root=str(directory),
            files=files,
            payload_bytes=snapshot.payload_bytes,
        )

    def run(self) -> BackfillReport:
        report = BackfillReport(dry_run=self.dry_run, roots=tuple(self.roots))
        manifests = discover_snapshot_manifests(self.roots)
        report.snapshots_found = len(manifests)

        for manifest_path in manifests:
            recorded = self._read_manifest(manifest_path)
            if recorded is None:
                report.verification_failures += 1
                report.failed.append(
                    {
                        "snapshot_id": None,
                        "directory": str(manifest_path.parent),
                        "reason": "manifest is unreadable or carries no snapshot id",
                    }
                )
                continue

            snapshot = self._resolve_frames(recorded, manifest_path)
            snapshot_id = snapshot.snapshot_id

            if snapshot_id != compute_snapshot_id(snapshot):
                report.verification_failures += 1
                report.failed.append(
                    {
                        "snapshot_id": snapshot_id,
                        "directory": str(manifest_path.parent),
                        "reason": "manifest snapshot id does not match its own fingerprint",
                    }
                )
                continue

            if self.store.has_backfill_been_applied(snapshot_id):
                report.snapshots_skipped += 1
                report.skipped.append(
                    {
                        "snapshot_id": snapshot_id,
                        "directory": str(manifest_path.parent),
                        "reason": ALREADY_APPLIED,
                    }
                )
                continue

            published_at = self._created_at(snapshot)
            if published_at is None:
                report.verification_failures += 1
                report.failed.append(
                    {
                        "snapshot_id": snapshot_id,
                        "directory": str(manifest_path.parent),
                        "reason": "manifest has no readable created_at, so no honest publication instant exists",
                    }
                )
                continue

            rows, counts = self._rows_for(snapshot)
            report.rows_seen += counts["seen"]
            report.rows_skipped_invalid += counts["invalid"]
            report.rows_skipped_ambiguous += counts["ambiguous"]
            report.datasets_skipped_unmapped += counts["unmapped"]
            report.datasets_skipped_unreadable += counts["unreadable"]
            report.unmapped.extend(counts["unmapped_codes"])
            report.unreadable.extend(counts["unreadable_codes"])

            if not self._frames_verify(snapshot):
                report.verification_failures += 1
                report.failed.append(
                    {
                        "snapshot_id": snapshot_id,
                        "directory": str(manifest_path.parent),
                        "reason": "persisted frames do not match the certified fingerprint",
                    }
                )
                logger.error(
                    "Snapshot backfill refused %s: persisted frames do not match the "
                    "fingerprint the quality gate certified against",
                    snapshot_id,
                )
                continue

            if self.dry_run:
                report.would_write += len(rows)
                report.applied.append(
                    {
                        "snapshot_id": snapshot_id,
                        "job_id": snapshot.job_id,
                        "created_at": published_at.isoformat(),
                        "rows_written": 0,
                        "rows_would_write": len(rows),
                        "dry_run": True,
                    }
                )
                continue

            written = self.store.record_backfilled_vintages(
                rows,
                snapshot_id=snapshot_id,
                published_at=published_at,
                job_id=snapshot.job_id,
                source_directory=str(manifest_path.parent),
            )
            report.snapshots_applied += 1
            report.rows_written += written
            report.applied.append(
                {
                    "snapshot_id": snapshot_id,
                    "job_id": snapshot.job_id,
                    "created_at": published_at.isoformat(),
                    "rows_written": written,
                    "rows_skipped": counts["invalid"] + counts["ambiguous"],
                }
            )
            logger.info(
                "Vintage backfill applied snapshot %s (job %s, published %s): %d vintage(s)",
                snapshot_id,
                snapshot.job_id,
                published_at.isoformat(),
                written,
            )

        return report

    @staticmethod
    def _created_at(snapshot: DatasetSnapshot) -> Optional[datetime]:
        """The certified capture instant, as an aware timestamp.

        A missing or unparseable one is not defaulted to now: the whole point of
        a backfilled vintage is that its publication instant came from the
        snapshot rather than from the moment the tool happened to run.
        """
        try:
            stamp = pd.Timestamp(snapshot.created_at)
        except (TypeError, ValueError):
            return None
        if pd.isna(stamp):
            return None
        stamp = stamp.tz_localize(timezone.utc) if stamp.tzinfo is None else stamp.tz_convert(timezone.utc)
        return stamp.to_pydatetime()

    def _frames_verify(self, snapshot: DatasetSnapshot) -> bool:
        """Whether the persisted frames still match the certified fingerprint."""
        from backend.modules.data.snapshots import DatasetSnapshotter

        snapshotter = DatasetSnapshotter(str(Path(snapshot.root or ".")))
        try:
            return snapshotter.verify(snapshot)
        except Exception:  # noqa: BLE001 - an unreadable snapshot is a refused snapshot
            logger.exception("Could not re-hash the persisted frames of snapshot %s", snapshot.snapshot_id)
            return False

    def _rows_for(
        self, snapshot: DatasetSnapshot
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        counts: Dict[str, Any] = {
            "seen": 0,
            "invalid": 0,
            "ambiguous": 0,
            "unmapped": 0,
            "unreadable": 0,
            "unmapped_codes": [],
            "unreadable_codes": [],
        }
        rows: List[Dict[str, Any]] = []

        frames = self._load_frames(snapshot)
        for code, frame in sorted(frames.items()):
            counts["seen"] += int(len(frame))
            publisher = self.publishers.get(code)
            if publisher is None:
                counts["unmapped"] += 1
                counts["unmapped_codes"].append(
                    {"code": code, "snapshot_id": snapshot.snapshot_id, "rows": int(len(frame))}
                )
                continue

            date_column = next((name for name in DATE_COLUMNS if name in frame.columns), None)
            value_column = next((name for name in VALUE_COLUMNS if name in frame.columns), None)
            if date_column is None or value_column is None:
                counts["unreadable"] += 1
                counts["unreadable_codes"].append(
                    {
                        "code": code,
                        "snapshot_id": snapshot.snapshot_id,
                        "rows": int(len(frame)),
                        "columns": [str(column) for column in frame.columns],
                        "reason": "no recognizable date or value column",
                    }
                )
                continue

            stamps = pd.to_datetime(frame[date_column], errors="coerce", utc=True)
            values = pd.to_numeric(frame[value_column], errors="coerce")

            # A period reported more than once means the frame carries an
            # identity the store's key cannot hold. Collapsing it would keep one
            # entity's number and lose the other without recording which.
            known = stamps.dropna()
            if len(known) != len(known.unique()):
                counts["ambiguous"] += int(len(frame))
                logger.warning(
                    "Vintage backfill skipped dataset %s in snapshot %s: %d row(s) share a "
                    "reporting period, so the frame is not one scalar series and would be "
                    "collapsed by the (period, source, indicator) key",
                    code,
                    snapshot.snapshot_id,
                    int(len(frame)),
                )
                continue

            for position in range(len(frame)):
                stamp = stamps.iat[position]
                value = values.iat[position]
                if pd.isna(stamp) or pd.isna(value) or not bool(np.isfinite(value)):
                    counts["invalid"] += 1
                    continue
                rows.append(
                    {
                        "time": pd.Timestamp(stamp).tz_convert(timezone.utc).to_pydatetime(),
                        "source_code": publisher[0][:MAX_CODE_LENGTH],
                        "indicator_code": str(code)[:MAX_CODE_LENGTH],
                        "region": publisher[1][:MAX_REGION_LENGTH],
                        "value": float(value),
                        "ingest_job_id": snapshot.job_id,
                    }
                )

        return rows, counts

    @staticmethod
    def _load_frames(snapshot: DatasetSnapshot) -> Dict[str, pd.DataFrame]:
        from backend.modules.data.snapshots import DatasetSnapshotter

        if not snapshot.root:
            return {}
        snapshotter = DatasetSnapshotter(snapshot.root)
        try:
            return snapshotter.load(snapshot)
        except Exception:  # noqa: BLE001 - reported as a verification failure by the caller
            logger.exception("Could not read the persisted frames of snapshot %s", snapshot.snapshot_id)
            return {}


def backfill_indicator_vintages(
    session,
    roots: Any,
    *,
    publishers: Optional[Mapping[str, Tuple[str, str]]] = None,
    dry_run: bool = False,
) -> BackfillReport:
    """Apply every verified certified snapshot under ``roots`` to the vintage log."""
    mapping = publishers if publishers is not None else publishers_from_catalogue(session)
    return VintageBackfiller(session, roots, mapping, dry_run=dry_run).run()
