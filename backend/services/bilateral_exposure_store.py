"""Secure persistence for institution-supplied bilateral exposure matrices.

Why this module exists
----------------------

The risk map used to draw interbank arcs from a bundled JavaScript fixture
(``frontend/src/data/network-connections.js``). Demoing a network is not the
same as *having* one: the fixture's exposures were invented, they never changed,
and nothing downstream could clear against them because they were strings in a
browser bundle rather than obligations the engine could read. Interbank
exposures re-price daily; the map has to be fed from what the institution
actually owes.

This module is the storage boundary between an uploaded bipartite matrix and the
engine. It is deliberately the *only* place that decides whether an exposure
matrix is admissible, so the upload endpoint, the graph endpoint and any future
engine caller cannot disagree about what "valid" means.

The canonical form
------------------

A matrix is a frame of ``debtor``, ``creditor``, ``amount`` rows, optionally
dated by an ``as_of`` column. Columns are matched case-insensitively after
stripping surrounding whitespace. ``amount`` is a *magnitude*: direction is
carried by which column names the debtor, exactly as in
:mod:`backend.modules.engine.multiplex`. A negative amount is therefore not
"money owed the other way", it is a malformed row, and it is rejected rather
than reinterpreted.

Duplicate ``(debtor, creditor)`` rows are **aggregated by summing**, not
rejected. Two loans between the same pair are an ordinary economic situation,
and the engine already treats multiple contracts as additive
(:func:`~backend.modules.engine.multiplex.build_interbank_exposure_layer` sums
into the same matrix cell). Rejecting them would make the endpoint unusable for
real books; silently collapsing them would hide a data-quality signal. The
choice made here is to sum *and report*: the number of collapsed duplicates and
the affected pairs travel back in the manifest and in the upload response, so an
operator can see that the upload was not one row per edge.

The persisted artefact is a Parquet file plus a JSON manifest in
``BILATERAL_EXPOSURE_DIR`` (default ``/app/data/bilateral_exposures``). The
manifest is not decorative: it records the content hash of the exact bytes that
were validated, the vintage, the reporting institution and the duplicate count,
so a network served by the API can be traced to the payload that produced it.

What this module protects, and what it does not
-----------------------------------------------

Protected:

* **No arbitrary code execution.** CSV is read with :func:`pandas.read_csv`
  and Parquet with :func:`pandas.read_parquet` pinned to the ``pyarrow``
  engine. Pickle-based formats (``read_pickle``, ``.pkl``) are never used: a
  pickle payload executes code on load.
* **Bounded resource use.** The byte size is checked against a ceiling before
  parsing (and again while the body is streamed, by the route), and the row,
  institution and identifier lengths are capped. The byte ceiling bounds the
  *compressed* input: a deliberately compressible Parquet payload can still
  expand during decode, so peak decode memory is not bounded by this module.
* **Schema and semantics are enforced.** Missing/extra columns, non-numeric or
  non-finite amounts, negative amounts, self-exposure, blank/control-character
  identifiers, case-colliding identifiers, an ambiguous or future ``as_of`` and
  an empty payload are all refused with a typed error. Nothing is coerced to a
  default and nothing is repaired silently.

NOT protected:

* **Caller identity and authorisation.** BEACON's API has no authentication
  layer (every route depends only on ``get_db``). Anyone who can reach this
  endpoint can replace the exposure matrix that the risk map and, in future,
  the clearing path consume. The endpoint must not be exposed beyond a trusted
  network until an auth layer exists; this module cannot substitute for one.
* **Semantic truth.** A well-formed matrix can still be wrong. Validation
  proves it is *internally* consistent, not that the institution reported
  honestly. Provenance is recorded (``source_institution``, content hash) so a
  wrong upload is attributable, not because it is detectable here.
* **Cross-institution reconciliation.** The debtor's claim and the creditor's
  reported claim are not compared; bilateral reports can disagree and this
  module will not notice.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

import numpy as np
import pandas as pd

from backend.exceptions import (
    BeaconError,
    DataIngestionError,
    DataQualityError,
    EmptyDatasetError,
    SchemaValidationError,
)

logger = logging.getLogger(__name__)

__all__ = [
    "BilateralExposureStore",
    "ValidatedExposures",
    "ExposureUploadError",
    "ExposureSchemaError",
    "ExposureEmptyError",
    "ExposureValidationError",
    "ExposureUploadTooLargeError",
    "UnsupportedExposureFormatError",
    "parse_exposure_upload",
    "validate_exposure_matrix",
    "default_bilateral_exposure_store",
    "load_current_bilateral_exposures",
    "DEFAULT_EXPOSURE_DIR",
    "REQUIRED_COLUMNS",
    "OPTIONAL_COLUMNS",
    "SUPPORTED_FORMATS",
    "PARQUET_ENGINE",
]

DEFAULT_EXPOSURE_DIR = "/app/data/bilateral_exposures"
MATRIX_FILENAME = "interbank_bilateral_exposures.parquet"
MANIFEST_FILENAME = "interbank_bilateral_exposures.manifest.json"

REQUIRED_COLUMNS: Tuple[str, ...] = ("debtor", "creditor", "amount")
OPTIONAL_COLUMNS: Tuple[str, ...] = ("as_of",)
SUPPORTED_FORMATS: Tuple[str, ...] = ("csv", "parquet")
# Pinned explicitly. The default engine is chosen at runtime from whatever
# pyarrow/fastparquet happens to be importable; pinning means the Parquet reader
# is a known, non-executable data decoder rather than an accident of the image.
PARQUET_ENGINE = "pyarrow"

DEFAULT_MAX_UPLOAD_BYTES = 64 * 1024 * 1024
DEFAULT_MAX_ROWS = 500_000
DEFAULT_MAX_INSTITUTIONS = 2_000
MAX_INSTITUTION_ID_LENGTH = 128
MAX_DUPLICATE_PAIRS_RECORDED = 50

SCHEMA_VERSION = 1
_HASH_PREFIX = "sha256:"

_CONTROL_CHARACTERS = r"[\x00-\x1f\x7f]"


# ---------------------------------------------------------------------------
# Typed errors
# ---------------------------------------------------------------------------
#
# These specialise the hierarchy in ``backend.exceptions`` because the standard
# status codes there describe a *provider* misbehaving (502/503), while these
# describe the *caller's own payload*. Reporting a client's malformed CSV as
# "upstream unavailable" would send monitoring after the wrong incident, so the
# codes and statuses are narrowed while the family (``BeaconError``) is kept so
# the global handler renders them consistently.


class ExposureUploadError(BeaconError):
    """Base class for a rejected bilateral exposure upload."""

    code = "EXPOSURE_UPLOAD_FAILED"
    http_status = 400
    severity = "warning"


class ExposureSchemaError(SchemaValidationError):
    """The payload's structure is wrong (missing/extra columns, undecodable)."""

    code = "EXPOSURE_SCHEMA_INVALID"
    http_status = 422


