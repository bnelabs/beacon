"""Compatibility helpers for Python's ``multiprocessing`` module."""

from __future__ import annotations

import logging
import threading
from typing import Callable, Optional

from multiprocessing import pool as mp_pool

logger = logging.getLogger(__name__)

_PATCH_LOCK = threading.Lock()
_PATCHED = False


def _wrap_pool_del(original_del: Callable[[mp_pool.Pool], None]) -> Callable[[mp_pool.Pool], None]:
    """Return a ``Pool.__del__`` wrapper that guards against stale picklers."""

    def safe_del(self: mp_pool.Pool) -> None:  # type: ignore[override]
        try:
            original_del(self)
        except AttributeError as exc:  # pragma: no cover - only hit at shutdown
            message = str(exc)
            if "dumps" not in message:
                raise
            # ``ForkingPickler.dumps`` is no longer available because the module
            # providing it was cleared during interpreter shutdown. This happens
            # when Celery/torch tweak the pickler implementation.
            logger.debug(
                "Suppressing multiprocessing Pool shutdown error caused by late interpreter teardown: %s",
                message,
            )
        except Exception:
            # Bubble up every other failure so default behaviour is preserved.
            raise

    return safe_del


def ensure_safe_pool_cleanup() -> None:
    """Patch ``Pool.__del__`` once so shutdown is resilient to teardown order."""

    global _PATCHED

    if _PATCHED:
        return

    with _PATCH_LOCK:
        if _PATCHED:
            return

        original_del: Optional[Callable[[mp_pool.Pool], None]] = getattr(mp_pool.Pool, "__del__", None)
        if original_del is None:
            logger.debug("No Pool.__del__ attribute to patch")
            _PATCHED = True
            return

        mp_pool.Pool.__del__ = _wrap_pool_del(original_del)  # type: ignore[assignment]
        _PATCHED = True
        logger.debug("Applied safe Pool.__del__ patch")
