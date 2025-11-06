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
from .fred_plugin import FREDPlugin
from .alpha_vantage_plugin import AlphaVantagePlugin
from .csv_plugin import CSVPlugin
from .custom_api_plugin import CustomAPIPlugin
from .sec_plugin import SECPlugin
from .ecb_plugin import ECBPlugin
from .bis_plugin import BISPlugin
from .imf_plugin import IMFPlugin
from .world_bank_plugin import WorldBankPlugin
from .ecb_banking_plugin import ECBBankingPlugin
from .fmp_plugin import FMPPlugin
from .kaggle_plugin import KagglePlugin

__all__ = [
    "DataSourcePlugin",
    "register_plugin",
    "get_plugin",
    "list_plugins",
    "YFinancePlugin",
    "FREDPlugin",
    "AlphaVantagePlugin",
    "CSVPlugin",
    "CustomAPIPlugin",
    "SECPlugin",
    "ECBPlugin",
    "BISPlugin",
    "IMFPlugin",
    "WorldBankPlugin",
    "ECBBankingPlugin",
    "FMPPlugin",
    "KagglePlugin",
]
