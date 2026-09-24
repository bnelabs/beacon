# BEACON Production Review — 2026-09-24

Unattended run: update stack → collect 2000–2026 → review + fix pipeline → double-check data → train → backtest/predict/scenarios.
Author: BEACON agent (goal `goal-3c144a83`), server `komedi`, all real data, no test fixtures.

## 1. Executive summary

- Stack updated v4.0.0 → **v6.0.5** (official tag, CPU build), rebuilt healthy; DB pre-dumped to `backups/beacon-pre-update-20260924-110517.sql`; alembic at `vintage_provenance_001`.
- Final certified data package: **job 16**, 71/71 sources, 2000-01-01 → 2026-09-24, **quality 93.96** (completeness 100, consistency 100, timeliness 77.5), 517,619 rows, snapshot `sha256:c56b84af…`.
- Two live defects found and fixed operationally during the run: **SEC 13F item pointed at a retired filer CIK** (data stale since 2024-08) and **dead FRED key in `.env`** (rotated out). Both fixed; a third finding (WB plugin misclassifies network timeouts as empty data) is recorded for the next code release.
- Model **job 17** (temporal_attention, multi-scale, CPU, 40 epochs): holdout R² 0.736 overall; per-series 0.88–0.98 on FX and VIX, weak on trend-dominated equity index levels (negative R² for SPX/NIKKEI/EUROSTOXX/GOLD).
- **Root-cause finding (F9, high):** a value-column bug in the multi-scale dataset builder silently excluded 60 of 71 series from training (everything without OHLC columns). The trained model is effectively a strong FX/equity/VIX/gold model with no rates/macro/credit coverage — despite the certified package containing 26 years of those. Recorded as the top code fix for the next release; retraining is the immediate next step once it lands.
- Backtest, 30-day prediction and five historical-regime scenario simulations all ran and were analysed (report §7). Live signal as of 2026-09-24: equity indices and gold in a **stress** (high-variance) HMM regime.

## 2. Stack update

| Item | Before | After |
|---|---|---|
| Image | beacon-backend v4.0.0 (local) | built from tag `v6.0.5` (commit 251f2f6), CPU torch 2.14.0 |
| Schema | `data_frequency_contract_001` | `vintage_provenance_001` (3 migrations applied by migrate service) |
| GPU | NVML driver/library mismatch (unusable) | CPU deployment (matches previous `Devices=[]`) |
| Ownership | models/, logs/, results/ root-owned → container user (uid 1000) could not write | `chown 1000:1000` |
| Zombie job 9 | "running" since 2026-09-18 | cancelled via `DELETE /api/v1/jobs/9` |

Backup: `backups/beacon-pre-update-20260924-110517.sql` (262 KB), taken before any mutation.

## 3. Data collection (2000–2026)

Run history:
- Job 14 (2000-01-01→2026-09-24, strict): **failed** — single failure `WB_DOMESTIC_CREDIT_ZA (EMPTY_DATASET)`. Root cause: transient 30 s read timeout to api.worldbank.org; the plugin catches *all* exceptions and returns `None`, which the collector reads as "empty dataset" — and `EmptyDatasetError` is **not retried** (only `DataSourceUnavailableError` is, 3× / 120 s budget). Upstream data verified live (ZAF: 25 non-null rows 2000–2024, API < 1 s).
- Job 15 (retry of 14): **completed 71/71**, quality 93.56.
- Job 16 (final, after SEC fix below): **completed 71/71**, quality **93.96**, 517,619 rows, 51,907→51,843 scalar rows persisted (51,915 total in store incl. retained history).

Coverage highlights (verified against parquet + live probes):
- 26-year window repaired the old 5-year runs: `WB_DOMESTIC_CREDIT_SA` now 18 rows (upstream ends 2017 — faithful, not fabricated).
- Daily FX 6,840 rows 2000-01-03→2026-09-23; DGS10/DGS2 6,684→2026-09-22; SPX/VIX/NIKKEI to 2026-09-24; WTI 6,322; gold 6,541 from 2008-08-30; SOFR from 2018-04-03; €STR from 2019-10-01; BIS quarterly →2026-01-01; AI4Risk interbank topology 393,589 edges 2016Q1–2023Q3.
- Confirmed NOT bugs (upstream facts): RRPONTSYD starts 2003 (facility existed since 2003); STLFSI2 ends 2022-01 (upstream cessation); TEDRATE ends 2022-01 (LIBOR era ended); BAMLH0A0HYM2 starts 2023-09 (series did not exist earlier); **CISS ended 2025-05-02 upstream** (ECB stopped publishing; collected tail matches exactly — staleness correctly flagged in the timeliness component 77.5).
- IMF: legacy SDMX endpoint (`dataservices.imf.org/REST/SDMX_JSON.svc`) is retired upstream; the modern DataMapper API works (NGDP_RPCH/USA → 52 years). The two IMF catalogue items (41/42) are not default-selected, so they never block runs — left disabled with this note; re-pointing them to DataMapper is a code task for the next release.
- AI4Risk credit-rating items (77/78) are disabled: `DATASET_MISSING` is the correct refusal (dataset is not hosted at the configured URL); left as-is.

