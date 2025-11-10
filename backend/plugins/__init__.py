"""Data source plugin system.

This module provides a plugin architecture for adding data sources without
modifying core code. Each plugin implements the DataSourcePlugin interface.

Historically we imported every plugin at module import time so they could
register themselves automatically. That behaviour makes local testing brittle
because optional third-party dependencies (for example ``fredapi`` or
``alpha_vantage``) must be installed even when the corresponding plugin is not
used. When the dependencies are absent the import previously raised a
``ModuleNotFoundError`` during application start-up, preventing even basic
smoke tests from running.

To keep the developer experience lightweight we now best-effort import each
plugin while gracefully skipping those whose optional dependencies are missing.
Any failures are logged and the remaining plugins still register correctly.
"""

from importlib import import_module
import logging
from typing import Dict, List, Tuple

from .base import (
    DataSourcePlugin,
    register_plugin,
    get_plugin,
    list_plugins
)

logger = logging.getLogger(__name__)


def _load_plugins() -> Dict[str, str]:
    """Attempt to import all plugins, skipping ones with missing deps."""

    plugin_specs: Tuple[Tuple[str, str], ...] = (
        (".yfinance_plugin", "YFinancePlugin"),
        (".fred_plugin", "FREDPlugin"),
        (".alpha_vantage_plugin", "AlphaVantagePlugin"),
        (".csv_plugin", "CSVPlugin"),
        (".custom_api_plugin", "CustomAPIPlugin"),
        (".sec_plugin", "SECPlugin"),
        (".ecb_plugin", "ECBPlugin"),
        (".bis_plugin", "BISPlugin"),
        (".imf_plugin", "IMFPlugin"),
        (".world_bank_plugin", "WorldBankPlugin"),
        (".ecb_banking_plugin", "ECBBankingPlugin"),
        (".fmp_plugin", "FMPPlugin"),
        (".kaggle_plugin", "KagglePlugin"),
    )

    loaded: Dict[str, str] = {}

    for module_suffix, attr in plugin_specs:
        module_name = __name__ + module_suffix
        try:
            module = import_module(module_name)
        except ModuleNotFoundError as exc:
            logger.warning(
                "Skipping plugin %s because dependency import failed: %s",
                module_name,
                exc,
            )
            continue

        plugin_cls = getattr(module, attr, None)
        if plugin_cls is None:
            logger.warning("Plugin module %s is missing %s", module_name, attr)
            continue

        globals()[attr] = plugin_cls
        loaded[attr] = module_name

    return loaded


_loaded_plugins = _load_plugins()


def available_plugins() -> List[str]:
    """Return the plugin class names that successfully imported."""

    return sorted(_loaded_plugins.keys())


__all__ = [
    "DataSourcePlugin",
    "register_plugin",
    "get_plugin",
    "list_plugins",
    "available_plugins",
    *_loaded_plugins.keys(),
]
