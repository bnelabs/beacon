"""European Central Bank (ECB) data source plugin."""

import requests
import pandas as pd
from datetime import datetime
from typing import Dict, Any, List, Optional
import logging
import time

from .base import DataSourcePlugin, register_plugin

logger = logging.getLogger(__name__)


class ECBPlugin(DataSourcePlugin):
    """
    Plugin for European Central Bank Data Portal.

    Provides access to:
    - Exchange rates (EXR)
    - Interest rates (IRS, FM, EON)
    - Banking statistics (BSI, BSP, MIR)
    - Monetary aggregates (ILM)
    - Government finance (GFS)
    - Balance of payments (BP6, IIP)
    """

    def validate_config(self) -> None:
        """ECB API requires no authentication."""
        # No configuration needed for ECB public API
        pass

    def test_connection(self) -> Dict[str, Any]:
        """Test ECB API connectivity."""
        try:
            base_url = "https://data-api.ecb.europa.eu/service/data"
            headers = {
                "Accept": "application/json",
                "User-Agent": "BEACON/2.0"
            }

            # Test with a simple exchange rate query
            url = f"{base_url}/EXR/D.USD.EUR.SP00.A"
            params = {"lastNObservations": 1, "format": "jsondata"}
            response = requests.get(url, headers=headers, params=params, timeout=10)

            if response.status_code == 200:
                return {
                    "success": True,
                    "message": "Successfully connected to ECB Data Portal",
                    "details": {"test_query": "EXR/D.USD.EUR.SP00.A"}
                }
            else:
                return {
                    "success": False,
                    "message": f"ECB API returned status {response.status_code}"
                }
        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to connect to ECB API: {str(e)}"
            }

    def fetch_asset_data(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Fetch exchange rate data from ECB.

        Args:
            symbols: List of currency pairs (e.g., ['USD', 'GBP', 'JPY'])
            start_date: Start date
            end_date: End date

        Returns:
            DataFrame with standardized columns
        """
        try:
            base_url = "https://data-api.ecb.europa.eu/service/data"
            headers = {
                "Accept": "application/json",
                "User-Agent": "BEACON/2.0"
            }

            all_data = []

            for currency in symbols:
                try:
                    # EXR = Exchange Rates, D = Daily, EUR base currency
                    key = f"D.{currency}.EUR.SP00.A"
                    url = f"{base_url}/EXR/{key}"

                    params = {
                        "format": "jsondata",
                        "detail": "dataonly",
                        "startPeriod": start_date.strftime("%Y-%m-%d"),
                        "endPeriod": end_date.strftime("%Y-%m-%d")
                    }

                    response = requests.get(url, headers=headers, params=params, timeout=30)
                    response.raise_for_status()

                    data = response.json()
                    df = self._parse_ecb_json(data)

                    if not df.empty:
                        # Convert to standardized format
                        df['Asset'] = f"{currency}/EUR"
                        df = df.rename(columns={'date': 'Date', 'value': 'Close'})
                        df['Open'] = df['Close']
                        df['High'] = df['Close']
                        df['Low'] = df['Close']
                        df['Volume'] = 0

                        all_data.append(df[['Date', 'Asset', 'Open', 'High', 'Low', 'Close', 'Volume']])

                    # Rate limiting
                    time.sleep(0.5)

                except Exception as e:
                    logger.warning(f"Failed to fetch {currency} from ECB: {e}")
                    continue

            if all_data:
                result = pd.concat(all_data, ignore_index=True)
                logger.info(f"Fetched {len(result)} rows for {len(symbols)} currencies from ECB")
                return result

            return None

        except Exception as e:
            logger.error(f"Error fetching data from ECB: {e}")
            return None

    def fetch_indicator_data(
        self,
        indicator_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Fetch economic indicator data from ECB.

        Args:
            indicator_id: ECB series key (e.g., 'FM/D.U2.EUR.4F.KR.EON.LEV' for EONIA)
            start_date: Start date
            end_date: End date

        Returns:
            DataFrame with Date and Value columns
        """
        try:
            base_url = "https://data-api.ecb.europa.eu/service/data"
            headers = {
                "Accept": "application/json",
                "User-Agent": "BEACON/2.0"
            }

            url = f"{base_url}/{indicator_id}"
            params = {
                "format": "jsondata",
                "detail": "dataonly",
                "startPeriod": start_date.strftime("%Y-%m-%d"),
                "endPeriod": end_date.strftime("%Y-%m-%d")
            }

            response = requests.get(url, headers=headers, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()
            df = self._parse_ecb_json(data)

            if not df.empty:
                df = df.rename(columns={'date': 'Date', 'value': 'Value'})
                logger.info(f"Fetched {len(df)} rows for indicator {indicator_id} from ECB")
                return df[['Date', 'Value']]

            return None

        except Exception as e:
            logger.error(f"Error fetching indicator {indicator_id} from ECB: {e}")
            return None

    def _parse_ecb_json(self, data: Dict) -> pd.DataFrame:
        """Parse ECB SDMX-JSON data format."""
        try:
            if "dataSets" not in data or not data["dataSets"]:
                return pd.DataFrame()

            dataset = data["dataSets"][0]
            structure = data.get("structure", {})

            # Extract observations
            series = dataset.get("series", {})

            records = []
            for series_key, series_data in series.items():
                observations = series_data.get("observations", {})

                for obs_key, obs_value in observations.items():
                    # Get time period
                    time_values = structure.get("dimensions", {}).get("observation", [{}])[0].get("values", [])
                    if int(obs_key) < len(time_values):
                        time_period = time_values[int(obs_key)].get("id")
                    else:
                        time_period = obs_key

                    # Get value (first element if list)
                    value = obs_value[0] if isinstance(obs_value, list) else obs_value

                    record = {
                        "date": self._parse_ecb_date(time_period),
                        "value": float(value) if value is not None else None
                    }

                    records.append(record)

            df = pd.DataFrame(records)

            if not df.empty and "date" in df.columns:
                df = df.sort_values("date")
                df = df.reset_index(drop=True)

            return df

        except Exception as e:
            logger.error(f"Failed to parse ECB data: {e}")
            return pd.DataFrame()

    def _parse_ecb_date(self, period: str) -> datetime:
        """Parse ECB date format (YYYY-MM-DD, YYYY-MM, YYYY-Q1, etc.)."""
        try:
            if len(period) == 10:  # YYYY-MM-DD
                return datetime.strptime(period, "%Y-%m-%d")
            elif len(period) == 7:  # YYYY-MM
                return datetime.strptime(period, "%Y-%m")
            elif "-Q" in period:  # YYYY-Q1
                year, quarter = period.split("-Q")
                month = (int(quarter) - 1) * 3 + 1
                return datetime(int(year), month, 1)
            elif len(period) == 4:  # YYYY
                return datetime(int(period), 1, 1)
            else:
                return datetime.now()
        except:
            return datetime.now()

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """ECB API requires no configuration."""
        return {}

    @classmethod
    def get_plugin_info(cls) -> Dict[str, Any]:
        """Get plugin metadata."""
        return {
            "name": "European Central Bank (ECB)",
            "description": "Free access to ECB Data Portal - exchange rates, interest rates, banking statistics. No API key required.",
            "version": "1.0.0",
            "author": "BEACON",
            "free": True,
            "registration_required": False,
            "registration_url": None
        }


# Register the plugin
register_plugin("ecb", ECBPlugin)