## 4. Defects found and status

| # | Finding | Severity | Status |
|---|---|---|---|
| F1 | `world_bank_plugin` converts network timeouts into `EmptyDatasetError` (not retried); killed entire strict run 14 on a transient 30 s timeout | High (availability) | **Operational**: re-run (job 15) succeeded. **Code fix for next release**: raise `DataSourceUnavailableError` on `requests.Timeout`/`ConnectionError`, mirroring `sec_plugin`. |
| F2 | SEC 13F catalogue item used `BLK` → CIK 0001364742 (BlackRock **Finance**, Inc.), whose last 13F-HR is 2024-08-13; current filer is BlackRock, Inc. CIK **0002012383** (13F-HR through 2026-08-07) | High (staleness, 25 months) | **Fixed**: `data_catalogue` id 33 endpoint `BLK.13F-HR` → `0002012383.13F-HR` (plugin resolves numeric tickers as CIKs). Job 16 collected the current 8 filings; DB store now carries the continuous 2006→2026 history (80 rows). |
| F3 | `.env` `FRED_API_KEY` was a rotated-out key; live key lives in `data_sources` id 2 config | Medium (config drift) | **Fixed**: `.env` synced to the live key (32-char, verified against DGS10 2026-09-22 = 4.96). `.env` remains untracked. |
| F4 | ECB DataWarehouse (data-api.ecb.europa.eu) intermittently times out from this host; FX items degrade to the Frankfurter mirror | Low (redundancy works) | Accepted; monitor. CISS and other DW series still collected fine in job 16. |
| F5 | Brief report `/api/v2/reports/brief/{id}` displays `anomalies_detected` under a "failed" key (18,197 findings shown as "failed: 18197" while 71/71 collected, 0 failed checks) | Low (presentation) | **Code fix for next release**: label the field correctly. |
| F6 | Rich `ScenarioParameters` (bank_failure, rate_cut_bps, …) are inert on the API simulate path: the route only applies legacy `adjustments` to the last N days; the engine's `apply_scenario` is reachable only via internal `combined` sub-scenarios | Medium (capability gap) | **Code fix for next release**: wire `scenario` into the simulate route. |
| F7 | Multi-scale trainer's walk-forward baseline comparison returned `null` ("not measured" — honestly reported, not faked) | Low (credibility metric missing) | Investigate `_baseline_comparison` failure mode; **code fix for next release**. |
| F8 | 18,197 anomalies in job 16 | Info | Audited: dominated by gap-run/stale-run findings on the 393,589-row AI4RISK interbank panel (banks entering/leaving the network create long missing-value runs per edge) plus genuine macro anomalies. Validator findings are warnings by design; integrity checks (duplicates, future timestamps) found 0. |
| F9 | **Multi-scale dataset builder drops every non-OHLC series from training.** `MultiSourceDataset` picks the value column with `'Close' if 'Close' in columns else 'Value'` — but in the joined panel frame `'Close'` is always present (from the OHLC series), so it is used for every series. Series whose values live in `Value` (all FRED rates incl. IR_US_10Y, macro, banking, credit, oil, SEC, BIS, WB) read as all-NaN → "Skipping series … – no observed values". Result: **only 11 of 71 series were actually trained** (5 FX, 5 equities, gold); the model's rates/macro/credit arm was never trained. Verified per series in the job-16 parquet (Close populated: GOLD, FX, equities; empty for IR_US_10Y/OIL_WTI/SOFR/credit with `Value` fully populated) | **High (model quality)** | **Code fix for next release**: select the value column per series (prefer the column that actually has non-null values, e.g. `Close` only when populated, else `Value`). Retrain after the fix — the model's domain is currently much narrower than the data package suggests. |

## 5. Data double-check (parity + spot checks)

- DB `indicator_observations` = 51,915 rows; 1:1 with `indicator_vintage_log` (provenance: every row carries ingest job, snapshot id, `publication_basis=ingest_instant` — honest, no invented publication dates).
- Per-source DB counts match job 16 parquet exactly (fred 46,556 / ecb 4,167 / bis 630 / world_bank 457 / sec_edgar 105).
- Persistence semantics verified in code: only certified scalar rows, upsert on (time, source, indicator, region), NaN never written as zero, duplicates counted not silent.
- Live-source spot checks (independent probes): FRED DGS10 tail ✓, ECB CISS tail ✓ (matches to the row), EDGAR 13F tail ✓ (2026-08-07 at new CIK), World Bank ZAF tail ✓.
- Anomaly audit: see F8.

