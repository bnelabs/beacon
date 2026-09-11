"""AI4Risk Interbank Network Dataset Plugin

Source: https://github.com/AI4Risk/interbank
Coverage: 4,548 banks, 2016Q1-2023Q1, quarterly
Features: 300+ bank features, interbank networks, credit ratings, SRISK

FREE - No API required, static dataset download
Registration: Not required
Documentation: https://github.com/AI4Risk/interbank

This plugin provides access to real interbank network topology and bank features
for training temporal GNN models on financial contagion and systemic risk.

The dataset is file-backed and must be downloaded by the operator. When it is
absent this plugin fails with :class:`DatasetMissingError` rather than
synthesising replacement data, because downstream risk scores cannot be
distinguished from plausible-looking fiction once fake exposure edges enter the
graph.
"""

import logging
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from backend.exceptions import (
    DatasetMissingError,
    EmptyDatasetError,
    SchemaValidationError,
)

from .base import DataSourcePlugin, register_plugin

logger = logging.getLogger(__name__)

DOWNLOAD_URL = "https://github.com/AI4Risk/interbank"

SUPPORTED_ITEMS = (
    "network_topology",
    "bank_features:<BANK_ID>",
    "credit_ratings",
    "systemic_risk",
)


class AI4RiskInterbankPlugin(DataSourcePlugin):
    """Plugin for AI4Risk Interbank Network Dataset."""

    def __init__(self, config: Dict[str, Any] = None):
        super().__init__(config or {})
        self.data_dir = self.config.get('data_dir', './data/ai4risk/')
        self.plugin_type = "ai4risk_interbank"

    def validate_config(self) -> None:
        """Require that the downloaded dataset directory exists.

        Raises:
            DatasetMissingError: When the dataset has not been downloaded.
        """
        data_dir = self.config.get('data_dir', './data/ai4risk/')
        if not os.path.isdir(data_dir):
            raise DatasetMissingError(
                f"AI4Risk dataset directory not found: {data_dir}",
                context={
                    "data_dir": data_dir,
                    "download_url": DOWNLOAD_URL,
                    "remediation": (
                        "Download the dataset from "
                        f"{DOWNLOAD_URL} and extract it into {data_dir}"
                    ),
                },
            )

    def test_connection(self) -> Dict[str, Any]:
        """Report whether the local AI4Risk dataset is present and usable."""
        try:
            files = os.listdir(self.data_dir)
        except OSError as exc:
            return {
                "success": False,
                "message": f"AI4Risk dataset directory is not readable: {self.data_dir}",
                "details": {
                    "error_code": "DATASET_MISSING",
                    "data_dir": self.data_dir,
                    "download_url": DOWNLOAD_URL,
                    "error": str(exc),
                },
            }

        expected = ("interbank_network.csv", "bank_features.csv", "credit_ratings.csv")
        present = [name for name in expected if name in files]
        if not present:
            return {
                "success": False,
                "message": (
                    f"AI4Risk data directory '{self.data_dir}' contains no recognised "
                    f"dataset files (expected one of: {', '.join(expected)})"
                ),
                "details": {
                    "error_code": "DATASET_MISSING",
                    "data_dir": self.data_dir,
                    "download_url": DOWNLOAD_URL,
                    "files": files[:5],
                },
            }

        return {
            "success": True,
            "message": f"AI4Risk dataset found ({len(present)}/{len(expected)} files present)",
            "details": {"data_dir": self.data_dir, "files": present},
        }

    def fetch_indicator_data(
        self,
        indicator_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """Alias for fetch_data to match base class interface."""
        return self.fetch_data(indicator_id, start_date, end_date)

    def fetch_asset_data(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """AI4Risk publishes interbank network topology, not tradable prices.

        Raises:
            SchemaValidationError: Always; this plugin has no asset series.
        """
        raise SchemaValidationError(
            "AI4Risk plugin does not provide asset price data",
            context={"symbols": list(symbols), "supported": list(SUPPORTED_ITEMS)},
        )

    def fetch_data(
        self,
        item_identifier: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Fetch interbank network data.

        Item identifier formats:
        - "network_topology" - Full interbank network edges (bank-to-bank exposures)
        - "bank_features:BANK_ID" - 300+ features for specific bank
        - "credit_ratings" - All bank credit ratings and SRISK indicators
        - "systemic_risk" - Systemic risk measures across all banks

        Raises:
            DatasetMissingError: The requested dataset file is absent.
            SchemaValidationError: The dataset does not match the expected schema.
            EmptyDatasetError: The dataset has no rows for the requested period.
            DataSourceUnavailableError: The dataset could not be read.
        """
        if item_identifier == "network_topology":
            return self._fetch_network_topology(start_date, end_date)
        if item_identifier.startswith("bank_features:"):
            bank_id = item_identifier.split(":", 1)[1]
            return self._fetch_bank_features(bank_id, start_date, end_date)
        if item_identifier == "credit_ratings":
            return self._fetch_credit_ratings(start_date, end_date)
        if item_identifier == "systemic_risk":
            return self._fetch_systemic_risk(start_date, end_date)

        raise SchemaValidationError(
            f"Unknown AI4Risk item identifier: {item_identifier}",
            context={"supported": list(SUPPORTED_ITEMS)},
        )

    def _read_dataset(self, filename: str) -> pd.DataFrame:
        """Read a dataset file, failing loudly when it is absent or unreadable."""
        path = os.path.join(self.data_dir, filename)
        if not os.path.isfile(path):
            raise DatasetMissingError(
                f"AI4Risk dataset file not found: {path}",
                context={
                    "file": path,
                    "download_url": DOWNLOAD_URL,
                    "remediation": f"Download the dataset from {DOWNLOAD_URL} into {self.data_dir}",
                },
            )
        try:
            return pd.read_csv(path)
        except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as exc:
            raise SchemaValidationError(
                f"AI4Risk dataset file could not be parsed: {path}",
                context={"file": path, "error": str(exc)},
                cause=exc,
            ) from exc

    def _resolve_date_column(self, df: pd.DataFrame, filename: str) -> pd.DataFrame:
        """Normalise the quarter/date column onto a 'Date' column."""
        source = next((col for col in ("quarter", "date", "Date") if col in df.columns), None)
        if source is None:
            raise SchemaValidationError(
                f"AI4Risk dataset '{filename}' has no date column",
                context={"columns": list(df.columns), "expected_any_of": ["quarter", "date", "Date"]},
            )
        df = df.copy()
        df["Date"] = pd.to_datetime(df[source], errors="coerce")
        if df["Date"].isna().all():
            raise SchemaValidationError(
                f"AI4Risk dataset '{filename}' has no parseable dates",
                context={"column": source},
            )
        return df

    def _fetch_network_topology(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """
        Fetch interbank network edges (bank-to-bank exposures).

        This provides the critical network topology for GNN training.
        """
        df = self._resolve_date_column(self._read_dataset('interbank_network.csv'), 'interbank_network.csv')

        column_mapping = {
            'bank_i': 'source_bank',
            'bank_j': 'target_bank',
            'source': 'source_bank',
            'target': 'target_bank',
            'exposure': 'Value',
            'weight': 'Value',
            'amount': 'Value',
        }
        df = df.rename(columns={k: v for k, v in column_mapping.items() if k in df.columns})

        required_cols = ['Date', 'source_bank', 'target_bank', 'Value']
        missing = [col for col in required_cols if col not in df.columns]
        if missing:
            raise SchemaValidationError(
                "AI4Risk network dataset is missing required columns",
                context={"missing": missing, "present": list(df.columns)},
            )

        df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]
        if df.empty:
            raise EmptyDatasetError(
                "No AI4Risk network edges in the requested period",
                context={"start_date": str(start_date), "end_date": str(end_date)},
            )
        return df[required_cols].sort_values('Date')

    def _fetch_bank_features(
        self,
        bank_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """
        Fetch 300+ features for a specific bank.

        Features include: assets, equity, debt, liquidity ratios, performance metrics, etc.
        """
        df = self._resolve_date_column(self._read_dataset('bank_features.csv'), 'bank_features.csv')

        id_column = next((col for col in ('bank_id', 'BANK_ID', 'id') if col in df.columns), None)
        if id_column is None:
            raise SchemaValidationError(
                "AI4Risk bank features dataset has no bank identifier column",
                context={"columns": list(df.columns)},
            )
        df = df[df[id_column] == bank_id]

        df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]
        if df.empty:
            raise EmptyDatasetError(
                f"No AI4Risk features found for bank '{bank_id}' in the requested period",
                context={
                    "bank_id": bank_id,
                    "start_date": str(start_date),
                    "end_date": str(end_date),
                },
            )

        id_cols = ['Date']
        if 'bank_id' in df.columns:
            id_cols.append('bank_id')

        feature_cols = [
            col for col in df.columns
            if col not in id_cols + ['quarter', 'date', 'id', 'BANK_ID']
        ]
        if not feature_cols:
            raise SchemaValidationError(
                f"AI4Risk bank features dataset has no feature columns for bank '{bank_id}'",
                context={"columns": list(df.columns)},
            )

        df_long = df.melt(
            id_vars=id_cols,
            value_vars=feature_cols,
            var_name='feature',
            value_name='Value'
        )

        return df_long[['Date', 'Value', 'feature', 'bank_id']].sort_values('Date')

    def _fetch_credit_ratings(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """
        Fetch credit ratings and SRISK (systemic risk) indicators.

        SRISK measures how much capital a bank would need in a systemic crisis.
        """
        df = self._resolve_date_column(self._read_dataset('credit_ratings.csv'), 'credit_ratings.csv')

        if 'rating' in df.columns and df['rating'].dtype == 'object':
            rating_map = {
                'AAA': 1, 'AA+': 2, 'AA': 3, 'AA-': 4,
                'A+': 5, 'A': 6, 'A-': 7,
                'BBB+': 8, 'BBB': 9, 'BBB-': 10,
                'BB+': 11, 'BB': 12, 'BB-': 13,
                'B+': 14, 'B': 15, 'B-': 16,
                'CCC': 17, 'CC': 18, 'C': 19, 'D': 20
            }
            df['rating_numeric'] = df['rating'].map(rating_map)

        if 'rating_numeric' in df.columns:
            df['Value'] = df['rating_numeric']
        elif 'srisk' in df.columns:
            df['Value'] = df['srisk']
        else:
            raise SchemaValidationError(
                "AI4Risk credit ratings dataset has neither a recognisable rating nor an srisk column",
                context={"columns": list(df.columns)},
            )

        if 'bank_id' not in df.columns:
            raise SchemaValidationError(
                "AI4Risk credit ratings dataset has no bank identifier column",
                context={"columns": list(df.columns)},
            )

        df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]
        if df.empty:
            raise EmptyDatasetError(
                "No AI4Risk credit ratings in the requested period",
                context={"start_date": str(start_date), "end_date": str(end_date)},
            )
        return df[['Date', 'bank_id', 'Value']].sort_values('Date')

    def _fetch_systemic_risk(
        self,
        start_date: datetime,
        end_date: datetime
    ) -> pd.DataFrame:
        """Fetch system-wide systemic risk measures."""
        ratings_df = self._fetch_credit_ratings(start_date, end_date)

        system_risk = ratings_df.groupby('Date').agg({
            'Value': ['mean', 'max', 'std']
        }).reset_index()

        system_risk.columns = ['Date', 'mean_risk', 'max_risk', 'risk_volatility']
        system_risk['Value'] = system_risk['mean_risk']

        return system_risk[['Date', 'Value']].sort_values('Date')

    def test_item(self, item_identifier: str) -> Dict[str, Any]:
        """Test AI4Risk data access for a single item."""
        try:
            end_date = datetime.now()
            start_date = datetime(end_date.year - 1, 1, 1)

            df = self.fetch_data(item_identifier, start_date, end_date)

            if df is None or df.empty:
                return {
                    "success": False,
                    "message": f"No data found for {item_identifier}",
                    "details": {"error_code": "EMPTY_DATASET"},
                }

            return {
                "success": True,
                "message": f"Successfully accessed AI4Risk data for {item_identifier}. Found {len(df)} records.",
                "details": {
                    "records": len(df),
                    "date_range": f"{df['Date'].min().date()} to {df['Date'].max().date()}",
                    "columns": df.columns.tolist()[:10],
                },
            }
        except Exception as e:
            error_code = getattr(e, "code", "DATA_INGESTION_FAILED")
            logger.error("Error testing AI4Risk item %s: %s", item_identifier, e)
            return {
                "success": False,
                "message": f"Failed to access {item_identifier}: {e}",
                "details": {"error_code": error_code, "error": str(e)},
            }

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Get configuration schema."""
        return {
            "data_dir": {
                "type": "string",
                "required": False,
                "default": "./data/ai4risk/",
                "label": "Data Directory",
                "help": f"Path to downloaded AI4Risk dataset (download from {DOWNLOAD_URL})"
            }
        }

    @classmethod
    def get_plugin_info(cls) -> Dict[str, Any]:
        """Get plugin metadata."""
        return {
            "name": "AI4Risk Interbank Network",
            "description": "Real interbank network topology and bank features for 4,548 banks (2016Q1-2023Q1)",
            "version": "1.1.0",
            "author": "BEACON",
            "free": True,
            "registration_required": False,
            "registration_url": None,
            "download_url": DOWNLOAD_URL,
            "data_types": ["interbank_networks", "credit_risk", "systemic_risk", "bank_features"],
            "coverage": "4,548 banks globally, quarterly snapshots",
            "frequency": "quarterly",
            "temporal": True,
            "network_topology": True
        }


# Register the plugin
register_plugin("ai4risk_interbank", AI4RiskInterbankPlugin)
