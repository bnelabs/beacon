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

                # Standardize column names to match expected schema
                # Different plugins return different capitalizations
                column_mapping = {}
                for col in df.columns:
                    col_lower = col.lower()
                    if col_lower == 'date':
                        column_mapping[col] = 'Date'
                    elif col_lower == 'value':
                        column_mapping[col] = 'Value'
                    elif col_lower == 'open':
                        column_mapping[col] = 'Open'
                    elif col_lower == 'high':
                        column_mapping[col] = 'High'
                    elif col_lower == 'low':
                        column_mapping[col] = 'Low'
                    elif col_lower == 'close':
                        column_mapping[col] = 'Close'
                    elif col_lower == 'volume':
                        column_mapping[col] = 'Volume'

                if column_mapping:
                    df = df.rename(columns=column_mapping)

                # Ensure datetime parsing and lowercase aliases for downstream compatibility
                if 'Date' in df.columns:
                    df['Date'] = pd.to_datetime(df['Date'], errors='coerce')
                    df['date'] = df['Date']
                if 'Value' in df.columns:
                    df['value'] = pd.to_numeric(df['Value'], errors='coerce')
                if 'Open' in df.columns and 'open' not in df.columns:
                    df['open'] = pd.to_numeric(df['Open'], errors='coerce')
                if 'High' in df.columns and 'high' not in df.columns:
                    df['high'] = pd.to_numeric(df['High'], errors='coerce')
                if 'Low' in df.columns and 'low' not in df.columns:
                    df['low'] = pd.to_numeric(df['Low'], errors='coerce')
                if 'Close' in df.columns and 'close' not in df.columns:
                    df['close'] = pd.to_numeric(df['Close'], errors='coerce')
                if 'Volume' in df.columns and 'volume' not in df.columns:
                    df['volume'] = pd.to_numeric(df['Volume'], errors='coerce')

                # Provide canonical aliases expected by downstream modules
                if 'Asset' in df.columns and 'asset' not in df.columns:
                    df['asset'] = df['Asset']
                if 'source_code' in df.columns and 'source' not in df.columns:
                    df['source'] = df['source_code']
                if 'value' not in df.columns:
                    if 'Value' in df.columns:
                        df['value'] = pd.to_numeric(df['Value'], errors='coerce')
                    elif 'close' in df.columns:
                        df['value'] = pd.to_numeric(df['close'], errors='coerce')
                    elif 'Close' in df.columns:
                        df['value'] = pd.to_numeric(df['Close'], errors='coerce')

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
        
        value_col = None
        if 'value' in data.columns:
            value_col = 'value'
        elif 'Value' in data.columns:
            value_col = 'Value'

        if value_col:
            value_series = pd.to_numeric(data[value_col], errors='coerce')
            features['value_mean'] = value_series.rolling(7, min_periods=1).mean()
            features['value_std'] = value_series.rolling(7, min_periods=1).std().fillna(0)

        return features

    # ``build_graph`` was removed. It produced one static adjacency per data
    # package by thresholding pairwise Pearson correlation at 0.5, and the
    # result was pickled to ``graph.pkl`` for a GNN that never read it.
    #
    # Two things were wrong with it. Correlation is co-movement, not exposure:
    # a correlation matrix is not a liability matrix, so no clearing or
    # cascade algorithm can be run on it -- there is no "who owes whom" in it.
    # And the graph was frozen for the whole window, which asserts that the
    # funding network is constant across days when it re-prices intraday.
    #
    # Graph construction returns in Phase 2 as a rolling-window multiplex whose
    # layers are separate economic relations (funding, balance-sheet
    # similarity, CCP clearing), each updated at its own frequency.
