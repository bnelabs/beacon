# Pre-registered early-warning evaluation — protocol v5

**Status: FROZEN, pending run.** Machine-readable half:
[`configs/event_eval_v5.yaml`](../../configs/event_eval_v5.yaml). Owner
sign-off: given in chat on 2026-09-18 ("can you make a wider data collection
from multiple resources and do another … round which is enhanced" — the
owner-initiated resumption the README gate describes). Committed and
git-tagged `prereg-early-warning-v5` **before** the run; after the tag,
changes require protocol v6 plus a CHANGELOG entry.

**Why v5 exists.** v4 published family NO (1/5) with the record's first
criteria-passing pair (`FRED_STLFSI4` × frozen hazard logit) and confirmed
the standing diagnosis: the constraint is the **family**, not the machinery.
Its outcome handling recorded "there is no planned v5" — a statement about
the record, not a lock: every version since v1 has said any resumption is
owner-initiated, a new protocol, frozen before its run. The owner initiated
v5 with one explicit aim: **a wider family from multiple sources**. v5
changes the family (and adds the monthly track the wider family needs) and
**changes no grading criterion**.

**Declared consequence of a wider family (stated before the run).** The
family rule — at least half of the tested indicators pass ALL criteria —
becomes *harder* as the family grows: with the projected ~11 testable
indicators, a system-level claim needs **≥6 full passes**. v5 is a
better-powered scientific record and more individual shots at the
STLFSI4-style pass, **not** a route to an easier claim. Feasibility of the
multiplicity control at the wider pool (L-19 rule: criteria
feasibility-checked against each other before the freeze, published numbers
only): the permutation test's minimum attainable p is 1/1000; the Holm pool
is 4 scorers × 11 indicators = 44 pairs; 0.001 × 44 = 0.044 ≤ 0.05, so Holm
survival remains attainable. Alarm-coherence arithmetic per track is declared
in §4; no criterion pair is unreachable by construction (the v2 defect
class).

**Outcome handling (declared now, honoured either way).** PASS (family claim
warranted: ≥ half of tested indicators pass, ≥3 testable) → the README claim
gate moves, carrying these numbers. FAIL → the line **remains parked**, now
with a five-run documented record; there is no planned v6 — any further
iteration needs a new owner decision and new recorded axes, exactly as v4 and
v5 needed. Individual indicator passes (the STLFSI4 class of result) are
published as facts either way and are **not** upgraded into system claims.

## 1. What is frozen identically (by shared code, not by promise)

The four criteria and their thresholds (median lead ≥10 business days;
false alarms ≤4 per quiet year; AUC **and** AP strictly above persistence
**and** AR(1) on the scorer's own grid; AP above the event base rate with a
1000-permutation p, seed 20260917, surviving Holm–Bonferroni at 0.05 across
the full pool) · the labeller quantile (0.95) · the windows (train ≤2006,
evaluate 2007–2024) · the model config (temporal attention, d_model 16,
1 layer, 15 epochs, sequence 30) · the seed protocol (`torch.manual_seed(11)`
at every train/refit) · the baselines · the alarm quantile (0.98, v3's
coherent point) · the minimum testable family (3) · the family rule · the
single-run rule. `test_prereg_v5.py` pins the equality of every shared
constant, exactly as `test_prereg_v4.py` did for v4.

## 2. Tracks (the monthly row is v5's only new mechanic)

Daily / weekly / quarterly rows are **unchanged from v4** (the daily row
re-states the frozen v1–v3 constants; pinned by test). The monthly row
translates the same design intent at the monthly grid's coarsest granularity:
horizon 1 step (~21 bd = the daily intent), min_duration 1 (coarsest
expressible), max_lead 2 (~42 bd), lead floor 1 step (~21 bd — **stricter**
than the 10-bd intent, declared not hidden), steps_per_year 12, hazard
lookback 3 (~one quarter), gap band (8, 35] days matching the measured
frequency classifier. Coverage expectations are computed at each track's own
cadence (monthly: ×12/365.25 calendar days) — a data-availability mechanic,
not a criterion.

## 3. Rolling refits and scorers (identical to v4)

The same four declared scorers: `tan_frozen` and `hazard_logit` (the frozen
pair — on unchanged sources they reproduce v3/v4 exactly, the run's own
reproducibility check), and `tan_rolling` / `hazard_logit_rolling` (annual
calendar-year-boundary refits on the strictly-prior expanding window; an
unsupportable window contributes declared absence, never zeros). Per-scorer
grids with baselines recomputed on each scorer's own grid, as v4.

