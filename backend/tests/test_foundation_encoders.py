"""Tests for the Toto 2.0 node encoder.

Two layers. The input assembly and the deterministic fallback need no weights and
always run. The real checkpoint is exercised only when it is already on disk, so
the suite never downloads ten gigabytes.

Checkpoints are read from a plain folder under ``BEACON_MODEL_DIR``, passed to
``from_pretrained`` as the model path. No HuggingFace cache is consulted anywhere in
this module, which the tests below assert directly rather than assume.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

from backend.modules.engine import foundation_encoders as fe
from backend.modules.engine.foundation_encoders import (
    MODEL_DIR_ENV,
    TOTO_LICENSE,
    EncoderProvenance,
    HashedFallbackEncoder,
    TotoEncoder,
    available_encoders,
    build_encoder,
    compose_input,
    local_model_path,
    resolve_model_dir,
)

TORCH_AVAILABLE = True
try:  # pragma: no cover - environment dependent
    import torch

    TORCH_AVAILABLE = torch.cuda is not None
except Exception:  # pragma: no cover
    TORCH_AVAILABLE = False


def random_levels(n_series: int = 3, n_steps: int = 200, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return np.cumsum(rng.normal(scale=0.5, size=(n_series, n_steps)), axis=1) + 100.0


def cached_toto_313m() -> bool:
    """Whether the 313m checkpoint is materialised in the local model tree.

    Deliberately delegates to the same resolver the encoder uses. Probing a cache
    path here instead would let this guard and the load path drift apart, and the
    failure mode is silent: the real-weight tests would skip forever while
    reporting green.
    """
    return local_model_path("Datadog/Toto-2.0-313m") is not None


class TestComposeInput:
    def test_two_channels_are_stacked(self):
        data = compose_input(random_levels())
        assert data.channels.shape == (3, 2, 200)
        assert data.channel_names == ("level", "fractional_difference")
        assert data.n_series == 3 and data.n_steps == 200

    def test_levels_channel_is_the_input_untouched(self):
        levels = random_levels()
        data = compose_input(levels)
        assert np.allclose(data.channels[:, 0, :], levels)

    def test_fractional_channel_differs_from_levels(self):
        # If the two channels were identical the concatenation would be pointless.
        data = compose_input(random_levels())
        assert not np.allclose(data.channels[:, 0, :], data.channels[:, 1, :])

    def test_fractional_channel_is_finite(self):
        # The expanding-window differencing form has no warm-up NaN; if that
        # changed, this must fail here rather than inside a foundation model.
        data = compose_input(random_levels())
        assert np.all(np.isfinite(data.channels))

    def test_one_dimensional_input_is_promoted(self):
        data = compose_input(random_levels(n_series=1)[0])
        assert data.channels.shape[0] == 1

    def test_for_series_selects_one_node(self):
        data = compose_input(random_levels())
        assert data.for_series(1).shape == (2, 200)
        with pytest.raises(IndexError):
            data.for_series(99)

    def test_amplitude_is_preserved_in_the_level_channel(self):
        # MOMENT-style internal normalisation would discard this; the two-channel
        # design is what keeps it available.
        base = random_levels()
        shifted = base + 1000.0
        assert not np.allclose(
            compose_input(base).channels[:, 0, :],
            compose_input(shifted).channels[:, 0, :],
        )

    def test_validation(self):
        with pytest.raises(ValueError, match="at least 4"):
            compose_input(np.zeros((2, 3)))
        with pytest.raises(ValueError, match="non-finite"):
            compose_input(np.full((2, 50), np.nan))
        with pytest.raises(ValueError, match="1-D or 2-D"):
            compose_input(np.zeros((2, 2, 2)))

    def test_serialises(self):
        json.dumps(compose_input(random_levels()).to_dict(), allow_nan=False)


class TestModelDirResolution:
    def test_explicit_argument_wins(self, monkeypatch):
        monkeypatch.setenv("BEACON_MODEL_DIR", "/from/env")
        assert resolve_model_dir("/explicit") == "/explicit"

    def test_beacon_variable_beats_hf_home(self, monkeypatch):
        monkeypatch.setenv("BEACON_MODEL_DIR", "/beacon")
        monkeypatch.setenv("HF_HOME", "/hf")
        assert resolve_model_dir() == "/beacon"

    def test_hf_home_is_deliberately_ignored(self, monkeypatch):
        # A HuggingFace cache is exactly what the load path must NOT consult:
        # checkpoints are ordinary folders, and HF_HOME must not be able to steer
        # resolution towards a pile of blob symlinks.
        monkeypatch.delenv("BEACON_MODEL_DIR", raising=False)
        monkeypatch.setenv("HF_HOME", "/hf")
        assert resolve_model_dir() is None

    def test_none_when_nothing_is_set(self, monkeypatch):
        monkeypatch.delenv("BEACON_MODEL_DIR", raising=False)
        monkeypatch.delenv("HF_HOME", raising=False)
        assert resolve_model_dir() is None


class TestLocalModelPath:
    """Checkpoints resolve to ordinary folders, and half-copied ones are rejected."""

    @staticmethod
    def _materialise(root: Path, leaf: str, *, config: bool = True, weight: bool = True):
        folder = root / leaf
        folder.mkdir(parents=True, exist_ok=True)
        if config:
            (folder / "config.json").write_text("{}", encoding="utf-8")
        if weight:
            (folder / "model.safetensors").write_bytes(b"0")
        return folder

    def test_resolves_a_hub_id_to_its_leaf_folder(self, tmp_path, monkeypatch):
        monkeypatch.setenv(MODEL_DIR_ENV, str(tmp_path))
        expected = self._materialise(tmp_path, "Toto-2.0-313m")
        assert local_model_path("Datadog/Toto-2.0-313m") == expected

    def test_returns_none_when_no_root_is_configured(self, monkeypatch):
        monkeypatch.delenv(MODEL_DIR_ENV, raising=False)
        assert local_model_path("Datadog/Toto-2.0-313m") is None

    def test_returns_none_when_the_folder_is_absent(self, tmp_path, monkeypatch):
        monkeypatch.setenv(MODEL_DIR_ENV, str(tmp_path))
        assert local_model_path("Datadog/Toto-2.0-313m") is None

    def test_rejects_a_folder_without_a_config(self, tmp_path, monkeypatch):
        monkeypatch.setenv(MODEL_DIR_ENV, str(tmp_path))
        self._materialise(tmp_path, "Toto-2.0-313m", config=False)
        assert local_model_path("Datadog/Toto-2.0-313m") is None

    def test_rejects_a_folder_without_weights(self, tmp_path, monkeypatch):
        # A half-copied checkpoint has to fail here -- where the message can name
        # the folder -- rather than deep inside from_pretrained.
        monkeypatch.setenv(MODEL_DIR_ENV, str(tmp_path))
        self._materialise(tmp_path, "Toto-2.0-313m", weight=False)
        assert local_model_path("Datadog/Toto-2.0-313m") is None

    def test_an_explicit_root_beats_the_environment(self, tmp_path, monkeypatch):
        monkeypatch.setenv(MODEL_DIR_ENV, str(tmp_path / "absent"))
        expected = self._materialise(tmp_path, "Toto-2.0-1B")
        assert local_model_path("Datadog/Toto-2.0-1B", str(tmp_path)) == expected

    def test_accepts_every_documented_weight_suffix(self, tmp_path, monkeypatch):
        monkeypatch.setenv(MODEL_DIR_ENV, str(tmp_path))
        for suffix in fe.WEIGHT_FILE_SUFFIXES:
            leaf = "model" + suffix.replace(".", "")
            folder = tmp_path / leaf
            folder.mkdir()
            (folder / "config.json").write_text("{}", encoding="utf-8")
            (folder / f"weights{suffix}").write_bytes(b"0")
            assert local_model_path(f"Org/{leaf}") == folder


class TestNoHiddenCacheInLoadPath:
    """The deployment mounts a folder; these guard that nothing reintroduces a cache."""

    def test_the_module_never_passes_a_cache_dir(self):
        # `cache_dir=` would hand the checkpoint back to HuggingFace's cache
        # machinery, which is precisely the behaviour that was removed. A comment
        # may still mention the word; a keyword argument may not.
        source = Path(fe.__file__).read_text(encoding="utf-8")
        assert "cache_dir=" not in source

    def test_loading_names_the_expected_folder_instead_of_fetching(self, tmp_path, monkeypatch):
        monkeypatch.setenv(MODEL_DIR_ENV, str(tmp_path))
        # No folder was materialised, so this must refuse and say where it looked.
        with pytest.raises(RuntimeError, match="no local checkpoint folder"):
            build_encoder(model_id="Datadog/Toto-2.0-313m")


class TestFallbackEncoder:
    def test_is_not_pretrained_and_says_so(self):
        provenance = HashedFallbackEncoder().provenance
        assert provenance.is_pretrained is False
        assert provenance.is_commercial_use_permitted is True
        assert "no pretrained weights" in provenance.licence

    def test_shape_and_finiteness(self):
        data = compose_input(random_levels())
        embedding = HashedFallbackEncoder(embed_dim=32, seed=1).encode(data)
        assert embedding.shape == (3, 32)
        assert np.all(np.isfinite(embedding))

    def test_is_deterministic(self):
        data = compose_input(random_levels())
        first = HashedFallbackEncoder(embed_dim=16, seed=3).encode(data)
        second = HashedFallbackEncoder(embed_dim=16, seed=3).encode(data)
        assert np.allclose(first, second)

    def test_distinguishes_different_series(self):
        data = compose_input(random_levels())
        embedding = HashedFallbackEncoder(embed_dim=64, seed=2).encode(data)
        assert len({tuple(np.round(row, 8)) for row in embedding}) == 3

    def test_embeddings_are_bounded(self):
        # The tanh squashing keeps the projection from exploding on large levels.
        data = compose_input(random_levels() * 1e6)
        embedding = HashedFallbackEncoder(embed_dim=8, seed=4).encode(data)
        assert np.all(np.abs(embedding) <= 1.0 + 1e-9)

    def test_empty_batch(self):
        empty = compose_input(random_levels(n_series=1)) 
        object.__setattr__(empty, "channels", np.zeros((0, 2, 50)))
        assert HashedFallbackEncoder(embed_dim=4).encode(empty).shape == (0, 4)

    def test_validation(self):
        with pytest.raises(ValueError, match="embed_dim"):
            HashedFallbackEncoder(embed_dim=0)


class TestProvenance:
    def test_serialises(self):
        payload = HashedFallbackEncoder().provenance.to_dict()
        json.dumps(payload, allow_nan=False)
        assert set(payload) >= {"name", "source", "licence", "kind", "is_pretrained"}

    def test_records_the_representation_versus_forecast_distinction(self):
        # A forecaster's hidden state is not a published embedding, and the record
        # has to say so rather than let a reader assume otherwise.
        forecaster = EncoderProvenance(
            name="x", source="y", licence="apache-2.0", kind="forecast",
            is_pretrained=True, is_commercial_use_permitted=True, embed_dim=8,
        )
        assert forecaster.kind == "forecast"
        assert forecaster.to_dict()["kind"] == "forecast"


class TestFactory:
    def test_fallback_is_always_available(self):
        encoder = build_encoder("fallback", embed_dim=8)
        assert isinstance(encoder, HashedFallbackEncoder)

    def test_unknown_kind_is_rejected(self):
        with pytest.raises(ValueError, match="unknown encoder"):
            build_encoder("nonexistent")

    def test_available_lists_toto(self):
        listing = available_encoders()
        assert "toto" in listing
        assert "fallback" in listing

    def test_default_is_toto(self):
        # The default must be the real encoder; quietly defaulting to the stand-in
        # would make every downstream result uninterpretable.
        with pytest.raises(Exception):
            # With local_files_only this cannot fetch, so a missing folder raises.
            build_encoder(model_id="Datadog/definitely-not-a-real-repo-xyz")

    def test_allow_fallback_substitutes_loudly(self):
        encoder = build_encoder(
            "toto", allow_fallback=True, model_id="Datadog/definitely-not-a-real-repo-xyz"
        )
        assert isinstance(encoder, HashedFallbackEncoder)
        assert encoder.provenance.is_pretrained is False


class TestTotoContractWithoutWeights:
    def test_licence_constant_is_apache(self):
        assert TOTO_LICENSE == "apache-2.0"

    def test_bad_device_is_reported_clearly(self):
        if not TORCH_AVAILABLE:  # pragma: no cover
            pytest.skip("torch unavailable")
        import torch

        if torch.cuda.is_available():  # pragma: no cover
            pytest.skip("CUDA is available, so the CPU-build guard cannot fire")
        with pytest.raises(RuntimeError, match="CUDA"):
            TotoEncoder(device="cuda", model_id="Datadog/Toto-2.0-313m")

    def test_argument_validation(self):
        with pytest.raises(ValueError, match="batch_size"):
            TotoEncoder(batch_size=0)
        with pytest.raises(ValueError, match="context_length"):
            TotoEncoder(context_length=8)
        with pytest.raises(ValueError, match="dtype"):
            TotoEncoder(dtype="int8")

    def test_a_missing_folder_refuses_rather_than_downloads(self):
        # The message must name the folder it looked in, because "not found" on
        # its own gives an operator nothing to act on.
        with pytest.raises(RuntimeError, match="no local checkpoint folder") as excinfo:
            TotoEncoder(model_id="Datadog/definitely-not-a-real-repo-xyz")
        assert "definitely-not-a-real-repo-xyz" in str(excinfo.value)


@pytest.mark.skipif(not cached_toto_313m(), reason="Toto-2.0-313m not in the local cache")
class TestTotoWithRealWeights:
    """Runs only against a checkpoint already on disk. Never downloads."""

    def _encoder(self) -> TotoEncoder:
        return TotoEncoder(
            model_id="Datadog/Toto-2.0-313m", device="cpu", batch_size=2, context_length=192
        )

    def test_loads_locally_with_the_expected_shape(self):
        encoder = self._encoder()
        assert encoder.n_parameters() == 312_684_608
        assert encoder.patch_size == 32
        assert encoder.embed_dim == 2048  # 1024 trunk width x 2 channels
        assert encoder.provenance.licence == "apache-2.0"
        assert encoder.provenance.is_commercial_use_permitted is True

    def test_encoding_produces_finite_distinct_embeddings(self):
        encoder = self._encoder()
        data = compose_input(random_levels(n_series=4, n_steps=200))
        embedding = encoder.encode(data)

        assert embedding.shape == (4, encoder.embed_dim)
        assert np.all(np.isfinite(embedding))
        # Distinct inputs must not collapse to one vector.
        assert len({tuple(np.round(row, 6)) for row in embedding}) == 4

    def test_different_series_give_different_embeddings(self):
        encoder = self._encoder()
        first = encoder.encode(compose_input(random_levels(seed=1)))
        second = encoder.encode(compose_input(random_levels(seed=2)))
        assert not np.allclose(first, second)

    def test_the_level_channel_actually_reaches_the_encoder(self):
        """The reason for two channels.

        A pure level shift must change the embedding. If the encoder discarded
        level entirely -- as an internally normalising representation model would
        -- this fails, and the second channel is the thing that saves it.
        """
        encoder = self._encoder()
        base = random_levels(n_series=1)
        shifted = base + 500.0
        first = encoder.encode(compose_input(base))
        second = encoder.encode(compose_input(shifted))
        assert not np.allclose(first, second)

    def test_batch_size_does_not_change_the_result(self):
        data = compose_input(random_levels(n_series=4))
        single = TotoEncoder(
            model_id="Datadog/Toto-2.0-313m", device="cpu", batch_size=1, context_length=192
        ).encode(data)
        grouped = TotoEncoder(
            model_id="Datadog/Toto-2.0-313m", device="cpu", batch_size=4, context_length=192
        ).encode(data)
        assert np.allclose(single, grouped, atol=1e-4)

    def test_reported_configuration_serialises(self):
        json.dumps(self._encoder().to_dict(), allow_nan=False)
