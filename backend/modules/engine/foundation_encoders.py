"""Foundation-model encoders for node features.

One encoder, one honest caveat, and a deterministic stand-in
------------------------------------------------------------

The plan calls for a frozen time-series foundation model as a *node encoder*: take
a node's raw series, produce an embedding, feed that into the temporal graph.

* **Toto 2.0** (Datadog, 2026) is what is wired here. It is Apache-2.0 and
  currently leads GIFT-Eval, BOOM and TIME. It is a *forecaster*: like every
  leading time-series foundation model now, it publishes no embedding API, so the
  node embedding is a pooled encoder-trunk hidden state rather than a vector
  trained to be linearly separable. That distinction is carried on the provenance
  as ``kind='forecast'`` rather than quietly glossed over.

  Two earlier candidates were removed rather than kept: MOMENT-1-large, which this
  plan originally named and which is now superseded, and TimesFM 3.0, which is
  **non-commercial** and so cannot serve the stated goal of MRM validation at a
  G-SIB or central bank. Neither is referenced by this module or its tests.

Weights are read from an explicit local folder
----------------------------------------------

Nothing here downloads. :func:`local_model_path` resolves each checkpoint to a
plain directory under ``BEACON_MODEL_DIR`` and the model is loaded from that path
directly, so there is no hidden cache anywhere in the load path and a misconfigured
folder raises instead of quietly pulling gigabytes. Materialising checkpoints as
ordinary folders -- rather than pointing at a HuggingFace cache -- is deliberate:
an operator can see, copy, mount and audit a folder, and a container can
bind-mount it read-only.

Licence is recorded, not assumed
--------------------------------

Every encoder surfaces an :class:`EncoderProvenance` carrying its licence and
whether commercial use is permitted, because that matters before deployment rather
than after. Toto 2.0 is Apache-2.0.

Why the input has two channels
------------------------------

Toto applies its own normalisation inside the model (``PatchedCausalStdScaler``),
subtracting the mean and dividing by the standard deviation before patches are
embedded. That makes it **structurally blind to vertical shifts**: two series at
different levels with the same shape produce identical embeddings. For a
systemic-risk signal, whose whole point is often that a level has moved somewhere
it has not been before, that is a real limitation.

The chosen input therefore carries both channels: raw levels, and fractional
differences from the Phase 2 module. Levels preserve the information the model can
see of its own dynamics; the fractional channel restores the level information the
scaler discards, and does so without the memory loss that integer differencing
would cause. Both are concatenated, and the graph network decides how much of each
to use.

A deterministic local fallback
------------------------------

:class:`HashedFallbackEncoder` needs no weights, is fully deterministic, and is
explicitly marked so that no downstream consumer can mistake it for a pretrained
model. Tests run against it, so the suite is runnable without a multi-gigabyte
weight download, and the real encoders are validated separately when the weights
are present.
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
    "TotoEncoder",
    "HashedFallbackEncoder",
    "compose_input",
    "build_encoder",
    "available_encoders",
    "resolve_model_dir",
    "local_model_path",
]

TOTO_REPO_DEFAULT = "Datadog/Toto-2.0-313m"
TOTO_LICENSE = "apache-2.0"
TOTO_PATCH_SIZE_DEFAULT = 32
TOTO_EMBED_DIM_DEFAULT = 1024

#: Root of the local model tree, resolved from the environment. Each checkpoint
#: lives in a plain folder beneath it (``<root>/Toto-2.0-313m/``), never in a
#: HuggingFace cache: the load path passes the folder itself to
#: ``from_pretrained`` and never a ``cache_dir``, so there is no cache to populate
#: and nothing can be fetched.
MODEL_DIR_ENV = "BEACON_MODEL_DIR"

#: Files a folder must contain before it is treated as a materialised checkpoint.
REQUIRED_MODEL_FILES = ("config.json",)

#: Suffixes accepted as a weight file when materialising a checkpoint.
WEIGHT_FILE_SUFFIXES = (".safetensors", ".bin", ".pt", ".pth")


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
    """Root of the local model tree.

    Precedence: an explicit argument, then ``BEACON_MODEL_DIR``, then ``None``.

    ``HF_HOME`` is deliberately **not** consulted. Pointing the load path at a
    HuggingFace cache makes a checkpoint a pile of symlinks into ``blobs`` that an
    operator cannot see, copy or mount as a unit, and it leaves in place a code
    path capable of populating that cache. Weights live in an ordinary folder.

    Nothing here downloads: a missing root simply yields ``None`` and the caller
    raises rather than falling back to the network.
    """
    if explicit:
        return explicit
    value = os.environ.get(MODEL_DIR_ENV)
    if value:
        return value
    return None


def _model_leaf(model_id: str) -> str:
    """Folder name a Hub-style id materialises to (``a/b`` -> ``b``)."""
    return str(model_id).strip().rstrip("/").split("/")[-1]


def _expected_model_path(model_id: str, root: Optional[str]) -> str:
    """The path a missing checkpoint was looked for at, for error messages."""
    leaf = _model_leaf(model_id)
    if not root:
        return f"<{MODEL_DIR_ENV} unset>/{leaf}"
    return str(Path(root).expanduser() / leaf)


def local_model_path(model_id: str, root: Optional[str] = None) -> Optional[Path]:
    """Materialised checkpoint folder for ``model_id``, or ``None``.

    ``model_id`` is a Hub-style id (``"Datadog/Toto-2.0-313m"``) and the folder is
    its leaf name beneath ``root`` (``<root>/Toto-2.0-313m``). A folder qualifies
    only when it holds every file in :data:`REQUIRED_MODEL_FILES` and at least one
    weight file, so a half-copied directory fails here -- where the message can
    name the folder -- rather than inside ``from_pretrained``.

    Returns ``None`` when no root is configured, or the folder is absent or
    incomplete. Absence is not treated as a fault here because this function is
    also the way to ask whether a checkpoint is present at all.
    """
    resolved_root = resolve_model_dir(root)
    if not resolved_root:
        return None
    leaf = _model_leaf(model_id)
    if not leaf:
        return None
    candidate = Path(resolved_root).expanduser() / leaf
    if not candidate.is_dir():
        return None
    if not all((candidate / name).is_file() for name in REQUIRED_MODEL_FILES):
        return None
    if not any(
        entry.is_file() and entry.suffix in WEIGHT_FILE_SUFFIXES
        for entry in candidate.iterdir()
    ):
        return None
    return candidate


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

        self.local_path = local_model_path(self.model_id, self.model_dir)
        if self.local_path is None:
            raise RuntimeError(
                f"no local checkpoint folder for {self.model_id!r} under "
                f"model_dir={self.model_dir!r}. Expected a directory holding "
                f"{' and '.join(REQUIRED_MODEL_FILES)} plus a weight file, at "
                f"{_expected_model_path(self.model_id, self.model_dir)}. This "
                "encoder never downloads and never reads a HuggingFace cache, so "
                "the checkpoint must be materialised as a plain folder first (see "
                "docs/deployment.md) or " + MODEL_DIR_ENV + " must point at the "
                "tree that holds it."
            )
        try:
            # The folder is handed over as the *model path*, never as a
            # cache_dir: transformers loads these files in place, so there is no
            # cache to consult and no cache to populate.
            self.model = Toto2Model.from_pretrained(
                str(self.local_path), local_files_only=True
            )
        except Exception as error:
            raise RuntimeError(
                f"could not load {self.model_id} from {self.local_path}: "
                f"{type(error).__name__}: {error}. This encoder never downloads; "
                "the folder above is incomplete or corrupt."
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
