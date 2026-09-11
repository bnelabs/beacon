"""Tests for content-addressed dataset lineage snapshots.

A quality attestation proves *that* a payload passed the gate. These tests pin
down the second half: the snapshot names the *exact rows* that were verified, so
a verdict can be re-checked (or shown to be irreproducible) months later.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from backend.modules.data.snapshots import (
    SNAPSHOT_MANIFEST_NAME,
    DatasetSnapshot,
    DatasetSnapshotter,
    compute_snapshot_id,
    fingerprint_frame,
    hash_frame,
    sha256_bytes,
    snapshot_root_for,
)


def _frame(rows: int = 8, offset: int = 0) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Date": pd.date_range("2023-01-01", periods=rows, freq="D"),
            "Value": range(offset, offset + rows),
        }
    )


class TestHashing:
    def test_same_content_hashes_equal_and_different_content_does_not(self):
        assert hash_frame(_frame()) == hash_frame(_frame())
        assert hash_frame(_frame()) != hash_frame(_frame(offset=1))

    def test_hash_is_a_prefixed_digest(self):
        digest = hash_frame(_frame())
        assert digest.startswith("sha256:")
        assert len(digest) == len("sha256:") + 64
        assert sha256_bytes(b"abc").startswith("sha256:")

    def test_fingerprint_records_shape_columns_and_dates(self):
        fingerprint = fingerprint_frame("A", _frame(5))

        assert fingerprint.code == "A"
        assert fingerprint.rows == 5
        assert fingerprint.columns == 2
        assert fingerprint.column_names == ("Date", "Value")
        assert fingerprint.first_date.startswith("2023-01-01")
        assert fingerprint.last_date.startswith("2023-01-05")


class TestCapture:
    def test_capture_is_content_addressed(self, tmp_path):
        first = DatasetSnapshotter(tmp_path, format="csv").capture({"A": _frame()}, job_id="job-1")
        second = DatasetSnapshotter(tmp_path, format="csv").capture({"A": _frame()}, job_id="job-1")

        assert first.snapshot_id == second.snapshot_id
        assert first.rows == 8
        assert first.verify() is True

    def test_capture_changes_when_a_single_cell_changes(self, tmp_path):
        base = DatasetSnapshotter(tmp_path, format="csv").capture({"A": _frame()}, job_id="job-1")

        mutated = _frame()
        mutated.loc[0, "Value"] = 999
        changed = DatasetSnapshotter(tmp_path, format="csv").capture({"A": mutated}, job_id="job-1")

        assert base.snapshot_id != changed.snapshot_id

    def test_content_address_does_not_depend_on_persistence(self, tmp_path):
        in_memory = DatasetSnapshotter(tmp_path).capture({"A": _frame()}, job_id="job-1", persist=False)
        persisted = DatasetSnapshotter(tmp_path, format="csv").capture({"A": _frame()}, job_id="job-1")

        assert in_memory.root is None
        assert in_memory.files == {}
        assert in_memory.snapshot_id == persisted.snapshot_id

    def test_persisted_snapshot_round_trips(self, tmp_path):
        snapshotter = DatasetSnapshotter(tmp_path, format="csv")
        snapshot = snapshotter.capture({"A": _frame(), "B": _frame(offset=100)}, job_id="job-1")

        assert snapshot.verify() is True
        manifest_path = Path(snapshot.root) / SNAPSHOT_MANIFEST_NAME
        assert manifest_path.exists()

        loaded = DatasetSnapshotter(tmp_path, format="csv").load(snapshot)
        assert set(loaded) == {"A", "B"}
        np.testing.assert_array_equal(
            loaded["A"]["Value"].to_numpy(), _frame()["Value"].to_numpy()
        )

        manifest = snapshotter.load_manifest(snapshot.snapshot_id)
        assert manifest is not None
        assert manifest.snapshot_id == snapshot.snapshot_id

    def test_verify_detects_live_and_on_disk_tampering(self, tmp_path):
        snapshotter = DatasetSnapshotter(tmp_path, format="csv")
        snapshot = snapshotter.capture({"A": _frame()}, job_id="job-1")

        assert snapshot.verify({"A": _frame()}) is True
        assert snapshot.verify({"A": _frame(offset=1)}) is False

        stored = Path(snapshot.files["A"])
        stored.write_text(stored.read_text(encoding="utf-8").replace("0", "7"), encoding="utf-8")
        assert snapshotter.verify(snapshot) is False

    def test_snapshot_id_covers_the_fingerprint(self, tmp_path):
        snapshot = DatasetSnapshotter(tmp_path).capture({"A": _frame()}, job_id="job-1", persist=False)
        assert snapshot.snapshot_id == compute_snapshot_id(snapshot)

        forged = DatasetSnapshot(
            snapshot_id=snapshot.snapshot_id,
            job_id=snapshot.job_id,
            created_at=snapshot.created_at,
            rows=snapshot.rows + 1,
            columns=snapshot.columns,
            datasets=snapshot.datasets,
        )
        assert forged.verify() is False

    def test_manifest_json_round_trips(self, tmp_path):
        snapshot = DatasetSnapshotter(tmp_path, format="csv").capture({"A": _frame()}, job_id="job-1")
        decoded = DatasetSnapshot.from_dict(json.loads(json.dumps(snapshot.to_dict())))
        assert decoded.snapshot_id == snapshot.snapshot_id
        assert decoded.datasets == snapshot.datasets

    def test_snapshot_root_defaults_below_the_output_dir(self):
        assert snapshot_root_for("/data/jobs/7") == "/data/jobs/7/snapshots"
        assert snapshot_root_for("/data/jobs/7", "/mnt/lineage") == "/mnt/lineage"

    def test_snapshot_without_persistence_cannot_be_loaded(self, tmp_path):
        snapshot = DatasetSnapshotter(tmp_path).capture({"A": _frame()}, job_id="job-1", persist=False)
        with pytest.raises(ValueError):
            DatasetSnapshotter(tmp_path).load(snapshot)
