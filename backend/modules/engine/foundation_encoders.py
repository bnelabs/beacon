"""Node-feature encoders: the contract, and a deterministic stand-in.

The foundation-model slot is EMPTY on purpose
----------------------------------------------

An earlier version of this module wired **Toto 2.0** (Datadog, Apache-2.0) as
the frozen node encoder, and carried ``toto-2`` plus its dependency train
(einops, gluonts[torch], safetensors, jaxtyping, dd-unit-scaling,
huggingface-hub) in every production image. The encoder was implemented and
tested but constructed only by a developer benchmark script: no production
code path ever embedded a node with it, while every image build paid
gigabytes. The 2026-09 hygiene round removed the Toto wrapper, the weights
resolution machinery and the benchmark script; the decision record lives in
the REMOVED register of ``backend/tests/test_reachability.py``.

What remains is the part worth keeping: the **encoder contract**
(:class:`TimeSeriesEncoder`, :class:`EncoderInput`, :class:`EncoderProvenance`),
the channel composer (:func:`compose_input`), and a deterministic hashed
stand-in used by the phase-integration tests. Re-adding a foundation model
means, in one change: the dependency, the encoder, AND the engine path that
embeds nodes with it -- never the dependency alone again.

Provenance is carried, not implied: an encoder states whether its vectors are
trained embeddings, pooled forecaster hidden states, or a deterministic
stand-in, so no downstream result can quietly misdescribe its features.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Protocol, Tuple

import numpy as np

logger = logging.getLogger(__name__)

__all__ = [
    "EncoderProvenance",
    "EncoderInput",
    "TimeSeriesEncoder",
    "HashedFallbackEncoder",
    "compose_input",
    "build_encoder",
    "available_encoders",
]

# The local model-tree constants that lived here (MODEL_DIR_ENV /
# REQUIRED_MODEL_FILES / WEIGHT_FILE_SUFFIXES, i.e. the BEACON_MODEL_DIR
# convention) described how the deleted Toto wrapper materialised checkpoints.
# They went with it: nothing in the runtime resolves a model directory any
# more, and docker-compose.yml no longer mounts one. A foundation encoder
# returns only in the same change that wires an engine path to it (census
# disposition, backend/tests/test_reachability.py) -- and defines its own
# weight-resolution contract there, in the open, instead of inheriting these.


@dataclass(frozen=True)
class EncoderProvenance:
    """Where an encoder's weights came from and what they may be used for."""

    name: str
    source: str
    licence: str
    kind: str
    """``'representation'`` for a model trained to embed, ``'forecast'`` for one
    trained to predict. The distinction is recorded because calling a forecaster an
    encoder misrepresents what its output means."""

    is_pretrained: bool
    is_commercial_use_permitted: bool
    embed_dim: int
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "licence": self.licence,
            "kind": self.kind,
            "is_pretrained": bool(self.is_pretrained),
            "is_commercial_use_permitted": bool(self.is_commercial_use_permitted),
            "embed_dim": int(self.embed_dim),
            "notes": self.notes,
        }


@dataclass(frozen=True)
class EncoderInput:
    """Levels and fractional differences, aligned and stacked."""

    channels: np.ndarray
    """``(n_series, 2, n_steps)``: channel 0 is level, channel 1 is the fractional
    difference."""

    channel_names: Tuple[str, ...]
    n_dropped_for_warmup: int
    n_series: int
    n_steps: int

    def for_series(self, index: int) -> np.ndarray:
        """``(2, n_steps)`` for one node."""
        if not 0 <= index < self.n_series:
            raise IndexError(f"series {index} is outside a {self.n_series}-series batch")
        return self.channels[index]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "channel_names": list(self.channel_names),
            "n_series": int(self.n_series),
            "n_steps": int(self.n_steps),
            "n_dropped_for_warmup": int(self.n_dropped_for_warmup),
        }


class TimeSeriesEncoder(Protocol):
    """What a node encoder must provide."""

    @property
    def embed_dim(self) -> int:
        ...

    @property
    def provenance(self) -> EncoderProvenance:
        ...

    def encode(self, data: EncoderInput) -> np.ndarray:
        ...


