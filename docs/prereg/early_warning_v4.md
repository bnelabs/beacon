# Pre-registered early-warning evaluation — protocol v4

**Status: FROZEN, pending run.** Machine-readable half:
[`configs/event_eval_v4.yaml`](../../configs/event_eval_v4.yaml). Owner
sign-off: given in chat on 2026-09-18 ("ok do all", approving the recorded-axes
resumption exactly as the v3 record described it: rolling refits + weekly/
quarterly tracks admitting the credit-gap family, every grading criterion
frozen). Committed and git-tagged `prereg-early-warning-v4` **before** the
run; after the tag, changes require protocol v5 plus a CHANGELOG entry.

**Why v4 exists.** v3's terminal clause parked the line and recorded the only
two axes a resumption would carry: (1) **rolling refits** — the discipline the
hazard architecture actually needs, after v3's frozen hazard logit collapsed
out-of-sample (AUC 0.39/0.44: an 18-year extrapolation of a pre-2006 fit does
not survive the QE-era regime change); and (2) **weekly/monthly tracks
admitting the credit-gap family** — the literature's best EWS variables are
not daily, and v1–v3 froze a daily step, so they could never enter the
family. v4 tests exactly those two axes and **changes no grading criterion**.

**Outcome handling (declared now, honoured either way).** PASS (family claim
warranted) → the README claim gate moves, carrying these numbers. FAIL → the
line **remains parked** with a four-run documented record; there is no planned
v5 — any further iteration needs a new owner decision and new recorded axes,
exactly as v4 needed. Both outcomes are publishable; neither gets argued with
after the fact.

## 1. What is frozen identically (by shared code, not by promise)

The four criteria (median lead ≥ 10 business days; ≤ 4 false alarms per quiet
year; AUC and AP strictly above persistence AND AR(1); AP above the event base
rate with a permutation p surviving Holm–Bonferroni at α = 0.05), the labeller
quantile (0.95), the windows (train ≤ 2006-12-31; eval 2007-01-01 →
2024-12-31), the model config and seed protocol (seed 11), the baseline
definitions, the permutation test (1000 shuffles, seed 20260917), the family
rule (≥ 3 testable; ≥ half of tested pass), the single-run rule, and the
tag → fetch → evaluate sequence. The runner enforces this structurally: one
shared constant block, one shared evaluation path; `TRACK_PARAMS["daily"]`
re-states the frozen v1–v3 constants and a pinned test asserts the equality.

## 2. Tracks (new mechanics; data-availability only)

| Track | Series | horizon | min_duration | lead floor | max_lead | steps/yr | hazard lookback |
|---|---|---|---|---|---|---|---|
| daily | T10Y2Y, T10Y3M, VIXCLS | 21 | 5 | 10 steps (=10 bd) | 42 | 252 | 63 |
| weekly | STLFSI4, KCFSI, (CISS attempt) | 4 | 1 | 2 steps (≈10 bd) | 8 | 52 | 13 |
| quarterly | BIS_CREDIT_GAP_US | 1 | 1 | 1 step (≈63 bd, **stricter**) | 2 | 4 | 1 |

The weekly/quarterly rows translate the same design intent (~21-bd move
horizon, ~5-bd persistence, ≥10-bd lead floor, ~one-quarter lookback) onto
coarser grids at the coarsest granularity each grid can express. The
quarterly horizon (1 step ≈ 63 bd) is *coarser* than the daily intent —
acknowledged here, declared before the run, not hidden. Frequency is verified
per track at fetch; a mismatch is a data-availability skip — series are never
resampled.

## 3. Rolling refits (the axis v3's collapse diagnosed)

