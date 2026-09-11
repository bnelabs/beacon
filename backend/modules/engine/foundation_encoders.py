"""Foundation-model encoders for node features.

Two models, one interface, and an important asymmetry
-----------------------------------------------------

The plan calls for frozen time-series foundation models as *node encoders*: take a
node's raw series, produce an embedding, feed that into the temporal graph. Two
models are wired here, and they do not do the same job:

* **MOMENT** is a representation model. It is pre-trained by masked reconstruction
  and its patch embeddings are the intended output, so using it as an encoder is
  using it as designed. It is loaded through plain ``transformers`` rather than the
  ``momentfm`` package, because that package pins ``numpy==1.25.2`` and this
  project runs numpy 2.x -- the pin would silently downgrade the array library and
  break scipy 1.18, which requires numpy>=2.0. MOMENT-1-large is a T5 encoder with
  no custom code in its repository, so nothing is lost by bypassing the wrapper.
* **TimesFM 3.0** is a *forecaster*. It is decoder-only and emits forecast
  horizons; it has no embedding API and its card documents none. Presenting it as
  an "encoder" would be misrepresenting it, so it is wired as what it is -- a
  forecast-feature extractor -- and its output is the forecast path and its
  quantiles, not a learned representation. The class is named accordingly.

Licensing is recorded, not assumed
----------------------------------

Both are surfaced as :class:`EncoderProvenance` and every encoder reports its
licence in ``to_dict()``, because this matters before deployment rather than after:

* MOMENT-1-large is **MIT**.
* timesfm-3.0-pytorch is **non-commercial** (TimesFM Non-Commercial License v1.0).
  The plan's stated goal is MRM validation at a G-SIB or central bank, and a
  non-commercial licence does not permit that. The licence is therefore carried on
  the provenance object and asserted in the tests, so it cannot be forgotten at
  legal review. Choosing to use it is a decision for the operator; the code's job
  is to make the decision visible rather than implicit.

Why the input has two channels
------------------------------

MOMENT applies reversible instance normalisation inside the model, subtracting the
mean and dividing by the standard deviation before the patches are embedded. That
makes it **structurally blind to vertical shifts**: two series at different levels
with the same shape produce identical embeddings. For a systemic-risk signal, whose
whole point is often that a level has moved somewhere it has not been before, that
is a real limitation.

The chosen input therefore carries both channels: raw levels, and fractional
differences from the Phase 2 module. Levels preserve the information the model can
see of its own dynamics; the fractional channel restores the level information
MOMENT's normalisation discards, and does so without the memory loss that integer
differencing would cause. Both are concatenated, and the graph network decides how
much of each to use.

A deterministic local fallback
------------------------------

:class:`HashedFallbackEncoder` needs no weights, is fully deterministic, and is
explicitly marked so that no downstream consumer can mistake it for a pretrained
model. Tests run against it, so the suite is runnable without a 2.7 GB download,
and the real encoders are validated separately when the weights are present.
"""

from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Protocol, Tuple

import numpy as np

logger = logging.getLogger(__name__)

__all__ = [
    "EncoderProvenance",
    "EncoderInput",
    "TimeSeriesEncoder",
    "TotoEncoder",
    "HashedFallbackEncoder",
    "compose_input",
    "build_encoder",
    "available_encoders",
    "resolve_model_dir",
]

TOTO_REPO_DEFAULT = "Datadog/Toto-2.0-313m"
TOTO_LICENSE = "apache-2.0"
TOTO_PATCH_SIZE_DEFAULT = 32
TOTO_EMBED_DIM_DEFAULT = 1024

#: Model folder, resolved from the environment. Defaults to the shared
#: HuggingFace cache so nothing is re-downloaded: every encoder loads with
#: ``local_files_only=True`` and will refuse rather than fetch.
MODEL_DIR_ENV = "BEACON_MODEL_DIR"
HF_HOME_ENV = "HF_HOME"


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
# Toto 2.0
# ---------------------------------------------------------------------------

def resolve_model_dir(explicit: Optional[str] = None) -> Optional[str]:
    """Where to look for model folders.

    Precedence: an explicit argument, then ``BEACON_MODEL_DIR``, then ``HF_HOME``,
    then ``None`` (meaning "use the library default"). Nothing here downloads; the
    encoders always load with ``local_files_only=True`` so a misconfigured path
    raises instead of quietly pulling ten gigabytes.
    """
    if explicit:
        return explicit
    for variable in (MODEL_DIR_ENV, HF_HOME_ENV):
        value = os.environ.get(variable)
        if value:
            return value
    return None


