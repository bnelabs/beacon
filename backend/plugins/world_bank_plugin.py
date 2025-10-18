"""World Bank Open Data API plugin."""

from typing import Dict, Any, List, Optional
import pandas as pd
from datetime import datetime
import requests
import logging
from .base import DataSourcePlugin, register_plugin

logger = logging.getLogger(__name__)


class WorldBankPlugin(DataSourcePlugin):
    """
    World Bank Open Data API plugin.

    Data from: World Bank Data API
    Documentation: https://datahelpdesk.worldbank.org/knowledgebase/articles/889392-about-the-indicators-api-documentation

    Features:
    - World Development Indicators (WDI)
    - Country-level economic data
    - Development statistics
    - No API key required
    """

    def validate_config(self) -> None:
        """Validate World Bank configuration (no API key needed)."""
        # World Bank API is open, no authentication required
        pass

    def test_connection(self) -> Dict[str, Any]:
        """Test World Bank API connectivity."""
        try:
            # Test with a simple query
            url = "https://api.worldbank.org/v2/country/all/indicator/NY.GDP.MKTP.CD"
            params = {"format": "json", "per_page": 1}
            response = requests.get(url, params=params, timeout=10)

            if response.status_code == 200:
                return {
                    "success": True,
                    "message": "Successfully connected to World Bank API"
                }
            else:
                return {
                    "success": False,
                    "message": f"World Bank API returned status code: {response.status_code}"
                }
        except Exception as e:
            logger.error(f"World Bank connection test failed: {e}")
            return {
                "success": False,
                "message": f"Failed to connect to World Bank API: {str(e)}"
            }

    def fetch_asset_data(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        World Bank doesn't provide traditional asset price data.

        Args:
            symbols: Not applicable for World Bank
            start_date: Start date
            end_date: End date

        Returns:
            None (World Bank is for indicators only)
        """
        logger.warning("World Bank plugin does not support asset price data")
        return None

    def fetch_indicator_data(
        self,
        indicator_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Fetch economic indicator data from World Bank.

        Args:
            indicator_id: World Bank indicator code with country
                Format: COUNTRY.INDICATOR (e.g., 'USA.NY.GDP.MKTP.CD' or 'WLD.SP.POP.TOTL')
                - USA = United States (3-letter code)
                - WLD = World
                - NY.GDP.MKTP.CD = GDP (current US$)
                - SP.POP.TOTL = Population, total

                Common indicators:
                - NY.GDP.MKTP.CD = GDP (current US$)
                - NY.GDP.PCAP.CD = GDP per capita
                - FP.CPI.TOTL.ZG = Inflation, consumer prices (annual %)
                - SL.UEM.TOTL.ZS = Unemployment, total (% of total labor force)
                - SP.POP.TOTL = Population, total
            start_date: Start date
            end_date: End date

        Returns:
            DataFrame with Date and Value columns
        """
        try:
            # Parse indicator ID
            # Format: COUNTRY.INDICATOR
            if '.' not in indicator_id:
                logger.error(f"Invalid World Bank indicator format: {indicator_id}")
                logger.info("Expected format: COUNTRY.INDICATOR (e.g., USA.NY.GDP.MKTP.CD)")
                return None

            parts = indicator_id.split('.', 1)
            country = parts[0]  # e.g., USA, WLD, GBR
            indicator = parts[1]  # e.g., NY.GDP.MKTP.CD

            # Build World Bank API URL
            # Format: https://api.worldbank.org/v2/country/{country}/indicator/{indicator}
            base_url = "https://api.worldbank.org/v2"
            url = f"{base_url}/country/{country}/indicator/{indicator}"

            # Parameters
            params = {
                "format": "json",
                "date": f"{start_date.year}:{end_date.year}",
                "per_page": 1000  # Max results per page
            }

            headers = {
                "Accept": "application/json",
                "User-Agent": "BEACON/2.0"
            }

            all_records = []
            page = 1

            # World Bank API uses pagination
            while True:
                params["page"] = page
                response = requests.get(url, headers=headers, params=params, timeout=30)
                response.raise_for_status()

                data = response.json()

                # World Bank returns [metadata, data]
                if not data or len(data) < 2:
                    break

                metadata = data[0]
                records = data[1]

                if not records:
                    break

                # Parse records
                for record in records:
                    date_str = record.get('date')
                    value = record.get('value')

                    if date_str and value is not None:
                        try:
                            # World Bank uses year as date
                            date = pd.to_datetime(f"{date_str}-01-01")
                            all_records.append({
                                'date': date,
                                'value': float(value)
                            })
                        except (ValueError, TypeError) as e:
                            logger.warning(f"Failed to parse record: {e}")
                            continue

                # Check if there are more pages
                total_pages = metadata.get('pages', 1)
                if page >= total_pages:
                    break

                page += 1

            if all_records:
                df = pd.DataFrame(all_records)
                df = df.sort_values('date')
                logger.info(f"Fetched {len(df)} records for {indicator_id} from World Bank")
                return df
            else:
                logger.warning(f"No data returned for {indicator_id} from World Bank")
                return None

        except Exception as e:
            logger.error(f"Error fetching indicator {indicator_id} from World Bank: {e}")
            return None

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Get configuration schema for World Bank plugin."""
        return {
            "name": {
                "type": "string",
                "required": False,
                "label": "Configuration Name",
                "description": "Optional name for this World Bank configuration",
                "default": "World Bank Open Data"
            },
            "timeout": {
                "type": "integer",
                "required": False,
                "label": "Request Timeout (seconds)",
                "description": "Timeout for API requests",
                "default": 30
            },
            "note": {
                "type": "info",
                "label": "Indicator Format",
                "description": "Use format: COUNTRY.INDICATOR (e.g., USA.NY.GDP.MKTP.CD for US GDP)"
            },
            "examples": {
                "type": "info",
                "label": "Common Indicators",
                "description": "NY.GDP.MKTP.CD (GDP), NY.GDP.PCAP.CD (GDP per capita), FP.CPI.TOTL.ZG (Inflation), SL.UEM.TOTL.ZS (Unemployment)"
            }
        }

    @classmethod
    def get_plugin_info(cls) -> Dict[str, Any]:
        """Get plugin metadata."""
        return {
            "name": "World Bank Open Data",
            "description": "Free access to World Development Indicators (WDI) - country-level economic data, development statistics, GDP, inflation, unemployment. No API key required.",
            "version": "1.0.0",
            "author": "BEACON",
            "free": True,
            "registration_required": False,
            "registration_url": None
        }


# Register the plugin
register_plugin("world_bank", WorldBankPlugin)
