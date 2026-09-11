"""Fedwire and TARGET2: the throughput of the two systemic large-value rails.

Why this feed exists
--------------------
Fedwire Funds Service and TARGET2 settle the interbank leg of almost every
dollar and euro payment of consequence. Their volume and value are a
market-infrastructure risk signal: a rail that stops settling, or whose value
per transaction jumps because the composition of traffic moved to fewer, larger
payments, is telling you something about the plumbing of the financial system
that no price series contains.

This module implements three connectors over two independent publishers:

``FedwireConnector``
    BIS CPMI comparative statistics (dataflow ``WS_CPMI_SYSTEMS``), reporting
    country ``US``, system ``US2P``.
``Target2Connector``
    ECB "Payments and Settlement Systems Statistics" (dataflow ``PSS``),
    system ``P101``.
``PaymentsConnector``
    A facade that fetches both and returns one combined observation frame.

What was verified, and how
--------------------------
Every code and endpoint below was checked with ``curl`` against the live API on
2026-09-11 (User-Agent ``BNELabs-BEACON/1.0``); no code here is guessed.

* **Fedwire system code = ``US2P``.** Pulled from
  ``/data/WS_CPMI_SYSTEMS/A.US..A.US2P.....?format=csv`` (HTTP 200, 9,379 bytes,
  48 rows for 2013-2024). The BIS codelist ``CL_CPMI_SYSTEMS`` names it; the row
  titles read "Fedwire Funds Service". 2024 rows:
  ``N/PA = 209.9`` (millions of transactions, ``UNIT_MULT=6``) and
  ``V/PB = 1_133_419_684`` (millions of USD), i.e. 209.9m transfers worth
  $1.133 quadrillion -- the right order of magnitude for Fedwire.
* **``SYSTEM_TYPE = A``** means "Payment systems, large-value" (BIS codelist
  ``CL_CPMI_SYST_TYPE``, which was pulled and read).
* **``MEASURE``** is ``N`` = "Number" and ``V`` = "Value" (``CL_CPMI_MEASURE``).
* **``INSTRUMENT_TYPE``** is ``PA`` = "Transactions, all" and ``PB`` = "Credit
  transfers" (``CL_CPMI_INSTR_TYP``). Fedwire Funds publishes exactly these two,
  so we capture both: "all" is the headline, "credit transfers" is the
  instrument split the source actually separates.
* **``UNIT_MULT = 6``** = "Millions" (``CL_UNIT_MULT``) and
  **``UNIT_MEASURE = 373``** = "Pure Number", ``USD`` = "US dollar"
  (``CL_BIS_UNIT``). Both codelists were pulled and read.
* **BIS dimension order** for this dataflow, from
  ``/datastructure/BIS/all/latest`` (DSD ``BIS:CPMI_SYSTEMS``):
  ``FREQ.REP_CTY.MEASURE.SYSTEM_TYPE.SYSTEM.INSTRUMENT_TYPE.OTHER_PS_TRANS.TYPE_OF_INFO``.
* **TARGET2 system code = ``P101``.** The ECB codelist ``CL_PSS_SYSTEM``
  (``/service/codelist/ECB/CL_PSS_SYSTEM``) contains ``P101`` =
  "Payments processing system - large value - TARGET2/TARGET component". The
  codelist *also* contains ``P1T1`` / ``P1T2`` ("TARGET2 component 1/2"), but a
  data query for either returns HTTP 404 "No Series was returned" for
  2013-2024 -- they are codebook entries with no observations. ``P101`` returns
  data, so ``P101`` is the code this module uses.
* **ECB dimension order**, from ``/datastructure/ECB/ECB_PSS1``:
  ``FREQ.REF_AREA.PSS_INFO_TYPE.PSS_INSTRUMENT.PSS_SYSTEM.DATA_TYPE_PSS.COUNT_AREA.COUNT_SECTOR.CURRENCY_TRANS.SERIES_DENOM``.
* **ECB measure codes** ``NT`` = "Number" and ``VT`` = "Value"
  (``CL_DATA_TYPE_PSS``); ``F000`` = "All transactions" (``CL_PSS_INFO_TYPE``);
  ``I39`` = "Payment services (sent), direct debits and credit transfers"
  (``CL_PSS_INSTRUMENT``). For the euro-area TARGET component the series is
  ``A.U2.F000.I39.P101.{NT,VT}.X0.00.*``.
* **ECB data coverage ends in 2021 for ``P101``.** TARGET2 was superseded by T2
  in March 2023 and the ECB stops publishing this system's annual series after
  the 2021 reference year. Verified live: the key still resolves, but the
  response is HTTP 200 with a **zero-byte body** for a 2023-2024 window. The
  connector turns that into
  :class:`~backend.exceptions.EmptyDatasetError` -- "there is no data here",
  not "the schema changed" -- rather than papering over the absence. (An
  out-of-catalogue key such as ``P1T1`` behaves differently: HTTP 404, which the
  shared client reports as
  :class:`~backend.exceptions.DataSourceUnavailableError`.)

Series identifiers
------------------
``series_id`` is stable, self-describing, and prefixed by the publisher, so the
two rails can never be confused. Verified examples::

    BIS:CPMI:system=US2P:cty=US:measure=N:instrument=PA:unit=PURE_NUMB
    BIS:CPMI:system=US2P:cty=US:measure=V:instrument=PB:unit=USD
    ECB:PSS:system=P101:area=U2:info=F000:instr=I39:measure=NT:unit=PURE_NUMB
    ECB:PSS:system=P101:area=U2:info=F000:instr=I39:measure=VT:unit=EUR

The initialism differs on purpose -- ``BIS:CPMI:`` versus ``ECB:PSS:`` -- so
:meth:`PaymentsConnector.fetch` cannot produce a key collision. The ECB token
set omits ``COUNT_AREA``/``COUNT_SECTOR`` because this connector pins them to
``X0``/``00`` (all counterparties, no breakdown); the BIS token set carries the
reporting country because BIS keys its systems by country.

``entity_id``.
    The **payment system**, always: ``FEDWIRE`` and ``TARGET2``. The object
    under risk analysis is the rail, not the sovereign that reports it, and a
    stable name survives the euro area's changing composition. The reporting
    area is retained inside ``series_id`` (``cty=US``, ``area=U2``) for anyone
    who needs it. :attr:`ConnectorSpec.entity_id` on the facade lists both,
    pipe-separated, because the field is a single string.

``valid_time``.
    ``YYYY-12-31`` -- the **end** of the year the value describes. The sources
    publish annual totals ("value of transactions in 2024"), so the number is
    not complete until the year closes; stamping it at ``YYYY-01-01`` would let
    a model at any point inside 2024 read a full-year total, which is exactly
    the look-ahead this package exists to prevent. The end-of-year stamp also
    keeps the two-clock rule honest: the earliest a source can publish is after
    the year ends.

``observed_at`` -- two real clocks, one documented assumption
    * **Fedwire:** the BIS release calendar (dataflow ``BIS_REL_CAL``) carries
      the annual CPMI release as ``CATEGORY`` ``CPMI_FMI``/``CPMI_CT``,
      ``RELEASE_TYPE`` ``S`` = "Release" (``CL_REL_TYPE``), with ``OBS_VALUE`` a
      ``YYYYMMDD`` release date. Verified verbatim: reference year 2022 ->
      ``20240213``, 2023 -> ``20250325``, 2024 -> ``20260427`` (both CPMI
      categories share the same date). :meth:`FedwireConnector.fetch` reads that
      calendar and stamps ``observed_at`` with the real release date.
    * **TARGET2:** the ECB exposes **no** release-calendar dataflow in
      ``/service/dataflow``, but it does expose a per-observation dissemination
      timestamp: requesting ``includeHistory=true`` adds ``ACTION``,
      ``VALID_FROM`` and ``VALID_TO`` to the CSV, and ``VALID_FROM`` is the
      instant the current vintage was released (e.g. the 2021 euro-area TARGET
      value carries ``2023-09-15T10:00:01+02:00``). That is a real publication
      timestamp, so ``Target2Connector`` uses it and needs no assumption in the
      normal path.
    * **Fallbacks.** The BIS calendar retains only recent years (2022-2024 in
      the extract verified), and a future ECB API change could drop
      ``VALID_FROM``. Where a real date is unavailable each connector falls back
      to ``valid_time + FALLBACK_PUBLICATION_LAG``, an **explicitly assumption**
      -laden, overridable class attribute. The fallbacks deliberately err *late*
      (a later ``observed_at`` can only understate availability, never leak a
      value that was not yet known). The current wall clock is never consulted.
    * Every row is checked against ``observed_at >= valid_time``; a violation
      raises rather than being clamped.

Units and ``value``
    Both publishers report in **millions** (``UNIT_MULT = 6``). This module
    applies the multiplier once, at parse time, so ``value`` is always an
    absolute count (transactions) or an absolute currency amount (USD for
    Fedwire, EUR for TARGET2) and is directly comparable across the two rails.
    The unit is recorded in ``series_id`` (``unit=PURE_NUMB`` / ``unit=USD`` /
    ``unit=EUR``); ``UNIT_MULT`` is *not* a token, because the stored value no
    longer carries it.

``revision``
    Fedwire: always ``0``. The BIS CSV carries only the current vintage, its
    revision column is ``OBS_PRE_BREAK`` (a series break, not a vintage), and
    the release calendar records one release per reference year -- the source
    does not distinguish revisions we can see, and inventing a numbering would
    be a lie. TARGET2: ranks ``observed_at`` within each series/period, so a
    genuine restatement that arrives as a second value-carrying vintage gets
    ``revision = 1``. In the extracts verified the ECB returned superseded
    vintages only as ``ACTION=Delete`` tombstones with no value, so in practice
    this is ``0`` as well.

Missing values
    A blank ``OBS_VALUE`` is expected and is **skipped, never zeroed**; the
    count of skipped rows by reason is recorded on the connector instance in
    :attr:`last_skipped` (and logged) so a caller can see how much was dropped.
    Rows that were kept but had to borrow a publication date are counted
    separately in :attr:`last_assumptions`, because nothing about them was
    dropped -- only their vintage stamp is inferred.
    Non-blank placeholders (``..``, ``-``, ``c``) go through
    :func:`~backend.modules.data.connectors.base.as_float` and raise, because
    the sources verified here write blanks rather than placeholders and a
    placeholder would signal a schema change worth failing on. If no row
    survives, :class:`~backend.exceptions.EmptyDatasetError` is raised.

Fail-closed behaviour
    An unreachable source, an HTTP error, a missing column, a violated identity
    column (wrong country/system), a duplicate observation carrying conflicting
    values, or an empty result all raise a typed error. Nothing is interpolated,
    forward-filled or back-filled.

    :class:`PaymentsConnector` **fails the whole call** when either source
    fails. It does not return partial data. A frame that quietly omitted
    TARGET2 would be indistinguishable downstream from "TARGET2 settled
    nothing", and there is nowhere in the observation schema to record "this
    half is missing" -- so the combined call is all-or-nothing, and the
    originating typed error (and which source raised it) reaches the caller.

``FetchRequest`` scope
    ``start``/``end`` bound ``valid_time`` and are pushed to the source as
    ``startPeriod``/``endPeriod``, widened to whole years so a mid-year bound
    never silently drops the year it lands in. ``entity_ids`` and
    ``series_ids`` are applied **after** parsing, never sent: neither publisher
    accepts them as keys, so filtering server-side would be a different query
    rather than the same one narrowed. On :class:`PaymentsConnector` a scope is
    also used to decide *which* sources to contact -- asking for one TARGET2
    series must not fail because Fedwire has nothing to return for it.

Not implemented
    * ECB ``TGB`` ("Target Balances") is a real dataflow -- its data structure
      ``ECB_TGB1`` resolves with HTTP 200 -- but it measures central bank
      *claims and liabilities within TARGET*, not payment-system throughput, and
      a clean data query was not verified here. It is noted as a complement and
      deliberately **not** implemented.
    * ECB ``P1T1``/``P1T2`` ("TARGET2 component 1/2") were left out: the
      codebook defines them, the data API returns no series for them.
    * The ECB's ``COUNT_SECTOR`` breakdown of TARGET traffic (same component vs
      another component) is published and was observed, but its codelist was not
      pulled, so this module captures only the all-counterparty total rather
      than assert semantics it did not verify.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

from backend.exceptions import (
    DataIngestionError,
    EmptyDatasetError,
    SchemaValidationError,
)
from .base import (
    ConnectorSpec,
    DataConnector,
    FetchRequest,
    HttpClient,
    as_float,
    require,
    validate_observation_frame,
)
from ..pit import OBSERVATION_COLUMNS

logger = logging.getLogger(__name__)

__all__ = [
    "BIS_CPMI_ENDPOINT",
    "BIS_RELEASE_CALENDAR_ENDPOINT",
    "ECB_PSS_ENDPOINT",
    "FEDWIRE_ENTITY_ID",
    "FEDWIRE_SYSTEM_CODE",
    "TARGET2_ENTITY_ID",
    "TARGET2_SYSTEM_CODE",
    "FedwireConnector",
    "Target2Connector",
    "PaymentsConnector",
    "bis_series_id",
    "ecb_series_id",
    "parse_bis_release_calendar",
]

# --------------------------------------------------------------------------
# Endpoints. Each was exercised with curl; see the module docstring.
# --------------------------------------------------------------------------

#: BIS CPMI comparative tables. Key order:
#: FREQ.REP_CTY.MEASURE.SYSTEM_TYPE.SYSTEM.INSTRUMENT_TYPE.OTHER_PS_TRANS.TYPE_OF_INFO
BIS_CPMI_ENDPOINT = "https://stats.bis.org/api/v1/data/WS_CPMI_SYSTEMS"

#: BIS release calendar: one ``RELEASE_TYPE=S`` row per annual CPMI release.
BIS_RELEASE_CALENDAR_ENDPOINT = "https://stats.bis.org/api/v1/data/BIS_REL_CAL"

#: ECB Payments and Settlement Systems Statistics. Key order:
#: FREQ.REF_AREA.PSS_INFO_TYPE.PSS_INSTRUMENT.PSS_SYSTEM.DATA_TYPE_PSS
#: .COUNT_AREA.COUNT_SECTOR.CURRENCY_TRANS.SERIES_DENOM
ECB_PSS_ENDPOINT = "https://data-api.ecb.europa.eu/service/data/PSS"

FEDWIRE_ENTITY_ID = "FEDWIRE"
TARGET2_ENTITY_ID = "TARGET2"

#: Verified against the BIS codelist ``CL_CPMI_SYSTEMS`` and live rows whose
#: titles read "Fedwire Funds Service".
FEDWIRE_REP_CTY = "US"
FEDWIRE_SYSTEM_CODE = "US2P"

#: Verified against the ECB codelist ``CL_PSS_SYSTEM``. ``P1T1``/``P1T2`` exist in
#: that codelist but return HTTP 404 for every period tried, so they are not used.
TARGET2_SYSTEM_CODE = "P101"
TARGET2_REF_AREA = "U2"

#: SDMX annual frequency, shared by both publishers (BIS ``CL_FREQ`` and the ECB
#: ``CL_FREQ`` both use ``A``), and pinned in every URL this module builds.
_ANNUAL_FREQUENCY = "A"

# BIS codes, each read from a BIS codelist (see the module docstring).
_CPMI_SYSTEM_TYPE_LARGE_VALUE = "A"
_CPMI_MEASURE_NUMBER = "N"
_CPMI_MEASURE_VALUE = "V"
_CPMI_INSTRUMENT_ALL = "PA"
_CPMI_INSTRUMENT_CREDIT_TRANSFERS = "PB"
_CPMI_TYPE_OF_INFO_OBSERVATION = "Z"
_CPMI_OTHER_PS_TRANS_NONE = "ZZZZ"
#: BIS ``UNIT_MEASURE`` codes we can name; anything else is carried verbatim.
_CPMI_UNIT_LABELS = {"373": "PURE_NUMB"}

# ECB codes, each read from an ECB codelist.
_ECB_INFO_TYPE_ALL_TRANSACTIONS = "F000"
_ECB_INSTRUMENT_CREDIT_TRANSFERS_AND_DIRECT_DEBITS = "I39"
_ECB_COUNT_AREA_ALL = "X0"
_ECB_COUNT_SECTOR_TOTAL = "00"
_ECB_MEASURE_NUMBER = "NT"
_ECB_MEASURE_VALUE = "VT"
_ECB_ACTION_DELETE = "Delete"

_ECB_UNIT_NUMBER = "PURE_NUMB"
_ECB_UNIT_VALUE = "EUR"

_YEAR_RE = re.compile(r"^\d{4}$")

_REQUIRED_COLUMNS: Mapping[str, Tuple[str, ...]] = {
    "bis": (
        "FREQ",
        "REP_CTY",
        "MEASURE",
        "SYSTEM_TYPE",
        "SYSTEM",
        "INSTRUMENT_TYPE",
        "OTHER_PS_TRANS",
        "TYPE_OF_INFO",
        "TIME_PERIOD",
        "OBS_VALUE",
        "UNIT_MULT",
        "UNIT_MEASURE",
    ),
    "ecb": (
        "FREQ",
        "REF_AREA",
        "PSS_INFO_TYPE",
        "PSS_INSTRUMENT",
        "PSS_SYSTEM",
        "DATA_TYPE_PSS",
        "COUNT_AREA",
        "COUNT_SECTOR",
        "TIME_PERIOD",
        "OBS_VALUE",
        "UNIT",
        "UNIT_MULT",
    ),
    "bis_release_calendar": (
        "FREQ",
        "CATEGORY",
        "RELEASE_TYPE",
        "TIME_PERIOD",
        "OBS_VALUE",
    ),
}


# --------------------------------------------------------------------------
# Series identifiers
# --------------------------------------------------------------------------


def bis_series_id(
    system_code: str,
    country: str,
    measure: str,
    instrument: str,
    unit: str,
) -> str:
    """Stable BIS CPMI series key, e.g. ``BIS:CPMI:system=US2P:cty=US:...``."""
    return (
        f"BIS:CPMI:system={system_code}:cty={country}:measure={measure}"
        f":instrument={instrument}:unit={unit}"
    )


def ecb_series_id(
    system_code: str,
    area: str,
    info_type: str,
    instrument: str,
    measure: str,
    unit: str,
) -> str:
    """Stable ECB PSS series key, e.g. ``ECB:PSS:system=P101:area=U2:...``."""
    return (
        f"ECB:PSS:system={system_code}:area={area}:info={info_type}"
        f":instr={instrument}:measure={measure}:unit={unit}"
    )


# --------------------------------------------------------------------------
# CSV plumbing
# --------------------------------------------------------------------------


def _decode(payload: Any, connector: str) -> str:
    """Decode a CSV body, tolerating a byte-order mark.

    ``latin-1`` is the last resort because it cannot fail: an undecodable byte
    must not abort ingestion of a file that is otherwise well formed, and every
    value we actually read is ASCII.
    """
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, (bytes, bytearray)):
        raise SchemaValidationError(
            f"{connector}: expected a CSV body, got {type(payload).__name__}",
            context={"connector": connector},
        )
    raw = bytes(payload)
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    # ``latin-1`` above decodes anything, so this is unreachable.
    raise SchemaValidationError(
        f"{connector}: CSV body could not be decoded", context={"connector": connector}
    )


def _text(row: Mapping[str, Any], column: str) -> str:
    """A trimmed string for ``column``, treating absent and ``None`` alike."""
    value = row.get(column)
    return "" if value is None else str(value).strip()


def _csv_rows(
    payload: Any, required: Sequence[str], connector: str
) -> List[Dict[str, str]]:
    """Parse ``payload`` into row dicts, failing closed on a missing column.

    An empty body is reported as :class:`EmptyDatasetError`, not as a schema
    error. That distinction is not academic: the ECB answers HTTP 200 with a
    zero-byte body for a valid series key in a period it has no data for (for
    example the TARGET2 key after the 2021 reference year), and calling that a
    malformed schema would send an operator hunting for a format change that
    never happened.
    """
    text = _decode(payload, connector)
    if text.strip() == "":
        raise EmptyDatasetError(
            f"{connector}: the source returned an empty body for this scope",
            context={"connector": connector},
        )
    try:
        reader: Any = csv.DictReader(io.StringIO(text))
        fieldnames = list(reader.fieldnames or [])
        rows = [dict(row) for row in reader]
    except csv.Error as exc:
        raise SchemaValidationError(
            f"{connector}: CSV body is malformed",
            context={"connector": connector, "error": str(exc)},
        ) from exc

    missing = [column for column in required if column not in fieldnames]
    require(
        not missing,
        f"{connector}: CSV is missing required columns",
        connector=connector,
        missing=missing,
        present=fieldnames,
    )
    return rows


def _unit_multiplier(value: Any, connector: str) -> int:
    """Parse ``UNIT_MULT``, the power of ten the source scaled its values by."""
    text = "" if value is None else str(value).strip()
    require(
        text != "",
        f"{connector}: UNIT_MULT is empty",
        connector=connector,
    )
    try:
        return int(text)
    except ValueError as exc:
        raise SchemaValidationError(
            f"{connector}: UNIT_MULT is not an integer",
            context={"connector": connector, "value": text},
        ) from exc


def _annual_valid_time(value: Any, connector: str) -> pd.Timestamp:
    """Map an annual ``TIME_PERIOD`` to the instant the period *ends*."""
    text = "" if value is None else str(value).strip()
    require(
        bool(_YEAR_RE.match(text)),
        f"{connector}: TIME_PERIOD is not an annual year",
        connector=connector,
        value=text,
    )
    return pd.Timestamp(year=int(text), month=12, day=31)


def _naive_utc(value: Any, connector: str, field_name: str) -> pd.Timestamp:
    """Parse a source timestamp and normalise it the way ``PITStore`` does."""
    text = "" if value is None else str(value).strip()
    try:
        stamp = pd.Timestamp(text)
    except (TypeError, ValueError) as exc:
        raise SchemaValidationError(
            f"{connector}: {field_name} is not a timestamp",
            context={"connector": connector, "value": text},
        ) from exc
    if pd.isna(stamp):
        raise SchemaValidationError(
            f"{connector}: {field_name} is NaT",
            context={"connector": connector, "value": text},
        )
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("UTC").tz_localize(None)
    return stamp


def _period_params(request: FetchRequest) -> List[Tuple[str, str]]:
    """``startPeriod``/``endPeriod`` bounds for an inclusive ``valid_time`` window.

    Bounds are widened to whole years on purpose: ``valid_time`` is 31 December,
    so a request ending 2024-06-01 must still *fetch* 2024 and let the parser
    drop the row. Narrowing here would silently lose a row the caller asked for.
    """
    params: List[Tuple[str, str]] = []
    if request.start is not None:
        params.append(("startPeriod", str(pd.Timestamp(request.start).year)))
    if request.end is not None:
        params.append(("endPeriod", str(pd.Timestamp(request.end).year)))
    return params


def _query_string(params: Sequence[Tuple[str, str]]) -> str:
    return "&".join(f"{name}={value}" for name, value in params)


# --------------------------------------------------------------------------
# Shared connector behaviour
# --------------------------------------------------------------------------


class _PaymentsBase(DataConnector):
    """Common parse-time bookkeeping for the two payment-system connectors.

    Both sources publish blank values that must be *skipped*, not zeroed, and
    both need a window filter and the same duplicate/conflict check. Those live
    here so the two parsers differ only where the sources differ.
    """

    accept = "text/csv"

    def __init__(self, client: Optional[HttpClient] = None) -> None:
        super().__init__(client)
        #: Rows dropped by the most recent :meth:`parse`, keyed by reason.
        self.last_skipped: Dict[str, int] = {}
        #: Rows kept but stamped with an assumed date, keyed by reason. Kept
        #: apart from ``last_skipped`` because nothing was skipped: the values
        #: are real, only the vintage stamp is inferred.
        self.last_assumptions: Dict[str, int] = {}
        #: Rows that survived every filter in the most recent :meth:`parse`.
        self.last_kept: int = 0

    def _reset_counters(self) -> None:
        self.last_skipped = {}
        self.last_assumptions = {}
        self.last_kept = 0

    def _skip(self, reason: str, count: int = 1) -> None:
        self.last_skipped[reason] = self.last_skipped.get(reason, 0) + count

    def _assume(self, reason: str, count: int = 1) -> None:
        self.last_assumptions[reason] = self.last_assumptions.get(reason, 0) + count

    @property
    def skipped_total(self) -> int:
        """How many rows the most recent :meth:`parse` discarded."""
        return sum(self.last_skipped.values())

    def _record(
        self,
        records: List[Dict[str, Any]],
        request: FetchRequest,
        connector: str,
    ) -> pd.DataFrame:
        """Filter to the requested window, assemble, and fail closed.

        This is deliberately the last thing :meth:`parse` does, so every
        failure mode below aborts the whole parse rather than yielding a
        quietly smaller frame.
        """
        kept: List[Dict[str, Any]] = []
        entity_filter = set(request.entity_ids)
        series_filter = set(request.series_ids)
        for record in records:
            # ``FetchRequest`` scope is honoured here rather than sent to the
            # source: neither BIS nor the ECB takes these keys, so filtering
            # server-side would be a different query, not the same one narrowed.
            if entity_filter and record["entity_id"] not in entity_filter:
                self._skip("out_of_scope_entity")
                continue
            if series_filter and record["series_id"] not in series_filter:
                self._skip("out_of_scope_series")
                continue
            if not request.covers(record["valid_time"]):
                self._skip("out_of_window")
                continue
            if record["observed_at"] < record["valid_time"]:
                raise SchemaValidationError(
                    f"{connector}: observation is stamped before the period ends",
                    context={
                        "connector": connector,
                        "series_id": record["series_id"],
                        "valid_time": str(record["valid_time"]),
                        "observed_at": str(record["observed_at"]),
                    },
                )
            kept.append(record)

        self.last_kept = len(kept)
        if not kept:
            raise EmptyDatasetError(
                f"{connector} returned no usable observations",
                context={
                    "connector": connector,
                    "skipped": dict(self.last_skipped),
                },
            )

        frame = pd.DataFrame.from_records(kept, columns=list(OBSERVATION_COLUMNS))
        frame["valid_time"] = pd.to_datetime(frame["valid_time"])
        frame["observed_at"] = pd.to_datetime(frame["observed_at"])
        frame["value"] = pd.to_numeric(frame["value"], errors="coerce").astype(
            "float64"
        )
        frame["revision"] = pd.to_numeric(frame["revision"], errors="coerce").astype(
            "int64"
        )

        conflicts = frame.groupby(
            ["series_id", "valid_time", "observed_at"]
        )["value"].nunique()
        conflicting = conflicts[conflicts > 1]
        require(
            conflicting.empty,
            f"{connector}: duplicate series keys carry conflicting values",
            connector=connector,
            keys=[str(key) for key in conflicting.index[:5]],
        )
        if self.last_skipped:
            logger.info(
                "%s: skipped %d source row(s): %s",
                connector,
                self.skipped_total,
                ", ".join(
                    f"{reason}={count}"
                    for reason, count in sorted(self.last_skipped.items())
                ),
            )
        return frame.sort_values(
            ["valid_time", "series_id", "entity_id"], kind="stable"
        ).reset_index(drop=True)


# --------------------------------------------------------------------------
# Fedwire / BIS CPMI
# --------------------------------------------------------------------------


class FedwireConnector(_PaymentsBase):
    """Fedwire Funds Service number and value of transactions, from BIS CPMI.

    Captures four series per year -- ``measure`` in ``{N, V}`` crossed with
    ``instrument`` in ``{PA (all transactions), PB (credit transfers)}`` -- for
    reporting country ``US`` and system ``US2P``.

    ``observed_at`` is the real BIS release date, read from the ``BIS_REL_CAL``
    release calendar; where the calendar has no row for a reference year (it
    retains only recent years) the documented
    :attr:`FALLBACK_PUBLICATION_LAG` is used instead. A calendar that cannot be
    reached degrades to the same fallback and is logged, because the calendar is
    auxiliary to the measurement: losing it changes ``observed_at``, losing the
    data does not happen.
    """

    #: Assumption, not a fact: used only when the BIS calendar has no release
    #: date for a reference year. The verified releases run ~1 year 2-4 months
    #: after the reference year ends (2024 -> 2026-04-27), so 1y6m errs late.
    FALLBACK_PUBLICATION_LAG = pd.DateOffset(years=1, months=6)

    #: Calendar categories covering the CPMI payments/FMI statistics. Both were
    #: verified to carry identical release dates.
    RELEASE_CATEGORIES: Tuple[str, ...] = ("CPMI_FMI", "CPMI_CT")
    #: ``CL_REL_TYPE``: ``S`` = "Release". Revisions are not first prints.
    RELEASE_TYPE_FIRST_PRINT = "S"

    def __init__(self, client: Optional[HttpClient] = None) -> None:
        super().__init__(client)
        #: Reference year -> BIS release timestamp, populated by :meth:`fetch`.
        self.release_dates: Dict[int, pd.Timestamp] = {}

    @property
    def spec(self) -> ConnectorSpec:
        return ConnectorSpec(
            name="bis_fedwire",
            kind="bis",
            entity_id=FEDWIRE_ENTITY_ID,
            source_url="https://www.bis.org/statistics/payment_stats.htm",
            endpoint=BIS_CPMI_ENDPOINT,
            licence=(
                "BIS statistics: use is unrestricted provided the BIS is cited as "
                "the source, any translation is flagged as unofficial, the use is "
                "not misleading, and inclusion in a commercial product adds no "
                "charge to subscribers; the BIS gives no warranty and the data are "
                "not investment advice. Quoted from 'Terms of permitted use of BIS "
                "statistics' (https://www.bis.org/terms_statistics.htm). That page "
                "returned HTTP 403 to this client, so the terms were read from the "
                "BIS Data Portal mirror (https://data.bis.org/help/legal)."
            ),
            cadence="annual",
            description=(
                "Number and value of Fedwire Funds Service transactions (system "
                "US2P) from the BIS CPMI comparative tables."
            ),
        )

    # -- URLs ------------------------------------------------------------

    def build_url(self, request: FetchRequest) -> str:
        """Keyed BIS CPMI URL: country ``US``, system type ``A``, system ``US2P``.

        Pinning the key server-side matters: the unfiltered ``/all`` variant of
        this dataflow is 551 KB for a single year, while this key is 9.4 KB for
        twelve years. ``MEASURE`` and ``INSTRUMENT_TYPE`` are left wildcarded
        because the connector wants both of each, and filtered in the parser.
        """
        key = (
            f"{_ANNUAL_FREQUENCY}.{FEDWIRE_REP_CTY}.."
            f"{_CPMI_SYSTEM_TYPE_LARGE_VALUE}.{FEDWIRE_SYSTEM_CODE}....."
        )
        params: List[Tuple[str, str]] = [("format", "csv")]
        params.extend(_period_params(request))
        return f"{BIS_CPMI_ENDPOINT}/{key}?{_query_string(params)}"

    def build_release_calendar_url(self, request: FetchRequest) -> str:
        """Release-calendar URL for the same reference-year window."""
        params: List[Tuple[str, str]] = [("format", "csv")]
        params.extend(_period_params(request))
        return f"{BIS_RELEASE_CALENDAR_ENDPOINT}/all?{_query_string(params)}"

    # -- I/O -------------------------------------------------------------

    def fetch(self, request: Optional[FetchRequest] = None) -> pd.DataFrame:
        """Resolve release dates, then fetch and parse like any connector.

        The extra request is the release calendar. It is attempted first so the
        parser never has to guess, and a failure there is logged and degraded
        rather than raised -- see the class docstring.
        """
        resolved = request or FetchRequest()
        self.release_dates = self._load_release_dates(resolved)
        return super().fetch(resolved)

    def _load_release_dates(self, request: FetchRequest) -> Dict[int, pd.Timestamp]:
        """Best-effort release calendar; returns ``{}`` when it is unusable."""
        url = self.build_release_calendar_url(request)
        name = self.spec.name
        try:
            payload = self._client.get(
                url, accept=self.accept, connector=f"{name}_release_calendar"
            )
            return parse_bis_release_calendar(payload, connector=name)
        except DataIngestionError as exc:
            logger.warning(
                "%s: BIS release calendar unusable (%s: %s); using the documented "
                "publication lag %s for every year it does not cover",
                name,
                type(exc).__name__,
                exc,
                self.FALLBACK_PUBLICATION_LAG,
            )
            return {}

    def _observed_at(self, valid_time: pd.Timestamp) -> pd.Timestamp:
        """Release date for the reference year, or the documented fallback."""
        release = self.release_dates.get(valid_time.year)
        if release is not None:
            return release
        return valid_time + self.FALLBACK_PUBLICATION_LAG

    # -- Parsing (no I/O) ------------------------------------------------

    def parse(self, payload: Any, request: FetchRequest) -> pd.DataFrame:
        """Parse a recorded BIS CPMI CSV body. Performs no network I/O."""
        name = self.spec.name
        self._reset_counters()
        rows = _csv_rows(payload, _REQUIRED_COLUMNS["bis"], name)
        records: List[Dict[str, Any]] = []

        for row in rows:
            # Identity columns: the key pins them, so a mismatch means the
            # request did not mean what we think it meant. Fail closed.
            require(
                _text(row, "FREQ") == _ANNUAL_FREQUENCY,
                f"{name}: FREQ is not annual",
                value=_text(row, "FREQ"),
            )
            require(
                _text(row, "REP_CTY") == FEDWIRE_REP_CTY,
                f"{name}: reporting country is not {FEDWIRE_REP_CTY}",
                value=_text(row, "REP_CTY"),
            )
            require(
                _text(row, "SYSTEM") == FEDWIRE_SYSTEM_CODE,
                f"{name}: system is not {FEDWIRE_SYSTEM_CODE}",
                value=_text(row, "SYSTEM"),
            )

            # Selection columns: additive changes in the source are dropped and
            # counted, not fatal, because a new instrument is not a schema break.
            if _text(row, "SYSTEM_TYPE") != _CPMI_SYSTEM_TYPE_LARGE_VALUE:
                self._skip("not_large_value_system")
                continue
            if _text(row, "TYPE_OF_INFO") != _CPMI_TYPE_OF_INFO_OBSERVATION:
                # "C" is a concentration ratio, not a volume.
                self._skip("not_an_observation")
                continue
            if _text(row, "OTHER_PS_TRANS") != _CPMI_OTHER_PS_TRANS_NONE:
                self._skip("breakdown_row")
                continue
            measure = _text(row, "MEASURE")
            if measure not in (_CPMI_MEASURE_NUMBER, _CPMI_MEASURE_VALUE):
                self._skip("unsupported_measure")
                continue
            instrument = _text(row, "INSTRUMENT_TYPE")
            if instrument not in (
                _CPMI_INSTRUMENT_ALL,
                _CPMI_INSTRUMENT_CREDIT_TRANSFERS,
            ):
                self._skip("unsupported_instrument")
                continue

            valid_time = _annual_valid_time(row.get("TIME_PERIOD"), name)
            raw_value = _text(row, "OBS_VALUE")
            if raw_value == "":
                # Expected: the BIS extract verified here happened to be
                # complete, but a blank is "not published", never zero.
                self._skip("empty_value")
                continue
            value = as_float(raw_value, field_name="OBS_VALUE", connector=name)
            value *= 10 ** _unit_multiplier(row.get("UNIT_MULT"), name)

            unit_code = _text(row, "UNIT_MEASURE")
            require(
                unit_code != "",
                f"{name}: UNIT_MEASURE is empty, so the series unit is unknown",
                value=unit_code,
            )
            unit = _CPMI_UNIT_LABELS.get(unit_code, unit_code)
            records.append(
                {
                    "entity_id": FEDWIRE_ENTITY_ID,
                    "series_id": bis_series_id(
                        FEDWIRE_SYSTEM_CODE,
                        FEDWIRE_REP_CTY,
                        measure,
                        instrument,
                        unit,
                    ),
                    "valid_time": valid_time,
                    "observed_at": self._observed_at(valid_time),
                    "value": value,
                    # The BIS CSV carries one vintage per year; a revision
                    # number would be invented. See the module docstring.
                    "revision": 0,
                }
            )

        return self._record(records, request, name)


def parse_bis_release_calendar(
    payload: Any, *, connector: str = "bis_fedwire"
) -> Dict[int, pd.Timestamp]:
    """Reference year -> CPMI release date, from a ``BIS_REL_CAL`` CSV body.

    Returns one date per reference year: the latest ``RELEASE_TYPE=S`` row for
    the CPMI categories, so a year with several calendar rows gets the final
    release. Empty when the calendar covers none of the years asked about --
    the caller falls back to a documented lag rather than inventing a date.
    """
    rows = _csv_rows(payload, _REQUIRED_COLUMNS["bis_release_calendar"], connector)
    dates: Dict[int, pd.Timestamp] = {}
    for row in rows:
        if _text(row, "FREQ") != "A":
            continue
        if _text(row, "CATEGORY") not in ("CPMI_FMI", "CPMI_CT"):
            continue
        if _text(row, "RELEASE_TYPE") != "S":
            continue
        year_text = _text(row, "TIME_PERIOD")
        if not _YEAR_RE.match(year_text):
            continue
        raw = _text(row, "OBS_VALUE")
        if raw == "":
            continue
        released = _naive_utc(raw, connector, "OBS_VALUE")
        year = int(year_text)
        previous = dates.get(year)
        dates[year] = released if previous is None else max(previous, released)
    return dates


# --------------------------------------------------------------------------
# TARGET2 / ECB PSS
# --------------------------------------------------------------------------


class Target2Connector(_PaymentsBase):
    """TARGET2 number and value of transactions, from the ECB PSS dataflow.

    Captures two series per year for the euro-area TARGET component
    (``REF_AREA=U2``, ``PSS_SYSTEM=P101``, ``PSS_INFO_TYPE=F000``,
    ``PSS_INSTRUMENT=I39``): ``DATA_TYPE_PSS=NT`` (number) and ``VT`` (value).

    TARGET2 is a large-value system by construction, so the source publishes no
    retail/large-value split for it; what it publishes is the instrument
    aggregate ``I39`` (credit transfers plus direct debits) which this connector
    takes whole. The ECB's ``COUNT_SECTOR`` breakdown is deliberately not
    captured -- see the module docstring.

    ``observed_at`` is the ECB's own dissemination timestamp. Requesting
    ``includeHistory=true`` adds ``VALID_FROM`` to the CSV; that is when the
    current vintage of the observation was released, and it is verified to be
    later than the reference year for the series captured here. When the column
    is absent the documented :attr:`FALLBACK_PUBLICATION_LAG` is used.
    """

    #: Assumption, not a fact: only used when the CSV has no ``VALID_FROM``.
    #: The verified dissemination stamps run ~1.7-2 years after the reference
    #: year ends, so 2 years errs slightly late.
    FALLBACK_PUBLICATION_LAG = pd.DateOffset(years=2)

    @property
    def spec(self) -> ConnectorSpec:
        return ConnectorSpec(
            name="ecb_target2",
            kind="ecb",
            entity_id=TARGET2_ENTITY_ID,
            source_url="https://data.ecb.europa.eu/data/datasets/PSS",
            endpoint=ECB_PSS_ENDPOINT,
            licence=(
                "ECB statistics: information obtained from the ECB website may be "
                "distributed or reproduced provided it appears accurately and the "
                "ECB is cited as the source; a product that is sold must tell "
                "buyers the information is available free of charge from the ECB, "
                "and any modification (for example seasonal adjustment or growth "
                "rates) must be stated explicitly. Quoted from the ECB "
                "'Disclaimer & Copyright' page "
                "(https://www.ecb.europa.eu/services/disclaimer/html/index.en.html)."
            ),
            cadence="annual",
            description=(
                "Number and value of credit transfers and direct debits settled in "
                "TARGET2 (ECB PSS system P101, euro area)."
            ),
        )

    # -- URLs ------------------------------------------------------------

    def build_url(self, request: FetchRequest) -> str:
        """Keyed ECB PSS URL for both measures, with vintage metadata.

        ``includeHistory=true`` is what yields the per-observation release
        timestamp; without it the ECB returns no date at all and ``observed_at``
        would have to fall back to an assumption. The key pins
        ``REF_AREA=U2`` / ``PSS_SYSTEM=P101`` / ``COUNT_AREA=X0`` /
        ``COUNT_SECTOR=00`` and leaves the measure wildcarded, so one small
        response (about 23 KB for 2000-2021) carries both ``NT`` and ``VT``.
        """
        key = (
            f"{_ANNUAL_FREQUENCY}.{TARGET2_REF_AREA}"
            f".{_ECB_INFO_TYPE_ALL_TRANSACTIONS}"
            f".{_ECB_INSTRUMENT_CREDIT_TRANSFERS_AND_DIRECT_DEBITS}"
            f".{TARGET2_SYSTEM_CODE}..{_ECB_COUNT_AREA_ALL}.{_ECB_COUNT_SECTOR_TOTAL}.."
        )
        params: List[Tuple[str, str]] = [
            ("format", "csvdata"),
            ("includeHistory", "true"),
        ]
        params.extend(_period_params(request))
        return f"{ECB_PSS_ENDPOINT}/{key}?{_query_string(params)}"

    # -- Parsing (no I/O) ------------------------------------------------

    def _observed_at(
        self, row: Mapping[str, Any], valid_time: pd.Timestamp, name: str
    ) -> Tuple[pd.Timestamp, bool]:
        """``(observed_at, was_real)`` for one ECB row.

        Returns the ECB dissemination timestamp when present, otherwise the
        documented lag. The boolean lets the caller count how many rows relied
        on the assumption.
        """
        raw = _text(row, "VALID_FROM")
        if raw != "":
            return _naive_utc(raw, name, "VALID_FROM"), True
        return valid_time + self.FALLBACK_PUBLICATION_LAG, False

    def parse(self, payload: Any, request: FetchRequest) -> pd.DataFrame:
        """Parse a recorded ECB PSS CSV body. Performs no network I/O."""
        name = self.spec.name
        self._reset_counters()
        rows = _csv_rows(payload, _REQUIRED_COLUMNS["ecb"], name)
        records: List[Dict[str, Any]] = []
        assumed = 0

        for row in rows:
            require(
                _text(row, "FREQ") == _ANNUAL_FREQUENCY,
                f"{name}: FREQ is not annual",
                value=_text(row, "FREQ"),
            )
            require(
                _text(row, "REF_AREA") == TARGET2_REF_AREA,
                f"{name}: REF_AREA is not {TARGET2_REF_AREA}",
                value=_text(row, "REF_AREA"),
            )
            require(
                _text(row, "PSS_INFO_TYPE") == _ECB_INFO_TYPE_ALL_TRANSACTIONS,
                f"{name}: PSS_INFO_TYPE is not {_ECB_INFO_TYPE_ALL_TRANSACTIONS}",
                value=_text(row, "PSS_INFO_TYPE"),
            )
            require(
                _text(row, "PSS_SYSTEM") == TARGET2_SYSTEM_CODE,
                f"{name}: PSS_SYSTEM is not {TARGET2_SYSTEM_CODE}",
                value=_text(row, "PSS_SYSTEM"),
            )

            instrument = _text(row, "PSS_INSTRUMENT")
            if instrument != _ECB_INSTRUMENT_CREDIT_TRANSFERS_AND_DIRECT_DEBITS:
                self._skip("unsupported_instrument")
                continue
            measure = _text(row, "DATA_TYPE_PSS")
            if measure not in (_ECB_MEASURE_NUMBER, _ECB_MEASURE_VALUE):
                self._skip("unsupported_measure")
                continue
            # Pinned by the key; filtered anyway so an override of build_url
            # cannot smuggle a breakdown into a series that claims to be total.
            if (
                _text(row, "COUNT_AREA") != _ECB_COUNT_AREA_ALL
                or _text(row, "COUNT_SECTOR") != _ECB_COUNT_SECTOR_TOTAL
            ):
                self._skip("unsupported_breakdown")
                continue

            valid_time = _annual_valid_time(row.get("TIME_PERIOD"), name)

            raw_value = _text(row, "OBS_VALUE")
            if raw_value == "":
                # Superseded ECB vintages arrive as ACTION=Delete tombstones
                # with a blank value; a blank is never zero.
                self._skip("empty_value")
                continue
            if _text(row, "ACTION") == _ECB_ACTION_DELETE:
                # Defensive: a Delete row is not an observation even if it
                # somehow carried a value. Not observed in the extracts read.
                self._skip("deleted_vintage")
                continue

            value = as_float(raw_value, field_name="OBS_VALUE", connector=name)
            value *= 10 ** _unit_multiplier(row.get("UNIT_MULT"), name)
            observed_at, is_real = self._observed_at(row, valid_time, name)
            if not is_real:
                assumed += 1

            unit = _text(row, "UNIT")
            require(
                unit != "",
                f"{name}: UNIT is empty, so the series unit is unknown",
                value=unit,
            )
            records.append(
                {
                    "entity_id": TARGET2_ENTITY_ID,
                    "series_id": ecb_series_id(
                        TARGET2_SYSTEM_CODE,
                        TARGET2_REF_AREA,
                        _ECB_INFO_TYPE_ALL_TRANSACTIONS,
                        instrument,
                        measure,
                        unit,
                    ),
                    "valid_time": valid_time,
                    "observed_at": observed_at,
                    "value": value,
                    "revision": 0,
                }
            )

        if assumed:
            self._assume("assumed_publication_lag", assumed)
            logger.warning(
                "%s: %d row(s) carried no VALID_FROM; observed_at uses the "
                "documented lag %s",
                name,
                assumed,
                self.FALLBACK_PUBLICATION_LAG,
            )

        frame = self._record(records, request, name)
        if len(frame):
            # The source does distinguish vintages (ACTION / VALID_FROM), so a
            # second value-carrying vintage of the same period is revision 1.
            frame = frame.sort_values(
                ["series_id", "valid_time", "observed_at"], kind="stable"
            )
            frame["revision"] = (
                frame.groupby(["series_id", "valid_time"]).cumcount().astype("int64")
            )
            frame = frame.sort_values(
                ["valid_time", "series_id", "entity_id"], kind="stable"
            ).reset_index(drop=True)
        return frame


# --------------------------------------------------------------------------
# Facade
# --------------------------------------------------------------------------


class PaymentsConnector(DataConnector):
    """Both systemic rails in one observation frame.

    ``entity_id`` is ``FEDWIRE`` or ``TARGET2`` per row and ``series_id`` is
    prefixed ``BIS:CPMI:`` or ``ECB:PSS:``, so the two systems can never be
    confused once combined. The two key spaces are disjoint by construction.

    **Partial data is not an option.** If either source fails, the whole call
    fails with that source's typed error, after logging which source raised.
    A combined frame missing one rail would read downstream as "that rail
    settled nothing" -- the observation schema has no column in which to record
    "this half is absent" -- so all-or-nothing is the only honest behaviour.

    ``build_url`` returns both endpoints, ``;``-separated, because the base
    contract allows one string and reporting only one of them would understate
    the connector's footprint. :meth:`fetch` does not use it; it delegates to
    each sub-connector so Fedwire's release-calendar lookup still runs.
    """

    accept = "text/csv"

    def __init__(
        self,
        client: Optional[HttpClient] = None,
        *,
        fedwire: Optional[FedwireConnector] = None,
        target2: Optional[Target2Connector] = None,
    ) -> None:
        super().__init__(client)
        # Passing one shared client keeps retry/backoff policy identical for
        # both sources and lets a test inject a single fake.
        self.fedwire = fedwire if fedwire is not None else FedwireConnector(self._client)
        self.target2 = target2 if target2 is not None else Target2Connector(self._client)

    @property
    def spec(self) -> ConnectorSpec:
        return ConnectorSpec(
            name="payments",
            kind="multi",
            entity_id=f"{FEDWIRE_ENTITY_ID}|{TARGET2_ENTITY_ID}",
            source_url="https://www.bis.org/statistics/payment_stats.htm",
            endpoint=f"{BIS_CPMI_ENDPOINT};{ECB_PSS_ENDPOINT}",
            licence=(
                "Combines two publishers, so both sets of terms apply: BIS "
                "statistics may be used freely with attribution and no extra "
                "charge in commercial products (https://www.bis.org/terms_statistics.htm, "
                "read via https://data.bis.org/help/legal); ECB statistics may be "
                "reproduced accurately with the ECB cited as source "
                "(https://www.ecb.europa.eu/services/disclaimer/html/index.en.html)."
            ),
            cadence="annual",
            description=(
                "Fedwire and TARGET2 large-value payment-system volumes from BIS "
                "CPMI and ECB PSS, combined into one observation frame."
            ),
        )

    # -- URLs ------------------------------------------------------------

    def build_url(self, request: FetchRequest) -> str:
        """Both sub-connector URLs, ``;``-separated."""
        return f"{self.fedwire.build_url(request)};{self.target2.build_url(request)}"

    @property
    def endpoints(self) -> Tuple[str, str]:
        """The two real endpoints, as a pair."""
        return (BIS_CPMI_ENDPOINT, ECB_PSS_ENDPOINT)

    # -- Combining -------------------------------------------------------

    #: Which series_id prefix each source owns. Used to decide, before any
    #: request is made, whether a scoped ``FetchRequest`` concerns a source at
    #: all -- asking for one TARGET2 series must not fail because Fedwire has
    #: nothing to return for it.
    SERIES_PREFIXES: Mapping[str, str] = {
        "fedwire": "BIS:CPMI:",
        "target2": "ECB:PSS:",
    }

    def _sources_for(self, request: FetchRequest) -> List[Tuple[str, DataConnector]]:
        """The sub-connectors a scoped request actually concerns.

        An empty ``entity_ids``/``series_ids`` means "no scope", so both sources
        are returned. A scope that matches neither source yields an empty list,
        which the caller turns into :class:`EmptyDatasetError`.
        """
        entities = set(request.entity_ids)
        series = tuple(request.series_ids)
        chosen: List[Tuple[str, DataConnector]] = []
        for source, connector in (
            ("fedwire", self.fedwire),
            ("target2", self.target2),
        ):
            if entities and connector.spec.entity_id not in entities:
                continue
            if series:
                prefix = self.SERIES_PREFIXES[source]
                if not any(item.startswith(prefix) for item in series):
                    continue
            chosen.append((source, connector))
        return chosen

    def parse(self, payload: Any, request: FetchRequest) -> pd.DataFrame:
        """Combine two recorded CSV bodies: ``{"fedwire": ..., "target2": ...}``.

        Performs no network I/O. This is the offline seam the tests drive; the
        sub-parsers keep their own skip counters, which remain readable on
        ``self.fedwire`` / ``self.target2`` afterwards. A source the request
        does not concern is neither required nor parsed.
        """
        name = self.spec.name
        require(
            isinstance(payload, Mapping),
            f"{name}: parse expects a mapping of source name to CSV body",
            connector=name,
            got=type(payload).__name__,
        )
        frames: List[pd.DataFrame] = []
        for source, connector in self._sources_for(request):
            require(
                source in payload,
                f"{name}: parse is missing the {source!r} body",
                connector=name,
                missing=source,
            )
            frames.append(connector.parse(payload[source], request))
        return self._combine(frames, name)

    def _combine(self, frames: Sequence[pd.DataFrame], name: str) -> pd.DataFrame:
        """Concatenate source frames, refusing collisions and conflicts.

        Re-checks the two guarantees the base contract cares about across the
        seam -- nothing is known before it was valid, and two rows that claim
        the same identity do not disagree -- because a collision between the
        two publishers would otherwise only surface inside ``PITStore``.
        """
        if not frames:
            raise EmptyDatasetError(
                f"{name}: the requested scope matches neither source",
                context={"connector": name},
            )
        frame = pd.concat(list(frames), ignore_index=True)
        if frame.empty:
            raise EmptyDatasetError(
                f"{name} produced no observations", context={"connector": name}
            )
        frame = frame.loc[:, list(OBSERVATION_COLUMNS)].copy()
        frame["valid_time"] = pd.to_datetime(frame["valid_time"])
        frame["observed_at"] = pd.to_datetime(frame["observed_at"])
        frame["value"] = pd.to_numeric(frame["value"], errors="coerce").astype(
            "float64"
        )
        frame["revision"] = pd.to_numeric(frame["revision"], errors="coerce").astype(
            "int64"
        )

        early = frame["observed_at"] < frame["valid_time"]
        require(
            not bool(early.any()),
            f"{name}: an observation is stamped before the period it describes",
            connector=name,
            series=sorted(frame.loc[early, "series_id"].unique().tolist())[:5],
        )

        conflicts = frame.groupby(
            ["series_id", "valid_time", "observed_at"]
        )["value"].nunique()
        conflicting = conflicts[conflicts > 1]
        require(
            conflicting.empty,
            f"{name}: the two sources collide on a series key with different values",
            connector=name,
            keys=[str(key) for key in conflicting.index[:5]],
        )
        return frame.sort_values(
            ["valid_time", "series_id", "entity_id"], kind="stable"
        ).reset_index(drop=True)

    def fetch(self, request: Optional[FetchRequest] = None) -> pd.DataFrame:
        """Fetch both sources, or fail the whole call on the first failure.

        Delegates to the sub-connectors -- rather than re-issuing their URLs --
        so Fedwire's release-calendar lookup runs exactly as it would standalone.
        A source that a scoped request does not concern is not contacted at all.
        """
        resolved = request or FetchRequest()
        name = self.spec.name
        frames: List[pd.DataFrame] = []
        for source, connector in self._sources_for(resolved):
            try:
                frames.append(connector.fetch(resolved))
            except Exception:
                logger.error(
                    "%s: source %r failed; refusing to return a partial frame",
                    name,
                    source,
                )
                raise
        return validate_observation_frame(
            self._combine(frames, name), connector=name
        )
