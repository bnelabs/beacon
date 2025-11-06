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

    def build_graph(self, data: pd.DataFrame) -> dict:
        """Build graph structure for GNN models based on temporal and feature correlations."""
        import networkx as nx
        from scipy.stats import pearsonr

        if data.empty:
            logger.warning(f"[{self.job_id}] Empty data provided for graph building")
            return {"nodes": [], "edges": [], "node_features": {}, "edge_weights": {}}

        # Correlation threshold for edge creation
        CORRELATION_THRESHOLD = 0.5

        # Create nodes from unique data sources
        nodes = []
        node_features = {}

        value_col = 'value' if 'value' in data.columns else 'Value' if 'Value' in data.columns else None
        date_col = 'date' if 'date' in data.columns else 'Date' if 'Date' in data.columns else None

        if 'source_code' in data.columns and value_col:
            unique_sources = data['source_code'].unique()

            for source in unique_sources:
                source_data = data[data['source_code'] == source]

                # Compute node features
                values = pd.to_numeric(source_data[value_col], errors='coerce').dropna()

                if len(values) > 0:
                    node_features[source] = {
                        'mean': float(values.mean()),
                        'std': float(values.std()),
                        'min': float(values.min()),
                        'max': float(values.max()),
                        'count': int(len(values))
                    }
                    nodes.append(source)

        # Build edges based on correlations between time series
        edges = []
        edge_weights = {}

        if len(nodes) > 1 and value_col and date_col:
            # Pivot data to have sources as columns
            try:
                pivot_data = data.pivot_table(
                    index=date_col,
                    columns='source_code',
                    values=value_col,
                    aggfunc='mean'
                )

                # Compute pairwise correlations
                for i, source1 in enumerate(nodes):
                    for source2 in nodes[i+1:]:
                        if source1 in pivot_data.columns and source2 in pivot_data.columns:
                            series1 = pivot_data[source1].dropna()
                            series2 = pivot_data[source2].dropna()

                            # Align series
                            common_idx = series1.index.intersection(series2.index)

                            if len(common_idx) > 2:
                                corr, p_value = pearsonr(
                                    series1.loc[common_idx],
                                    series2.loc[common_idx]
                                )

                                # Add edge if correlation is significant
                                if abs(corr) >= CORRELATION_THRESHOLD and p_value < 0.05:
                                    edge_id = f"{source1}_{source2}"
                                    edges.append({
                                        "source": source1,
                                        "target": source2,
                                        "weight": float(abs(corr))
                                    })
                                    edge_weights[edge_id] = float(abs(corr))

            except Exception as e:
                logger.warning(f"[{self.job_id}] Could not compute correlations: {e}")

        logger.info(f"[{self.job_id}] Built graph with {len(nodes)} nodes and {len(edges)} edges")

        return {
            "nodes": nodes,
            "edges": edges,
            "node_features": node_features,
            "edge_weights": edge_weights
        }
