"""ECB Central Counterparty Clearing Statistics (the CPMI-IOSCO CCP PQDs).

What this feed is
-----------------
``CCP`` is the ECB Data Portal dataflow "Central Counterparty Clearing
Statistics" (DSD ``ECB:ECB_CCP1``). It carries the European leg of the
CPMI-IOSCO *public quantitative disclosures* for central counterparties: the
number of clearing members (participants) and the volume and value of the
contracts each CCP clears, broken down by instrument, counterparty country and
currency. It is annual, covers 2006 onward, and is the only public
cross-CCP panel of its kind for European clearing houses.

Everything below was verified against the live service on 2026-09-11 with
``curl -H "User-Agent: BNELabs-BEACON/1.0 (research; bne@bnelabs.dev)"``:

* ``GET /service/data/CCP/all?format=csvdata`` -> HTTP 200, 29,388,030 bytes,
  88,160 data rows, 20 reference years (2006-2025).
* ``GET /service/dataflow/ECB/CCP`` -> HTTP 200; name "Central Counterparty
  Clearing Statistics"; structure ``ECB_CCP1``.
* ``GET /service/datastructure/ECB/ECB_CCP1`` -> HTTP 200; dimensions
  ``FREQ, CCP_SYSTEM, SSS_INFO_TYPE, SSS_INSTRUMENT, COUNT_AREA, SSS_SYSTEM,
  CURRENCY_TRANS, SERIES_DENOM`` plus ``TIME_PERIOD``. ``UNIT`` and
  ``UNIT_MULT`` are *series-level attributes*, not dimensions.
* ``GET /service/codelist/ECB/CL_SSS_INFO_TYPE`` (and 12 further codelists)
  -> HTTP 200. Meanings quoted below are taken verbatim from those files.
* ``GET https://data.ecb.europa.eu/data/datasets/CCP/data-information`` -> the
  ECB's own statement, quoted below, that the data are annual, that clearing
  member counts refer to the last day of the year, and that publication happens
  6-7 months after the reference year ends.

The CSV columns are exactly, in order::

    KEY,FREQ,CCP_SYSTEM,SSS_INFO_TYPE,SSS_INSTRUMENT,COUNT_AREA,SSS_SYSTEM,
    CURRENCY_TRANS,SERIES_DENOM,TIME_PERIOD,OBS_VALUE,OBS_STATUS,OBS_CONF,
    OBS_PRE_BREAK,OBS_COM,TIME_FORMAT,COLLECTION,COMPILING_ORG,DISS_ORG,
    PUBL_ECB,PUBL_MU,PUBL_PUBLIC,DECIMALS,SOURCE_AGENCY,TITLE,TITLE_COMPL,
    UNIT,UNIT_MULT

Verified code meanings (from the ECB codelists, never guessed)
--------------------------------------------------------------
``SSS_INFO_TYPE`` -- the ECB's ``CL_SSS_INFO_TYPE`` holds ~110 codes because it
is shared with the CSD dataflow. The codes actually present in the ``CCP``
dataflow were enumerated from the live download and are recorded in
:data:`INFO_TYPE_LABELS` together with their codelist names. They are the
participant counts (``D00``-``D5T``, e.g. ``D0T`` = "Total participants",
``D01`` = "Total participants - central counterparty (CCP)") and the
transaction measures (``OUT`` = "Outright", ``REP`` = "Repo",
``LNK`` = "Transactions through a clearing link", ``NTC`` = "Non-OTC
transactions", ``OTC`` = "OTC transactions", ``ST0``-``ST2`` = securities
transfers).

``OBS_STATUS`` -- from ``CL_OBS_STATUS``: ``A`` = "Normal value", ``L`` =
"Missing value; data exist but were not collected", ``M`` = "Missing value;
data cannot exist". In this dataset the mapping is *exact*: across all 88,160
rows, :data:`OBS_VALUE` is non-empty on precisely the 43,880 ``A`` rows and
empty on precisely the 17,082 ``L`` plus 27,198 ``M`` rows. Empty is therefore
a labelled missing value, never a zero.

``UNIT_MULT`` -- from ``CL_UNIT_MULT`` (``0`` = Units, ``1`` = Tens, ``3`` =
Thousands, ``6`` = Millions, ...). Importantly, this connector does **not**
apply it. The codelist code ``1`` on the participant series would imply a x10
scale, but the published values are plainly counts: for ``AT1``/``D03``/2006 the
raw value 51 is consistent with the sibling breakdown (``D0T`` = 66) and with
the ``GB1`` total of 117-171 clearing members over 2006-2019 -- multiplying by
ten is impossible. The raw ``OBS_VALUE`` is therefore emitted verbatim and
``UNIT``/``UNIT_MULT`` are carried inside the ``series_id`` so a consumer can
apply (or ignore) the scale itself. Applying a multiplier we cannot defend
would fabricate numbers, which the base contract forbids.

``SERIES_DENOM`` -- this dimension, not ``UNIT``, is what separates the two
measures that share a key otherwise: from ``CL_SERIES_DENOM``, ``Q`` =
"Quantity" (transaction counts, ``UNIT=PURE_NUMB``) and ``E`` = "Euro"
(notional amounts, ``UNIT=EUR``). ``N`` = "National currency" also appears and
is published as ``UNIT=PURE_NUMB``. Handling only "CCP x info type x
instrument x frequency" would silently mix counts with euro notional: in the
live data 9,791 of 16,832 such groups contain more than one row for the same
year, usually the ``Q``/``E`` pair. The ``series_id`` therefore carries the
full coded dimension set.

Series key convention
---------------------
Every coded dimension plus the unit metadata, in a fixed order that starts
with the reporting CCP, as a self-describing colon-delimited key::

    ECB:CCP:ccp=AT1:info=D00:instr=Z:area=X0:sss=ZZZ:cur=Z0Z:denom=Q:unit=PURE_NUMB:mult=1:freq=A

``info`` is the ``SSS_INFO_TYPE`` code, ``instr`` the ``SSS_INSTRUMENT`` code,
``area`` the ``COUNT_AREA`` code, ``sss`` the ``SSS_SYSTEM`` code, ``cur`` the
``CURRENCY_TRANS`` code, ``denom`` the ``SERIES_DENOM`` code, and ``freq`` the
``FREQ`` code. ``TITLE`` travels alongside as a human-readable ``label`` column
but never enters the key: titles are prose, get edited, and are not unique.

The full dimension tuple ``(FREQ, CCP_SYSTEM, SSS_INFO_TYPE, SSS_INSTRUMENT,
COUNT_AREA, SSS_SYSTEM, CURRENCY_TRANS, SERIES_DENOM, TIME_PERIOD)`` was
verified to be unique over all 88,160 live rows, with zero conflicting values,
so the key above (plus ``valid_time``) is a genuine primary key.

Time conventions
----------------
``valid_time`` is the **end** of the reference year: the annual observation
labelled ``2025`` becomes ``2025-12-31``. The ECB's own data-information page
states "The number of clearing members refers to the last day of the year", so
period-end is the stated measurement instant, not an arbitrary choice; it is
also the latest instant the value can describe, which is the conservative
choice for a point-in-time store.

``observed_at`` is the publication instant. **The SDMX CSV feed carries no
per-observation publication date** -- there is no revision, release or
valid-from field on any of the 28 columns, and the SDMX dataflow metadata
carries no ``ValidFrom``. The ECB's data-information page does state that "The
data are published 6-7 months after the end of the reference year", and the
Data Portal's dataset page carried "Last updated: 30 Jun 2025" for the 2024
reference year (6 months, i.e. 181 days). Because the CSV offers no date, this
connector applies a documented lag constant, :data:`DEFAULT_PUBLICATION_LAG_DAYS`
= 212 days (7 months, the late end of the ECB's own stated window) and marks it
as an assumption. The late bound is deliberate: a too-early ``observed_at``
would let a backtest see a value before it was actually published, while a
too-late one merely delays visibility. The constant is overridable through the
constructor. ``observed_at`` is always strictly after ``valid_time`` (any
non-negative lag satisfies this), and the current time is never used.

``revision`` is always ``0``. The feed publishes only the latest vintage of
each series: it exposes no revision counter, no ``OBS_PRE_BREAK`` markers
(empty on all 88,160 rows) and no vintage history. Restatements are therefore
indistinguishable from first prints here, and inventing a revision number would
be exactly the kind of fabrication the pipeline forbids. A revision-aware
ingest needs a different source (for example repeated portal snapshots).

Failure policy
--------------
:meth:`EcbCcpConnector.parse` performs no I/O. It fails closed with
:class:`~backend.exceptions.SchemaValidationError` on a missing column, a
non-annual ``TIME_PERIOD``/``FREQ``, an unparseable number, or a duplicate
series key carrying a conflicting value; and with
:class:`~backend.exceptions.EmptyDatasetError` when the payload holds no rows
at all or *every* row was skipped for an empty ``OBS_VALUE``. Empty values are
skipped and counted -- never turned into zero.
"""

