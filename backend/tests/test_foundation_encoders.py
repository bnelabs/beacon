"""Tests for the node-feature encoder contract and its deterministic stand-in.

The Toto 2.0 wrapper, its weights-resolution machinery and the developer
benchmark script were removed in the 2026-09 hygiene round (see the module
docstring and the REMOVED register in ``test_reachability.py``): the encoder
was never constructed by a production path while every image paid for its
dependency train. What is tested here is what survived -- the channel
composer, the hashed stand-in, the provenance contract and the factory --
because the phase-integration test composes the stand-in into the
regime -> mixture-of-experts -> conformal chain.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.modules.engine.foundation_encoders import (
    EncoderInput,
    HashedFallbackEncoder,
    available_encoders,
    build_encoder,
    compose_input,
)


def _panel(rows: int = 64, cols: int = 3) -> np.ndarray:
    rng = np.random.default_rng(7)
    return rng.normal(100.0, 5.0, size=(cols, rows))


class TestComposeInput:
    def test_two_channels_are_stacked(self):
        data = compose_input(_panel())
        assert data.channel_names == ("level", "fractional_difference")
        assert data.channels.shape[1] == 2

    def test_levels_channel_is_the_input_untouched(self):
        panel = _panel()
        data = compose_input(panel)
        assert np.allclose(data.channels[:, 0, :], panel)

    def test_fractional_channel_differs_from_levels(self):
        data = compose_input(_panel())
        assert not np.allclose(data.channels[:, 0, :], data.channels[:, 1, :])

    def test_fractional_channel_is_finite(self):
        data = compose_input(_panel())
        assert np.all(np.isfinite(data.channels[:, 1, :]))

    def test_one_dimensional_input_is_promoted(self):
        data = compose_input(np.arange(32, dtype=float))
        assert data.n_series == 1

    def test_for_series_selects_one_node(self):
        data = compose_input(_panel())
        one = data.for_series(1)
        assert one.shape == (2, data.n_steps)

    def test_for_series_out_of_range_raises(self):
        data = compose_input(_panel())
        with pytest.raises(IndexError):
            data.for_series(data.n_series)

    def test_amplitude_is_preserved_in_the_level_channel(self):
        panel = _panel()
        shifted = panel + 500.0
        assert np.allclose(compose_input(shifted).channels[:, 0, :], shifted)

    def test_too_short_a_series_is_rejected(self):
        with pytest.raises(ValueError):
            compose_input(np.zeros((1, 3)))

    def test_serialises(self):
        payload = compose_input(_panel()).to_dict()
        assert payload["channel_names"] == ["level", "fractional_difference"]
        assert payload["n_series"] == 3


class TestFallbackEncoder:
    def test_embeds_every_node_with_a_finite_vector(self):
        encoder = HashedFallbackEncoder(embed_dim=24)
        rows = np.asarray(encoder.encode(compose_input(_panel())))
        assert rows.shape == (3, 24)
        assert np.all(np.isfinite(rows))

    def test_deterministic_across_instances(self):
        data = compose_input(_panel())
        a = HashedFallbackEncoder(embed_dim=16).encode(data)
        b = HashedFallbackEncoder(embed_dim=16).encode(data)
        assert np.allclose(a, b)

    def test_provenance_says_stand_in_not_model(self):
        provenance = HashedFallbackEncoder(embed_dim=8).provenance
        assert provenance.is_pretrained is False
        assert provenance.embed_dim == 8

    def test_embed_dim_is_validated(self):
        with pytest.raises(ValueError):
            HashedFallbackEncoder(embed_dim=0)


class TestFactory:
    def test_only_the_stand_in_is_available(self):
        assert set(available_encoders()) == {"fallback"}

    def test_default_build_is_the_stand_in(self):
        encoder = build_encoder()
        assert isinstance(encoder, HashedFallbackEncoder)

    def test_unknown_kind_raises(self):
        with pytest.raises(ValueError, match="unknown encoder"):
            build_encoder("nonexistent-model")

    def test_input_contract_is_what_encoders_consume(self):
        data: EncoderInput = compose_input(_panel())
        encoder = build_encoder(embed_dim=12)
        assert np.asarray(encoder.encode(data)).shape == (3, 12)
