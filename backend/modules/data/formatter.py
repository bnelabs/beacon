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

        if 'source_code' in data.columns:
            unique_sources = data['source_code'].unique()

            for source in unique_sources:
                source_data = data[data['source_code'] == source]

                if 'value' in source_data.columns:
                    # Compute node features
                    values = source_data['value'].dropna()

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

        if len(nodes) > 1 and 'value' in data.columns and 'date' in data.columns:
            # Pivot data to have sources as columns
            try:
                pivot_data = data.pivot_table(
                    index='date',
                    columns='source_code',
                    values='value',
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
