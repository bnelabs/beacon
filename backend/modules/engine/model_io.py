"""Hardened loading and saving of PyTorch checkpoints.

``torch.load`` reconstructs arbitrary Python objects through the pickle
protocol, so a checkpoint downloaded from a model registry, uploaded by a
user, or shared between teams can execute code at deserialisation time. A
BEACON checkpoint only ever needs tensors plus plain metadata, so every load
goes through :func:`safe_torch_load`, which restricts the unpickler to that
subset via ``weights_only=True``.

Artifacts that predate this hardening (or third-party checkpoints) can still
contain richer Python objects. Loading those requires an explicit operator
opt-in through the ``BEACON_ALLOW_UNSAFE_CHECKPOINT_LOAD`` environment
variable; the fallback is recorded as a security event rather than applied
silently.
"""

from __future__ import annotations

import io
import logging
import os
from pathlib import Path
from typing import Any, Mapping, Optional

logger = logging.getLogger(__name__)

UNSAFE_LOAD_ENV_VAR = "BEACON_ALLOW_UNSAFE_CHECKPOINT_LOAD"

_TRUTHY = {"1", "true", "yes", "on"}


class UnsafeCheckpointError(RuntimeError):
    """Raised when a checkpoint cannot be loaded under the safe unpickler.

    Attributes:
        path: Location of the rejected checkpoint.
        reason: Human-readable explanation of why it was rejected.
    """

    code = "UNSAFE_CHECKPOINT"

    def __init__(self, path: Any, reason: str):
        self.path = str(path)
        self.reason = reason
        super().__init__(f"Refusing to load checkpoint '{self.path}': {reason}")


def is_unsafe_load_allowed() -> bool:
    """Return whether the operator has opted into legacy unsafe checkpoint loads."""
    return os.getenv(UNSAFE_LOAD_ENV_VAR, "").strip().lower() in _TRUTHY


def _require_torch():
    """Import torch lazily so this module stays importable without the ML stack."""
    try:
        import torch  # noqa: WPS433 - deliberate lazy import
    except ImportError as exc:  # pragma: no cover - exercised only without torch
        raise ImportError(
            "PyTorch is required to load BEACON model checkpoints. "
            "Install the backend requirements before using model_io."
        ) from exc
    return torch


def safe_torch_load(
    model_path: Any,
    map_location: Any = None,
    *,
    allow_unsafe: Optional[bool] = None,
) -> Mapping[str, Any]:
    """Load a checkpoint with the restricted (weights-only) unpickler.

    Args:
        model_path: Path to the ``.pt`` checkpoint.
        map_location: Passed through to ``torch.load`` (e.g. ``"cpu"`` or a device).
        allow_unsafe: Override the environment opt-in. When ``None`` the value of
            ``BEACON_ALLOW_UNSAFE_CHECKPOINT_LOAD`` decides.

    Raises:
        FileNotFoundError: The checkpoint does not exist.
        UnsafeCheckpointError: The checkpoint is not weights-only serialisable and
            unsafe loading has not been enabled.
    """
    path = Path(model_path)
    if not path.is_file():
        raise FileNotFoundError(f"Model checkpoint not found: {path}")

    torch = _require_torch()
    allow = is_unsafe_load_allowed() if allow_unsafe is None else allow_unsafe

    try:
        return torch.load(str(path), map_location=map_location, weights_only=True)
    except Exception as safe_exc:  # noqa: BLE001 - torch raises several unrelated types
        if not allow:
            raise UnsafeCheckpointError(
                path,
                "checkpoint is not weights-only serialisable "
                f"({type(safe_exc).__name__}: {safe_exc}). Re-save it with "
                "safe_torch_save(), or set "
                f"{UNSAFE_LOAD_ENV_VAR}=1 to accept the risk for legacy artifacts.",
            ) from safe_exc

        logger.warning(
            "SECURITY: loading '%s' with the unrestricted unpickler because %s is set. "
            "Only do this for checkpoints you produced yourself.",
            path,
            UNSAFE_LOAD_ENV_VAR,
        )
        return torch.load(str(path), map_location=map_location, weights_only=False)


def safe_torch_save(checkpoint: Mapping[str, Any], model_path: Any) -> str:
    """Serialise a checkpoint that is guaranteed to load under ``weights_only=True``.

    The payload is round-tripped through the restricted unpickler before the
    file is written, so an artifact that would force operators to disable the
    safe loader is rejected at save time instead of at load time.

    Returns:
        The path the checkpoint was written to.
    """
    torch = _require_torch()
    path = Path(model_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    buffer = io.BytesIO()
    torch.save(checkpoint, buffer)
    buffer.seek(0)
    try:
        torch.load(buffer, weights_only=True)
    except Exception as exc:  # noqa: BLE001
        raise UnsafeCheckpointError(
            path,
            "checkpoint metadata contains objects the weights-only unpickler rejects "
            f"({type(exc).__name__}: {exc}). Store only tensors and plain Python "
            "containers so the artifact remains safely loadable.",
        ) from exc

    torch.save(checkpoint, str(path))
    logger.debug("Saved weights-only compatible checkpoint to %s", path)
    return str(path)
