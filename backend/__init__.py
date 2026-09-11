"""Backend API application.

The public objects below are resolved lazily (PEP 562). Importing them eagerly
meant that ``import backend.exceptions`` — or any other submodule — pulled in
FastAPI, Celery, and PyTorch, so every unit test required the full runtime
stack just to import a domain error class.
"""

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .api.main import app
    from .database import close_db, get_db, init_db
    from .tasks.celery_app import celery_app

__all__ = ["app", "init_db", "close_db", "get_db", "celery_app"]

_LAZY_IMPORTS = {
    "app": (".api.main", "app"),
    "init_db": (".database", "init_db"),
    "close_db": (".database", "close_db"),
    "get_db": (".database", "get_db"),
    "celery_app": (".tasks.celery_app", "celery_app"),
}


def __getattr__(name: str) -> Any:
    """Resolve the documented public attributes on first access."""
    try:
        module_name, attribute = _LAZY_IMPORTS[name]
    except KeyError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None

    value = getattr(import_module(module_name, __name__), attribute)
    globals()[name] = value
    return value


def __dir__() -> list:
    return sorted(__all__)
