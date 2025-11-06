"""FDIC API Plugin - US Bank-Level Data

Fetches financial data for FDIC-insured US banks including:
- Asset and liability data
- Liquidity metrics
- Performance ratios (ROA, ROE)
- Deposit and loan information

FREE API - No registration required
Documentation: https://api.fdic.gov/banks/docs
Coverage: 4,380+ active US banks
"""

import pandas as pd
import requests
from datetime import datetime, timedelta
from typing import Dict, Any, Optional
import logging

from backend.plugins.base_plugin import BasePlugin

logger = logging.getLogger(__name__)


class FDICPlugin(BasePlugin):
    """Plugin for FDIC BankFind Suite API."""

    def __init__(self):
        super().__init__()
        self.base_url = "https://api.fdic.gov/banks"
        self.plugin_type = "fdic"

    def fetch_data(
        self,
        item_identifier: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Fetch bank financial data from FDIC API.

        Item identifier format: "FIELD_NAME:CERT_NUMBER" or "TOP_N_BANKS:FIELD"
        Examples:
            - "ASSET:628" - Total assets for JPMorgan Chase (CERT 628)
            - "TOP_50:ASSET" - Top 50 banks by asset size
            - "LIQTOT:628" - Total liquidity for specific bank
        """
        try:
            if item_identifier.startswith("TOP_"):
                # Fetch top N banks
                return self._fetch_top_banks(item_identifier, start_date, end_date)
            else:
                # Fetch specific bank data
                return self._fetch_bank_data(item_identifier, start_date, end_date)

        except Exception as e:
            logger.error(f"Error fetching FDIC data for {item_identifier}: {e}")
            return None

    def _fetch_top_banks(
        self,
        item_identifier: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """Fetch top N banks by specified metric."""
        # Parse identifier: "TOP_50:ASSET"
        parts = item_identifier.split(":")
        n = int(parts[0].replace("TOP_", ""))
        field = parts[1] if len(parts) > 1 else "ASSET"

        # Build API request
        endpoint = f"{self.base_url}/institutions"

        # Common financial fields
        fields = [
            "NAME", "CERT", "CITY", "STNAME",
            "ASSET", "DEP", "LNLSNET", "LIAB",
            "LIQTOT",  # Total liquidity
            "ROA", "ROAPTX",  # Performance ratios
            "EQTOT",  # Total equity
            "DEPDOM",  # Domestic deposits
        ]

        params = {
            "filters": "ACTIVE:1",  # Active banks only
            "fields": ",".join(fields),
            "sort_by": field,
            "sort_order": "DESC",
            "limit": n,
            "format": "json"
        }

        response = requests.get(endpoint, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        if "data" not in data or not data["data"]:
            logger.warning(f"No data returned for {item_identifier}")
            return None

        # Convert to DataFrame
        records = []
        for item in data["data"]:
            bank_data = item["data"]
            # Create a record for each bank with current date
            record = {
                "Date": end_date,  # Use most recent date
                "Value": bank_data.get(field, 0),
                "bank_id": str(bank_data.get("CERT")),
                "bank_name": bank_data.get("NAME"),
                "city": bank_data.get("CITY"),
                "state": bank_data.get("STNAME"),
            }

            # Add all financial fields
            for field_name in fields:
                if field_name in bank_data and field_name not in ["NAME", "CERT", "CITY", "STNAME"]:
                    record[field_name.lower()] = bank_data[field_name]

            records.append(record)

        df = pd.DataFrame(records)
        df["Date"] = pd.to_datetime(df["Date"])

        return df

    def _fetch_bank_data(
        self,
        item_identifier: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """Fetch specific field for a specific bank."""
        # Parse identifier: "ASSET:628"
        parts = item_identifier.split(":")
        field = parts[0]
        cert = parts[1]

        # Fetch current data (FDIC only provides most recent snapshot via institutions API)
        endpoint = f"{self.base_url}/institutions"

        params = {
            "filters": f"CERT:{cert}",
            "fields": f"NAME,CERT,{field},REPDTE",
            "format": "json"
        }

        response = requests.get(endpoint, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        if "data" not in data or not data["data"]:
            logger.warning(f"No data returned for CERT {cert}")
            return None

        bank_data = data["data"][0]["data"]

        # Create DataFrame
        df = pd.DataFrame([{
            "Date": end_date,  # Use most recent date
            "Value": bank_data.get(field, 0),
            "bank_id": str(cert),
            "bank_name": bank_data.get("NAME"),
        }])

        df["Date"] = pd.to_datetime(df["Date"])

        return df

    def test_item(self, item_identifier: str) -> Dict[str, Any]:
        """Test FDIC data access."""
        try:
            end_date = datetime.now()
            start_date = end_date - timedelta(days=1)

            df = self.fetch_data(item_identifier, start_date, end_date)

            if df is not None and not df.empty:
                return {
                    "success": True,
                    "message": f"Successfully accessed FDIC data for {item_identifier}. Found {len(df)} banks.",
                    "details": {
                        "data_points": len(df),
                        "banks": df["bank_name"].tolist() if "bank_name" in df.columns else []
                    }
                }
            else:
                return {
                    "success": False,
                    "message": f"No data found for {item_identifier}",
                    "details": {"error": "Empty dataset"}
                }
        except Exception as e:
            logger.error(f"Error testing FDIC item {item_identifier}: {e}")
            return {
                "success": False,
                "message": f"Failed to access {item_identifier}: {str(e)}",
                "details": {"error": str(e)}
            }

    def get_available_fields(self) -> Dict[str, str]:
        """Return available FDIC data fields with descriptions."""
        return {
            "ASSET": "Total Assets (in thousands)",
            "DEP": "Total Deposits",
            "DEPDOM": "Domestic Deposits",
            "LNLSNET": "Net Loans and Leases",
            "LIAB": "Total Liabilities",
            "LIQTOT": "Total Liquidity",
            "EQTOT": "Total Equity Capital",
            "ROA": "Return on Assets (%)",
            "ROAPTX": "Return on Assets (Pre-Tax %)",
            "ROE": "Return on Equity (%)",
            "NETINC": "Net Income",
            "INTINC": "Interest Income",
            "INTEXP": "Interest Expense",
            "NIMY": "Net Interest Margin (%)",
        }
