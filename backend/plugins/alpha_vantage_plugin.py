"""Alpha Vantage data source plugin."""

import requests
import pandas as pd
from datetime import datetime
from typing import Dict, Any, List, Optional
import logging
import time

from .base import DataSourcePlugin, register_plugin

logger = logging.getLogger(__name__)


class AlphaVantagePlugin(DataSourcePlugin):
    """Plugin for Alpha Vantage stock data."""

    BASE_URL = "https://www.alphavantage.co/query"

    def validate_config(self) -> None:
        """Validate Alpha Vantage configuration."""
        if not self.config.get('api_key'):
            raise ValueError("Alpha Vantage API key is required. Get one free at https://www.alphavantage.co/support/#api-key")

    def test_connection(self) -> Dict[str, Any]:
        """Test Alpha Vantage API connectivity."""
        try:
            params = {
                'function': 'TIME_SERIES_DAILY',
                'symbol': 'IBM',
                'apikey': self.config['api_key'],
                'outputsize': 'compact'
            }

            response = requests.get(self.BASE_URL, params=params, timeout=10)
            data = response.json()

            if "Error Message" in data:
                return {
                    "success": False,
                    "message": "Invalid symbol or API error"
                }
            elif "Note" in data:
                return {
                    "success": False,
                    "message": "API call frequency limit reached. Free tier allows 5 calls/minute, 500 calls/day."
                }
            elif "Time Series (Daily)" in data:
                return {
                    "success": True,
                    "message": "Successfully connected to Alpha Vantage API",
                    "details": {"test_symbol": "IBM"}
                }
            else:
                return {
                    "success": False,
                    "message": "Unexpected response from Alpha Vantage API"
                }

        except requests.exceptions.Timeout:
            return {
                "success": False,
                "message": "Connection timeout. Please check your internet connection."
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Connection failed: {str(e)}"
            }

    def fetch_asset_data(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Fetch stock data from Alpha Vantage.

        Args:
            symbols: List of stock symbols
            start_date: Start date
            end_date: End date

        Returns:
            DataFrame with standardized columns
        """
        frames = []
        rate_limit = self.config.get('rate_limit', 12)  # Free tier: 5 calls/min = 12 sec between calls

        for idx, symbol in enumerate(symbols):
            try:
                # Rate limiting
                if idx > 0:
                    time.sleep(rate_limit)

                params = {
                    'function': 'TIME_SERIES_DAILY',
                    'symbol': symbol,
                    'apikey': self.config['api_key'],
                    'outputsize': 'full'
                }

                response = requests.get(self.BASE_URL, params=params, timeout=30)
                data = response.json()

                if "Error Message" in data:
                    logger.warning(f"Invalid symbol: {symbol}")
                    continue
                elif "Note" in data:
                    logger.warning("Rate limit reached, stopping data collection")
                    break
                elif "Time Series (Daily)" not in data:
                    logger.warning(f"No data for symbol: {symbol}")
                    continue

                # Parse time series
                time_series = data["Time Series (Daily)"]

                # Convert to DataFrame
                df = pd.DataFrame.from_dict(time_series, orient='index')
                df.index = pd.to_datetime(df.index)
                df = df.sort_index()

                # Rename columns
                df.columns = ['Open', 'High', 'Low', 'Close', 'Volume']

                # Filter date range
                df = df[(df.index >= start_date) & (df.index <= end_date)]

                if df.empty:
                    logger.warning(f"No data in date range for {symbol}")
                    continue

                # Convert types
                for col in ['Open', 'High', 'Low', 'Close']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce').astype('Int64')

                # Add metadata
                df['Asset'] = symbol
                df = df.reset_index().rename(columns={'index': 'Date'})

                # Reorder columns
                df = df[['Date', 'Asset', 'Open', 'High', 'Low', 'Close', 'Volume']]

                frames.append(df)
                logger.info(f"Fetched {len(df)} rows for {symbol} from Alpha Vantage")

            except Exception as e:
                logger.error(f"Error fetching {symbol} from Alpha Vantage: {e}")
                continue

        if not frames:
            return None

        result = pd.concat(frames, ignore_index=True)
        logger.info(f"Fetched total {len(result)} rows for {len(frames)} symbols from Alpha Vantage")
        return result

    def fetch_indicator_data(
        self,
        indicator_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Fetch economic indicator data from Alpha Vantage.

        Args:
            indicator_id: Indicator code (e.g., 'REAL_GDP', 'INFLATION')
            start_date: Start date
            end_date: End date

        Returns:
            DataFrame with Date and Value columns
        """
        try:
            params = {
                'function': indicator_id,
                'apikey': self.config['api_key']
            }

            response = requests.get(self.BASE_URL, params=params, timeout=30)
            data = response.json()

            if "Error Message" in data or "data" not in data:
                logger.warning(f"No data for indicator: {indicator_id}")
                return None

            # Parse data
            df = pd.DataFrame(data['data'])
            df['date'] = pd.to_datetime(df['date'])
            df['value'] = pd.to_numeric(df['value'], errors='coerce')

            # Filter date range
            df = df[(df['date'] >= start_date) & (df['date'] <= end_date)]

            # Standardize columns
            df = df.rename(columns={'date': 'Date', 'value': 'Value'})
            df = df[['Date', 'Value']].sort_values('Date')

            logger.info(f"Fetched {len(df)} observations for indicator {indicator_id}")
            return df

        except Exception as e:
            logger.error(f"Error fetching indicator from Alpha Vantage: {e}")
            return None

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Get Alpha Vantage configuration schema."""
        return {
            "api_key": {
                "type": "string",
                "required": True,
                "label": "Alpha Vantage API Key",
                "help": "Get your free API key at https://www.alphavantage.co/support/#api-key",
                "secret": True
            },
            "rate_limit": {
                "type": "number",
                "required": False,
                "default": 12,
                "label": "Rate Limit (seconds)",
                "help": "Delay between API calls. Free tier: 5 calls/minute (12 sec recommended)"
            }
        }

    @classmethod
    def get_plugin_info(cls) -> Dict[str, Any]:
        """Get plugin metadata."""
        return {
            "name": "Alpha Vantage",
            "description": "Stock market data and economic indicators. Free tier: 5 calls/min, 500 calls/day.",
            "version": "1.0.0",
            "author": "Liquidity Monitor",
            "free": True,
            "registration_required": True,
            "registration_url": "https://www.alphavantage.co/support/#api-key",
            "data_types": ["stocks", "forex", "crypto", "economic_indicators"],
            "limitations": "Free tier: 5 API calls per minute, 500 per day"
        }


# Register the plugin
register_plugin("alpha_vantage", AlphaVantagePlugin)
