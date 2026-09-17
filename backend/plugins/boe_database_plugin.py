"""Bank of England Interactive Database plugin (keyless, HTML-table interface).

What the probe established (docs/probes/boe_endpoint_probe.md, executed
2026-09-17 — every statement below was observed, not inferred):

* there is no REST/JSON service and no stateless CSV switch: the Interactive
  Database at ``boeapps/database`` is a server-rendered ASP application whose
  ``FromShowColumns.asp`` answers with an HTML table (``csv.x=yes`` does not
  change the content type; ISO dates are refused — ``DD/Mon/YYYY`` only);
* the table structure is regular: a thead naming the series ("Official Bank
  Rate" + code ``IUDBEDR``), then one ``<td>date</td><td>value</td>`` row per
  observation;
* no authentication, no API key, no registration.

This plugin is therefore a strict HTML-table reader, exactly as the probe's
YELLOW-path contract prescribes:

* **schema drift fails loudly.** A missing data table, a header without the
  series code, an unparseable date or a non-numeric value raises
  :class:`BoEDatabaseError` — the platform's typed-error, no-synthetic-data
  rule. Nothing here degrades to "empty data" when the page changed shape;
  empty *is* distinguishable from drifted, and both are reported as what
  they are (an empty window returns ``None`` per the plugin contract).
* **evidence-first catalogue.** Only series whose responses were actually
  observed during the probe ship in the built-in catalogue (``IUDBEDR``).
  Additional codes may be declared through the source's ``series`` config —
  an operator declaring an input is the platform's normal contract — but the
  plugin never guesses series codes.
* **politeness is part of the contract.** One request per fetch, an
  identifying User-Agent, and the timeout is configurable. The probe found
  no published rate limits; that absence is a reason for restraint, not for
  hammering.

Licence, RESOLVED 2026-09-18: the reuse terms live at
``bankofengland.co.uk/legal`` — the paths tried during the probe
(``/copyright`` and ``/terms-and-conditions``) both 404; ``/legal`` is the
real page, found by search on 2026-09-18. Its "Bank of England Database"
section states that the Database is the copyright of the Governor and
Company of the Bank of England and that "Reproduction of data in the
Database is subject to the terms of the UK Open Government Licence",
"allowing and encouraging free and flexible data reuse". Derived products
should carry the standard OGL v3 attribution ("Contains public sector
information licensed under the Open Government Licence v3.0"). Two scope
notes from the same page, recorded because they bind any catalogue
expansion: third-party-owned series are NOT covered by the grant — the page
names LSEG spot-exchange-rate data as requiring LSEG's own approval, and
the built-in catalogue holds only the BoE's own Bank Rate — and SONIA /
SONIA Compounded Index series carry a required attribution statement of
their own if they are ever added.

Date parsing note: the interface renders two-digit years (``02 Jan 24``).
Two-digit years are resolved with an explicit pivot — ``yy`` greater than
the current year's last two digits maps to the 1900s, otherwise the 2000s —
because Bank Rate history reaches back to 1694 and Python's ``%y`` pivot
(2069) would read ``57`` as 2057. The pivot is a declared rule, not a
heuristic, and it is tested at its boundary.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
import requests

from .base import DataSourcePlugin, register_plugin

logger = logging.getLogger(__name__)

BASE_URL = "https://www.bankofengland.co.uk/boeapps/database/fromshowcolumns.asp"
USER_AGENT = (
    "beacon-platform (systemic-risk monitoring; data-source plugin; "
    "+https://github.com/bnelabs/beacon)"
)

#: alias -> BoE series code. Only probe-verified series are built in.
SERIES_CATALOGUE: Dict[str, str] = {
    "bank_rate": "IUDBEDR",
    "iudbedr": "IUDBEDR",
    "official_bank_rate": "IUDBEDR",
}

SERIES_LABELS: Dict[str, str] = {
    "IUDBEDR": "Official Bank Rate",
}


class BoEDatabaseError(ValueError):
    """The BoE Interactive Database could not serve a parseable answer.

    A subclass of ValueError so the platform's generic plugin-error handling
    applies, while callers (and tests) can name the failure precisely: an
    HTTP status, an ErrorPage redirect, a missing table or schema drift are
    facts about the endpoint, never empty data.
    """


class _TableExtractor(HTMLParser):
    """Collect every table's rows as cell-text lists, flagging header rows."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: List[List[Tuple[List[str], bool]]] = []
        self._rows: Optional[List[Tuple[List[str], bool]]] = None
        self._cells: Optional[List[str]] = None
        self._cell: Optional[List[str]] = None
        self._row_is_header = False

    def handle_starttag(self, tag: str, attrs) -> None:
        if tag == "table":
            self._rows = []
        elif tag == "tr" and self._rows is not None:
            self._cells = []
            self._row_is_header = False
        elif tag in ("td", "th") and self._cells is not None:
            self._cell = []
            if tag == "th":
                self._row_is_header = True

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._cell is not None and self._cells is not None:
            self._cells.append(re.sub(r"\s+", " ", "".join(self._cell)).strip())
            self._cell = None
        elif tag == "tr" and self._cells is not None and self._rows is not None:
            self._rows.append((self._cells, self._row_is_header))
            self._cells = None
        elif tag == "table" and self._rows is not None:
            self.tables.append(self._rows)
            self._rows = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _parse_boe_date(text: str) -> pd.Timestamp:
    """Parse ``DD Mon YYYY`` or ``DD Mon YY`` with the declared century pivot."""
    cleaned = text.strip()
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return pd.Timestamp(datetime.strptime(cleaned, fmt))
        except ValueError:
            continue
    match = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]{3,})\s+(\d{2})", cleaned)
    if match is None:
        raise BoEDatabaseError(f"unparseable BoE date cell: {text!r}")
    day, month, yy = int(match.group(1)), match.group(2), int(match.group(3))
    current_yy = datetime.now().year % 100
    year = 1900 + yy if yy > current_yy else 2000 + yy
    try:
        return pd.Timestamp(datetime.strptime(f"{day} {month} {year}", "%d %b %Y"))
    except ValueError as exc:
        raise BoEDatabaseError(f"unparseable BoE date cell: {text!r}") from exc


