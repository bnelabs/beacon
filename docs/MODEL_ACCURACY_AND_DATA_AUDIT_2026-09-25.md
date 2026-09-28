# BEACON — Live Model Accuracy Test & Data-Input Audit

**Date:** 2026-09-25 · **Stack:** 6.2.1 live (`efd972e`), all containers up
**Method:** fresh jobs through the live API + independent offline recomputation from raw artifacts + per-series data audit
**Artifacts:** jobs 37 (backtest) & 38 (prediction) in the DB; `.agent-state/verify_live_backtest.py`, `.agent-state/verify_per_source.csv`; failure-ledger entries L-64/L-65

> **Amendment (2026-09-25, later that day):** the coordinate audit
> (`.agent-state/audit_coordinate_systems.py`, per-series table
> `.agent-state/audit_coord.csv`) found that every pooled number in this report was
> computed in **mixed coordinates** — model predictions standardised by the
> checkpoint's `source_stats` (fit on the train subset, ending 2017-02-08), targets
> standardised on all pre-test rows (ending 2021-05-20). The defect was fixed in
> **PR #156** (merged; in release 6.2.2). Corrected consistent-coordinate pooled
> numbers (same n=25,264, targets resolved with the same precedence the engine uses —
> checkpoint stats where present, else pre-test stats): **R² 0.3606, MSE 6.4564,
> MAE 1.1835, directional 0.4889** (naive persistence 0.9987 / 0.4939). The model is
> still worse than persistence everywhere measurable — that conclusion is unchanged;
> what changed is by how much. The live re-run of the fixed backtest additionally
> excludes the two series whose *input* windows had no checkpoint statistics
> (FRED_SOFR, IR_ESTR — named in `non_comparable_series`), so n will be ≈22,621.
> All headline numbers below are the as-shipped 6.2.1 measurements (mixed
> coordinates) and are marked where the corrected value differs.

---

## 1. Executive summary

**The deployed model (job 26 checkpoint) is a weak pooled next-step forecaster and a strong
mean-reverter on a handful of series.** On the live out-of-sample window
(2021-05-21 → 2026-09-24, 34 macro/financial sources, 25,264 aligned one-step
predictions), the independently recomputed results are:

