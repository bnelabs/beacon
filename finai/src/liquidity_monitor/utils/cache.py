"""Data caching utilities for the liquidity monitor."""

import os
import pandas as pd
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

from ..utils.config import Config
from ..utils.logger import get_logger

logger = get_logger(__name__)


class DataCache:
    """Handles caching of financial data to avoid repeated API calls."""
    
    def __init__(self, config: Config):
        """
        Initialize cache.
        
        Args:
            config: Configuration object
        """
        self.config = config
        self.cache_enabled = config.get("data.cache_enabled", True)
        self.cache_format = config.get("data.cache_format", "parquet")
        
        # Set up cache directory relative to project root
        project_root = Path(__file__).parent.parent.parent.parent.parent
        self.cache_dir = project_root / "data" / "cache"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
    
    def get_cache_path(
        self,
        data_type: str,
        identifier: Any, # Can be list of strings or list of dicts for funds
        start_date: datetime,
        end_date: datetime
    ) -> Path:
        """
        Get the cache file path for a specific dataset.
        
        Args:
            data_type: Type of data (e.g., 'assets', 'indicators', 'fred')
            identifier: Unique identifier (string, list of strings, or list of dicts)
            start_date: Start date of the data
            end_date: End date of the data
            
        Returns:
            Path to cache file
        """
        # Create a filename from the parameters
        date_str = f"{start_date.strftime('%Y%m%d')}_to_{end_date.strftime('%Y%m%d')}"
        
        # Create a hash of the identifier for long lists/complex inputs
        if isinstance(identifier, list):
            # Convert complex list types (like fund list) to a deterministic string before hashing
            identifier_str_raw = str(sorted(map(lambda x: str(x), identifier)))
        else:
            identifier_str_raw = str(identifier)
        
        id_hash = hashlib.md5(identifier_str_raw.encode()).hexdigest()[:8]
        
        # Use hash as identifier part
        filename = f"{data_type}_{id_hash}_{date_str}.{self.cache_format}"
        return self.cache_dir / filename
    
    def load_data(
        self,
        data_type: str,
        identifier: Any,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Load data from cache if available.
        
        Args:
            data_type: Type of data
            identifier: Unique identifier
            start_date: Start date
            end_date: End date
            
        Returns:
            Cached DataFrame or None if not found
        """
        if not self.cache_enabled:
            return None
        
        cache_path = self.get_cache_path(data_type, identifier, start_date, end_date)
        
        if not cache_path.exists():
            return None
        
        try:
            if self.cache_format == "parquet":
                data = pd.read_parquet(cache_path)
            elif self.cache_format == "feather":
                data = pd.read_feather(cache_path)
            else:  # csv
                data = pd.read_csv(cache_path, parse_dates=["Date"])
            
            logger.debug(f"Loaded {data_type} data from cache: {cache_path.name}")
            return data
            
        except Exception as e:
            logger.warning(f"Error loading from cache {cache_path.name}: {e}")
            return None
    
    def save_data(
        self,
        data: pd.DataFrame,
        data_type: str,
        identifier: Any,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[Path]:
        """
        Save data to cache.
        
        Args:
            data: DataFrame to cache
            data_type: Type of data
            identifier: Unique identifier
            start_date: Start date
            end_date: End date
            
        Returns:
            Path to cache file or None if saving failed/disabled
        """
        if not self.cache_enabled:
            return None
        
        cache_path = self.get_cache_path(data_type, identifier, start_date, end_date)
        
        try:
            if self.cache_format == "parquet":
                data.to_parquet(cache_path, index=False)
            elif self.cache_format == "feather":
                data.to_feather(cache_path)
            else:  # csv
                data.to_csv(cache_path, index=False)
            
            logger.debug(f"Saved {data_type} data to cache: {cache_path.name}")
            return cache_path
            
        except Exception as e:
            logger.warning(f"Error saving to cache {cache_path.name}: {e}")
            return None
    
    def clear_cache(self, data_type: str = None, older_than_days: int = None):
        """
        Clear cache files.
        
        Args:
            data_type: Type of data to clear (None for all)
            older_than_days: Clear files older than this many days (None for all)
        """
        now = datetime.now()
        
        for cache_file in self.cache_dir.glob(f"*.{self.cache_format}"):
            # Check if file matches data type filter
            if data_type and not cache_file.name.startswith(f"{data_type}_"):
                continue
            
            # Check if file is older than specified days
            if older_than_days is not None:
                try:
                    file_time = datetime.fromtimestamp(cache_file.stat().st_mtime)
                    if (now - file_time).days <= older_than_days:
                        continue
                except OSError:
                    # Skip if file stat fails (e.g., file deleted between glob and stat)
                    continue
            
            # Delete file
            try:
                cache_file.unlink()
                logger.debug(f"Deleted cache file: {cache_file.name}")
            except Exception as e:
                logger.warning(f"Error deleting cache file {cache_file.name}: {e}")
        
        logger.info(f"Cache cleared (data_type: {data_type or 'all'}, older_than: {older_than_days or 'all'} days)")
