"""Network graph and bilateral exposure upload API.

What this module serves
-----------------------

``GET /api/v1/network/graph`` returns the *current* multiplex network as JSON:
institution nodes with their exposure totals and an edge list carrying the
obligations themselves. The data comes from
:mod:`backend.services.bilateral_exposure_store`, which is the same store the
upload endpoint writes and the engine-facing reader
(``load_bank_exposures``) consumes. The graph is therefore a view of a real,
clearing-eligible obligation set, not of a rendering fixture.

``POST /api/v1/network/exposures`` accepts an institution's bilateral exposure
matrix (CSV or Parquet) and persists it through that store. Validation and the
security posture are documented on the store module; this module is the
transport.

Why REST and not WebSocket
--------------------------

The repository already runs a WebSocket (``jobs_ws.py``), but that channel is a
*job-progress* broadcast: its manager is wired to ``job_events`` and its
lifecycle is tied to job status changes. The exposure network is a snapshot that
changes only when an upload succeeds, so a client needs the current value on
demand and an explicit cache-invalidation signal, not a continuous stream.
Adding a second pub/sub channel to the job socket would duplicate that manager
and its lifecycle for no benefit, and the frontend's fetch helper is REST-based.
REST is therefore used. If push updates are wanted later, the existing job bus
can carry an invalidation event while this endpoint stays the snapshot reader.

Why the unavailable state is HTTP 200
-------------------------------------

"No network has been uploaded" is not an error: it is the truthful answer for a
fresh deployment, and the UI must be able to render it as a first-class state
("no exposure matrix yet") rather than as a failed request that invites a retry
loop. The response carries ``status: "unavailable"`` with a human-readable
``unavailable_reason`` and empty ``nodes``/``edges``; ``status: "available"``
always accompanies a real graph. A malformed or unreadable *stored* artefact is
a different thing and raises a typed error, so an empty graph can never hide a
broken one.

Why the upload is a raw body rather than multipart
--------------------------------------------------

FastAPI's ``UploadFile``/``File`` require ``python-multipart``, which is not a
declared dependency of this project. The endpoint accepts the file as the raw
request body and resolves the format from the ``format`` query parameter, an
``X-Filename`` header, or the request ``Content-Type``. This keeps the upload
free of an undeclared runtime dependency and lets the byte ceiling be enforced
against the actual stream rather than a client-supplied multipart header.

Geography is deliberately not served here
-----------------------------------------

The node ids are institutions. Geographic placement (region boundaries, base
map, region coordinates) is *reference* data and legitimately static; exposure
is *live* data and must not be. Serving region coordinates from the backend
would mean copying the frontend's region table into the API, where it would
drift. The response records this split in
``metadata.geography_resolution = "client_reference_data"``.

Authentication
--------------

This router applies the same dependency convention as every other route in the
application: there is no authentication layer. The upload endpoint can therefore
be called by anyone who can reach the API, and that is a real exposure of the
network data. It must stay on a trusted network until an auth layer exists; no
alternative scheme is invented here.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, Query, Request, status

from backend.modules.engine.multiplex import build_interbank_exposure_layer
from backend.services.bilateral_exposure_store import (
    ExposureEmptyError,
    ExposureUploadTooLargeError,
    UnsupportedExposureFormatError,
    BilateralExposureStore,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Content types that unambiguously identify one supported format. A generic
# ``application/octet-stream`` is not in this table: guessing a format from an
# opaque body is how a Parquet file gets fed to the CSV reader and reported as a
# schema error rather than a format error.
_CONTENT_TYPE_FORMATS: Dict[str, str] = {
    "text/csv": "csv",
    "application/csv": "csv",
    "application/vnd.apache.parquet": "parquet",
    "application/x-parquet": "parquet",
}

_SUFFIX_FORMATS: Dict[str, str] = {
    ".csv": "csv",
    ".parquet": "parquet",
    ".pq": "parquet",
}


def get_bilateral_exposure_store() -> BilateralExposureStore:
    """FastAPI dependency for the exposure store.

    Mirrors ``get_db``: the router depends on an abstract store rather than
    reaching for a module-level singleton, which is what lets tests point it at
    a temporary directory without monkeypatching the filesystem layout.
    """
    return BilateralExposureStore()


async def _read_limited_body(request: Request, max_bytes: int) -> bytes:
    """Read the request body, aborting once it exceeds ``max_bytes``.

    ``Content-Length`` is checked first when present so an obviously oversized
    upload is refused before any of it is buffered, but it is not trusted on its
    own: the stream is counted as it arrives, so a chunked or lying client
    cannot get past the ceiling.
    """
    declared = request.headers.get("content-length")
    if declared is not None:
        try:
            if int(declared) > max_bytes:
                raise ExposureUploadTooLargeError(
                    f"the uploaded matrix declares {declared} bytes, above the "
                    f"{max_bytes} byte ceiling",
                    context={"declared_bytes": int(declared), "max_bytes": int(max_bytes)},
                )
        except ValueError:
            # A non-numeric Content-Length is not itself a reason to reject;
            # the streaming count below is authoritative.
            pass

    chunks = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > max_bytes:
            raise ExposureUploadTooLargeError(
                f"the uploaded matrix exceeded the {max_bytes} byte ceiling "
                "while being read",
                context={"max_bytes": int(max_bytes)},
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _resolve_format(
    request: Request, explicit: Optional[str], filename: Optional[str]
) -> str:
    """Resolve the payload format, refusing to guess when it is ambiguous."""
    if explicit:
        candidate = explicit.strip().lower().lstrip(".")
        if candidate in ("csv", "parquet"):
            return candidate
        raise UnsupportedExposureFormatError(
            f"unsupported format {explicit!r}; supported formats are ['csv', 'parquet']",
            context={"format": explicit},
        )

    header = request.headers.get("x-filename")
    for candidate in (filename, header):
        if candidate:
            suffix = "." + str(candidate).rsplit(".", 1)[-1].lower() if "." in str(candidate) else ""
            if suffix in _SUFFIX_FORMATS:
                return _SUFFIX_FORMATS[suffix]

    content_type = (request.headers.get("content-type") or "").split(";")[0].strip().lower()
    if content_type in _CONTENT_TYPE_FORMATS:
        return _CONTENT_TYPE_FORMATS[content_type]

    raise UnsupportedExposureFormatError(
        "the exposure matrix format could not be determined; pass ?format=csv or "
        "?format=parquet, an X-Filename header, or a recognised Content-Type",
        context={"content_type": content_type or None},
    )


def _graph_from_frame(
    frame: pd.DataFrame,
    manifest: Dict[str, Any],
) -> Dict[str, Any]:
    """Build the node/edge/layer payload from a stored matrix.

    The layer is constructed with the same
    :func:`~backend.modules.engine.multiplex.build_interbank_exposure_layer`
    the engine uses, so the graph cannot describe a matrix the clearing path
    would refuse (for example, one with a negative cell). The edge set is read
    off that layer's adjacency, which is also what clearing consumes.
    """
    node_ids = sorted(
        {str(value) for value in frame["debtor"]}
        | {str(value) for value in frame["creditor"]}
    )

    # The vintage is metadata, not a filtering key: the store already refused
    # multiple or future vintages, so the frame is one instant. The 'as_of'
    # column is dropped before building because the multiplex filter expects a
    # comparable timestamp and the manifest already carries the authoritative
    # value.
    declared_as_of = manifest.get("as_of")
    build_as_of = pd.Timestamp(declared_as_of) if declared_as_of else pd.Timestamp.now()
    build_frame = frame.drop(columns=["as_of"], errors="ignore")
    layer = build_interbank_exposure_layer(
        build_frame, node_ids, as_of=build_as_of, name="interbank"
    )

    matrix = layer.adjacency
    gross_liabilities = matrix.sum(axis=1)
    gross_claims = matrix.sum(axis=0)
    out_degree = (matrix > 0).sum(axis=1)
    in_degree = (matrix > 0).sum(axis=0)

    nodes = [
        {
            "id": node_id,
            "name": node_id,
            "gross_liabilities": float(gross_liabilities[position]),
            "gross_claims": float(gross_claims[position]),
            "out_degree": int(out_degree[position]),
            "in_degree": int(in_degree[position]),
            # The exposure matrix carries no risk score. Reporting null is the
            # honest answer; inventing one from network position would present
            # a model output that was never computed.
            "risk_score": None,
        }
        for position, node_id in enumerate(node_ids)
    ]

    edges = [
        {
            "id": f"{node_ids[debtor]}->{node_ids[creditor]}",
            "source": node_ids[debtor],
            "target": node_ids[creditor],
            "exposure": float(matrix[debtor, creditor]),
            "layer": layer.name,
            "kind": layer.kind.value,
            "directed": bool(layer.directed),
            "is_clearing_eligible": bool(layer.is_clearing_eligible),
            "risk_score": None,
        }
        for debtor, creditor in zip(*np.nonzero(matrix))
        if debtor != creditor
    ]

    return {
        "status": "available",
        "as_of": declared_as_of,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": "bilateral_exposure_store",
        "unavailable_reason": None,
        "nodes": nodes,
        "edges": edges,
        "layers": [layer.to_dict()],
        "metadata": {
            "n_nodes": len(node_ids),
            "n_edges": int(layer.metadata.get("n_edges", len(edges))),
            "gross_notional": float(matrix.sum()),
            "source_institution": manifest.get("source_institution"),
            "content_hash": manifest.get("content_hash"),
            "uploaded_at": manifest.get("uploaded_at"),
            "duplicate_edges_aggregated": manifest.get("duplicate_edges_aggregated", 0),
            "geography_resolution": "client_reference_data",
            "risk_score_available": False,
        },
    }


@router.get("/graph", response_model=Dict[str, Any])
async def get_network_graph(
    store: BilateralExposureStore = Depends(get_bilateral_exposure_store),
) -> Dict[str, Any]:
    """Return the current multiplex network graph, or an explicit unavailable state.

    Response shape (``status: "available"``)::

        {
          "status": "available",
          "as_of": "<ISO vintage or null>",
          "generated_at": "<ISO>",
          "source": "bilateral_exposure_store",
          "unavailable_reason": null,
          "nodes": [{"id", "name", "gross_liabilities", "gross_claims",
                     "out_degree", "in_degree", "risk_score"}],
          "edges": [{"id", "source", "target", "exposure", "layer", "kind",
                     "directed", "is_clearing_eligible", "risk_score"}],
          "layers": [{"name", "kind", "as_of", "directed", "n_nodes",
                      "density", "is_clearing_eligible", "metadata"}],
          "metadata": {"n_nodes", "n_edges", "gross_notional",
                       "source_institution", "content_hash", "uploaded_at",
                       "duplicate_edges_aggregated", "geography_resolution",
                       "risk_score_available"}
        }

    When nothing has been uploaded the same keys are present with
    ``status: "unavailable"``, empty ``nodes``/``edges``/``layers`` and a
    populated ``unavailable_reason``.
    """
    frame = store.load()
    if frame is None:
        return {
            "status": "unavailable",
            "as_of": None,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "source": "bilateral_exposure_store",
            "unavailable_reason": (
                "no bilateral exposure matrix has been uploaded; the interbank "
                "network is unavailable rather than assumed"
            ),
            "nodes": [],
            "edges": [],
            "layers": [],
            "metadata": {
                "n_nodes": 0,
                "n_edges": 0,
                "gross_notional": None,
                "source_institution": None,
                "content_hash": None,
                "uploaded_at": None,
                "duplicate_edges_aggregated": 0,
                "geography_resolution": "client_reference_data",
                "risk_score_available": False,
            },
        }

    manifest = store.manifest() or {}
    return _graph_from_frame(frame, manifest)


@router.post(
    "/exposures",
    response_model=Dict[str, Any],
    status_code=status.HTTP_201_CREATED,
)
async def upload_bilateral_exposures(
    request: Request,
    source_institution: str = Query(
        ...,
        min_length=1,
        description="Institution supplying the matrix; recorded for attribution.",
    ),
    as_of: Optional[str] = Query(
        None,
        description=(
            "ISO vintage for the matrix. Only used when the payload has no "
            "'as_of' column; if both are present they must agree."
        ),
    ),
    data_format: Optional[str] = Query(
        None,
        alias="format",
        description="Payload format: csv or parquet. Inferred from X-Filename/Content-Type if omitted.",
    ),
    filename: Optional[str] = Query(
        None, description="Optional original filename, used only to infer the format."
    ),
    store: BilateralExposureStore = Depends(get_bilateral_exposure_store),
) -> Dict[str, Any]:
    """Accept and persist a bilateral exposure matrix.

    The body is the file itself. Validation is delegated to
    :class:`~backend.services.bilateral_exposure_store.BilateralExposureStore`;
    every rejection is a typed error from that module and is rendered by the
    application's ``BeaconError`` handler.

    Response (201)::

        {
          "status": "stored",
          "source_institution": "...",
          "as_of": "<ISO or null>",
          "uploaded_at": "<ISO>",
          "format": "csv" | "parquet",
          "content_hash": "sha256:...",
          "n_rows": <int>, "n_edges": <int>, "n_institutions": <int>,
          "gross_notional": <float>,
          "duplicate_edges_aggregated": <int>,
          "duplicate_pairs": [["debtor", "creditor"], ...],
          "institutions": ["..."],
          "columns": ["debtor", "creditor", "amount"]
        }
    """
    content = await _read_limited_body(request, store.max_upload_bytes)
    resolved_format = _resolve_format(request, data_format, filename)
    if not content:
        raise ExposureEmptyError(
            "the uploaded bilateral exposure matrix is empty",
            context={"format": resolved_format},
        )

    manifest = store.ingest(
        content,
        data_format=resolved_format,
        source_institution=source_institution,
        as_of=as_of,
    )
    return {"status": "stored", **manifest}
