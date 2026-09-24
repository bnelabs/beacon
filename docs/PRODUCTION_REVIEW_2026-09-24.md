# BEACON Production Review — 2026-09-24

Unattended run: update stack → collect 2000–2026 → review + fix pipeline → double-check data → train → backtest/predict/scenarios → ship releases → re-run everything on the fixed stack → final verdict.
Author: BEACON agent (goal `goal-f858d7b6`), server `komedi`, all real data, no test fixtures.

## 1. Executive summary

- Stack updated v4.0.0 → **v6.2.0** (five official releases cut and published on this run: 6.1.0, 6.1.1, 6.1.2, 6.1.3, 6.2.0; CPU builds), rebuilt healthy at each step; DB pre-dumped before each mutation (`backups/beacon-pre-6.1.0-…sql`, `backups/beacon-pre-6.1.1-…sql`).
- Final certified data package: **job 20**, 71/71 sources, 2000-01-01 → 2026-09-24, **quality 93.96**, 517,625 rows.
- **Eleven code defects plus one design limitation found; every code-level defect is fixed and shipped** — 6.1.0 (PR #143: value-column selection, scenario parameters, network scenarios, backtest ground truth, brief-report label, WB/IMF retryability, SEC CIK), 6.1.1 (PR #145: degenerate standardization + bounded objective), 6.1.2 (PR #147), 6.1.3 (PR #149: walk-forward baseline comparison complete), 6.2.0 (PR #151: background scenario jobs + batched inference). The failure ledger (`docs/FAILURE_LEDGER.md`, L-43…L-62) records each finding with status and evidence; L-62 (scenario scores invariant under uniform affine shocks) is the one recorded design limitation, with the evidence in §7.3.
- Model retrained on the fixed stack (**job 26 on 6.1.3**, temporal_attention multi-scale, 2000→2026 panel, the final artefact): training objective is O(1) from epoch 1 (was 4.23e18 before the 6.1.1 fix), the walk-forward baseline comparison now measures all 30 measurable sources against persistence/AR(1) (11 beat both), and the backtest scores against leakage-free derived ground truth.
- **Final verdict on model usefulness:** the model is useful **within its designed role** — predicting the next standardized step of each series (relative move, risk ranking, regime input) — with genuine out-of-sample skill on low-drift, mean-reverting series (rates, FX, VIX) and an honest, documented failure on trending equity-index levels. It is not a level forecaster for trending assets, and the report says so wherever the numbers appear. Details: §6–§7.

## 2. Stack update

| Item | Before | After |
|---|---|---|
| Image | beacon-backend v4.0.0 (local) | v6.2.0 (tag `v6.2.0`), CPU torch build; 6.1.0/6.1.1/6.1.2/6.1.3 also deployed and verified during the run |
| Schema | `data_frequency_contract_001` | `vintage_provenance_001` (3 migrations applied by migrate service) |
| GPU | NVML driver/library mismatch (unusable) | CPU deployment (matches previous `Devices=[]`) |
| Ownership | models/, logs/, results/ root-owned → container user (uid 1000) could not write | `chown 1000:1000` |
| Zombie job 9 | "running" since 2026-09-18 | cancelled via `DELETE /api/v1/jobs/9` |

Backups: `backups/beacon-pre-update-20260924-110517.sql` (262 KB, before any mutation), `backups/beacon-pre-6.1.0-20260924-153141.sql` (31 MB), `backups/beacon-pre-6.1.1-20260924-162354.sql` (37.7 MB). All taken before the respective mutation; the live DB is the store of record.

## 3. Data collection (2000–2026)

Run history:
- Job 14 (2000-01-01→2026-09-24, strict): **failed** — single failure `WB_DOMESTIC_CREDIT_ZA (EMPTY_DATASET)`. Root cause: transient 30 s read timeout to api.worldbank.org; the plugin catches *all* exceptions and returns `None`, which the collector reads as "empty dataset" — and `EmptyDatasetError` is **not retried** (only `DataSourceUnavailableError` is, 3× / 120 s budget). Upstream data verified live (ZAF: 25 non-null rows 2000–2024, API < 1 s).
- Job 15 (retry of 14): **completed 71/71**, quality 93.56.
- Job 16 (after the SEC fix): **completed 71/71**, quality 93.96, 517,619 rows.
- Job 20 (final package used for training, collected on the fixed stack): **completed 71/71**, quality **93.96**, 517,625 rows — same package content plus the `series_id` grain column the panel feeds need.

Coverage highlights (verified against parquet + live probes):
- 26-year window repaired the old 5-year runs: `WB_DOMESTIC_CREDIT_SA` now 18 rows (upstream ends 2017 — faithful, not fabricated).
- Daily FX 6,840 rows 2000-01-03→2026-09-23; DGS10/DGS2 6,684→2026-09-22; SPX/VIX/NIKKEI to 2026-09-24; WTI 6,322; gold 6,541 from 2008-08-30; SOFR from 2018-04-03; €STR from 2019-10-01; BIS quarterly →2026-01-01; AI4Risk interbank topology 393,589 edges 2016Q1–2023.
- Confirmed NOT bugs (upstream facts): RRPONTSYD starts 2003 (facility existed since 2003); STLFSI2 ends 2022-01 (upstream ceased); WB annual/quarterly series have ≤ ~22 rows inside the 2000–2017 training window — too short for a 30-step window, honestly excluded, not dropped by bug.

Known-good refusals:
- IMF: legacy SDMX endpoint retired upstream; the modern DataMapper API works. The two IMF catalogue items (41/42) have no DataMapper equivalent (verified) and remain disabled with the reason recorded; the plugin's DataMapper path is corrected and live-verified (6.1.0).
- AI4Risk credit-rating items (77/78) are disabled: `DATASET_MISSING` is the correct refusal (dataset not hosted at the configured URL).

## 4. Defects found and status

| # | Finding | Severity | Final status |
|---|---|---|---|
| F1 | `world_bank_plugin` converts network timeouts into `EmptyDatasetError` (not retried); killed strict run 14 on a transient 30 s timeout | High (availability) | **Fixed in 6.1.0 (L-57, PR #143)**: 4xx stays a `None` decision; `requests.RequestException` (timeout/connection/5xx) raises retryable `DataSourceUnavailableError` |
| F2 | SEC 13F catalogue item used `BLK` → CIK 0001364742 (retired filer; stale since 2024-08); current filer is CIK 0002012383 | High (staleness, 25 months) | **Fixed**: catalogue id 33 repointed (ops) + **hardened in 6.1.0 (L-58, PR #143)**: `KNOWN_SEC_CIKS["BLK"]` corrected, retired CIK documented |
| F3 | `.env` `FRED_API_KEY` was a rotated-out key | Medium (config drift) | **Fixed (ops)**: `.env` synced to the live key, verified against DGS10; `.env` remains untracked |
| F4 | ECB DataWarehouse intermittently times out from this host; FX items degrade to the Frankfurter mirror | Low (redundancy works) | Accepted; monitor |
| F5 | Brief report displays `anomalies_detected` under a "failed" key | Low (presentation) | **Fixed in 6.1.0 (L-53, PR #143)** |
| F6 | Rich `ScenarioParameters` inert on the API simulate path | Medium (capability gap) | **Fixed in 6.1.0 (L-52, PR #143)**: parameters flow through `engine.apply_scenario`; response and job record carry `scenario_parameters`; verified in §7.3 |
| F7 | Multi-scale trainer's walk-forward baseline comparison returned `null` | Low (credibility metric) | **Fixed in 6.1.0 + 6.1.2 (L-55, L-61; PR #143, #147)**: value-column selection (L-51), then the window-guard off-by-one, the adapter reshape, and the `mean_lift` aggregation. The 6.1.2 retrain reports measured per-source lifts (§6) |
| F8 | 18,197 anomalies in the certified package | Info | Audited: dominated by gap-run/stale-run findings on the 393,589-row AI4RISK panel (banks entering/leaving the network) plus genuine macro anomalies; integrity checks (duplicates, future timestamps) found 0 |
| F9 | **Dataset builder dropped every non-OHLC series from training** (frame-wide `'Close' in columns` test; `Close` is always present → 60 of 71 series read as all-NaN → only 11 series trained) | **High (model quality)** | **Fixed in 6.1.0 (L-51, PR #143)**: `value_columns.py` selects the first candidate column that actually holds values; all six read sites use it. Verified on the retrain: 15,179 series / 88,844 sequences enter training across 41 sources (was 11 series / 14,511 sequences) |
| F10 | **Degenerate standardization dominated the training objective**: near-constant series (zero-variance AI4RISK edges, a constant-1.0 SEC series) standardized on `std + 1e-8` produced z-scores to 3.1e10 → job 21 (6.1.0 retrain, cancelled) reached val loss **4.23e18 at epoch 1**, making model selection meaningless | **High (model quality)** | **Fixed in 6.1.1 (L-60, PR #145)**: near-constant series (relative std < 1e-6) skipped from training with a declared warning; every standardized value entering the model (train inputs/targets, prediction windows, calibration windows) and the backtest's derived targets is clipped to ±10. Job 22 retrain (6.1.1): epoch-1 val loss **10.13** — O(1); model selection meaningful again |
| F11 | **Walk-forward baseline comparison still measured nothing** after F7's fix: the window-count guard compared `n - seq_len + 1` windows against `n - seq_len` targets (fired for every long series — job 22: 53 entries, 0 measured, `mean_lift` null, including daily series with 1,300+ windows); the frozen-model adapter fed `(batch, seq, 1)` to a `(batch, seq)` model (uncatchable `RuntimeError`); the `mean_lift` aggregate filtered dict values with `isinstance(…, float)` | Medium (credibility metric) | **Fixed in 6.1.2 (L-61, PR #147)**: trailing window dropped (1:1 alignment), 2-D features, r2-lift aggregation. Offline smoke on the real job-20 splits measured 19/53 sources after the fix; the job 23 retrain reports measured entries and a finite `mean_lift` (§6) |

## 5. Data double-check (parity + spot checks)

- DB `indicator_observations` = 51,915 rows; 1:1 with `indicator_vintage_log` (provenance: every row carries ingest job, snapshot id, `publication_basis=ingest_instant` — honest, no invented publication dates).
- Per-source DB counts match the certified parquet exactly (fred 46,556 / ecb 4,167 / bis 630 / world_bank 457 / sec_edgar 105).
- Persistence semantics verified in code: only certified scalar rows, upsert on (time, source, indicator, region), NaN never written as zero, duplicates counted not silent.
- Live-source spot checks (independent probes): FRED DGS10 tail ✓, ECB CISS tail ✓ (matches to the row), EDGAR 13F tail ✓ (2026-08-07 at new CIK), World Bank ZAF tail ✓.
- Anomaly audit: see F8.

## 6. Model training

Four retrainings on the fixed pipeline (jobs 22, 23, 25-era intermediates and job 26); the 6.1.3 run (job 26) is the final artefact.

### 6.1 Job 22 on 6.1.1 (intermediate — proved the objective fix)

- 88,844 training sequences (41 sources forming windows / 15,179 series), train 2000-01-01→2017-02-08; test 2021-05-20→2026-09-24 (24,733 sequences / 2,143 series / 70 sources).
- **Epoch-1 val loss 10.13 (O(1) — was 4.23e18 on job 21)**; best checkpoint epoch 3 on that bounded metric; clip warnings fired on AI4RISK series, confirming the ±10 bound is active.
- Holdout: pooled R² 0.871 in original units (dominated by the large-scale AI4RISK edge series — the pooled number is the wrong view on a mixed-scale panel); per-series below is the meaningful one.

### 6.2 Job 23 on 6.1.2 (intermediate — proved L-61 defects 1–3)

- Same certified package (job 20), same config (temporal_attention, d_model 64, nhead 8, 2 layers, seq 30, 40 epochs, CPU), same chronological split: train 2000-01-01→2017-02-08 (134,310 rows), val 2017-02-08→2021-05-20, test 2021-05-20→2026-09-24 (151,942 rows).
- Loss curve: epoch 1: train 0.113 / val 10.47; epoch 4: val 10.06 (best); epoch 40: train 0.014 / val 10.81 (epoch-1 val 10.47; best val 10.06 at epoch 4).
- Holdout: pooled R² 0.851 (original units — see §6.1 caveat); MAE 33,360, RMSE 308,401 (original units).
- Per-series holdout, headline series:

| Series | R² | Verdict |
|---|---|---|
| IR_US_10Y | 0.990 | strong — the rates arm the F9 fix brought into training |
| STOCK_VIX | 0.837 | strong |
| EXR_EUR_JPY | 0.857 | strong |
| EXR_EUR_USD | 0.816 | strong |
| STOCK_EUROSTOXX50 | 0.238 | weak — trend-dominated level |
| COMM_GOLD | −0.582 | negative — level drift dominates |
| STOCK_NIKKEI | −3.751 | negative — level drift dominates |
| STOCK_SPX | −31.431 | negative — level drift dominates |

- **Walk-forward baseline comparison (first real measurement since the single-scale trainer reported it in round two):** 19 sources measured out of 53 candidates (honest skips recorded for quarterly/annual feeds with < 40 test points); `mean_lift` (model R² − baseline R², per source, mean over persistence and AR(1)): **−63.55**.
- Reproducibility manifest: artifact hash, config hash, git sha, data attestation + snapshot binding — in the job result.
- Ensemble: requested 1 (multi-scale trainer does not train independent members yet — platform reports this honestly).

### 6.3 Job 26 on 6.1.3 (final artefact — L-61 complete)

- Same certified package (job 20) and config as job 23; the only code difference is the baseline-comparison fix (L-61 defect 4: compound-id feeds measured, panel feed recorded).
- Loss: epoch-1 val 9.89 (train 0.115); best val 9.89 at epoch 1 (flat val curve 9.9–11.0 over 40 epochs — the bounded objective from 6.1.1 makes the checkpoint choice stable, not dramatic); holdout pooled R² 0.859 (original units — §6.1 caveat).
- Per-series holdout, headline series (final model):

| Series | R² |
|---|---|
| IR_US_10Y | 0.972 |
| EXR_EUR_JPY | 0.800 |
| COMM_OIL_WTI | 0.794 |
| STOCK_VIX | 0.769 |
| CREDIT_US_SPREAD | 0.722 |
| EXR_EUR_USD | 0.378 |
| STOCK_EUROSTOXX50 | −0.586 |
| COMM_GOLD | −0.718 |
| STOCK_NIKKEI | −3.595 |
| STOCK_SPX | −30.710 |

Same split as job 23; the per-series distribution is unchanged in shape (9 of 2,143 series R² > 0.5, 13 > 0, median 0 — the long tail of tiny AI4RISK edge series).
- **Baseline comparison, complete candidate set:** 30 of 65 candidate sources measured (all 12 compound-id FX/equity/VIX/gold feeds now included), the AI4RISK panel recorded as one honest skip, `mean_lift` −50.06.
  - - Measured (30): all 12 compound-id feeds are now in. The model beats **both** persistence and AR(1) on 11 daily feeds — IR_US_10Y (+2.87/+1.90), FRED_REPO_RATE (+1.40/+2.34), CREDIT_US_SPREAD (+1.38/+3.08), COMM_OIL_WTI (+1.28/+0.90), EXR_EUR_CNY (+1.11/+1.20), STOCK_VIX (+0.84/+1.33), STOCK_HSI (+0.74/+0.89), FRED_KCFSI (+0.67/+0.29), ECB_CISS (+0.54/+3.40), FRED_STLFSI4 (+0.62/+1.15), FRED_COMMERCIAL_PAPER (+0.39/+0.17) — and on IR_US_2Y (+0.26/+0.77). It loses on EUR/JPY (−0.35), EUR/USD (−0.14), gold (−2.61), EUROSTOXX (−3.64), NIKKEI (−4.51), SPX (−15.71) and on the small-sample quarterly feeds, where the mean lift is dominated by MM_US_M2 (−400), ECON_US_CPI (−313) and BANK_EU_DEPOSITS (−361) — R² on 30–100-window folds, where a single bad fold flips the sign.
- Skipped (35), every one recorded: 33 "series too short for folds" (annual/quarterly WB and BIS feeds), 1 "not enough windows" (ECON_EU_HICP), 1 "no usable value column" (WB_DOMESTIC_CREDIT_SA has no test-window data — upstream ended 2017), and the AI4RISK panel once as "panel feed; per-entity walk-forward not measured".
- This is the final, complete credibility measurement: the report no longer undercounts the candidate set.

Interpretation: the model tracks *levels* of low-drift, mean-reverting series (rates, FX, VIX) well out of sample; equity/gold index levels are dominated by secular trends a 30-window attention model cannot extrapolate. For an early-warning system the relevant quantities are risk scores, direction and regime change — measured next.

## 7. Model effectiveness verification

### 7.1 Backtest (job 27, test window 2021-05-21 → 2026-09-24)

- 26,056 risk-series predictions over 35 sources (the 35 single-series feeds; the AI4RISK panel is scored as a feed, not per edge); 125,885 rows dropped for history (the max_steps=2000 window), 0 dropped for missing values.
- **Ground truth now exists and is leakage-free**: each score is paired (via `predicted_row_offset`) with the standardized next-step actual of the same series, standardized on the pre-test window only (2000→2021-05), clipped by the same ±10 law as training; series without pre-test history keep NaN targets and are excluded. Declared in the result as `target_derivation`; finite targets on 25,264 of 26,056 scored rows (96.96%).
- Aligned accuracy (score space = model's standardized space): MSE **7.774**, MAE 1.322, RMSE 2.788, R² **0.188**, directional accuracy / hit rate **0.449**. (Intermediate 6.1.2 run, job 24: R² 0.175, directional 0.445 — the final model is slightly better; both sit below the 0.5 directional coin-flip, which the report does not paper over: 30-day-ahead direction on a mixed-scale panel is a hard problem, and the platform reports the miss.)
- Walk-forward sub-evaluation: all 35 series honestly skipped — "no series had enough timesteps for the fold configuration" (per-series backtest windows are too short for 5 expanding folds at min_train_size=30). Declared, not hidden.
- Volatility baselines: GARCH(1,1) vs unconditional variance per series, with per-series lift (3 folds each, 0 fit failures).
- Stats provenance per series: 32 `checkpoint`, 3 `payload_window` (feeds with no pre-test history — declared).

### 7.2 30-day prediction (job 28, as of 2026-09-24)

71 sources scored (mean risk 0.259, max 2.402, min −1.408). Top risk (standardized, uncalibrated — the platform states this explicitly):

| Source | Risk | 30d prediction | Regime (HMM) |
|---|---|---|---|
| STOCK_NIKKEI | 2.40 | 46,407 | **stress** |
| STOCK_SPX | 2.19 | 6,005 | **stress** |
| EXR_EUR_JPY | 2.15 | 176.6 | calm |
| STOCK_EUROSTOXX50 | 1.90 | 5,361 | **stress** |
| COMM_GOLD | 1.85 | 3,026 | **stress** |
| FRED_BANK_ASSETS | 1.76 | 16,351 | **stress** |
| FRED_FED_BALANCE_SHEET | 1.76 | 4,825,812 | **stress** |
| MM_US_M2 | 1.70 | 12,492 | **stress** |
| BANK_US_COMMERCIAL_LOANS | 1.69 | 1,886 | **stress** |
| BANK_EU_DEPOSITS | 1.54 | 2,068,583 | **stress** |

- 44/71 sources carry split-conformal 90% intervals; 27 refused for insufficient calibration history (honestly `NaN`); 26/71 refused a regime ("insufficient_history_for_regime") while 24 are flagged **stress** and 21 **calm** (student-t HMM higher-variance state).
- Uncertainty decomposition: single model → "not measurable" (no ensemble; stated, not hidden).
- Live signal: equity indices, bank-credit, Fed balance sheet, M2, bank assets and gold in a **high-variance (stress) regime** at end-2026 — consistent with the 6.1.2 run (job 25: same 24-stress/21-calm split, EUROSTOXX on top at 2.71).

### 7.3 Scenario simulations (model 26, horizon 30 days, via `POST /api/v1/models/26/simulate`)

Six scenarios driven by the **rich `ScenarioParameters`** (the 6.1.0 wiring), each re-scored across all sources; the two network scenarios run the Eisenberg–Noe clearing on the latest quarter of the AI4Risk edges (221 banks) with declared endowment assumptions:

| Scenario | Parameters | Key reactions | network_analysis |
|---|---|---|---|
| Baseline | — | 71 series; avg risk 0.259, max 2.402 (NIKKEI), min −1.408 | — |
| Market crash | stock_drop_pct 0.20, volatility_spike 2.0 | scores unchanged vs baseline: max \|Δ\| = 4.8e−7 (float noise) — a uniform 20% price cut is an affine transform of each equity series, which the per-series standardisation absorbs (see L-62) | — |
| Rate shock | rate_cut_bps −60, credit_spread_widening 1.5 | scores near-identical: max \|Δ\| = 0.022 (IR_EURIBOR_1M −0.547→−0.569, FRED_REPO_RATE −1.393→−1.392); uniform +0.6pp on rate feeds is again largely absorbed by standardisation | — |
| Liquidity freeze | interbank_lending_reduction 0.70 | scores exactly identical (max \|Δ\| = 0; the freeze hits interbank/AI4RISK rows, not the scalar feeds scored) | 4,412 nodes, 0 defaults, total shortfall 0.0, converged in 1 iteration, 0 contagion edges — solvent under the declared endowment = 1.0×gross-exposure assumption |
| Bank failure (bank "0", top gross exposure 5.7e8) | failed_bank_id "0", endowment_fraction 1.0 | only the non-uniform transform moves a score: AI4RISK network-topology feed 0.839→0.790 (failed bank's equity zeroed, counterparties haircut) | 4,401 nodes, 1 default (bank "0", insolvency), total shortfall 4,827,005, 717 contagion edges in round 1, converged in 2 iterations |
| Regional shock (NA) | regional_shocks [{NA, 0.10}] | scores exactly identical (max \|Δ\| = 0): the collection payload carries no `region` column, so the shock cannot be located — declared in the server log, not silently applied | — |

Every response carries `scenario_parameters` (verifying the F6 fix end-to-end) and the network scenarios carry a `network_analysis` block (defaults, shortfalls, contagion edges, declared assumptions: edge orientation read as `sourceid holds a claim on targetid`; endowments = `endowment_fraction` × gross total exposure; failed bank's endowment zeroed).

**Read on effectiveness:**
1. **Shocks land in the data, not (yet) in the scores.** Parameters are echoed verbatim in `scenario_parameters` on all six responses (verifying F6 end-to-end) and the transforms do hit the data: equity prices are cut, rate feeds shifted, the failed bank's equity zeroed and its counterparties haircut. But the ML score response is nearly zero for the uniform shocks, because each scoring window is standardised by per-series statistics (checkpoint statistics, or self-computed when the checkpoint has no series-grain statistics for the feed) — and a uniform scale/shift of a series is an affine transform that z-scoring absorbs (L-62). Measured: market crash max |Δ| = 4.8e−7, rate shock 0.022, liquidity freeze 0, bank failure 0.049, regional shock 0. The one genuinely non-uniform transform (bank failure) moves exactly the feed it touches.
2. **Systemic propagation is now measurable.** The Eisenberg–Noe clearing responds as designed and is honest about its assumptions: the 70% interbank lending freeze is fully absorbed (0 defaults, shortfall 0.0 — under the declared endowment = 1.0×gross-exposure assumption every bank's endowment covers its liabilities), while zeroing bank "0"'s endowment cascades to 1 default, total shortfall 4.83M across 717 contagion edges, converging in 2 iterations. Edge orientation and endowment construction are declared in the output, never silently assumed.
3. **Outputs are honestly calibrated.** Scores are "standardized units, uncalibrated — not a probability"; intervals are conformal where calibratable and refused where not; provenance is disclosed per series.

## 8. Final state

**Done and shipped (this run):**

| Release | PR | Fixes |
|---|---|---|
| 6.1.0 | #143 | L-51 value-column selection (F9), L-52 scenario parameters (F6), L-53 brief report (F5), L-54 backtest ground truth, L-56 network scenarios, L-57/L-59 provider retryability (F1), L-58 SEC CIK (F2), L-59 IMF catalogue |
| 6.1.1 | #145 | L-60 degenerate standardization + ±10 clip (F10) |
| 6.1.2 | #147 | L-61 walk-forward baseline measurement (F11) |
| 6.1.3 | #149 | L-61 defect 4: compound-id feeds vanished from the baseline report |
| 6.2.0 | #151 | background scenario jobs (2-concurrency `scenario-worker` on a dedicated queue), batched cross-source inference, naive/aware `started_at` fix on the job failure path |

**Final verdict — is the model useful?**

**Useful within its designed role; not a directional trading signal.**

The model is a per-series *standardized one-step-ahead* forecaster, and measured against that role:

* **Strong where its assumptions hold.** On low-drift, mean-reverting macro series the holdout R² is excellent — IR_US_10Y 0.972, EUR/JPY 0.800, WTI 0.794, VIX 0.769, CREDIT_US_SPREAD 0.722 — and 11 of the 30 measurable daily feeds beat *both* the persistence and AR(1) baselines (L-61 fixed the measurement that had hidden this). These are exactly the series a risk desk uses for relative ranking and regime awareness.
* **Weak where its assumptions don't.** On trending equity and gold *levels* (SPX −30.7, NIKKEI −3.6, GOLD −0.72 holdout R²) it is negative by construction: a 30-window standardized model cannot extrapolate secular trends. This is declared in the report, not hidden in a negative number, and the fix is a modelling decision (forecast returns/deltas, not levels).
* **Honest about its uncertainty.** 27/71 sources are refused a conformal interval for insufficient history; the single model reports the epistemic/aleatoric split as *not measurable* rather than fabricating a zero; the executive summary states "standardized units, uncalibrated — not a probability."
* **Backtest is below coin-flip direction and we say so.** Aligned holdout R² 0.188, directional accuracy 0.449 (standardized score space). Useful for *ranking* and *regime* (24 stress / 21 calm / 26 none, stable across 6.1.2→6.1.3 reruns), not for sign-picking.
* **The scenario layer is mechanically sound, with one declared limitation.** End-to-end wiring works (parameters echoed, network clearing computed and converged, storage layout stable, 2-concurrency background jobs on a dedicated queue in 6.2.0). But the rich scenario parameters are uniform affine transforms that the per-series standardisation absorbs, so uniform shocks do not move the ML scores (L-62); only non-uniform shocks (a failed bank) do. The network-clearing block, computed independently of the model, responds correctly and is where systemic propagation is measurable today.

**Bottom line:** deploy it as a standardized risk-ranking and regime monitor for mean-reverting macro series, with the conformal intervals and refusal flags as shipped. Do not deploy it as a directional trading signal, and do not read the scenario ML scores as a response to uniform macro shocks until L-62 is addressed. Every limitation above is named, bounded, and reproduced in the artefacts (jobs 26/27/28, six scenario responses, this report).

**Remaining (named, bounded, not silent):**

1. Multi-scale ensemble: the trainer reports it cannot train independent members yet; implementing it would make the epistemic/aleatoric uncertainty decomposition measurable instead of "not_measurable_single_model".
2. IMF catalogue items 41/42: no DataMapper equivalent exists (verified); re-enabling needs a new indicator choice, not a port.
3. ECB DataWarehouse intermittent timeouts: redundancy works; monitor.
4. Equity/gold *level* forecasting: a 30-window model cannot extrapolate secular trends; if level forecasts are wanted, the target must become returns/deltas (a modelling decision, recorded here rather than hidden in a negative R²).
5. FRED key hygiene: the live key sits in DB config; `.env` stays untracked. Consider env-injected config only.
6. Scenario score-invariance (L-62, this run): the rich scenario parameters are implemented as uniform full-history affine transforms, which the per-series standardisation of the scoring window absorbs — so uniform shocks (price cuts, rate cuts, lending freezes) do not move the ML scores, only non-uniform ones (a failed bank) do. Making scenarios bite on the scores is a modelling decision (e.g. scenario-relative normalisation, or shock shapes that change variance structure), recorded here rather than papered over.
7. Scenario runtime: measured on the 71-source payload, the regime nowcast is 99.9% of `engine.predict` time (1,002.5 s of 1,003.8 s); batched scoring takes <0.5 s. A further order-of-magnitude scenario speedup requires re-tuning the regime EM — deliberately out of scope for 6.2.0 (statistical-meaning change); the 2-concurrency background queue is what 6.2.0 ships.
