"""Yahoo Finance data source plugin."""

import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import logging

from .base import DataSourcePlugin, register_plugin
logger = logging.getLogger(__name__)

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart"
DEFAULT_YAHOO_USER_AGENT = "BEACON/4.0 beacon@bnelabs.com"


class YFinancePlugin(DataSourcePlugin):
    """Plugin for Yahoo Finance data source."""

    def validate_config(self) -> None:
        """Yahoo Finance requires no configuration."""
        # No configuration needed for yfinance
        pass

    def test_connection(self) -> Dict[str, Any]:
        """Test Yahoo Finance connectivity."""
        try:
            # ``Ticker.info`` uses Yahoo's quoteSummary endpoint, which is
            # frequently rate-limited (HTTP 429) even when the public chart
            # endpoint is healthy.  Probe the same chart contract used by
            # collection instead of treating quote metadata as connectivity.
            end_date = datetime.utcnow()
            data = self._fetch_chart_data(
                "AAPL", end_date - timedelta(days=7), end_date
            )

            if data is not None and not data.empty:
                return {
                    "success": True,
                    "message": "Successfully connected to Yahoo Finance",
                    "details": {"test_symbol": "AAPL", "rows": len(data)}
                }
            else:
                return {
                    "success": False,
                    "message": "Could not retrieve data from Yahoo Finance"
                }
        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to connect to Yahoo Finance: {str(e)}"
            }

    def _fetch_chart_data(
        self,
        symbol: str,
        start_date: datetime,
        end_date: datetime,
    ) -> Optional[pd.DataFrame]:
        """Fetch one symbol from Yahoo's public chart JSON endpoint.

        The pinned yfinance client uses quoteSummary for ``Ticker.info`` and
        can report a false outage when that endpoint is rate-limited.  Yahoo's
        chart endpoint is the stable data path needed by Beacon and returns
        the OHLCV arrays without a crumb or API key.
        """
        response = self.http.get(
            f"{YAHOO_CHART_URL}/{symbol}",
            params={
                "period1": int(start_date.timestamp()),
                # Yahoo treats period2 as exclusive; include the requested
                # end date even when callers pass a midnight boundary.
                "period2": int((end_date + timedelta(days=1)).timestamp()),
                "interval": "1d",
                "events": "div,splits",
            },
            headers={"User-Agent": DEFAULT_YAHOO_USER_AGENT},
        )
        response.raise_for_status()
        payload = response.json()
        chart = payload.get("chart") or {}
        result = (chart.get("result") or [None])[0]
        if not result:
            error = chart.get("error") or {}
            raise ValueError(error.get("description") or f"No chart data for {symbol}")

        timestamps = result.get("timestamp") or []
        quote = ((result.get("indicators") or {}).get("quote") or [None])[0]
        if not timestamps or not quote:
            return None

        frame = pd.DataFrame(
            {
                "Date": pd.to_datetime(timestamps, unit="s", utc=True).tz_localize(None),
                "Open": quote.get("open"),
                "High": quote.get("high"),
                "Low": quote.get("low"),
                "Close": quote.get("close"),
                "Volume": quote.get("volume"),
            }
        )
        frame = frame.dropna(subset=["Date", "Close"])
        frame = frame[
            (frame["Date"] >= pd.Timestamp(start_date.date()))
            & (frame["Date"] <= pd.Timestamp(end_date.date()))
        ]
        return frame.sort_values("Date").reset_index(drop=True)

    def fetch_asset_data(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Fetch price data from Yahoo Finance.

        Args:
            symbols: List of ticker symbols
            start_date: Start date
            end_date: End date

        Returns:
            DataFrame with standardized columns
        """
        try:
            frames = []
            for symbol in symbols:
                try:
                    symbol_data = self._fetch_chart_data(symbol, start_date, end_date)
                    if symbol_data is None or symbol_data.empty:
                        logger.warning("No data returned for symbol: %s", symbol)
                        continue
                    symbol_data = symbol_data.copy()
                    symbol_data["Asset"] = symbol
                    required_cols = ['Date', 'Asset', 'Open', 'High', 'Low', 'Close', 'Volume']
                    symbol_data = symbol_data[required_cols]

                    frames.append(symbol_data)
                except Exception as e:
                    logger.warning(f"Failed to process {symbol}: {e}")
                    continue

            if not frames:
                return None

            result = pd.concat(frames, ignore_index=True)
            logger.info(f"Fetched {len(result)} rows for {len(symbols)} symbols from Yahoo Finance")
            return result

        except Exception as e:
            logger.error(f"Error fetching data from Yahoo Finance: {e}")
            return None

    def fetch_indicator_data(
        self,
        indicator_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """Yahoo Finance doesn't provide economic indicators."""
        logger.warning("Yahoo Finance plugin does not support economic indicators")
        return None

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Yahoo Finance requires no credentials; rate limiting is optional."""
        return {
            "rate_limit": {
                "type": "number",
                "required": False,
                "default": 0,
                "label": "Rate Limit (seconds)",
                "help": "Optional delay between Yahoo Finance requests.",
                "min": 0,
            }
        }

    @classmethod
    def get_plugin_info(cls) -> Dict[str, Any]:
        """Get plugin metadata."""
        return {
            "name": "Yahoo Finance",
            "description": "Free stock market data from Yahoo Finance. No API key required.",
            "version": "1.0.0",
            "author": "Liquidity Monitor",
            "free": True,
            "registration_required": False,
            "registration_url": None
        }


# Register the plugin
register_plugin("yfinance", YFinancePlugin)
