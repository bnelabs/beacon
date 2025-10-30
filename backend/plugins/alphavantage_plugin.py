"""Alpha Vantage API Plugin - Global Stock Market Data

Fetches real-time and historical stock prices for publicly traded banks worldwide.

Registration: FREE API key at https://www.alphavantage.co/support/#api-key
Free Tier: 25 API calls/day, 5 calls/minute
Coverage: Global stock exchanges (NYSE, NASDAQ, LSE, TSE, etc.)

Data includes:
- Daily/Weekly/Monthly stock prices (OHLCV)
- Real-time quotes
- Technical indicators
- Fundamental data (earnings, financials)
"""

import pandas as pd
import requests
from datetime import datetime
from typing import Dict, Any, Optional
import logging
import time

from plugins.base_plugin import BasePlugin

logger = logging.getLogger(__name__)


class AlphaVantagePlugin(BasePlugin):
    """Plugin for Alpha Vantage stock market data API."""

    def __init__(self, api_key: Optional[str] = None):
        super().__init__()
        self.base_url = "https://www.alphavantage.co/query"
        self.plugin_type = "alphavantage"
        # API key should be stored in environment variable or config
        self.api_key = api_key or "demo"  # Use demo key for testing
        self._last_call_time = 0
        self._min_interval = 12  # 5 calls per minute = 12 seconds between calls

    def _rate_limit(self):
        """Enforce rate limiting (5 calls/minute for free tier)."""
        elapsed = time.time() - self._last_call_time
        if elapsed < self._min_interval:
            sleep_time = self._min_interval - elapsed
            logger.info(f"Rate limiting: sleeping for {sleep_time:.1f}s")
            time.sleep(sleep_time)
        self._last_call_time = time.time()

    def fetch_data(
        self,
        item_identifier: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Fetch stock price data from Alpha Vantage.

        Item identifier format: "SYMBOL:FUNCTION"
        Examples:
            - "JPM:DAILY" - Daily prices for JP Morgan Chase
            - "BAC:WEEKLY" - Weekly prices for Bank of America
            - "C:MONTHLY" - Monthly prices for Citigroup
            - "GS:INTRADAY" - Intraday prices for Goldman Sachs
        """
        try:
            parts = item_identifier.split(":")
            symbol = parts[0]
            function = parts[1] if len(parts) > 1 else "DAILY"

            self._rate_limit()

            if function == "DAILY":
                return self._fetch_daily(symbol, start_date, end_date)
            elif function == "WEEKLY":
                return self._fetch_weekly(symbol, start_date, end_date)
            elif function == "MONTHLY":
                return self._fetch_monthly(symbol, start_date, end_date)
            elif function == "INTRADAY":
                return self._fetch_intraday(symbol, start_date, end_date)
            else:
                logger.error(f"Unknown function: {function}")
                return None

        except Exception as e:
            logger.error(f"Error fetching Alpha Vantage data for {item_identifier}: {e}")
            return None

    def _fetch_daily(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """Fetch daily stock prices."""
        params = {
            "function": "TIME_SERIES_DAILY",
            "symbol": symbol,
            "outputsize": "full",  # Get full history
            "apikey": self.api_key
        }

        response = requests.get(self.base_url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        if "Time Series (Daily)" not in data:
            logger.warning(f"No daily data for {symbol}: {data.get('Note', data.get('Error Message', 'Unknown error'))}")
            return None

        # Convert to DataFrame
        time_series = data["Time Series (Daily)"]
        records = []

        for date_str, values in time_series.items():
            date = pd.to_datetime(date_str)
            if start_date <= date <= end_date:
                records.append({
                    "Date": date,
                    "Open": float(values["1. open"]),
                    "High": float(values["2. high"]),
                    "Low": float(values["3. low"]),
                    "Close": float(values["4. close"]),
                    "Volume": int(values["5. volume"]),
                    "symbol": symbol
                })

        if not records:
            return None

        df = pd.DataFrame(records)
        df = df.sort_values("Date")
        df["Value"] = df["Close"]  # For compatibility with engine

        return df

    def _fetch_weekly(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """Fetch weekly stock prices."""
        params = {
            "function": "TIME_SERIES_WEEKLY",
            "symbol": symbol,
            "apikey": self.api_key
        }

        response = requests.get(self.base_url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        if "Weekly Time Series" not in data:
            logger.warning(f"No weekly data for {symbol}")
            return None

        time_series = data["Weekly Time Series"]
        records = []

        for date_str, values in time_series.items():
            date = pd.to_datetime(date_str)
            if start_date <= date <= end_date:
                records.append({
                    "Date": date,
                    "Open": float(values["1. open"]),
                    "High": float(values["2. high"]),
                    "Low": float(values["3. low"]),
                    "Close": float(values["4. close"]),
                    "Volume": int(values["5. volume"]),
                    "symbol": symbol
                })

        if not records:
            return None

        df = pd.DataFrame(records)
        df = df.sort_values("Date")
        df["Value"] = df["Close"]

        return df

    def _fetch_monthly(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """Fetch monthly stock prices."""
        params = {
            "function": "TIME_SERIES_MONTHLY",
            "symbol": symbol,
            "apikey": self.api_key
        }

        response = requests.get(self.base_url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        if "Monthly Time Series" not in data:
            logger.warning(f"No monthly data for {symbol}")
            return None

        time_series = data["Monthly Time Series"]
        records = []

        for date_str, values in time_series.items():
            date = pd.to_datetime(date_str)
            if start_date <= date <= end_date:
                records.append({
                    "Date": date,
                    "Open": float(values["1. open"]),
                    "High": float(values["2. high"]),
                    "Low": float(values["3. low"]),
                    "Close": float(values["4. close"]),
                    "Volume": int(values["5. volume"]),
                    "symbol": symbol
                })

        if not records:
            return None

        df = pd.DataFrame(records)
        df = df.sort_values("Date")
        df["Value"] = df["Close"]

        return df

    def _fetch_intraday(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """Fetch intraday stock prices (1-minute intervals)."""
        params = {
            "function": "TIME_SERIES_INTRADAY",
            "symbol": symbol,
            "interval": "5min",
            "outputsize": "full",
            "apikey": self.api_key
        }

        response = requests.get(self.base_url, params=params, timeout=30)
        response.raise_for_status()

        data = response.json()

        time_series_key = "Time Series (5min)"
        if time_series_key not in data:
            logger.warning(f"No intraday data for {symbol}")
            return None

        time_series = data[time_series_key]
        records = []

        for datetime_str, values in time_series.items():
            dt = pd.to_datetime(datetime_str)
            if start_date <= dt <= end_date:
                records.append({
                    "Date": dt,
                    "Open": float(values["1. open"]),
                    "High": float(values["2. high"]),
                    "Low": float(values["3. low"]),
                    "Close": float(values["4. close"]),
                    "Volume": int(values["5. volume"]),
                    "symbol": symbol
                })

        if not records:
            return None

        df = pd.DataFrame(records)
        df = df.sort_values("Date")
        df["Value"] = df["Close"]

        return df

    def test_item(self, item_identifier: str) -> Dict[str, Any]:
        """Test Alpha Vantage data access."""
        try:
            end_date = datetime.now()
            start_date = datetime(end_date.year, 1, 1)  # YTD data

            df = self.fetch_data(item_identifier, start_date, end_date)

            if df is not None and not df.empty:
                return {
                    "success": True,
                    "message": f"Successfully accessed Alpha Vantage data for {item_identifier}. Found {len(df)} data points.",
                    "details": {
                        "data_points": len(df),
                        "date_range": f"{df['Date'].min().date()} to {df['Date'].max().date()}"
                    }
                }
            else:
                return {
                    "success": False,
                    "message": f"No data found for {item_identifier}. Note: Free tier limited to 25 calls/day.",
                    "details": {"error": "Empty dataset or rate limit exceeded"}
                }
        except Exception as e:
            logger.error(f"Error testing Alpha Vantage item {item_identifier}: {e}")
            return {
                "success": False,
                "message": f"Failed to access {item_identifier}: {str(e)}",
                "details": {"error": str(e)}
            }

    def get_bank_symbols(self, country: str = "US") -> Dict[str, str]:
        """Return common bank stock symbols by country."""
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
            },
            "EU": {
                "HSBA.L": "HSBC Holdings (London)",
                "BARC.L": "Barclays (London)",
                "LLOY.L": "Lloyds Banking Group (London)",
                "BNP.PA": "BNP Paribas (Paris)",
                "SAN.MC": "Banco Santander (Madrid)",
                "DBK.DE": "Deutsche Bank (Frankfurt)",
            },
            "JP": {
                "8306.T": "Mitsubishi UFJ Financial (Tokyo)",
                "8316.T": "Sumitomo Mitsui Financial (Tokyo)",
                "8411.T": "Mizuho Financial Group (Tokyo)",
            }
        }

        return symbols.get(country, {})
