"""Utility helpers for backend application."""

from .multiprocessing_patch import ensure_safe_pool_cleanup

__all__ = ["ensure_safe_pool_cleanup"]
