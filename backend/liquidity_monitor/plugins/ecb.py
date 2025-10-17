"""ECB (European Central Bank) Data Portal plugin."""

import requests
import pandas as pd
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import time

from liquidity_monitor.plugins.base import DataSourcePlugin


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

    def __init__(self, config: Dict):
        super().__init__(config)
        self.base_url = "https://data-api.ecb.europa.eu/service/data"
        self.headers = {
            "Accept": "application/json",
            "User-Agent": "LiquidityMonitor/2.0"
        }

    def test_connection(self) -> bool:
        """Test API connectivity."""
        try:
            # Test with a simple exchange rate query
            url = f"{self.base_url}/EXR/D.USD.EUR.SP00.A"
            params = {"lastNObservations": 1, "format": "jsondata"}
            response = requests.get(url, headers=self.headers, params=params, timeout=10)
            return response.status_code == 200
        except Exception as e:
            print(f"ECB connection test failed: {e}")
            return False

    def fetch_data(self,
                   flow_ref: str,
                   key: str = "",
                   start_date: Optional[str] = None,
                   end_date: Optional[str] = None,
                   **kwargs) -> pd.DataFrame:
        """
        Fetch data from ECB Data Portal.

        Args:
            flow_ref: Data flow reference (e.g., 'EXR' for exchange rates)
            key: Series key (e.g., 'D.USD.EUR.SP00.A' for daily USD/EUR rate)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            **kwargs: Additional query parameters

        Returns:
            DataFrame with columns: date, value, [dimensions...]
        """
        # Build URL
        url = f"{self.base_url}/{flow_ref}"
        if key:
            url = f"{url}/{key}"

        # Build parameters
        params = {
            "format": "jsondata",
            "detail": "dataonly"
        }

        if start_date:
            params["startPeriod"] = start_date
        if end_date:
            params["endPeriod"] = end_date

        params.update(kwargs)

        # Make request
        try:
            response = requests.get(url, headers=self.headers, params=params, timeout=30)
            response.raise_for_status()

            data = response.json()

            # Parse ECB JSON structure
            df = self._parse_ecb_json(data)

            # Rate limiting
            time.sleep(0.5)

            return df

        except requests.exceptions.RequestException as e:
            raise Exception(f"ECB API request failed: {e}")

    def _parse_ecb_json(self, data: Dict) -> pd.DataFrame:
        """Parse ECB JSON data format."""
        try:
            # ECB uses SDMX-JSON format
            if "dataSets" not in data or not data["dataSets"]:
                return pd.DataFrame()

            dataset = data["dataSets"][0]
            structure = data.get("structure", {})

            # Extract dimensions
            dimensions = structure.get("dimensions", {}).get("series", [])

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

                    # Add dimension values
                    series_indices = series_key.split(":")
                    for i, dim in enumerate(dimensions):
                        if i < len(series_indices):
                            dim_values = dim.get("values", [])
                            dim_index = int(series_indices[i])
                            if dim_index < len(dim_values):
                                dim_value = dim_values[dim_index]
                                record[dim.get("id")] = dim_value.get("id")

                    records.append(record)

            df = pd.DataFrame(records)

            if not df.empty and "date" in df.columns:
                df = df.sort_values("date")
                df = df.reset_index(drop=True)

            return df

        except Exception as e:
            raise Exception(f"Failed to parse ECB data: {e}")

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

    def fetch_exchange_rates(self,
                            currencies: List[str],
                            base_currency: str = "EUR",
                            frequency: str = "D",
                            start_date: Optional[str] = None,
                            end_date: Optional[str] = None) -> pd.DataFrame:
        """
        Fetch exchange rates.

        Args:
            currencies: List of currency codes (e.g., ['USD', 'GBP', 'JPY'])
            base_currency: Base currency (default: EUR)
            frequency: D (daily), M (monthly)
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
        """
        all_data = []

        for currency in currencies:
            key = f"{frequency}.{currency}.{base_currency}.SP00.A"
            df = self.fetch_data("EXR", key, start_date, end_date)

            if not df.empty:
                df["currency_pair"] = f"{currency}/{base_currency}"
                all_data.append(df)

        if all_data:
            return pd.concat(all_data, ignore_index=True)
        return pd.DataFrame()

    def fetch_interest_rates(self,
                            rate_type: str = "EONIA",
                            start_date: Optional[str] = None,
                            end_date: Optional[str] = None) -> pd.DataFrame:
        """
        Fetch interest rates.

        Args:
            rate_type: Rate type (EONIA, EURIBOR, etc.)
            start_date: Start date
            end_date: End date
        """
        # FM = Financial Market Data
        # D = Daily frequency
        # N = Overnight (for EONIA)
        if rate_type == "EONIA":
            key = "D.U2.EUR.4F.KR.EON.LEV"
        else:
            key = ""  # Will fetch all if empty

        return self.fetch_data("FM", key, start_date, end_date)

    def fetch_banking_statistics(self,
                                 stat_type: str = "deposits",
                                 start_date: Optional[str] = None,
                                 end_date: Optional[str] = None) -> pd.DataFrame:
        """
        Fetch banking statistics.

        Args:
            stat_type: Type of statistic (deposits, loans, reserves)
            start_date: Start date
            end_date: End date
        """
        # BSI = Balance Sheet Items
        # This is a simplified query - actual BSI has complex dimensions
        return self.fetch_data("BSI", "", start_date, end_date, lastNObservations=100)


# Register plugin
def register():
    """Register ECB plugin."""
    return {
        "name": "ecb",
        "display_name": "European Central Bank",
        "plugin_class": ECBPlugin,
        "description": "European Central Bank Data Portal - Exchange rates, interest rates, banking statistics",
        "requires_api_key": False,
        "regions": ["europe", "global"],
        "categories": ["exchange_rates", "interest_rates", "banking", "central_bank"]
    }
