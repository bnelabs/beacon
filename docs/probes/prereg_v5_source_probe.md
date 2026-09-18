# Pre-registration v5 — source probe (wider family, multiple sources)

**Discipline:** criteria written and committed to this file BEFORE any request;
findings recorded verbatim afterwards. Polite probing (≈12 requests, keyed FRED
metadata endpoints + one BIS revalidation + one NY Fed transport check),
identified purpose, no aggressive retry.

**Context.** v4 (tag `prereg-early-warning-v4`) tested the two recorded axes
and published family NO (1/5) with the record's first criteria-passing pair
(`FRED_STLFSI4` × frozen hazard logit). Under the recorded rules any
resumption is owner-initiated, a new protocol, frozen before its run; the
owner initiated v5 on 2026-09-18 with the explicit aim of a **wider family
from multiple sources**. v5 changes the family (and adds the monthly track the
wider family needs); it changes **no grading criterion** — the four frozen
criteria, labeller quantile, windows, model config, seed protocol, baselines,
permutation test, Holm level, family rule and single-run rule remain identical
to v1–v4 by shared code.

**Declared consequence of a wider family (stated before any probe):** the
family rule (at least half of the tested indicators pass ALL criteria) becomes
*harder*, not easier, as the family grows — with ~10 testable indicators a
system-level claim needs ≥5 full passes. v5 is therefore explicitly a
better-powered scientific record and more individual shots at the STLFSI4-style
pass, NOT a route to an easier claim. The Holm pool grows with the family
(4 scorers × tested indicators); feasibility: the permutation test's minimum
attainable p is 1/1000 = 0.001, and 0.001 × 44 = 0.044 ≤ 0.05, so Holm
survival remains attainable at the planned pool size (arithmetic declared
pre-run, per the L-19 rule).

## Pre-written criteria (frozen before probing)

For each candidate series:

- **GREEN** — fetchable through an existing declared transport (keyed FRED API
  or keyless BIS SDMX); structured; **history starts ≤ 2000-01-01** (≥7 years
  of training data before the frozen 2007 evaluation boundary); measured
  frequency matches a declared track (daily/weekly/monthly/quarterly); the
  series' own FRED notes (or BIS terms) contain **no** prohibition pattern
  from the frozen `LICENCE_PROHIBITION_RE`.
- **YELLOW** — fetchable, but: start 2000-01-02…2003-12-31 (thin training
  span), or frequency mismatch requiring a declared track reassignment, or
  licence lines present-but-ambiguous. A YELLOW source may enter the family
  only if the protocol document explicitly declares the shortfall and its
  consequence before the freeze.
- **RED** — prohibition pattern present; or no structured transport in the
  plugin zoo; or history starts after 2003-12-31. Excluded pre-fetch,
  recorded, not substituted.

**Disposition rule (declared now):** only GREEN sources enter the v5 family;
YELLOW only with an explicit declared shortfall; RED is recorded verbatim and
never substituted. Directions for every entering code are declared in
`backend/modules/data/semantics.py` BEFORE any v5 fetch. BIS debt-service
ratio stays excluded on v4's recorded YELLOW (US history from 1999-Q1 — ~32
pre-2007 quarters cannot honestly train the declared architecture); no
re-probe needed.

## Candidates to probe (all declared now, before findings)

| # | Candidate | Intended track | Why (literature/registry rationale) |
|---|---|---|---|
| P1 | `FRED_DCOILWTICO` — WTI crude (EIA) | daily | Oil-price spikes as recession precursors (Hamilton); daily since 1986 |
| P2 | `FRED_DTWEXBGS` — broad trade-weighted USD index (Federal Reserve Board) | daily | Dollar spikes = global funding stress (2008, 2020, 2022) |
| P3 | `FRED_MORTGAGE30US` — 30y mortgage rate (Freddie Mac) | weekly | Rate-shock channel; weekly since 1971 |
| P4 | `FRED_NFCI` — Chicago Fed National Financial Conditions Index | weekly | The other national stress composite (beside STLFSI4); by construction higher = tighter |
| P5 | `FRED_FEDFUNDS` — effective federal funds rate | monthly (new track) | Policy-tightening channel (2000, 2006-07, 2022-23); monthly since 1954 |
| P6 | `FRED_UMCSENT` — U. Michigan consumer sentiment | monthly (new track) | Demand-side collapse precedes/attends crises; falling = stress |
| P7 | `BIS_CREDIT_GAP_US` — revalidate the v4 GREEN source | quarterly | The credit-gap family's admitted member; confirm endpoint + terms unchanged |
| P8 | NY Fed 12-month recession probability (`rp_prob`) | monthly (attempt) | A published expert model as an indicator; transport check only — the plugin zoo has no NY Fed research transport |

