"""Base class for data source plugins.

This plugin system allows adding new data sources without modifying core code.
Each plugin defines its own configuration schema and data fetching logic.
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, List, Optional
import pandas as pd
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class DataSourcePlugin(ABC):
    """Abstract base class for all data source plugins."""

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the plugin with configuration.

        Args:
            config: Plugin-specific configuration dictionary
        """
        self.config = config
        self._resilient_session = None
        self.validate_config()

    @property
    def http(self):
        """Lazily-built resilient HTTP session shared by this plugin's calls.

        Opt-in: a plugin that replaces its raw ``requests.get(...)`` with
        ``self.http.get(...)`` gains unified exponential-backoff retries, a
        bounded TTL response cache with stale-on-outage fallback, and per-host
        rate limiting -- without bespoke code. See
        :mod:`backend.plugins.http_client`.

        Configuration keys honoured (all optional):
          * ``timeout``      -- per-request timeout in seconds (default 30).
          * ``rate_limit``   -- minimum seconds between calls to the same host.
          * ``cache_ttl``    -- seconds a response stays fresh; ``0`` disables
                                caching and the stale fallback (default 300).
        """
        if getattr(self, "_resilient_session", None) is None:
            from backend.plugins.http_client import ResilientSession

            config = getattr(self, "config", {}) or {}
            self._resilient_session = ResilientSession(
                timeout=float(config.get("timeout", 30) or 30),
                min_interval=float(config.get("rate_limit", 0) or 0),
                cache_ttl=float(config.get("cache_ttl", 300) or 0),
            )
        return self._resilient_session

    @abstractmethod
    def validate_config(self) -> None:
        """
        Validate the plugin configuration.

        Raises:
            ValueError: If configuration is invalid
        """
        pass

    @abstractmethod
    def test_connection(self) -> Dict[str, Any]:
        """
        Test if the data source is accessible.

        Returns:
            Dictionary with keys:
            - success (bool): Whether connection succeeded
            - message (str): User-friendly message
            - details (dict, optional): Additional information
        """
        pass

    def test_item(self, item_identifier: str) -> Dict[str, Any]:
        """
        Test if a specific data item (indicator/symbol) is available.

        This method attempts to fetch a small sample of data to verify the item exists
        and is accessible. Default implementation uses fetch_indicator_data with a
        short date range. Override for custom behavior.

        Args:
            item_identifier: The indicator ID, symbol, or endpoint to test

        Returns:
            Dictionary with keys:
            - success (bool): Whether the item is accessible
            - message (str): User-friendly message
            - details (dict, optional): Additional information (e.g., data points found)
        """
        try:
            # Try to fetch last 7 days of data as a test
            from datetime import timedelta
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)

            # Try indicator data first (most common)
            df = self.fetch_indicator_data(item_identifier, start_date, end_date)

            if df is not None and not df.empty:
                return {
                    "success": True,
                    "message": f"Successfully accessed {item_identifier}. Found {len(df)} data points.",
                    "details": {
                        "data_points": len(df),
                        "date_range": f"{start_date.date()} to {end_date.date()}"
                    }
                }
            else:
                return {
                    "success": False,
                    "message": f"No data found for {item_identifier}. It may not exist or have no recent data.",
                    "details": {"error": "Empty dataset"}
                }

        except Exception as e:
            logger.error(f"Error testing item {item_identifier}: {e}")
            return {
                "success": False,
                "message": f"Failed to access {item_identifier}: {str(e)}",
                "details": {"error": str(e)}
            }

    @abstractmethod
    def fetch_asset_data(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Fetch price data for specified assets.

        Args:
            symbols: List of asset symbols/tickers
            start_date: Start date for data
            end_date: End date for data

        Returns:
            DataFrame with columns: Date, Asset, Open, High, Low, Close, Volume
            or None if fetch fails
        """
        pass

    @abstractmethod
    def fetch_indicator_data(
        self,
        indicator_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Fetch indicator/economic data.

        Args:
            indicator_id: Identifier for the indicator
            start_date: Start date for data
            end_date: End date for data

        Returns:
            DataFrame with columns: Date, Value
            or None if fetch fails
        """
        pass

    @classmethod
    @abstractmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """
        Get the configuration schema for this plugin.

        Returns:
            Dictionary describing required and optional configuration fields.
            Used to generate UI forms automatically.

            Example:
            {
                "api_key": {
                    "type": "string",
                    "required": True,
                    "label": "API Key",
                    "help": "Get your free API key from..."
                },
                "rate_limit": {
                    "type": "number",
                    "required": False,
                    "default": 2.0,
                    "label": "Rate Limit (seconds)",
                    "help": "Delay between API calls"
                }
            }
        """
        pass

    @classmethod
    @abstractmethod
    def get_plugin_info(cls) -> Dict[str, Any]:
        """
        Get metadata about this plugin.

        Returns:
            Dictionary with plugin information:
            - name: Human-readable plugin name
            - description: What this plugin does
            - version: Plugin version
            - author: Plugin author
            - free: Whether the data source is free
            - registration_required: Whether user needs to register
            - registration_url: Where to register (if applicable)
        """
        pass


# Plugin registry
_PLUGIN_REGISTRY = {}


def register_plugin(plugin_type: str, plugin_class: type):
    """
    Register a data source plugin.

    Args:
        plugin_type: Unique identifier for the plugin
        plugin_class: Plugin class (must inherit from DataSourcePlugin)
    """
    if not issubclass(plugin_class, DataSourcePlugin):
        raise ValueError(f"{plugin_class} must inherit from DataSourcePlugin")

    _PLUGIN_REGISTRY[plugin_type] = plugin_class
    logger.info(f"Registered plugin: {plugin_type}")


def get_plugin(plugin_type: str) -> Optional[type]:
    """
    Get a plugin class by type.

    Args:
        plugin_type: Plugin identifier

    Returns:
        Plugin class or None if not found
    """
    return _PLUGIN_REGISTRY.get(plugin_type)


def list_plugins() -> List[Dict[str, Any]]:
    """
    List all registered plugins.

    Returns:
        List of plugin information dictionaries
    """
    return [
        {
            "type": plugin_type,
            **plugin_class.get_plugin_info(),
            "config_schema": plugin_class.get_config_schema()
        }
        for plugin_type, plugin_class in _PLUGIN_REGISTRY.items()
    ]
