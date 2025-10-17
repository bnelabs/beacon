"""Data Formatter - Standardization and feature engineering."""

import logging
from typing import Dict
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

class DataFormatter:
    def __init__(self, job_id: str):
        self.job_id = job_id

    def format(self, data: Dict[str, pd.DataFrame], target_schema: str) -> pd.DataFrame:
        logger.info(f"[{self.job_id}] Formatting to {target_schema}")
        
        # Combine all datasets
        all_data = []
        for code, df in data.items():
            if not df.empty:
                df = df.copy()
                df['source_code'] = code
                all_data.append(df)
        
        if not all_data:
            return pd.DataFrame()
        
        combined = pd.concat(all_data, ignore_index=True)
        return combined

    def extract_features(self, data: pd.DataFrame) -> pd.DataFrame:
        """Extract engineered features."""
        if data.empty:
            return pd.DataFrame()
        
        features = pd.DataFrame(index=data.index)
        
        if 'value' in data.columns:
            features['value_mean'] = data['value'].rolling(7).mean()
            features['value_std'] = data['value'].rolling(7).std()
        
        return features

    def build_graph(self, data: pd.DataFrame) -> dict:
        """Build graph structure for GNN models."""
        # Simple placeholder
        return {"nodes": [], "edges": []}
