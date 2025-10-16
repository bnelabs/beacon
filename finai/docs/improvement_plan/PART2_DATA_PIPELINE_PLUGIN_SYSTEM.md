# PRODUCTION-GRADE IMPROVEMENT PLAN - PART 2
## Configurable Data Pipeline & Plugin System

**Document Version:** 1.0
**Last Updated:** December 2024
**Prerequisite Reading:** Part 1 (Architecture)

---

## TABLE OF CONTENTS

1. [Plugin System Overview](#plugin-system-overview)
2. [Core Plugin Interface](#core-plugin-interface)
3. [Built-in Plugins](#built-in-plugins)
4. [UI Configuration Workflow](#ui-configuration-workflow)
5. [Data Quality & Validation](#data-quality-validation)
6. [Free Data Sources Reference](#free-data-sources-reference)

---

## PLUGIN SYSTEM OVERVIEW

### Design Goals

1. **Zero Hardcoding**: Add data sources via UI without touching code
2. **Type Safety**: Plugins define expected data schema
3. **Self-Documenting**: Plugins generate their own UI forms
4. **Testable**: Test connection before using
5. **Extensible**: Users can create custom plugins

### Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     PLUGIN REGISTRY                          │
│  (Maps plugin type → plugin class)                          │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  yfinance    → YFinancePlugin                                │
│  fred        → FREDPlugin                                    │
│  sec         → SECPlugin                                     │
│  csv         → CSVUploadPlugin                               │
│  api         → GenericAPIPlugin                              │
│  database    → DatabasePlugin                                │
│  websocket   → WebSocketPlugin                               │
│  custom      → CustomPlugin (user-defined)                   │
│                                                               │
└─────────────────────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────────────────────┐
│                  ABSTRACT BASE CLASS                         │
│              DataSourcePlugin (ABC)                          │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  Abstract Methods (Must Implement):                          │
│  • fetch_data(assets, start_date, end_date) → DataFrame     │
│  • validate_config() → {valid, errors, warnings}            │
│  • test_connection() → {success, message, latency_ms}       │
│                                                               │
│  Optional Methods (Can Override):                            │
│  • get_rate_limits() → {limit, period, current_usage}       │
│  • get_schema() → {Date: datetime64, Asset: str, ...}       │
│  • get_ui_config_schema() → JSON Schema for UI forms        │
│  • transform_data(df) → Preprocess fetched data             │
│  • handle_error(exception) → User-friendly error message    │
│                                                               │
└─────────────────────────────────────────────────────────────┘
         ↓
┌─────────────────────────────────────────────────────────────┐
│                CONCRETE PLUGIN IMPLEMENTATIONS               │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  class YFinancePlugin(DataSourcePlugin):                     │
│      def fetch_data(...):                                    │
│          # Implementation specific to yfinance API           │
│                                                               │
│  class FREDPlugin(DataSourcePlugin):                         │
│      def fetch_data(...):                                    │
│          # Implementation specific to FRED API               │
│                                                               │
│  ... more plugins ...                                        │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

---

## CORE PLUGIN INTERFACE

### Base Class Definition

```python
# src/liquidity_monitor/data/plugins/base.py

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
import pandas as pd
from datetime import datetime
from enum import Enum

class DataSourceType(Enum):
    """Types of data sources."""
    STOCK_PRICES = "stock_prices"
    ECONOMIC_INDICATORS = "economic_indicators"
    FINANCIAL_STATEMENTS = "financial_statements"
    FUND_HOLDINGS = "fund_holdings"
    CUSTOM = "custom"

class PluginStatus(Enum):
    """Plugin execution status."""
    IDLE = "idle"
    CONNECTING = "connecting"
    FETCHING = "fetching"
    PROCESSING = "processing"
    COMPLETE = "complete"
    ERROR = "error"

class RateLimitError(Exception):
    """Raised when rate limit is exceeded."""
    pass

class AuthenticationError(Exception):
    """Raised when API authentication fails."""
    pass

class DataNotFoundError(Exception):
    """Raised when requested data is not available."""
    pass

class DataSourcePlugin(ABC):
    """
    Abstract base class for all data source plugins.

    This defines the contract that all plugins must follow.
    Users can create custom plugins by inheriting this class
    and implementing the required methods.
    """

    def __init__(self, config: dict):
        """
        Initialize plugin with configuration.

        Args:
            config: Dictionary containing plugin configuration
                {
                    "id": "unique_id",
                    "name": "My Data Source",
                    "type": DataSourceType,
                    "enabled": bool,
                    "api_key": "...",  # Optional
                    "rate_limit": 100,
                    "rate_period": "minute",
                    ... plugin-specific params ...
                }
        """
        self.config = config
        self.id = config.get("id")
        self.name = config.get("name", "Unnamed Source")
        self.type = config.get("type", DataSourceType.CUSTOM)
        self.enabled = config.get("enabled", True)

        # Rate limiting
        self._last_request_time = None
        self._request_count = 0
        self._rate_limit_window_start = None

        # Status tracking
        self.status = PluginStatus.IDLE
        self.last_run = None
        self.last_success = None
        self.last_error = None

    @abstractmethod
    def fetch_data(
        self,
        assets: List[str],
        start_date: datetime,
        end_date: datetime,
        **kwargs
    ) -> pd.DataFrame:
        """
        Fetch data from source.

        This is the main method that retrieves data from the external source.

        Args:
            assets: List of asset identifiers (tickers, ISINs, etc.)
            start_date: Start of date range (inclusive)
            end_date: End of date range (inclusive)
            **kwargs: Additional plugin-specific parameters

        Returns:
            DataFrame with standardized schema:
                - Date (datetime64): Timestamp
                - Asset (str): Asset identifier
                - Plus plugin-specific columns

        Raises:
            ConnectionError: Cannot reach data source
            RateLimitError: Rate limit exceeded
            AuthenticationError: Invalid credentials
            DataNotFoundError: Asset/date range not found
            ValueError: Invalid parameters

        Example:
            >>> plugin = YFinancePlugin(config)
            >>> df = plugin.fetch_data(
            ...     assets=['JPM', 'BAC'],
            ...     start_date=datetime(2024, 1, 1),
            ...     end_date=datetime(2024, 12, 31)
            ... )
            >>> print(df.head())
                  Date Asset   Close    Volume
            0 2024-01-01   JPM  150.25  12000000
            1 2024-01-02   JPM  151.30  11500000
            ...
        """
        pass

    @abstractmethod
    def validate_config(self) -> Dict[str, Any]:
        """
        Validate plugin configuration.

        Checks if all required settings are present and valid.
        Should not make external API calls (use test_connection for that).

        Returns:
            Dictionary with validation results:
            {
                "valid": bool,  # True if config is valid
                "errors": List[str],  # List of error messages
                "warnings": List[str]  # List of warning messages
            }

        Example:
            >>> plugin = FREDPlugin({"name": "FRED", "api_key": None})
            >>> result = plugin.validate_config()
            >>> print(result)
            {
                "valid": False,
                "errors": ["API key is required"],
                "warnings": []
            }
        """
        pass

    @abstractmethod
    def test_connection(self) -> Dict[str, Any]:
        """
        Test connection to data source.

        Performs a lightweight check to verify the source is reachable
        and credentials are valid. Should complete quickly (<10 seconds).

        Returns:
            Dictionary with test results:
            {
                "success": bool,  # True if connection successful
                "message": str,  # Human-readable status message
                "latency_ms": float,  # Response time in milliseconds
                "metadata": dict  # Optional additional info
            }

        Example:
            >>> plugin = YFinancePlugin(config)
            >>> result = plugin.test_connection()
            >>> print(result)
            {
                "success": True,
                "message": "Connection successful",
                "latency_ms": 234.5,
                "metadata": {"version": "0.2.46"}
            }
        """
        pass

    def get_rate_limits(self) -> Dict[str, Any]:
        """
        Get rate limit information.

        Returns current rate limit status for this plugin.

        Returns:
            Dictionary with rate limit info:
            {
                "limit": int,  # Max requests per period
                "period": str,  # "second", "minute", "hour", "day"
                "current_usage": int,  # Requests used in current window
                "reset_time": datetime,  # When limit resets
                "exceeded": bool  # True if limit currently exceeded
            }
        """
        return {
            "limit": self.config.get("rate_limit", 1000),
            "period": self.config.get("rate_period", "hour"),
            "current_usage": self._request_count,
            "reset_time": self._rate_limit_window_start,
            "exceeded": False
        }

    def get_schema(self) -> Dict[str, str]:
        """
        Get expected output schema.

        Defines what columns the plugin returns and their data types.

        Returns:
            Dictionary mapping column names to pandas dtypes:
            {
                "Date": "datetime64[ns]",
                "Asset": "str",
                "Close": "float64",
                ...
            }
        """
        return {
            "Date": "datetime64[ns]",
            "Asset": "str"
        }

    def get_ui_config_schema(self) -> Dict[str, Any]:
        """
        Get JSON Schema for UI form generation.

        This schema is used to automatically generate configuration
        forms in the web dashboard. Follows JSON Schema specification.

        Returns:
            JSON Schema object describing configuration options

        Example:
            >>> plugin = YFinancePlugin({})
            >>> schema = plugin.get_ui_config_schema()
            >>> print(schema)
            {
                "type": "object",
                "title": "Yahoo Finance Configuration",
                "properties": {
                    "name": {
                        "type": "string",
                        "title": "Data Source Name",
                        "default": "Yahoo Finance"
                    },
                    "batch_size": {
                        "type": "integer",
                        "title": "Batch Size",
                        "minimum": 1,
                        "maximum": 100,
                        "default": 20
                    }
                },
                "required": ["name"]
            }
        """
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "title": "Data Source Name",
                    "default": self.name
                },
                "enabled": {
                    "type": "boolean",
                    "title": "Enabled",
                    "default": True
                }
            },
            "required": ["name"]
        }

    def transform_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Transform fetched data before returning.

        Override this method to apply plugin-specific transformations.
        Default implementation returns data unchanged.

        Args:
            df: Raw DataFrame from fetch_data()

        Returns:
            Transformed DataFrame
        """
        return df

    def handle_error(self, exception: Exception) -> Dict[str, Any]:
        """
        Convert technical exception to user-friendly message.

        Override this method to provide plugin-specific error translations.

        Args:
            exception: Exception that was raised

        Returns:
            Dictionary with user-friendly error info:
            {
                "title": str,  # Short error title
                "message": str,  # Plain English explanation
                "severity": str,  # "info", "warning", "error", "critical"
                "suggestions": List[str],  # What user can do to fix
                "technical_details": str  # Original exception for experts
            }
        """
        return {
            "title": "Data Source Error",
            "message": f"Failed to fetch data: {str(exception)}",
            "severity": "error",
            "suggestions": [
                "Check your internet connection",
                "Verify the data source is online",
                "Contact support if problem persists"
            ],
            "technical_details": str(exception)
        }

    def _check_rate_limit(self):
        """
        Check if rate limit would be exceeded.

        Raises RateLimitError if limit exceeded.
        """
        rate_limit = self.config.get("rate_limit")
        if not rate_limit:
            return

        # Reset counter if window expired
        period = self.config.get("rate_period", "hour")
        period_seconds = {
            "second": 1,
            "minute": 60,
            "hour": 3600,
            "day": 86400
        }[period]

        now = datetime.now()
        if (not self._rate_limit_window_start or
            (now - self._rate_limit_window_start).seconds > period_seconds):
            self._request_count = 0
            self._rate_limit_window_start = now

        # Check limit
        if self._request_count >= rate_limit:
            raise RateLimitError(
                f"Rate limit exceeded: {rate_limit} requests per {period}"
            )

        self._request_count += 1

    def _update_status(self, status: PluginStatus):
        """Update plugin status."""
        self.status = status
        if status == PluginStatus.COMPLETE:
            self.last_success = datetime.now()
        elif status == PluginStatus.ERROR:
            self.last_error = datetime.now()
        self.last_run = datetime.now()
```

---

## BUILT-IN PLUGINS

### 1. YFinance Plugin (Free Stock Prices)

```python
# src/liquidity_monitor/data/plugins/yfinance_plugin.py

import yfinance as yf
import time
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any

from .base import DataSourcePlugin, DataSourceType, DataNotFoundError

class YFinancePlugin(DataSourcePlugin):
    """
    Yahoo Finance data source plugin.

    Provides free stock price data for global markets.

    Features:
    - No API key required
    - Covers 100K+ assets globally
    - Historical data back to 1960s
    - Real-time quotes (15-min delay)
    - Dividends, splits, financials

    Limitations:
    - Rate limited (~2000 requests/hour)
    - No official API (uses web scraping)
    - Occasional service interruptions
    - Some international stocks have limited data
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.batch_size = config.get("batch_size", 20)
        self.rate_limit_sleep = config.get("rate_limit_sleep", 2.0)
        self.type = DataSourceType.STOCK_PRICES

    def fetch_data(
        self,
        assets: List[str],
        start_date: datetime,
        end_date: datetime,
        **kwargs
    ) -> pd.DataFrame:
        """Fetch stock price data from Yahoo Finance."""
        import yfinance as yf

        all_data = []

        # Batch downloads to respect rate limits
        for i in range(0, len(assets), self.batch_size):
            batch = assets[i:i + self.batch_size]

            try:
                # Check rate limit
                self._check_rate_limit()

                # Download batch
                data = yf.download(
                    batch,
                    start=start_date,
                    end=end_date,
                    progress=False,
                    auto_adjust=True,
                    threads=True
                )

                if data.empty:
                    continue

                # Handle single vs multi-ticker response
                if len(batch) == 1 and not isinstance(data.columns, pd.MultiIndex):
                    # Single ticker returns flat columns
                    data.columns = pd.MultiIndex.from_product(
                        [data.columns, batch],
                        names=['Metric', 'Asset']
                    )

                # Convert to standard format
                if isinstance(data.columns, pd.MultiIndex):
                    # Swap levels: (Metric, Asset) → (Asset, Metric)
                    data.columns = data.columns.swaplevel()

                    # Stack asset level
                    data = data.stack(level=0, future_stack=True)
                    data = data.rename_axis(["Date", "Asset"]).reset_index()

                    # Rename columns
                    rename_map = {
                        'Adj Close': 'Close',
                        'Close': 'Close_Unadj'
                    }
                    data = data.rename(columns=rename_map)

                    # Keep only required columns
                    required_cols = ['Date', 'Asset', 'Open', 'High', 'Low', 'Close', 'Volume']
                    data = data[[col for col in data.columns if col in required_cols]]

                    all_data.append(data)

                # Rate limiting
                if i + self.batch_size < len(assets):
                    time.sleep(self.rate_limit_sleep)

            except Exception as e:
                # Log error but continue with other batches
                self.last_error = {
                    "batch": i // self.batch_size + 1,
                    "assets": batch,
                    "error": str(e)
                }
                continue

        if not all_data:
            raise DataNotFoundError("No data was successfully downloaded")

        result = pd.concat(all_data, ignore_index=True)
        return self.transform_data(result)

    def validate_config(self) -> Dict[str, Any]:
        """Validate configuration."""
        errors = []
        warnings = []

        # Validate batch size
        if self.batch_size < 1 or self.batch_size > 100:
            errors.append("Batch size must be between 1 and 100")

        # Validate rate limit sleep
        if self.rate_limit_sleep < 0.5:
            warnings.append(
                "Rate limit sleep < 0.5s may cause request failures. "
                "Yahoo Finance recommends at least 1 second between requests."
            )

        # Check rate limit config
        rate_limit = self.config.get("rate_limit", 2000)
        if rate_limit > 5000:
            warnings.append(
                f"Rate limit set to {rate_limit}/hour, but Yahoo Finance "
                "typically allows ~2000/hour. You may experience failures."
            )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }

    def test_connection(self) -> Dict[str, Any]:
        """Test Yahoo Finance connectivity."""
        start_time = time.time()

        try:
            # Test with a known-good ticker
            test_data = yf.download(
                "AAPL",
                period="1d",
                progress=False
            )

            latency = (time.time() - start_time) * 1000

            if test_data.empty:
                return {
                    "success": False,
                    "message": "Test download returned empty data. Yahoo Finance may be unavailable.",
                    "latency_ms": latency
                }

            return {
                "success": True,
                "message": "Connection successful. Yahoo Finance is reachable.",
                "latency_ms": latency,
                "metadata": {
                    "test_ticker": "AAPL",
                    "rows_returned": len(test_data)
                }
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"Connection failed: {str(e)}",
                "latency_ms": (time.time() - start_time) * 1000
            }

    def get_schema(self) -> Dict[str, str]:
        """Get output schema."""
        return {
            "Date": "datetime64[ns]",
            "Asset": "str",
            "Open": "float64",
            "High": "float64",
            "Low": "float64",
            "Close": "float64",
            "Volume": "int64"
        }

    def get_ui_config_schema(self) -> Dict[str, Any]:
        """Get UI form schema."""
        return {
            "type": "object",
            "title": "Yahoo Finance Configuration",
            "description": "Configure Yahoo Finance stock price data source. No API key required.",
            "properties": {
                "name": {
                    "type": "string",
                    "title": "Data Source Name",
                    "default": "Yahoo Finance",
                    "description": "Friendly name to identify this data source"
                },
                "enabled": {
                    "type": "boolean",
                    "title": "Enabled",
                    "default": True
                },
                "batch_size": {
                    "type": "integer",
                    "title": "Batch Size",
                    "description": "Number of assets to download simultaneously. Lower values are slower but more reliable.",
                    "default": 20,
                    "minimum": 1,
                    "maximum": 100
                },
                "rate_limit_sleep": {
                    "type": "number",
                    "title": "Rate Limit Sleep (seconds)",
                    "description": "Delay between batch downloads. Increase if experiencing failures.",
                    "default": 2.0,
                    "minimum": 0.5,
                    "maximum": 10.0
                },
                "rate_limit": {
                    "type": "integer",
                    "title": "Rate Limit (requests per hour)",
                    "description": "Maximum API requests per hour. Yahoo Finance typically allows ~2000.",
                    "default": 2000,
                    "minimum": 100,
                    "maximum": 10000
                }
            },
            "required": ["name", "batch_size", "rate_limit_sleep"]
        }

    def handle_error(self, exception: Exception) -> Dict[str, Any]:
        """Translate errors to plain English."""
        error_msg = str(exception).lower()

        if "no data" in error_msg or "404" in error_msg:
            return {
                "title": "Asset Not Found",
                "message": "One or more requested stocks could not be found on Yahoo Finance.",
                "severity": "warning",
                "suggestions": [
                    "Check that ticker symbols are correct (e.g., 'AAPL' not 'Apple')",
                    "Verify the asset is publicly traded",
                    "Try using the full ticker including exchange (e.g., 'AAPL.US')",
                    "Search for the correct ticker on finance.yahoo.com"
                ],
                "technical_details": str(exception)
            }

        elif "rate limit" in error_msg or "429" in error_msg:
            return {
                "title": "Download Limit Reached",
                "message": "Yahoo Finance is limiting download requests. This happens when too many requests are made in a short time.",
                "severity": "warning",
                "suggestions": [
                    "Wait 15-30 minutes before retrying",
                    "Increase 'Rate Limit Sleep' setting to 3-5 seconds",
                    "Reduce 'Batch Size' to 10-15 assets",
                    "Spread downloads across multiple hours using scheduled tasks"
                ],
                "technical_details": str(exception)
            }

        elif "connection" in error_msg or "timeout" in error_msg:
            return {
                "title": "Connection Problem",
                "message": "Cannot connect to Yahoo Finance. This could be a network issue or Yahoo Finance may be temporarily unavailable.",
                "severity": "error",
                "suggestions": [
                    "Check your internet connection",
                    "Try accessing finance.yahoo.com in a web browser",
                    "Wait a few minutes and retry",
                    "Check if Yahoo Finance is experiencing outages (status.yahoo.com)"
                ],
                "technical_details": str(exception)
            }

        else:
            return super().handle_error(exception)
```

### 2. FRED Plugin (Free Economic Data)

```python
# src/liquidity_monitor/data/plugins/fred_plugin.py

from fredapi import Fred
import pandas as pd
from datetime import datetime
from typing import List, Dict, Any

from .base import DataSourcePlugin, DataSourceType, AuthenticationError

class FREDPlugin(DataSourcePlugin):
    """
    Federal Reserve Economic Data (FRED) plugin.

    Provides free US economic indicators from the Federal Reserve Bank of St. Louis.

    Features:
    - 800K+ economic time series
    - Data back to 1776 (for some series)
    - Daily updates
    - Official government data
    - Free API key (no rate limits for most users)

    Limitations:
    - US-focused (limited international data)
    - Some series updated infrequently (quarterly, annually)
    - Requires free API key registration

    Register for API key: https://fred.stlouisfed.org/docs/api/api_key.html
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = config.get("api_key")
        self.type = DataSourceType.ECONOMIC_INDICATORS
        self._client = None

    @property
    def client(self) -> Fred:
        """Lazy load FRED client."""
        if self._client is None:
            if not self.api_key:
                raise AuthenticationError("FRED API key is required")
            self._client = Fred(api_key=self.api_key)
        return self._client

    def fetch_data(
        self,
        assets: List[str],  # For FRED, these are series IDs like 'GDP', 'UNRATE'
        start_date: datetime,
        end_date: datetime,
        **kwargs
    ) -> pd.DataFrame:
        """Fetch economic indicators from FRED."""
        all_series = []

        for series_id in assets:
            try:
                # Check rate limit
                self._check_rate_limit()

                # Fetch series
                series = self.client.get_series(
                    series_id,
                    observation_start=start_date,
                    observation_end=end_date
                )

                if not series.empty:
                    # Convert to DataFrame
                    df = pd.DataFrame({
                        'Date': series.index,
                        'Asset': series_id,
                        'Value': series.values
                    })
                    all_series.append(df)

            except Exception as e:
                self.last_error = {
                    "series_id": series_id,
                    "error": str(e)
                }
                continue

        if not all_series:
            raise DataNotFoundError("No FRED data was successfully downloaded")

        result = pd.concat(all_series, ignore_index=True)

        # Forward fill to handle weekends/holidays
        result = result.sort_values(['Asset', 'Date'])
        result['Value'] = result.groupby('Asset')['Value'].ffill()

        return self.transform_data(result)

    def validate_config(self) -> Dict[str, Any]:
        """Validate configuration."""
        errors = []
        warnings = []

        if not self.api_key:
            errors.append(
                "FRED API key is required. "
                "Get a free key at https://fred.stlouisfed.org/docs/api/api_key.html"
            )
        elif len(self.api_key) != 32:
            warnings.append(
                "FRED API keys are typically 32 characters. "
                "Your key may be invalid."
            )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }

    def test_connection(self) -> Dict[str, Any]:
        """Test FRED API connectivity."""
        import time

        start_time = time.time()

        try:
            # Test with GDP series (always available)
            test_data = self.client.get_series('GDP', limit=1)
            latency = (time.time() - start_time) * 1000

            if test_data.empty:
                return {
                    "success": False,
                    "message": "API key is valid but no data returned",
                    "latency_ms": latency
                }

            return {
                "success": True,
                "message": "Connection successful. FRED API is reachable.",
                "latency_ms": latency,
                "metadata": {
                    "test_series": "GDP",
                    "latest_value": float(test_data.iloc[-1])
                }
            }

        except Exception as e:
            error_msg = str(e).lower()

            if "api key" in error_msg or "authentication" in error_msg:
                message = "Invalid API key. Please check your FRED API key."
            else:
                message = f"Connection failed: {str(e)}"

            return {
                "success": False,
                "message": message,
                "latency_ms": (time.time() - start_time) * 1000
            }

    def get_schema(self) -> Dict[str, str]:
        """Get output schema."""
        return {
            "Date": "datetime64[ns]",
            "Asset": "str",  # Series ID (e.g., 'GDP', 'UNRATE')
            "Value": "float64"
        }

    def get_ui_config_schema(self) -> Dict[str, Any]:
        """Get UI form schema."""
        return {
            "type": "object",
            "title": "FRED Configuration",
            "description": "Federal Reserve Economic Data - Free US economic indicators",
            "properties": {
                "name": {
                    "type": "string",
                    "title": "Data Source Name",
                    "default": "FRED"
                },
                "enabled": {
                    "type": "boolean",
                    "title": "Enabled",
                    "default": True
                },
                "api_key": {
                    "type": "string",
                    "title": "API Key",
                    "description": "Get free API key at https://fred.stlouisfed.org/docs/api/api_key.html",
                    "format": "password",
                    "minLength": 32,
                    "maxLength": 32
                },
                "rate_limit": {
                    "type": "integer",
                    "title": "Rate Limit (requests per hour)",
                    "description": "FRED allows 120 requests per minute for most users",
                    "default": 7200,
                    "minimum": 100
                }
            },
            "required": ["name", "api_key"]
        }

    def handle_error(self, exception: Exception) -> Dict[str, Any]:
        """Translate errors to plain English."""
        error_msg = str(exception).lower()

        if "api key" in error_msg or "authentication" in error_msg or "401" in error_msg:
            return {
                "title": "Invalid API Key",
                "message": "The FRED API key is invalid or expired.",
                "severity": "error",
                "suggestions": [
                    "Check that you copied the entire API key (32 characters)",
                    "Verify the key hasn't expired",
                    "Generate a new API key at https://fred.stlouisfed.org/docs/api/api_key.html",
                    "Make sure there are no extra spaces before/after the key"
                ],
                "technical_details": str(exception)
            }

        elif "not found" in error_msg or "404" in error_msg:
            return {
                "title": "Economic Indicator Not Found",
                "message": "One or more requested economic indicators could not be found in FRED.",
                "severity": "warning",
                "suggestions": [
                    "Check series IDs are correct (e.g., 'GDP' not 'Gross Domestic Product')",
                    "Search for series on https://fred.stlouisfed.org",
                    "Some series may have been discontinued - check FRED website for alternatives"
                ],
                "technical_details": str(exception)
            }

        else:
            return super().handle_error(exception)
```

### 3. CSV Upload Plugin

```python
# src/liquidity_monitor/data/plugins/csv_plugin.py

import pandas as pd
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

from .base import DataSourcePlugin, DataSourceType, DataNotFoundError

class CSVUploadPlugin(DataSourcePlugin):
    """
    CSV file upload plugin.

    Allows users to upload custom data from CSV files.

    Features:
    - Supports any CSV format with column mapping
    - Handles various date formats
    - Automatic data type detection
    - Preview before import

    Use Cases:
    - Internal data not available via API
    - Historical data from vendors
    - Manual data entry
    - Testing with sample data
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.file_path = config.get("file_path")
        self.delimiter = config.get("delimiter", ",")
        self.date_format = config.get("date_format", "%Y-%m-%d")
        self.encoding = config.get("encoding", "utf-8")
        self.skip_rows = config.get("skip_rows", 0)

        # Column mapping: CSV column name → system column name
        self.mapping = config.get("mapping", {})

        self.type = DataSourceType.CUSTOM

    def fetch_data(
        self,
        assets: List[str],
        start_date: datetime,
        end_date: datetime,
        **kwargs
    ) -> pd.DataFrame:
        """Read data from CSV file."""
        if not Path(self.file_path).exists():
            raise FileNotFoundError(f"CSV file not found: {self.file_path}")

        try:
            # Read CSV
            df = pd.read_csv(
                self.file_path,
                delimiter=self.delimiter,
                encoding=self.encoding,
                skiprows=self.skip_rows
            )

            # Apply column mapping
            if self.mapping:
                df = df.rename(columns=self.mapping)

            # Validate required columns
            required = ['Date', 'Asset']
            missing = [col for col in required if col not in df.columns]
            if missing:
                raise ValueError(f"Missing required columns: {missing}")

            # Parse dates
            df["Date"] = pd.to_datetime(df["Date"], format=self.date_format, errors='coerce')

            # Drop rows with invalid dates
            df = df.dropna(subset=['Date'])

            # Filter by date range
            df = df[
                (df["Date"] >= start_date) &
                (df["Date"] <= end_date)
            ]

            # Filter by assets if specified
            if assets:
                df = df[df["Asset"].isin(assets)]

            if df.empty:
                raise DataNotFoundError(
                    f"No data found for date range {start_date.date()} to {end_date.date()}"
                )

            return self.transform_data(df)

        except Exception as e:
            raise ConnectionError(f"Failed to read CSV file: {e}")

    def validate_config(self) -> Dict[str, Any]:
        """Validate CSV configuration."""
        errors = []
        warnings = []

        # Check file path
        if not self.file_path:
            errors.append("File path is required")
        elif not Path(self.file_path).exists():
            errors.append(f"File not found: {self.file_path}")
        elif not self.file_path.endswith('.csv'):
            warnings.append(
                "File doesn't have .csv extension. "
                "Make sure it's a valid CSV file."
            )

        # Check mapping
        required_mappings = ["Date", "Asset"]
        if self.mapping:
            mapped_system_cols = set(self.mapping.values())
            missing = [col for col in required_mappings if col not in mapped_system_cols]
            if missing:
                errors.append(
                    f"Column mapping must include: {', '.join(missing)}"
                )

        # Check delimiter
        valid_delimiters = [",", ";", "\t", "|"]
        if self.delimiter not in valid_delimiters:
            warnings.append(
                f"Unusual delimiter '{self.delimiter}'. "
                f"Supported delimiters: {', '.join(valid_delimiters)}"
            )

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }

    def test_connection(self) -> Dict[str, Any]:
        """Test CSV file accessibility."""
        import time

        start_time = time.time()

        try:
            # Try to read first few rows
            df = pd.read_csv(
                self.file_path,
                delimiter=self.delimiter,
                encoding=self.encoding,
                skiprows=self.skip_rows,
                nrows=5
            )

            latency = (time.time() - start_time) * 1000

            return {
                "success": True,
                "message": f"File readable. Found {len(df.columns)} columns, {len(df)} sample rows.",
                "latency_ms": latency,
                "metadata": {
                    "columns": df.columns.tolist(),
                    "sample_rows": len(df)
                }
            }

        except Exception as e:
            return {
                "success": False,
                "message": f"Cannot read file: {str(e)}",
                "latency_ms": (time.time() - start_time) * 1000
            }

    def get_schema(self) -> Dict[str, str]:
        """Get output schema (dynamic based on CSV)."""
        if not Path(self.file_path).exists():
            return {
                "Date": "datetime64[ns]",
                "Asset": "str"
            }

        try:
            # Infer schema from file
            df = pd.read_csv(
                self.file_path,
                delimiter=self.delimiter,
                nrows=100
            )

            if self.mapping:
                df = df.rename(columns=self.mapping)

            return {col: str(dtype) for col, dtype in df.dtypes.items()}

        except:
            return {
                "Date": "datetime64[ns]",
                "Asset": "str"
            }

    def get_ui_config_schema(self) -> Dict[str, Any]:
        """Get UI form schema."""
        return {
            "type": "object",
            "title": "CSV Upload Configuration",
            "description": "Upload custom data from CSV files",
            "properties": {
                "name": {
                    "type": "string",
                    "title": "Data Source Name",
                    "default": "CSV Upload"
                },
                "enabled": {
                    "type": "boolean",
                    "title": "Enabled",
                    "default": True
                },
                "file_path": {
                    "type": "string",
                    "title": "CSV File",
                    "format": "file",
                    "description": "Upload or select CSV file"
                },
                "delimiter": {
                    "type": "string",
                    "title": "Delimiter",
                    "description": "Character separating columns",
                    "enum": [",", ";", "\t", "|"],
                    "enumNames": ["Comma (,)", "Semicolon (;)", "Tab", "Pipe (|)"],
                    "default": ","
                },
                "date_format": {
                    "type": "string",
                    "title": "Date Format",
                    "description": "Python strftime format (e.g., %Y-%m-%d for 2024-12-15)",
                    "default": "%Y-%m-%d",
                    "examples": [
                        "%Y-%m-%d (2024-12-15)",
                        "%d/%m/%Y (15/12/2024)",
                        "%m/%d/%Y (12/15/2024)",
                        "%Y%m%d (20241215)"
                    ]
                },
                "encoding": {
                    "type": "string",
                    "title": "File Encoding",
                    "enum": ["utf-8", "latin1", "cp1252", "ascii"],
                    "default": "utf-8"
                },
                "skip_rows": {
                    "type": "integer",
                    "title": "Skip Rows",
                    "description": "Number of header rows to skip",
                    "default": 0,
                    "minimum": 0,
                    "maximum": 100
                },
                "mapping": {
                    "type": "object",
                    "title": "Column Mapping",
                    "description": "Map CSV columns to system fields",
                    "properties": {
                        "date_column": {
                            "type": "string",
                            "title": "Date Column Name",
                            "description": "Name of column containing dates"
                        },
                        "asset_column": {
                            "type": "string",
                            "title": "Asset Column Name",
                            "description": "Name of column containing asset identifiers"
                        },
                        "price_column": {
                            "type": "string",
                            "title": "Price Column Name (optional)",
                            "description": "Name of column containing prices"
                        },
                        "volume_column": {
                            "type": "string",
                            "title": "Volume Column Name (optional)",
                            "description": "Name of column containing trading volume"
                        }
                    },
                    "required": ["date_column", "asset_column"]
                }
            },
            "required": ["name", "file_path", "mapping"]
        }
```

---

## UI CONFIGURATION WORKFLOW

### Step-by-Step User Experience

#### Step 1: Navigate to Data Sources

```
User clicks: Dashboard → Data Sources → [+ Add New Source]
```

#### Step 2: Select Plugin Type

```
┌─────────────────────────────────────────────────────────────┐
│  Select Data Source Type                                     │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  Popular Sources:                                             │
│                                                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ 📈 Yahoo    │  │ 📊 FRED     │  │ 📄 CSV      │         │
│  │   Finance   │  │  Economic   │  │   Upload    │         │
│  │             │  │  Data       │  │             │         │
│  │ Free        │  │ Free*       │  │ Custom      │         │
│  │ Stock Data  │  │ US Econ     │  │ Data        │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│                                                               │
│  Advanced Sources:                                            │
│                                                               │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │
│  │ 🏛️ SEC      │  │ 🌐 Custom   │  │ 🗄️ Database │         │
│  │   Edgar     │  │   API       │  │   Connect   │         │
│  │             │  │             │  │             │         │
│  │ Free*       │  │ Any REST    │  │ PostgreSQL  │         │
│  │ Filings     │  │ API         │  │ MySQL       │         │
│  └─────────────┘  └─────────────┘  └─────────────┘         │
│                                                               │
│  * Requires free API key registration                        │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

#### Step 3: Configure Plugin (Auto-Generated Form)

**Example: Yahoo Finance**

```
┌─────────────────────────────────────────────────────────────┐
│  Configure Yahoo Finance                                     │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ℹ️ Yahoo Finance provides free stock price data for        │
│     100K+ global assets. No API key required.                │
│                                                               │
│  Data Source Name: *                                          │
│  ┌────────────────────────────────────────────────────────┐ │
│  │ Yahoo Finance                                           │ │
│  └────────────────────────────────────────────────────────┘ │
│                                                               │
│  Enabled:                                                     │
│  ☑ Active  ☐ Disabled                                       │
│                                                               │
│  Advanced Settings (Optional):                               │
│  [Show/Hide]                                                  │
│                                                               │
│  Batch Size: *                                                │
│  ┌────┐                                                      │
│  │ 20 │ assets per request                                  │
│  └────┘                                                      │
│  ℹ️ Lower values are more reliable but slower               │
│                                                               │
│  Rate Limit Sleep: *                                          │
│  ┌────┐                                                      │
│  │ 2.0│ seconds between batches                             │
│  └────┘                                                      │
│  ℹ️ Increase if experiencing download failures               │
│                                                               │
│  Rate Limit: *                                                │
│  ┌──────┐                                                    │
│  │ 2000 │ requests per hour                                 │
│  └──────┘                                                    │
│                                                               │
│  [Test Connection]  [Save]  [Cancel]                         │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

#### Step 4: Test Connection

```
User clicks: [Test Connection]

┌─────────────────────────────────────────────────────────────┐
│  Testing Connection...                                       │
├─────────────────────────────────────────────────────────────┤
│                                                               │
│  ⏳ Connecting to Yahoo Finance...                           │
│  ⏳ Downloading test data (AAPL, 1 day)...                   │
│  ✓ Connection successful!                                    │
│                                                               │
│  Response Time: 234 ms                                        │
│  Test Data: 1 row retrieved                                  │
│                                                               │
│  [Save Configuration]                                         │
│                                                               │
└─────────────────────────────────────────────────────────────┘
```

#### Step 5: Save and Use

```
Configuration saved!

System automatically:
1. Validates configuration
2. Saves to database
3. Makes plugin available for data collection
4. Shows in Data Sources list
```

---

## FREE DATA SOURCES REFERENCE

### Comprehensive List of Free Financial Data APIs

| Source | Data Type | API Key Required | Rate Limit | Coverage |
|--------|-----------|------------------|------------|----------|
| **Yahoo Finance** | Stock prices, quotes | No | ~2000/hour | Global, 100K+ assets |
| **FRED** | US economic indicators | Yes (free) | 120/min | 800K+ series |
| **Alpha Vantage** | Stocks, forex, crypto | Yes (free) | 500/day | Global markets |
| **IEX Cloud** | US stocks, market data | Yes (free tier) | 50K/month | US markets |
| **Quandl/Nasdaq** | Various datasets | Yes (free) | 50 calls/day | Multiple sources |
| **World Bank API** | Global economic data | No | Unlimited | 200+ countries |
| **ECB API** | European economic data | No | Unlimited | Eurozone |
| **Coinbase API** | Crypto prices | No | 10 req/sec | Major crypto |
| **CoinGecko API** | Crypto prices | No (paid for higher) | 10-50/min | 10K+ crypto |
| **Finnhub** | Stock data | Yes (free) | 60 calls/min | Global markets |
| **Polygon.io** | Market data | Yes (free tier) | Limited | US markets |
| **Twelve Data** | Stocks, forex, crypto | Yes (free) | 800/day | Global markets |

### Registration Instructions

#### FRED (Federal Reserve Economic Data)
1. Go to https://fred.stlouisfed.org/
2. Click "Sign In" → "Create Account"
3. Verify email
4. Go to https://fred.stlouisfed.org/docs/api/api_key.html
5. Click "Request API Key"
6. Copy 32-character key

#### Alpha Vantage
1. Go to https://www.alphavantage.co/support/#api-key
2. Enter email address
3. Instant API key (no verification needed)
4. Free tier: 500 requests/day, 5 requests/minute

#### IEX Cloud
1. Go to https://iexcloud.io/
2. Click "Start Free"
3. Verify email
4. Free tier: 50,000 messages/month

### Recommended Free Setup for Regulatory Monitoring

**Core Configuration (No Budget):**
```yaml
data_sources:
  - type: yfinance
    name: "Yahoo Finance"
    config:
      batch_size: 20
      rate_limit_sleep: 2.0

  - type: fred
    name: "FRED Economic"
    config:
      api_key: "YOUR_FREE_KEY"

  - type: csv
    name: "Manual Data Upload"
    config:
      file_path: "data/custom/manual_data.csv"
```

This provides:
- ✅ 100K+ global stock prices (Yahoo Finance)
- ✅ 800K+ US economic indicators (FRED)
- ✅ Custom data upload capability (CSV)
- ✅ Zero cost
- ✅ Sufficient for most regulatory monitoring needs

---

## NEXT SECTIONS

- **Part 3**: Error Translation & User-Friendly Messaging (Complete implementation)
- **Part 4**: Resource Optimization Strategies
- **Part 5**: Implementation Roadmap
- **Part 6**: Deployment Architecture

**END OF PART 2**
