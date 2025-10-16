"""Yahoo Finance data source plugin."""

import yfinance as yf
import pandas as pd
from datetime import datetime
from typing import Dict, Any, List, Optional
import logging

from .base import DataSourcePlugin, register_plugin

logger = logging.getLogger(__name__)


class YFinancePlugin(DataSourcePlugin):
    """Plugin for Yahoo Finance data source."""

    def validate_config(self) -> None:
        """Yahoo Finance requires no configuration."""
        # No configuration needed for yfinance
        pass

    def test_connection(self) -> Dict[str, Any]:
        """Test Yahoo Finance connectivity."""
        try:
            # Try fetching a well-known ticker
            test_ticker = yf.Ticker("AAPL")
            info = test_ticker.info

            if info and 'symbol' in info:
                return {
                    "success": True,
                    "message": "Successfully connected to Yahoo Finance",
                    "details": {"test_symbol": "AAPL"}
                }
            else:
                return {
                    "success": False,
                    "message": "Could not retrieve data from Yahoo Finance"
                }
        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to connect to Yahoo Finance: {str(e)}"
            }

    def fetch_asset_data(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Fetch price data from Yahoo Finance.

        Args:
            symbols: List of ticker symbols
            start_date: Start date
            end_date: End date

        Returns:
            DataFrame with standardized columns
        """
        try:
            # Download data
            data = yf.download(
                symbols,
                start=start_date.strftime("%Y-%m-%d"),
                end=end_date.strftime("%Y-%m-%d"),
                group_by='ticker',
                auto_adjust=False,
                progress=False
            )

            if data.empty:
                logger.warning(f"No data returned for symbols: {symbols}")
                return None

            # Handle single vs multiple tickers
            if len(symbols) == 1:
                if not isinstance(data.columns, pd.MultiIndex):
                    data = data.copy()
                    data.columns = pd.MultiIndex.from_product(
                        [data.columns, symbols],
                        names=['Metric', 'Asset']
                    )

            # Convert to standardized format
            frames = []
            for symbol in symbols:
                try:
                    symbol_data = data[symbol] if len(symbols) > 1 else data[symbol]
                    symbol_data = symbol_data.copy()
                    symbol_data['Asset'] = symbol
                    symbol_data = symbol_data.reset_index()

                    # Rename columns to standard format
                    symbol_data = symbol_data.rename(columns={
                        'Date': 'Date',
                        'Open': 'Open',
                        'High': 'High',
                        'Low': 'Low',
                        'Close': 'Close',
                        'Volume': 'Volume'
                    })

                    # Select only required columns
                    required_cols = ['Date', 'Asset', 'Open', 'High', 'Low', 'Close', 'Volume']
                    symbol_data = symbol_data[required_cols]

                    frames.append(symbol_data)
                except Exception as e:
                    logger.warning(f"Failed to process {symbol}: {e}")
                    continue

            if not frames:
                return None

            result = pd.concat(frames, ignore_index=True)
            logger.info(f"Fetched {len(result)} rows for {len(symbols)} symbols from Yahoo Finance")
            return result

        except Exception as e:
            logger.error(f"Error fetching data from Yahoo Finance: {e}")
            return None

    def fetch_indicator_data(
        self,
        indicator_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """Yahoo Finance doesn't provide economic indicators."""
        logger.warning("Yahoo Finance plugin does not support economic indicators")
        return None

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Yahoo Finance requires no configuration."""
        return {}

    @classmethod
    def get_plugin_info(cls) -> Dict[str, Any]:
        """Get plugin metadata."""
        return {
            "name": "Yahoo Finance",
            "description": "Free stock market data from Yahoo Finance. No API key required.",
            "version": "1.0.0",
            "author": "Liquidity Monitor",
            "free": True,
            "registration_required": False,
            "registration_url": None
        }


# Register the plugin
register_plugin("yfinance", YFinancePlugin)
