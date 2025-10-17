"""CSV file upload plugin for custom data."""

import pandas as pd
from datetime import datetime
from typing import Dict, Any, List, Optional
import logging
import os

from .base import DataSourcePlugin, register_plugin

logger = logging.getLogger(__name__)


class CSVPlugin(DataSourcePlugin):
    """Plugin for CSV file uploads."""

    def validate_config(self) -> None:
        """Validate CSV configuration."""
        if not self.config.get('file_path'):
            raise ValueError("CSV file path is required")

        file_path = self.config['file_path']
        if not os.path.exists(file_path):
            raise ValueError(f"CSV file not found: {file_path}")

    def test_connection(self) -> Dict[str, Any]:
        """Test if CSV file is readable."""
        try:
            file_path = self.config['file_path']

            # Try reading first few rows
            df = pd.read_csv(file_path, nrows=5)

            if df.empty:
                return {
                    "success": False,
                    "message": "CSV file is empty"
                }

            return {
                "success": True,
                "message": f"Successfully read CSV file with {len(df.columns)} columns",
                "details": {
                    "columns": list(df.columns),
                    "rows_sample": len(df)
                }
            }

        except pd.errors.EmptyDataError:
            return {
                "success": False,
                "message": "CSV file is empty"
            }
        except pd.errors.ParserError as e:
            return {
                "success": False,
                "message": f"CSV parsing error: {str(e)}"
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Failed to read CSV: {str(e)}"
            }

    def fetch_asset_data(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Read asset data from CSV file.

        Expected CSV format:
        Date,Asset,Open,High,Low,Close,Volume
        2024-01-01,AAPL,100.0,105.0,99.0,104.0,1000000
        """
        try:
            file_path = self.config['file_path']
            df = pd.read_csv(file_path)

            # Check required columns
            required_cols = ['Date', 'Asset', 'Open', 'High', 'Low', 'Close', 'Volume']
            missing_cols = [col for col in required_cols if col not in df.columns]

            if missing_cols:
                logger.error(f"CSV missing required columns: {missing_cols}")
                return None

            # Convert date column
            df['Date'] = pd.to_datetime(df['Date'])

            # Filter by symbols if specified
            if symbols:
                df = df[df['Asset'].isin(symbols)]

            # Filter by date range
            df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]

            if df.empty:
                logger.warning("No data matches the specified filters")
                return None

            # Ensure correct types
            for col in ['Open', 'High', 'Low', 'Close']:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            df['Volume'] = pd.to_numeric(df['Volume'], errors='coerce').astype('Int64')

            # Select and order columns
            df = df[required_cols]

            logger.info(f"Loaded {len(df)} rows from CSV for {df['Asset'].nunique()} assets")
            return df

        except Exception as e:
            logger.error(f"Error reading CSV file: {e}")
            return None

    def fetch_indicator_data(
        self,
        indicator_id: str,
        start_date: datetime,
        end_date: datetime
    ) -> Optional[pd.DataFrame]:
        """
        Read indicator data from CSV file.

        Expected CSV format:
        Date,Indicator,Value
        2024-01-01,GDP,23000
        """
        try:
            file_path = self.config['file_path']
            df = pd.read_csv(file_path)

            # Check for indicator format
            if 'Indicator' in df.columns:
                # Multi-indicator CSV
                df = df[df['Indicator'] == indicator_id]
                required_cols = ['Date', 'Value']
            else:
                # Single indicator CSV
                required_cols = ['Date', 'Value']

            missing_cols = [col for col in required_cols if col not in df.columns]
            if missing_cols:
                logger.error(f"CSV missing required columns: {missing_cols}")
                return None

            # Convert date column
            df['Date'] = pd.to_datetime(df['Date'])

            # Filter by date range
            df = df[(df['Date'] >= start_date) & (df['Date'] <= end_date)]

            if df.empty:
                logger.warning("No indicator data matches the specified filters")
                return None

            # Ensure correct types
            df['Value'] = pd.to_numeric(df['Value'], errors='coerce')

            # Select and order columns
            df = df[['Date', 'Value']].sort_values('Date')

            logger.info(f"Loaded {len(df)} indicator observations from CSV")
            return df

        except Exception as e:
            logger.error(f"Error reading indicator CSV: {e}")
            return None

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        """Get CSV configuration schema."""
        return {
            "file_path": {
                "type": "string",
                "required": True,
                "label": "CSV File Path",
                "help": "Full path to the CSV file (e.g., /app/data/custom_data.csv)",
                "placeholder": "/app/data/my_data.csv"
            },
            "data_type": {
                "type": "select",
                "required": False,
                "default": "asset",
                "label": "Data Type",
                "options": ["asset", "indicator"],
                "help": "Whether this CSV contains asset prices or indicator data"
            }
        }

    @classmethod
    def get_plugin_info(cls) -> Dict[str, Any]:
        """Get plugin metadata."""
        return {
            "name": "CSV File",
            "description": "Upload custom data from CSV files. Useful for proprietary or historical data.",
            "version": "1.0.0",
            "author": "Liquidity Monitor",
            "free": True,
            "registration_required": False,
            "registration_url": None,
            "data_types": ["stocks", "bonds", "commodities", "indicators"],
            "csv_format_asset": "Date,Asset,Open,High,Low,Close,Volume",
            "csv_format_indicator": "Date,Value"
        }


# Register the plugin
register_plugin("csv", CSVPlugin)
