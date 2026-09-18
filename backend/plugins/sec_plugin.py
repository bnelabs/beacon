"""SEC Edgar API plugin for company filings data."""

from typing import Dict, Any, List, Optional
import pandas as pd
import requests
from datetime import datetime, timedelta
from .base import DataSourcePlugin, register_plugin
from .http_client import retry_call
from backend.exceptions import DataSourceUnavailableError
import logging

logger = logging.getLogger(__name__)

SEC_DATA_URL = "https://data.sec.gov"
SEC_TICKER_URL = "https://www.sec.gov/files/company_tickers.json"
DEFAULT_SEC_USER_AGENT = "BEACON/4.0 beacon@bnelabs.com"
KNOWN_SEC_CIKS = {
    # The catalogue's keyless SEC rows use these stable issuers. Avoiding the
    # multi-megabyte ticker manifest makes those jobs independent of a second
    # SEC endpoint that is especially prone to proxy/read timeouts.
    "JPM": "0000019617",
    "BLK": "0001364742",
}


class SECPlugin(DataSourcePlugin):
    """
    SEC Edgar API plugin for accessing company filings.

    Data from: https://sec-api.io
    API Documentation: https://sec-api.io/docs

    Features:
    - Company financials (10-K, 10-Q filings)
    - Institutional holdings (13F filings)
    - Insider trading (Form 4)
    - Company facts and metrics

    Pricing:
    - Free tier: 100 requests/month
    - Starter: $49/month, 1,000 requests
    - Pro: $99/month, 10,000 requests
    - Enterprise: Custom pricing
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize SEC API plugin.

        Args:
            config: Configuration dictionary with 'api_key'
        """
        self.config = config or {}
        self.api_key = self.config.get('api_key', '')
        self._query_api = None
        self._render_api = None
        # Call the base initializer so validate_config is part of the normal
        # plugin lifecycle.  Keyless SEC EDGAR access is valid, so validation
        # no longer rejects a source merely because SEC_API_KEY is empty.
        super().__init__(self.config)

    @property
    def query_api(self):
        """Lazy load Query API."""
        if self._query_api is None:
            from sec_api import QueryApi
            self._query_api = QueryApi(api_key=self.api_key)
        return self._query_api

    @property
    def render_api(self):
        """Lazy load Render API for formatted data."""
        if self._render_api is None:
            from sec_api import RenderApi
            self._render_api = RenderApi(api_key=self.api_key)
        return self._render_api

    def get_name(self) -> str:
        """Get plugin name."""
        return "sec_edgar"

    def get_description(self) -> str:
        """Get plugin description."""
        return "SEC Edgar filings data including 10-K, 10-Q, 13F, and Form 4"

    def _sec_headers(self) -> Dict[str, str]:
        """Build the identifying User-Agent required by SEC public APIs."""
        return {
            "Accept": "application/json",
            "User-Agent": self.config.get("user_agent") or DEFAULT_SEC_USER_AGENT,
        }

    def _official_get(self, url: str, **kwargs: Any) -> Any:
        """GET a public SEC endpoint through Beacon's resilient HTTP client."""
        headers = dict(self._sec_headers())
        headers.update(kwargs.pop("headers", {}) or {})
        response = self.http.get(
            url,
            headers=headers,
            timeout=float(self.config.get("timeout", 30)),
            **kwargs,
        )
        response.raise_for_status()
        return response.json()

    def _ticker_cik(self, ticker: str) -> str:
        """Resolve a ticker to the zero-padded CIK used by data.sec.gov."""
        wanted = ticker.strip().upper()
        configured_cik = self.config.get("cik")
        if configured_cik is not None and str(configured_cik).isdigit():
            return str(int(configured_cik)).zfill(10)
        if wanted.isdigit():
            return str(int(wanted)).zfill(10)
        if wanted in KNOWN_SEC_CIKS:
            return KNOWN_SEC_CIKS[wanted]

        payload = self._official_get(SEC_TICKER_URL)
        for row in payload.values():
            if str(row.get("ticker", "")).upper() == wanted:
                return str(int(row["cik_str"])).zfill(10)
        raise ValueError(f"SEC ticker not found: {ticker}")

    def _official_submissions(self, ticker: str) -> Dict[str, Any]:
        cik = self._ticker_cik(ticker)
        return self._official_get(f"{SEC_DATA_URL}/submissions/CIK{cik}.json")

    def _fetch_official_data(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
        config: Optional[Dict[str, Any]] = None,
    ) -> pd.DataFrame:
        """Fetch recent filings from SEC's keyless submissions API."""
        effective_config = {**self.config, **(config or {})}
        filing_types = set(effective_config.get("filing_types", ["10-K", "10-Q"]))
        payload = self._official_submissions(ticker)
        rows = []

        submission_sets = [payload.get("filings", {}).get("recent", {})]
        # ``recent`` covers only the newest portion of a company's history.
        # SEC publishes older filing blocks in the ``files`` manifest; without
        # reading those blocks a 2000--present query silently returned only one
        # annual filing for JPM. Fetch only blocks whose declared date range
        # overlaps the caller's window.
        requested_start = pd.Timestamp(start_date)
        requested_end = pd.Timestamp(end_date)
        historical_failures = 0
        for manifest in payload.get("filings", {}).get("files", []):
            file_start = pd.to_datetime(manifest.get("filingFrom"), errors="coerce")
            file_end = pd.to_datetime(manifest.get("filingTo"), errors="coerce")
            if (
                pd.isna(file_start)
                or pd.isna(file_end)
                or file_end < requested_start
                or file_start > requested_end
            ):
                continue
            file_name = manifest.get("name")
            if file_name:
                try:
                    submission_sets.append(
                        self._official_get(f"{SEC_DATA_URL}/submissions/{file_name}")
                    )
                except requests.RequestException as exc:
                    # A single historical archive shard can time out while
                    # the current submissions document and other shards are
                    # available. Keep the valid filings we already have and
                    # continue; the warning makes the coverage degradation
                    # visible without manufacturing rows.
                    historical_failures += 1
                    logger.warning(
                        "SEC historical submissions block %s unavailable; "
                        "continuing with remaining blocks (%s)",
                        file_name,
                        exc,
                    )

        for submission in submission_sets:
            # The public submissions API calls this field ``filingDate``.
            # Older SEC API payloads used ``filed``; accepting both keeps the
            # keyless path compatible with recorded fixtures and gateways.
            filing_dates = submission.get("filingDate") or submission.get("filed") or []
            forms = submission.get("form") or []
            accessions = submission.get("accessionNumber") or []
            documents = submission.get("primaryDocument") or []
            report_dates = submission.get("reportDate") or []
            for index, filed_text in enumerate(filing_dates):
                filed = pd.to_datetime(filed_text, errors="coerce")
                if pd.isna(filed) or filed < requested_start or filed > requested_end:
                    continue
                form_type = forms[index] if index < len(forms) else None
                if filing_types and form_type not in filing_types:
                    continue
                accession = accessions[index] if index < len(accessions) else None
                primary_document = documents[index] if index < len(documents) else None
                accession_path = str(accession or "").replace("-", "")
                cik = str(payload.get("cik", "")).zfill(10)
                filing_url = None
                if accession_path and primary_document:
                    filing_url = (
                        f"https://www.sec.gov/Archives/edgar/data/{int(cik)}/"
                        f"{accession_path}/{primary_document}"
                    )
                report_date = report_dates[index] if index < len(report_dates) else None
                rows.append(
                    {
                        "date": filed,
                        "ticker": ticker.upper(),
                        "form_type": form_type,
                        "company_name": payload.get("name"),
                        "cik": payload.get("cik"),
                        "accession_no": accession,
                        "filing_url": filing_url,
                        "period_end": pd.to_datetime(report_date, errors="coerce"),
                        "data_type": "financial_statement"
                        if form_type in {"10-K", "10-Q"}
                        else "filing",
                    }
                )
        if not rows:
            return pd.DataFrame()
        if historical_failures:
            logger.warning(
                "SEC filings for %s have reduced historical coverage: "
                "%d submissions block(s) were unavailable",
                ticker,
                historical_failures,
            )
        frame = pd.DataFrame(rows).set_index("date")
        return frame[~frame.index.duplicated(keep="first")].sort_index()

    def _test_official(self) -> Dict[str, Any]:
        """Probe Apple submissions through the public SEC API."""
        payload = self._official_submissions("AAPL")
        recent = payload.get("filings", {}).get("recent", {})
        return {
            "success": True,
            "message": "SEC EDGAR public API connection successful",
            "details": {
                "test_ticker": "AAPL",
                "company": payload.get("name"),
                "recent_filings": len(recent.get("form", [])),
                "api_key_required": False,
            },
        }

    def fetch_asset_data(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        SEC doesn't provide traditional asset price data.

        Args:
            symbols: Not applicable for SEC
            start_date: Start date
            end_date: End date

        Returns:
            None (SEC is for filings only)
        """
        logger.warning("SEC plugin does not support asset price data")
        return None

    def fetch_indicator_data(
        self,
        indicator_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Fetch SEC filings data as indicator data.

        Args:
            indicator_id: Format: "TICKER.FILING_TYPE" (e.g., "AAPL.10-K")
            start_date: Start date
            end_date: End date

        Returns:
            DataFrame with date and filing information
        """
        try:
            # Parse indicator_id
            if '.' not in indicator_id:
                logger.error(f"Invalid SEC indicator format: {indicator_id}")
                logger.info("Expected format: TICKER.FILING_TYPE (e.g., AAPL.10-K)")
                return None

            parts = indicator_id.split('.', 1)
            ticker = parts[0]
            filing_type = parts[1] if len(parts) > 1 else "10-K"

            # Use the existing fetch_data method
            df = self.fetch_data(ticker, start_date, end_date, {"filing_types": [filing_type]})

            if df is not None and not df.empty:
                # Convert to indicator format (date, value)
                # For SEC filings, we'll use filing count as value
                result = df.reset_index()
                result = result[['date']].copy()
                result['value'] = 1  # Each row represents one filing
                return result

            return None

        except requests.RequestException as e:
            # Preserve the provider outage as retryable instead of converting
            # it to ``None``.  The collector's bounded retry policy can then
            # recover from a transient SEC timeout; an empty frame is reserved
            # for a reachable API that genuinely has no matching filings.
            logger.error(f"SEC provider unavailable for {indicator_id}: {e}")
            raise DataSourceUnavailableError(
                f"SEC public API unavailable for '{indicator_id}'",
                context={"indicator": indicator_id, "provider": "sec_edgar"},
                cause=e,
            ) from e
        except Exception as e:
            logger.error(f"Error fetching SEC indicator {indicator_id}: {e}")
            return None

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """
        Get configuration schema for the UI.

        Returns:
            Schema defining required/optional configuration
        """
        return {
            "api_key": {
                "type": "string",
                "required": False,
                "secret": True,
                "label": "sec-api.io API Key (optional)",
                "help": "Optional. Leave blank to use the free SEC EDGAR public API. Add a sec-api.io key only for its extended query service.",
                "placeholder": "Optional sec-api.io key"
            },
            "user_agent": {
                "type": "string",
                "required": False,
                "label": "SEC User-Agent",
                "help": "Identify this application and include a contact email as requested by SEC automated-access guidance.",
                "default": DEFAULT_SEC_USER_AGENT,
                "placeholder": "Beacon/4.0 you@example.com"
            },
            "timeout": {
                "type": "number",
                "required": False,
                "label": "Request Timeout (seconds)",
                "default": 30,
                "min": 5,
                "max": 120
            },
            "filing_types": {
                "type": "multi-select",
                "required": False,
                "label": "Filing Types",
                "help": "Types of SEC filings to collect",
                "default": ["10-K", "10-Q"],
                "options": [
                    {"value": "10-K", "label": "10-K (Annual Report)"},
                    {"value": "10-Q", "label": "10-Q (Quarterly Report)"},
                    {"value": "8-K", "label": "8-K (Current Report)"},
                    {"value": "13F-HR", "label": "13F (Institutional Holdings)"},
                    {"value": "4", "label": "Form 4 (Insider Trading)"},
                    {"value": "DEF 14A", "label": "DEF 14A (Proxy Statement)"}
                ]
            },
            "rate_limit": {
                "type": "number",
                "required": False,
                "label": "Rate Limit (seconds)",
                "help": "Delay between requests to avoid rate limiting",
                "default": 1.0,
                "min": 0.5,
                "max": 10.0
            }
        }

    def fetch_data(
        self,
        ticker: str,
        start_date: datetime,
        end_date: datetime,
        config: Optional[Dict[str, Any]] = None
    ) -> pd.DataFrame:
        """
        Fetch SEC filings data for a ticker.

        Args:
            ticker: Stock ticker symbol
            start_date: Start date for data collection
            end_date: End date for data collection
            config: Optional configuration overrides

        Returns:
            DataFrame with SEC filings data
        """
        if not self.api_key:
            try:
                return self._fetch_official_data(ticker, start_date, end_date, config)
            except Exception as e:
                logger.error(f"Error fetching SEC public filings for {ticker}: {e}")
                raise

        try:
            config = config or {}
            filing_types = config.get("filing_types", ["10-K", "10-Q"])

            all_filings = []

            for filing_type in filing_types:
                logger.info(f"Fetching {filing_type} filings for {ticker}")

                # Build query
                query = {
                    "query": {
                        "query_string": {
                            "query": f"ticker:{ticker} AND formType:\"{filing_type}\" AND "
                                   f"filedAt:[{start_date.strftime('%Y-%m-%d')} TO {end_date.strftime('%Y-%m-%d')}]"
                        }
                    },
                    "from": "0",
                    "size": "100",
                    "sort": [{"filedAt": {"order": "desc"}}]
                }

                # Execute query. The sec_api SDK owns its transport, so the
                # plugin-wide backoff wraps the call.
                response = retry_call(lambda: self.query_api.get_filings(query), retries=2)
                filings = response.get("filings", [])

                for filing in filings:
                    filing_data = {
                        "date": pd.to_datetime(filing.get("filedAt")),
                        "ticker": ticker,
                        "form_type": filing.get("formType"),
                        "company_name": filing.get("companyName"),
                        "cik": filing.get("cik"),
                        "accession_no": filing.get("accessionNo"),
                        "filing_url": filing.get("linkToFilingDetails"),
                        "period_end": pd.to_datetime(filing.get("periodOfReport")) if filing.get("periodOfReport") else None
                    }

                    # Extract financial metrics if available
                    if filing_type in ["10-K", "10-Q"]:
                        # Try to get key financial metrics from filing
                        try:
                            # This would require parsing XBRL data
                            # For now, we'll store the filing reference
                            filing_data["data_type"] = "financial_statement"
                        except Exception as e:
                            logger.warning(f"Could not extract financials: {e}")

                    elif filing_type == "13F-HR":
                        filing_data["data_type"] = "institutional_holdings"

                    elif filing_type == "4":
                        filing_data["data_type"] = "insider_trading"

                    all_filings.append(filing_data)

            if not all_filings:
                logger.warning(f"No SEC filings found for {ticker}")
                return pd.DataFrame()

            df = pd.DataFrame(all_filings)
            df.set_index("date", inplace=True)
            df.sort_index(inplace=True)

            return df

        except Exception as e:
            logger.error(f"Error fetching SEC data for {ticker}: {e}")
            raise

    def validate_config(self) -> None:
        """
        Validate plugin configuration.

        Raises:
            ValueError: If configuration is invalid
        """
        # SEC's own submissions and company-facts APIs are public.  An
        # optional sec-api.io key is still accepted for the richer query
        # features, but it is not required for this source.
        return

    def get_company_facts(self, ticker: str) -> Dict[str, Any]:
        """
        Get company facts and metrics.

        Args:
            ticker: Stock ticker symbol

        Returns:
            Dictionary with company facts
        """
        try:
            # Get CIK from ticker
            query = {
                "query": {"query_string": {"query": f"ticker:{ticker}"}},
                "from": "0",
                "size": "1"
            }
            response = self.query_api.get_filings(query)
            filings = response.get("filings", [])

            if not filings:
                return {}

            cik = filings[0].get("cik")

            # Fetch company facts (would need additional API endpoint)
            return {
                "cik": cik,
                "ticker": ticker,
                "company_name": filings[0].get("companyName"),
                "sic": filings[0].get("sic"),
                "state": filings[0].get("stateOfIncorporation")
            }

        except Exception as e:
            logger.error(f"Error fetching company facts for {ticker}: {e}")
            return {}

    def get_institutional_holders(
        self,
        ticker: str,
        date: Optional[datetime] = None
    ) -> pd.DataFrame:
        """
        Get institutional holdings (13F filings).

        Args:
            ticker: Stock ticker symbol
            date: Optional date to get holdings as of (defaults to latest)

        Returns:
            DataFrame with institutional holdings
        """
        if not self.api_key:
            try:
                start = date or (datetime.now() - timedelta(days=365))
                return self._fetch_official_data(
                    ticker,
                    start,
                    datetime.now(),
                    {"filing_types": ["13F-HR"]},
                ).reset_index()
            except Exception as e:
                logger.error(f"Error fetching SEC public 13F filings for {ticker}: {e}")
                return pd.DataFrame()

        try:
            # Query 13F filings
            if date:
                date_str = date.strftime('%Y-%m-%d')
                query_str = f"ticker:{ticker} AND formType:\"13F-HR\" AND filedAt:[{date_str} TO *]"
            else:
                query_str = f"ticker:{ticker} AND formType:\"13F-HR\""

            query = {
                "query": {"query_string": {"query": query_str}},
                "from": "0",
                "size": "10",
                "sort": [{"filedAt": {"order": "desc"}}]
            }

            response = self.query_api.get_filings(query)
            filings = response.get("filings", [])

            if not filings:
                return pd.DataFrame()

            # Process holdings data
            holdings_data = []
            for filing in filings:
                holdings_data.append({
                    "date": pd.to_datetime(filing.get("filedAt")),
                    "filer": filing.get("companyName"),
                    "cik": filing.get("cik"),
                    "filing_url": filing.get("linkToFilingDetails")
                })

            return pd.DataFrame(holdings_data)

        except Exception as e:
            logger.error(f"Error fetching institutional holdings for {ticker}: {e}")
            return pd.DataFrame()

    def test_connection(self) -> Dict[str, Any]:
        """
        Test SEC API connection.

        Returns:
            Dictionary with test results
        """
        if not self.api_key:
            try:
                return self._test_official()
            except Exception as e:
                return {
                    "success": False,
                    "message": f"SEC EDGAR public API connection failed: {str(e)}",
                }

        try:
            query = {
                "query": {"query_string": {"query": "ticker:AAPL"}},
                "from": "0",
                "size": "1"
            }
            response = self.query_api.get_filings(query)
            return {
                "success": True,
                "message": "SEC API connection successful",
                "details": {"total_filings_available": response.get("total", {}).get("value", 0)},
            }
        except Exception as e:
            # Keep the source usable when an old/invalid optional sec-api key
            # is present: verify the keyless SEC endpoint and explain which
            # mode is active instead of reporting a misleading provider outage.
            try:
                result = self._test_official()
                result["message"] += "; optional sec-api.io key was not accepted, so public mode is active"
                return result
            except Exception as official_error:
                return {
                    "success": False,
                    "message": f"SEC API connection failed: {e}; public EDGAR fallback failed: {official_error}",
                }

    @classmethod
    def get_plugin_info(cls) -> Dict[str, Any]:
        """Get plugin metadata."""
        return {
            "name": "SEC Edgar",
            "description": "Company filings from the SEC EDGAR public API; optional sec-api.io access adds richer queries.",
            "version": "1.0.0",
            "author": "BEACON",
            "free": True,
            "registration_required": False,
            "registration_url": "https://www.sec.gov/search-filings/edgar-application-programming-interfaces"
        }


# Register the plugin
register_plugin("sec_edgar", SECPlugin)
