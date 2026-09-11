"""Tests for the hardened PyTorch checkpoint loader.

The security-relevant behaviour is that checkpoints which are not
weights-only serialisable are rejected unless an operator explicitly opts in
via ``BEACON_ALLOW_UNSAFE_CHECKPOINT_LOAD``.
"""

from __future__ import annotations

import pytest

from backend.modules.engine import model_io
from backend.modules.engine.model_io import (
    UNSAFE_LOAD_ENV_VAR,
    UnsafeCheckpointError,
    is_unsafe_load_allowed,
    safe_torch_load,
    safe_torch_save,
)


class OpaqueMetadata:
    """Deliberately not representable by the weights-only unpickler."""

    def __init__(self, value: int = 1) -> None:
        self.value = value


def test_unsafe_load_disabled_by_default(monkeypatch):
    monkeypatch.delenv(UNSAFE_LOAD_ENV_VAR, raising=False)
    assert is_unsafe_load_allowed() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_unsafe_load_env_opt_in(monkeypatch, value):
    monkeypatch.setenv(UNSAFE_LOAD_ENV_VAR, value)
    assert is_unsafe_load_allowed() is True


def test_missing_checkpoint_raises_before_loading(tmp_path):
    """A missing file must fail without ever touching the ML stack."""
    with pytest.raises(FileNotFoundError):
        safe_torch_load(tmp_path / "does-not-exist.pt")


def test_unsafe_checkpoint_error_carries_context(tmp_path):
    exc = UnsafeCheckpointError(tmp_path / "model.pt", "not weights-only serialisable")
    assert exc.code == "UNSAFE_CHECKPOINT"
    assert exc.path.endswith("model.pt")
    assert "not weights-only serialisable" in str(exc)


def test_safe_round_trip(tmp_path):
    torch = pytest.importorskip("torch")
    path = tmp_path / "checkpoint.pt"
    payload = {
        "model_state_dict": {"weight": torch.ones(3, 2)},
        "optimizer_state_dict": {"lr": 1e-3, "params": [0, 1]},
        "epoch": 7,
        "config": {"d_model": 128, "dropout": 0.1},
        "sources": ["ECB", "FRED"],
        "source_stats": {"ECB": {"mean": 1.5, "std": 0.25}},
        "nested": {"flags": [True, False, None]},
    }

    safe_torch_save(payload, path)
    assert path.is_file()

    loaded = safe_torch_load(path)
    assert loaded["epoch"] == 7
    assert loaded["sources"] == ["ECB", "FRED"]
    assert loaded["source_stats"]["ECB"]["mean"] == pytest.approx(1.5)
    assert torch.equal(loaded["model_state_dict"]["weight"], torch.ones(3, 2))


def test_save_rejects_non_weights_only_metadata(tmp_path):
    torch = pytest.importorskip("torch")
    path = tmp_path / "unsafe.pt"

    with pytest.raises(UnsafeCheckpointError) as excinfo:
        safe_torch_save({"model_state_dict": {}, "meta": OpaqueMetadata(5)}, path)

    assert "weights-only" in str(excinfo.value)
    assert not path.exists()


def test_load_rejects_legacy_checkpoint_by_default(tmp_path):
    torch = pytest.importorskip("torch")
    path = tmp_path / "legacy.pt"
    torch.save({"model_state_dict": {}, "meta": OpaqueMetadata(5)}, path)

    with pytest.raises(UnsafeCheckpointError):
        safe_torch_load(path, allow_unsafe=False)


def test_load_allows_legacy_checkpoint_with_explicit_opt_in(tmp_path):
    torch = pytest.importorskip("torch")
    path = tmp_path / "legacy.pt"
    torch.save({"model_state_dict": {}, "meta": OpaqueMetadata(5)}, path)

    loaded = safe_torch_load(path, allow_unsafe=True)
    assert loaded["meta"].value == 5


def test_env_var_drives_the_fallback(tmp_path, monkeypatch):
    torch = pytest.importorskip("torch")
    path = tmp_path / "legacy.pt"
    torch.save({"meta": OpaqueMetadata(9)}, path)

    monkeypatch.delenv(UNSAFE_LOAD_ENV_VAR, raising=False)
    with pytest.raises(UnsafeCheckpointError):
        safe_torch_load(path)

    monkeypatch.setenv(UNSAFE_LOAD_ENV_VAR, "1")
    assert safe_torch_load(path)["meta"].value == 9


def test_module_exports_are_stable():
    assert model_io.UNSAFE_LOAD_ENV_VAR == "BEACON_ALLOW_UNSAFE_CHECKPOINT_LOAD"
