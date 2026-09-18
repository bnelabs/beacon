"""European Central Bank (ECB) data source plugin."""

import requests
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import logging
import time

from .base import DataSourcePlugin, register_plugin
from .http_client import retry_call

logger = logging.getLogger(__name__)

FRANKFURTER_BASE_URL = "https://api.frankfurter.app"


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

    # The ECB data portal can time out on a long daily EXR query even though
    # the same series is available when the response is bounded.  Keep each
    # page below the portal's practical response size while preserving the
    # caller's requested date range.
    EXCHANGE_RATE_PAGE_SIZE = 1000
    EXCHANGE_RATE_TIMEOUT = 10
    INDICATOR_TIMEOUT = 30

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
            symbols: List of endpoints or currency codes (e.g., ['EXR/D.USD.EUR.SP00.A'] or ['USD'])
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

            for symbol in symbols:
                try:
                    # Check if symbol is a full endpoint path or just a currency code
                    if '/' in symbol:
                        # Full endpoint provided (e.g., "EXR/D.USD.EUR.SP00.A")
                        url = f"{base_url}/{symbol}"
                        # Extract currency from endpoint for asset name
                        parts = symbol.split('/')
                        if len(parts) >= 2:
                            key_parts = parts[1].split('.')
                            currency = key_parts[1] if len(key_parts) > 1 else "UNKNOWN"
                        else:
                            currency = "UNKNOWN"
                    else:
                        # Just currency code provided (e.g., "USD")
                        currency = symbol
                        key = f"D.{currency}.EUR.SP00.A"
                        url = f"{base_url}/EXR/{key}"

                    try:
                        df = self._fetch_exchange_rate_series(
                            url, headers, start_date, end_date
                        )
                    except Exception as exc:
                        # Frankfurter republishes the ECB reference-rate data
                        # and supports the same EUR-base daily series.  It is
                        # a bounded, source-compatible fallback when the ECB
                        # portal's historical query is unavailable.
                        logger.warning(
                            "ECB portal failed for %s (%s); trying the "
                            "ECB-backed Frankfurter mirror",
                            symbol,
                            exc,
                        )
                        df = self._fetch_frankfurter_series(
                            currency, start_date, end_date
                        )

                    if df.empty:
                        df = self._fetch_frankfurter_series(
                            currency, start_date, end_date
                        )

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
                    logger.warning(f"Failed to fetch {symbol} from ECB: {e}")
                    continue

            if all_data:
                result = pd.concat(all_data, ignore_index=True)
                logger.info(f"Fetched {len(result)} rows for {len(symbols)} symbols from ECB")
                return result

            return None

        except Exception as e:
            logger.error(f"Error fetching data from ECB: {e}")
            return None

    def _fetch_exchange_rate_series(
        self,
        url: str,
        headers: Dict[str, str],
        start_date: datetime,
        end_date: datetime,
    ) -> pd.DataFrame:
        """Fetch a daily EXR series in bounded pages.

        A full 2000--present request for some ECB currency series currently
        hangs or returns HTTP 500, while the official API responds normally to
        the same query with ``firstNObservations``.  Advance the cursor past
        the last returned observation so pages are disjoint and concatenate
        them back into the exact requested window.
        """
        return self._fetch_paged_series(
            url,
            headers,
            start_date,
            end_date,
            page_size=self.EXCHANGE_RATE_PAGE_SIZE,
            timeout=self.EXCHANGE_RATE_TIMEOUT,
            page_delay=0.5,
            retries=1,
        )

    def _fetch_paged_series(
        self,
        url: str,
        headers: Dict[str, str],
        start_date: datetime,
        end_date: datetime,
        *,
        page_size: int,
        timeout: float,
        page_delay: float,
        retries: int,
    ) -> pd.DataFrame:
        """Fetch any ECB series in bounded observation pages."""
        def request_page(params: Dict[str, Any]) -> pd.DataFrame:
            def request_json():
                response = requests.get(
                    url,
                    headers=headers,
                    params=params,
                    timeout=timeout,
                )
                response.raise_for_status()
                return response.json()

            return self._parse_ecb_json(
                retry_call(
                    request_json,
                    retries=retries,
                    backoff_factor=0.5,
                    max_backoff=4.0,
                    exceptions=(requests.RequestException, ValueError),
                )
            )

        def combine(pages: List[pd.DataFrame]) -> pd.DataFrame:
            if not pages:
                return pd.DataFrame()
            return (
                pd.concat(pages, ignore_index=True)
                .drop_duplicates(subset=["date"])
                .sort_values("date")
                .reset_index(drop=True)
            )

        try:
            cursor = start_date
            pages = []

            while cursor.date() <= end_date.date():
                page = request_page(
                    {
                        "format": "jsondata",
                        "detail": "dataonly",
                        "startPeriod": cursor.strftime("%Y-%m-%d"),
                        "endPeriod": end_date.strftime("%Y-%m-%d"),
                        "firstNObservations": page_size,
                    }
                )

                if page.empty:
                    break
                pages.append(page)

                last_date = pd.to_datetime(page["date"], errors="coerce").max()
                # A short page is the provider's explicit end-of-series signal.
                # Do not issue a speculative next request for sparse monthly or
                # quarterly series; some ECB routes return a non-JSON empty body
                # for a cursor beyond their last observation.
                if (
                    len(page) < page_size
                    or pd.isna(last_date)
                    or last_date.date() >= end_date.date()
                ):
                    break

                next_cursor = last_date.to_pydatetime() + timedelta(days=1)
                if next_cursor.date() <= cursor.date():
                    # Defensive guard against a malformed provider response that
                    # never advances the observation cursor.
                    break
                cursor = next_cursor
                if page_delay:
                    time.sleep(page_delay)

            return combine(pages)
        except Exception as forward_error:
            # Some ECB series fail when the server has to seek from their oldest
            # observation, but respond to the equivalent backwards query. This
            # is especially common for CISS. Walk backward from the requested
            # end date with ``lastNObservations`` before giving up to the caller.
            logger.warning(
                "ECB forward paging failed for %s (%s); retrying backwards",
                url,
                forward_error,
            )
            try:
                cursor_end = end_date
                pages = []
                while cursor_end.date() >= start_date.date():
                    page = request_page(
                        {
                            "format": "jsondata",
                            "detail": "dataonly",
                            "startPeriod": start_date.strftime("%Y-%m-%d"),
                            "endPeriod": cursor_end.strftime("%Y-%m-%d"),
                            "lastNObservations": page_size,
                        }
                    )
                    if page.empty:
                        break
                    pages.append(page)
                    first_date = pd.to_datetime(page["date"], errors="coerce").min()
                    if (
                        len(page) < page_size
                        or pd.isna(first_date)
                        or first_date.date() <= start_date.date()
                    ):
                        break
                    previous_cursor = first_date.to_pydatetime() - timedelta(days=1)
                    if previous_cursor.date() >= cursor_end.date():
                        break
                    cursor_end = previous_cursor
                    if page_delay:
                        time.sleep(page_delay)
                return combine(pages)
            except Exception:
                raise forward_error

    def _fetch_frankfurter_series(
        self,
        currency: str,
        start_date: datetime,
        end_date: datetime,
    ) -> pd.DataFrame:
        """Fetch the same EUR-base reference rate from Frankfurter.

        Frankfurter's response is already a date-keyed map, so unlike the
        ECB SDMX response it does not need pagination.  The mirror is only
        used for exchange-rate assets; ECB indicators continue to use their
        original endpoint and fail honestly if that endpoint is unavailable.
        """
        url = (
            f"{FRANKFURTER_BASE_URL}/"
            f"{start_date.strftime('%Y-%m-%d')}..{end_date.strftime('%Y-%m-%d')}"
        )
        response = requests.get(
            url,
            params={"from": "EUR", "to": currency},
            headers={"Accept": "application/json", "User-Agent": "BEACON/2.0"},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        rows = []
        for date_text, rates in (payload.get("rates") or {}).items():
            value = (rates or {}).get(currency)
            if value is None:
                continue
            rows.append({"date": self._parse_ecb_date(date_text), "value": float(value)})
        return pd.DataFrame(rows, columns=["date", "value"])

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
            # The portal is prone to timing out on an unbounded historical
            # request for some series (not only EXR). Use the same official
            # firstNObservations paging contract for rates, CISS and policy
            # series while preserving the requested dates.
            df = self._fetch_paged_series(
                url,
                headers,
                start_date,
                end_date,
                page_size=self.EXCHANGE_RATE_PAGE_SIZE,
                timeout=self.INDICATOR_TIMEOUT,
                page_delay=0.2,
                retries=2,
            )

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
        except (ValueError, TypeError, AttributeError) as e:
            logger.warning(f"Failed to parse ECB date '{period}': {e}. Using current date.")
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
