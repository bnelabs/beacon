"""FDIC BankFind Suite plugin (keyless supervisory financials).

The FDIC publishes quarterly bank-level financials through the BankFind Suite
API with no key. This is the supervisory-aggregate source BEACON's US
institution data should come from: total assets, deposits, equity and
performance ratios per CERT, per reporting date.

Provenance of this rewrite
--------------------------

The previous ``fdic_plugin.py`` imported ``backend.plugins.base_plugin``, a
module that never existed in the repository's history: the plugin was dead on
arrival, unregistered, and unimportable, while the frontend advertised FDIC as
an enabled source. It also queried the ``institutions`` endpoint for financial
fields that endpoint does not carry. This rewrite is verified against the live
API (2026-09-15): uppercase field names, the ``item["data"]`` response
nesting, and the ``CERT:<n> AND REPDTE:[<start> TO <end>]`` filter syntax all
return real data (probe: CERT 628, JPMorgan Chase Bank NA).

Only fields verified against the live API are declared in
:data:`SUPPORTED_FIELDS`. An undeclared field is refused with a typed error
rather than guessed at the API, and the interbank marginal fields that would
feed ``POST /api/v1/network/estimate`` are a documented follow-on: they were
not in the default field set of the probe and will not be declared until they
are verified the same way.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd
import requests

from .base import DataSourcePlugin, register_plugin

logger = logging.getLogger(__name__)

FINANCIALS_URL = "https://api.fdic.gov/banks/financials"

#: Fields verified against the live API on 2026-09-15 (CERT 628 probe).
#: Adding a field means verifying it the same way; guessing field names at a
#: supervisory API is how the previous dead plugin happened.
SUPPORTED_FIELDS: Dict[str, str] = {
    "ASSET": "Total assets (USD)",
    "DEP": "Total deposits (USD)",
    "DEPDOM": "Domestic deposits (USD)",
    "EQTOT": "Total equity capital (USD)",
    "LNLSNET": "Net loans and leases (USD)",
    "NETINC": "Net income (USD)",
    "ROA": "Return on assets (%, annualised)",
    "ROE": "Return on equity (%, annualised)",
}

PROBE_CERT = "628"  # a large, permanently-present institution; probe only


class FDICFieldError(ValueError):
    """An undeclared field or malformed indicator was requested."""


class FDICPlugin(DataSourcePlugin):
    """Quarterly supervisory financials from the FDIC BankFind Suite API."""

    def validate_config(self) -> None:
        """Keyless source: nothing to validate beyond the optional timeout."""
        timeout = self.config.get("timeout", 30)
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            raise ValueError("timeout must be a positive number of seconds")

    def test_connection(self) -> Dict[str, Any]:
        """One-row probe of the financials index; reports the row it got."""
        try:
            response = requests.get(
                FINANCIALS_URL,
                params={"limit": 1, "format": "json"},
                timeout=float(self.config.get("timeout", 30)),
            )
            if response.status_code != 200:
                return {
                    "success": False,
                    "message": f"FDIC API returned HTTP {response.status_code}",
                }
            payload = response.json()
            rows = payload.get("data") or []
            if not rows:
                return {"success": False, "message": "FDIC API returned no rows"}
            return {
                "success": True,
                "message": "Connected to FDIC BankFind Suite API (keyless)",
                "details": {
                    "index_total": payload.get("meta", {}).get("total"),
                    "probe_row_keys": len(rows[0].get("data", {})),
                },
            }
        except requests.RequestException as exc:
            return {"success": False, "message": str(exc)}

    def fetch_asset_data(
        self,
        symbols: List[str],
        start_date: datetime,
        end_date: datetime,
    ) -> Optional[pd.DataFrame]:
        """FDIC publishes supervisory financials, not market prices."""
        logger.warning("FDIC plugin does not provide asset price data")
        return None

    def fetch_indicator_data(
        self,
        indicator_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> Optional[pd.DataFrame]:
        """Fetch one verified financial field for one institution over time.

        Args:
            indicator_id: ``FIELD:CERT`` -- e.g. ``ASSET:628`` for total
                assets of JPMorgan Chase Bank NA. ``FIELD`` must be in
                :data:`SUPPORTED_FIELDS`; anything else raises
                :class:`FDICFieldError` rather than being passed to the API.
            start_date: First reporting date to include (inclusive).
            end_date: Last reporting date to include (inclusive).

        Returns:
            DataFrame with ``Date`` (report date) and ``Value`` columns,
            ordered by date. ``None`` when the API returned no rows for the
            declaration (an empty series is a fact, logged as such).
        """
        field, cert = self._parse_indicator(indicator_id)
        filters = (
            f"CERT:{cert} AND "
            f"REPDTE:[{start_date:%Y%m%d} TO {end_date:%Y%m%d}]"
        )
        try:
            response = requests.get(
                FINANCIALS_URL,
                params={
                    "filters": filters,
                    "fields": f"CERT,NAME,REPDTE,{field}",
                    "limit": 1000,
                    "sort_by": "REPDTE",
                    "sort_order": "ASC",
                    "format": "json",
                },
                timeout=float(self.config.get("timeout", 30)),
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.error("FDIC API request failed for %s: %s", indicator_id, exc)
            return None

        rows = (response.json() or {}).get("data") or []
        records = []
        for row in rows:
            record = row.get("data") or {}
            value = record.get(field)
            if value is None:
                # A reporting date where the field is null is a gap in the
                # supervisory record; it is dropped, never zero-filled.
                continue
            records.append(
                {
                    "Date": pd.to_datetime(str(record["REPDTE"]), format="%Y%m%d"),
                    "Value": float(value),
                }
            )
        if not records:
            logger.warning(
                "FDIC returned no observations for %s between %s and %s",
                indicator_id, start_date.date(), end_date.date(),
            )
            return None
        df = pd.DataFrame(records).sort_values("Date").reset_index(drop=True)
        logger.info("Fetched %d FDIC observations for %s", len(df), indicator_id)
        return df

    @staticmethod
    def _parse_indicator(indicator_id: str) -> tuple[str, str]:
        parts = (indicator_id or "").split(":")
        if len(parts) != 2 or not parts[0].strip() or not parts[1].strip():
            raise FDICFieldError(
                f"indicator {indicator_id!r} must be FIELD:CERT, e.g. ASSET:628"
            )
        field = parts[0].strip().upper()
        cert = parts[1].strip()
        if field not in SUPPORTED_FIELDS:
            raise FDICFieldError(
                f"field {field!r} is not declared in SUPPORTED_FIELDS; only "
                f"fields verified against the live API are served: "
                f"{sorted(SUPPORTED_FIELDS)}"
            )
        if not cert.isdigit():
            raise FDICFieldError(f"CERT {cert!r} must be the numeric FDIC certificate number")
        return field, cert

    @classmethod
    def get_config_schema(cls) -> Dict[str, Any]:
        return {
            "timeout": {
                "type": "number",
                "required": False,
                "default": 30,
                "label": "Request timeout (seconds)",
            }
        }

    @classmethod
    def get_plugin_info(cls) -> Dict[str, Any]:
        return {
            "name": "FDIC BankFind Suite",
            "description": (
                "Quarterly US bank supervisory financials (assets, deposits, "
                "equity, profitability) from the FDIC -- keyless"
            ),
            "version": "2.0.0",
            "author": "BNE Labs",
            "free": True,
            "registration_required": False,
            "data_types": ["supervisory_financials"],
            "example_series": ["ASSET:628", "DEP:628", "EQTOT:628", "ROA:628"],
        }


# Register the plugin
register_plugin("fdic", FDICPlugin)
