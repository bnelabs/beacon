"""ECB Banking Supervision Plugin - European Bank Data

Fetches supervisory banking statistics for European significant institutions (SIs)
from the European Central Bank's banking supervision data portal.

Registration: FREE - No API key required
Coverage: 114+ significant European banks
Data includes:
- COREP (capital adequacy information)
- FINREP (financial information)
- Supervisory statistics
- Quarterly updates

Documentation: https://data.ecb.europa.eu/
"""

import pandas as pd
import requests
from datetime import datetime
from typing import Dict, Any, Optional
import logging

from plugins.base_plugin import BasePlugin

logger = logging.getLogger(__name__)


class ECBBankingPlugin(BasePlugin):
    """Plugin for ECB Banking Supervision data API."""

    def __init__(self):
        super().__init__()
        self.base_url = "https://data-api.ecb.europa.eu/service/data"
        self.plugin_type = "ecb_banking"

    def fetch_data(
        self,
        item_identifier: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Fetch European banking supervision data from ECB.

        Item identifier format: "DATASET.KEY"
        Examples:
            - "CBD.S.Q.N.A.A00.A.1.U2.2240.Z01.E" - Capital adequacy data
            - "BSI.M.N.A.A00.A.1.U2.2240.Z01.E" - Balance sheet items
        """
        try:
            # Parse dataset and key
            parts = item_identifier.split(".", 1)
            dataset = parts[0]
            key = parts[1] if len(parts) > 1 else ""

            # Format dates for ECB API
            start_period = start_date.strftime("%Y-%m")
            end_period = end_date.strftime("%Y-%m")

            # Build API request
            endpoint = f"{self.base_url}/{dataset}/{key}"

            params = {
                "startPeriod": start_period,
                "endPeriod": end_period,
                "format": "csvdata",  # CSV format for easier parsing
            }

            response = requests.get(endpoint, params=params, timeout=60)
            response.raise_for_status()

            # Parse CSV response
            from io import StringIO
            df = pd.read_csv(StringIO(response.text))

            if df.empty:
                logger.warning(f"No data returned for {item_identifier}")
                return None

            # Standardize columns
            if 'TIME_PERIOD' in df.columns:
                df['Date'] = pd.to_datetime(df['TIME_PERIOD'])
            elif 'TIME' in df.columns:
                df['Date'] = pd.to_datetime(df['TIME'])
            else:
                logger.error(f"No time column found in ECB data")
                return None

            if 'OBS_VALUE' in df.columns:
                df['Value'] = pd.to_numeric(df['OBS_VALUE'], errors='coerce')
            else:
                logger.error(f"No value column found in ECB data")
                return None

            # Filter by date range
            df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]

            # Keep essential columns
            columns_to_keep = ['Date', 'Value']

            # Add bank identifier if available
            if 'REF_AREA' in df.columns:
                df['bank_id'] = df['REF_AREA']
                columns_to_keep.append('bank_id')

            if 'TITLE' in df.columns:
                df['indicator'] = df['TITLE']
                columns_to_keep.append('indicator')

            df = df[columns_to_keep]
            df = df.sort_values('Date')

            return df

        except Exception as e:
            logger.error(f"Error fetching ECB banking data for {item_identifier}: {e}")
            return None

    def test_item(self, item_identifier: str) -> Dict[str, Any]:
        """Test ECB banking data access."""
        try:
            end_date = datetime.now()
            start_date = datetime(end_date.year - 1, 1, 1)  # Last year

            df = self.fetch_data(item_identifier, start_date, end_date)

            if df is not None and not df.empty:
                return {
                    "success": True,
                    "message": f"Successfully accessed ECB data for {item_identifier}. Found {len(df)} data points.",
                    "details": {
                        "data_points": len(df),
                        "date_range": f"{df['Date'].min().date()} to {df['Date'].max().date()}"
                    }
                }
            else:
                return {
                    "success": False,
                    "message": f"No data found for {item_identifier}",
                    "details": {"error": "Empty dataset"}
                }
        except Exception as e:
            logger.error(f"Error testing ECB item {item_identifier}: {e}")
            return {
                "success": False,
                "message": f"Failed to access {item_identifier}: {str(e)}",
                "details": {"error": str(e)}
            }

    def get_available_datasets(self) -> Dict[str, str]:
        """Return available ECB banking supervision datasets."""
        return {
            "CBD": "Consolidated Banking Data (Capital requirements)",
            "BSI": "Balance Sheet Items",
            "SSI": "Supervisory Statistics - Significant Institutions",
            "LSI": "Supervisory Statistics - Less Significant Institutions",
            "MIR": "MFI Interest Rates",
            "SEC": "Securities Holdings Statistics",
        }

    def get_common_indicators(self) -> Dict[str, str]:
        """Return common banking indicators."""
        return {
            "CAPITAL_RATIO": "Capital adequacy ratio (CET1)",
            "LEVERAGE_RATIO": "Leverage ratio",
            "NPL_RATIO": "Non-performing loans ratio",
            "LIQUIDITY_RATIO": "Liquidity coverage ratio (LCR)",
            "ROA": "Return on assets",
            "ROE": "Return on equity",
            "COST_INCOME": "Cost-to-income ratio",
        }
