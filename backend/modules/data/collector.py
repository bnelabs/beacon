"""Data Collector - Multi-source data collection."""

import logging
from typing import List, Dict, Optional
from datetime import datetime
import pandas as pd
from sqlalchemy.orm import Session
import os

from backend.models.data_catalogue import DataCatalogueItem
from backend.models.data_source import DataSource
from backend.plugins.base import get_plugin
from .country_utils import CountryMatcher

logger = logging.getLogger(__name__)


class DataCollector:
    """Collects data from multiple sources based on catalogue selection."""

    def __init__(self, db: Session, job_id: str, output_dir: str):
        self.db = db
        self.job_id = job_id
        self.output_dir = output_dir

    def collect(
        self,
        catalogue_items: List[int],
        start_date: str,
        end_date: str,
        country_filters: Optional[List[str]] = None,
        region_filters: Optional[List[str]] = None,
    ) -> Dict[str, pd.DataFrame]:
        """
        Collect data from selected catalogue items.

        Returns:
            Dict mapping item_code to DataFrame
        """
        logger.info(f"[{self.job_id}] Collecting {len(catalogue_items)} datasets")

        collected = {}
        matcher = CountryMatcher(country_filters, region_filters)
        matched_codes = []

        for item_id in catalogue_items:
            item = self.db.query(DataCatalogueItem).filter(DataCatalogueItem.id == item_id).first()
            if not item:
                logger.warning(f"Catalogue item {item_id} not found")
                continue

            if not matcher.should_collect(item):
                logger.info(
                    "[%s] Skipping %s (%s) - outside selected country scope '%s'",
                    self.job_id,
                    item.code,
                    getattr(item, "region", None),
                    matcher.describe(),
                )
                continue

            try:
                df = self._fetch_item_data(item, start_date, end_date)
                collected[item.code] = df
                logger.info(f"Collected {len(df)} records for {item.code}")
                matched_codes.append(item.code)
            except Exception as e:
                logger.error(f"Failed to collect {item.code}: {e}")
                collected[item.code] = pd.DataFrame()  # Empty on failure

        if matcher.active and not matched_codes:
            raise ValueError("Selected country filters did not match any catalogue data sets.")

        return collected

    def _fetch_item_data(self, item: DataCatalogueItem, start_date: str, end_date: str) -> pd.DataFrame:
        """Fetch data for a single catalogue item using the plugin system."""
        # Get the data source
        data_source = item.data_source
        if not data_source:
            logger.error(f"No data source configured for {item.code}")
            return pd.DataFrame()

        # Get the appropriate plugin
        plugin_class = get_plugin(data_source.plugin_type)
        if not plugin_class:
            logger.error(f"Plugin type '{data_source.plugin_type}' not found")
            return pd.DataFrame()

        # Prepare plugin config - inject API keys from environment if not in config
        config = data_source.config or {}

        # Inject FRED API key from environment if not in config
        if data_source.plugin_type == 'fred' and not config.get('api_key'):
            fred_key = os.getenv('FRED_API_KEY')
            if fred_key:
                config['api_key'] = fred_key
                logger.info("Injected FRED API key from environment")

        # Inject Alpha Vantage API key from environment if not in config
        if data_source.plugin_type == 'alpha_vantage' and not config.get('api_key'):
            av_key = os.getenv('ALPHA_VANTAGE_API_KEY')
            if av_key:
                config['api_key'] = av_key
                logger.info("Injected Alpha Vantage API key from environment")

        # Inject SEC API key from environment if not in config
        if data_source.plugin_type == 'sec_edgar' and not config.get('api_key'):
            sec_key = os.getenv('SEC_API_KEY')
            if sec_key:
                config['api_key'] = sec_key
                logger.info("Injected SEC API key from environment")

        # Instantiate plugin with config
        plugin = plugin_class(config)

        # Convert dates
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        # Fetch data based on item type
        # Use endpoint from catalogue if available, otherwise use code
        endpoint = item.endpoint if item.endpoint else item.code

        if item.category in ['exchange_rates', 'stocks', 'bonds', 'commodities']:
            # Asset data (price data)
            df = plugin.fetch_asset_data([endpoint], start_dt, end_dt)
        else:
            # Indicator data (economic indicators, interest rates, etc.)
            df = plugin.fetch_indicator_data(endpoint, start_dt, end_dt)

        return df if df is not None else pd.DataFrame()
