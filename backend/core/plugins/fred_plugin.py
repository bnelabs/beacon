"""FRED (Federal Reserve Economic Data) plugin."""

from fredapi import Fred
import pandas as pd
from datetime import datetime
from typing import Dict, Any, List, Optional
import logging

from .base import DataSourcePlugin, register_plugin

logger = logging.getLogger(__name__)


class FREDPlugin(DataSourcePlugin):
    """Plugin for FRED economic data."""

    def validate_config(self) -> None:
        """Validate FRED configuration."""
        if not self.config.get('api_key'):
            raise ValueError("FRED API key is required. Get one free at https://fred.stlouisfed.org/docs/api/api_key.html")

    def test_connection(self) -> Dict[str, Any]:
        """Test FRED API connectivity."""
        try:
            fred = Fred(api_key=self.config['api_key'])
            # Try fetching a well-known series
            test_data = fred.get_series('GDP', limit=1)

            if test_data is not None and len(test_data) > 0:
                return {
                    "success": True,
                    "message": "Successfully connected to FRED API",
                    "details": {"test_series": "GDP", "latest_value": float(test_data.iloc[0])}
                }
            else:
                return {
                    "success": False,
                    "message": "Could not retrieve data from FRED"
                }
        except Exception as e:
            error_msg = str(e)
            if "400" in error_msg or "API key" in error_msg:
                return {
                    "success": False,
                    "message": "Invalid API key. Please check your FRED API key and try again."
                }
            elif "429" in error_msg:
                return {
                    "success": False,
                    "message": "Rate limit exceeded. Please wait a moment and try again."
                }
            else:
                return {
                    "success": False,
                    "message": f"Connection failed: {error_msg}"
                }

    def fetch_asset_data(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """FRED doesn't provide asset price data."""
        logger.warning("FRED plugin does not support asset price data")
        return None

    def fetch_indicator_data(
        self,
        indicator_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Fetch economic indicator data from FRED.

        Args:
            indicator_id: FRED series ID (e.g., 'GDP', 'UNRATE', 'CPIAUCSL')
            start_date: Start date
            end_date: End date

        Returns:
            DataFrame with Date and Value columns
        """
        try:
            fred = Fred(api_key=self.config['api_key'])

            # Fetch series data
            data = fred.get_series(
                indicator_id,
                observation_start=start_date.strftime("%Y-%m-%d"),
                observation_end=end_date.strftime("%Y-%m-%d")
            )

            if data is None or data.empty:
                logger.warning(f"No data returned for FRED series: {indicator_id}")
                return None

            # Convert to DataFrame
            df = data.reset_index()
            df.columns = ['Date', 'Value']

            # Remove NaN values
            df = df.dropna()

            logger.info(f"Fetched {len(df)} observations for FRED series {indicator_id}")
            return df

        except Exception as e:
            logger.error(f"Error fetching data from FRED: {e}")
            return None

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Get FRED configuration schema."""
        return {
            "api_key": {
                "type": "string",
                "required": True,
                "label": "FRED API Key",
                "help": "Get your free API key at https://fred.stlouisfed.org/docs/api/api_key.html",
                "secret": True
            },
            "rate_limit": {
                "type": "number",
                "required": False,
                "default": 0.5,
                "label": "Rate Limit (seconds)",
                "help": "Delay between API calls (FRED allows 120 requests/minute)"
            }
        }

    @classmethod
    def get_plugin_info(cls) -> Dict[str, Any]:
        """Get plugin metadata."""
        return {
            "name": "FRED",
            "description": "Federal Reserve Economic Data - free economic indicators from the St. Louis Fed",
            "version": "1.0.0",
            "author": "Liquidity Monitor",
            "free": True,
            "registration_required": True,
            "registration_url": "https://fred.stlouisfed.org/docs/api/api_key.html",
            "data_types": ["economic_indicators"],
            "example_series": ["GDP", "UNRATE", "CPIAUCSL", "DFF", "T10Y2Y"]
        }


# Register the plugin
register_plugin("fred", FREDPlugin)