from __future__ import annotations

import csv
import io
import logging
import re
from typing import Dict, List, Mapping, Optional
from urllib.parse import urlencode

import pandas as pd

from backend.exceptions import EmptyDatasetError, SchemaValidationError
from ..pit import OBSERVATION_COLUMNS
from .base import ConnectorSpec, DataConnector, FetchRequest, HttpClient, as_float

logger = logging.getLogger(__name__)

__all__ = [
    "EcbCcpConnector",
    "INFO_TYPE_LABELS",
    "DEFAULT_PUBLICATION_LAG_DAYS",
]

#: Dataflow identifier inside the ECB Data Portal's SDMX service.
DATASET_ID = "CCP"

#: Human-facing dataset landing page (verified HTTP 200 on 2026-09-11).
SOURCE_URL = "https://data.ecb.europa.eu/data/datasets/CCP"

#: Machine endpoint, without the query string. ``all`` asks for every series.
ENDPOINT = "https://data-api.ecb.europa.eu/service/data/CCP/all"

#: The ECB serves CSV when the ``format`` parameter is set and ``Accept:
#: text/csv`` is sent. ``Accept: application/vnd.sdmx.data+csv`` was tested and
#: returns HTTP 406, so the plain media type is used.
ACCEPT = "text/csv"

#: Frequency code this connector accepts. The dataset is annual and its
#: ``TIME_PERIOD`` is a bare year; anything else cannot be mapped to a year-end
#: ``valid_time`` unambiguously, so it is rejected rather than guessed.
ANNUAL_FREQ = "A"