class TotoEncoder:
    """Toto 2.0 as a frozen node encoder.

    Toto 2.0 (Datadog, 2026) is the current state of the art on GIFT-Eval, BOOM and
    TIME, and is Apache-2.0. It is a *forecaster*, like every current leading TSFM
    -- the dedicated representation-model category essentially ended with MOMENT --
    so the embedding is taken from its encoder trunk rather than from a published
    embedding API. That is a real distinction and it is recorded in the provenance
    as ``kind='forecast'``: the number is a hidden state trained to predict, not a
    vector trained to represent.

    Concretely the trunk is captured with a forward hook on ``transformer``, which
    lets the model do its own scaling and patching (``PatchedCausalStdScaler`` then
    ``InputResidualMLP``) instead of this class re-deriving that preprocessing and
    drifting from it. The hidden state is pooled over patch positions and flattened
    across channels.

    Args:
        model_id: Repository id. Swap to ``Datadog/Toto-2.0-2.5B`` for the largest
            checkpoint -- same code path, more weights.
        model_dir: Folder holding the model. Defaults to :func:`resolve_model_dir`.
        device: ``'cuda'``, ``'cpu'`` or ``'auto'``.
        dtype: ``'float32'`` or ``'bfloat16'``. bf16 halves the weights and is the
            right choice on a 24 GB card where attention, not weights, is what
            grows.
        batch_size: Nodes encoded per forward pass.
        context_length: Input width; padded or truncated to a multiple of the
            model's patch size.
    """

    def __init__(
        self,
        model_id: str = TOTO_REPO_DEFAULT,
        model_dir: Optional[str] = None,
        device: str = "auto",
        dtype: str = "float32",
        batch_size: int = 8,
        context_length: int = 512,
    ) -> None:
        import torch

        if batch_size < 1:
            raise ValueError(f"batch_size must be positive, got {batch_size}")
        if context_length < 64:
            raise ValueError(f"context_length must be at least 64, got {context_length}")
        if dtype not in ("float32", "bfloat16", "float16"):
            raise ValueError(f"unsupported dtype {dtype!r}")

        self._torch = torch
        self.model_id = str(model_id)
        self.model_dir = resolve_model_dir(model_dir)
        self.batch_size = int(batch_size)
        self.requested_context = int(context_length)

        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        if device == "cuda" and not torch.cuda.is_available():
            raise RuntimeError(
                "device='cuda' requested but torch reports no CUDA device. The "
                "installed wheel is probably the CPU build "
                f"(torch.version.cuda={torch.version.cuda!r}); install the CUDA "
                "build of the same version."
            )
        self.device = device
        self.dtype_name = dtype

        from toto2 import Toto2Model

        load_kwargs: Dict[str, Any] = {"local_files_only": True}
        if self.model_dir:
            load_kwargs["cache_dir"] = self.model_dir
        try:
            self.model = Toto2Model.from_pretrained(self.model_id, **load_kwargs)
        except Exception as error:
            raise RuntimeError(
                f"could not load {self.model_id} from local files "
                f"(model_dir={self.model_dir!r}): {type(error).__name__}: {error}. "
                "This encoder never downloads; populate the folder first."
            ) from error

        self.model.eval()
        torch_dtype = getattr(torch, dtype)
        self.model.to(device=device, dtype=torch_dtype)
        for parameter in self.model.parameters():
            parameter.requires_grad_(False)

        self.patch_size = int(getattr(self.model.config, "patch_size", TOTO_PATCH_SIZE_DEFAULT))
        self._context = max(
            self.patch_size, (self.requested_context // self.patch_size) * self.patch_size
        )

        # d_model is read off the module rather than the config so the embedding
        # width is right for any checkpoint size without a lookup table.
        self._trunk_dim = self._infer_trunk_dim()
        self._captured: Optional[Any] = None
        self._hook = self.model.transformer.register_forward_hook(self._capture)

    def _infer_trunk_dim(self) -> int:
        """Embedding width, read off the module rather than a size lookup table.

        ``patch_proj`` is an ``InputResidualMLP`` (linear1 -> linear2 with a skip
        projection), not a ``Sequential``, so it cannot be indexed. The width is
        taken from whichever output projection exists, falling back to the config,
        so the same code works for every checkpoint size without hard-coding 1024.
        """
        projection = self.model.patch_proj
        for attribute in ("linear2", "linear", "out"):
            submodule = getattr(projection, attribute, None)
            if submodule is not None and hasattr(submodule, "out_features"):
                return int(submodule.out_features)
        config_width = getattr(self.model.config, "d_model", None)
        if config_width:
            return int(config_width)
        raise RuntimeError(
            "could not infer the trunk width from patch_proj or the config; the "
            "Toto2Model internal layout has changed"
        )

    def _capture(self, module: Any, args: Any, output: Any) -> None:
        self._captured = output

    @property
    def embed_dim(self) -> int:
        # One trunk-width vector per channel, concatenated.
        return self._trunk_dim * 2

    def n_parameters(self) -> int:
        return int(sum(p.numel() for p in self.model.parameters()))

    @property
    def provenance(self) -> EncoderProvenance:
        return EncoderProvenance(
            name=self.model_id.split("/")[-1],
            source=self.model_id,
            licence=TOTO_LICENSE,
            kind="forecast",
            is_pretrained=True,
            is_commercial_use_permitted=True,
            embed_dim=self.embed_dim,
            notes=(
                "Toto 2.0 (Datadog, 2026). Apache-2.0. Forecaster: the embedding is "
                "a pooled encoder hidden state, not a published representation, so "
                "it is trained to predict rather than to be linearly separable. "
                "Loaded from local files only."
            ),
        )

    def _prepare(self, channel: np.ndarray) -> np.ndarray:
        block = np.asarray(channel, dtype=np.float32)
        if block.shape[1] >= self._context:
            return block[:, -self._context :]
        pad = self._context - block.shape[1]
        # Edge padding: the model's own scaler handles level, so replicating the
        # last observation adds a flat run rather than a fake excursion.
        return np.pad(block, ((0, 0), (pad, 0)), mode="edge")

    def encode(self, data: EncoderInput) -> np.ndarray:
        torch = self._torch
        channels = data.channels
        if channels.shape[0] == 0:
            return np.zeros((0, self.embed_dim), dtype=float)

        level = self._prepare(channels[:, 0, :])
        fractional = self._prepare(channels[:, 1, :])
        n_series = level.shape[0]
        embeddings: List[np.ndarray] = []

        torch_dtype = getattr(torch, self.dtype_name)
        with torch.no_grad():
            for start in range(0, n_series, self.batch_size):
                stop = min(start + self.batch_size, n_series)
                size = stop - start
                # Two variates per node: the level channel and the fractional
                # channel travel together so the trunk can relate them.
                target = np.stack(
                    [level[start:stop], fractional[start:stop]], axis=1
                )  # (B, 2, T)
                inputs = {
                    "target": torch.as_tensor(target, dtype=torch_dtype, device=self.device),
                    "target_mask": torch.ones(
                        (size, 2, self._context), dtype=torch.bool, device=self.device
                    ),
                    "series_ids": torch.arange(
                        2, dtype=torch.int64, device=self.device
                    ).reshape(1, 2).expand(size, 2),
                }
                self.model.forecast(inputs, horizon=self.patch_size)
                hidden = self._captured
                if hidden is None:
                    raise RuntimeError(
                        "the transformer hook captured nothing; the Toto2Model "
                        "internal module layout has changed"
                    )
                # (B, n_var, q_len, dim) -> pool patches -> (B, n_var, dim) -> flatten
                pooled = hidden.mean(dim=-2)
                embeddings.append(pooled.reshape(size, -1).float().cpu().numpy())

        return np.concatenate(embeddings, axis=0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "model_id": self.model_id,
            "model_dir": self.model_dir,
            "device": self.device,
            "dtype": self.dtype_name,
            "context_length": self._context,
            "patch_size": self.patch_size,
            "n_parameters": self.n_parameters(),
            "embed_dim": self.embed_dim,
            "provenance": self.provenance.to_dict(),
        }


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
    "toto": (
        TotoEncoder,
        "Toto 2.0 node encoder. Apache-2.0, state of the art on GIFT-Eval/BOOM/TIME.",
    ),
    "fallback": (
        HashedFallbackEncoder,
        "Deterministic stand-in with no pretrained weights.",
    ),
}