class ExposureEmptyError(EmptyDatasetError):
    """The payload parsed but carried no rows."""

    code = "EXPOSURE_EMPTY"
    http_status = 422


class ExposureValidationError(DataQualityError):
    """The payload is well-formed but not admissible as obligations."""

    code = "EXPOSURE_VALIDATION_FAILED"
    http_status = 422


class ExposureUploadTooLargeError(DataIngestionError):
    """The payload exceeds a configured size or cardinality ceiling."""

    code = "EXPOSURE_UPLOAD_TOO_LARGE"
    http_status = 413


class UnsupportedExposureFormatError(SchemaValidationError):
    """The payload is neither CSV nor Parquet."""

    code = "EXPOSURE_FORMAT_UNSUPPORTED"
    http_status = 415


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ValidatedExposures:
    """A matrix that has passed every admissibility check.

    ``frame`` is the canonical, de-duplicated frame in the column order the
    engine expects. The counts describe the *raw* payload so the difference
    between what was uploaded and what was stored is visible.
    """

    frame: pd.DataFrame
    n_rows: int
    n_edges: int
    n_institutions: int
    gross_notional: float
    duplicate_edges_aggregated: int
    duplicate_pairs: Tuple[Tuple[str, str], ...]
    institutions: Tuple[str, ...]
    as_of: Optional[str]


