"""Connectors for the non-bank and market-infrastructure sources.

The plan's Phase 0 names five feeds the pipeline did not have: SEC N-MFP
(money-market fund portfolios), BIS total credit (private credit), ECB central
counterparty clearing statistics (the CPMI-IOSCO public quantitative
disclosures), Fedwire and TARGET2 payment-system volumes, and SEC Form PF.

Four are served by public APIs and are implemented beside this module. Form PF is
not, and cannot be: it is confidential by statute and reaches the SEC under a
regime that does not permit public redistribution. That feed is therefore
represented by :mod:`backend.modules.data.connectors.sec_form_pf`, which fails
closed and documents the restricted path rather than pretending to fetch it.

The contract every connector honours
------------------------------------
1. **One schema.** :meth:`DataConnector.fetch` returns an *observation frame* --
   exactly :data:`~backend.modules.data.pit.OBSERVATION_COLUMNS` -- so the result
   drops straight into a :class:`~backend.modules.data.pit.PITStore` with no
   per-source adapter.

2. **Two clocks, never conflated.** ``valid_time`` is the period a number
   *describes*; ``observed_at`` is when the source *published* it. Collapsing them
   is what makes a backtest silently clairvoyant, so the distinction is enforced
   in :func:`validate_observation_frame` rather than left to reviewers.

3. **Fails closed.** An unreachable source, an unexpected schema, or an empty
   result raises a typed :class:`~backend.exceptions.BeaconError` subclass with a
   stable ``code``. No connector invents, interpolates, forward-fills or
   back-fills a value to plug a hole. A gap is a gap.

4. **Declares itself.** Every connector carries a :class:`ConnectorSpec` naming its
   licence and terms. BIS, ECB and SEC each attach different conditions to
   redistribution, and a reader must be able to see which applies without leaving
   the code.

5. **Separates I/O from parsing.** :meth:`DataConnector.parse` does no network I/O,
   so the suite tests every parser against recorded payloads and stays offline.

6. **Identifies itself to the source.** Every request carries a descriptive
   ``User-Agent``. SEC returns 403 without one, and all three publishers ask to be
   told who is calling.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple

import numpy as np
import pandas as pd
import requests

from backend.exceptions import (
    DataIngestionError,
    DataSourceUnavailableError,
    EmptyDatasetError,
    SchemaValidationError,
)
from ..pit import OBSERVATION_COLUMNS, Observation, PITStore

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_USER_AGENT",
    "ConnectorSpec",
    "FetchRequest",
    "ConnectorReport",
    "HttpClient",
    "DataConnector",
    "validate_observation_frame",
    "frame_to_observations",
]

#: SEC requires a descriptive User-Agent with contact details and returns 403
#: without one. The same string is correct for BIS and the ECB, both of which ask
#: callers to identify themselves.
DEFAULT_USER_AGENT = "BNELabs-BEACON/1.0 (research; +https://bnelabs.dev; bne@bnelabs.dev)"

DEFAULT_TIMEOUT = 60.0
DEFAULT_RETRIES = 4
DEFAULT_BACKOFF = 1.6
MAX_BACKOFF = 30.0

#: Status codes worth retrying: the request may succeed unchanged later.
RETRYABLE_STATUS = frozenset({429, 500, 502, 503, 504})


@dataclass(frozen=True)
class ConnectorSpec:
    """What a connector reads, and on what terms.

    Attributes:
        name: Stable connector key, e.g. ``"sec_n_mfp"``.
        kind: Source family -- ``"sec"``, ``"bis"`` or ``"ecb"``.
        entity_id: Value written to ``Observation.entity_id`` by default. This is
            the *reporting* entity (a fund, a country, a CCP), not the reader.
        source_url: Human-facing landing page for the dataset.
        endpoint: Machine endpoint the connector calls, without the key.
        licence: Redistribution terms, quoted from the publisher's own policy.
        cadence: Publication frequency, which bounds how stale a value can be.
        description: One sentence on what the feed measures.
        requires_credentials: ``True`` when the connector cannot work anonymously.
    """

    name: str
    kind: str
    entity_id: str
    source_url: str
    endpoint: str
    licence: str
    cadence: str
    description: str
    requires_credentials: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "entity_id": self.entity_id,
            "source_url": self.source_url,
            "endpoint": self.endpoint,
            "licence": self.licence,
            "cadence": self.cadence,
            "description": self.description,
            "requires_credentials": self.requires_credentials,
        }


@dataclass(frozen=True)
class FetchRequest:
    """Time window and entity scope for one fetch.

    ``start`` and ``end`` are inclusive bounds on ``valid_time``. Both are
    optional: a connector with no bound asks for everything the source will give,
    which is the right default for a first snapshot but not for a routine refresh.
    """

    start: Optional[pd.Timestamp] = None
    end: Optional[pd.Timestamp] = None
    entity_ids: Tuple[str, ...] = ()
    series_ids: Tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in ("start", "end"):
            value = getattr(self, field_name)
            if value is None:
                continue
            try:
                normalised = pd.Timestamp(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"{field_name} must be a timestamp, got {value!r}"
                ) from exc
            if normalised.tzinfo is not None:
                normalised = normalised.tz_convert("UTC").tz_localize(None)
            object.__setattr__(self, field_name, normalised)
        if self.start is not None and self.end is not None and self.end < self.start:
            raise ValueError(
                f"end must not precede start (start={self.start!r}, end={self.end!r})"
            )
        object.__setattr__(self, "entity_ids", tuple(str(e) for e in self.entity_ids))
        object.__setattr__(self, "series_ids", tuple(str(s) for s in self.series_ids))

    def covers(self, valid_time: pd.Timestamp) -> bool:
        """Whether ``valid_time`` falls inside the requested window."""
        if self.start is not None and valid_time < self.start:
            return False
        if self.end is not None and valid_time > self.end:
            return False
        return True


@dataclass
class ConnectorReport:
    """Outcome of one :meth:`DataConnector.load` call."""

    connector: str
    fetched: int = 0
    added: int = 0
    series: Tuple[str, ...] = ()
    entities: Tuple[str, ...] = ()
    first_valid_time: Optional[pd.Timestamp] = None
    last_valid_time: Optional[pd.Timestamp] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "connector": self.connector,
            "fetched": int(self.fetched),
            "added": int(self.added),
            "series": list(self.series),
            "entities": list(self.entities),
            "first_valid_time": (
                None if self.first_valid_time is None else str(self.first_valid_time)
            ),
            "last_valid_time": (
                None if self.last_valid_time is None else str(self.last_valid_time)
            ),
        }


class HttpClient:
    """A small retrying HTTP client shared by the connectors.

    Retries only what is safe to retry. A 5xx, a 429 or a transport error may
    succeed unchanged on a second attempt; a 400 or a 404 will not, and retrying
    it burns the publisher's quota and ours. ``Retry-After`` is respected verbatim
    when a source sends it, because both BIS and SEC throttle by IP.

    The ``sleep`` hook is injectable so tests exercise the retry path without
    actually waiting.
    """

    def __init__(
        self,
        *,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout: float = DEFAULT_TIMEOUT,
        retries: int = DEFAULT_RETRIES,
        backoff: float = DEFAULT_BACKOFF,
        sleep=time.sleep,
        session: Optional[requests.Session] = None,
    ) -> None:
        if retries < 0:
            raise ValueError(f"retries must be non-negative, got {retries}")
        if timeout <= 0:
            raise ValueError(f"timeout must be positive, got {timeout}")
        self.user_agent = user_agent
        self.timeout = float(timeout)
        self.retries = int(retries)
        self.backoff = float(backoff)
        self._sleep = sleep
        self._session = session or requests.Session()

    def _headers(self, accept: Optional[str]) -> Dict[str, str]:
        headers = {"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"}
        if accept:
            headers["Accept"] = accept
        return headers

    def get(
        self,
        url: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        accept: Optional[str] = None,
        connector: str = "connector",
    ) -> bytes:
        """Fetch ``url``, retrying transient failures, and return the body.

        Raises:
            DataSourceUnavailableError: The source could not be reached, refused
                the request, or kept failing past the retry budget.
        """
        # The URL is logged, never the body and never any header: an API key in a
        # header or query string must not reach the log.
        safe_url = url.split("?")[0]
        last_error: Optional[BaseException] = None

        for attempt in range(self.retries + 1):
            try:
                response = self._session.get(
                    url,
                    params=params,
                    headers=self._headers(accept),
                    timeout=self.timeout,
                )
            except requests.RequestException as exc:
                last_error = exc
                if attempt >= self.retries:
                    break
                self._wait(attempt, None)
                continue

            if response.status_code in RETRYABLE_STATUS and attempt < self.retries:
                logger.warning(
                    "%s: %s returned %s, retrying (%d/%d)",
                    connector,
                    safe_url,
                    response.status_code,
                    attempt + 1,
                    self.retries,
                )
                self._wait(attempt, response.headers.get("Retry-After"))
                continue

            if response.status_code >= 400:
                raise DataSourceUnavailableError(
                    f"{connector} request failed with HTTP {response.status_code}",
                    context={"url": safe_url, "status": response.status_code},
                )

            return response.content

        raise DataSourceUnavailableError(
            f"{connector} could not reach the source after {self.retries + 1} attempts",
            context={"url": safe_url},
            cause=last_error,
        )

    def _wait(self, attempt: int, retry_after: Optional[str]) -> None:
        delay = min(self.backoff**attempt, MAX_BACKOFF)
        if retry_after:
            try:
                delay = max(delay, float(retry_after))
            except (TypeError, ValueError):
                pass
        self._sleep(min(delay, MAX_BACKOFF))


class DataConnector(ABC):
    """Base class: fetch raw bytes, parse them into the observation schema.

    Subclasses implement :meth:`build_url` and :meth:`parse`. ``parse`` takes the
    raw payload and returns a frame, and performs no I/O, which is what lets the
    tests run the real parsers against recorded fixtures with no network.
    """

    #: Media type the source should return; sent as ``Accept``.
    accept: str = "application/json"

    def __init__(self, client: Optional[HttpClient] = None) -> None:
        self._client = client or HttpClient()

    @property
    @abstractmethod
    def spec(self) -> ConnectorSpec:
        """Static description of this connector."""

    @abstractmethod
    def build_url(self, request: FetchRequest) -> str:
        """Absolute URL for ``request``, without credentials."""

    @abstractmethod
    def parse(self, payload: bytes, request: FetchRequest) -> pd.DataFrame:
        """Parse a raw response into an observation frame. Performs no I/O."""

    def fetch(self, request: Optional[FetchRequest] = None) -> pd.DataFrame:
        """Retrieve and validate one batch of observations."""
        resolved = request or FetchRequest()
        url = self.build_url(resolved)
        payload = self._client.get(url, accept=self.accept, connector=self.spec.name)
        frame = self.parse(payload, resolved)
        return validate_observation_frame(frame, connector=self.spec.name)

    def load(
        self, store: PITStore, request: Optional[FetchRequest] = None
    ) -> ConnectorReport:
        """Fetch a batch and append it to ``store``.

        Idempotent: :class:`PITStore` de-duplicates identical re-appends, so a
        refresh that overlaps a previous window adds nothing twice. ``added``
        therefore reports what was genuinely new.
        """
        frame = self.fetch(request)
        added = store.append(frame_to_observations(frame))
        return ConnectorReport(
            connector=self.spec.name,
            fetched=int(frame.shape[0]),
            added=int(added),
            series=tuple(sorted(frame["series_id"].unique())) if len(frame) else (),
            entities=(
                tuple(sorted(frame["entity_id"].unique())) if len(frame) else ()
            ),
            first_valid_time=(
                pd.Timestamp(frame["valid_time"].min()) if len(frame) else None
            ),
            last_valid_time=(
                pd.Timestamp(frame["valid_time"].max()) if len(frame) else None
            ),
        )


def validate_observation_frame(
    frame: Any, *, connector: str = "connector"
) -> pd.DataFrame:
    """Coerce and check a connector's output against the observation schema.

    Enforces the two-clock rule and finiteness here, once, rather than in each
    connector: a parser that returns ``observed_at < valid_time`` has produced a
    value that could not have been known when it claims to describe, and that is
    the single most damaging class of bug in a point-in-time pipeline.

    Raises:
        SchemaValidationError: Columns are missing, a value is non-finite, an
            ``observed_at`` precedes its ``valid_time``, or a ``revision`` is
            negative.
        EmptyDatasetError: The frame carries no rows.
    """
    if not isinstance(frame, pd.DataFrame):
        raise SchemaValidationError(
            f"{connector} parser must return a DataFrame, got {type(frame).__name__}"
        )

    missing = [c for c in OBSERVATION_COLUMNS if c not in frame.columns]
    if missing:
        raise SchemaValidationError(
            f"{connector} output is missing required columns",
            context={"missing": missing, "present": list(frame.columns)},
        )
    if frame.empty:
        raise EmptyDatasetError(
            f"{connector} returned no rows for the requested scope",
            context={"connector": connector},
        )

    clean = frame.loc[:, list(OBSERVATION_COLUMNS)].copy()
    clean["valid_time"] = pd.to_datetime(clean["valid_time"])
    clean["observed_at"] = pd.to_datetime(clean["observed_at"])
    clean["value"] = pd.to_numeric(clean["value"], errors="coerce").astype("float64")
    clean["revision"] = pd.to_numeric(clean["revision"], errors="coerce")

    if clean["value"].isna().any():
        bad = int(clean["value"].isna().sum())
        raise SchemaValidationError(
            f"{connector} produced {bad} unparseable value(s)",
            context={"connector": connector, "count": bad},
        )
    if not np.isfinite(clean["value"].to_numpy()).all():
        raise SchemaValidationError(
            f"{connector} produced non-finite values",
            context={"connector": connector},
        )
    if clean["revision"].isna().any():
        raise SchemaValidationError(
            f"{connector} produced missing revision labels",
            context={"connector": connector},
        )
    clean["revision"] = clean["revision"].astype("int64")
    if (clean["revision"] < 0).any():
        raise SchemaValidationError(
            f"{connector} produced negative revisions",
            context={"connector": connector},
        )
    if (clean["observed_at"] < clean["valid_time"]).any():
        offenders = clean.loc[
            clean["observed_at"] < clean["valid_time"], "series_id"
        ].unique()[:5]
        raise SchemaValidationError(
            f"{connector} produced observations known before they were valid",
            context={"connector": connector, "series": [str(s) for s in offenders]},
        )

    return clean.sort_values(
        ["valid_time", "series_id", "entity_id"], kind="stable"
    ).reset_index(drop=True)


def frame_to_observations(frame: pd.DataFrame) -> List[Observation]:
    """Convert a validated observation frame into :class:`Observation` objects."""
    return [
        Observation(
            entity_id=row["entity_id"],
            series_id=row["series_id"],
            valid_time=row["valid_time"],
            observed_at=row["observed_at"],
            value=float(row["value"]),
            revision=int(row["revision"]),
        )
        for row in frame.to_dict("records")
    ]


def as_float(value: Any, *, field_name: str, connector: str) -> float:
    """Parse a source number, rejecting the placeholders sources actually emit.

    Statistical publishers write ``".."``, ``"-"``, ``"c"`` and ``""`` for
    "not available", "nil", "confidential" and "missing". Those are *not* zero and
    must not become zero, so they raise instead of coercing.
    """
    if value is None:
        raise SchemaValidationError(
            f"{connector}: {field_name} is absent",
            context={"connector": connector, "field": field_name},
        )
    if isinstance(value, (int, float, np.integer, np.floating)) and not isinstance(
        value, bool
    ):
        numeric = float(value)
    else:
        text = str(value).strip()
        if text in ("", "..", ".", "-", "c", "C", "n/a", "N/A", "NA", "null", "None"):
            raise SchemaValidationError(
                f"{connector}: {field_name} carries a non-numeric placeholder",
                context={"connector": connector, "field": field_name, "value": text},
            )
        try:
            numeric = float(text)
        except ValueError as exc:
            raise SchemaValidationError(
                f"{connector}: {field_name} is not numeric",
                context={"connector": connector, "field": field_name, "value": text},
            ) from exc
    if not np.isfinite(numeric):
        raise SchemaValidationError(
            f"{connector}: {field_name} is not finite",
            context={"connector": connector, "field": field_name},
        )
    return numeric


def require(condition: bool, message: str, **context: Any) -> None:
    """Raise :class:`SchemaValidationError` unless ``condition`` holds."""
    if not condition:
        raise SchemaValidationError(message, context=context or None)