| Metric (standardized score space) | Deployed model, as shipped (mixed coords, job 37) | Deployed model, consistent coords (PR #156) | Naive persistence |
|---|---|---|---|
| Pooled R² | 0.188 | **0.361** | **0.999** |
| Pooled MAE | 1.32 | **1.18** | — |
| Directional accuracy | 0.449 (below coin-flip) | **0.489** | 0.494 |
| Beats naive per-source | 1 / 34 (the winner has n=4) | **0 / 35** (no winner at any n) | — |

The model's pooled accuracy is **strictly worse than "carry the last observation forward" on every
source with meaningful data, in either coordinate system**, and its average next-step
direction is below the persistence baseline in both (0.449 / 0.489 vs 0.508 / 0.494).
This is despite genuine, large out-of-sample skill on mean-reverting series (US rates R² 0.93–0.98,
EUR/CNY 0.96, WTI 0.90, credit spread 0.75, VIX 0.74, HSI 0.56) — real, but not enough to beat
persistence there either.

**Four root causes, all verified:**

1. **The shipped backtest measured a coordinate mismatch, not just the model (fixed, PR #156).**
   The model's predictions live in the checkpoint `source_stats` coordinate (fit on the train
   subset, ending 2017-02-08 05:36), while the backtest re-derived its targets on all pre-test
   rows (ending 2021-05-20 09:36). Comparing the two makes the pooled R²/MAE partly a unit
   conversion error: measured 0.188 mixed vs 0.361 consistent (n=25,264; per-series
   decomposition in `.agent-state/audit_coord.csv`). The fix resolves each series' target
   statistics with the same precedence the engine uses for its inputs, records the per-series
   provenance, and excludes the two series whose input windows had no checkpoint statistics
   (FRED_SOFR, IR_ESTR) instead of silently averaging them in.
2. **The shipped checkpoint is the epoch-1 (0-indexed) state of training.** Validation loss rose
   monotonically from 9.886 to ~11.0 over 40 epochs; best-epoch selection froze at epoch 0. The
   "trained" model is effectively an under-trained snapshot. The huge validation loss is driven
   mostly by 94,676 short AI4RISK "series" (2–6 points each, heavily zero-padded windows) that make
   up most of the 15,179 training entities and dominate the standardized-space loss scale.
   (Amendment: the epoch-0 best is a data-composition artifact — the AI4RISK tail carries 96.6%
   of the val SSE — not blanket undertraining; see §3.)
3. **Three of the 71 ingested series are semantically corrupt** and passed the quality gate
   silently: `BIS_CREDIT_TO_GDP_{US,EU,JP}` are per-date mixes of three different BIS series
   (proven: the parser drops dimension columns and an unstable sort picks the survivor — L-64),
   and `FRED_REPO_RATE` is actually the Fed RRP dollar *volume* stored as a repo *rate* (L-65).
4. **The 23 weakest sources are trending level series** (equities, gold, CPI, M2, bank aggregates)
   whose raw-level targets the 30-window standardized model cannot extrapolate — it predicts
   reversion to the 2000–2021 training mean (e.g. live prediction: NIKKEI 65,019 → 46,407 in one
   day, displayed as the *highest* risk score +2.40σ). This is the declared limitation from the
   2026-09-24 review, now quantified live.

**What works well (verified):** snapshot↔DB consistency (0 mismatches / 59 series), no
train/val/test leakage in the split design, clean gap handling (no forward-fill, gaps →
standardized mean with tracked observed fraction), honest uncertainty (44/71 conformal
intervals, 27 explicit refusals, risk level explicitly "uncalibrated"), deterministic inference
(jobs 28 and 38 identical to float precision), reproducible content-addressed snapshots.

---

## 2. Live accuracy test

### 2.1 Fresh backtest (job 37, live API)

`POST /api/v1/jobs {"job_type":"backtest", "trained_model_job":26, start 2021-05-21 →
end 2026-09-24, walk_forward 5-split expanding, max_steps 2000}` — completed in 265 s.

- 26,056 per-timestep predictions over **35 sources** (of 71 ingested); 25,264 aligned to
  ground truth (96.96%).
- Pooled standardized-space metrics: **R² 0.1879, MSE 7.7738, MAE 1.3217, RMSE 2.7882,
  directional 0.4491, hit rate 0.4491**.
- Ground-truth target = each series' standardized next-step value, standardized on the
  pre-test window only (leak-safe by construction) — but **not** in the same coordinate as
  the predictions, which live in the checkpoint `source_stats` (train-subject stats ending
  2017-02-08). This mixed-coordinate pairing is what the pooled numbers above measure;
  PR #156 closes it (see the amendment note at the top).
- **Walk-forward diagnostics: 0 folds executed.** Every series was skipped — the one-size
  5-fold expanding config requires ≥30 training samples in the *first* fold, which no
  in-window series satisfies (annual: 3–4 rows; quarterly: 19–20). The skips are recorded with
  reasons, but the "walk-forward" section of the result is empty — a reporting gap, not a
  hidden failure.
- Excluded from scoring (all documented): 30 low-frequency sources (<30 rows in window),
  2 SEC constant-marker series, and the AI4RISK network (94,676 entities, most with 1–8 rows).

### 2.2 Independent verification (recomputed from raw artifacts)

`.agent-state/verify_live_backtest.py` re-derives the backtest **without any backend metric
code**: raw panel (`data/jobs/20/timeseries.parquet`) + deployed checkpoint
(`data/jobs/26/best_model.pt`) only. Own standardization (checkpoint train-window stats per
series, ±10 clip, gaps→0), own sliding-window loop, own target derivation (pre-test
standardization), own alignment (window ending at t ↔ target at t+1, per-series seams), own
metrics.

**Reproduces job 37 bit-for-bit:** n = 25,264 · MSE 7.7738 · MAE 1.3217 · R² 0.1879 ·
directional 0.4491. The live API's numbers are therefore trustworthy (the *implementation*
reproduces exactly what it was asked to compute); the per-source table below is the verified
breakdown (the job result itself does not carry one). Caveat: both the job and this
recomputation score predictions and targets in the two different standardization coordinates
named in §2.1 — the mixed-coordinate defect, corrected in PR #156.