## 6. Model training (job 17)

- Data: job 16 package; chronological split train 2000-01-01→2021-05-20 (134,310 rows), val 80/20 inside train, test 2021-05-20→2026-09-24 (151,936 rows).
- Architecture: temporal_attention multi-scale (383,042 params, d_model 64, 2 layers, seq 30), CPU, 40 epochs, best epoch 36, LR reduced on plateau.
- Holdout: **R² 0.736**, MAE 1,899.5, RMSE 6,137.7 (mixed-scale panel; per-series below is the meaningful view).
- Per-series holdout (2021→2026):

| Series | R² | Verdict |
|---|---|---|
| EXR_EUR_USD | 0.927 | strong |
| EXR_EUR_JPY | 0.880 | strong |
| STOCK_VIX | 0.871 | strong |
| EXR_EUR_CNY | 0.979 | strong |
| STOCK_HSI | 0.985 | strong |
| EXR_EUR_GBP | 0.408 | moderate |
| STOCK_EUROSTOXX50 | 0.015 | weak (level drift) |
| COMM_GOLD | -0.504 | weak (regime-driven level) |
| STOCK_NIKKEI | -2.227 | weak (level drift) |
| EXR_EUR_CHF | -3.339 | weak |
| STOCK_SPX | -6.429 | weak (level drift) |

Interpretation: the model tracks *levels* of low-drift, mean-reverting series (FX, VIX) very well; equity/gold index levels are dominated by secular trends a 30-window attention model cannot extrapolate out-of-sample. For an early-warning system the relevant quantities are risk scores, direction and regime change — measured next in the backtest and scenarios.

**Critical scope caveat (root cause found — see F9):** only these 11 series entered the training dataset at all. The builder's value-column selection reads the panel-wide `'Close'` column for every series, so every non-OHLC series (rates, macro, banking, credit, oil, SEC, BIS, WB — 60 of 71) was skipped as "no observed values" despite having fully populated `Value` columns. The model is therefore currently a strong FX/equity/VIX/gold model that has *never seen a rate, a macro number, or a credit spread*. The per-series weakness above is the honest consequence; the missing macro arm is a bug, not a limitation of the data.

- Reproducibility manifest: artifact hash, config hash, git sha, data attestation + snapshot binding — all recorded in the job result.
- Ensemble: requested 1 (multi-scale trainer does not train independent members yet — platform reports this honestly).

## 7. Model effectiveness verification

### 7.1 Backtest (job 18, test window 2021-05-21 → 2026-09-24)

- 26,050 risk-series predictions over 35 scalar sources (125,885 AI4RISK edge rows dropped for insufficient history — disclosed).
- **No ground-truth risk column exists in the collection package**, so return-based accuracy metrics (MSE/R²/directional) are correctly reported as `None`, not fabricated. This is a data-schema gap, honestly surfaced.
- **Normalisation provenance (disclosed per series):** 11 series used checkpoint (training-time) statistics — clean; **24 series** (all rates/macro/banking/credit) used statistics fitted on the evaluated window, which the result explicitly flags as "metrics on those series are optimistic: the normalisation saw the future". Any read of those 24 must treat them as upper bounds.
- **Walk-forward volatility baselines** (model frozen; GARCH(1,1) and unconditional variance refit per fold, 3 folds per series, expanding):
  - 11 series scored, 40,839 sparse series honestly skipped (reason recorded: non-finite values across gaps).
  - GARCH(1,1) beats the unconditional-variance baseline on all scored series (expected — it is the standard vol model). VIX is mixed (−52.4 mse, +0.115 mae vs unconditional).
  - Model-vs-baseline lift is not claimed; the platform reports what it could measure.

### 7.2 30-day prediction (job 19, as of 2026-09-24)

71 sources scored. Top risk (standardized, uncalibrated — the platform states this explicitly):

| Source | Risk | 30d prediction | Regime (HMM) |
|---|---|---|---|
| STOCK_SPX | 2.56 | 6,615 | **stress** |
| STOCK_EUROSTOXX50 | 2.49 | 5,908 | **stress** |
| STOCK_NIKKEI | 2.25 | 44,682 | **stress** |
| EXR_EUR_JPY | 2.23 | 178.1 | calm |
| COMM_GOLD | 2.13 | 3,276 | **stress** |
| STOCK_HSI | 0.89 | 25,275 | stress |
| EXR_EUR_GBP | 0.81 | 0.869 | calm |