## 4. Alarm rule (uniform q98; per-track arithmetic from published facts)

Alarm = top 2% of each scorer's own score grid, applied identically to both
baselines. Daily: ~5.0 alarms/yr; the ceiling of 4 needs precision ≥ ~20% —
v3 measured 23–29% at q98: demanding but reachable (v3/v4's frozen
arithmetic). Weekly: ~1.0 alarm/yr → the FA ceiling cannot bind; lift and
lead bind. **Monthly: ~0.24 alarms/yr → the ceiling cannot bind; lift and
lead bind (declared consequence, pre-run).** Quarterly: 1–2 alarms in the
whole window → as weekly.

## 5. Family and dispositions (all re-derived on a fresh fetch)

Probe of record: [`docs/probes/prereg_v5_source_probe.md`](../probes/prereg_v5_source_probe.md)
(criteria-first; GREEN/YELLOW/RED per candidate; verbatim findings).

- **Daily:** `FRED_T10Y2Y`, `FRED_T10Y3M`, `FRED_VIXCLS` (as v2–v4) +
  `FRED_DCOILWTICO` (WTI crude, EIA, daily 1986–; P1 GREEN).
- **Weekly:** `FRED_STLFSI4` (v4's passing indicator) + `FRED_MORTGAGE30US`
  (Freddie Mac PMMS, weekly 1971–; P3 GREEN, copyright line recorded) +
  `FRED_NFCI` (Chicago Fed, weekly 1971–; P4 GREEN). `ECB_CISS` keeps its
  declared keyless attempt — recorded, not substituted.
- **Monthly (new track):** `FRED_FEDFUNDS` (1954–; P5 GREEN) +
  `FRED_UMCSENT` (1952–; P6 GREEN, citation recorded, direction −1) +
  `FRED_KCFSI` **reassigned weekly→monthly** — its measured cadence is
  ~31-day; v4's weekly refusal is the evidence for the reassignment. No
  resampling then, none now.
- **Quarterly:** `BIS_CREDIT_GAP_US` (P7 revalidated GREEN: 274 rows,
  1957-Q4–2026-Q1, homogeneous series, terms unchanged, attribution
  recorded).
- **Excluded pre-fetch (probe dispositions):** `FRED_DTWEXBGS` — RED,
  history starts 2006-01-02 (P2); NY Fed recession probability — RED, the
  documented URL serves HTML and the plugin zoo has no NY Fed research
  transport (P8); BIS debt-service ratio — stays excluded on v4's recorded
  YELLOW (1999-Q1 start).
- **Re-derived at fetch, never skipped from memory:** `FRED_SOFR` (coverage),
  `FRED_BAMLH0A0HYM2` (licence, refused pre-download), `FRED_RRPONTSYD`
  (owner exclusion), the six operator-reported codes (no public source; the
  PRA probe confirmed bank-level data is supervisory-confidential).
- **Directions declared before any v5 fetch** in
  `backend/modules/data/semantics.py`, each with its literature rationale:
  DCOILWTICO +1 (Hamilton), MORTGAGE30US +1 (rate-shock channel), NFCI +1
  (tighter-than-average by construction), FEDFUNDS +1 (tightening channel),
  UMCSENT −1 (collapsing confidence = stress).

Projected testable family: **11 indicators, four tracks, three publishers**
(pending the frozen quality gate re-deriving every skip at fetch time).

## 6. Transport and licence

Keyed FRED API (`FRED_API_KEY` from the environment, never written to any
file, endpoints recorded `api_key=<redacted>`) + keyless BIS SDMX CSV
(quarter-end date convention; a payload mixing dimension values is a
format-drift refusal). Licence screen BEFORE download for every series
(FRED: the series' own notes vs the frozen prohibition patterns; BIS: the
live terms page must show its permission sentence or the series is refused
as `licence_unconfirmed` — the BoE-404 precedent). Licence lines and the BIS
attribution travel in the manifest.

## 7. Execution

In-process (declared deviation, as v1–v4). Sequence: **tag → fetch →
evaluate**, one run, zero retries; pre-metric infrastructure defects are the
only re-run grounds, logged with diffs and with zero metrics observed
(the v4 attempt-log discipline). The manifest (per-series SHA-256, licence
lines, redacted endpoints, measured frequencies, coverage) commits with the
report. Negative results published unchanged.
