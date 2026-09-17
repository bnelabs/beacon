# PRA endpoint probe — bank-level UK exposures

**Executed:** 2026-09-18 · **Discipline:** criteria written before any
request; findings recorded verbatim. Polite probing (≈8 requests, identified
user-agent, no aggressive retry).

Context: the BoE probe (`boe_endpoint_probe.md`) classified the UK gap YELLOW
with two actions; action 1 (Interactive Database → `boe_database` plugin) and
action 4 (licence → UK OGL v3) are done. This probe closes out the remaining
recorded action: **is bank-level UK exposure data publicly fetchable from the
PRA in structured form?**

## Pre-written criteria (frozen before probing)

GREEN: a keyless, structured (CSV/JSON/SDMX) endpoint publishes
*bank-level* exposures (per-institution lending, liquidity or leverage
series) with a documented, stable contract.
YELLOW: structured *aggregate* data only (system-level totals by cohort),
bank-level obtainable only via FOI request or paid vendors.
RED: no structured public data beyond what `boe_database` already serves;
bank-level exposures are supervisory-confidential with no public route.

Disposition: GREEN ⇒ a plugin proposal follows the BoE discipline (probe →
contract → pinned-bytes tests). YELLOW/RED ⇒ recorded as the finding it is;
the operator-onboarding route (`docs/operator_series_onboarding.md`) is the
only path for bank-level data, and the probe says so plainly.

## Findings

*(recorded after execution, verbatim; 8 requests, 2026-09-18, UA
`Mozilla/5.0 (compatible; BEACON-source-probe/4.0; research; bnelabs)`)*

- The standalone PRA landing paths 404 — the site restructured:
  `/prudential-regulation-authority` → 404,
  `/prudential-regulation-authority/data-and-publications` → 404,
  `/statistics/bank-and-building-society-data` → 404,
  `/prudential-regulation-authority/regulatory-reporting` → 404.
  (`/legal` and `/statistics` → 200, so the host is reachable; the paths
  moved.)
- `/statistics` (200) describes the PRA-sourced public releases verbatim:
  *"Insurance aggregate data quarterly report — This report is a quarterly
  statistical release of **aggregated data**, produced using PRA regulatory
  data supplied by UK authorised insurance firms"*, with a published update
  calendar. Aggregate money-and-credit releases (Bankstats-derived) are
  linked from the same index.
- `/prudential-regulation/regulatory-reporting/regulatory-reporting-banking-sector/banks-building-societies-and-investment-firms`
  (200) publishes the *reporting contract*, not the returns: *"details of
  data items firms submit to the PRA, and supporting instructions and
  taxonomy"*. Individual-firm data appears only in a supervisory-feedback
  context (*"provide individual firms with feedback on their interim
  reporting returns"*), i.e. confidential.
- No keyless structured endpoint publishing **bank-level** exposures was
  found within the probe budget.

**Classification: YELLOW** (against the frozen criteria) — structured
*aggregate* PRA-sourced releases exist and are machine-reachable; bank-level
exposures are supervisory-confidential with no public route short of an FOI
request. **Disposition:** the operator-onboarding route
(`docs/operator_series_onboarding.md`) is the only path for bank-level data —
exactly the six registry codes it was written for. The aggregate insurance
quarterly release is recorded as a possible future `boe_statistics`-style
plugin candidate (out of scope here; it feeds no registry code). This closes
the last open action of the BoE probe's YELLOW path.

