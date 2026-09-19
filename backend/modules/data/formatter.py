"""Data Formatter - Standardization and feature engineering."""

import logging
from typing import Dict, Mapping, Optional
import pandas as pd
import numpy as np

logger = logging.getLogger(__name__)

class DataFormatter:
    def __init__(self, job_id: str):
        self.job_id = job_id

    @staticmethod
    def _identity_columns(df: pd.DataFrame):
        """Return panel dimensions that identify an independent series."""
        for identity in (
            ("source_bank", "target_bank"),
            ("bank_id", "feature"),
            ("bank_id",),
            ("ticker",),
            ("Asset",),
            ("asset",),
            ("instrument",),
        ):
            if all(column in df.columns for column in identity):
                return list(identity)
        return []

    def format(
        self,
        data: Dict[str, pd.DataFrame],
        target_schema: str,
        source_metadata: Optional[Mapping[str, Mapping[str, object]]] = None,
    ) -> pd.DataFrame:
        logger.info(f"[{self.job_id}] Formatting to {target_schema}")
        source_metadata = source_metadata or {}

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
                metadata = source_metadata.get(code, {})
                # The previous package-level ``frequency: daily`` claim was
                # false for mixed panels.  Carry the catalogue contract on
                # every row so downstream consumers can keep cadence and unit
                # semantics attached to the observation.
                df['frequency'] = metadata.get('frequency')
                df['unit'] = metadata.get('unit')
                df['granularity'] = metadata.get('granularity')

                identity_columns = self._identity_columns(df)
                if identity_columns:
                    identity = (
                        df[identity_columns]
                        .astype('string')
                        .fillna('<NA>')
                        .agg('::'.join, axis=1)
                    )
                    df['series_id'] = code + '::' + identity
                else:
                    df['series_id'] = code
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
            group_col = 'series_id' if 'series_id' in data.columns else (
                'source_code' if 'source_code' in data.columns else None
            )

            # Format concatenates sources source-by-source.  A global rolling
            # window therefore used the last six rows of one dataset as the
            # history for the first row of the next, and a panel such as
            # AI4Risk also crossed bank-edge boundaries.  Compute the same
            # seven-observation features chronologically inside each natural
            # series and restore the original row alignment.
            working = pd.DataFrame({
                '__value': value_series.to_numpy(),
                '__row_position': np.arange(len(data)),
            })
            if group_col is None:
                working['__series'] = '__single__'
            else:
                working['__series'] = data[group_col].astype('string').fillna('<NA>').to_numpy()
            date_column = next((c for c in ('Date', 'date', 'timestamp', 'time') if c in data.columns), None)
            if date_column is not None:
                working['__date'] = pd.to_datetime(data[date_column], errors='coerce').to_numpy()
                ordered = working.sort_values(
                    ['__series', '__date', '__row_position'],
                    kind='mergesort',
                    na_position='last',
                )
            else:
                ordered = working.sort_values(['__series', '__row_position'], kind='mergesort')

            grouped = ordered.groupby('__series', sort=False, dropna=False)['__value']
            ordered['__value_mean'] = grouped.transform(
                lambda series: series.rolling(7, min_periods=1).mean()
            )
            ordered['__value_std'] = grouped.transform(
                lambda series: series.rolling(7, min_periods=2).std()
            )

            value_mean = np.full(len(data), np.nan, dtype=float)
            value_std = np.full(len(data), np.nan, dtype=float)
            positions = ordered['__row_position'].to_numpy(dtype=int)
            value_mean[positions] = ordered['__value_mean'].to_numpy(dtype=float)
            value_std[positions] = ordered['__value_std'].to_numpy(dtype=float)
            features['value_mean'] = value_mean
            # `min_periods=2` because dispersion is undefined for a single
            # observation, and the result is deliberately NOT filled afterwards. It
            # used to be `.fillna(0)`, which wrote "volatility is exactly zero" for
            # the first row of every series -- a fabricated number of the same kind
            # the point-in-time store exists to prevent. A missing dispersion stays
            # missing and the consumer decides what to do about it.
            features['value_std'] = value_std

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
