"""BIS (Bank for International Settlements) API plugin."""

from typing import Dict, Any, List, Optional
import pandas as pd
from datetime import datetime
import requests
import logging
from .base import DataSourcePlugin, register_plugin

logger = logging.getLogger(__name__)


class BISPlugin(DataSourcePlugin):
    """
    Bank for International Settlements (BIS) API plugin.

    Data from: BIS Statistics Warehouse API
    Documentation: https://www.bis.org/statistics/

    Features:
    - Credit statistics
    - Debt securities
    - Exchange rates
    - Property prices
    - No API key required
    """

    def validate_config(self) -> None:
        """Validate BIS configuration (no API key needed)."""
        # BIS API is open, no authentication required
        pass

    def test_connection(self) -> Dict[str, Any]:
        """Test BIS API connectivity."""
        try:
            # Test with a simple query to BIS Statistics API
            url = "https://stats.bis.org/api/v1/data"
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                return {
                    "success": True,
                    "message": "Successfully connected to BIS Statistics API"
                }
            else:
                return {
                    "success": False,
                    "message": f"BIS API returned status code: {response.status_code}"
                }
        except Exception as e:
            logger.error(f"BIS connection test failed: {e}")
            return {
                "success": False,
                "message": f"Failed to connect to BIS API: {str(e)}"
            }

    def fetch_asset_data(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Fetch asset/exchange rate data from BIS.

        Args:
            symbols: List of BIS series keys or currency codes
            start_date: Start date
            end_date: End date

        Returns:
            DataFrame with standardized columns
        """
        try:
            base_url = "https://stats.bis.org/api/v1"
            all_data = []

            for symbol in symbols:
                try:
                    # BIS uses specific series keys
                    # For now, we'll return empty data and log
                    logger.info(f"BIS asset data fetch for {symbol} - implementation needed for specific series")

                    # Placeholder: return empty DataFrame
                    # TODO: Implement specific BIS series mapping

                except Exception as e:
                    logger.warning(f"Failed to fetch {symbol} from BIS: {e}")
                    continue

            if all_data:
                result = pd.concat(all_data, ignore_index=True)
                logger.info(f"Fetched {len(result)} rows from BIS")
                return result

            return None

        except Exception as e:
            logger.error(f"Error fetching data from BIS: {e}")
            return None

    def fetch_indicator_data(
        self,
        indicator_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Fetch economic indicator data from BIS.

        Args:
            indicator_id: BIS series key (e.g., 'WEBSTATS_CREDIT_TO_GDP_PUB_DATAFLOW')
            start_date: Start date
            end_date: End date

        Returns:
            DataFrame with Date and Value columns
        """
        try:
            # BIS API endpoint for data
            url = "https://stats.bis.org/api/v1/data"

            # Parameters for API request
            params = {
                "format": "json",
                "startPeriod": start_date.strftime("%Y-%m-%d"),
                "endPeriod": end_date.strftime("%Y-%m-%d")
            }

            # Add indicator ID to URL path
            full_url = f"{url}/{indicator_id}"

            headers = {
                "Accept": "application/json",
                "User-Agent": "BEACON/2.0"
            }

            response = requests.get(full_url, headers=headers, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()

            # Parse BIS JSON response
            df = self._parse_bis_json(data)

            if df is not None and not df.empty:
                logger.info(f"Fetched {len(df)} records for {indicator_id} from BIS")
                return df
            else:
                logger.warning(f"No data returned for {indicator_id} from BIS")
                return None

        except Exception as e:
            logger.error(f"Error fetching indicator {indicator_id} from BIS: {e}")
            return None

    def _parse_bis_json(self, data: Dict) -> Optional[pd.DataFrame]:
        """Parse BIS API JSON response into DataFrame."""
        try:
            if not data or 'data' not in data:
                return None

            # BIS returns data in SDMX-JSON format
            # Structure: data.dataSets[0].series -> observations
            records = []

            # This is a simplified parser - BIS SDMX format is complex
            # May need adjustment based on actual API response structure
            if 'dataSets' in data:
                for dataset in data['dataSets']:
                    if 'series' in dataset:
                        for series_key, series_data in dataset['series'].items():
                            if 'observations' in series_data:
                                for time_key, obs_data in series_data['observations'].items():
                                    value = obs_data[0] if isinstance(obs_data, list) else obs_data
                                    records.append({
                                        'date': time_key,  # May need parsing
                                        'value': float(value) if value is not None else None
                                    })

            if records:
                df = pd.DataFrame(records)
                df['date'] = pd.to_datetime(df['date'])
                df = df.sort_values('date')
                return df

            return None

        except Exception as e:
            logger.error(f"Error parsing BIS JSON: {e}")
            return None

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Get configuration schema for BIS plugin."""
        return {
            "name": {
                "type": "string",
                "required": False,
                "label": "Configuration Name",
                "description": "Optional name for this BIS configuration",
                "default": "BIS Statistics"
            },
            "timeout": {
                "type": "integer",
                "required": False,
                "label": "Request Timeout (seconds)",
                "description": "Timeout for API requests",
                "default": 30
            }
        }

    @classmethod
    def get_plugin_info(cls) -> Dict[str, Any]:
        """Get plugin metadata."""
        return {
            "name": "Bank for International Settlements (BIS)",
            "description": "Free access to BIS Statistics - credit statistics, debt securities, exchange rates, property prices. No API key required.",
            "version": "1.0.0",
            "author": "BEACON",
            "free": True,
            "registration_required": False,
            "registration_url": None
        }


# Register the plugin
register_plugin("bis", BISPlugin)