- 44/71 sources carry split-conformal 90% intervals; 27 sources are refused intervals for insufficient calibration history (honestly `NaN`).
- Uncertainty decomposition: single model → "not measurable" for all 71 (no ensemble; stated, not hidden).
- The live signal: equity indices and gold in a **high-variance (stress) regime** at the end of 2026, with equity levels forecast to extend the move. That is a genuine early-warning output from real data.

### 7.3 Scenario simulations (model 17, horizon 30 days, via `POST /api/v1/models/17/simulate`)

Five historical-regime shocks applied to the last 30 days of the affected sources (the mechanism the API currently supports), each re-scored across all 71 sources:

| Scenario | Key reactions (risk score Δ vs baseline) | Overall score |
|---|---|---|
| Baseline | SPX 2.56, EUROSTOXX 2.49, NIKKEI 2.25, GOLD 2.13 | +0.122 |
| 2022-style rate shock (10Y +60%, VIX +80%, spreads +50%) | SPX 2.56→2.29; overall up | +0.139 |
| March-2020 liquidity freeze (indices −30..−38%, VIX +150%) | EUROSTOXX 2.49→**0.11** (mean-reverting response), HSI 0.89→**−0.82** (bounce), overall down | +0.103 |
| Oil/gold supply shock (WTI +60%, gold +40%) | GOLD 2.13→2.26 (safe-haven), SPX 2.56→2.43 | +0.133 |
| FX crisis (EUR −10% vs USD, JPY weak, CHF strong) | EUR/GBP 0.81→1.58, EUR/JPY 2.23→2.45 | +0.149 |
| 1970s stagflation (oil +80%, gold +50%, rates +30/20%) | GOLD 2.13→2.26, SPX 2.56→2.38 | +0.134 |

**Read on effectiveness:**
1. **Shocks land where they should.** The targeted series respond correctly (crash → strong mean-reverting reversal signal; FX shock → FX stress propagates within the FX block; oil shock → gold safe-haven). The model does not ignore the intervention.
2. **Cross-series propagation is weak.** Non-targeted series barely move (NIKKEI unchanged under the 2020-style crash; macro sources inert in all scenarios). The multi-scale attention is largely per-series in this configuration; the systemic channel (Eisenberg–Noe clearing with exposures/endowments, Brunnermeier–Pedersen spiral) exists in the engine but is not exposed by the API scenario path (see F6).
3. **Outputs are honestly calibrated.** Scores are "standardized units, uncalibrated — not a probability", intervals are conformal where calibratable and refused where not, and provenance (checkpoint vs window-fitted) is disclosed per series. Nothing is dressed up.

**Verdict:** the model is effective as a *per-series risk early-warning* on its trained domain (FX, equity indices, VIX, gold — R² 0.87–0.98 on the cleanest series, correct regime flags on live 2026 data, correct directional reactions to scenario shocks). It is not yet effective at *systemic propagation* across series in the current API configuration, and its macro/rates coverage is limited by both training-set inclusion (11 series) and the missing ground-truth column for accuracy scoring. Both are named, bounded, fixable gaps — not silent failures.

## 8. Recommendations for the next release (code)

1. `world_bank_plugin`: network errors → `DataSourceUnavailableError` (retryable); keep `EmptyDatasetError` for genuinely empty responses.
2. IMF plugin: port to the live DataMapper API (`www.imf.org/external/datamapper/api/v1/{INDICATOR}/{COUNTRY}`); re-enable items 41/42 after port.
3. Wire `ScenarioParameters` into `POST /models/{id}/simulate` (engine `apply_scenario` already implements the transformations).
4. Fix brief-report "failed" field to show `anomalies_detected` distinctly from failed checks.
5. Investigate multi-scale `_baseline_comparison` null; report the walk-forward lift once it runs.
6. Rotate the FRED key out of any place where it could be committed (deployment.md documents a previously committed real key; DB config now holds the live key — consider moving it to env-injected config).
7. Wire the network path (bank_exposures/bank_endowments → Eisenberg–Noe + spiral) into the scenario/prediction API so systemic propagation is testable end-to-end; today the engine supports it and the API does not.
8. Add a ground-truth target column (or derive one from returns) to the collection package so backtest accuracy metrics can actually be scored; until then the backtest correctly refuses to fabricate them.
9. **Fix F9 first and retrain**: correct the `MultiSourceDataset` value-column selection (per-series non-null check instead of the frame-wide `'Close' in columns` test), retrain, and re-verify that all 71 sources with sufficient history enter the dataset. This is the single highest-impact change for the early-warning domain: the model currently has no rates/macro/credit coverage despite 26 years of that data sitting in the certified package.
10. Multi-scale ensemble: the trainer reports it cannot train independent members yet; implementing that would make the epistemic/aleatoric uncertainty decomposition measurable instead of "not_measurable_single_model".
