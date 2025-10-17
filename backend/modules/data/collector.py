"""Data Collector - Multi-source data collection."""

import logging
from typing import List, Dict
import pandas as pd
from sqlalchemy.orm import Session

from models.data_catalogue import DataCatalogueItem
from models.data_source import DataSource

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
        """Fetch data for a single catalogue item."""
        # TODO: Implement actual data fetching using plugins
        # For now, return mock data structure
        return pd.DataFrame({
            'date': pd.date_range(start_date, end_date),
            'value': 100.0,
            'source': item.code,
            'asset': item.code
        })