def parse_exposure_upload(content: bytes, *, data_format: str) -> pd.DataFrame:
    """Decode an uploaded body into a frame without executing any of it.

    Args:
        content: The raw request body.
        data_format: ``"csv"`` or ``"parquet"``.

    Returns:
        The parsed frame, columns untouched; :func:`validate_exposure_matrix`
        normalises them.

    Raises:
        ExposureEmptyError: If the body is empty.
        UnsupportedExposureFormatError: If ``data_format`` is not supported.
        ExposureSchemaError: If the bytes cannot be decoded as that format.
    """
    if not content:
        raise ExposureEmptyError(
            "the uploaded bilateral exposure matrix is empty",
            context={"format": data_format},
        )
    if data_format not in SUPPORTED_FORMATS:
        raise UnsupportedExposureFormatError(
            f"unsupported exposure format {data_format!r}; "
            f"supported formats are {list(SUPPORTED_FORMATS)}",
            context={"format": data_format},
        )

    buffer = io.BytesIO(content)
    try:
        if data_format == "csv":
            frame = pd.read_csv(buffer)
        else:
            # ``engine`` is pinned rather than defaulted so the reader cannot
            # silently become a different (or pickle-capable) backend.
            frame = pd.read_parquet(buffer, engine=PARQUET_ENGINE)
    except BeaconError:
        raise
    except Exception as exc:  # noqa: BLE001 - any decoder failure is the same defect
        raise ExposureSchemaError(
            f"the uploaded body could not be decoded as {data_format}: {exc}",
            context={"format": data_format},
            cause=exc,
        ) from exc

    if not isinstance(frame, pd.DataFrame):
        raise ExposureSchemaError(
            f"the {data_format} payload did not decode to a table",
            context={"format": data_format, "decoded_type": type(frame).__name__},
        )
    buffer.close()
    return frame


def _normalise_columns(frame: pd.DataFrame) -> pd.DataFrame:
    """Lower-case and strip column names, rejecting collisions.

    Two source columns that normalise to the same name (``Amount`` and
    ``amount``) would make every later lookup dependent on column order. That is
    rejected rather than resolved, because whichever one is silently kept could
    be the wrong side of the book.
    """
    frame = frame.copy()
    original = [str(column) for column in frame.columns]
    normalised = [
        str(column).strip().lstrip("\ufeff").lower() for column in original
    ]
    duplicates = sorted({name for name in normalised if normalised.count(name) > 1})
    if duplicates:
        raise ExposureSchemaError(
            "the uploaded matrix has columns that collide once normalised: "
            f"{duplicates}",
            context={"original_columns": original, "colliding": duplicates},
        )
    frame.columns = normalised
    return frame


def _clean_identifiers(series: pd.Series, *, column: str) -> pd.Series:
    """Strip, bound and sanity-check one institution-id column."""
    cleaned = series.astype("string").str.strip()
    missing = cleaned.isna() | (cleaned == "")
    if bool(missing.any()):
        raise ExposureValidationError(
            f"the uploaded matrix has blank {column!r} value(s)",
            context={"column": column, "rows": int(missing.sum())},
        )
    too_long = cleaned.str.len() > MAX_INSTITUTION_ID_LENGTH
    if bool(too_long.any()):
        offenders = sorted(cleaned[too_long].unique().tolist())[:5]
        raise ExposureValidationError(
            f"institution ids in {column!r} exceed {MAX_INSTITUTION_ID_LENGTH} "
            f"characters",
            context={"column": column, "examples": offenders},
        )
    unsafe = cleaned.str.contains(_CONTROL_CHARACTERS, regex=True, na=False)
    if bool(unsafe.any()):
        raise ExposureValidationError(
            f"institution ids in {column!r} contain control characters or "
            "line breaks, which would corrupt the network identity",
            context={"column": column, "rows": int(unsafe.sum())},
        )
    return cleaned


def _reject_case_collisions(debtor: pd.Series, creditor: pd.Series) -> None:
    """Refuse ids that differ only by case.

    ``BANK_A`` and ``bank_a`` would become two nodes and the exposures between
    them would silently halve, which looks like a real de-risking in every
    downstream figure. Treating case as significant is not a choice this module
    should make on the data's behalf, so the ambiguity is refused.
    """
    variants: Dict[str, set] = {}
    for identifier in pd.concat([debtor, creditor], ignore_index=True).unique():
        variants.setdefault(str(identifier).lower(), set()).add(str(identifier))
    collisions = {
        key: sorted(value) for key, value in variants.items() if len(value) > 1
    }
    if collisions:
        raise ExposureValidationError(
            "the uploaded matrix uses the same institution id with different "
            "casing, which would split one institution into several nodes",
            context={
                "collisions": [
                    {"lower": key, "variants": value}
                    for key, value in sorted(collisions.items())
                ]
            },
        )