_YEAR_RE = re.compile(r"^\d{4}$")

#: Dimension codes must be safe to splice into the ``series_id`` key format.
_CODE_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")

#: Publication lag, in days, applied to every observation's ``valid_time`` to
#: obtain ``observed_at``. An ASSUMPTION: the ECB states the CCP statistics are
#: published "6-7 months after the end of the reference year" but the CSV feed
#: exposes no per-observation release date, so a constant is the honest option.
#: 212 days is the late end (7 months) of that window, chosen so a point-in-time
#: query can never expose a value earlier than it could have been published.
#: Overridable via ``EcbCcpConnector(publication_lag_days=...)``.
DEFAULT_PUBLICATION_LAG_DAYS = 212

#: Columns ``parse`` reads. A payload missing any of them is rejected: a silent
#: absent column would otherwise surface as empty strings and quietly drop data.
REQUIRED_COLUMNS: tuple[str, ...] = (
    "FREQ",
    "CCP_SYSTEM",
    "SSS_INFO_TYPE",
    "SSS_INSTRUMENT",
    "COUNT_AREA",
    "SSS_SYSTEM",
    "CURRENCY_TRANS",
    "SERIES_DENOM",
    "TIME_PERIOD",
    "OBS_VALUE",
    "OBS_STATUS",
    "TITLE",
    "UNIT",
    "UNIT_MULT",
)

