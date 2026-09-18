"""FRED (Federal Reserve Economic Data) plugin.

Two access paths, one contract
------------------------------

With an API key the official ``fredapi`` client is used. Without one -- or
when the keyed API is temporarily unreachable -- the plugin falls back to
``fredgraph.csv``, the CSV endpoint behind FRED's own graph pages, which needs
no key. The fallback exists because the curated stress-index catalogue
(STLFSI4, KCFSI, CISS, ...) should not be dark on a fresh deployment that has
not registered a key yet; FRED is free either way, the key only buys
documented rate limits and metadata access.

The fallback is deliberately conservative: one series per request, the
declared observation window passed through (``cosd``/``coed``), the configured
``timeout``, and a typed :class:`FredKeylessError` for any non-200 response
so a renamed or retired series is reported as what it is instead of parsing
an HTML error page as data. Missing observations arrive as ``.`` in the CSV
and are dropped, never zero-filled.
"""

from __future__ import annotations

import io
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

from .base import DataSourcePlugin, register_plugin

logger = logging.getLogger(__name__)

KEYLESS_CSV_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv"


class FredKeylessError(ValueError):
    """The keyless fredgraph.csv fallback could not serve the series."""


class FREDPlugin(DataSourcePlugin):
    """Plugin for FRED economic data (keyed API, keyless CSV fallback)."""

    def validate_config(self) -> None:
        """Validate FRED configuration.

        A missing key is not an error: the keyless CSV fallback serves
        indicator fetches. It is logged so the operator knows which path
        the plugin will take.
        """
        api_key = self.config.get('api_key')
        if not api_key or api_key == '':
            logger.info(
                "FRED API key not configured; using the keyless fredgraph.csv "
                "fallback (set FRED_API_KEY for documented rate limits)"
            )

    def test_connection(self) -> Dict[str, Any]:
        """Test FRED connectivity through whichever path is configured."""
        api_key = self.config.get('api_key')
        if not api_key or api_key == '':
            return self._test_keyless_connection()
        try:
            from fredapi import Fred

            fred = Fred(api_key=api_key)
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

    def _test_keyless_connection(self) -> Dict[str, Any]:
        """Probe fredgraph.csv with a short recent window of a stable series."""
        end = datetime.utcnow().date()
        start = end.replace(year=end.year - 1)
        try:
            df = self._fetch_keyless_csv(
                "GDP",
                datetime(start.year, start.month, start.day),
                datetime(end.year, end.month, end.day),
            )
        except FredKeylessError as exc:
            return {"success": False, "message": f"Keyless FRED probe failed: {exc}"}
        if df is None or df.empty:
            return {"success": False, "message": "Keyless FRED probe returned no rows"}
        return {
            "success": True,
            "message": "Connected to FRED via the keyless fredgraph.csv endpoint",
            "details": {
                "test_series": "GDP",
                "latest_value": float(df["Value"].iloc[-1]),
                "access": "keyless_csv",
            },
        }

    def _fetch_keyless_csv(
        self,
        series_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> Optional[pd.DataFrame]:
        """Download one series through fredgraph.csv.

        Returns a ``Date``/``Value`` frame, or ``None`` when the series has no
        observations in the window. Raises :class:`FredKeylessError` on any
        non-200 response or an unparseable payload -- both are facts about the
        endpoint, not empty data.
        """
        params = {
            "id": series_id,
            "cosd": start_date.strftime("%Y-%m-%d"),
            "coed": end_date.strftime("%Y-%m-%d"),
        }
        timeout = float(self.config.get("timeout", 30))
        response = requests.get(KEYLESS_CSV_URL, params=params, timeout=timeout)
        if response.status_code != 200:
            raise FredKeylessError(
                f"fredgraph.csv returned HTTP {response.status_code} for series "
                f"{series_id!r} (a 404 usually means the id was renamed or retired)"
            )
        try:
            raw = pd.read_csv(io.StringIO(response.text))
        except Exception as exc:  # pandas raises a family of parser errors
            raise FredKeylessError(
                f"fredgraph.csv payload for {series_id!r} is not parseable CSV: {exc}"
            ) from exc
        if raw.shape[1] < 2 or raw.empty:
            raise FredKeylessError(
                f"fredgraph.csv payload for {series_id!r} has no date/value columns"
            )
        # Column names vary with the endpoint's vintage ("observation_date" vs
        # "DATE"; series id vs "VALUE"). Position is the stable contract: the
        # first column is the observation date, the second the value.
        raw = raw.iloc[:, :2]
        raw.columns = ["Date", "Value"]
        raw["Date"] = pd.to_datetime(raw["Date"], errors="coerce")
        # FRED encodes missing observations as "."; coerce makes them NaN and
        # they are dropped -- a gap in the record is never a zero.
        raw["Value"] = pd.to_numeric(raw["Value"], errors="coerce")
        df = raw.dropna().reset_index(drop=True)
        if df.empty:
            return None
        return df

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
            DataFrame with Date and Value columns, via the keyed API when a
            key is configured and via fredgraph.csv otherwise.
        """
        api_key = self.config.get('api_key')
        if not api_key or api_key == '':
            return self._fetch_indicator_keyless(indicator_id, start_date, end_date)

        try:
            from fredapi import Fred

            fred = Fred(api_key=api_key)

            # Fetch series data
            data = fred.get_series(
                indicator_id,
                observation_start=start_date.strftime("%Y-%m-%d"),
                observation_end=end_date.strftime("%Y-%m-%d")
            )

            if data is None or data.empty:
                logger.warning(
                    "Keyed FRED API returned no data for %s; trying the "
                    "keyless fredgraph.csv fallback",
                    indicator_id,
                )
                return self._fetch_indicator_keyless(indicator_id, start_date, end_date)

            # Convert to DataFrame
            df = data.reset_index()
            df.columns = ['Date', 'Value']

            # Remove NaN values
            df = df.dropna()

            logger.info(f"Fetched {len(df)} observations for FRED series {indicator_id}")
            return df

        except Exception as e:
            # A configured key should not make the otherwise public keyless
            # path unavailable.  In particular, fredapi raises low-level DNS
            # and timeout errors when api.stlouisfed.org is down, while
            # fredgraph.csv can remain healthy and serve the same series.
            logger.warning(
                "Keyed FRED fetch failed for %s (%s); trying the keyless "
                "fredgraph.csv fallback",
                indicator_id,
                e,
            )
            return self._fetch_indicator_keyless(indicator_id, start_date, end_date)

    def _fetch_indicator_keyless(
        self,
        indicator_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> Optional[pd.DataFrame]:
        """Keyless path: typed errors are logged; the contract still returns None."""
        try:
            df = self._fetch_keyless_csv(indicator_id, start_date, end_date)
        except (FredKeylessError, requests.RequestException) as exc:
            logger.error("Keyless FRED fetch failed for %s: %s", indicator_id, exc)
            return None
        if df is None:
            logger.warning(f"No data returned for FRED series: {indicator_id}")
            return None
        logger.info(
            "Fetched %d observations for FRED series %s via keyless CSV",
            len(df), indicator_id,
        )
        return df

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Get FRED configuration schema."""
        return {
            "api_key": {
                "type": "string",
                "required": False,
                "label": "FRED API Key",
                "help": (
                    "Optional. Without a key the plugin uses the keyless "
                    "fredgraph.csv endpoint. A free key "
                    "(https://fred.stlouisfed.org/docs/api/api_key.html) adds "
                    "documented rate limits."
                ),
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
            "description": (
                "Federal Reserve Economic Data - free economic indicators from "
                "the St. Louis Fed; works keyless via fredgraph.csv, a key "
                "adds documented rate limits"
            ),
            "version": "1.1.0",
            "author": "Liquidity Monitor",
            "free": True,
            "registration_required": False,
            "registration_url": "https://fred.stlouisfed.org/docs/api/api_key.html",
            "data_types": ["economic_indicators"],
            "example_series": ["GDP", "UNRATE", "CPIAUCSL", "DFF", "T10Y2Y"]
        }


# Register the plugin
register_plugin("fred", FREDPlugin)