Refit at **every calendar-year boundary** of the evaluation span, on the
**expanding window of all observations strictly before the boundary**
(strictly causal — a boundary never sees a later row; a pinned test asserts
it). Identical architecture, config and seed protocol (`torch.manual_seed(11)`
before every refit). Each year is scored by the checkpoint fit before that
year began, with `sequence_length` rows of *past* observations as prediction
warm-up. A boundary whose window cannot support the fit (< `sequence_length`
+ 10 rows; or, for the hazard scorer, no training-span onsets) contributes
**no scores for that year — declared absence, not zero**. Rolling scorers can
therefore cover eval steps the frozen TAN's eval-only warm-up drops; v4
declares **per-scorer grids**: each scorer is graded against baselines
recomputed on its own grid, with the grid recorded in the report.

Four scorers, all declared pre-run: `tan_frozen` and `hazard_logit` (identical
to v3 — on unchanged sources they reproduce v3's numbers, the run's own
reproducibility check) and `tan_rolling`, `hazard_logit_rolling` (spec above).
Holm pools **every** scorer–indicator pair: four scorers quadruple the
hypotheses and the adjustment sees all of them.

## 4. Alarm rule (uniform quantile, per-track arithmetic from published facts)

Alarm on the top 2% of each scorer's own score grid (q98, uniform). From
published v2/v3 numbers only: daily ≈ 5.0 alarms/yr, so the ceiling of 4
requires precision ≥ ~20% — v3 measured 23–29% at q98: demanding but
reachable. Weekly ≈ 1.0 alarm/yr and quarterly ≈ 1–2 alarms in the whole
18-year window, so at those cadences the FA ceiling **cannot bind for any
precision** — the binding criteria there are lift and lead. Both consequences
are declared before the run, not discovered after it.

## 5. Family and dispositions (all re-derived on a fresh fetch)

Entering: the daily trio (as v2/v3); weekly `FRED_STLFSI4`, `FRED_KCFSI`
(registry directions predate v4); quarterly `BIS_CREDIT_GAP_US` =
`WS_CREDIT_GAP/Q.US.P.A.C.E` — the **gap** (CG_DTYPE=C; A/B are levels), US
private non-financial, quarterly 1957-Q4 onward, keyless, licence GREEN with
attribution. `ECB_CISS` keeps its declared v1-style keyless FRED attempt; the
source probe found the ECB data-API flow mis-resolves to `ECB_FMD2` and the
legacy SDW host does not connect, so its skip will be **recorded, not
substituted**. The BIS **debt service ratio** was probed keyless-fetchable but
**YELLOW** (US history starts 1999-Q1 — ~32 pre-2007 quarters cannot honestly
train the declared architecture) and is **excluded pre-fetch** under the
probe's declared disposition rule. Skips re-derive at fetch: SOFR (coverage),
HY OAS (licence — refused pre-download), RRPONTSYD (owner exclusion), six
operator-reported codes (no public source). Probe record:
[`docs/probes/prereg_v4_source_probe.md`](../probes/prereg_v4_source_probe.md).
Direction for `BIS_CREDIT_GAP_US` (+1: widening gap = credit boom = risk
build-up) is declared in the registry **before any v4 fetch**, with rationale.

## 6. Transport and licence

FRED: keyed (`FRED_API_KEY` from the environment, never written to any file;
recorded endpoints redacted). BIS: keyless SDMX CSV from stats.bis.org;
quarter periods map to quarter-**end** calendar dates (declared convention); a
payload mixing dimension values is a format-drift refusal, never a guess.
Licence screen **before every download**: FRED series notes and the live BIS
terms page (`data.bis.org/help/legal`) against the same prohibition patterns;
for BIS the permission sentence itself must be observable on the live page —
its absence means drift and the series is refused as `licence_unconfirmed`
(the BoE-404 precedent). Attribution recorded in the manifest: *"Source: BIS
Data Portal - Bank for International Settlements"*.

## 7. Execution

Tag → fetch → evaluate, one run, zero retries; re-runs only for documented
pre-metric infrastructure defects, logged with diffs. In-process (declared
deviation, as v1–v3). Expected wall time on the reference box (2 CPU): ~45–60
minutes (≈ 108 small rolling refits + 6 frozen fits + permutation tests over
the pooled pairs), sequential, explicit teardown between fits.