def compose_input(
    levels: np.ndarray,
    *,
    fraction: float = 0.4,
    trim_to_fractional: bool = True,
) -> EncoderInput:
    """Build the two-channel encoder input.

    Args:
        levels: ``(n_series, n_steps)`` of raw values.
        fraction: Fractional differencing order passed to the Phase 2 module.
        trim_to_fractional: When true, the level channel is trimmed to the same
            length as the fractional channel so the two align index-for-index. The
            expanding-window differencing used here has no warm-up NaN, so no rows
            are lost, but the alignment is asserted rather than assumed.

    Returns:
        An :class:`EncoderInput` with both channels finite.
    """
    from backend.modules.data.fractional import frac_diff

    series = np.asarray(levels, dtype=float)
    if series.ndim == 1:
        series = series.reshape(1, -1)
    if series.ndim != 2:
        raise ValueError(f"levels must be 1-D or 2-D, got shape {series.shape}")
    if series.shape[1] < 4:
        raise ValueError(
            f"a series needs at least 4 observations to difference, got {series.shape[1]}"
        )
    if not np.all(np.isfinite(series)):
        # Gaps must be handled explicitly upstream: this module will not impute,
        # because every imputation scheme is a modelling choice that belongs
        # somewhere visible.
        raise ValueError(
            "levels contain non-finite values; fill or mask them explicitly before "
            "encoding rather than letting this layer choose an imputation"
        )

    fractional = np.vstack([frac_diff(row, fraction) for row in series])
    if not np.all(np.isfinite(fractional)):
        # The expanding-window form should have no warm-up holes; if it does, that
        # is a change in the differencing module and it should fail here loudly.
        raise ValueError(
            "fractional differencing produced non-finite values; the expanding-window "
            "form is expected to have no warm-up NaN"
        )

    n_dropped = 0
    level_channel = series
    if trim_to_fractional and fractional.shape[1] != series.shape[1]:
        width = min(fractional.shape[1], series.shape[1])
        n_dropped = int(series.shape[1] - width)
        level_channel = series[:, -width:]
        fractional = fractional[:, -width:]

    channels = np.stack([level_channel, fractional], axis=1)
    return EncoderInput(
        channels=channels,
        channel_names=("level", "fractional_difference"),
        n_dropped_for_warmup=n_dropped,
        n_series=int(channels.shape[0]),
        n_steps=int(channels.shape[2]),
    )


# ---------------------------------------------------------------------------
# Deterministic fallback
# ---------------------------------------------------------------------------

class HashedFallbackEncoder:
    """A deterministic encoder that needs no weights.

    It is not a foundation model and does not pretend to be: it projects a fixed
    set of series statistics through a seeded random matrix. Its purpose is to make
    the pipeline runnable and the test suite independent of a 2.7 GB download, and
    ``provenance.is_pretrained`` is false so nothing downstream can mistake it for
    one.
    """

    def __init__(self, embed_dim: int = 64, seed: int = 0) -> None:
        if embed_dim < 1:
            raise ValueError(f"embed_dim must be positive, got {embed_dim}")
        self._embed_dim = int(embed_dim)
        rng = np.random.default_rng(seed)
        # Summaries per channel: mean, std, min, max, last, slope, and three
        # autocorrelations. Nine is arbitrary but fixed, and documented here.
        self._n_summaries = 9
        self._projection = rng.normal(
            scale=1.0 / math.sqrt(self._n_summaries * 2), size=(self._n_summaries * 2, self._embed_dim)
        )

    @property
    def embed_dim(self) -> int:
        return self._embed_dim

    @property
    def provenance(self) -> EncoderProvenance:
        return EncoderProvenance(
            name="HashedFallbackEncoder",
            source="local",
            licence="n/a (no pretrained weights)",
            kind="representation",
            is_pretrained=False,
            is_commercial_use_permitted=True,
            embed_dim=self._embed_dim,
            notes=(
                "Deterministic stand-in with no pretrained weights. Intended for "
                "tests and offline runs; it is not a foundation model and carries "
                "none of one's transfer learning."
            ),
        )

    @staticmethod
    def _summaries(series: np.ndarray) -> np.ndarray:
        values = np.asarray(series, dtype=float).reshape(-1)
        n = values.size
        scale = values.std() or 1.0
        slope = (
            float(np.polyfit(np.arange(n), values, 1)[0]) if n > 1 else 0.0
        )
        autocorrelations = []
        for lag in (1, 2, 3):
            if n > lag and scale > 0:
                autocorrelations.append(
                    float(np.corrcoef(values[:-lag], values[lag:])[0, 1])
                )
            else:
                autocorrelations.append(0.0)
        return np.asarray(
            [
                values.mean(),
                scale,
                values.min(),
                values.max(),
                values[-1],
                slope,
                *autocorrelations,
            ],
            dtype=float,
        )

    def encode(self, data: EncoderInput) -> np.ndarray:
        channels = data.channels
        if channels.shape[0] == 0:
            return np.zeros((0, self._embed_dim), dtype=float)

        rows = []
        for index in range(channels.shape[0]):
            summaries = np.concatenate(
                [self._summaries(channels[index, c, :]) for c in (0, 1)]
            )
            summaries = np.nan_to_num(summaries, nan=0.0, posinf=0.0, neginf=0.0)
            rows.append(np.tanh(summaries @ self._projection))
        return np.asarray(rows, dtype=float)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_AVAILABLE = {
    "fallback": (
        HashedFallbackEncoder,
        "Deterministic stand-in with no pretrained weights.",
    ),
}


def available_encoders() -> Mapping[str, str]:
    """Names of the encoders and a one-line description of each."""
    return {name: description for name, (_, description) in _AVAILABLE.items()}


def build_encoder(kind: str = "fallback", **kwargs: Any) -> TimeSeriesEncoder:
    """Construct an encoder by name.

    Only the deterministic stand-in exists today (see the module docstring).
    ``allow_fallback`` is retained in the signature for call-site stability
    and is a no-op: there is no pretrained encoder left to fall back from.
    """
    kwargs.pop("allow_fallback", None)
    key = str(kind).lower()
    if key not in _AVAILABLE:
        raise ValueError(
            f"unknown encoder {kind!r}; available: {sorted(_AVAILABLE)}"
        )
    factory, _description = _AVAILABLE[key]
    return factory(**kwargs)
