"""BIS total credit -- credit to the private non-financial sector.

Why this feed
-------------
The stock of credit extended to households and non-financial corporations is the
denominator behind household/corporate leverage ratios, the BIS credit-to-GDP
gap and most "excess credit" early-warning measures. It is a *stock* measured at
a point in time, it is *revised*, and it is published with a multi-month lag, so
it belongs in :class:`~backend.modules.data.pit.PITStore` (one vintage per
``valid_time``) rather than in a flat macro table. Collapsing those two clocks is
exactly the failure :mod:`backend.modules.data.pit` exists to prevent, so this
connector keeps them explicit.

Verified source shape (checked with ``curl`` on 2026-09-11)
-----------------------------------------------------------
Endpoint::

    https://stats.bis.org/api/v1/data/WS_TC/all?format=csv&startPeriod=<p>&endPeriod=<p>

``WS_TC`` is the BIS "Total credit" dataflow, version 2.0, whose data structure
is ``BIS_TOTAL_CREDIT(2.0)``. ``GET`` on the endpoint returned ``HTTP 200`` and a
CSV whose header was, verbatim::

    FREQ,BORROWERS_CTY,TC_BORROWERS,TC_LENDERS,VALUATION,UNIT_TYPE,TC_ADJUST,
    COLLECTION,DECIMALS,UNIT_MULT,UNIT_MEASURE,TITLE_TS,TIME_PERIOD,OBS_VALUE,
    OBS_STATUS,OBS_PRE_BREAK,OBS_CONF

The dimension order above matches the DSD exactly (``FREQ, BORROWERS_CTY,
TC_BORROWERS, TC_LENDERS, VALUATION, UNIT_TYPE, TC_ADJUST, TIME_PERIOD``); the
remaining columns are SDMX attributes. ``TITLE_TS`` is a human-readable title, but
the *coded* columns are authoritative here: the title is never parsed, because
BIS edits prose without that being a schema change.

Codes, read from the BIS codelists served at
``https://stats.bis.org/api/v1/codelist/BIS/<ID>/latest``:

* ``TC_BORROWERS`` (``CL_TC_BORROWERS``): ``P`` private non-financial sector,
  ``N`` non-financial corporations, ``H`` households & NPISHs, ``C`` non-financial
  sector (households + corporations + government, i.e. *not* private), ``G``
  general government.
* ``TC_LENDERS`` (``CL_TC_LENDERS``): ``A`` all sectors, ``B`` banks (domestic).
* ``VALUATION`` (``CL_VALUATION``): ``M`` market value, ``N`` nominal value.
* ``UNIT_TYPE`` (``CL_BIS_UNIT``): ``770`` percentage of GDP, ``799`` percentage
  of GDP using PPP exchange rates, ``USD`` US dollar, ``XDC`` domestic currency.
* ``OBS_CONF`` (``CL_CONF_STATUS``): ``F`` free, ``C`` confidential; ``N``/``D``/``S``
  not for publication.
* ``OBS_STATUS`` (``CL_OBS_STATUS``): ``A`` normal, ``B`` break, ``P`` provisional,
  ``Q`` suppressed, ``H``/``L``/``M`` missing.

Units and multipliers -- recorded, never applied
-------------------------------------------------
``UNIT_MULT`` is the SDMX unit multiplier: the value is expressed in
``10 ** UNIT_MULT`` of ``UNIT_MEASURE``. The codelist ``CL_UNIT_MULT`` maps
``0`` (units; the codelist omits 0 but SDMX treats it as no multiplier), ``3``
thousands, ``6`` millions, ``9`` billions, ``12`` trillions. This was checked
against real rows: every ``UNIT_TYPE=770``/``799`` row carries ``UNIT_MULT=0`` and
``UNIT_MEASURE=367`` ("Per cent"), while every ``UNIT_TYPE=USD``/``XDC`` row
carries ``UNIT_MULT=9`` (billions of ``USD``/the domestic currency). ``OBS_VALUE``
is therefore stored **exactly as published**: percent-of-GDP values are already
percentages, and currency values are in *billions* of the stated currency. This
connector does **no** scaling, because scaling would silently change the number
for one unit class and not the other. ``series_id`` carries ``unit=<UNIT_TYPE>``,
which determines the multiplier for every row observed in this feed; a consumer
converting to units must multiply by ``10 ** UNIT_MULT`` and read ``UNIT_MEASURE``
for the currency.

Conventions this connector fixes
--------------------------------
``series_id``
    ``BIS:TC:borrowers=<TC_BORROWERS>:lenders=<TC_LENDERS>:val=<VALUATION>:unit=<UNIT_TYPE>``
    e.g. ``BIS:TC:borrowers=P:lenders=A:val=M:unit=770``. Built only from coded
    dimensions, so it is stable across title wording changes and self-describing
    without a lookup table.

``entity_id``
    ``BORROWERS_CTY`` -- an ISO-2 country code (``LU``, ``SE``) or a BIS aggregate
    code (``4T`` emerging market economies). The *borrower* country is the entity
    the observation describes; the lender sector is part of the series.

``valid_time``
    The **last day of the quarter** the value describes: ``2025-Q4`` becomes
    ``2025-12-31``. Total credit is a stock measured at a point in time, and the
    BIS reports it on an end-of-period basis (``COLLECTION=E``), so the last
    instant at which the reported stock was the reported stock is quarter end.
    Using quarter end (rather than quarter start) also matters for the two-clock
    rule: a value published after quarter end keeps ``observed_at >= valid_time``.

``observed_at``
    The date the value first became public. The CSV carries no per-observation
    publication timestamp, so the connector resolves one in this order:

    1. ``release_dates`` passed to the constructor -- an explicit
       ``{"2025-Q4": "2026-06-15"}`` mapping. These can be taken from the BIS
       release calendar dataflow ``BIS_REL_CAL``: category ``TOTAL_CREDIT``,
       release type ``S``, ``TIME_PERIOD`` the reference quarter and ``OBS_VALUE``
       an 8-digit release date. Use :func:`parse_release_calendar` to build the
       mapping from that payload. The 14 ``TOTAL_CREDIT`` releases available on
       2026-09-11 ran from 2023-Q1 (released 2023-09-18) to 2026-Q2 (released
       2026-12-07).
    2. Otherwise ``valid_time + publication_lag_days``. The default,
       :data:`DEFAULT_PUBLICATION_LAG_DAYS`, is **171 days -- an assumption**, the
       largest lag seen across those 14 releases (range 156-171, mean 164). The
       maximum is chosen deliberately: a lag that were too short would claim a
       value was knowable before BIS released it, which is the clairvoyance this
       package exists to prevent; a lag that is slightly too long only forgoes a
       few days of legitimate signal.

    A supplied release date that precedes ``valid_time`` is rejected
    (:class:`SchemaValidationError`) rather than silently pushed forward.
    ``observed_at`` is never the wall-clock time.

    *Limitation, stated plainly:* ``WS_TC`` exposes only the latest revision of a
    period, not the vintage timeline. Stamping a period with its *first* release
    date means a figure that BIS later revised is attributed to (and visible from)
    the first release. Ingestion is therefore vintage-honest only up to the first
    print; callers who need revision-accurate history must supply per-vintage
    ``observed_at`` values themselves.

``revision``
    Always ``0``. ``OBS_PRE_BREAK`` is a break flag and ``OBS_CONF`` a
    confidentiality flag; neither distinguishes a restatement, and no column in
    this feed reports a vintage number. Inventing one is worse than admitting the
    limitation, so revisions are simply not distinguished. Because the store keys
    on ``(entity, series, valid_time, observed_at, revision)``, a later restatement
    re-ingested under the same first-print date is rejected by
    :class:`~backend.modules.data.pit.PITStore` as a conflicting vintage instead of
    silently overwriting one.

Suppressed cells
----------------
``OBS_VALUE`` is empty for suppressed observations, and BIS's CSV writer also
emits the literal string ``"NaN"`` for an absent attribute (observed in
``OBS_PRE_BREAK``). A row whose value is one of the placeholders that
:func:`~backend.modules.data.connectors.base.as_float` rejects -- ``""``, ``".."``,
``"-"``, ``"c"``, ``"NaN"`` ... -- is **skipped and counted**, not fatal: empty
cells are normal in BIS data and one suppressed cell must not discard a batch of
thousands. The count is exposed on :attr:`BisCreditConnector.last_stats`. A value
that is present but not numeric at all still raises, because that is schema drift
rather than suppression.

Default slice
-------------
``TC_BORROWERS`` in ``{"P", "N", "H"}`` and ``TC_LENDERS`` in ``{"A", "B"}``,
``TC_ADJUST="A"``, ``FREQ="Q"``. ``P`` is the private non-financial sector itself,
``N`` splits out corporations and ``H`` households; ``C`` is excluded because it
adds general government -- the public sector -- which is not private credit, and
``G`` is excluded for the same reason. ``A``/``B`` cover credit from all sectors
and from banks. Every axis is a constructor argument. ``TC_ADJUST`` defaults to
``A`` (adjusted for breaks): BIS publishes each series twice, and where no break
exists the adjusted and unadjusted rows are byte-identical, so keeping both would
put two rows on the same ``series_id`` and ``valid_time``. ``series_id`` does not
carry the adjustment, so a caller who configures both must expect the duplicate
check to fail closed on any pair whose values differ.

Fails closed
------------
An unreachable source, an HTTP error, a missing or reordered required column, an
unparseable period, a non-numeric (not merely suppressed) value, two rows on one
series/period with different values, or no rows left after filtering all raise a
typed :class:`~backend.exceptions.BeaconError`. Nothing is interpolated or
forward-filled.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

from backend.exceptions import EmptyDatasetError, SchemaValidationError

from ..pit import OBSERVATION_COLUMNS
from .base import (
    ConnectorSpec,
    DataConnector,
    FetchRequest,
    HttpClient,
    as_float,
    require,
)

logger = logging.getLogger(__name__)

__all__ = [
    "BIS_DATA_ENDPOINT",
    "BIS_DATA_PORTAL_URL",
    "BIS_LICENCE",
    "BIS_RELEASE_CALENDAR_ENDPOINT",
    "BIS_TC_COLUMNS",
    "BisCreditConnector",
    "DEFAULT_ADJUSTMENTS",
    "DEFAULT_BORROWERS",
    "DEFAULT_FREQUENCIES",
    "DEFAULT_LENDERS",
    "DEFAULT_PUBLICATION_LAG_DAYS",
    "ParseStats",
    "TC_BORROWER_LABELS",
    "TC_LENDER_LABELS",
    "UNIT_MULT_LABELS",
    "UNIT_TYPE_LABELS",
    "VALUATION_LABELS",
    "parse_release_calendar",
]

#: Stable registry key; also used as ``ConnectorReport.connector``.
CONNECTOR_NAME = "bis_credit"

#: Human-facing BIS Data Portal topic page (verified ``HTTP 200``).
BIS_DATA_PORTAL_URL = "https://data.bis.org/topics/TOTAL_CREDIT"

#: Machine endpoint, without the period query. Verified ``HTTP 200``.
BIS_DATA_ENDPOINT = "https://stats.bis.org/api/v1/data/WS_TC/all"

#: Release-calendar dataflow (``BIS_REL_CAL``, version 1.0). The ``WS_REL_CAL``
#: id suggested by the BIS site name does not resolve; ``BIS_REL_CAL`` does. The
#: ``?format=csv`` suffix is part of the constant because there is no ``build_url``
#: for this feed and the API defaults to XML without it.
BIS_RELEASE_CALENDAR_ENDPOINT = (
    "https://stats.bis.org/api/v1/data/BIS_REL_CAL/all?format=csv"
)

#: Quoted from the BIS "Terms of permitted use of BIS statistics" and the BIS API
#: terms at https://data.bis.org/help/legal (retrieved 2026-09-11). The binding
#: clause for us is attribution: reproduction is permitted provided the BIS is
#: cited as the source and no BIS endorsement is implied.
BIS_LICENCE = (
    "BIS statistics: use is unrestricted provided the BIS is cited as the source "
    "in any reproduction, translations are marked unofficial, use is not "
    "misleading (no implied BIS endorsement) and commercial inclusion adds no "
    "charge to subscribers. The BIS warrants no accuracy and gives no investment "
    "advice; the API is provided 'as-is' (data.bis.org/help/legal, 2026-09-11)."
)

#: The verified CSV header, in the order the DSD and the API emit it. Required
#: columns must all be present *and* keep this relative order: a reordering means
#: the source changed shape, which is exactly when a parser must refuse to guess.
BIS_TC_COLUMNS: Tuple[str, ...] = (
    "FREQ",
    "BORROWERS_CTY",
    "TC_BORROWERS",
    "TC_LENDERS",
    "VALUATION",
    "UNIT_TYPE",
    "TC_ADJUST",
    "COLLECTION",
    "DECIMALS",
    "UNIT_MULT",
    "UNIT_MEASURE",
    "TITLE_TS",
    "TIME_PERIOD",
    "OBS_VALUE",
    "OBS_STATUS",
    "OBS_PRE_BREAK",
    "OBS_CONF",
)

#: Labels from the BIS codelists, kept beside the codes so a reader does not have
#: to leave the module to know what ``TC_BORROWERS=P`` means.
TC_BORROWER_LABELS: Dict[str, str] = {
    "P": "Private non-financial sector",
    "N": "Non-financial corporations",
    "H": "Households & NPISHs",
    "C": "Non financial sector (private + government)",
    "G": "General government",
}
TC_LENDER_LABELS: Dict[str, str] = {
    "A": "All sectors",
    "B": "Banks, domestic",
}
VALUATION_LABELS: Dict[str, str] = {
    "M": "Market value",
    "N": "Nominal value",
}
UNIT_TYPE_LABELS: Dict[str, str] = {
    "770": "Percentage of GDP",
    "799": "Percentage of GDP (PPP exchange rates)",
    "USD": "US dollar",
    "XDC": "Domestic currency",
}
#: SDMX unit multiplier: the value is in ``10 ** UNIT_MULT`` of ``UNIT_MEASURE``.
UNIT_MULT_LABELS: Dict[str, str] = {
    "0": "Units (no multiplier)",
    "1": "Tens",
    "2": "Hundreds",
    "3": "Thousands",
    "4": "Tens of thousands",
    "6": "Millions",
    "7": "Tens of millions",
    "8": "Hundred millions",
    "9": "Billions",
    "12": "Trillions",
    "15": "Quadrillions",
}

#: Private-credit borrowers: the private sector itself, plus its two components.
DEFAULT_BORROWERS: Tuple[str, ...] = ("P", "N", "H")
#: Credit from every lender, and from banks specifically.
DEFAULT_LENDERS: Tuple[str, ...] = ("A", "B")
#: Break-adjusted rows only; see the module docstring for why both would collide.
DEFAULT_ADJUSTMENTS: Tuple[str, ...] = ("A",)
#: ``WS_TC`` is the quarterly total-credit dataflow.
DEFAULT_FREQUENCIES: Tuple[str, ...] = ("Q",)
#: Documented assumption: maximum first-release lag, in days, of the 14
#: ``TOTAL_CREDIT`` releases listed in the module docstring (range 156-171).
DEFAULT_PUBLICATION_LAG_DAYS = 171

#: Placeholders that mean "no value", not zero. ``as_float`` rejects the same set
#: (plus ``"NaN"``, which BIS's CSV writer emits for absent attributes); this
#: module checks them first so a suppressed cell is counted instead of raising.
_SUPPRESSED_VALUES = frozenset(
    {
        "",
        ".",
        "..",
        "-",
        "c",
        "C",
        "n/a",
        "N/A",
        "NA",
        "null",
        "None",
        "nan",
        "NaN",
        "NAN",
    }
)

#: ``YYYY-Qn`` only. ``FREQ`` is filtered to ``Q`` first, so anything else here is
#: a genuine schema surprise rather than a period the connector supports.
_QUARTER_RE = re.compile(r"^(\d{4})-Q([1-4])$")


@dataclass
class ParseStats:
    """Sidecar counts from one :meth:`BisCreditConnector.parse` call.

    ``parse`` has to return an observation frame, so it cannot also return a
    summary. The counts are kept on the connector instead, which is what makes
    "we skipped N suppressed cells" visible rather than silent.
    """

    rows_in_payload: int = 0
    rows_out_of_slice: int = 0
    rows_filtered_by_request: int = 0
    rows_suppressed: int = 0
    duplicate_rows_collapsed: int = 0
    rows_emitted: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {
            "rows_in_payload": self.rows_in_payload,
            "rows_out_of_slice": self.rows_out_of_slice,
            "rows_filtered_by_request": self.rows_filtered_by_request,
            "rows_suppressed": self.rows_suppressed,
            "duplicate_rows_collapsed": self.duplicate_rows_collapsed,
            "rows_emitted": self.rows_emitted,
        }


def _quarter_end(period: str) -> pd.Timestamp:
    """Last calendar day of the quarter named by a BIS ``TIME_PERIOD``.

    Raises:
        SchemaValidationError: The label is not ``YYYY-Qn``. Failing here is
            deliberate: guessing a period from a malformed label is how a value
            ends up attached to the wrong quarter.
    """
    match = _QUARTER_RE.match(str(period).strip().upper())
    if match is None:
        raise SchemaValidationError(
            f"{CONNECTOR_NAME}: TIME_PERIOD is not a quarterly period",
            context={"connector": CONNECTOR_NAME, "period": str(period)},
        )
    year, quarter = int(match.group(1)), int(match.group(2))
    return pd.Timestamp(year=year, month=quarter * 3, day=1) + pd.offsets.MonthEnd(0)


def _quarter_label(stamp: pd.Timestamp) -> str:
    """BIS ``TIME_PERIOD`` label for the quarter containing ``stamp``."""
    return f"{stamp.year}-Q{stamp.quarter}"


def _quarter_bounds(stamp: pd.Timestamp) -> Tuple[pd.Timestamp, pd.Timestamp]:
    """First and last calendar day of the quarter containing ``stamp``."""
    period = pd.Period(stamp, freq="Q")
    return period.start_time.normalize(), period.end_time.normalize()


def _is_suppressed(value: Any) -> bool:
    """Whether ``value`` is a "no value" placeholder rather than a number."""
    return str(value).strip() in _SUPPRESSED_VALUES


def _read_csv(payload: bytes) -> pd.DataFrame:
    """Read a BIS CSV payload as strings, preserving empty cells as ``""``.

    ``keep_default_na=False`` is load-bearing: with the default, pandas would turn
    an empty ``OBS_VALUE`` into ``NaN`` and turn the string ``"NA"`` into a missing
    value, which would erase the distinction between a suppressed cell and a
    country code that happens to read like a placeholder.

    Raises:
        SchemaValidationError: The payload is empty or is not decodable CSV.
    """
    if payload is None or not isinstance(payload, (bytes, bytearray)):
        raise SchemaValidationError(
            f"{CONNECTOR_NAME}: payload must be bytes",
            context={"connector": CONNECTOR_NAME, "type": type(payload).__name__},
        )
    if not bytes(payload).strip():
        raise SchemaValidationError(
            f"{CONNECTOR_NAME}: response body is empty",
            context={"connector": CONNECTOR_NAME},
        )
    try:
        return pd.read_csv(
            io.BytesIO(bytes(payload)),
            dtype=str,
            keep_default_na=False,
            encoding="utf-8-sig",
        )
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
        raise SchemaValidationError(
            f"{CONNECTOR_NAME}: response is not decodable CSV",
            context={"connector": CONNECTOR_NAME},
            cause=exc,
        ) from exc


def _validate_columns(frame: pd.DataFrame) -> None:
    """Require the documented columns, present and in their documented order.

    Raises:
        SchemaValidationError: A required column is missing, or the required
            columns appear in a different relative order (schema drift).
    """
    present = [str(column) for column in frame.columns]
    missing = [column for column in BIS_TC_COLUMNS if column not in present]
    if missing:
        raise SchemaValidationError(
            f"{CONNECTOR_NAME}: response is missing required columns",
            context={
                "connector": CONNECTOR_NAME,
                "missing": missing,
                "present": present,
            },
        )
    required = set(BIS_TC_COLUMNS)
    ordered = [column for column in present if column in required]
    if ordered != list(BIS_TC_COLUMNS):
        raise SchemaValidationError(
            f"{CONNECTOR_NAME}: response columns are in an unexpected order",
            context={
                "connector": CONNECTOR_NAME,
                "expected": list(BIS_TC_COLUMNS),
                "found": ordered,
            },
        )


def parse_release_calendar(
    payload: bytes,
    *,
    categories: Sequence[str] = ("TOTAL_CREDIT",),
) -> Dict[str, pd.Timestamp]:
    """Map reference period -> first release date from a ``BIS_REL_CAL`` payload.

    The BIS release-calendar dataflow publishes, per reference period, the date its
    statistics were (or will be) released. For ``TOTAL_CREDIT`` the calendar's
    ``TIME_PERIOD`` is the reference quarter and ``OBS_VALUE`` is an 8-digit
    ``YYYYMMDD`` date, which is exactly the ``{period: release date}`` mapping
    :class:`BisCreditConnector` accepts as ``release_dates``.

    Offline by construction: it parses bytes and performs no I/O, so it is
    testable against a recorded payload.

    Args:
        payload: Raw CSV from :data:`BIS_RELEASE_CALENDAR_ENDPOINT`.
        categories: Calendar categories to keep. Defaults to ``TOTAL_CREDIT``.

    Returns:
        ``{"2025-Q4": Timestamp("2026-06-15"), ...}``. When a period appears more
        than once the *earliest* date wins, because the first release is when the
        period's number first became public.

    Raises:
        SchemaValidationError: Required calendar columns are missing, a kept row's
            release date is not an 8-digit date, or nothing matched.
    """
    frame = _read_csv(payload)
    missing = [
        column
        for column in ("CATEGORY", "TIME_PERIOD", "OBS_VALUE")
        if column not in frame.columns
    ]
    if missing:
        raise SchemaValidationError(
            f"{CONNECTOR_NAME}: release calendar is missing required columns",
            context={"connector": CONNECTOR_NAME, "missing": missing},
        )

    wanted = {str(category).strip().upper() for category in categories}
    kept = frame[
        frame["CATEGORY"].map(lambda value: str(value).strip().upper()).isin(wanted)
    ]
    if kept.empty:
        raise EmptyDatasetError(
            f"{CONNECTOR_NAME}: release calendar matched no categories",
            context={
                "connector": CONNECTOR_NAME,
                "categories": sorted(wanted),
            },
        )

    dates = pd.to_datetime(
        kept["OBS_VALUE"].astype(str).str.strip(), format="%Y%m%d", errors="coerce"
    )
    if dates.isna().any():
        bad = kept.loc[dates.isna(), "OBS_VALUE"].astype(str).unique()[:5]
        raise SchemaValidationError(
            f"{CONNECTOR_NAME}: release calendar carries unparseable dates",
            context={"connector": CONNECTOR_NAME, "values": [str(v) for v in bad]},
        )

    releases: Dict[str, pd.Timestamp] = {}
    for period, released in zip(kept["TIME_PERIOD"], dates):
        key = str(period).strip().upper()
        stamp = pd.Timestamp(released).normalize()
        current = releases.get(key)
        if current is None or stamp < current:
            releases[key] = stamp
    return releases


class BisCreditConnector(DataConnector):
    """Connector for BIS ``WS_TC`` total credit (private credit).

    See the module docstring for the verified schema, the ``valid_time`` /
    ``observed_at`` conventions, and the unit/multiplier handling.
    """

    #: BIS serves CSV here; the base default is JSON.
    accept = "text/csv"

    def __init__(
        self,
        *,
        borrowers: Sequence[str] = DEFAULT_BORROWERS,
        lenders: Sequence[str] = DEFAULT_LENDERS,
        valuations: Optional[Sequence[str]] = None,
        unit_types: Optional[Sequence[str]] = None,
        adjustments: Sequence[str] = DEFAULT_ADJUSTMENTS,
        frequencies: Sequence[str] = DEFAULT_FREQUENCIES,
        publication_lag_days: int = DEFAULT_PUBLICATION_LAG_DAYS,
        release_dates: Optional[Mapping[str, Any]] = None,
        client: Optional[HttpClient] = None,
    ) -> None:
        """Configure the slice and the publication-date rule.

        Args:
            borrowers: ``TC_BORROWERS`` codes to keep. Defaults to the private
                slice ``("P", "N", "H")``; pass ``("P",)`` for the aggregate
                private sector only.
            lenders: ``TC_LENDERS`` codes to keep. Defaults to ``("A", "B")``.
            valuations: ``VALUATION`` codes; ``None`` keeps every valuation
                (market and nominal are distinct series).
            unit_types: ``UNIT_TYPE`` codes; ``None`` keeps every unit (each is a
                distinct series and is named in ``series_id``).
            adjustments: ``TC_ADJUST`` codes. Defaults to ``("A",)`` for the
                break-adjusted headline series; see the module docstring.
            frequencies: ``FREQ`` codes. Defaults to ``("Q",)``.
            publication_lag_days: Fallback first-publication lag used when
                ``release_dates`` has no entry for a period. See
                :data:`DEFAULT_PUBLICATION_LAG_DAYS`.
            release_dates: Explicit ``{"2025-Q4": "2026-06-15"}`` first-release
                dates, e.g. from :func:`parse_release_calendar`. Overrides the lag.
            client: Injected :class:`~backend.modules.data.connectors.base.HttpClient`.

        Raises:
            ValueError: A slice is empty, or the lag is negative.
        """
        super().__init__(client=client)
        self._borrowers = self._codes(borrowers, "borrowers")
        self._lenders = self._codes(lenders, "lenders")
        self._valuations = self._codes(valuations, "valuations", allow_none=True)
        self._unit_types = self._codes(unit_types, "unit_types", allow_none=True)
        self._adjustments = self._codes(adjustments, "adjustments")
        self._frequencies = self._codes(frequencies, "frequencies")
        if publication_lag_days < 0:
            raise ValueError(
                f"publication_lag_days must be non-negative, got {publication_lag_days}"
            )
        self._publication_lag_days = int(publication_lag_days)
        self._release_dates: Dict[str, pd.Timestamp] = {}
        for key, value in (release_dates or {}).items():
            try:
                stamp = pd.Timestamp(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"release_dates[{key!r}] is not a timestamp: {value!r}"
                ) from exc
            self._release_dates[str(key).strip().upper()] = stamp
        #: Counts from the most recent :meth:`parse`; see :class:`ParseStats`.
        self.last_stats = ParseStats()

    @staticmethod
    def _codes(
        values: Optional[Sequence[str]], name: str, *, allow_none: bool = False
    ) -> Optional[Tuple[str, ...]]:
        """Normalise a code slice to a tuple of stripped strings."""
        if values is None:
            return None if allow_none else ()
        codes = tuple(str(value).strip() for value in values if str(value).strip())
        if not codes and not allow_none:
            raise ValueError(f"{name} must name at least one code")
        return codes

    @property
    def spec(self) -> ConnectorSpec:
        """Static description of this connector, including BIS redistribution terms."""
        return ConnectorSpec(
            name=CONNECTOR_NAME,
            kind="bis",
            # The reporting entity varies per row (borrower country/aggregate), so
            # the spec cannot name one; "*" marks "see the row".
            entity_id="*",
            source_url=BIS_DATA_PORTAL_URL,
            endpoint=BIS_DATA_ENDPOINT,
            licence=BIS_LICENCE,
            cadence="quarterly",
            description=(
                "Credit to the private non-financial sector (households and "
                "non-financial corporations) from banks and from all sectors, as "
                "stocks valued at market value or nominal value."
            ),
            requires_credentials=False,
        )

    def build_url(self, request: FetchRequest) -> str:
        """Absolute ``WS_TC`` URL for ``request``, without credentials.

        ``FetchRequest`` bounds are timestamps but BIS ``startPeriod``/``endPeriod``
        are SDMX periods, so each bound is coarsened to the quarter containing it
        (a ``FetchRequest(start="2025-Q4")`` resolves to ``2025-10-01``, whose
        quarter is ``2025-Q4``). :meth:`parse` applies the window at the *same*
        quarter granularity, so the rows kept agree with the URL that was sent
        even though ``valid_time`` is the quarter's last day.

        ``entity_ids``/``series_ids`` are **not** sent to BIS: only the verified
        ``WS_TC/all`` URL shape is used here, and those filters are applied in
        :meth:`parse`. An entity-scoped request therefore still downloads the full
        payload -- correct, but not bandwidth-optimal.
        """
        query = ["format=csv"]
        if request.start is not None:
            query.append(f"startPeriod={_quarter_label(request.start)}")
        if request.end is not None:
            query.append(f"endPeriod={_quarter_label(request.end)}")
        return f"{BIS_DATA_ENDPOINT}?{'&'.join(query)}"

    def parse(self, payload: bytes, request: FetchRequest) -> pd.DataFrame:
        """Parse a ``WS_TC`` CSV response into an observation frame. No I/O.

        Applies the configured slice, the request's window and entity/series
        scope, skips suppressed values (counting them on :attr:`last_stats`),
        resolves ``observed_at``, and fails closed on duplicates with conflicting
        values. The window is applied at quarter granularity -- the granularity
        BIS itself filters at -- so a bound that falls mid-quarter keeps the whole
        quarter rather than a fraction of it.

        Raises:
            SchemaValidationError: Missing/reordered columns, a bad period, a
                present-but-non-numeric value, a release date before the period,
                or two rows on one series/period with different values.
            EmptyDatasetError: No rows survive the slice, request and suppression.
        """
        frame = _read_csv(payload)
        _validate_columns(frame)
        if frame.empty:
            raise EmptyDatasetError(
                f"{CONNECTOR_NAME}: response contained a header but no rows",
                context={"connector": CONNECTOR_NAME},
            )

        stats = ParseStats(rows_in_payload=int(frame.shape[0]))
        entity_filter = set(request.entity_ids)
        series_filter = set(request.series_ids)
        window_start = (
            _quarter_bounds(request.start)[0] if request.start is not None else None
        )
        window_end = (
            _quarter_bounds(request.end)[1] if request.end is not None else None
        )
        records: List[Dict[str, Any]] = []

        for row in frame.to_dict("records"):
            if not self._in_slice(row):
                stats.rows_out_of_slice += 1
                continue

            valid_time = _quarter_end(row["TIME_PERIOD"])
            if window_start is not None and valid_time < window_start:
                stats.rows_filtered_by_request += 1
                continue
            if window_end is not None and valid_time > window_end:
                stats.rows_filtered_by_request += 1
                continue

            entity_id = str(row["BORROWERS_CTY"]).strip()
            series_id = self._series_id(row)
            if entity_filter and entity_id not in entity_filter:
                stats.rows_filtered_by_request += 1
                continue
            if series_filter and series_id not in series_filter:
                stats.rows_filtered_by_request += 1
                continue

            raw_value = row["OBS_VALUE"]
            if _is_suppressed(raw_value):
                # Empty cells are normal in BIS data; one suppressed observation
                # must not discard the batch. Non-numeric garbage still raises
                # below, because that is schema drift, not suppression.
                stats.rows_suppressed += 1
                continue
            value = as_float(
                raw_value, field_name="OBS_VALUE", connector=CONNECTOR_NAME
            )

            records.append(
                {
                    "entity_id": entity_id,
                    "series_id": series_id,
                    "valid_time": valid_time,
                    "observed_at": self._observed_at(row["TIME_PERIOD"], valid_time),
                    "value": value,
                    "revision": self._revision(row),
                }
            )

        # Publish the counts before any later failure so that a rejected batch is
        # still diagnosable ("9 of 12 rows were out of slice").
        self.last_stats = stats
        if not records:
            raise EmptyDatasetError(
                f"{CONNECTOR_NAME}: no rows survived slicing and suppression",
                context={
                    "connector": CONNECTOR_NAME,
                    "rows_in_payload": stats.rows_in_payload,
                    "rows_out_of_slice": stats.rows_out_of_slice,
                    "rows_filtered_by_request": stats.rows_filtered_by_request,
                    "rows_suppressed": stats.rows_suppressed,
                },
            )

        parsed = pd.DataFrame.from_records(records, columns=list(OBSERVATION_COLUMNS))
        key_columns = ["entity_id", "series_id", "valid_time"]
        distinct = parsed.groupby(key_columns, sort=False)["value"].nunique()
        conflicts = distinct[distinct > 1]
        if not conflicts.empty:
            first = conflicts.index[0]
            raise SchemaValidationError(
                f"{CONNECTOR_NAME}: one series/period carries conflicting values",
                context={
                    "connector": CONNECTOR_NAME,
                    "entity_id": str(first[0]),
                    "series_id": str(first[1]),
                    "valid_time": str(first[2]),
                },
            )
        deduped = parsed.drop_duplicates(subset=key_columns, keep="first")
        stats.duplicate_rows_collapsed = int(parsed.shape[0] - deduped.shape[0])
        stats.rows_emitted = int(deduped.shape[0])
        if stats.rows_suppressed:
            logger.warning(
                "%s: skipped %d suppressed OBS_VALUE cell(s) of %d row(s)",
                CONNECTOR_NAME,
                stats.rows_suppressed,
                stats.rows_in_payload,
            )

        deduped = deduped.copy()
        deduped["valid_time"] = pd.to_datetime(deduped["valid_time"])
        deduped["observed_at"] = pd.to_datetime(deduped["observed_at"])
        deduped["value"] = deduped["value"].astype("float64")
        deduped["revision"] = deduped["revision"].astype("int64")
        return deduped.sort_values(
            ["valid_time", "series_id", "entity_id"], kind="stable"
        ).reset_index(drop=True)

    def _in_slice(self, row: Mapping[str, Any]) -> bool:
        """Whether ``row`` falls inside the configured frequency/sector slice."""
        if str(row["FREQ"]).strip() not in self._frequencies:
            return False
        if str(row["TC_BORROWERS"]).strip() not in self._borrowers:
            return False
        if str(row["TC_LENDERS"]).strip() not in self._lenders:
            return False
        if str(row["TC_ADJUST"]).strip() not in self._adjustments:
            return False
        if (
            self._valuations is not None
            and str(row["VALUATION"]).strip() not in self._valuations
        ):
            return False
        if (
            self._unit_types is not None
            and str(row["UNIT_TYPE"]).strip() not in self._unit_types
        ):
            return False
        return True

    @staticmethod
    def _series_id(row: Mapping[str, Any]) -> str:
        """Self-describing series key from the coded dimensions, e.g.
        ``BIS:TC:borrowers=P:lenders=A:val=M:unit=770``."""
        return "BIS:TC:borrowers={b}:lenders={l}:val={v}:unit={u}".format(
            b=str(row["TC_BORROWERS"]).strip(),
            l=str(row["TC_LENDERS"]).strip(),
            v=str(row["VALUATION"]).strip(),
            u=str(row["UNIT_TYPE"]).strip(),
        )

    def _observed_at(self, period: str, valid_time: pd.Timestamp) -> pd.Timestamp:
        """First-publication date for ``period``; never before ``valid_time``."""
        explicit = self._release_dates.get(str(period).strip().upper())
        if explicit is not None:
            observed_at = pd.Timestamp(explicit).normalize()
        else:
            # ``unit="D"`` explicitly: a bare integer day count goes through NumPy's
            # deprecated "generic" timedelta unit on this pandas/NumPy pair.
            observed_at = valid_time + pd.Timedelta(
                self._publication_lag_days, unit="D"
            )
        require(
            observed_at >= valid_time,
            f"{CONNECTOR_NAME}: observed_at precedes valid_time",
            connector=CONNECTOR_NAME,
            period=str(period),
            observed_at=str(observed_at),
            valid_time=str(valid_time),
        )
        return observed_at

    @staticmethod
    def _revision(row: Mapping[str, Any]) -> int:
        """Always ``0``: this feed exposes no vintage or restatement number.

        ``OBS_PRE_BREAK`` marks a series break and ``OBS_CONF`` a confidentiality
        flag; neither is a revision label, and inventing one would fabricate a
        vintage chain that the source never published.
        """
        return 0
