#!/usr/bin/env python
"""Read certified dataset snapshots back into the indicator vintage log.

Why this exists
---------------

``indicator_vintage_log`` records every publication with the instant it was
published *to this deployment*, and ``TimeSeriesStore.observations_as_of`` plus
``GET /api/v1/observations/as-of`` read it. But the certified payload itself is
filed elsewhere: ``DatasetSnapshotter`` writes a content-addressed directory per
certification -- ``<snapshot_id>/snapshot.json`` plus one persisted frame per
dataset -- under each job's output directory, and nothing had ever read those
directories back. So the as-of answer covered only whatever had been collected
since the log was created, while the snapshots that prove what the deployment
knew earlier sat on the volume unqueried.

``backend.modules.results.vintage_backfill`` is the bridge. This file is the
operator's way to run it: point it at job output directories, and it resolves
each job's snapshot root with the same helper the collector used to write it
(``snapshot_root_for``), re-hashes every snapshot before touching the database,
and stamps each recovered vintage with the **snapshot's** capture instant rather
than now.

What the tool refuses to do, and where that is enforced
-----------------------------------------------------

The refusals are the module's, not this script's -- see that module's docstring
and ``backend/tests/test_vintage_backfill.py``:

* a snapshot that does not verify is reported under ``failed`` and is *not*
  recorded as applied, so repairing the payload lets it be applied later;
* ``indicator_observations`` is never written: it means "what is believed now";
* a re-run reports ``already applied`` instead of duplicating history;
* a dataset with two rows for one period is skipped and counted as ambiguous,
  never collapsed into the store's (period, source, indicator, region) key.

Exit status
-----------

Non-zero when the report contains failures -- a manifest that could not be read,
a snapshot whose id does not match its own fingerprint, or a payload that does
not re-hash to the content address its directory is named by. A green exit
therefore means "every snapshot I looked at verified", which is the only version
of "the backfill finished" worth having on a table whose purpose is attestation.
A dry run exits non-zero for the same reason: the operator should see the refusal
before deciding to apply.

Examples
--------

Preview what a volume holds, writing nothing::

    python scripts/backfill_indicator_vintages.py --dry-run \\
        --jobs-dir /app/data/jobs --jobs-dir /app/data/pipelines

Apply it, then print the report an operator can paste into a runbook::

    python scripts/backfill_indicator_vintages.py \\
        --jobs-dir /app/data/jobs | jq .

One known snapshot, straight from its directory::

    python scripts/backfill_indicator_vintages.py --snapshot-root /mnt/lineage
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import List, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.database import SessionLocal  # noqa: E402
from backend.modules.data.snapshots import snapshot_root_for  # noqa: E402
from backend.modules.results.vintage_backfill import (  # noqa: E402
    VintageBackfiller,
    publishers_from_catalogue,
)

logger = logging.getLogger("beacon.backfill_vintages")

#: Where the two production paths file their snapshots. ``job_tasks`` collects
#: into ``/app/data/jobs/<job_id>`` and the synchronous pipeline route into
#: ``PIPELINE_DATA_DIR`` (same default), so these are the directories a deployed
#: volume actually has. A root that does not exist is warned about and skipped.
DEFAULT_JOBS_DIRS = ("/app/data/jobs", os.getenv("PIPELINE_DATA_DIR", "/app/data/pipelines"))


def _resolve_roots(args: argparse.Namespace) -> List[str]:
    """Snapshot roots: the explicit ones, plus each job dir's own snapshot root.

    ``--jobs-dir`` walks one level of job directories and resolves each with
    ``snapshot_root_for`` -- the helper ``DataOrchestrator`` used when it wrote
    them -- so the tool looks in the same place the collector wrote to instead
    of guessing a layout.
    """
    roots: List[str] = [str(Path(root)) for root in args.snapshot_root]
    for jobs_dir in args.jobs_dir:
        base = Path(jobs_dir)
        if not base.exists():
            print(f"[warn] jobs dir {base} does not exist", file=sys.stderr)
            continue
        if (base / "snapshot.json").exists():
            # Someone pointed at a snapshot directory itself, not its parent.
            roots.append(str(base))
            continue
        for child in sorted(p for p in base.iterdir() if p.is_dir()):
            roots.append(snapshot_root_for(str(child)))
    return sorted(set(roots))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill indicator vintages from certified dataset snapshots. "
            "Reads snapshots, writes only indicator_vintage_log and "
            "vintage_backfill_runs, and never touches indicator_observations."
        )
    )
    parser.add_argument(
        "--jobs-dir",
        action="append",
        default=[],
        metavar="DIR",
        help=(
            "Directory holding per-job output; each child is resolved with "
            "snapshot_root_for(). Repeatable. Defaults to "
            + " and ".join(DEFAULT_JOBS_DIRS)
            + " when neither --jobs-dir nor --snapshot-root is given."
        ),
    )
    parser.add_argument(
        "--snapshot-root",
        action="append",
        default=[],
        metavar="DIR",
        help="A directory that already is a snapshot root (holds <snapshot_id>/snapshot.json). Repeatable.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Discover, verify and count every snapshot; write nothing and record nothing.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Suppress the human-readable summary line (the JSON report stays on stdout).",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    roots = _resolve_roots(args)
    if not roots and not args.jobs_dir and not args.snapshot_root:
        roots = _resolve_roots(
            argparse.Namespace(jobs_dir=list(DEFAULT_JOBS_DIRS), snapshot_root=[])
        )
    if not roots:
        print(
            "[error] no snapshot roots to scan: pass --jobs-dir and/or --snapshot-root "
            "(the defaults do not exist on this machine)",
            file=sys.stderr,
        )
        return 2

    session = SessionLocal()
    try:
        publishers = publishers_from_catalogue(session)
        report = VintageBackfiller(session, roots, publishers, dry_run=args.dry_run).run()
    finally:
        session.close()

    payload = report.to_dict()
    print(json.dumps(payload, indent=2, sort_keys=True))

    if not args.quiet:
        verb = "would write" if report.dry_run else "wrote"
        print(
            f"\n{report.snapshots_found} snapshot(s) found under {len(roots)} root(s): "
            f"{report.snapshots_applied} applied, {report.snapshots_skipped} already applied, "
            f"{report.verification_failures} refused; {verb} {report.rows_written if not report.dry_run else report.would_write} vintage(s), "
            f"{report.rows_skipped_invalid} invalid, {report.rows_skipped_ambiguous} ambiguous, "
            f"{report.datasets_skipped_unmapped} unmapped, {report.datasets_skipped_unreadable} unreadable; "
            "indicator_observations untouched",
            file=sys.stderr,
        )

    return 1 if report.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
