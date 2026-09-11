"""SEC Form PF -- the feed that deliberately does not fetch.

Why this module refuses instead of downloading
----------------------------------------------
Form PF is the confidential systemic-risk filing that private fund advisers submit
to the SEC. Individual filings are **not public**, and this is not an oversight or
a missing API key: it is the design of the regime. The SEC's own annual report to
Congress on its use of Form PF data describes staff receiving the data "via a
direct feed from FINRA" and maintaining it "on access-controlled internal data
systems", with onward disclosure to FSOC/OFR, the CFTC and the Federal Reserve
Board "subject to agreements regarding appropriate use of and confidentiality
protections for Form PF data". Filings are made through FINRA's Private Fund
Reporting Depository (PFRD), which is not a public endpoint.

Verified on 2026-09-11:

* ``https://www.sec.gov/data-research/statistics-data-visualizations/private-fund-statistics``
  returns **200**. This is the public substitute: the SEC's quarterly *Private
  Funds Statistics*, which publishes analysis of **aggregated** Form PF data.
* ``https://www.sec.gov/foia/docs/form-pf-data.htm`` returns **404** -- there is no
  public Form PF data page to scrape.
* ``https://efts.sec.gov/LATEST/search-index?forms=PF`` returns 200 but serves the
  full-text *search index*; it does not expose Form PF filings.

So the honest implementation is a connector that raises
:class:`~backend.exceptions.RestrictedSourceError` and names the lawful
alternative, rather than one that returns nothing and lets a caller assume the
source was merely quiet. A gap that is invisible is worse than a gap that shouts.

What to do instead, and what this module does support
-----------------------------------------------------
1. **Public aggregate feed.** The SEC's *Private Funds Statistics* is public and is
   the correct input for industry-level private fund exposure. It is a separate
   ingestion job: it publishes aggregate tables, not fund-level observations, so it
   cannot be turned into the per-entity series this pipeline models without a
   documented mapping. That work is deliberately not faked here.
2. **Entitled access.** An institution that lawfully holds Form PF data -- a
   regulator, or an adviser reading its own filings -- can load it through
   :meth:`SecFormPfConnector.load_authorised_export`, which validates against the
   same schema as every other connector. That path demands an explicit
   ``source_reference`` so the provenance of restricted data is never implicit.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import pandas as pd

from backend.exceptions import RestrictedSourceError

from .base import (
    ConnectorReport,
    ConnectorSpec,
    DataConnector,
    FetchRequest,
    frame_to_observations,
    validate_observation_frame,
)
from ..pit import PITStore

__all__ = ["SecFormPfConnector", "FORM_PF_REFUSAL_REASON", "PUBLIC_ALTERNATIVE_URL"]

#: The public aggregate substitute, verified reachable (HTTP 200).
PUBLIC_ALTERNATIVE_URL = (
    "https://www.sec.gov/data-research/statistics-data-visualizations/"
    "private-fund-statistics"
)

#: Where Form PF is actually filed. Not a public API.
FILING_SYSTEM = "FINRA Private Fund Reporting Depository (PFRD)"

FORM_PF_REFUSAL_REASON = (
    "Form PF filings are confidential and are not retrievable by this pipeline. "
    "The SEC receives them from FINRA's Private Fund Reporting Depository and "
    "holds them on access-controlled internal systems; fund-level data is shared "
    "only with FSOC/OFR, the CFTC and the Federal Reserve Board under "
    "confidentiality agreements. There is no public endpoint to call, so this "
    "connector refuses rather than returning a misleadingly empty result. Use the "
    "SEC's public 'Private Funds Statistics' for aggregate private fund exposure, "
    "or supply an authorised extract via load_authorised_export()."
)


@dataclass(frozen=True)
class FormPfAvailability:
    """Machine-readable statement of what can and cannot be obtained."""

    public_filings: bool = False
    public_aggregates: bool = True
    filing_system: str = FILING_SYSTEM
    public_alternative: str = PUBLIC_ALTERNATIVE_URL
    reason: str = FORM_PF_REFUSAL_REASON

    def to_dict(self) -> Dict[str, Any]:
        return {
            "public_filings": self.public_filings,
            "public_aggregates": self.public_aggregates,
            "filing_system": self.filing_system,
            "public_alternative": self.public_alternative,
            "reason": self.reason,
        }


class SecFormPfConnector(DataConnector):
    """A connector that fail-closes on a source that is not public.

    Every retrieval method raises :class:`RestrictedSourceError` (code
    ``DATA_SOURCE_RESTRICTED``, HTTP 451). It is deliberately not silent and
    deliberately not retried: retrying will never help, and an empty frame would
    be indistinguishable from "no funds to report".

    Use :meth:`availability` to report the situation to an operator, and
    :meth:`load_authorised_export` when an entitlement genuinely exists.
    """

    accept = "application/xml"

    @property
    def spec(self) -> ConnectorSpec:
        return ConnectorSpec(
            name="sec_form_pf",
            kind="sec",
            entity_id="PRIVATE_FUND_SECTOR",
            source_url=PUBLIC_ALTERNATIVE_URL,
            endpoint="(none -- confidential; filed via FINRA PFRD)",
            licence=(
                "Confidential. Form PF information is not public and is withheld "
                "from FOIA-type release; the SEC publishes only aggregated "
                "statistics derived from it."
            ),
            cadence="quarterly (aggregates only)",
            description=(
                "Private fund systemic-risk filing by SEC-registered advisers. "
                "Fund-level data is confidential, so this connector refuses and "
                "points at the SEC's public aggregate statistics instead."
            ),
            requires_credentials=True,
        )

    @staticmethod
    def availability() -> FormPfAvailability:
        """What is obtainable from this source, and why."""
        return FormPfAvailability()

    def build_url(self, request: FetchRequest) -> str:
        """Always raises: there is no public URL to build."""
        raise RestrictedSourceError(
            FORM_PF_REFUSAL_REASON,
            context={"connector": self.spec.name, "filing_system": FILING_SYSTEM},
        )

    def parse(self, payload: bytes, request: FetchRequest) -> pd.DataFrame:
        """Always raises: no public payload exists to parse."""
        raise RestrictedSourceError(
            FORM_PF_REFUSAL_REASON,
            context={
                "connector": self.spec.name,
                "payload_bytes": len(payload) if payload else 0,
            },
        )

    def fetch(self, request: Optional[FetchRequest] = None) -> pd.DataFrame:
        """Always raises :class:`RestrictedSourceError`.

        Overridden so the refusal is explicit at the top level rather than an
        incidental consequence of :meth:`build_url` raising first.
        """
        raise RestrictedSourceError(
            FORM_PF_REFUSAL_REASON,
            context={
                "connector": self.spec.name,
                "operation": "fetch",
                "filing_system": FILING_SYSTEM,
            },
        )

    def load_authorised_export(
        self,
        store: PITStore,
        frame: pd.DataFrame,
        *,
        source_reference: str,
    ) -> ConnectorReport:
        """Load an extract an entitled operator already holds.

        This is the only way Form PF data enters the pipeline. The frame must
        already be in observation schema, because transcribing a restricted source
        is the operator's step and must not be guessed at here.

        ``source_reference`` is mandatory and is an explicit attestation: it is the
        authority under which the data was obtained (a filing receipt, an agreement
        reference, an internal system id). Requiring it means restricted data can
        never enter the store anonymously.

        Raises:
            ValueError: ``source_reference`` is empty.
            RestrictedSourceError: The frame claims to come from a public fetch,
                which cannot be true for this source.
            SchemaValidationError: The frame violates the observation schema.
        """
        if not str(source_reference).strip():
            raise ValueError(
                "source_reference is required: restricted data must carry the "
                "authority under which it was obtained"
            )
        if frame is not None and "retrieved_publicly" in getattr(frame, "columns", ()):
            raise RestrictedSourceError(
                "Form PF data cannot be marked as publicly retrieved",
                context={"connector": self.spec.name, "source_reference": source_reference},
            )

        validated = validate_observation_frame(frame, connector=self.spec.name)
        added = store.append(frame_to_observations(validated))
        return ConnectorReport(
            connector=self.spec.name,
            fetched=int(validated.shape[0]),
            added=int(added),
            series=tuple(sorted(validated["series_id"].unique())),
            entities=tuple(sorted(validated["entity_id"].unique())),
            first_valid_time=pd.Timestamp(validated["valid_time"].min()),
            last_valid_time=pd.Timestamp(validated["valid_time"].max()),
        )
