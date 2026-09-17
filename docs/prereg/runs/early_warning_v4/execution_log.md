# Execution log — early_warning_v4 (single-run record)

**Tag:** `prereg-early-warning-v4` → commit `e72581b` (protocol document,
config, runner with tracks/rolling scorers/BIS transport, registry direction,
contract tests — all frozen before any fetch).

**Sequence (declared):** tag → fetch → evaluate (the v3 sequence). The fresh
keyed FRED fetch and keyless BIS fetch ran after the protocol tag and before
any metric; the manifest with per-series SHA-256 hashes, fetch timestamps,
licence lines and redacted endpoints commits with this report, so the data
the run consumed is exactly auditable. `FRED_API_KEY` was read from the
environment only; grep of every committed path under `data/prereg/v4/`
confirms the key appears in zero files. The licence screen ran before every
download: `FRED_BAMLH0A0HYM2` was refused pre-download on its prohibition
language (no prohibited bytes exist in this directory); the BIS screen read
the live terms page (`data.bis.org/help/legal`) and recorded the permission
sentence verbatim plus the required attribution.

## Attempt log (full transparency)

| Attempt | When (UTC) | Outcome |
|---|---|---|
| 1 | 2026-09-17 19:45:36 → ~19:47 | **killed by the execution environment** (the launching shell's process group was SIGKILLed at its 120 s call timeout; `nohup` does not survive a group kill). Got partway through the first indicator's rolling refits (`work/FRED_STLFSI4/rolling_tan_2007…2014`). **No metric was computed, logged or observed** — the buffered stdout died with the process; zero results existed to bias a restart. Intermediate work dirs deleted before attempt 2. |
| 2 | 2026-09-17 19:58:35 → 20:14:45 | **aborted pre-metric: executor defect.** The per-scorer-grid path ranked rolling scorers against the primary grid's labels (`_score_card` closed over `events` instead of using the handed `ev`): `FRED_STLFSI4` raised `ValueError: labels and scores must have the same length, got 910 and 939` **before any metric existed**, and the mismatch was structural — every indicator's rolling grid differs from the frozen TAN's warm-up-truncated grid, so all five were deterministically doomed. Observed: the traceback and training-loss lines only (no criterion-adjacent number for any indicator). Terminated at 20:14:45 rather than burn 35 minutes producing five recorded infrastructure failures. Fix: two references in `_score_card` (`roc_auc(ev, sc)`, `average_precision(ev, sc)`) plus an end-to-end regression test that reconstructs the exact grid mismatch synthetically and pins criteria on both grids (`TestPerGridScoringEndToEnd`). Diff vs tag touches only those lines + the test. Work dirs deleted before attempt 3. |
| 3 | 2026-09-17 20:18:26 → 21:57:10 | **evaluated — the run of record** (5 indicators × 4 declared scorers, zero retries, zero configuration changes; ~99 minutes on 2 CPUs, peak RSS ~450 MB, fully detached) |

Both restarts fall under the run rules' clause for documented pre-metric
infrastructure defects: **no metric for any indicator was computed, logged or
observed in either attempt** — there were no results to bias a restart, and
the frozen rules, family, criteria and data bytes were identical every time.


**Pre-metric executor defects, fixed after the tag and recorded with diffs:**
(1) the BIS licence-line extraction at the tag recorded JSON-LD page
furniture instead of the terms sentence (a loose `licen` pattern matched the
page header); fixed before the fetch re-run, which the run rules' documented-
defect clause covers. (2) the per-scorer-grid scoring path ranked rolling
scorers against the primary grid's labels (attempt 2 above). Both fixes live
on `fix/prereg-v4-licence-lines`; `git diff prereg-early-warning-v4 HEAD`
touches only `_bis_licence_screen`'s text extraction, `_score_card`'s two
grid references, and the added pinned tests — **no protocol constant,
criterion, family entry, alarm rule or scorer spec changed**; the YAML
precedence clause covers the executor. The fetch phase was re-run in full
before any metric after fix (1); both fetches produced the same five testable
indicators and the same four skips.

## Fetch facts (manifest of record, attempt-2 state)

- **Testable (5):** `FRED_T10Y2Y`, `FRED_T10Y3M`, `FRED_VIXCLS` (daily,
  coverage 0.96/0.96/0.97, 7 episodes each); `FRED_STLFSI4` (weekly track,
  coverage 1.00, 7 episodes, 1,618 rows from 1993); `BIS_CREDIT_GAP_US`
  (quarterly track, coverage 1.00, 7 episodes, 274 rows, 1957-Q4 → 2026-Q1,
  keyless SDMX CSV, licence GREEN with attribution).
- **Skipped (4), each by a declared rule, none resampled or substituted:**
  `FRED_KCFSI` — `frequency_not_weekly`: FRED serves it **monthly** (median
  gap 31 days, 419 rows from 1990-02); the protocol declares no monthly
  track, so the weekly track refused it. `FRED_SOFR` — coverage 0.36 (daily
  from 2018-04). `FRED_BAMLH0A0HYM2` — licence prohibits reproduction,
  refused **pre-download**. `ECB_CISS` — declared keyless FRED attempt
  failed (metadata HTTP 400); the source probe independently found the ECB
  data-API flow mis-resolves and the legacy SDW host does not connect —
  recorded, not substituted (the v1 precedent).
- **Excluded (7):** `FRED_RRPONTSYD` (owner exclusion) and the six
  operator-reported codes (no public source) — as every version before.

## Verdict (published unchanged)

**Family claim: NO — 1 of 5 tested indicators passed** (testable-family
minimum of 3 met; the family rule requires at least half). Under the outcome
handling frozen before the run, the early-warning line **remains parked** with
a four-run documented record; there is no planned v5 — any further iteration
needs a new owner decision and new recorded axes.

**The record's first criteria-passing pair:** `FRED_STLFSI4` (weekly track)
via the **frozen** hazard logit passed all four criteria — AUC 0.9223,
AP 0.3836, median lead 2.0 weeks (≈ 10 business days, at the weekly floor),
0.483 false alarms per quiet year (ceiling 4), strictly above BOTH baselines
on AUC and AP, permutation p = 0.001, Holm-surviving across the 20-pair
pool. One passing pair of twenty tested does not warrant the family claim,
and is published as the fact it is — not upgraded into a claim.

**What the run established (all pre-declared as possible outcomes):**

- **Rolling refits did not rescue the daily family** — the axis v3's hazard
  collapse motivated is empirically closed for these indicators: T10Y3M's
  rolling TAN got *worse* (FA/quiet-yr 4.20 → 5.37, median lead 10.0 → 7.5
  steps, below the floor); T10Y2Y and VIXCLS rolling ≈ frozen (AUC 0.5565 vs
  0.5547; 0.9216 vs 0.9257). Regime drift was not what held the daily family
  back.
- **The quarterly credit gap was weak under this operationalisation:**
  BIS_CREDIT_GAP_US scored AUC 0.39–0.65 across its four scorers, detected no
  event within max_lead (median lead undefined), on only 3 labelled events in
  72 quarters — under-powered by construction at quarterly resolution. The
  literature's best EWS variable did not demonstrate warning value *in this
  test*; that is a statement about this test as much as the variable, and it
  is published either way.
- **The winning combination was weekly cadence + onset-hazard architecture** —
  and the *frozen* hazard beat its rolling counterpart on STLFSI4 (lift
  criterion), the opposite of the v3 diagnosis' expectation. Recorded as the
  finding it is.
- **Reproducibility held a fourth time:** every frozen scorer × daily
  indicator pair (6 of 6) matches v3's published AUC/AP exactly, on a fresh
  fetch with new SHA-256s recorded in the manifest.