def _parse_as_of(series: pd.Series) -> Optional[pd.Timestamp]:
    """Validate the optional ``as_of`` column into a single vintage.

    A stored matrix describes one network at one instant. Rows carrying
    different vintages are not a matrix, they are a panel that would be summed
    across time; a future vintage is look-ahead. Both are refused.
    """
    if series.isna().any():
        raise ExposureValidationError(
            "the 'as_of' column has missing values; every row must declare the "
            "same vintage (drop the column entirely if the matrix is undated)",
            context={"missing": int(series.isna().sum())},
        )
    try:
        parsed = pd.to_datetime(series, errors="coerce", utc=True, format="mixed")
    except Exception as exc:  # noqa: BLE001 - pandas raises several types here
        raise ExposureValidationError(
            f"the 'as_of' column could not be parsed as timestamps: {exc}",
            cause=exc,
        ) from exc
    unparsed = parsed.isna()
    if bool(unparsed.any()):
        offenders = sorted(series[unparsed].astype(str).unique().tolist())[:5]
        raise ExposureValidationError(
            "the 'as_of' column contains values that are not timestamps",
            context={"examples": offenders},
        )
    unique = pd.DatetimeIndex(parsed).unique()
    if len(unique) != 1:
        raise ExposureValidationError(
            "the 'as_of' column contains more than one vintage; a bilateral "
            "matrix must describe the network at a single instant",
            context={"vintages": [value.isoformat() for value in unique[:5]]},
        )
    vintage = pd.Timestamp(unique[0])
    now = pd.Timestamp.now(tz="UTC")
    if vintage > now:
        raise ExposureValidationError(
            f"the 'as_of' vintage {vintage.isoformat()} is in the future "
            f"(now is {now.isoformat()}); a network cannot be reported before it "
            "exists",
            context={"as_of": vintage.isoformat(), "now": now.isoformat()},
        )
    return vintage