def available_encoders() -> Mapping[str, str]:
    """Names of the encoders and a one-line description of each."""
    return {name: description for name, (_, description) in _AVAILABLE.items()}


def build_encoder(kind: str = "toto", **kwargs: Any) -> TimeSeriesEncoder:
    """Construct an encoder by name.

    Falls back to :class:`HashedFallbackEncoder` when pretrained weights cannot be
    loaded AND ``allow_fallback`` is true, logging loudly, because silently
    substituting a stand-in for a foundation model would make every downstream
    result uninterpretable.
    """
    allow_fallback = bool(kwargs.pop("allow_fallback", False))
    key = str(kind).lower()
    if key not in _AVAILABLE:
        raise ValueError(
            f"unknown encoder {kind!r}; available: {sorted(_AVAILABLE)}"
        )

    factory, _description = _AVAILABLE[key]
    try:
        return factory(**kwargs)
    except Exception as error:
        if not allow_fallback:
            raise
        logger.warning(
            "encoder %r unavailable (%s: %s); falling back to the deterministic "
            "stand-in, which is NOT a pretrained model",
            kind,
            type(error).__name__,
            error,
        )
        return HashedFallbackEncoder(
            embed_dim=int(kwargs.get("embed_dim", 64))
            if key == "fallback"
            else 64
        )
