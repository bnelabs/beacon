"""SEC Edgar API plugin for company filings data."""

from typing import Dict, Any, List, Optional
import pandas as pd
from datetime import datetime, timedelta
from .base import DataSourcePlugin, register_plugin
import logging

logger = logging.getLogger(__name__)


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
        self.config = config
        self.api_key = config.get('api_key', '')
        self._query_api = None
        self._render_api = None

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
                "required": True,
                "secret": True,
                "label": "SEC API Key",
                "help": "API key from https://sec-api.io (Free tier: 100 requests/month)",
                "placeholder": "Enter your SEC API key"
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

                # Execute query
                response = self.query_api.get_filings(query)
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
        if not self.api_key:
            raise ValueError("SEC API key is required")

        try:
            # Test API key with a simple query
            test_query = {
                "query": {"query_string": {"query": "ticker:AAPL AND formType:\"10-K\""}},
                "from": "0",
                "size": "1"
            }
            self.query_api.get_filings(test_query)
            logger.info("SEC API key validation successful")
        except Exception as e:
            logger.error(f"SEC API key validation failed: {e}")
            raise ValueError(f"SEC API key validation failed: {e}")

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
        try:
            # Simple test query
            query = {
                "query": {"query_string": {"query": "ticker:AAPL"}},
                "from": "0",
                "size": "1"
            }
            response = self.query_api.get_filings(query)

            return {
                "success": True,
                "message": "SEC API connection successful",
                "total_filings_available": response.get("total", {}).get("value", 0)
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"SEC API connection failed: {str(e)}"
            }

    @classmethod
    def get_plugin_info(cls) -> Dict[str, Any]:
        """Get plugin metadata."""
        return {
            "name": "SEC Edgar",
            "description": "Company filings data from SEC Edgar API - 10-K, 10-Q, 13F, Form 4. Free tier: 100 requests/month.",
            "version": "1.0.0",
            "author": "BEACON",
            "free": False,
            "registration_required": True,
            "registration_url": "https://sec-api.io"
        }


# Register the plugin
register_plugin("sec_edgar", SECPlugin)