def validate_exposure_matrix(
    frame: pd.DataFrame,
    *,
    max_rows: int = DEFAULT_MAX_ROWS,
    max_institutions: int = DEFAULT_MAX_INSTITUTIONS,
) -> ValidatedExposures:
    """Check an exposure frame and return its canonical, de-duplicated form.

    Raises typed errors, never repairs. See the module docstring for why each
    check exists.
    """
    if frame is None or frame.empty:
        raise ExposureEmptyError("the uploaded bilateral exposure matrix has no rows")

    frame = _normalise_columns(frame)

    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        raise ExposureSchemaError(
            f"the uploaded matrix is missing required column(s): {missing}. "
            f"Expected {list(REQUIRED_COLUMNS)} and optionally {list(OPTIONAL_COLUMNS)}",
            context={"missing": missing, "received": list(frame.columns)},
        )
    unexpected = [
        column
        for column in frame.columns
        if column not in REQUIRED_COLUMNS + OPTIONAL_COLUMNS
    ]
    if unexpected:
        raise ExposureSchemaError(
            f"the uploaded matrix has unrecognised column(s): {unexpected}. "
            f"Expected {list(REQUIRED_COLUMNS)} and optionally {list(OPTIONAL_COLUMNS)}; "
            "an unrecognised column is dropped here, and dropping the wrong one "
            "would silently change what is being added up",
            context={"unexpected": unexpected, "received": list(frame.columns)},
        )

    if len(frame) > max_rows:
        raise ExposureUploadTooLargeError(
            f"the uploaded matrix has {len(frame)} rows, above the {max_rows} row "
            "ceiling",
            context={"rows": int(len(frame)), "max_rows": int(max_rows)},
        )

    amounts = pd.to_numeric(frame["amount"], errors="coerce")
    invalid = amounts.isna() | ~np.isfinite(amounts.to_numpy(dtype=float, na_value=np.nan))
    if bool(invalid.any()):
        offenders = frame.loc[invalid, "amount"].astype(str).unique().tolist()[:5]
        raise ExposureValidationError(
            "the 'amount' column contains non-numeric or non-finite values",
            context={"examples": offenders, "rows": int(invalid.sum())},
        )
    negative = amounts < 0
    if bool(negative.any()):
        offenders = [
            {
                "debtor": str(row["debtor"]),
                "creditor": str(row["creditor"]),
                "amount": float(row["amount"]),
            }
            for _, row in frame.loc[negative].head(5).iterrows()
        ]
        raise ExposureValidationError(
            "exposures must be non-negative magnitudes; direction is carried by "
            "the debtor/creditor columns, so a negative amount is a malformed row",
            context={"rows": int(negative.sum()), "examples": offenders},
        )

    debtor = _clean_identifiers(frame["debtor"], column="debtor")
    creditor = _clean_identifiers(frame["creditor"], column="creditor")
    _reject_case_collisions(debtor, creditor)

    self_exposure = debtor == creditor
    if bool(self_exposure.any()):
        offenders = sorted(debtor[self_exposure].unique().tolist())[:5]
        raise ExposureValidationError(
            "an institution cannot hold an exposure to itself",
            context={"rows": int(self_exposure.sum()), "institutions": offenders},
        )

    institutions = sorted(set(debtor.tolist()) | set(creditor.tolist()))
    if len(institutions) > max_institutions:
        raise ExposureUploadTooLargeError(
            f"the uploaded matrix names {len(institutions)} institutions, above "
            f"the {max_institutions} ceiling; the adjacency is quadratic in this "
            "count",
            context={
                "institutions": len(institutions),
                "max_institutions": int(max_institutions),
            },
        )

    as_of: Optional[str] = None
    if "as_of" in frame.columns:
        vintage = _parse_as_of(frame["as_of"])
        as_of = vintage.isoformat() if vintage is not None else None

    canonical = pd.DataFrame(
        {
            "debtor": debtor.astype("string"),
            "creditor": creditor.astype("string"),
            "amount": amounts.astype(float),
        }
    )
    if as_of is not None:
        canonical["as_of"] = pd.to_datetime(vintage)

    raw_edges = len(canonical)
    grouped = (
        canonical.groupby(["debtor", "creditor"], as_index=False, sort=True)["amount"]
        .sum()
        .reset_index(drop=True)
    )
    if as_of is not None:
        grouped["as_of"] = pd.to_datetime(vintage)
        grouped = grouped[["debtor", "creditor", "amount", "as_of"]]
    else:
        grouped = grouped[["debtor", "creditor", "amount"]]

    counts = canonical.groupby(["debtor", "creditor"], sort=True).size()
    duplicate_counts = counts[counts > 1]
    duplicate_edges = int((duplicate_counts - 1).sum())
    duplicate_pairs = tuple(
        (str(debtor_id), str(creditor_id))
        for debtor_id, creditor_id in duplicate_counts.index[:MAX_DUPLICATE_PAIRS_RECORDED]
    )

    return ValidatedExposures(
        frame=grouped,
        n_rows=int(raw_edges),
        n_edges=int(len(grouped)),
        n_institutions=len(institutions),
        gross_notional=float(grouped["amount"].sum()),
        duplicate_edges_aggregated=duplicate_edges,
        duplicate_pairs=duplicate_pairs,
        institutions=tuple(institutions),
        as_of=as_of,
    )


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class BilateralExposureStore:
    """File-backed store for the current bilateral exposure matrix.

    The store is the shared boundary between the upload endpoint and the engine:
    :meth:`load_bank_exposures` returns exactly the ``(debtor, creditor) ->
    amount`` mapping that :meth:`BankRiskAnalyzer.analyze_multiple_banks` accepts,
    so an uploaded file is consumable without an intermediate translation step
    that could disagree with the file.

    Args:
        root: Directory holding the matrix and manifest. Defaults to
            ``BILATERAL_EXPOSURE_DIR`` then :data:`DEFAULT_EXPOSURE_DIR`.
        max_upload_bytes: Ceiling on the raw payload.
        max_rows: Ceiling on payload rows.
        max_institutions: Ceiling on distinct institutions.
    """

    def __init__(
        self,
        root: Optional[os.PathLike | str] = None,
        *,
        max_upload_bytes: Optional[int] = None,
        max_rows: Optional[int] = None,
        max_institutions: Optional[int] = None,
    ) -> None:
        env_root = os.getenv("BILATERAL_EXPOSURE_DIR")
        self.root = Path(root if root is not None else (env_root or DEFAULT_EXPOSURE_DIR))
        self.max_upload_bytes = int(
            max_upload_bytes
            if max_upload_bytes is not None
            else os.getenv("BILATERAL_EXPOSURE_MAX_BYTES", DEFAULT_MAX_UPLOAD_BYTES)
        )
        self.max_rows = int(
            max_rows
            if max_rows is not None
            else os.getenv("BILATERAL_EXPOSURE_MAX_ROWS", DEFAULT_MAX_ROWS)
        )
        self.max_institutions = int(
            max_institutions
            if max_institutions is not None
            else os.getenv("BILATERAL_EXPOSURE_MAX_INSTITUTIONS", DEFAULT_MAX_INSTITUTIONS)
        )

    # -- paths ---------------------------------------------------------------

    @property
    def matrix_path(self) -> Path:
        return self.root / MATRIX_FILENAME

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_FILENAME

    def is_available(self) -> bool:
        """Whether a stored matrix exists at all.

        Existence only. A caller that needs the contents must call
        :meth:`load`, which raises rather than returning an empty frame when the
        stored artefact is unreadable.
        """
        return self.matrix_path.is_file()

    # -- write ---------------------------------------------------------------

    def ingest(
        self,
        content: bytes,
        *,
        data_format: str,
        source_institution: str,
        as_of: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Validate raw bytes and persist them as the current matrix.

        Args:
            content: Raw request body.
            data_format: ``"csv"`` or ``"parquet"``.
            source_institution: Who supplied the matrix. Required so a wrong
                upload is attributable.
            as_of: Optional ISO vintage used only when the payload has no
                ``as_of`` column. Supplying both different vintages is refused.

        Returns:
            The manifest that was written.

        Raises:
            BeaconError subclasses as documented on the validation functions.
        """
        reporter = str(source_institution or "").strip()
        if not reporter:
            raise ExposureValidationError(
                "source_institution is required; an exposure matrix with no "
                "reported origin cannot be attributed or challenged",
                context={"source_institution": source_institution},
            )
        if len(content) > self.max_upload_bytes:
            raise ExposureUploadTooLargeError(
                f"the uploaded matrix is {len(content)} bytes, above the "
                f"{self.max_upload_bytes} byte ceiling",
                context={
                    "bytes": len(content),
                    "max_bytes": int(self.max_upload_bytes),
                },
            )

        frame = parse_exposure_upload(content, data_format=data_format)
        if as_of is not None and "as_of" not in _normalise_columns(frame).columns:
            frame = frame.copy()
            frame["as_of"] = as_of

        validated = validate_exposure_matrix(
            frame,
            max_rows=self.max_rows,
            max_institutions=self.max_institutions,
        )

        if as_of is not None and validated.as_of is not None:
            declared = pd.Timestamp(as_of)
            if declared.tzinfo is not None:
                declared = declared.tz_convert("UTC").tz_localize(None)
            in_file = pd.Timestamp(validated.as_of)
            if in_file.tzinfo is not None:
                in_file = in_file.tz_convert("UTC").tz_localize(None)
            if declared != in_file:
                raise ExposureValidationError(
                    "the as_of argument and the payload's 'as_of' column disagree; "
                    "a matrix has one vintage and it must not be ambiguous",
                    context={
                        "argument": str(as_of),
                        "payload": validated.as_of,
                    },
                )

        content_hash = _HASH_PREFIX + hashlib.sha256(content).hexdigest()
        written_at = datetime.now(timezone.utc).isoformat()
        manifest: Dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "matrix_file": MATRIX_FILENAME,
            "source_institution": reporter,
            "as_of": validated.as_of,
            "uploaded_at": written_at,
            "format": data_format,
            "byte_size": len(content),
            "content_hash": content_hash,
            "n_rows": validated.n_rows,
            "n_edges": validated.n_edges,
            "n_institutions": validated.n_institutions,
            "gross_notional": validated.gross_notional,
            "duplicate_edges_aggregated": validated.duplicate_edges_aggregated,
            "duplicate_pairs": [list(pair) for pair in validated.duplicate_pairs],
            "institutions": list(validated.institutions),
            "columns": list(validated.frame.columns),
        }

        self._write_matrix(validated.frame, manifest)
        logger.info(
            "Stored bilateral exposure matrix from %s: %d institutions, %d edges, "
            "%d duplicate row(s) collapsed (%s)",
            reporter,
            validated.n_institutions,
            validated.n_edges,
            validated.duplicate_edges_aggregated,
            content_hash,
        )
        return manifest

    def _write_matrix(self, frame: pd.DataFrame, manifest: Mapping[str, Any]) -> None:
        """Atomically replace the stored matrix and manifest.

        Written to a temporary file in the same directory and moved into place,
        so a crash mid-write cannot leave a half-written Parquet that a later
        reader would happily open as a truncated network.
        """
        self.root.mkdir(parents=True, exist_ok=True)
        temporary = tempfile.NamedTemporaryFile(
            dir=self.root, prefix=".exposures-", suffix=".parquet.tmp", delete=False
        )
        temporary.close()
        try:
            frame.to_parquet(temporary.name, engine=PARQUET_ENGINE, index=False)
            os.replace(temporary.name, self.matrix_path)
        except Exception:
            Path(temporary.name).unlink(missing_ok=True)
            raise

        manifest_tmp = self.root / (MANIFEST_FILENAME + ".tmp")
        manifest_tmp.write_text(
            json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
        )
        os.replace(manifest_tmp, self.manifest_path)

    def clear(self) -> None:
        """Remove the stored matrix and manifest, if any."""
        self.matrix_path.unlink(missing_ok=True)
        self.manifest_path.unlink(missing_ok=True)

    # -- read ----------------------------------------------------------------

    def load(self) -> Optional[pd.DataFrame]:
        """Return the stored matrix, or ``None`` when nothing has been uploaded.

        A store that exists but cannot be read raises rather than returning an
        empty frame: "no network" and "a corrupted network" must not look the
        same to the caller.
        """
        if not self.matrix_path.is_file():
            return None
        try:
            frame = pd.read_parquet(self.matrix_path, engine=PARQUET_ENGINE)
        except Exception as exc:  # noqa: BLE001 - surface any decoder failure
            raise ExposureSchemaError(
                "the stored bilateral exposure matrix could not be read",
                context={"matrix_file": MATRIX_FILENAME},
                cause=exc,
            ) from exc
        missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
        if missing:
            raise ExposureSchemaError(
                "the stored bilateral exposure matrix is missing required "
                f"column(s): {missing}",
                context={"missing": missing, "matrix_file": MATRIX_FILENAME},
            )
        return frame

    def load_bank_exposures(self) -> Optional[Dict[Tuple[str, str], float]]:
        """The engine-facing reader: ``(debtor, creditor) -> amount``.

        This is the exact mapping accepted by
        :meth:`backend.modules.risk.bank_analyzer.BankRiskAnalyzer.analyze_multiple_banks`
        and convertible to a clearing layer through
        :func:`backend.modules.engine.multiplex.build_interbank_exposure_layer`.
        Returning this shape here is what makes "uploaded" and "consumable by
        the engine" the same statement.
        """
        frame = self.load()
        if frame is None:
            return None
        return {
            (str(debtor), str(creditor)): float(amount)
            for debtor, creditor, amount in zip(
                frame["debtor"], frame["creditor"], frame["amount"]
            )
        }

    def manifest(self) -> Optional[Dict[str, Any]]:
        """Return the stored manifest, or ``None`` when absent or unreadable."""
        if not self.manifest_path.is_file():
            return None
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001 - a broken manifest is metadata only
            logger.warning("Bilateral exposure manifest is unreadable: %s", exc)
            return None
        return payload if isinstance(payload, dict) else None


# ---------------------------------------------------------------------------
# Module-level accessors
# ---------------------------------------------------------------------------


def default_bilateral_exposure_store() -> BilateralExposureStore:
    """The store at the configured default location."""
    return BilateralExposureStore()


def load_current_bilateral_exposures(
    store: Optional[BilateralExposureStore] = None,
) -> Optional[Dict[Tuple[str, str], float]]:
    """Load the current matrix in the shape the engine consumes.

    Provided as a module-level function so an engine caller can obtain live
    exposures without knowing the storage layout; ``None`` means nothing has
    been uploaded, which callers must report as unavailable rather than
    substituting a default network.
    """
    return (store or default_bilateral_exposure_store()).load_bank_exposures()
