"""Kaggle bulk dataset plugin for Beacon."""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import zipfile

import pandas as pd

from .base import DataSourcePlugin, register_plugin

logger = logging.getLogger(__name__)

_kaggle_import_error: Optional[Exception]

try:  # pragma: no cover - import side effects depend on environment
    from kaggle.api.kaggle_api_extended import KaggleApi
except Exception as exc:  # noqa: BLE001 - propagate original error in validation
    KaggleApi = None  # type: ignore[assignment]
    _kaggle_import_error = exc
else:
    _kaggle_import_error = None


class KagglePlugin(DataSourcePlugin):
    """Plugin to access Kaggle bulk datasets for historical backfills."""

    def __init__(self, config: Dict[str, Any]):
        self._api: Optional[KaggleApi] = None
        super().__init__(config)

    # ------------------------------------------------------------------
    # Configuration helpers
    # ------------------------------------------------------------------
    def validate_config(self) -> None:
        if not self.config.get("dataset"):
            raise ValueError(
                "Kaggle dataset is required (for example, finnhub/reported-financials). "
                "Set it in Configure."
            )
        if not self.config.get("file_name"):
            raise ValueError(
                "Kaggle file name is required (the file inside the dataset archive). "
                "Set it in Configure."
            )

        cache_dir = Path(self.config.get("cache_dir", "/app/data/kaggle"))
        cache_dir.mkdir(parents=True, exist_ok=True)

    def _get_api(self) -> KaggleApi:
        if self._api is None:
            username = self.config.get("username") or os.getenv("KAGGLE_USERNAME")
            api_key = self.config.get("api_key") or os.getenv("KAGGLE_KEY")
            if username:
                os.environ["KAGGLE_USERNAME"] = str(username)
            if api_key:
                os.environ["KAGGLE_KEY"] = str(api_key)

            api_class = KaggleApi
            if api_class is None:
                # Importing the top-level kaggle package authenticates
                # immediately.  The module-level import above therefore
                # fails on a clean host before the per-source credentials can
                # be applied.  Retry the class import after setting the
                # configured environment credentials.
                try:
                    from kaggle.api.kaggle_api_extended import KaggleApi as LoadedKaggleApi

                    api_class = LoadedKaggleApi
                except Exception as exc:
                    raise ImportError(
                        "Kaggle credentials are required. Enter Kaggle username and API key "
                        "in Configure, or set KAGGLE_USERNAME and KAGGLE_KEY."
                    ) from exc

            api = api_class()
            api.authenticate()
            self._api = api
        return self._api

    # ------------------------------------------------------------------
    # Dataset handling
    # ------------------------------------------------------------------
    def _dataset_cache_path(self) -> Path:
        cache_dir = Path(self.config.get("cache_dir", "/app/data/kaggle"))
        file_name = Path(self.config["file_name"]).name
        return cache_dir / file_name

    def _zip_cache_path(self) -> Path:
        cache_dir = Path(self.config.get("cache_dir", "/app/data/kaggle"))
        file_name = Path(self.config["file_name"]).name
        return cache_dir / f"{file_name}.zip"

    def _ensure_dataset_file(self) -> Path:
        target_path = self._dataset_cache_path()
        force_download = bool(self.config.get("force_download", False))
        if target_path.exists() and not force_download:
            return target_path

        api = self._get_api()
        dataset = self.config["dataset"]
        file_name = self.config["file_name"]
        cache_dir = target_path.parent
        cache_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            "Downloading %s/%s from Kaggle into %s",
            dataset,
            file_name,
            cache_dir,
        )

        api.dataset_download_file(
            dataset,
            file_name,
            path=str(cache_dir),
            force=True,
            quiet=bool(self.config.get("quiet", True)),
        )

        zip_path = self._zip_cache_path()
        if zip_path.exists():
            with zipfile.ZipFile(zip_path, "r") as archive:
                archive.extractall(cache_dir)
            zip_path.unlink()

        if not target_path.exists():
            raise FileNotFoundError(
                f"Downloaded file {file_name} not found in {cache_dir}."
            )

        return target_path

    def _load_dataset(self) -> pd.DataFrame:
        dataset_path = self._ensure_dataset_file()
        suffix = dataset_path.suffix.lower()
        if suffix in {".csv", ".txt"}:
            df = pd.read_csv(dataset_path)
        elif suffix in {".parquet", ".pq"}:
            df = pd.read_parquet(dataset_path)
        elif suffix == ".json":
            df = pd.read_json(dataset_path)
        else:
            raise ValueError(f"Unsupported Kaggle dataset format: {suffix}")

        if df.empty:
            raise ValueError(
                f"Dataset {dataset_path} is empty. Verify dataset configuration."
            )
        return df

    def _resolve_column(self, df: pd.DataFrame, config_key: str, candidates: List[str]) -> str:
        column = self.config.get(config_key)
        if column:
            if column not in df.columns:
                raise ValueError(f"Configured column '{column}' not found in dataset")
            return column

        for candidate in candidates:
            if candidate in df.columns:
                return candidate
        raise ValueError(
            f"None of the expected columns {candidates} found. Configure '{config_key}'."
        )

    # ------------------------------------------------------------------
    # DataSourcePlugin interface
    # ------------------------------------------------------------------
    def test_connection(self) -> Dict[str, Any]:
        try:
            # Validate credentials and dataset access without downloading the
            # full file twice.  ``_load_dataset`` is intentionally the same
            # path used by collection so the probe is meaningful.
            df = self._load_dataset().head(5)
            return {
                "success": True,
                "message": "Successfully accessed Kaggle dataset.",
                "details": {
                    "rows_sample": len(df),
                    "columns": list(df.columns),
                },
            }
        except Exception as exc:  # pragma: no cover - network or auth errors
            logger.error("Kaggle dataset test failed: %s", exc)
            return {
                "success": False,
                "message": f"Kaggle connection failed: {exc}",
            }

    def fetch_asset_data(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime,
    ) -> Optional[pd.DataFrame]:
        df = self._load_dataset()

        date_col = self._resolve_column(df, "date_column", ["date", "Date", "timestamp"])  # type: ignore[arg-type]
        symbol_col = self._resolve_column(
            df,
            "symbol_column",
            ["symbol", "ticker", "Symbol", "Ticker", "Asset"],
        )
        open_col = self._resolve_column(
            df,
            "open_column",
            ["open", "Open"],
        )
        high_col = self._resolve_column(
            df,
            "high_column",
            ["high", "High"],
        )
        low_col = self._resolve_column(
            df,
            "low_column",
            ["low", "Low"],
        )
        close_col = self._resolve_column(
            df,
            "close_column",
            ["close", "Close", "Adj Close", "adjusted_close"],
        )

        volume_col = self.config.get("volume_column")
        if volume_col and volume_col not in df.columns:
            raise ValueError(f"Configured volume column '{volume_col}' not found")
        if not volume_col:
            for candidate in ["volume", "Volume", "shares_traded"]:
                if candidate in df.columns:
                    volume_col = candidate
                    break

        working_df = df.copy()
        working_df[date_col] = pd.to_datetime(working_df[date_col])
        if symbols:
            working_df = working_df[working_df[symbol_col].isin(symbols)]

        working_df = working_df[
            (working_df[date_col] >= start_date) & (working_df[date_col] <= end_date)
        ]

        if working_df.empty:
            return None

        result = pd.DataFrame(
            {
                "Date": working_df[date_col],
                "Asset": working_df[symbol_col],
                "Open": pd.to_numeric(working_df[open_col], errors="coerce"),
                "High": pd.to_numeric(working_df[high_col], errors="coerce"),
                "Low": pd.to_numeric(working_df[low_col], errors="coerce"),
                "Close": pd.to_numeric(working_df[close_col], errors="coerce"),
            }
        )

        if volume_col:
            result["Volume"] = (
                pd.to_numeric(working_df[volume_col], errors="coerce").astype("Int64")
            )
        else:
            result["Volume"] = pd.NA

        return result.sort_values(["Asset", "Date"]).reset_index(drop=True)

    def fetch_indicator_data(
        self,
        indicator_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> Optional[pd.DataFrame]:
        df = self._load_dataset()

        date_col = self._resolve_column(df, "date_column", ["date", "Date"])
        value_col = self._resolve_column(df, "value_column", ["value", "Value", indicator_id])

        indicator_col = self.config.get("indicator_column")
        if indicator_col:
            if indicator_col not in df.columns:
                raise ValueError(
                    f"Configured indicator column '{indicator_col}' not present in dataset"
                )
            df = df[df[indicator_col] == indicator_id]

        if df.empty:
            return None

        df[date_col] = pd.to_datetime(df[date_col])
        filtered = df[(df[date_col] >= start_date) & (df[date_col] <= end_date)]
        if filtered.empty:
            return None

        result = pd.DataFrame(
            {
                "Date": filtered[date_col],
                "Value": pd.to_numeric(filtered[value_col], errors="coerce"),
            }
        )
        return result.sort_values("Date").reset_index(drop=True)

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        return {
            "username": {
                "type": "string",
                "required": False,
                "label": "Kaggle Username",
                "help": "Your Kaggle account username; alternatively set KAGGLE_USERNAME.",
            },
            "api_key": {
                "type": "string",
                "required": False,
                "secret": True,
                "label": "Kaggle API Key",
                "help": "Create a token in Kaggle Account settings; alternatively set KAGGLE_KEY.",
            },
            "dataset": {
                "type": "string",
                "required": True,
                "label": "Kaggle Dataset",
                "placeholder": "finnhub/reported-financials",
            },
            "file_name": {
                "type": "string",
                "required": True,
                "label": "File Name",
                "placeholder": "reported_financials.csv",
            },
            "cache_dir": {
                "type": "string",
                "required": False,
                "label": "Cache Directory",
                "default": "/app/data/kaggle",
            },
            "force_download": {
                "type": "boolean",
                "required": False,
                "label": "Force Download",
                "default": False,
            },
            "date_column": {
                "type": "string",
                "required": False,
                "label": "Date Column",
            },
            "symbol_column": {
                "type": "string",
                "required": False,
                "label": "Symbol Column",
            },
            "open_column": {
                "type": "string",
                "required": False,
                "label": "Open Column",
            },
            "high_column": {
                "type": "string",
                "required": False,
                "label": "High Column",
            },
            "low_column": {
                "type": "string",
                "required": False,
                "label": "Low Column",
            },
            "close_column": {
                "type": "string",
                "required": False,
                "label": "Close Column",
            },
            "volume_column": {
                "type": "string",
                "required": False,
                "label": "Volume Column",
            },
            "indicator_column": {
                "type": "string",
                "required": False,
                "label": "Indicator Column",
            },
            "value_column": {
                "type": "string",
                "required": False,
                "label": "Value Column",
            },
        }

    @classmethod
    def get_plugin_info(cls) -> Dict[str, Any]:
        return {
            "name": "Kaggle Bulk Dataset",
            "description": "Download large historical datasets from Kaggle for offline backfills.",
            "version": "1.0.0",
            "author": "Beacon AI",
            "free": True,
            "registration_required": True,
            "registration_url": "https://www.kaggle.com/account/login?phase=startRegisterTab",
        }


register_plugin("kaggle", KagglePlugin)
