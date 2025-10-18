"""IMF (International Monetary Fund) Data API plugin."""

from typing import Dict, Any, List, Optional
import pandas as pd
from datetime import datetime
import requests
import logging
from .base import DataSourcePlugin, register_plugin

logger = logging.getLogger(__name__)


class IMFPlugin(DataSourcePlugin):
    """
    International Monetary Fund (IMF) Data API plugin.

    Data from: IMF Data API
    Documentation: https://datahelp.imf.org/knowledgebase/articles/667681-using-json-restful-web-service

    Features:
    - International Financial Statistics (IFS)
    - Balance of Payments (BOP)
    - Government Finance Statistics (GFS)
    - World Economic Outlook (WEO)
    - No API key required
    """

    def validate_config(self) -> None:
        """Validate IMF configuration (no API key needed)."""
        # IMF API is open, no authentication required
        pass

    def test_connection(self) -> Dict[str, Any]:
        """Test IMF API connectivity."""
        try:
            # Test with dataflow endpoint
            url = "https://dataservices.imf.org/REST/SDMX_JSON.svc/Dataflow"
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                return {
                    "success": True,
                    "message": "Successfully connected to IMF Data API"
                }
            else:
                return {
                    "success": False,
                    "message": f"IMF API returned status code: {response.status_code}"
                }
        except Exception as e:
            logger.error(f"IMF connection test failed: {e}")
            return {
                "success": False,
                "message": f"Failed to connect to IMF API: {str(e)}"
            }

    def fetch_asset_data(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        IMF doesn't provide traditional asset price data.

        Args:
            symbols: Not applicable for IMF
            start_date: Start date
            end_date: End date

        Returns:
            None (IMF is for indicators only)
        """
        logger.warning("IMF plugin does not support asset price data")
        return None

    def fetch_indicator_data(
        self,
        indicator_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Fetch economic indicator data from IMF.

        Args:
            indicator_id: IMF indicator code (e.g., 'IFS.M.US.PMP_IX')
                Format: Database.Frequency.Country.Indicator
                - IFS = International Financial Statistics
                - M = Monthly, Q = Quarterly, A = Annual
                - US = United States (ISO code)
                - PMP_IX = Producer Price Index
            start_date: Start date
            end_date: End date

        Returns:
            DataFrame with Date and Value columns
        """
        try:
            # Parse indicator ID to extract components
            # Format: Database.Frequency.Country.Indicator
            parts = indicator_id.split('.')
            if len(parts) < 4:
                logger.error(f"Invalid IMF indicator format: {indicator_id}")
                logger.info("Expected format: Database.Frequency.Country.Indicator (e.g., IFS.M.US.PMP_IX)")
                return None

            database = parts[0]  # e.g., IFS, BOP, GFS
            frequency = parts[1]  # e.g., M (monthly), Q (quarterly), A (annual)
            country = parts[2]    # e.g., US, GB, JP
            indicator = '.'.join(parts[3:])  # Rest is the indicator

            # Build IMF API URL
            # Format: https://dataservices.imf.org/REST/SDMX_JSON.svc/CompactData/{database}/{frequency}.{country}.{indicator}
            base_url = "https://dataservices.imf.org/REST/SDMX_JSON.svc"
            url = f"{base_url}/CompactData/{database}/{frequency}.{country}.{indicator}"

            # Add time period parameters
            params = {
                "startPeriod": start_date.strftime("%Y"),
                "endPeriod": end_date.strftime("%Y")
            }

            headers = {
                "Accept": "application/json",
                "User-Agent": "BEACON/2.0"
            }

            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()

            # Parse IMF JSON response
            df = self._parse_imf_json(data, frequency)

            if df is not None and not df.empty:
                logger.info(f"Fetched {len(df)} records for {indicator_id} from IMF")
                return df
            else:
                logger.warning(f"No data returned for {indicator_id} from IMF")
                return None

        except Exception as e:
            logger.error(f"Error fetching indicator {indicator_id} from IMF: {e}")
            return None

    def _parse_imf_json(self, data: Dict, frequency: str) -> Optional[pd.DataFrame]:
        """Parse IMF API JSON response into DataFrame."""
        try:
            if not data:
                return None

            # IMF returns data in SDMX-JSON format
            # Structure: CompactData.DataSet.Series.Obs
            records = []

            # Navigate the JSON structure
            if 'CompactData' in data and 'DataSet' in data['CompactData']:
                dataset = data['CompactData']['DataSet']

                # Series can be a single object or a list
                series_list = dataset.get('Series', [])
                if not isinstance(series_list, list):
                    series_list = [series_list]

                for series in series_list:
                    if 'Obs' in series:
                        obs_list = series['Obs']
                        if not isinstance(obs_list, list):
                            obs_list = [obs_list]

                        for obs in obs_list:
                            time_period = obs.get('@TIME_PERIOD')
                            value = obs.get('@OBS_VALUE')

                            if time_period and value:
                                # Parse time period based on frequency
                                date = self._parse_imf_date(time_period, frequency)
                                if date:
                                    records.append({
                                        'date': date,
                                        'value': float(value)
                                    })

            if records:
                df = pd.DataFrame(records)
                df = df.sort_values('date')
                return df

            return None

        except Exception as e:
            logger.error(f"Error parsing IMF JSON: {e}")
            return None

    def _parse_imf_date(self, time_period: str, frequency: str) -> Optional[datetime]:
        """Parse IMF time period string to datetime."""
        try:
            # Format depends on frequency:
            # M (Monthly): 2024-01
            # Q (Quarterly): 2024-Q1
            # A (Annual): 2024

            if frequency == 'M':
                # Monthly: YYYY-MM
                return pd.to_datetime(time_period + '-01')
            elif frequency == 'Q':
                # Quarterly: YYYY-Q1 -> convert to first month of quarter
                year, quarter = time_period.split('-Q')
                month = (int(quarter) - 1) * 3 + 1
                return pd.to_datetime(f"{year}-{month:02d}-01")
            elif frequency == 'A':
                # Annual: YYYY
                return pd.to_datetime(f"{time_period}-01-01")
            else:
                # Try generic parsing
                return pd.to_datetime(time_period)

        except Exception as e:
            logger.warning(f"Failed to parse IMF date '{time_period}': {e}")
            return None

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Get configuration schema for IMF plugin."""
        return {
            "name": {
                "type": "string",
                "required": False,
                "label": "Configuration Name",
                "description": "Optional name for this IMF configuration",
                "default": "IMF Data"
            },
            "timeout": {
                "type": "integer",
                "required": False,
                "label": "Request Timeout (seconds)",
                "description": "Timeout for API requests",
                "default": 30
            },
            "note": {
                "type": "info",
                "label": "Indicator Format",
                "description": "Use format: Database.Frequency.Country.Indicator (e.g., IFS.M.US.PMP_IX)"
            }
        }

    @classmethod
    def get_plugin_info(cls) -> Dict[str, Any]:
        """Get plugin metadata."""
        return {
            "name": "International Monetary Fund (IMF)",
            "description": "Free access to IMF Data - International Financial Statistics (IFS), Balance of Payments, Government Finance Statistics, World Economic Outlook. No API key required.",
            "version": "1.0.0",
            "author": "BEACON",
            "free": True,
            "registration_required": False,
            "registration_url": None
        }


# Register the plugin
register_plugin("imf", IMFPlugin)
