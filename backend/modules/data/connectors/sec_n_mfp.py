"""SEC Form N-MFP -- money-market fund monthly portfolio and liquidity report.

Why this feed matters
---------------------
A money-market fund is a systemic node: it holds short-dated paper, promises
same-day liquidity at a stable share price, and is the buyer of last resort for
parts of the commercial-paper and repo markets. Form N-MFP is the only public
source of the fund's own monthly numbers -- total net assets, dollar-weighted
average portfolio maturity (WAM), dollar-weighted average life (WAL), and daily
and weekly liquid assets -- so it is the feed that makes that exposure visible
before a run rather than after it.

Live verification (2026-09-11, ``User-Agent: BNELabs-BEACON/1.0
(research; bne@bnelabs.dev)``)
--------------------------------------------------------------------------
* ``GET https://efts.sec.gov/LATEST/search-index?q=...&forms=N-MFP...`` -> HTTP
  200, but **zero hits** for N-MFP / N-MFP2 in every window tried (2019, 2022,
  2023, 2024, 2025, 2026) even though ``form.idx`` shows ~1000 N-MFP2 filings in
  a single quarter. Structured N-MFP submissions are not in the full-text index,
  so this connector deliberately does not discover filings through it. This is a
  correction to the brief, not a shortcut.
* ``GET https://data.sec.gov/submissions/CIK0000862021.json`` -> HTTP 200
  (118 KB), ``filings.recent`` carries the parallel arrays ``accessionNumber``,
  ``form``, ``filingDate``, ``reportDate`` and ``primaryDocument``. This is the
  discovery path actually used.
* ``GET https://www.sec.gov/Archives/edgar/data/862021/000114554924001106/primary_doc.xml``
  -> HTTP 200, the real filing XML.
* ``primaryDocument`` in the submissions index points at a *rendered* copy
  (``xslN-MFP2_X01/primary_doc.xml``) which returns XHTML (``<!DOCTYPE html>``),
  not the machine-readable XML. The connector therefore keeps only the basename
  and fetches ``<accession-dir>/primary_doc.xml``, which returns the raw XML.

Observed schemas -- exact tags, all rooted at ``edgarSubmission``
----------------------------------------------------------------
``http://www.sec.gov/edgar/nmfp3`` (Form N-MFP3, current since 2024-07):
    ``formData/generalInfo/{reportDate,cik,seriesId}``;
    ``formData/seriesLevelInfo/{averagePortfolioMaturity,averageLifeMaturity,
    netAssetOfSeries}``; liquidity is a *dated daily panel*: one
    ``liquidAssetsDetails`` block per business day, each carrying
    ``totalValueDailyLiquidAssets``, ``totalValueWeeklyLiquidAssets``,
    ``percentageDailyLiquidAssets``, ``percentageWeeklyLiquidAssets`` and
    ``totalLiquidAssetsNearPercentDate``.

``http://www.sec.gov/edgar/nmfp2`` (N-MFP2, 2016-10..2024-06) and
``http://www.sec.gov/edgar/nmfp1`` (N-MFP1, 2016-05..2016-10), whose ``ns3``
namespace is ``.../nmfp2common`` / ``.../nmfp1common``:
    the same ``generalInfo`` / ``seriesLevelInfo`` tags, except liquidity is a
    *positional* container -- ``totalValueDailyLiquidAssets`` with children
    ``ns3:fridayDay1``..``ns3:fridayDay5`` on N-MFP2 (``ns3:fridayWeek1``..
    ``ns3:fridayWeek4`` on the one N-MFP1 filing inspected) and
    ``totalValueWeeklyLiquidAssets`` with ``ns3:fridayWeek1``..``ns3:fridayWeek5``,
    with ``percentageDailyLiquidAssets`` / ``percentageWeeklyLiquidAssets``
    shaped the same way. Form item A.13 asks for each Friday of the reporting
    month, and the *last* slot is "(if applicable)" -- it is often present as a
    literal ``0.00`` filler on a four-Friday month.

``http://www.sec.gov/edgar/nmfp`` (original N-MFP, filed through 2016-04):
    ``DocumentPeriodEndDate``, ``EntityCentralIndexKey``, ``seriesId`` and
    ``seriesLevelInformation/part1:{dollarWeightedAveragePortfolioMaturity,
    dollarWeightedAverageLifeMaturity,AssetsNet}``. It carries **no** daily or
    weekly liquid-asset elements, so only three series are emitted for it; the
    liquidity series are absent, not zero.

Conventions this connector fixes
--------------------------------
*Series ids* (stable strings, unit stated once):

====================== =======================================================
``N-MFP:TOTAL_NET_ASSETS``        total net assets of the series, USD
``N-MFP:WAM_DAYS``                dollar-weighted average portfolio maturity, days
``N-MFP:WAL_DAYS``                dollar-weighted average life maturity, days
``N-MFP:DAILY_LIQUID_ASSETS``     daily liquid assets, USD
``N-MFP:WEEKLY_LIQUID_ASSETS``    weekly liquid assets (incl. daily), USD
``N-MFP:DAILY_LIQUID_ASSETS_PCT`` daily liquid assets / total assets, fraction
``N-MFP:WEEKLY_LIQUID_ASSETS_PCT``weekly liquid assets / total assets, fraction
====================== =======================================================

* ``entity_id`` is the filing's ``seriesId`` (e.g. ``S000011990``), falling back
  to ``CIK##########`` only when the filing omits it. It is the *fund series*,
  never the reader. A CIK is not a safe identifier here: one registrant files
  several series on the same day, and collapsing them onto the CIK would make
  two distinct funds indistinguishable -- and :class:`PITStore` would reject the
  second as a conflicting rewrite of the first.
* ``valid_time`` is the period the filing describes: EDGAR ``reportDate`` (the
  month end), or the legacy ``DocumentPeriodEndDate``. The five Friday values are
  labelled with that month end rather than with each Friday, because the filing
  is the unit of publication and the month is the period it reports.
* ``observed_at`` is the EDGAR **filing date** supplied by the submissions
  index -- the day the numbers became public. It is never "now": the module
  contains no call to ``datetime.now``/``pd.Timestamp.now``/``.today()``.
  ``parse`` accepts it explicitly; if it is omitted it falls back to the filing's
  own ``signatureDate`` (which matched the EDGAR filing date on every filing
  inspected); if neither exists it raises rather than defaulting to the clock. A
  filing whose ``observed_at`` precedes its ``valid_time`` is rejected, because
  a number cannot describe a period before that period began.
* *Liquidity selection.* N-MFP3 publishes a dated daily panel: the connector
  takes the block with the greatest ``totalLiquidAssetsNearPercentDate`` (the
  freshest snapshot in the month). N-MFP1/2 publish the same values positionally
  indexed by Friday: the connector takes the highest populated slot that the
  calendar says exists (the number of Fridays in the reporting month), which is
  the last Friday of the month and the freshest figure available. It never
  averages the five Fridays, because an average is a number the fund never
  reported.
* *Revision.* ``parse`` labels every row revision ``0``; ``fetch`` renumbers
  across the filings it collected: for each ``(entity_id, series_id,
  valid_time)`` the earliest ``observed_at`` gets ``0`` and each later distinct
  filing date gets the next integer. So an ``N-MFP2/A`` restating the same month
  is a new vintage with a higher revision, the way :class:`PITStore` expects.

Failure policy
--------------
Malformed XML, an unknown namespace, a missing ``submissionType`` / period end,
a missing registrant index or a non-numeric placeholder raises
:class:`~backend.exceptions.SchemaValidationError`. A well-formed filing that
yields no rows -- because the request scoped other entities, or because the
submissions index lists no N-MFP filing in the window -- is passed through
:func:`~backend.modules.data.connectors.base.validate_observation_frame`, which
raises :class:`~backend.exceptions.EmptyDatasetError`. Nothing is invented,
interpolated or forward-filled.

Known limitations
-----------------
* Discovery reads ``filings.recent`` only. Registrants with more than one
  ``filings.files`` chunk (very long histories) have older filings in those
  side files, which are not fetched. ``recent`` carried ~480 filings / 16 years
  for the largest fund inspected, so this is a long-tail limit, not a routine one.
* Repurchase-agreement collateral and security-level holdings are present in the
  XML but are not extracted; this module is the aggregate systemic-exposure feed.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any, List, Mapping, Optional, Sequence, Tuple

import pandas as pd

from backend.exceptions import SchemaValidationError
from ..pit import OBSERVATION_COLUMNS
from .base import (
    ConnectorSpec,
    DataConnector,
    FetchRequest,
    as_float,
    require,
    validate_observation_frame,
)

__all__ = [
    "SERIES_IDS",
    "SERIES_TOTAL_NET_ASSETS",
    "SERIES_WAM_DAYS",
    "SERIES_WAL_DAYS",
    "SERIES_DAILY_LIQUID_ASSETS",
    "SERIES_WEEKLY_LIQUID_ASSETS",
    "SERIES_DAILY_LIQUID_ASSETS_PCT",
    "SERIES_WEEKLY_LIQUID_ASSETS_PCT",
    "FilingRef",
    "SecNMfpConnector",
]

#: Connector key, used in messages and log lines.
_NAME = "sec_n_mfp"

#: The values written to ``Observation.series_id``. See the module docstring for
#: the unit each one carries.
SERIES_TOTAL_NET_ASSETS = "N-MFP:TOTAL_NET_ASSETS"
SERIES_WAM_DAYS = "N-MFP:WAM_DAYS"
SERIES_WAL_DAYS = "N-MFP:WAL_DAYS"
SERIES_DAILY_LIQUID_ASSETS = "N-MFP:DAILY_LIQUID_ASSETS"
SERIES_WEEKLY_LIQUID_ASSETS = "N-MFP:WEEKLY_LIQUID_ASSETS"
SERIES_DAILY_LIQUID_ASSETS_PCT = "N-MFP:DAILY_LIQUID_ASSETS_PCT"
SERIES_WEEKLY_LIQUID_ASSETS_PCT = "N-MFP:WEEKLY_LIQUID_ASSETS_PCT"

#: Every series this connector can emit, in a stable order.
SERIES_IDS: Tuple[str, ...] = (
    SERIES_TOTAL_NET_ASSETS,
    SERIES_WAM_DAYS,
    SERIES_WAL_DAYS,
    SERIES_DAILY_LIQUID_ASSETS,
    SERIES_WEEKLY_LIQUID_ASSETS,
    SERIES_DAILY_LIQUID_ASSETS_PCT,
    SERIES_WEEKLY_LIQUID_ASSETS_PCT,
)

#: EDGAR form types that carry an N-MFP submission. The base form is what
#: ``full-index``/``submissions`` report for amendments once the ``/A`` suffix is
#: stripped, so membership is tested on the base name.
N_MFP_FORMS = frozenset({"N-MFP", "N-MFP1", "N-MFP2", "N-MFP3"})

#: XML namespaces of the four observed N-MFP schemas.
SUPPORTED_NAMESPACES = frozenset(
    {
        "http://www.sec.gov/edgar/nmfp",
        "http://www.sec.gov/edgar/nmfp1",
        "http://www.sec.gov/edgar/nmfp2",
        "http://www.sec.gov/edgar/nmfp3",
    }
)

#: Per-registrant filing index. One registrant per request; ``fetch`` fans out.
SUBMISSIONS_ENDPOINT = "https://data.sec.gov/submissions/CIK{cik}.json"

#: Raw filing documents. ``cik_int`` has no leading zeros and ``accession`` has no
#: dashes -- that is EDGAR's archive layout, not a choice.
ARCHIVE_ENDPOINT = (
    "https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession}/{filename}"
)

#: Human landing page for the dataset.
SOURCE_URL = "https://www.sec.gov/edgar/searchedgar/companysearch"

#: Liquidity containers, in the order they are emitted. Each entry is
#: ``(tag, preferred friday prefixes, series_id)``. The preferred prefixes differ
#: by schema: N-MFP2 names daily children ``fridayDayN`` while N-MFP1 reuses
#: ``fridayWeekN`` inside the daily container, so both are tried in order.
_LIQUIDITY_FIELDS: Tuple[Tuple[str, Tuple[str, ...], str], ...] = (
    ("totalValueDailyLiquidAssets", ("fridayDay", "fridayWeek"), SERIES_DAILY_LIQUID_ASSETS),
    ("totalValueWeeklyLiquidAssets", ("fridayWeek", "fridayDay"), SERIES_WEEKLY_LIQUID_ASSETS),
    ("percentageDailyLiquidAssets", ("fridayDay", "fridayWeek"), SERIES_DAILY_LIQUID_ASSETS_PCT),
    ("percentageWeeklyLiquidAssets", ("fridayWeek", "fridayDay"), SERIES_WEEKLY_LIQUID_ASSETS_PCT),
)


@dataclass(frozen=True)
class FilingRef:
    """One N-MFP filing as described by the submissions index."""

    cik: str
    accession: str
    form: str
    filing_date: pd.Timestamp
    report_date: pd.Timestamp
    primary_document: str


def _local_name(tag: str) -> str:
    """``{ns}name`` -> ``name``; a bare name is returned unchanged."""
    return tag.rsplit("}", 1)[-1]


def _namespace_of(tag: str) -> str:
    """The namespace URI of a qualified ElementTree tag, or ``""``."""
    if tag.startswith("{"):
        return tag[1:].split("}", 1)[0]
    return ""


def _child(element: Optional[ET.Element], local: str) -> Optional[ET.Element]:
    """First *direct* child of ``element`` whose local name is ``local``."""
    if element is None:
        return None
    for candidate in list(element):
        if _local_name(candidate.tag) == local:
            return candidate
    return None


def _find_first(element: Optional[ET.Element], local: str) -> Optional[ET.Element]:
    """First descendant (document order) of ``element`` with local name ``local``."""
    if element is None:
        return None
    for candidate in element.iter():
        if _local_name(candidate.tag) == local:
            return candidate
    return None


def _text(element: Optional[ET.Element]) -> Optional[str]:
    """Stripped element text, or ``None`` for a missing/empty element."""
    if element is None or element.text is None:
        return None
    text = element.text.strip()
    return text or None


def _first_text(element: ET.Element, names: Sequence[str]) -> Optional[Tuple[str, str]]:
    """``(tag, text)`` for the first present, populated name in ``names``."""
    for name in names:
        text = _text(_find_first(element, name))
        if text is not None:
            return name, text
    return None


def _normalise_cik(value: object) -> str:
    """Coerce a CIK to EDGAR's 10-digit zero-padded form.

    Raises:
        SchemaValidationError: ``value`` holds no 1-10 digit CIK. Failing here is
            deliberate: a malformed CIK would otherwise build a valid-looking URL
            for a *different* registrant.
    """
    text = str(value).strip().upper()
    if text.startswith("CIK"):
        text = text[3:]
    digits = "".join(ch for ch in text if ch.isdigit())
    if not digits or len(digits) > 10 or digits != text:
        raise SchemaValidationError(
            f"{_NAME}: {value!r} is not a CIK",
            context={"connector": _NAME, "value": str(value)},
        )
    return digits.zfill(10)


def _is_n_mfp_form(form: str) -> bool:
    """Whether an EDGAR form type is one of the N-MFP family (amendment or not)."""
    return form.split("/", 1)[0].strip().upper() in N_MFP_FORMS


def _empty_frame() -> pd.DataFrame:
    """An empty frame carrying the observation column contract and dtypes."""
    frame = pd.DataFrame.from_records([], columns=list(OBSERVATION_COLUMNS))
    frame["valid_time"] = pd.to_datetime(frame["valid_time"])
    frame["observed_at"] = pd.to_datetime(frame["observed_at"])
    frame["value"] = frame["value"].astype("float64")
    frame["revision"] = frame["revision"].astype("int64")
    return frame


def _observations_frame(rows: Sequence[Mapping[str, Any]]) -> pd.DataFrame:
    """Build an observation frame from parsed rows, applying the column dtypes."""
    if not rows:
        return _empty_frame()
    frame = pd.DataFrame.from_records(list(rows), columns=list(OBSERVATION_COLUMNS))
    frame["valid_time"] = pd.to_datetime(frame["valid_time"])
    frame["observed_at"] = pd.to_datetime(frame["observed_at"])
    frame["value"] = frame["value"].astype("float64")
    frame["revision"] = frame["revision"].astype("int64")
    return frame


def _parse_xml(payload: Any) -> ET.Element:
    """Parse and sanity-check a filing payload.

    Raises:
        SchemaValidationError: The payload is not bytes/str, is not well-formed
            XML, or is not one of the N-MFP schemas. Failing closed on the
            namespace catches the ``xsl.../primary_doc.xml`` rendering, which is
            well-formed HTML and would otherwise parse into an empty result.
    """
    if isinstance(payload, str):
        data = payload.encode("utf-8")
    elif isinstance(payload, (bytes, bytearray)):
        data = bytes(payload)
    else:
        raise SchemaValidationError(
            f"{_NAME}: filing payload must be bytes, got {type(payload).__name__}",
            context={"connector": _NAME},
        )
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise SchemaValidationError(
            f"{_NAME}: filing is not well-formed XML",
            context={"connector": _NAME, "error": str(exc)},
            cause=exc,
        ) from exc

    namespace = _namespace_of(root.tag)
    if namespace not in SUPPORTED_NAMESPACES:
        raise SchemaValidationError(
            f"{_NAME}: not an N-MFP filing (unexpected XML namespace)",
            context={
                "connector": _NAME,
                "namespace": namespace,
                "supported": sorted(SUPPORTED_NAMESPACES),
            },
        )
    return root


def _friday_slots(report_date: pd.Timestamp) -> int:
    """How many Fridays the reporting calendar month contains (4 or 5).

    Form item A.13 keys its liquidity slots by Friday of the reporting month, so
    the calendar fixes how many slots are applicable; the trailing
    "(if applicable)" slot is a literal ``0.00`` filler on a four-Friday month in
    the filings inspected.
    """
    month_start = report_date.replace(day=1)
    month_end = month_start + pd.offsets.MonthEnd(0)
    return int(len(pd.date_range(month_start, month_end, freq="W-FRI")))


def _last_applicable_friday(
    container: ET.Element, slots: int, prefixes: Sequence[str], field: str
) -> float:
    """Highest populated Friday slot the calendar says exists.

    Empty slots are skipped -- the form authorises omitting a week it did not
    calculate -- but a slot that carries a non-numeric placeholder is handed to
    :func:`as_float`, which raises rather than coercing.

    Raises:
        SchemaValidationError: The container has no populated applicable slot.
    """
    for index in range(min(slots, 5), 0, -1):
        for prefix in prefixes:
            element = _child(container, f"{prefix}{index}")
            if element is not None and _text(element) is not None:
                return as_float(
                    _text(element),
                    field_name=f"{field}/{prefix}{index}",
                    connector=_NAME,
                )
    raise SchemaValidationError(
        f"{_NAME}: liquidity container has no populated Friday slot "
        f"for the reporting month",
        context={"connector": _NAME, "field": field, "slots": slots},
    )


def _extract_liquidity(
    series_level: ET.Element, report_date: pd.Timestamp
) -> Mapping[str, float]:
    """The four liquidity series for one filing, omitting what is not reported.

    Two shapes are handled, because EDGAR changed the form in 2024: N-MFP3's
    dated daily panel and N-MFP1/2's positional Friday containers. A schema that
    carries neither (original N-MFP) yields an empty mapping -- absence of a
    series, never a zero.
    """
    values: dict = {}

    daily_panel = [
        element
        for element in series_level.iter()
        if _local_name(element.tag) == "liquidAssetsDetails"
    ]
    if daily_panel:
        # N-MFP3: explicit dates, so "freshest" is unambiguous. Ties go to the
        # last block in document order, which is deterministic.
        chosen = None
        chosen_date = ""
        for element in daily_panel:
            date_text = _text(_child(element, "totalLiquidAssetsNearPercentDate")) or ""
            if chosen is None or date_text >= chosen_date:
                chosen, chosen_date = element, date_text
        assert chosen is not None  # the loop above always runs at least once
        for leaf, _prefixes, series_id in _LIQUIDITY_FIELDS:
            text = _text(_child(chosen, leaf))
            if text is not None:
                values[series_id] = as_float(text, field_name=leaf, connector=_NAME)
        return values

    slots = _friday_slots(report_date)
    for container_name, prefixes, series_id in _LIQUIDITY_FIELDS:
        container = _find_first(series_level, container_name)
        if container is None or len(list(container)) == 0:
            continue
        values[series_id] = _last_applicable_friday(
            container, slots, prefixes, container_name
        )
    return values


def _assign_revisions(frame: pd.DataFrame) -> pd.DataFrame:
    """Number vintages per ``(entity, series, valid_time)`` by filing date.

    The earliest distinct filing date gets ``0`` and every later distinct date
    gets the next integer, so an amendment is a new revision of the same period
    rather than a rewrite of the original vintage. Rows sharing a filing date
    keep the same revision.
    """
    if frame.empty:
        return frame
    keys = ["entity_id", "series_id", "valid_time"]
    distinct = frame.loc[:, keys + ["observed_at"]].drop_duplicates()
    distinct = distinct.sort_values(keys + ["observed_at"], kind="stable")
    distinct["revision"] = distinct.groupby(keys, sort=False).cumcount().astype("int64")
    # Drop the parser's placeholder revision first: merging onto a column of the
    # same name would silently become revision_x / revision_y.
    merged = frame.drop(columns=["revision"]).merge(
        distinct, on=keys + ["observed_at"], how="left"
    )
    return merged.loc[:, list(OBSERVATION_COLUMNS)]


class SecNMfpConnector(DataConnector):
    """Fetch SEC Form N-MFP money-market fund reports.

    Discovery is per registrant: EDGAR has no bulk N-MFP endpoint, so the caller
    names the CIKs to read in :attr:`FetchRequest.entity_ids`. ``fetch`` then
    walks each registrant's submissions index, downloads the raw
    ``primary_doc.xml`` for every N-MFP filing inside the requested period, and
    parses them offline.
    """

    accept = "application/json"

    @property
    def spec(self) -> ConnectorSpec:
        return ConnectorSpec(
            name=_NAME,
            kind="sec",
            # The real entity is the filing's seriesId; a fixed default would be
            # wrong, so the field names the source identifier instead.
            entity_id="seriesId",
            source_url=SOURCE_URL,
            endpoint=SUBMISSIONS_ENDPOINT,
            licence=(
                "US SEC EDGAR. Filings are US Government works and are not "
                "subject to copyright in the United States (17 U.S.C. 105); the "
                "SEC publishes EDGAR free to reuse. SEC requires a descriptive "
                "User-Agent and asks automated clients to stay under 10 "
                "requests per second. Verified 2026-09-11: anonymous GETs of "
                "data.sec.gov/submissions and www.sec.gov/Archives returned "
                "HTTP 200 with such a User-Agent."
            ),
            cadence="monthly",
            description=(
                "Monthly portfolio, maturity and liquidity position of US "
                "money-market funds from SEC Form N-MFP/N-MFP1/N-MFP2/N-MFP3."
            ),
            requires_credentials=False,
        )

    # -- URLs ---------------------------------------------------------------

    def build_url(self, request: FetchRequest) -> str:
        """The submissions-index URL for the single registrant in ``request``.

        EDGAR's index is per CIK, so this addresses exactly one registrant;
        :meth:`fetch` fans a multi-registrant request out into single-registrant
        requests rather than silently returning only the first.

        Raises:
            SchemaValidationError: ``request`` does not name exactly one CIK.
        """
        if len(request.entity_ids) != 1:
            raise SchemaValidationError(
                f"{_NAME}: exactly one registrant CIK is required, got "
                f"{len(request.entity_ids)}",
                context={"connector": _NAME, "entity_ids": list(request.entity_ids)},
            )
        return SUBMISSIONS_ENDPOINT.format(cik=_normalise_cik(request.entity_ids[0]))

    @staticmethod
    def build_document_url(cik: str, accession: str, primary_document: str) -> str:
        """Raw-XML archive URL for one filing.

        ``primary_document`` comes from the submissions index as a *rendered*
        path such as ``xslN-MFP2_X01/primary_doc.xml``; only its basename is kept,
        because the rendered copy is XHTML and the raw XML sits at the accession
        directory root.
        """
        normalized_accession = accession.replace("-", "").strip()
        if not normalized_accession:
            raise SchemaValidationError(
                f"{_NAME}: filing has no accession number",
                context={"connector": _NAME},
            )
        filename = primary_document.rsplit("/", 1)[-1].strip() or "primary_doc.xml"
        return ARCHIVE_ENDPOINT.format(
            cik_int=str(int(_normalise_cik(cik))),
            accession=normalized_accession,
            filename=filename,
        )

    # -- discovery ----------------------------------------------------------

    def parse_submissions(
        self, payload: Any, request: Optional[FetchRequest] = None
    ) -> List[FilingRef]:
        """Read an EDGAR submissions index into N-MFP filing references.

        Pure and offline. Filters to the N-MFP family and, when ``request``
        carries bounds, to filings whose ``reportDate`` (the described period)
        falls inside them.

        Raises:
            SchemaValidationError: The payload is not a submissions document, or
                a matched N-MFP entry is missing its accession, filing date or
                report date.
        """
        try:
            document = json.loads(payload)
        except (TypeError, ValueError) as exc:
            raise SchemaValidationError(
                f"{_NAME}: submissions index is not valid JSON",
                context={"connector": _NAME},
                cause=exc,
            ) from exc
        if not isinstance(document, dict):
            raise SchemaValidationError(
                f"{_NAME}: submissions index must be a JSON object",
                context={"connector": _NAME, "type": type(document).__name__},
            )

        filings = document.get("filings")
        if not isinstance(filings, dict) or not isinstance(
            filings.get("recent"), dict
        ):
            raise SchemaValidationError(
                f"{_NAME}: submissions index has no filings.recent block",
                context={"connector": _NAME},
            )
        recent = filings["recent"]

        required = (
            "accessionNumber",
            "form",
            "filingDate",
            "reportDate",
            "primaryDocument",
        )
        missing = [key for key in required if key not in recent]
        if missing:
            raise SchemaValidationError(
                f"{_NAME}: submissions index is missing required arrays",
                context={"connector": _NAME, "missing": missing},
            )
        lengths = {key: len(recent[key]) for key in required}
        if len(set(lengths.values())) != 1:
            raise SchemaValidationError(
                f"{_NAME}: submissions index parallel arrays differ in length",
                context={"connector": _NAME, "lengths": lengths},
            )

        fallback_cik: Optional[str] = None
        document_cik = document.get("cik")
        if document_cik is not None and str(document_cik).strip():
            fallback_cik = _normalise_cik(document_cik)
        elif request is not None and request.entity_ids:
            fallback_cik = _normalise_cik(request.entity_ids[0])

        references: List[FilingRef] = []
        for index in range(next(iter(lengths.values()))):
            form = str(recent["form"][index] or "").strip()
            if not _is_n_mfp_form(form):
                continue

            accession = str(recent["accessionNumber"][index] or "").strip()
            if not accession:
                raise SchemaValidationError(
                    f"{_NAME}: N-MFP index entry has no accession number",
                    context={"connector": _NAME, "index": index, "form": form},
                )

            report_text = str(recent["reportDate"][index] or "").strip()
            filing_text = str(recent["filingDate"][index] or "").strip()
            if not report_text or not filing_text:
                raise SchemaValidationError(
                    f"{_NAME}: N-MFP index entry is missing a date",
                    context={
                        "connector": _NAME,
                        "accession": accession,
                        "report_date": report_text,
                        "filing_date": filing_text,
                    },
                )
            try:
                report_date = pd.Timestamp(report_text)
                filing_date = pd.Timestamp(filing_text)
            except (TypeError, ValueError) as exc:
                raise SchemaValidationError(
                    f"{_NAME}: N-MFP index entry carries an unparseable date",
                    context={"connector": _NAME, "accession": accession},
                    cause=exc,
                ) from exc

            if request is not None and not request.covers(report_date):
                continue

            if fallback_cik is None:
                raise SchemaValidationError(
                    f"{_NAME}: submissions index has no registrant CIK",
                    context={"connector": _NAME, "accession": accession},
                )
            references.append(
                FilingRef(
                    cik=fallback_cik,
                    accession=accession,
                    form=form,
                    filing_date=filing_date,
                    report_date=report_date,
                    primary_document=(
                        str(recent["primaryDocument"][index] or "").strip()
                        or "primary_doc.xml"
                    ),
                )
            )
        return references

    # -- parsing ------------------------------------------------------------

    def parse(
        self,
        payload: Any,
        request: FetchRequest,
        *,
        observed_at: Optional[object] = None,
        accession: Optional[str] = None,
    ) -> pd.DataFrame:
        """Parse one ``primary_doc.xml`` into an observation frame. No I/O.

        Args:
            payload: Raw XML bytes (a ``str`` is accepted for tests).
            request: Scope. Used to filter the filing by registrant CIK and, for
                ``series_ids``, to filter the emitted series.
            observed_at: The EDGAR filing date. Passed by :meth:`fetch` from the
                submissions index, which is the authoritative "became public"
                instant. When omitted, the filing's own ``signatureDate`` is used
                if present. The current clock is never consulted -- a historical
                filing stamped "now" would be visible to every backtest.
            accession: Optional accession, used only in error context.

        Raises:
            SchemaValidationError: The payload is malformed, is not an N-MFP
                schema, omits its ``submissionType`` or period end, carries a
                non-numeric placeholder, supplies no usable numeric series, or
                is dated before the period it describes.
        """
        context: dict = {"connector": _NAME}
        if accession:
            context["accession"] = accession

        root = _parse_xml(payload)

        submission_type = _text(_find_first(root, "submissionType"))
        if submission_type is None or not _is_n_mfp_form(submission_type):
            raise SchemaValidationError(
                f"{_NAME}: submission is not a form N-MFP filing",
                context={**context, "submission_type": submission_type},
            )

        general = _find_first(root, "generalInfo")
        if general is not None:
            period_text = _text(_child(general, "reportDate"))
            cik_text = _text(_child(general, "cik"))
            series_text = _text(_child(general, "seriesId"))
        else:
            period_text = _text(_find_first(root, "DocumentPeriodEndDate"))
            cik_text = _text(_find_first(root, "EntityCentralIndexKey"))
            series_text = _text(_find_first(root, "seriesId"))
        if period_text is None:
            raise SchemaValidationError(
                f"{_NAME}: filing has no reporting-period end date",
                context=context,
            )
        try:
            valid_time = pd.Timestamp(period_text)
        except (TypeError, ValueError) as exc:
            raise SchemaValidationError(
                f"{_NAME}: reporting-period end date is unparseable",
                context={**context, "period_ending": period_text},
                cause=exc,
            ) from exc

        cik = _normalise_cik(cik_text) if cik_text else None

        # "Not mine" is not the same as "malformed": a filing outside the
        # requested registrants yields an empty frame, which
        # validate_observation_frame reports as EmptyDatasetError.
        if request.entity_ids and cik not in {
            _normalise_cik(entity) for entity in request.entity_ids
        }:
            return _empty_frame()

        if observed_at is not None:
            try:
                published_at = pd.Timestamp(observed_at)
            except (TypeError, ValueError) as exc:
                raise SchemaValidationError(
                    f"{_NAME}: observed_at is not a timestamp",
                    context={**context, "observed_at": str(observed_at)},
                    cause=exc,
                ) from exc
        else:
            signature_text = _text(_find_first(root, "signatureDate"))
            if signature_text is None:
                raise SchemaValidationError(
                    f"{_NAME}: filing has no publication date; pass the EDGAR "
                    "filing date as observed_at (the clock must not be used)",
                    context=context,
                )
            try:
                published_at = pd.Timestamp(signature_text)
            except (TypeError, ValueError) as exc:
                raise SchemaValidationError(
                    f"{_NAME}: signature date is unparseable",
                    context={**context, "signature_date": signature_text},
                    cause=exc,
                ) from exc

        require(
            published_at >= valid_time,
            f"{_NAME}: filing is dated before the period it describes",
            connector=_NAME,
            observed_at=str(published_at),
            valid_time=str(valid_time),
        )

        entity_id = series_text or (f"CIK{cik}" if cik else _NAME.upper())

        # Element truthiness depends on child count for ElementTree, so an empty
        # <seriesLevelInfo/> would be falsy; test for absence explicitly.
        series_level = _find_first(root, "seriesLevelInfo")
        if series_level is None:
            series_level = _find_first(root, "seriesLevelInformation")
        if series_level is None:
            raise SchemaValidationError(
                f"{_NAME}: filing has no series-level information block",
                context=context,
            )

        numeric_candidates: List[Tuple[str, Optional[Tuple[str, str]]]] = [
            (
                SERIES_TOTAL_NET_ASSETS,
                _first_text(series_level, ("netAssetOfSeries", "AssetsNet")),
            ),
            (
                SERIES_WAM_DAYS,
                _first_text(
                    series_level,
                    (
                        "averagePortfolioMaturity",
                        "dollarWeightedAveragePortfolioMaturity",
                    ),
                ),
            ),
            (
                SERIES_WAL_DAYS,
                _first_text(
                    series_level,
                    ("averageLifeMaturity", "dollarWeightedAverageLifeMaturity"),
                ),
            ),
        ]

        rows: List[dict] = []
        for series_id, candidate in numeric_candidates:
            if candidate is None:
                continue
            field_name, text = candidate
            rows.append(
                {
                    "entity_id": entity_id,
                    "series_id": series_id,
                    "valid_time": valid_time,
                    "observed_at": published_at,
                    "value": as_float(text, field_name=field_name, connector=_NAME),
                    "revision": 0,
                }
            )

        for series_id, value in _extract_liquidity(series_level, valid_time).items():
            rows.append(
                {
                    "entity_id": entity_id,
                    "series_id": series_id,
                    "valid_time": valid_time,
                    "observed_at": published_at,
                    "value": value,
                    "revision": 0,
                }
            )

        if not rows:
            raise SchemaValidationError(
                f"{_NAME}: filing carries no usable numeric series",
                context={**context, "entity_id": entity_id},
            )

        frame = _observations_frame(rows)
        if request.series_ids:
            frame = frame.loc[frame["series_id"].isin(request.series_ids)]
        return frame.reset_index(drop=True)

    # -- orchestration ------------------------------------------------------

    def fetch(self, request: Optional[FetchRequest] = None) -> pd.DataFrame:
        """Discover, download, parse and validate N-MFP filings.

        The base class fetches one URL; N-MFP needs an index then one document per
        filing, so this override performs that fan-out while keeping
        :meth:`parse` a pure single-document parser.

        Raises:
            SchemaValidationError: No registrant CIK was supplied.
            EmptyDatasetError: The window contains no N-MFP filing.
        """
        resolved = request or FetchRequest()
        if not resolved.entity_ids:
            raise SchemaValidationError(
                f"{_NAME}: FetchRequest.entity_ids must name at least one "
                "registrant CIK; EDGAR publishes N-MFP filings per registrant",
                context={"connector": _NAME},
            )

        frames: List[pd.DataFrame] = []
        for entity in resolved.entity_ids:
            scoped = FetchRequest(
                start=resolved.start,
                end=resolved.end,
                entity_ids=(entity,),
                series_ids=resolved.series_ids,
            )
            index_payload = self._client.get(
                self.build_url(scoped),
                accept="application/json",
                connector=_NAME,
            )
            for reference in self.parse_submissions(index_payload, scoped):
                document = self._client.get(
                    self.build_document_url(
                        reference.cik,
                        reference.accession,
                        reference.primary_document,
                    ),
                    accept="application/xml",
                    connector=_NAME,
                )
                frames.append(
                    self.parse(
                        document,
                        scoped,
                        observed_at=reference.filing_date,
                        accession=reference.accession,
                    )
                )

        non_empty = [frame for frame in frames if not frame.empty]
        combined = (
            pd.concat(non_empty, ignore_index=True) if non_empty else _empty_frame()
        )
        combined = _assign_revisions(combined)
        if resolved.series_ids:
            combined = combined.loc[combined["series_id"].isin(resolved.series_ids)]
        return validate_observation_frame(combined, connector=_NAME)