Monthly-track intent translation (declared now, to be pinned by test):
horizon 1 step (~21 bd ≥ the 21-bd daily intent), min_duration 1 (the
coarsest expressible), max_lead 2 (~42 bd, the daily ceiling), lead floor 1
step (~21 bd — STRICTER than the 10-bd intent, declared not hidden),
steps_per_year 12, hazard lookback 3 (~one quarter), gap window (8, 35] days.
Alarm arithmetic (declared now): uniform q98 → ~0.24 alarms/year on monthly →
the FA ceiling cannot bind on monthly (as on weekly/quarterly in v4); lift and
lead bind — declared consequence, pre-run.

## Findings

*(recorded after execution, verbatim; 10 requests, 2026-09-18, keyed FRED
metadata endpoints + 1 BIS SDMX GET + 1 NY Fed transport GET)*

| # | Candidate | Observed | Classification |
|---|---|---|---|
| P1 | `DCOILWTICO` | daily; 1986-01-02 → 2026-09-15; notes: EIA definitions/sources link; prohibition pattern: **absent** | **GREEN** |
| P2 | `DTWEXBGS` | daily; **start 2006-01-02** → 2026-09-11; prohibition pattern: absent | **RED** — history starts after 2003-12-31; <1 year of pre-2007 training data. **Excluded pre-fetch, recorded, not substituted.** |
| P3 | `MORTGAGE30US` | weekly; 1971-04-02 → 2026-09-17; notes carry "Copyright, 2016, Freddie Mac. Reprinted with permission." + as-is warranty + 2022 methodology-change note; prohibition pattern: **absent** | **GREEN** (copyright + methodology lines recorded in the manifest's licence lines) |
| P4 | `NFCI` | weekly; 1971-01-08 → 2026-09-11; notes describe the index (positive = tighter than average); prohibition pattern: **absent** | **GREEN** |
| P5 | `FEDFUNDS` | monthly; 1954-07-01 → 2026-08-01; prohibition pattern: **absent** | **GREEN** |
| P6 | `UMCSENT` | monthly; 1952-11-01 → 2026-07-01; notes carry a required citation ("Surveys of Consumers, University of Michigan…") and "Copyright, 2016, Surveys of Consumers, University of Michigan. Reprinted with permission."; 1-month publication delay noted by the source; prohibition pattern: **absent** | **GREEN** (citation line travels in the manifest; the delay is immaterial for a historical evaluation, recorded) |
| P7 | `BIS_CREDIT_GAP_US` | keyless SDMX CSV; 274 rows; 1957-Q4 → 2026-Q1; homogeneous single series (all dimension values identical: Q/US/P/A/C/E); terms page unchanged since the v4 probe (permission sentence + required attribution already recorded) | **GREEN** (revalidated) |
| P8 | NY Fed `rp_prob` | GET of the documented medialog URL returned **HTTP 200 with Content-Type `text/html`** (`<!DOCTYPE html>` first bytes) — a web page, not the spreadsheet; the plugin zoo has no NY Fed research transport (nyfed_plugin serves reference rates only) | **RED** — no structured keyless transport. **Excluded pre-fetch, recorded, not substituted.** |

Carried dispositions (no re-probe needed): BIS debt-service ratio stays
**YELLOW-excluded** on v4's recorded finding (US history from 1999-Q1);
`ECB_CISS` stays a declared keyless attempt whose skip will be recorded;
`FRED_BAMLH0A0HYM2` stays licence-refused pre-download; `FRED_RRPONTSYD`
stays owner-excluded; the six operator-reported codes stay excluded (no public
source — the PRA probe confirmed bank-level data is supervisory-confidential).

**Family consequence (declared from these findings, before the freeze):** the
v5 testable family is projected at **11 indicators across four tracks and
three publishers** (US Treasury/FRED-served: T10Y2Y, T10Y3M, VIXCLS,
DCOILWTICO, STLFSI4, MORTGAGE30US, NFCI, KCFSI, FEDFUNDS, UMCSENT; BIS:
CREDIT_GAP_US) — pending the frozen quality gate re-deriving every skip at
fetch time (SOFR is expected to skip on coverage again). Under the unchanged
family rule, a system-level claim would need **≥6 of the tested indicators to
pass ALL criteria**. That is the declared bar v5 runs against.