#: ``series_id`` components, in the order they appear in the key. Each entry is
#: ``(label, csv column)``. The order is intentionally not the raw DSD order:
#: the CCP leads and the frequency trails, so the key reads from the entity
#: outward and matches the documented example in the module docstring.
_SERIES_ID_PARTS: tuple[tuple[str, str], ...] = (
    ("ccp", "CCP_SYSTEM"),
    ("info", "SSS_INFO_TYPE"),
    ("instr", "SSS_INSTRUMENT"),
    ("area", "COUNT_AREA"),
    ("sss", "SSS_SYSTEM"),
    ("cur", "CURRENCY_TRANS"),
    ("denom", "SERIES_DENOM"),
    ("unit", "UNIT"),
    ("mult", "UNIT_MULT"),
    ("freq", "FREQ"),
)

#: Human-readable ``SSS_INFO_TYPE`` names, transcribed verbatim from the ECB
#: codelist ``CL_SSS_INFO_TYPE``. Only the codes actually observed in the
#: ``CCP`` dataflow are listed; the shared codelist holds many more used by the
#: CSD dataflow. This dictionary exists to document the codes in code. The
#: connector does not key on it -- ``TITLE`` is the label it carries.
INFO_TYPE_LABELS: Mapping[str, str] = {
    "D00": "Total participants - central bank",
    "D01": "Total participants - central counterparty (CCP)",
    "D03": "Total participants - credit institution",
    "D04": "Total participants - other",
    "D0T": "Total participants",
    "D10": "Domestic participants - central bank",
    "D11": "Domestic participants - central counterparty (CCP)",
    "D13": "Domestic participants - credit institution",
    "D14": "Domestic participants - other",
    "D1T": "Domestic participants",
    "D30": "Non-domestic EU participants - central bank",
    "D31": "Non-domestic EU participants - central counterparty (CCP)",
    "D33": "Non-domestic EU participants - credit institution",
    "D34": "Non-domestic EU participants - other",
    "D3T": "Non-domestic EU participants",
    "D40": "Non-domestic non-EU participants - central bank",
    "D41": "Non-domestic non-EU participants - central counterparty (CCP)",
    "D43": "Non-domestic non-EU participants - credit institution",
    "D44": "Non-domestic non-EU participants - other",
    "D4T": "Non-domestic non-EU participants",
    "D50": (
        "Domestic participants - branches of entities registered abroad, "
        "central bank"
    ),
    "D51": (
        "Domestic participants - branches of entities registered abroad, "
        "central counterparty (CCP)"
    ),
    "D53": (
        "Domestic participants - branches of entities registered abroad, "
        "credit institution"
    ),
    "D54": (
        "Domestic participants - branches of entities registered abroad, other"
    ),
    "D5T": "Domestic participants - branches of entities registered abroad",
    "LNK": "Transactions through a clearing link",
    "NTC": "Non-OTC transactions",
    "OTC": "OTC transactions",
    "OUT": "Outright",
    "REP": "Repo",
    "ST0": "Securities transfers from CSD account to another CSD account",
    "ST1": "Securities transfers from CCP to/from clearing member",
    "ST2": "Securities transfers from clearing member to clearing member",
}

#: Licence text, quoted from the ECB's own reuse policy page (verified
#: 2026-09-11): "All publicly available ESCB statistics may be reused free of
#: charge on the condition that the source is quoted ... and that the
#: statistics (including metadata) are not modified."
LICENCE = (
    "ESCB statistics: free access and free reuse. 'All publicly available ESCB "
    "statistics may be reused free of charge on the condition that the source "
    "is quoted (e.g. \"Source: ECB statistics.\") and that the statistics "
    "(including metadata) are not modified.' The right of free reuse does not "
    "extend to third-party data. Source: ECB, 'Policy regarding the reuse of "
    "ESCB statistics', "
    "https://www.ecb.europa.eu/stats/ecb_statistics/governance_and_quality_"
    "framework/html/usage_policy.en.html"
)


