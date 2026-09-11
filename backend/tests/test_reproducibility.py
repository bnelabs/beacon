"""Tests for the model reproducibility manifest.

A risk score is only defensible if the artefact that produced it can be traced
to a code revision, a configuration, a data attestation and a dataset snapshot,
and if the weights themselves are hash-verifiable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.modules.engine.reproducibility import (
    MANIFEST_FILENAME,
    MANIFEST_VERSION,
    ModelManifest,
    config_hash,
    git_sha,
    sha256_file,
)

_GIT_ENV_VARS = ("BEACON_GIT_SHA", "GITHUB_SHA", "GIT_COMMIT", "SOURCE_VERSION")


class _FakeAttestation:
    attestation_id = "sha256:attestation"


class _FakeSnapshot:
    snapshot_id = "sha256:snapshot"


def _model(tmp_path: Path, payload: bytes = b"weights", name: str = "best_model.pt") -> Path:
    path = tmp_path / name
    path.write_bytes(payload)
    return path


class TestHashing:
    def test_config_hash_is_order_independent(self):
        assert config_hash({"a": 1, "b": 2}) == config_hash({"b": 2, "a": 1})
        assert config_hash({"a": 1}) != config_hash({"a": 2})
        assert config_hash(None) == config_hash({})

    def test_sha256_file_reflects_the_bytes(self, tmp_path):
        original = _model(tmp_path, b"abc")
        assert sha256_file(original) == sha256_file(original)
        assert sha256_file(_model(tmp_path, b"abd", "other.pt")) != sha256_file(original)

    def test_git_sha_prefers_the_environment(self, monkeypatch):
        monkeypatch.setenv("BEACON_GIT_SHA", "deadbeef")
        assert git_sha() == "deadbeef"

    def test_git_sha_falls_back_to_the_checkout(self, monkeypatch):
        for name in _GIT_ENV_VARS:
            monkeypatch.delenv(name, raising=False)
        resolved = git_sha()
        # A git checkout yields a full sha; a source export yields "unknown".
        assert resolved == "unknown" or len(resolved) == 40


class TestCapture:
    def test_capture_records_full_provenance(self, tmp_path):
        model = _model(tmp_path)
        config = {"epochs": 5, "model": "temporal_attention"}

        manifest = ModelManifest.capture(
            model,
            config,
            job_id="job-1",
            model_type="TEMPORAL_ATTENTION",
            attestation=_FakeAttestation(),
            snapshot=_FakeSnapshot(),
            dataset_row_counts={"FRED": 100},
            training_metrics={"test_rmse": 0.5},
            backtest={"lift": {"persistence": {"rmse": 0.1}}},
            extra={"data_source_job": "data-7"},
        )

        assert manifest.manifest_version == MANIFEST_VERSION
        assert manifest.model_artifact_hash == sha256_file(model)
        assert manifest.config_hash == config_hash(config)
        assert manifest.attestation_id == "sha256:attestation"
        assert manifest.snapshot_id == "sha256:snapshot"
        assert manifest.git_sha
        assert manifest.created_at
        assert manifest.dataset_row_counts == {"FRED": 100}
        assert manifest.backtest["lift"]["persistence"]["rmse"] == 0.1
        assert manifest.extra == {"data_source_job": "data-7"}

    def test_capture_accepts_plain_identifier_strings(self, tmp_path):
        manifest = ModelManifest.capture(
            _model(tmp_path), {}, attestation_id="sha256:a", snapshot_id="sha256:s"
        )
        assert manifest.attestation_id == "sha256:a"
        assert manifest.snapshot_id == "sha256:s"

    def test_capture_without_an_artefact_cannot_be_verified(self, tmp_path):
        manifest = ModelManifest.capture(tmp_path / "missing.pt", {})
        assert manifest.model_artifact_hash is None
        assert manifest.verify() is False

    def test_numpy_values_are_coerced_to_json(self, tmp_path):
        import numpy as np

        manifest = ModelManifest.capture(
            _model(tmp_path), {}, training_metrics={"test_rmse": np.float64(0.25)}
        )
        assert manifest.training_metrics["test_rmse"] == 0.25
        assert manifest.backtest is None


class TestRoundTripAndVerification:
    def test_write_defaults_next_to_the_model_and_round_trips(self, tmp_path):
        model = _model(tmp_path)
        manifest = ModelManifest.capture(model, {"epochs": 1}, job_id="job-1")
        written = Path(manifest.write())

        assert written.name == MANIFEST_FILENAME
        assert written.parent == tmp_path

        restored = ModelManifest.load(model)
        assert restored.to_dict() == manifest.to_dict()
        assert restored.verify() is True

    def test_load_accepts_a_directory_or_the_manifest_path(self, tmp_path):
        model = _model(tmp_path)
        ModelManifest.capture(model, {}).write()

        assert ModelManifest.load(tmp_path).model_path == str(model)
        assert ModelManifest.load(tmp_path / MANIFEST_FILENAME).model_path == str(model)

    def test_load_raises_when_the_manifest_is_absent(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            ModelManifest.load(tmp_path / "nothing.json")

    def test_verify_detects_a_swapped_artefact(self, tmp_path):
        model = _model(tmp_path, b"original")
        manifest = ModelManifest.capture(model, {})
        assert manifest.verify() is True

        model.write_bytes(b"tampered")
        assert manifest.verify() is False

    def test_verify_accepts_an_explicit_artefact_path(self, tmp_path):
        model = _model(tmp_path, b"original")
        manifest = ModelManifest.capture(model, {})

        copy = tmp_path / "copy.pt"
        copy.write_bytes(b"original")
        assert manifest.verify(copy) is True

        stray = tmp_path / "stray.pt"
        stray.write_bytes(b"something else")
        assert manifest.verify(stray) is False

    def test_describe_summarises_the_provenance(self, tmp_path):
        manifest = ModelManifest.capture(_model(tmp_path), {}, attestation_id="sha256:a")
        description = manifest.describe()
        assert "git=" in description
        assert "sha256:a" in description
