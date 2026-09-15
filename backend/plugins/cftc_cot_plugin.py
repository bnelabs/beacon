"""CFTC Commitments-of-Traders plugin (keyless Socrata endpoint).

Crowded-trade overlap (`engine/portfolio_overlap.py`) has had no positioning
input since it was written. The CFTC publishes the weekly COT report through
a public Socrata API with no key; the TFF (Trader-Funding-Category) dataset
gives aggregate long/short positions by trader category, which is the closest
observable proxy for crowding in futures markets.

The Socrata resource id is configurable because the CFTC has re-published
datasets under new ids before; the default is the legacy TFF report. Rows are
returned as-is (one per market/trader-category/week); aggregation into
positioning measures belongs to the overlap module, not the plugin.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

from .base import DataSourcePlugin, register_plugin

logger = logging.getLogger(__name__)

DEFAULT_RESOURCE = "6dca-aqww"
BASE = "https://publicreporting.cftc.gov/resource/{resource}.json"


class CFTCCotPlugin(DataSourcePlugin):
    """Weekly COT positioning via the public Socrata API (no key)."""

    def validate_config(self) -> None:
        resource = self.config.get("resource_id", DEFAULT_RESOURCE)
        if not isinstance(resource, str) or not resource.strip():
            raise ValueError("resource_id must be a non-empty Socrata resource id")

    def test_connection(self) -> Dict[str, Any]:
        url = BASE.format(resource=self.config.get("resource_id", DEFAULT_RESOURCE))
        try:
            response = requests.get(url, params={"$limit": 1}, timeout=15)
            ok = response.status_code == 200
            return {"success": ok, "message": "CFTC COT reachable" if ok else f"HTTP {response.status_code}"}
        except requests.RequestException as exc:
            return {"success": False, "message": str(exc)}

    def fetch_indicator_data(
        self,
        indicator_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> Optional[pd.DataFrame]:
        """Fetch COT rows for one market (``indicator_id`` = commodity/market code)."""
        url = BASE.format(resource=self.config.get("resource_id", DEFAULT_RESOURCE))
        params = {
            "$limit": 50000,
            "$where": (
                f"report_date between '{start_date:%Y-%m-%d}' and '{end_date:%Y-%m-%d}'"
            ),
        }
        if indicator_id and indicator_id != "all":
            params["$where"] += f" AND commodity_code = '{indicator_id}'"

        response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()
        rows = response.json()
        if not rows:
            return None

        frame = pd.DataFrame(rows)
        if "report_date" in frame.columns:
            frame["Date"] = pd.to_datetime(frame["report_date"], errors="coerce")
        value_candidates = [
            column for column in frame.columns
            if column.startswith(("long_", "short_", "open_interest"))
        ]
        if not value_candidates:
            return None
        frame["Value"] = pd.to_numeric(frame[value_candidates[0]], errors="coerce")
        frame = frame.dropna(subset=["Date", "Value"])
        if frame.empty:
            return None
        return frame[["Date", "Value"]].sort_values("Date")

    def fetch_asset_data(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime,
    ) -> Optional[pd.DataFrame]:
        frames = []
        for symbol in symbols:
            frame = self.fetch_indicator_data(symbol, start_date, end_date)
            if frame is not None:
                frame = frame.assign(Asset=symbol)
                frames.append(frame)
        if not frames:
            return None
        return pd.concat(frames, ignore_index=True)

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        return {
            "resource_id": {
                "type": "string",
                "required": False,
                "default": DEFAULT_RESOURCE,
                "label": "Socrata resource id",
                "help": "CFTC public reporting dataset id (TFF legacy by default)",
            }
        }

    @classmethod
    def get_plugin_info(cls) -> Dict[str, Any]:
        return {
            "name": "CFTC COT",
            "description": "Weekly commitments of traders; positioning proxy for crowded-trade overlap",
            "version": "1.0.0",
            "author": "BEACON",
            "free": True,
            "registration_required": False,
            "registration_url": None,
            "data_types": ["positioning", "derivatives"],
            "flexible": False,
        }


register_plugin("cftc_cot", CFTCCotPlugin)
