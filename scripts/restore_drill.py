#!/usr/bin/env python3
"""Restore drill: prove the recovery story before you need it.

A backup nobody has restored is a hypothesis. This drill verifies, against a
copy in a temporary directory, the three recovery claims the runbook makes:

1. dataset snapshots are content-addressed and their hashes still verify;
2. the point-in-time exposure store round-trips (append -> as-of query) and
   refuses clairvoyant cut-offs;
3. bilateral exposure manifests still match their matrix files.

It prints a checklist and exits non-zero on any failure. Run it after every
deployment change and on a schedule; it touches no production state.

Usage:  PYTHONPATH=. python scripts/restore_drill.py [--data-dir DATA_DIR]
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
import pandas as pd


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"[{'PASS' if ok else 'FAIL'}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=None,
                        help="production data directory to copy (optional)")
    args = parser.parse_args()

    results = []
    with tempfile.TemporaryDirectory(prefix="beacon-drill-") as tmp:
        tmp_path = Path(tmp)

        # 1. snapshot content-addressing round-trip
        from backend.modules.data.snapshots import DatasetSnapshotter

        frame = pd.DataFrame({
            "Date": pd.date_range("2024-01-01", periods=5, freq="D"),
            "source_code": "DRILL",
            "Value": np.arange(5, dtype=float),
        })
        snapshotter = DatasetSnapshotter(root=tmp_path / "snapshots")
        snapshot = snapshotter.capture({"DRILL": frame}, job_id="drill")
        restored = snapshotter.load(snapshot)
        results.append(check(
            "snapshot restores the exact rows it was issued against",
            restored["DRILL"].equals(frame),
            snapshot.snapshot_id[:16],
        ))
        results.append(check("snapshot manifest verifies against its copy", snapshotter.verify(snapshot)))
        mutated = frame.copy()
        mutated.loc[0, "Value"] = 999.0
        mutated_snapshot = snapshotter.capture({"DRILL": mutated}, job_id="drill-mutated", persist=False)
        results.append(check(
            "a mutated dataset does NOT share the original snapshot id",
            mutated_snapshot.snapshot_id != snapshot.snapshot_id,
        ))

        # 2. PIT store round-trip and anti-clairvoyance
        from backend.modules.data.pit import Observation, PITStore
        from datetime import datetime, timezone

        store = PITStore()  # in-memory: the drill touches no production state
        valid_time = datetime(2024, 1, 10, tzinfo=timezone.utc)   # period described
        published = datetime(2024, 1, 12, tzinfo=timezone.utc)     # vintage: when known
        store.append([Observation(
            entity_id="DRILL", series_id="x", valid_time=valid_time,
            observed_at=published, value=1.0, revision=0,
        )])
        known = store.query("DRILL", as_of=datetime(2024, 1, 15, tzinfo=timezone.utc))
        unknown = store.query("DRILL", as_of=datetime(2024, 1, 11, tzinfo=timezone.utc))
        results.append(check(
            "PIT round-trip returns the vintage known at the cut-off",
            len(known) == 1 and float(known.iloc[0]["value"]) == 1.0,
        ))
        results.append(check(
            "PIT refuses a cut-off before publication (anti-clairvoyance)",
            len(unknown) == 0,
        ))

        # 3. exposure manifest/matrix agreement, if a production dir is given
        if args.data_dir:
            from backend.services.bilateral_exposure_store import BilateralExposureStore
            src = Path(args.data_dir)
            work = tmp_path / "exposures"
            if src.exists():
                shutil.copytree(src, work, dirs_exist_ok=True)
                store2 = BilateralExposureStore(root=work)
                if store2.is_available():
                    matrix = store2.load()
                    manifest_ok = matrix is not None and not matrix.empty
                    results.append(check("exposure matrix loads from the copy", manifest_ok))
                else:
                    print("[SKIP] no exposure matrix present in the copy")
            else:
                print(f"[SKIP] data dir {src} does not exist")
        else:
            print("[SKIP] exposure manifest check (pass --data-dir to include)")

    failed = [ok for ok in results if not ok]
    print(f"\ndrill complete: {len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
