"""Backfilling the vintage log from certified snapshots, idempotently.

``indicator_vintage_log`` is the audit half of the point-in-time contract, and
``observations_as_of`` is its reader. Both existed before this change with one
weakness each: the writer stamps ``published_at`` with the instant *this
deployment wrote the row*, and the certified data itself is filed elsewhere --
``DatasetSnapshotter`` writes a content-addressed directory per certification
(``<snapshot_id>/snapshot.json`` plus one parquet per dataset), and nothing read
those directories back. So a deployment that had been collecting for months
could answer "what did you know on 3 March" only with the rows it happened to
write since the log existed, while the certified payload that proves what it
knew on 3 March sat unqueried on disk.

This module is the bridge, and the rules it obeys are the ones the rest of the
pipeline already states:

* A backfilled vintage's publication instant is the **certified snapshot's**
  ``created_at``, not ``now()``. Stamping the write instant on historical data
  is the look-ahead lie in reverse: it makes the series unqueryable for every
  instant before today and presents that as history.
* A snapshot whose persisted frames do not match its own content address is
  never applied. Half-applying an unverified payload would put uncertified
  numbers in the table whose entire purpose is attestation.
* Re-applying is a no-op that is *reported*, not a silent zero: "already
  applied" and "nothing to do" are different answers, and an operator deciding
  whether the backfill finished has to tell them apart.
* A dataset that is not one scalar series is skipped and counted. Collapsing a
  panel into (period, source, indicator) drops entity identities silently --
  the same reason ``persist_observations`` refuses panel rows.
* Rows with no parseable date or no finite value are counted, never written as
  zero, and a code that no configured source publishes is skipped rather than
  written under an invented publisher.

The manifest's ``created_at`` is rewritten in these tests. That is legitimate
rather than a cheat: ``created_at`` is deliberately excluded from the snapshot
fingerprint (``DatasetSnapshot.fingerprint``), so the content address -- which
*is* the directory name -- does not depend on when the capture happened, and
``verify()`` still passes. It is also the only way to exercise as-of semantics
against a vintage that is not "one second ago".
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.database import Base
from backend.models.timeseries import (
    IndicatorObservation,
    IndicatorVintageLog,
    VintageBackfillRun,
)
from backend.modules.data.snapshots import SNAPSHOT_MANIFEST_NAME, DatasetSnapshotter
from backend.modules.results.timeseries_store import TimeSeriesStore
from backend.modules.results.vintage_backfill import VintageBackfiller

PUBLISHED_AT = datetime(2026, 3, 3, 9, 0, tzinfo=timezone.utc)
CODE = "LIQ_RATIO"
PUBLISHERS = {CODE: ("imf", "GLOBAL")}

_TABLES = [
    IndicatorObservation.__table__,
    IndicatorVintageLog.__table__,
    VintageBackfillRun.__table__,
]


@pytest.fixture()
def session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine, tables=_TABLES)
    factory = sessionmaker(bind=engine)
    db = factory()
    try:
        yield db
    finally:
        db.close()
        engine.dispose()


def _observations_frame(dates, values, **extra):
    # `errors="coerce"` on purpose: two tests hand this helper a deliberate
    # "not-a-date", and the row has to reach the module under test -- a fixture
    # that rejects it tests the fixture instead of the backfill's counting.
    payload = {"Date": pd.to_datetime(dates, errors="coerce"), "Value": list(values)}
    payload.update(extra)
    return pd.DataFrame(payload)


def _certify(root: Path, frame: pd.DataFrame, *, code: str = CODE, job_id: str = "job_snap_1"):
    """Capture a snapshot the way the orchestrator does, then age its manifest."""
    snapshotter = DatasetSnapshotter(root / "snapshots")
    snapshot = snapshotter.capture({code: frame}, job_id=job_id)

    manifest_path = snapshotter.snapshot_dir(snapshot.snapshot_id) / SNAPSHOT_MANIFEST_NAME
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["created_at"] = PUBLISHED_AT.isoformat()
    manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return snapshot.snapshot_id


def _vintages(session, **filters):
    query = session.query(IndicatorVintageLog)
    for column, value in filters.items():
        query = query.filter(getattr(IndicatorVintageLog, column) == value)
    return query.order_by(IndicatorVintageLog.time, IndicatorVintageLog.published_at).all()


class TestTheCertifiedInstantIsThePublicationInstant:
    def test_a_backfilled_vintage_is_published_at_the_snapshot_instant(self, session, tmp_path):
        snapshot_id = _certify(
            tmp_path, _observations_frame(["2026-01-31", "2026-02-28"], [100.0, 101.0])
        )
        report = VintageBackfiller(session, tmp_path, PUBLISHERS).run()

        assert report.snapshots_found == 1
        assert report.snapshots_applied == 1
        assert report.rows_written == 2

        vintages = _vintages(session)
        assert [row.value for row in vintages] == [100.0, 101.0]
        assert all(row.published_at == PUBLISHED_AT for row in vintages), (
            "a backfilled vintage must carry the certified snapshot's instant; "
            "stamping now() would make the series unqueryable at every earlier "
            "as-of and hide the backfill's own history"
        )
        assert all(row.snapshot_id == snapshot_id for row in vintages)
        assert all(row.publication_basis == "certified_snapshot" for row in vintages)
        assert all(row.ingest_job_id == "job_snap_1" for row in vintages)

    def test_as_of_sees_the_series_only_from_the_certified_instant_onward(self, session, tmp_path):
        _certify(tmp_path, _observations_frame(["2026-01-31"], [100.0]))
        VintageBackfiller(session, tmp_path, PUBLISHERS).run()
        store = TimeSeriesStore(session)

        assert (
            store.observations_as_of("imf", CODE, PUBLISHED_AT - timedelta(microseconds=1))
            == []
        )
        assert [row.value for row in store.observations_as_of("imf", CODE, PUBLISHED_AT)] == [100.0]

    def test_a_later_live_restatement_outranks_the_backfilled_vintage(self, session, tmp_path):
        _certify(tmp_path, _observations_frame(["2026-01-31"], [100.0]))
        VintageBackfiller(session, tmp_path, PUBLISHERS).run()
        store = TimeSeriesStore(session)

        store.record_observations(
            [
                {
                    "time": datetime(2026, 1, 31, tzinfo=timezone.utc),
                    "source_code": "imf",
                    "indicator_code": CODE,
                    "region": "GLOBAL",
                    "value": 95.0,
                    "ingest_job_id": "job_live",
                }
            ]
        )

        assert [row.value for row in store.observations_as_of("imf", CODE, PUBLISHED_AT)] == [100.0]
        assert [
            row.value for row in store.observations_as_of("imf", CODE, datetime.now(timezone.utc))
        ] == [95.0]

        live = _vintages(session, ingest_job_id="job_live")
        assert live[0].publication_basis == "ingest_instant", (
            "a live write publishes at the ingest instant; the backfill must not "
            "claim that instant is a certification instant"
        )
        assert live[0].snapshot_id is None


class TestReApplicationIsANoOpThatSaysSo:
    def test_the_second_run_writes_nothing_and_says_why(self, session, tmp_path):
        snapshot_id = _certify(
            tmp_path, _observations_frame(["2026-01-31", "2026-02-28"], [100.0, 101.0])
        )
        first = VintageBackfiller(session, tmp_path, PUBLISHERS).run()
        second = VintageBackfiller(session, tmp_path, PUBLISHERS).run()

        assert first.rows_written == 2
        assert second.rows_written == 0
        assert second.snapshots_applied == 0
        assert second.snapshots_skipped == 1
        assert [entry["snapshot_id"] for entry in second.skipped] == [snapshot_id]
        assert second.skipped[0]["reason"] == "already applied"
        assert session.query(IndicatorVintageLog).count() == 2, (
            "a re-run duplicated vintages: the append-only log would then "
            "over-report its own history"
        )

    def test_an_emptily_applied_snapshot_is_still_marked_applied(self, session, tmp_path):
        # Nothing in this snapshot is publishable as a scalar indicator, yet the
        # application is a fact. Without recording it, every later run re-reads
        # the same empty snapshot forever and the operator never learns that the
        # backfill is finished.
        _certify(tmp_path, _observations_frame(["2026-01-31"], [100.0]))
        first = VintageBackfiller(session, tmp_path, {}).run()
        assert first.snapshots_applied == 1
        assert first.rows_written == 0

        second = VintageBackfiller(session, tmp_path, {}).run()
        assert second.snapshots_applied == 0
        assert second.snapshots_skipped == 1

    def test_a_dry_run_reports_without_writing(self, session, tmp_path):
        _certify(tmp_path, _observations_frame(["2026-01-31"], [100.0]))
        report = VintageBackfiller(session, tmp_path, PUBLISHERS, dry_run=True).run()

        assert report.dry_run is True
        assert report.rows_written == 0
        assert report.would_write == 1
        assert session.query(IndicatorVintageLog).count() == 0
        assert session.query(VintageBackfillRun).count() == 0

    def test_one_unapplied_snapshot_does_not_stop_the_others(self, session, tmp_path):
        _certify(tmp_path / "job_1", _observations_frame(["2026-01-31"], [100.0]))
        _certify(tmp_path / "job_2", _observations_frame(["2026-02-28"], [200.0]), job_id="job_2")

        report = VintageBackfiller(session, tmp_path, PUBLISHERS).run()
        assert report.snapshots_applied == 2
        assert report.rows_written == 2
        assert sorted(row.ingest_job_id for row in _vintages(session)) == ["job_2", "job_snap_1"]


class TestUnverifiedPayloadsAreNeverApplied:
    def test_a_frame_that_does_not_match_its_snapshot_id_is_refused(self, session, tmp_path):
        snapshot_id = _certify(
            tmp_path, _observations_frame(["2026-01-31", "2026-02-28"], [100.0, 101.0])
        )
        directory = DatasetSnapshotter(tmp_path / "snapshots").snapshot_dir(snapshot_id)
        pd.DataFrame({"Date": pd.to_datetime(["2026-01-31"]), "Value": [999.0]}).to_parquet(
            directory / f"{CODE}.parquet"
        )

        report = VintageBackfiller(session, tmp_path, PUBLISHERS).run()

        assert report.rows_written == 0
        assert report.snapshots_applied == 0
        assert report.verification_failures == 1
        assert report.failed[0]["snapshot_id"] == snapshot_id
        assert session.query(IndicatorVintageLog).count() == 0
        assert session.query(VintageBackfillRun).count() == 0, (
            "an unverified snapshot was recorded as applied; the ledger would "
            "then claim coverage it never produced"
        )

    def test_a_manifest_that_disagrees_with_its_own_directory_name_is_reported(self, session, tmp_path):
        snapshot_id = _certify(tmp_path, _observations_frame(["2026-01-31"], [100.0]))
        manifest_path = (
            DatasetSnapshotter(tmp_path / "snapshots").snapshot_dir(snapshot_id)
            / SNAPSHOT_MANIFEST_NAME
        )
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        payload["snapshot_id"] = "sha256:" + "0" * 64
        manifest_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

        report = VintageBackfiller(session, tmp_path, PUBLISHERS).run()

        assert report.rows_written == 0
        assert report.verification_failures == 1
        assert session.query(IndicatorVintageLog).count() == 0


class TestWhatIsSkippedIsCounted:
    def test_a_dataset_that_is_not_one_scalar_series_is_skipped_not_collapsed(self, session, tmp_path):
        # Two entities reporting the same period: writing both under
        # (period, imf, LIQ_RATIO) would keep one entity's number and lose the
        # other without saying which.
        frame = _observations_frame(
            ["2026-01-31", "2026-01-31", "2026-02-28"],
            [100.0, 250.0, 101.0],
            entity_id=["ENT_ALPHA", "ENT_BETA", "ENT_ALPHA"],
        )
        _certify(tmp_path, frame)

        report = VintageBackfiller(session, tmp_path, PUBLISHERS).run()

        assert report.rows_written == 0
        assert report.rows_skipped_ambiguous == 3
        assert session.query(IndicatorVintageLog).count() == 0

    def test_rows_without_a_date_or_a_finite_value_are_counted_not_fabricated(self, session, tmp_path):
        frame = _observations_frame(["2026-01-31", "not-a-date", "2026-03-31"], [100.0, np.nan, np.inf])
        _certify(tmp_path, frame)

        report = VintageBackfiller(session, tmp_path, PUBLISHERS).run()

        assert report.rows_written == 1
        assert report.rows_skipped_invalid == 2
        assert [row.value for row in _vintages(session)] == [100.0]

    def test_a_code_no_configured_source_publishes_is_skipped(self, session, tmp_path):
        _certify(tmp_path, _observations_frame(["2026-01-31"], [100.0]))
        report = VintageBackfiller(session, tmp_path, {"OTHER_CODE": ("imf", "GLOBAL")}).run()

        assert report.rows_written == 0
        assert report.datasets_skipped_unmapped == 1
        assert report.unmapped[0]["code"] == CODE
        assert session.query(IndicatorVintageLog).count() == 0

    def test_the_counts_add_up_across_a_mixed_snapshot(self, session, tmp_path):
        frame = _observations_frame(
            ["2026-01-31", "2026-01-31", "not-a-date"], [100.0, 250.0, 7.0]
        )
        _certify(tmp_path, frame)

        report = VintageBackfiller(session, tmp_path, PUBLISHERS).run()

        assert report.rows_seen == 3
        assert report.rows_written + report.rows_skipped_invalid + report.rows_skipped_ambiguous == 3


class TestWhatTheBackfillLooksAt:
    def test_snapshots_are_found_recursively_under_the_given_root(self, tmp_path):
        # A deployment files snapshots per job output directory, not in one flat
        # tree, so a backfill that reads only one level finds nothing.
        _certify(tmp_path / "jobs" / "job_1" / "output", _observations_frame(["2026-01-31"], [100.0]))
        _certify(tmp_path / "jobs" / "job_2" / "output", _observations_frame(["2026-02-28"], [200.0]))

        found = VintageBackfiller.discover(tmp_path)
        assert len(found) == 2
        assert all(manifest_path.name == SNAPSHOT_MANIFEST_NAME for _, manifest_path in found)

    def test_a_directory_without_a_manifest_is_not_treated_as_a_snapshot(self, session, tmp_path):
        stray = tmp_path / "snapshots" / "deadbeef"
        stray.mkdir(parents=True)
        (stray / "orphan.parquet").write_bytes(b"not a snapshot")

        assert VintageBackfiller.discover(tmp_path) == []
        report = VintageBackfiller(session, tmp_path, PUBLISHERS).run()
        assert report.snapshots_found == 0
        assert session.query(IndicatorVintageLog).count() == 0

    def test_the_report_is_a_dict_an_operator_can_read_directly(self, session, tmp_path):
        _certify(tmp_path, _observations_frame(["2026-01-31"], [100.0]))
        report = VintageBackfiller(session, tmp_path, PUBLISHERS).run()
        payload = report.to_dict()

        assert payload["snapshots_applied"] == 1
        assert payload["rows_written"] == 1
        assert payload["publication_basis"] == "certified_snapshot"
        assert payload["applied"][0]["created_at"] == PUBLISHED_AT.isoformat()
