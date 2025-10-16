"""Data source plugin system.

This module provides a plugin architecture for adding data sources without
modifying core code. Each plugin implements the DataSourcePlugin interface.
"""

from .base import (
    DataSourcePlugin,
    register_plugin,
    get_plugin,
    list_plugins
)

# Import all plugins to register them
from .yfinance_plugin import YFinancePlugin

__all__ = [
    "DataSourcePlugin",
    "register_plugin",
    "get_plugin",
    "list_plugins",
    "YFinancePlugin"
]
