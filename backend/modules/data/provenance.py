"""Data-source provenance: what every feed is, where it comes from, and what
part of the platform's input is *inferred* rather than observed.

Why this module exists
----------------------

An external review asked the question an auditor would: for each number that
enters the system, who published it, under what licence/registration, and is
it an observation or an inference? The answer was scattered across plugin
docstrings and nowhere at all for the estimated bilateral network. This module
is the single curated answer, served at ``GET /api/v1/data-sources/disclosure``
and rendered on the Data Sources page.

Design rules
------------

* Access facts (free, key required) are **derived from each plugin's own
  ``get_plugin_info()``** -- the plugin is the system of record for how it
  authenticates, and a copied string would drift.
* Publisher, provenance class and "what it feeds" are **curated here**,
  because no plugin introspection can produce them. The guard test
  (``test_provenance_disclosure.py``) fails when a registered plugin has no
  curated entry, so a new feed cannot ship undisclosed.
* Configured/enabled counts and catalogue coverage are **queried from the
  database at request time**: the disclosure describes this deployment, not a
  hypothetical one.
* Inferred inputs are disclosed as a first-class list. Today there is exactly
  one: the bilateral network estimated from declared aggregate marginals
  (``POST /api/v1/network/estimate``). It is labelled at every surface it
  appears on, never persisted as if observed, and its caveat travels with
  every clearing result computed from it.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import Integer, func
from sqlalchemy.orm import Session

from backend.plugins import list_plugins

#: The closed vocabulary of provenance classes. A source's class answers
#: "what kind of truth is this?" -- supervisory publication, official
#: statistic, regulatory filing, market observation, research dataset, or an
#: operator declaration whose provenance is whatever the operator states.
PROVENANCE_CLASSES: Dict[str, str] = {
    "supervisory_published": (
        "published by a banking supervisor about the institutions it supervises"
    ),
    "official_statistics": (
        "published by a central bank, statistical agency or intergovernmental "
        "body as official statistics"
    ),
    "regulatory_filings": (
        "filings made by issuers to a regulator and published by that regulator"
    ),
    "market_observed": (
        "prices and fundamentals observed in markets, typically via a "
        "commercial or unofficial aggregator"
    ),
    "research_dataset": (
        "a fixed dataset published for research; provenance and vintage are "
        "the dataset's, not a live feed's"
    ),
    "operator_declared": (
        "content supplied or configured by the deploying operator; the "
        "platform cannot vouch for its provenance beyond the operator's word"
    ),
}


@dataclass(frozen=True)
class ProvenanceRecord:
    """The curated half of a source's disclosure."""

    publisher: str
    provenance_class: str
    provides: str
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        if self.provenance_class not in PROVENANCE_CLASSES:
            raise ValueError(
                f"provenance class {self.provenance_class!r} is not declared "
                f"in PROVENANCE_CLASSES"
            )


