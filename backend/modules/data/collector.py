"""Data Collector - Multi-source data collection."""

import logging
from typing import List, Dict
from datetime import datetime
import pandas as pd
from sqlalchemy.orm import Session
import os

from models.data_catalogue import DataCatalogueItem
from models.data_source import DataSource
from plugins.base import get_plugin

logger = logging.getLogger(__name__)


class DataCollector:
    """Collects data from multiple sources based on catalogue selection."""

    def __init__(self, db: Session, job_id: str, output_dir: str):
        self.db = db
        self.job_id = job_id
        self.output_dir = output_dir

    def collect(self, catalogue_items: List[int], start_date: str, end_date: str) -> Dict[str, pd.DataFrame]:
        """
        Collect data from selected catalogue items.

        Returns:
            Dict mapping item_code to DataFrame
        """
        logger.info(f"[{self.job_id}] Collecting {len(catalogue_items)} datasets")

        collected = {}

        for item_id in catalogue_items:
            item = self.db.query(DataCatalogueItem).filter(DataCatalogueItem.id == item_id).first()
            if not item:
                logger.warning(f"Catalogue item {item_id} not found")
                continue

            try:
                df = self._fetch_item_data(item, start_date, end_date)
                collected[item.code] = df
                logger.info(f"Collected {len(df)} records for {item.code}")
            except Exception as e:
                logger.error(f"Failed to collect {item.code}: {e}")
                collected[item.code] = pd.DataFrame()  # Empty on failure

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

        # Prepare plugin config - retrieve secret from vault if necessary
        config = data_source.config or {}
        if "api_key_vault_ref" in config:
            from services.secrets_service import SecretsService
            secrets_service = SecretsService()
            try:
                api_key = secrets_service.get_secret(config["api_key_vault_ref"], "api_key")
                config["api_key"] = api_key
            except Exception as e:
                logger.error(f"Failed to retrieve secret for data source {data_source.id}: {e}")
                return pd.DataFrame()

        # Instantiate plugin with config
        plugin = plugin_class(config)

        # Convert dates
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")

        # Fetch data based on item type
        # Use endpoint from catalogue if available, otherwise use code
        endpoint = item.endpoint if item.endpoint else item.code

        if item.category.value in ['exchange_rates', 'stocks', 'bonds', 'commodities']:
            # Asset data (price data)
            df = plugin.fetch_asset_data([endpoint], start_dt, end_dt)
        else:
            # Indicator data (economic indicators, interest rates, etc.)
            df = plugin.fetch_indicator_data(endpoint, start_dt, end_dt)

        return df if df is not None else pd.DataFrame()
