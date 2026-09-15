"""New York Fed reference-rates plugin (keyless public API).

Funding liquidity is the input the Brunnermeier-Pedersen spiral needs and the
platform never had: SOFR (secured overnight funding), EFFR (unsecured) and
OBFR (overnight bank funding) are the benchmarks whose spikes and spreads
mark funding stress. The NY Fed publishes them through a free, keyless JSON
API.

The API's payload shape has changed across versions, so parsing accepts the
documented list-of-records forms and refuses silently-missing fields rather
than inventing columns.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

from .base import DataSourcePlugin, register_plugin

logger = logging.getLogger(__name__)

SUPPORTED = ("sofr", "effr", "obfr", "sofr99th")
BASE = "https://api.newyorkfed.org/api/rates/{rate}"


class NYFedPlugin(DataSourcePlugin):
    """NY Fed overnight reference rates (SOFR/EFFR/OBFR/SOFR99)."""

    def validate_config(self) -> None:
        rates = self.config.get("rates", list(SUPPORTED))
        unknown = [rate for rate in rates if rate not in SUPPORTED]
        if unknown:
            raise ValueError(f"unsupported rate(s): {unknown}; supported: {SUPPORTED}")

    def test_connection(self) -> Dict[str, Any]:
        try:
            response = requests.get(f"{BASE.format(rate='sofr')}/json", timeout=15)
            ok = response.status_code == 200
            return {"success": ok, "message": "NY Fed rates reachable" if ok else f"HTTP {response.status_code}"}
        except requests.RequestException as exc:
            return {"success": False, "message": str(exc)}

    def _records(self, rate: str) -> List[Dict[str, Any]]:
        response = requests.get(f"{BASE.format(rate=rate)}/json", timeout=30)
        response.raise_for_status()
        payload = response.json()
        for key in (rate, "rates", "data", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        if isinstance(payload, list):
            return payload
        raise ValueError(f"unrecognised NY Fed payload shape for {rate!r}: {sorted(payload)}")

    def fetch_indicator_data(
        self,
        indicator_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> Optional[pd.DataFrame]:
        rate = str(indicator_id).lower()
        if rate not in SUPPORTED:
            raise ValueError(f"unsupported rate {indicator_id!r}; supported: {SUPPORTED}")

        records = self._records(rate)
        frame = pd.DataFrame(records)
        date_col = next((c for c in ("date", "effectiveDate", "effective_date") if c in frame.columns), None)
        value_col = next((c for c in ("percent", "percentRate", "rate", "value") if c in frame.columns), None)
        if date_col is None or value_col is None:
            raise ValueError(f"NY Fed payload for {rate!r} lacks date/value columns: {sorted(frame.columns)}")

        frame["Date"] = pd.to_datetime(frame[date_col], errors="coerce")
        frame["Value"] = pd.to_numeric(frame[value_col], errors="coerce")
        frame = frame.dropna(subset=["Date", "Value"])
        frame = frame[(frame["Date"] >= pd.Timestamp(start_date)) & (frame["Date"] <= pd.Timestamp(end_date))]
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
                frames.append(frame.assign(Asset=symbol))
        if not frames:
            return None
        return pd.concat(frames, ignore_index=True)

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        return {
            "rates": {
                "type": "list",
                "required": False,
                "default": list(SUPPORTED),
                "label": "Rates to expose",
                "help": f"Subset of {SUPPORTED}",
            }
        }

    @classmethod
    def get_plugin_info(cls) -> Dict[str, Any]:
        return {
            "name": "NY Fed Reference Rates",
            "description": "SOFR/EFFR/OBFR/SOFR99 overnight funding benchmarks (keyless)",
            "version": "1.0.0",
            "author": "BEACON",
            "free": True,
            "registration_required": False,
            "registration_url": None,
            "data_types": ["interest_rates", "funding"],
            "flexible": False,
        }


register_plugin("nyfed", NYFedPlugin)