class BoEDatabasePlugin(DataSourcePlugin):
    """Official Bank Rate (and operator-declared series) from the BoE database."""

    def _catalogue(self) -> Dict[str, str]:
        catalogue = dict(SERIES_CATALOGUE)
        extra = self.config.get("series") or {}
        if not isinstance(extra, dict):
            raise BoEDatabaseError("'series' config must be a mapping of alias -> BoE series code")
        for alias, code in extra.items():
            if not isinstance(code, str) or not code.strip():
                raise BoEDatabaseError(f"'series' config entry {alias!r} has no series code")
            catalogue[str(alias).lower()] = code.strip().upper()
        return catalogue

    def validate_config(self) -> None:
        self._catalogue()  # raises on malformed config; nothing else to check

    def _resolve(self, indicator_id: str) -> str:
        catalogue = self._catalogue()
        key = str(indicator_id).strip().lower()
        if key in catalogue:
            return catalogue[key]
        upper = str(indicator_id).strip().upper()
        if upper in catalogue.values():
            return upper
        raise BoEDatabaseError(
            f"unknown BoE series {indicator_id!r}: the built-in catalogue holds only "
            f"probe-verified series ({sorted(set(catalogue.values()))}); declare additional "
            "codes in the source's 'series' config rather than have the plugin guess"
        )

    def _request_html(self, code: str, start_date: datetime, end_date: datetime) -> str:
        params = {
            "csv.x": "yes",
            "Datefrom": start_date.strftime("%d/%b/%Y"),
            "Dateto": end_date.strftime("%d/%b/%Y"),
            "SeriesCodes": code,
            "CSVF": "CNF",
            "UsingCodes": "Y",
            "VPD": "Y",
            "VFD": "N",
        }
        timeout = float(self.config.get("timeout", 30))
        response = requests.get(
            BASE_URL, params=params, headers={"User-Agent": USER_AGENT}, timeout=timeout
        )
        if response.status_code != 200:
            raise BoEDatabaseError(
                f"BoE Interactive Database returned HTTP {response.status_code} for {code!r}"
            )
        if "ErrorPage.asp" in response.url:
            raise BoEDatabaseError(
                f"BoE Interactive Database rejected the query for {code!r} "
                "(ErrorPage redirect); the series code or DD/Mon/YYYY window was refused"
            )
        return response.text

    def _parse_table(self, html: str, code: str) -> pd.DataFrame:
        extractor = _TableExtractor()
        extractor.feed(html)

        data_rows: Optional[List[Tuple[List[str], bool]]] = None
        for rows in extractor.tables:
            headers = [cells for cells, is_header in rows if is_header]
            flat = " ".join(" ".join(cells) for cells in headers).lower()
            if "date" in flat and code.lower() in flat:
                data_rows = rows
                break
        if data_rows is None:
            raise BoEDatabaseError(
                f"no data table naming series {code!r} in the BoE response: the page "
                "structure changed or the series is not published; refusing to guess"
            )

        records: List[Tuple[pd.Timestamp, float]] = []
        for cells, is_header in data_rows:
            if is_header:
                continue
            if len(cells) < 2:
                raise BoEDatabaseError(
                    f"BoE data row has {len(cells)} cell(s), expected date+value: {cells!r}"
                )
            date = _parse_boe_date(cells[0])
            try:
                value = float(cells[1].replace(",", ""))
            except ValueError as exc:
                raise BoEDatabaseError(
                    f"non-numeric BoE value cell {cells[1]!r} on {cells[0]!r}: schema drift, "
                    "not missing data"
                ) from exc
            records.append((date, value))

        if not records:
            return pd.DataFrame(columns=["Date", "Value"])
        frame = pd.DataFrame(records, columns=["Date", "Value"])
        return frame.drop_duplicates(subset=["Date"]).sort_values("Date").reset_index(drop=True)

    def test_connection(self) -> Dict[str, Any]:
        code = SERIES_CATALOGUE["bank_rate"]
        end = datetime.now()
        start = datetime(end.year, end.month, end.day) - pd.Timedelta(days=90)
        try:
            html = self._request_html(code, start, end)
            frame = self._parse_table(html, code)
            return {
                "success": True,
                "message": (
                    f"Connected to the BoE Interactive Database; parsed {len(frame)} row(s) "
                    f"of {SERIES_LABELS.get(code, code)} from the last 90 days"
                ),
            }
        except BoEDatabaseError as exc:
            return {"success": False, "message": str(exc)}
        except requests.RequestException as exc:
            return {"success": False, "message": str(exc)}

    def fetch_indicator_data(
        self,
        indicator_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> Optional[pd.DataFrame]:
        code = self._resolve(indicator_id)
        html = self._request_html(code, start_date, end_date)
        frame = self._parse_table(html, code)
        if frame.empty:
            # An empty window is a fact (no observations published in range),
            # and the plugin contract reports it as None -- not as an error
            # and not as fabricated rows.
            return None
        frame = frame[
            (frame["Date"] >= pd.Timestamp(start_date)) & (frame["Date"] <= pd.Timestamp(end_date))
        ]
        if frame.empty:
            return None
        return frame

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
            "series": {
                "type": "dict",
                "required": False,
                "default": {},
                "label": "Additional series",
                "help": (
                    "alias -> BoE series code, for series an operator has verified in the "
                    "Interactive Database. The built-in catalogue holds only probe-verified "
                    "codes (Official Bank Rate, IUDBEDR); the plugin never guesses codes."
                ),
            },
            "timeout": {
                "type": "number",
                "required": False,
                "default": 30,
                "label": "Request timeout (seconds)",
            },
        }

    @classmethod
    def get_plugin_info(cls) -> Dict[str, Any]:
        return {
            "name": "Bank of England Interactive Database",
            "description": (
                "Official Bank Rate and operator-declared series from the BoE Interactive "
                "Database (keyless HTML-table interface; see docs/probes/boe_endpoint_probe.md)"
            ),
            "version": "1.0.0",
            "author": "BEACON",
            "free": True,
            "registration_required": False,
            "registration_url": None,
            "data_types": ["interest_rates", "official_statistics"],
            "flexible": False,
        }


register_plugin("boe_database", BoEDatabasePlugin)