class EcbCcpConnector(DataConnector):
    """Connector for the ECB Central Counterparty Clearing Statistics dataflow.

    Args:
        client: Shared retrying HTTP client. Injectable so tests stay offline.
        publication_lag_days: Days added to each observation's ``valid_time`` to
            obtain ``observed_at``. Defaults to
            :data:`DEFAULT_PUBLICATION_LAG_DAYS`; see the module docstring for
            why a constant is used and why the late end of the ECB's stated
            window is the default. Must be a non-negative integer.

    Attributes:
        last_skipped_empty: Number of rows skipped by the most recent
            :meth:`parse` call because ``OBS_VALUE`` was empty. Reset on every
            call, so a caller can record how much of a batch was missing.
        last_skipped_status_counts: ``OBS_STATUS`` -> count for exactly those
            skipped rows (``L`` = "data exist but were not collected", ``M`` =
            "data cannot exist"), which distinguishes "not collected yet" from
            "impossible" without changing the emitted frame.
        last_labels: ``series_id`` -> ``TITLE`` for the most recent
            :meth:`parse` call. ``fetch``/``load`` trim the frame back to the
            six-column observation schema, which drops the parse-level
            ``label`` column, so this keeps the human-readable name reachable
            after storage without putting prose into the series key.
    """

    accept = ACCEPT

    def __init__(
        self,
        client: Optional[HttpClient] = None,
        *,
        publication_lag_days: int = DEFAULT_PUBLICATION_LAG_DAYS,
    ) -> None:
        super().__init__(client)
        if isinstance(publication_lag_days, bool) or not isinstance(
            publication_lag_days, int
        ):
            raise ValueError(
                "publication_lag_days must be an integer, got "
                f"{publication_lag_days!r}"
            )
        if publication_lag_days < 0:
            raise ValueError(
                "publication_lag_days must be non-negative, got "
                f"{publication_lag_days!r}"
            )
        self._publication_lag_days = int(publication_lag_days)
        self.last_skipped_empty = 0
        self.last_skipped_status_counts: Dict[str, int] = {}
        self.last_labels: Dict[str, str] = {}

    @property
    def publication_lag_days(self) -> int:
        """Days between a reference year's end and its assumed publication."""
        return self._publication_lag_days

    @property
    def spec(self) -> ConnectorSpec:
        """Static description. ``entity_id`` names the reporting-entity column.

        There is no single default entity here -- every CCP is its own entity --
        so the field records the source dimension name, ``CCP_SYSTEM``, from
        which each row's ``entity_id`` is taken.
        """
        return ConnectorSpec(
            name="ecb_ccp",
            kind="ecb",
            entity_id="CCP_SYSTEM",
            source_url=SOURCE_URL,
            endpoint=ENDPOINT,
            licence=LICENCE,
            cadence="annual",
            description=(
                "Annual CPMI-IOSCO public quantitative disclosures for central "
                "counterparties: clearing-member counts and per-instrument "
                "cleared transaction volumes and values."
            ),
            requires_credentials=False,
        )

    def build_url(self, request: FetchRequest) -> str:
        """Return the SDMX CSV URL for ``request``.

        ``start``/``end`` are ``valid_time`` bounds, and every ``valid_time`` in
        this feed is a year end, so the year of each bound is the exact
        ``startPeriod``/``endPeriod`` to send: year ``Y`` yields ``Y-12-31``, so
        ``Y >= start.year`` and ``Y <= end.year`` are the inclusive integer
        equivalents. :meth:`parse` still applies the exact timestamp bounds, so
        a mid-year bound is honoured precisely even though the request over-
        fetches at year granularity.
        """
        params: Dict[str, str] = {"format": "csvdata"}
        if request.start is not None:
            params["startPeriod"] = f"{request.start.year:04d}"
        if request.end is not None:
            params["endPeriod"] = f"{request.end.year:04d}"
        return f"{ENDPOINT}?{urlencode(params)}"

    def parse(self, payload: bytes, request: FetchRequest) -> pd.DataFrame:
        """Parse an SDMX CSV body into an observation frame. No network I/O.

        Returns a frame with :data:`~backend.modules.data.pit.OBSERVATION_COLUMNS`
        plus a human-readable ``label`` column carrying ``TITLE``. The base
        validator trims the frame back to the six core columns in
        :meth:`~backend.modules.data.connectors.base.DataConnector.fetch`, so
        storage is unaffected; the label survives for parse-level consumers.

        Raises:
            SchemaValidationError: The payload is not decodable UTF-8/CSV, a
                required column is missing, ``FREQ`` is not annual,
                ``TIME_PERIOD`` is not a four-digit year, ``OBS_VALUE`` is a
                non-numeric placeholder, or a series key repeats with a
                conflicting value within one ``valid_time``.
            EmptyDatasetError: The payload has no data rows, or every row was
                skipped for an empty ``OBS_VALUE``.
        """
        connector = self.spec.name
        text = self._decode(payload)
        if text.strip() == "":
            raise EmptyDatasetError(
                f"{connector} returned an empty response body",
                context={"connector": connector},
            )

        reader = csv.DictReader(io.StringIO(text))
        fieldnames: List[str] = list(reader.fieldnames or [])
        if not fieldnames:
            raise SchemaValidationError(
                f"{connector} CSV has no header row",
                context={"connector": connector},
            )
        missing = [column for column in REQUIRED_COLUMNS if column not in fieldnames]
        if missing:
            raise SchemaValidationError(
                f"{connector} CSV is missing required columns",
                context={
                    "connector": connector,
                    "missing": missing,
                    "present": fieldnames,
                },
            )

        records: List[Dict[str, object]] = []
        labels: Dict[str, str] = {}
        seen: Dict[tuple, float] = {}
        skipped_empty = 0
        skipped_by_status: Dict[str, int] = {}

        for line_number, row in enumerate(reader, start=2):
            freq = self._field(row, "FREQ")
            if freq != ANNUAL_FREQ:
                raise SchemaValidationError(
                    f"{connector} expected annual frequency {ANNUAL_FREQ!r}, "
                    f"got {freq!r}",
                    context={
                        "connector": connector,
                        "line": line_number,
                        "FREQ": freq,
                    },
                )

            period = self._field(row, "TIME_PERIOD")
            if not _YEAR_RE.fullmatch(period):
                raise SchemaValidationError(
                    f"{connector} TIME_PERIOD {period!r} is not an annual "
                    "'YYYY' period",
                    context={
                        "connector": connector,
                        "line": line_number,
                        "TIME_PERIOD": period,
                    },
                )
            # End of the reference year: the ECB states clearing-member counts
            # refer to the last day of the year, and year-end is the latest
            # instant the annual figure can describe.
            valid_time = pd.Timestamp(year=int(period), month=12, day=31)

            raw_value = self._field(row, "OBS_VALUE")
            if raw_value == "":
                # A labelled missing value (OBS_STATUS L or M), common in this
                # dataset. It is not zero and must not become one.
                status = self._field(row, "OBS_STATUS") or "<empty>"
                skipped_empty += 1
                skipped_by_status[status] = skipped_by_status.get(status, 0) + 1
                continue

            series_id = self._series_id(row, connector, line_number)
            if not request.covers(valid_time):
                continue
            if request.entity_ids and self._field(row, "CCP_SYSTEM") not in (
                request.entity_ids
            ):
                continue
            if request.series_ids and series_id not in request.series_ids:
                continue

            value = as_float(raw_value, field_name="OBS_VALUE", connector=connector)
            key = (series_id, valid_time)
            if key in seen:
                if seen[key] != value:
                    raise SchemaValidationError(
                        f"{connector} carries the same series key and period "
                        "with two different values",
                        context={
                            "connector": connector,
                            "line": line_number,
                            "series_id": series_id,
                            "valid_time": str(valid_time),
                            "values": [seen[key], value],
                        },
                    )
                continue  # an exact repeat; drop it rather than duplicate a key
            seen[key] = value
            title = self._field(row, "TITLE")
            labels[series_id] = title

            records.append(
                {
                    "entity_id": self._field(row, "CCP_SYSTEM"),
                    "series_id": series_id,
                    "valid_time": valid_time,
                    "observed_at": valid_time
                    + pd.Timedelta(self._publication_lag_days, unit="D"),
                    "value": value,
                    # This feed publishes only the latest vintage and exposes no
                    # revision counter, so every observation is a first print.
                    "revision": 0,
                    "label": title,
                }
            )

        self.last_skipped_empty = skipped_empty
        self.last_skipped_status_counts = dict(skipped_by_status)
        self.last_labels = labels

        if not records:
            raise EmptyDatasetError(
                f"{connector} produced no observations: all {skipped_empty} "
                "row(s) carried an empty OBS_VALUE",
                context={
                    "connector": connector,
                    "skipped_empty": skipped_empty,
                    "status_counts": skipped_by_status,
                },
            )

        logger.debug(
            "%s: emitted %d observation(s), skipped %d empty OBS_VALUE row(s) %s",
            connector,
            len(records),
            skipped_empty,
            skipped_by_status,
        )

        frame = pd.DataFrame.from_records(
            records, columns=list(OBSERVATION_COLUMNS) + ["label"]
        )
        frame["valid_time"] = pd.to_datetime(frame["valid_time"])
        frame["observed_at"] = pd.to_datetime(frame["observed_at"])
        frame["value"] = frame["value"].astype("float64")
        frame["revision"] = frame["revision"].astype("int64")
        return frame.sort_values(
            ["valid_time", "series_id", "entity_id"], kind="stable"
        ).reset_index(drop=True)

    @staticmethod
    def _field(row: Mapping[str, object], column: str) -> str:
        """One CSV cell as a stripped string; ``None``/absent becomes ``""``."""
        value = row.get(column)
        return "" if value is None else str(value).strip()

    @classmethod
    def _series_id(
        cls, row: Mapping[str, object], connector: str, line_number: int
    ) -> str:
        """Build the self-describing series key from the coded dimensions.

        Raises:
            SchemaValidationError: A dimension code is empty or contains a
                character that would make the key ambiguous -- a key that
                cannot be split back into its parts is not self-describing.
        """
        parts: List[str] = ["ECB:CCP"]
        for label, column in _SERIES_ID_PARTS:
            code = cls._field(row, column)
            if not _CODE_RE.fullmatch(code):
                raise SchemaValidationError(
                    f"{connector} dimension {column} has an unusable code "
                    f"{code!r}; series keys must be self-describing",
                    context={
                        "connector": connector,
                        "line": line_number,
                        "column": column,
                        "code": code,
                    },
                )
            parts.append(f"{label}={code}")
        return ":".join(parts)

    @staticmethod
    def _decode(payload: object) -> str:
        """Decode the response body to text, rejecting anything unexpected.

        ``utf-8-sig`` strips a byte-order mark the ECB occasionally emits, which
        would otherwise turn the first column name into ``"\\ufeffKEY"`` and
        defeat every column lookup.
        """
        if isinstance(payload, str):
            return payload
        if isinstance(payload, (bytes, bytearray)):
            try:
                return bytes(payload).decode("utf-8-sig")
            except UnicodeDecodeError as exc:
                raise SchemaValidationError(
                    "ECB CCP response is not valid UTF-8",
                    context={"connector": "ecb_ccp"},
                    cause=exc,
                ) from exc
        raise SchemaValidationError(
            "ECB CCP payload must be bytes, got "
            f"{type(payload).__name__}",
            context={"connector": "ecb_ccp"},
        )