#: One entry per registered plugin type. The guard test asserts this table and
#: the runtime registry stay in sync in both directions.
CURATED_PROVENANCE: Dict[str, ProvenanceRecord] = {
    "fdic": ProvenanceRecord(
        publisher="U.S. Federal Deposit Insurance Corporation",
        provenance_class="supervisory_published",
        provides=(
            "quarterly bank-level supervisory financials (assets, deposits, "
            "equity, profitability) per FDIC CERT via the BankFind Suite API"
        ),
        notes=(
            "served fields verified against the live API on 2026-09-15; "
            "interbank marginal fields (the /network/estimate inputs) will be "
            "declared only after the same verification"
        ),
    ),
    "ecb_banking": ProvenanceRecord(
        publisher="European Central Bank (SSM banking statistics)",
        provenance_class="supervisory_published",
        provides="euro-area bank-level supervisory statistics",
    ),
    "ecb": ProvenanceRecord(
        publisher="European Central Bank",
        provenance_class="official_statistics",
        provides="euro-area monetary and financial statistics (SDW API)",
    ),
    "fred": ProvenanceRecord(
        publisher="Federal Reserve Bank of St. Louis",
        provenance_class="official_statistics",
        provides=(
            "U.S. macro series and stress indices (STLFSI4, KCFSI, CISS, "
            "SOFR, T10Y2Y, ...)"
        ),
        notes=(
            "works keyless via the fredgraph.csv endpoint; a free API key "
            "adds documented rate limits"
        ),
    ),
    "nyfed": ProvenanceRecord(
        publisher="Federal Reserve Bank of New York",
        provenance_class="official_statistics",
        provides="reference rates (SOFR, overnight reverse repo) from the NY Fed public API",
    ),
    "boe_database": ProvenanceRecord(
        publisher="Bank of England",
        provenance_class="official_statistics",
        provides=(
            "Official Bank Rate (IUDBEDR) and operator-declared series from the "
            "Interactive Database's HTML-table interface; reuse licence CONFIRMED "
            "2026-09-18 against bankofengland.co.uk/legal ('Bank of England "
            "Database' section): UK Open Government Licence v3 -- derived products "
            "should attribute 'Contains public sector information licensed under "
            "the Open Government Licence v3.0', (c) Governor and Company of the "
            "Bank of England; third-party-sourced series (e.g. LSEG spot exchange "
            "rates) are excluded from that licence and need the third party's "
            "approval (see docs/probes/boe_endpoint_probe.md)"
        ),
    ),
    "cftc_cot": ProvenanceRecord(
        publisher="U.S. Commodity Futures Trading Commission",
        provenance_class="official_statistics",
        provides="weekly Commitments-of-Traders positioning (public Socrata endpoint)",
    ),
    "bis": ProvenanceRecord(
        publisher="Bank for International Settlements",
        provenance_class="official_statistics",
        provides="cross-border banking and global liquidity statistics",
    ),
    "imf": ProvenanceRecord(
        publisher="International Monetary Fund",
        provenance_class="official_statistics",
        provides="IMF Data API series (macro-financial aggregates)",
    ),
    "world_bank": ProvenanceRecord(
        publisher="World Bank",
        provenance_class="official_statistics",
        provides="country development and financial-sector indicators",
    ),
    "sec_edgar": ProvenanceRecord(
        publisher="U.S. Securities and Exchange Commission",
        provenance_class="regulatory_filings",
        provides="EDGAR company filing metadata and extracted facts",
    ),
    "yfinance": ProvenanceRecord(
        publisher="Yahoo Finance (unofficial community API)",
        provenance_class="market_observed",
        provides="daily prices and fundamentals for listed instruments",
        notes=(
            "an unofficial endpoint with no service guarantees; a convenience "
            "feed, never a system of record"
        ),
    ),
    "alpha_vantage": ProvenanceRecord(
        publisher="Alpha Vantage",
        provenance_class="market_observed",
        provides="prices, FX and technical indicators (free key required)",
    ),
    "fmp": ProvenanceRecord(
        publisher="Financial Modeling Prep",
        provenance_class="market_observed",
        provides="global bank fundamentals and market data (key required)",
    ),
    "kaggle": ProvenanceRecord(
        publisher="Kaggle (per-dataset publishers)",
        provenance_class="research_dataset",
        provides="bulk historical datasets; provenance is the individual dataset's",
        notes="dataset-level provenance must be checked before research use",
    ),
    "ai4risk_interbank": ProvenanceRecord(
        publisher="AI4Risk challenge (published research dataset)",
        provenance_class="research_dataset",
        provides=(
            "2016-2023 interbank network dataset (4,548 banks) for topology "
            "and research work"
        ),
        notes="a fixed competition dataset, not a live supervisory feed",
    ),
    "csv": ProvenanceRecord(
        publisher="the deploying operator",
        provenance_class="operator_declared",
        provides="operator-uploaded CSV series; provenance is whatever the operator declares",
    ),
    "custom_api": ProvenanceRecord(
        publisher="an operator-configured endpoint",
        provenance_class="operator_declared",
        provides="arbitrary JSON endpoints, fetched under the platform SSRF policy",
    ),
}

