"""Financial Modeling Prep (FMP) Plugin - Global Bank Fundamentals

Fetches comprehensive financial data, ratios, and fundamentals for publicly
traded banks worldwide.

Registration: FREE tier available at https://site.financialmodelingprep.com/developer/docs
Free Tier: 250 requests/day
Coverage: Global stock exchanges, 30+ years historical data

Data includes:
- Financial statements (Income, Balance Sheet, Cash Flow)
- Financial ratios (Liquidity, Profitability, Leverage)
- Company profile and metrics
- Stock prices and dividends
- Earnings and estimates
"""

import os
import pandas as pd
import requests
from datetime import datetime
from typing import Dict, Any, Optional, List
import logging
import time

from .base import DataSourcePlugin, register_plugin

logger = logging.getLogger(__name__)


class FMPPlugin(DataSourcePlugin):
    """Plugin for Financial Modeling Prep API."""

    def __init__(self, config: Dict[str, Any] = None):
        config = config or {}
        super().__init__(config)
        self.base_url = "https://financialmodelingprep.com/api/v3"
        self.plugin_type = "fmp"
        # API key should be stored in environment variable or config
        self.api_key = self.config.get('api_key') or os.getenv('FMP_API_KEY')
        if not self.api_key:
            raise ValueError("Financial Modeling Prep API key is required. Set it in connector config or FMP_API_KEY env var.")
        # Persist resolved key in config to keep downstream consumers consistent
        self.config['api_key'] = self.api_key
        self._last_call_time = 0
        self._min_interval = 0.25  # 250/day = ~4 calls per second max

    def validate_config(self) -> None:
        """Validate FMP configuration."""
        api_key = (self.config or {}).get('api_key') or os.getenv('FMP_API_KEY')
        if not api_key:
            raise ValueError("Financial Modeling Prep API key is required. Obtain one at https://site.financialmodelingprep.com/developer/docs and set FMP_API_KEY or provide it in plugin config.")

    def test_connection(self) -> Dict[str, Any]:
        """Test FMP API connection."""
        try:
            endpoint = f"{self.base_url}/profile/JPM"
            params = {"apikey": self.api_key}
            response = requests.get(endpoint, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            if data and isinstance(data, list) and len(data) > 0:
                return {
                    "success": True,
                    "message": "Successfully connected to Financial Modeling Prep API"
                }
            return {
                "success": False,
                "message": "Invalid API response"
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to connect: {str(e)}"
            }

    def fetch_indicator_data(self, indicator_id: str, start_date: datetime, end_date: datetime) -> Optional[pd.DataFrame]:
        """Alias for fetch_data to match base class interface."""
        return self.fetch_data(indicator_id, start_date, end_date)

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """FMP API configuration schema."""
        return {
            "api_key": {
                "type": "string",
                "required": True,
                "label": "API Key",
                "help": "Get your API key from https://site.financialmodelingprep.com/developer/docs",
                "secret": True
            }
        }

    @classmethod
    def get_plugin_info(cls) -> Dict[str, Any]:
        """Get plugin metadata."""
        return {
            "name": "Financial Modeling Prep",
            "description": "Global bank fundamentals and financial data",
            "version": "1.0.0",
            "author": "BEACON",
            "free": True,
            "registration_required": True,
            "registration_url": "https://site.financialmodelingprep.com/developer/docs"
        }

    def _rate_limit(self):
        """Enforce rate limiting (250 calls/day for free tier)."""
        elapsed = time.time() - self._last_call_time
        if elapsed < self._min_interval:
            sleep_time = self._min_interval - elapsed
            time.sleep(sleep_time)
        self._last_call_time = time.time()

    def fetch_data(
        self,
        item_identifier: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Fetch financial data from FMP.

        Item identifier format: "SYMBOL:ENDPOINT"
        Examples:
            - "JPM:ratios" - Financial ratios for JP Morgan
            - "BAC:income-statement" - Income statement for Bank of America
            - "C:balance-sheet-statement" - Balance sheet for Citigroup
            - "GS:cash-flow-statement" - Cash flow for Goldman Sachs
            - "WFC:key-metrics" - Key metrics for Wells Fargo
        """
        try:
            parts = item_identifier.split(":")
            symbol = parts[0]
            endpoint = parts[1] if len(parts) > 1 else "ratios"

            self._rate_limit()

            if endpoint == "ratios":
                return self._fetch_ratios(symbol, start_date, end_date)
            elif endpoint == "income-statement":
                return self._fetch_income_statement(symbol, start_date, end_date)
            elif endpoint == "balance-sheet-statement":
                return self._fetch_balance_sheet(symbol, start_date, end_date)
            elif endpoint == "cash-flow-statement":
                return self._fetch_cash_flow(symbol, start_date, end_date)
            elif endpoint == "key-metrics":
                return self._fetch_key_metrics(symbol, start_date, end_date)
            elif endpoint == "profile":
                return self._fetch_company_profile(symbol)
            else:
                logger.error(f"Unknown endpoint: {endpoint}")
                return None

        except Exception as e:
            logger.error(f"Error fetching FMP data for {item_identifier}: {e}")
            return None

    def _fetch_ratios(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """Fetch financial ratios (liquidity, profitability, leverage)."""
        endpoint = f"{self.base_url}/ratios/{symbol}"

        params = {
            "apikey": self.api_key,
            "limit": 40  # Get enough history
        }

        response = requests.get(endpoint, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        if not data or not isinstance(data, list):
            logger.warning(f"No ratios data for {symbol}")
            return None

        # Convert to DataFrame
        df = pd.DataFrame(data)

        if 'date' not in df.columns:
            return None

        df['Date'] = pd.to_datetime(df['date'])
        df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]

        if df.empty:
            return None

        # Extract key liquidity and risk metrics
        ratios = []
        for _, row in df.iterrows():
            record = {
                'Date': row['Date'],
                'symbol': symbol,
                # Liquidity ratios
                'current_ratio': row.get('currentRatio'),
                'quick_ratio': row.get('quickRatio'),
                'cash_ratio': row.get('cashRatio'),
                # Profitability ratios
                'return_on_assets': row.get('returnOnAssets'),
                'return_on_equity': row.get('returnOnEquity'),
                'net_profit_margin': row.get('netProfitMargin'),
                # Leverage ratios
                'debt_ratio': row.get('debtRatio'),
                'debt_equity_ratio': row.get('debtEquityRatio'),
                # Efficiency ratios
                'asset_turnover': row.get('assetTurnover'),
            }
            ratios.append(record)

        result_df = pd.DataFrame(ratios)
        result_df['Value'] = result_df['current_ratio']  # Use current ratio as primary value
        result_df = result_df.sort_values('Date')

        return result_df

    def _fetch_income_statement(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """Fetch income statement data."""
        endpoint = f"{self.base_url}/income-statement/{symbol}"

        params = {
            "apikey": self.api_key,
            "limit": 40
        }

        response = requests.get(endpoint, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        if not data or not isinstance(data, list):
            return None

        df = pd.DataFrame(data)

        if 'date' not in df.columns:
            return None

        df['Date'] = pd.to_datetime(df['date'])
        df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]

        if df.empty:
            return None

        # Extract key metrics
        df['Value'] = df['netIncome']
        df['symbol'] = symbol
        df['revenue'] = df['revenue']
        df['operating_income'] = df['operatingIncome']
        df['interest_income'] = df.get('interestIncome', 0)
        df['interest_expense'] = df.get('interestExpense', 0)

        df = df.sort_values('Date')

        return df[['Date', 'Value', 'symbol', 'revenue', 'operating_income', 'interest_income', 'interest_expense']]

    def _fetch_balance_sheet(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """Fetch balance sheet data."""
        endpoint = f"{self.base_url}/balance-sheet-statement/{symbol}"

        params = {
            "apikey": self.api_key,
            "limit": 40
        }

        response = requests.get(endpoint, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        if not data or not isinstance(data, list):
            return None

        df = pd.DataFrame(data)

        if 'date' not in df.columns:
            return None

        df['Date'] = pd.to_datetime(df['date'])
        df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]

        if df.empty:
            return None

        # Extract key balance sheet items
        df['Value'] = df['totalAssets']
        df['symbol'] = symbol
        df['total_assets'] = df['totalAssets']
        df['total_liabilities'] = df['totalLiabilities']
        df['total_equity'] = df['totalEquity']
        df['cash'] = df.get('cashAndCashEquivalents', 0)
        df['total_debt'] = df.get('totalDebt', 0)

        df = df.sort_values('Date')

        return df[['Date', 'Value', 'symbol', 'total_assets', 'total_liabilities', 'total_equity', 'cash', 'total_debt']]

    def _fetch_cash_flow(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """Fetch cash flow statement data."""
        endpoint = f"{self.base_url}/cash-flow-statement/{symbol}"

        params = {
            "apikey": self.api_key,
            "limit": 40
        }

        response = requests.get(endpoint, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        if not data or not isinstance(data, list):
            return None

        df = pd.DataFrame(data)

        if 'date' not in df.columns:
            return None

        df['Date'] = pd.to_datetime(df['date'])
        df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]

        if df.empty:
            return None

        df['Value'] = df['freeCashFlow']
        df['symbol'] = symbol
        df['operating_cash_flow'] = df['operatingCashFlow']
        df['free_cash_flow'] = df['freeCashFlow']

        df = df.sort_values('Date')

        return df[['Date', 'Value', 'symbol', 'operating_cash_flow', 'free_cash_flow']]

    def _fetch_key_metrics(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """Fetch key metrics and valuation ratios."""
        endpoint = f"{self.base_url}/key-metrics/{symbol}"

        params = {
            "apikey": self.api_key,
            "limit": 40
        }

        response = requests.get(endpoint, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        if not data or not isinstance(data, list):
            return None

        df = pd.DataFrame(data)

        if 'date' not in df.columns:
            return None

        df['Date'] = pd.to_datetime(df['date'])
        df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]

        if df.empty:
            return None

        df['Value'] = df.get('marketCap', 0)
        df['symbol'] = symbol

        df = df.sort_values('Date')

        return df

    def _fetch_company_profile(self, symbol: str) -> Optional[pd.DataFrame]:
        """Fetch company profile information."""
        endpoint = f"{self.base_url}/profile/{symbol}"

        params = {
            "apikey": self.api_key
        }

        response = requests.get(endpoint, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        if not data or not isinstance(data, list):
            return None

        # Convert to DataFrame with current date
        df = pd.DataFrame(data)
        df['Date'] = datetime.now()
        df['Value'] = df.get('mktCap', 0)

        return df

    def test_item(self, item_identifier: str) -> Dict[str, Any]:
        """Test FMP data access."""
        try:
            end_date = datetime.now()
            start_date = datetime(end_date.year - 1, 1, 1)

            df = self.fetch_data(item_identifier, start_date, end_date)

            if df is not None and not df.empty:
                return {
                    "success": True,
                    "message": f"Successfully accessed FMP data for {item_identifier}. Found {len(df)} data points.",
                    "details": {
                        "data_points": len(df),
                        "date_range": f"{df['Date'].min().date()} to {df['Date'].max().date()}"
                    }
                }
            else:
                return {
                    "success": False,
                    "message": f"No data found for {item_identifier}. Note: Free tier limited to 250 calls/day.",
                    "details": {"error": "Empty dataset or rate limit exceeded"}
                }
        except Exception as e:
            logger.error(f"Error testing FMP item {item_identifier}: {e}")
            return {
                "success": False,
                "message": f"Failed to access {item_identifier}: {str(e)}",
                "details": {"error": str(e)}
            }

    def get_bank_symbols_by_country(self, country: str = "US") -> Dict[str, str]:
        """Return major bank stock symbols by country."""
        symbols = {
            "US": {
                "JPM": "JPMorgan Chase & Co.",
                "BAC": "Bank of America Corp",
                "WFC": "Wells Fargo & Company",
                "C": "Citigroup Inc.",
                "USB": "U.S. Bancorp",
                "PNC": "PNC Financial Services",
                "TFC": "Truist Financial Corp",
                "GS": "Goldman Sachs Group Inc.",
                "MS": "Morgan Stanley",
                "BK": "Bank of New York Mellon Corp",
                "COF": "Capital One Financial",
                "SCHW": "Charles Schwab Corp",
            },
            "EU": {
                "HSBA.L": "HSBC Holdings (UK)",
                "BARC.L": "Barclays (UK)",
                "LLOY.L": "Lloyds Banking Group (UK)",
                "BNP.PA": "BNP Paribas (France)",
                "SAN.MC": "Banco Santander (Spain)",
                "DBK.DE": "Deutsche Bank (Germany)",
                "BBVA.MC": "BBVA (Spain)",
                "ISP.MI": "Intesa Sanpaolo (Italy)",
                "UCG.MI": "UniCredit (Italy)",
                "GLE.PA": "Société Générale (France)",
            },
            "JP": {
                "8306.T": "Mitsubishi UFJ Financial",
                "8316.T": "Sumitomo Mitsui Financial",
                "8411.T": "Mizuho Financial Group",
                "8309.T": "Sumitomo Mitsui Trust",
            },
            "CN": {
                "1398.HK": "Industrial & Commercial Bank of China",
                "3988.HK": "Bank of China",
                "0939.HK": "China Construction Bank",
                "1288.HK": "Agricultural Bank of China",
            },
            "BR": {
                "ITUB": "Itaú Unibanco (Brazil)",
                "BBD": "Banco Bradesco (Brazil)",
            },
        }

        return symbols.get(country, {})


# Register the plugin
register_plugin("fmp", FMPPlugin)