### 2.3 Per-source live results (2021-05-21 → 2026-09-24, standardized space)

*(As-shipped mixed coordinates — the job 37 measurement. The consistent-coordinate
per-source values, where targets use the checkpoint stats where present, are column B of
`.agent-state/audit_coord.csv`; for FRED_SOFR and IR_ESTR, which have no checkpoint
statistics, the consistent value is computed with the pre-test fallback and those two
series are excluded from the fixed live backtest's pooled metrics.)*

| Source | n | model R² | naive R² | model beats naive? |
|---|---|---|---|---|
| IR_US_2Y | 1304 | **0.984** | 0.997 | no |
| EXR_EUR_CNY | 1341 | **0.964** | 0.994 | no |
| IR_US_10Y | 1304 | **0.927** | 0.996 | no |
| COMM_OIL_WTI | 1303 | **0.900** | 0.971 | no |
| CREDIT_US_SPREAD | 1301 | **0.748** | 0.984 | no |
| STOCK_VIX | 1312 | **0.743** | 0.884 | no |
| EXR_EUR_JPY | 1341 | **0.705** | 0.997 | no |
| ECB_CISS | 177 | **0.668** | 0.878 | no |
| STOCK_HSI | 1283 | **0.557** | 0.991 | no |
| EXR_EUR_USD | 1341 | 0.483 | 0.990 | no |
| EXR_EUR_CHF | 1341 | 0.470 | 0.994 | no |
| FRED_STLFSI4 | 249 | 0.465 | 0.572 | no |
| FRED_KCFSI | 33 | −0.38 | 0.03 | no |
| COMM_GOLD | 1314 | −0.46 | 0.998 | no |
| STOCK_EUROSTOXX50 | 1314 | −0.46 | 0.996 | no |
| FRED_SOFR | 1303 | −0.59 | 0.999 | no |
| FRED_COMMERCIAL_PAPER | 248 | −0.66 | 0.968 | no |
| FRED_FINANCIAL_STRESS | 4 | −0.78 | −1.04 | **yes (n=4, not meaningful)** |
| STOCK_NIKKEI | 1276 | −0.89 | 0.998 | no |
| FRED_REPO_RATE | 1303 | −1.01 | 0.995 | no (data corrupt, L-65) |
| EXR_EUR_GBP | 1341 | −1.23 | 0.963 | no |
| IR_ESTR | 1340 | −1.86 | 0.994 | no |
| STOCK_SPX | 1310 | −2.68 | 0.998 | no |
| FRED_FED_BALANCE_SHEET | 248 | −2.70 | 0.999 | no |
| ECON_EU_HICP | 25 | −4.01 | 0.424 | no |
| MM_TED_SPREAD | 134 | −9.12 | 0.895 | no |
| ECON_US_UNEMPLOYMENT | 32 | −9.91 | 0.672 | no |
| BANK_US_RESERVES | 33 | −12.5 | 0.854 | no |
| FRED_BANK_ASSETS | 247 | −22.0 | 0.995 | no |
| BANK_US_COMMERCIAL_LOANS | 33 | −24.4 | 0.882 | no |
| BANK_EU_LOANS | 32 | −28.1 | 0.969 | no |
| MM_US_M2 | 33 | −57.5 | 0.985 | no |
| BANK_EU_DEPOSITS | 32 | −84.9 | 0.796 | no |
| ECON_US_CPI | 32 | −87.8 | 0.980 | no |

Reading: 12 sources have real skill (R² > 0.4, all mean-reverting) in these mixed-coordinate
numbers; 11 do in the consistent coordinates (the same mean-reverting tier, with ECB_CISS
dropping to 0.508 and EUR_USD/EUR_CHF/STLFSI4 falling below 0.4). Either way, 23–26 sources
are *worse than the pre-test mean* as predictors — the pattern is exactly "trending levels +
low-frequency + the corrupt RRP series." No source beats persistence in either coordinate
system. (R² in z-space equals R² in raw space *within one coordinate system*, since
denormalization is an affine map with positive std — which is precisely why mixing the two
coordinate systems corrupts the pooled metric.)

### 2.4 Live prediction (job 38)

`POST /api/v1/jobs {"job_type":"prediction", "trained_model_job":26, forecast_horizon:30}` —
completed in 1,151 s (regime nowcast ≈ 1,002 s = 87% of runtime).

- **71 predictions** (one standardized next-step value per source), mean risk 0.259.
- **Reproducibility:** identical to job 28 (run 2 h earlier, same data snapshot) to
  |Δrisk| ≤ 2.4e-7 — inference is deterministic.
- **Intervals:** 44/71 with split-conformal 90% intervals; **27 refused**
  (`insufficient_history_for_calibration`) — an honest refusal, not a silent gap.
- **Uncertainty:** all 71 `not_measurable_single_model` (ensemble_size=1 → no
  aleatoric/epistemic split) — declared, not hidden.
- **Regimes** (Student-t HMM nowcast, higher-variance state = "stress"): 24 stress / 21 calm
  / 26 none.
- **Top risk scores are level artifacts, not stress signals.** The score is
  `(predicted next level − train-window mean)/train-window std`:

  | Source | last actual | model next-step | displayed risk |
  |---|---|---|---|
  | STOCK_NIKKEI | 65,019 (09-18) | **46,407** (−28.6% in one day) | **+2.402** |
  | STOCK_SPX | 7,706 (09-23) | **6,005** (−22.1% in one day) | **+2.190** |
  | EXR_EUR_JPY | 180.57 (09-24) | 176.64 (−2.2%) | **+2.153** |
  | IR_US_2Y | 4.71 (09-22) | 4.814 (+10 bp) | +1.455 |
  | FRED_REPO_RATE | 0.46 (09-23) | 5.611 (+1,117%!) | −1.393 |

  The model is pulling trending indices back toward their 2000–2021 training mean; the
  "high risk" display is the predicted level's distance from that mean. For IR_US_2Y the
  same machinery produces a sensible +10 bp move. **The dashboard's risk ranking currently
  measures training-mean distance for trending assets, not stress.**

### 2.5 Interval coverage — why it can't be scored yet

Conformal intervals can only be validated against future actuals. The latest ingested data
ends 2026-09-22/24, and job 38 predicts *forward* from there, so **no out-of-sample interval
coverage measurement is possible until the next data collection lands**. The calibration
data (rolling held-out residuals) is leak-safe by construction (`_conformal_fit_from_scores`
uses windows disjoint from the scored window). Verdict: intervals are *methodologically sound,
empirically unvalidated* — revisit after the next ingest with a one-step-ahead coverage test.

---

## 3. Training pipeline review (job 26, data job 20)

- **Panel:** 517,625 rows; 15,179 training entities (70 macro feeds + 15,108 AI4RISK
  entities… 94,676 network edges appear in the raw panel; the checkpoint carries 15,179
  statistics keys).
- **Split (chronological):** train 2000-01-01 → 2021-06 (80% of span); val = last 20% of the
  train window (≈2016-10 → 2021-06); test = last 20% (≈2021-06 → 2026-09). Per-series z-score
  statistics are computed on the train split only; val/test reuse train statistics —
  **no train/val/test leakage**. Sliding windows overlap by design (each point appears in up
  to 30 windows) — standard for this architecture, no purged CV applied.
- **Epoch behavior (the key finding):** train loss 0.115 → 0.014; **val loss 9.886 → 11.0,
  monotonically worse**; best epoch = 0 (the first). `data/jobs/26/best_model.pt` literally
  stores `epoch: 0`. Every later epoch was rejected by model selection.
  Amended reading: the epoch-0 best is a **data-composition artifact, not blanket
  undertraining** — the AI4RISK tail (15,115 of 88,844 train windows = 17.0%; 6,778 of 25,897
  val windows = 26.2%) carries 96.62% of the validation SSE (val loss recomputed bit-exact:
  9.885547372289606). The val loss is ~10 because that tail's 2–6 point series are far from
  their own tiny per-series training statistics; model selection is responding to the tail's
  worsening, not to the macro feeds. Retraining with the degenerate tail handled (or split
  out) is the accuracy path — see §7.
- **Why val loss is ~10:** 94,676 AI4RISK edge "series" of 2–6 points each. Each contributes 1–2
  windows of 28–29 zero-padded inputs; targets are 2–4 point per-entity z-scores; the val
  window (2016-10 → 2021-06) is exactly where these short series' few late observations sit,
  often far from their 2–3 observation training statistics. They are ~75% of training
  records and dominate the pooled loss. They are degenerate inputs for a 30-window forecaster
  (the degenerate-standardization guard, L-60, skips only *constant* series; 2–6 point series
  pass).
- **Holdout reporting:** 34 low-frequency sources have **num_samples = 1** in the test split
  (one annual/quarterly point) — their per-source R² (reported 0.0) is undefined, and the
  baseline comparison measured only 30/65 sources (35 skipped). The headline
  "holdout pooled R² 0.859" is raw-scale pooled — **scale-dominated** by AI4RISK edges
  (values to 7e7) and large-bank series; it is not comparable to the z-space live R² 0.361
  (consistent coordinates; the shipped 0.188 mixed-coordinate number measures part unit
  conversion).
- **Checkpoint inconsistency:** `FRED_SOFR`, `FRED_BAMLH0A0HYM2`, `IR_ESTR` have **no
  source statistics and no embedding in the checkpoint** (66 sources registered, 15,179 stats
  keys — the two fields disagree). At inference they fall back silently: payload-window
  (in-sample) normalization + source-id 0 (i.e. the EXR_EUR_USD encoder/predictor). Their
  scores are produced by the wrong per-source components. (`stats_provenance` in job 37
  records this for exactly these 3.)
- **Walk-forward:** the training baseline comparison (3 splits, min_train 5) still skips 35/65
  sources; the live backtest walk-forward skipped 35/35 (0 folds). The "walk-forward
  validation" machinery currently contributes no evidence in either direction.
- **Reproducibility:** snapshot sha256-pinned (`fa319016…`), training attestation
  sha256-pinned (`13675d44…`), counts train 134,310 / val 231,373 / test 151,942 records.

---

## 4. Data-input audit (71 ingested series)

### 4.1 What is clean (verified)

- **Snapshot ↔ DB consistency:** all 59 macro series present in both stores match
  **exactly** (0 value mismatches) — the training panel and the observation API read the
  same certified rows. The 12 market-panel codes are intentionally not in the DB
  (skipped by design).
- **No NaNs, no constants** (except the 2 SEC event-marker series by design); all 60
  (Date, Value) series are internally consistent with their upstream sources (spot-checked
  against live FRED/DB).
- **Pipeline hygiene:** `cleaner.py`/`pit.py`/`formatter.py` do **no** forward-fill, back-fill,
  or retrieval interpolation; missing points become standardized 0 with a tracked
  observed-fraction; extremes clipped at ±10 z (L-60); degenerate standardizations refused.
- **Provenance:** append-only vintage log (every value carries job + attestation),
  content-addressed snapshots, quality attestation per collection.
- **Genuine-looking anomalies explained** (not defects): SPX min 676.53 (2009-03-09),
  NIKKEI 7,054.98 (2003), WTI −36.98 (2020), VIX/STLFSI4 large %-jumps (zero-crossings),
  US unemployment 2.36× (2020), HICP 3 zeros (minor), Fed balance sheet in $millions.

### 4.2 Defect 1 — BIS credit-to-GDP chimeras (L-64, OPEN)

`BIS_CREDIT_TO_GDP_{US,EU,JP}` are stored as quarter-by-quarter mixes of **three different
BIS series** (two levels + one gap, see §1). Evidence chain:

1. Live fetch of `WS_CREDIT_GAP/Q.JP` (2026-09-25, 3 identical responses, same md5): the CSV
   contains 658 rows = 3 blocks (CG_DTYPE A: 246q level 110.8–213.6; B: 206q level 137.0–217.7;
   C: 206q gap −29.7…+27.0), all overlapping on 206 quarters.
2. `_parse_bis_csv` drops all dimension columns, then `sort_values("date")`
   (unstable quicksort) + `drop_duplicates("date", keep="first")` — the survivor per date is
   whatever order the unstable sort leaves.
3. Running the **shipped parser** on the current response reproduces the stored values
   **exactly** (JP 2000-Q1 −23.11, 2000-Q2 213.48, 2000-Q3 186.45, …); a stable sort on the
   same file would give a pure level series. The stored mix is a sort-order artifact.
4. Identical values in DB + vintage log + training snapshot across jobs 15/16/20 — stable,
   so the pipeline is deterministic, but the *semantics* are not defined by any documented
   rule.
5. The catalogue also mislabels the endpoint: `WS_CREDIT_GAP` is the gap family, stored under
   "credit to GDP, percent."
6. Quality gate: row counts/missingness fine; KPSS (warning-only) finds the oscillation
   "stationary." No check inspects units or endpoint semantics.

### 4.3 Defect 2 — FRED_REPO_RATE is RRP volume (L-65, OPEN)

Endpoint `RRPONTSYD` = Overnight RRP Facility **dollar volume** (billions USD, daily), stored
under code/unit "repo rate / percentage". Values 0 → 2,553.7 (2022 peak ≈ $2.55T; 2026-09-24
= 0.63, matches live FRED). The upstream data is genuine and consistent — only the label is
wrong. Live prediction moves it +1,117% in one day; live R² −1.01.

### 4.4 Staleness & degenerate series (no defect in the pipeline — data availability)

| Series | last observation | note |
|---|---|---|
| FRED_FINANCIAL_STRESS | 2022-01-07 | 4 rows in test window |
| MM_TED_SPREAD | 2022-01-21 | 134 rows in window |
| ECB_CISS | 2025-05-02 | 177 rows in window |
| WB_DOMESTIC_CREDIT_SA | 2017 | World Bank series ended |
| WB_BANK_NPL_JP / CAPITAL_RATIO_JP | 2022 | ended |
| WB_BANK_NPL_DE | 4 rows total | nearly empty |
| IR_ECB_DEPOSIT | 64 obs | sparse-but-genuine |
| IR_EURIBOR_1M | 43 obs | sparse-but-genuine (EURIBOR discontinued 2024 → expected) |
| SEC_BANK_FINANCIALS / SEC_INSTITUTIONAL_HOLDINGS | constant 1.0 markers | event flags by design; degenerate inputs |

### 4.5 Source-store health (2026-09-25)

`data_sources`: ECB/FRED/AlphaVantage/SEC/active; **Kaggle Bulk dead** (empty config `{}`, no
cache, 20 consecutive failures — the old backfill route is gone); **World Bank / IMF /
AI4Risk / Yahoo in error state** (Yahoo last successful 2026-09-22; market series are 1–3
days stale at the panel edge). No silent stale-cache degradation was active in job 20
(no `degraded` entries in its collection report).

---

## 5. Pros (verified strengths)

1. **Leak-safe evaluation design.** Train-only z-score statistics; val/test reuse train
   stats; backtest targets use only pre-test data. The 2026-09-24 campaign (L-51…L-63)
   fixed the leaky paths and the live backtest's numbers reproduce bit-for-bit
   independently. Amended: the leak-safety was real, but the target re-fit on all pre-test
   rows created a *coordinate* mismatch with the checkpoint's train-subset statistics —
   fixed in PR #156, which also records the per-series provenance so the class of bug
   is visible in the result.
2. **Real skill where the design fits.** R² 0.47–0.98 on mean-reverting series (rates, FX, WTI,
   credit spreads, VIX, HSI) — a 5-year out-of-sample result no amount of in-sample tuning
   manufactures. The model learns genuine short-horizon mean-reversion structure.
3. **Honest uncertainty reporting.** Conformal intervals with explicit refusal (27/71),
   "uncalibrated" risk level instead of invented bands, `not_measurable_single_model` instead
   of a fake aleatoric/epistemic split, skip reasons recorded for every walk-forward skip.
   The system repeatedly says "I don't know" where it doesn't know.
4. **Clean data handling.** No fillna(0), no forward-fill, gaps as explicit standardized 0 with
   observed-fraction tracking, ±10 clip, degenerate-standardization guard, append-only vintage
   log, content-addressed snapshots, snapshot↔DB exact consistency.
5. **Deterministic, reproducible inference.** Jobs 28 vs 38 (same data, 2 h apart): identical to
   2.4e-7. Training artifacts hash-pinned.
6. **Operational robustness.** Per-source failure isolation, strict-JSON results, retry with
   backoff, provider-degradation flagging, 6.2.1 stack healthy, no in-flight jobs.

## 6. Cons (verified weaknesses)

1. **Under-trained shipped model.** Best epoch = 0; val loss monotonically worse (9.886 →
   11.0); the checkpoint is the first-epoch state. Model selection correctly *rejected* later
   epochs — but nothing diagnosed why validation loss is ~10 in standardized space (AI4RISK
   dilution), so 40 epochs produced an epoch-1 artifact.
2. **Worse than naive persistence everywhere measurable — in both coordinate systems.**
   Mixed coords (as shipped): pooled R² 0.188 vs 0.998, directional 0.449 vs 0.508.
   Consistent coords (PR #156): pooled R² 0.361 vs 0.999, directional 0.489 vs 0.494.
   Zero sources with meaningful data beat carry-forward either way. As a *pooled*
   next-step forecaster the deployed model currently adds no value over a baseline
   with no parameters.
3. **Training data diluted by degenerate entities.** 94,676 two-to-six-point AI4RISK edges
   dominate the loss; 34 low-frequency sources get a single holdout sample; the pooled raw R²
   0.859 headline is scale-dominated and misleading.
4. **Semantically corrupt data passes silently.** BIS chimeras (L-64) and RRP-as-repo-rate
   (L-65) reach training, the DB, and live predictions; the quality gate has no unit/semantics
   check, and KPSS (warning-only) cannot see a level/gap mix.
5. **Trending levels break the score semantics.** For equities/gold/CPI/M2/bank aggregates the
   model predicts reversion to the 2000–2021 mean; the dashboard's top "risk" sources are
   these level artifacts (NIKKEI +2.40σ = predicted −28% one-day crash), not stress.
6. **Checkpoint/inference inconsistency.** 3 feeds (SOFR, BAMLH0A0HYM2, ESTR) silently fall
   back to in-sample window stats + the wrong source embedding (id 0 — the FIRST trained
   source's embedding, not an untrained slot). Amended: both halves are now *recorded* in
   the results — `stats_provenance` (6.2.1) and `embedding_fallback` /
   `embedding_provenance` (PR #157, in release 6.2.2); the checkpoint-side inconsistency
   itself is fixed at retrain time (register every trained feed in `sources`, refuse loudly
   instead of embedding-id-0).
7. **Walk-forward validation is empty** in both training (35/65 skipped) and live backtest
   (0/35 folds) — the "rigorous validation" story currently rests on a single chronological
   holdout.
8. **30 of 71 sources are unscoreable by the backtest** (<30 rows in window) — the model's
   "71-series" claim is validated on 34–35.
9. **Runtime:** prediction job 19.2 min, 87% spent in regime EM nowcast (known, L-62 lineage).

## 7. Recommendations (prioritized)

1. **Retrain with the degenerate tail handled** (highest accuracy impact): exclude or
   down-weight 2–6 point entities (or feed AI4RISK through its own panel path once it exists);
   verify val loss falls below ~1.0 before trusting model selection again; re-run the live
   backtest and expect the pooled number to move toward the per-source strong tier.
2. **Fix the two data defects (L-64, L-65)** before the next training: BIS parser
   (dimension-aware, stable dedupe, explicit CG_DTYPE) and re-point `FRED_REPO_RATE`; add a
   quality-gate unit/magnitude assertion so the class of bug can't pass silently again.
3. **Retarget trending series to returns/deltas** (declared open item #4, now quantified):
   one-step *changes* make risk scores sign-consistent, make pooled directional comparable to
   0.5, and remove the NIKKEI-style level artifacts from the dashboard.
4. **Make the checkpoint self-consistent:** every trained feed registered in `sources` with
   its stats; fallback scoring should refuse loudly instead of silently using embedding 0.
   (Half done: PR #157 records the fallback in the results instead of logging it; the
   checkpoint-side fix lands with the retrain.)
5. **Frequency-aware walk-forward** (per-cadence fold config) so the diagnostic actually runs;
   report the naive-persistence delta as the primary accuracy statistic until the model beats
   it.
6. **Validate interval coverage** at the next ingest: one-step-ahead empirical coverage of the
   44 conformal intervals (expected ≈ 90%).
7. Optional: ensemble_size ≥ 2 (open item #1) to make epistemic/aleatoric uncertainty
   measurable and enable the designed refusal-on-epistemic-spike.

**Immediate (in flight as of this amendment):** ship release 6.2.2 (PR #156 + PR #157),
deploy in a safe window, and re-run the live backtest to verify the fixed numbers —
expect pooled R² ≈ 0.36, directional ≈ 0.49, n ≈ 22,621, with FRED_SOFR and IR_ESTR named
in `non_comparable_series` and per-series `target_stats_provenance`/`embedding_provenance`
visible in the result.

---

## 8. Appendix — jobs & artifacts (2026-09-25)

| Job | Type | Duration | Outcome |
|---|---|---|---|
| 37 | backtest (model 26) | 265 s | 25,264 aligned; R² 0.1879; directional 0.4491; walk-forward 0 folds (all skipped, reasons recorded) |
| 38 | prediction (model 26) | 1,151 s | 71 sources; 44/71 conformal, 27 refused; regimes 24/21/26; identical to job 28 (2.4e-7) |

- Independent recomputation: `.agent-state/verify_live_backtest.py` → exact match with job 37;
  per-source table `.agent-state/verify_per_source.csv` + naive-baseline comparison.
- Raw job results: `/tmp/job37.json`, `/tmp/job38.json`, `/tmp/job20.json`.
- Failure ledger: **L-64** (BIS chimeras, OPEN), **L-65** (RRP-as-repo-rate, OPEN).
- Data audit scripts from earlier this session: `.agent-state/audit_series.py`.

*Report generated from live evidence only; every number above was produced or independently
recomputed on 2026-09-25 against the running 6.2.1 stack. Amended later the same day for
the coordinate-system defect (PR #156): the as-shipped pooled numbers are retained as the
verified 6.2.1 measurement, with the consistent-coordinate values given wherever the
correction changes a conclusion.*