#: Inputs the platform *infers* rather than observes. Each entry states what
#: it is, where it is produced, and the caveat that must travel with it.
INFERRED_INPUTS: List[Dict[str, Any]] = [
    {
        "name": "bilateral_exposure_network",
        "produced_by": "POST /api/v1/network/estimate",
        "method": (
            "maximum-entropy and minimum-support completions of declared "
            "aggregate interbank marginals, with Eisenberg-Noe clearing "
            "propagated over marginal-preserving structural draws"
        ),
        "status": (
            "estimated: responses carry status=estimated and "
            "persistence=not_stored; estimates are never written to the "
            "bilateral exposure store and never served as observations"
        ),
        "caveat": (
            "a prior over bilateral structure given the declared aggregates, "
            "not a measurement of bilateral exposures; every clearing result "
            "computed from it inherits the caveat"
        ),
    },
]

DATA_POLICY = {
    "synthetic_data": (
        "forbidden: the platform does not generate, impute or fabricate "
        "observations. A quantity that cannot be computed from real inputs is "
        "served as an explicit unavailable state with a reason, never as a "
        "plausible-looking placeholder."
    ),
    "estimated_inputs": (
        "labelled at every surface they appear on (see inferred_inputs) and "
        "excluded from the observed-data stores"
    ),
}


def build_disclosure(db: Session) -> Dict[str, Any]:
    """Assemble the deployment-specific disclosure payload.

    Merges the curated registry with each plugin's self-declared access facts
    and live database counts. A configured data source whose ``plugin_type``
    is not registered is disclosed under ``orphaned_configurations`` rather
    than dropped: a broken feed the operator cannot see is worse than an
    ugly list.
    """
    from backend.models.data_catalogue import DataCatalogueItem
    from backend.models.data_source import DataSource

    # configured/enabled counts and catalogue coverage, per plugin type
    configured: Dict[str, int] = {}
    enabled: Dict[str, int] = {}
    for plugin_type, count, enabled_count in (
        db.query(
            DataSource.plugin_type,
            func.count(DataSource.id),
            func.sum(func.cast(DataSource.enabled, Integer)),
        )
        .group_by(DataSource.plugin_type)
        .all()
    ):
        configured[plugin_type or "unknown"] = int(count)
        enabled[plugin_type or "unknown"] = int(enabled_count or 0)

    catalogue_counts: Dict[str, int] = {}
    rows = (
        db.query(DataSource.plugin_type, func.count(DataCatalogueItem.id))
        .join(DataCatalogueItem, DataCatalogueItem.data_source_id == DataSource.id)
        .group_by(DataSource.plugin_type)
        .all()
    )
    for plugin_type, count in rows:
        catalogue_counts[plugin_type or "unknown"] = int(count)

    sources: List[Dict[str, Any]] = []
    undocumented: List[str] = []
    for info in sorted(list_plugins(), key=lambda entry: entry["type"]):
        plugin_type = info["type"]
        curated = CURATED_PROVENANCE.get(plugin_type)
        if curated is None:
            # The guard test fails on this in CI; at runtime the source is
            # still disclosed, with its provenance explicitly missing.
            undocumented.append(plugin_type)
        sources.append(
            {
                "plugin_type": plugin_type,
                "name": info.get("name", plugin_type),
                "description": info.get("description"),
                "publisher": curated.publisher if curated else None,
                "provenance_class": curated.provenance_class if curated else "undisclosed",
                "provides": curated.provides if curated else None,
                "notes": curated.notes if curated else None,
                "access": {
                    "free": bool(info.get("free", False)),
                    "key_required": bool(info.get("registration_required", False)),
                    "registration_url": info.get("registration_url"),
                },
                "deployment": {
                    "configured_sources": configured.get(plugin_type, 0),
                    "enabled_sources": enabled.get(plugin_type, 0),
                    "catalogue_items": catalogue_counts.get(plugin_type, 0),
                },
            }
        )

    registered = {info["type"] for info in list_plugins()}
    orphaned = sorted(set(configured) - registered)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "policy": DATA_POLICY,
        "provenance_classes": PROVENANCE_CLASSES,
        "sources": sources,
        "inferred_inputs": INFERRED_INPUTS,
        "undocumented_plugins": undocumented,
        "orphaned_configurations": [
            {
                "plugin_type": plugin_type,
                "configured_sources": configured.get(plugin_type, 0),
                "problem": "configured in this deployment but not registered at runtime; it cannot fetch",
            }
            for plugin_type in orphaned
        ],
    }
