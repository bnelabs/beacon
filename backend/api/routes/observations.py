"""Point-in-time reads of indicator observations.

The vintage log (``indicator_vintage_log``) has recorded every publication since
the migration that created it, and ``TimeSeriesStore.observations_as_of`` has
known how to read it since the same change -- with nothing on the other end of
either. The reachability census recorded the reader as tested and uncalled, which
is the polite way of saying the feature could not be used.

This route is the caller, and it keeps the contract the network graph already
establishes for as-of answers:

* a malformed timestamp is a typed 422 that names the value it could not read;
* nothing known at that instant is HTTP 200 with ``status: "unavailable"`` and a
  reason -- **never** the current values. ``indicator_observations`` is the
  latest-value store, and reaching for it under an ``as_of`` would answer every
  historical question with today's belief, which is the exact look-ahead the
  vintage log exists to prevent;
* every row states *why* its publication instant is what it is
  (``publication_basis``): the capture instant of a certified snapshot, this
  deployment's ingest instant, or ``unknown`` for rows written before provenance
  existed -- with the counts of each, so an answer never rests on a provenance
  its reader cannot see;
* truncation is reported (``truncated``, ``vintages_at_or_before_as_of``) rather
  than discoverable only by noticing that a series looks short.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models.timeseries import IndicatorVintageLog
from backend.modules.results.timeseries_store import (
    CERTIFIED_SNAPSHOT_BASIS,
    INGEST_INSTANT_BASIS,
    UNKNOWN_BASIS,
    TimeSeriesStore,
)

logger = logging.getLogger(__name__)

# No prefix and no tags here, matching the other 22 route modules: ``main.py``
# mounts every router with its own prefix and tag, and a router that smuggled
# its own would be the one place where the API's path layout is decided twice.
router = APIRouter()

DEFAULT_LIMIT = 500
MAX_LIMIT = 5000

#: The answer an operator gets when nothing was known, and why the current
#: values are not offered instead.
NO_SUBSTITUTION = (
    "the latest-value store is not substituted for history: it holds what is "
    "believed now, not what was known then"
)


def _parse_stamp(value: str, name: str) -> datetime:
    """An ISO 8601 timestamp, or a 422 that quotes the value it could not read.

    A naive timestamp is read as UTC, which is the convention the collector, the
    validator and the point-in-time store already state; leaving it naive would
    make the cut-off depend on the server's local clock.
    """
    try:
        stamp = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"{name} {value!r} is not a valid ISO 8601 timestamp",
        ) from exc
    if stamp.tzinfo is None:
        return stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def _iso(stamp: Optional[datetime]) -> Optional[str]:
    """Serialize a timestamp without pretending a naive one is local time.

    SQLite returns these columns naive; the convention across this backend is
    that a naive stored stamp is UTC, and the response must carry that reading
    rather than leave it to the client to guess.
    """
    if stamp is None:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc).isoformat()


def _basis_of(row: IndicatorVintageLog) -> str:
    basis = (row.publication_basis or "").strip()
    if basis in {INGEST_INSTANT_BASIS, CERTIFIED_SNAPSHOT_BASIS}:
        return basis
    return UNKNOWN_BASIS


def _row_payload(row: IndicatorVintageLog) -> Dict[str, Any]:
    return {
        "time": _iso(row.time),
        "value": float(row.value),
        "region": row.region,
        "published_at": _iso(row.published_at),
        "publication_basis": _basis_of(row),
        "snapshot_id": row.snapshot_id,
        "ingest_job_id": row.ingest_job_id,
    }


def _unavailable(
    *,
    source_code: str,
    indicator_code: str,
    region: Optional[str],
    as_of: datetime,
    reason: str,
) -> Dict[str, Any]:
    """Every key the available response carries is present here too.

    A client must not be able to tell the two apart by shape alone and pick the
    wrong one; an unavailable answer is a fact about the past, not an empty
    series to plot.
    """
    return {
        "status": "unavailable",
        "source_code": source_code,
        "indicator_code": indicator_code,
        "region": region,
        "as_of": as_of.isoformat(),
        "unavailable_reason": f"{reason} ({NO_SUBSTITUTION})",
        "observations": [],
        "count": 0,
        "vintages_at_or_before_as_of": 0,
        "provenance_coverage": {
            CERTIFIED_SNAPSHOT_BASIS: 0,
            INGEST_INSTANT_BASIS: 0,
            UNKNOWN_BASIS: 0,
        },
        "limit": None,
        "truncated": False,
    }


@router.get("/as-of", response_model=Dict[str, Any])
def get_observations_as_of(
    source_code: str = Query(
        ...,
        min_length=1,
        description="Publisher identity, e.g. the plugin type of the data source.",
    ),
    indicator_code: str = Query(..., min_length=1, description="Catalogue indicator code."),
    as_of: str = Query(
        ...,
        description=(
            "Instant to answer as of (ISO 8601). Only vintages published at or "
            "before it are considered; a restatement published later is invisible "
            "here by construction."
        ),
    ),
    region: Optional[str] = Query(default=None, description="Restrict to one region."),
    valid_from: Optional[str] = Query(
        default=None,
        description="Earliest reporting period to return. Does not move the cut-off.",
    ),
    valid_to: Optional[str] = Query(
        default=None,
        description="Latest reporting period to return. Does not move the cut-off.",
    ),
    limit: int = Query(
        default=DEFAULT_LIMIT,
        ge=1,
        le=MAX_LIMIT,
        description="Maximum periods to return. Truncation is reported, not hidden.",
    ),
    db: Session = Depends(get_db),
):
    """The indicator series as this deployment knew it at ``as_of``."""
    as_of_stamp = _parse_stamp(as_of, "as_of")
    window_from = _parse_stamp(valid_from, "valid_from") if valid_from is not None else None
    window_to = _parse_stamp(valid_to, "valid_to") if valid_to is not None else None

    if window_from is not None and window_to is not None and window_from > window_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"valid_from {valid_from!r} is after valid_to {valid_to!r}; "
                "the requested period window is empty by construction"
            ),
        )

    store = TimeSeriesStore(db)
    rows = store.observations_as_of(
        source_code,
        indicator_code,
        as_of_stamp,
        region,
        valid_from=window_from,
        valid_to=window_to,
    )

    series = f"{source_code}/{indicator_code}" + (f" ({region})" if region else "")
    if not rows:
        reason = (
            f"no vintage of {series} was published to this deployment at or before "
            f"{as_of_stamp.isoformat()}"
        )
        logger.info("As-of observation read unavailable: %s", reason)
        return _unavailable(
            source_code=source_code,
            indicator_code=indicator_code,
            region=region,
            as_of=as_of_stamp,
            reason=reason,
        )

    coverage: Dict[str, int] = {
        CERTIFIED_SNAPSHOT_BASIS: 0,
        INGEST_INSTANT_BASIS: 0,
        UNKNOWN_BASIS: 0,
    }
    for row in rows:
        coverage[_basis_of(row)] += 1

    truncated = len(rows) > limit
    page = rows[:limit]

    return {
        "status": "available",
        "source_code": source_code,
        "indicator_code": indicator_code,
        "region": region,
        "as_of": as_of_stamp.isoformat(),
        "observations": [_row_payload(row) for row in page],
        "count": len(page),
        "vintages_at_or_before_as_of": len(rows),
        "provenance_coverage": coverage,
        "limit": limit,
        "truncated": truncated,
    }
