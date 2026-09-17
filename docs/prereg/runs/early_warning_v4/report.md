# Pre-registered early-warning evaluation — run report (early_warning_v4)

*Run at 2026-09-17T21:57:10+00:00 against tag `prereg-early-warning-v4`. Single-run rule: these numbers are the run.*

## Family verdict

- Tested: **5** indicator(s): BIS_CREDIT_GAP_US, FRED_STLFSI4, FRED_T10Y2Y, FRED_T10Y3M, FRED_VIXCLS
- Passed all frozen criteria (Holm-adjusted): **1** — FRED_STLFSI4
- Family rule: at least half of the tested family passes all criteria (Holm-adjusted AP included), AND at least 3 indicators were testable -- a claim graded on fewer than that is a claim graded on an anecdote
- **System-level 'demonstrated early-warning' claim warranted: NO**

## Per-indicator results

| code | status | events | base rate | AUC | AP | AP p (perm) | median lead | FA/quiet-yr | beats baselines | passed |
|---|---|---|---|---|---|---|---|---|---|---|
| `BIS_CREDIT_GAP_US` · tan_frozen | evaluated | 3 | 0.070 | 0.392 | 0.074 | 0.7463 | nan | 0.1 | no | fail |
| `BIS_CREDIT_GAP_US` · tan_rolling | evaluated | 3 | 0.070 | 0.581 | 0.080 | 0.4835 | nan | 0.118 | no | fail |
| `BIS_CREDIT_GAP_US` · hazard_logit | evaluated | 3 | 0.070 | 0.467 | 0.093 | 0.5664 | nan | 0.1 | no | fail |
| `BIS_CREDIT_GAP_US` · hazard_logit_rolling | evaluated | 3 | 0.070 | 0.654 | 0.115 | 0.2817 | nan | 0.118 | no | fail |
| `BIS_CREDIT_GAP_US` — **indicator verdict** | fail (any declared scorer, Holm-adjusted) | | | | | | | | | |
| `FRED_STLFSI4` · tan_frozen | evaluated | 19 | 0.053 | 0.812 | 0.213 | 0.0010 | 2.5 | 0.543 | no | fail |
| `FRED_STLFSI4` · tan_rolling | evaluated | 19 | 0.053 | 0.844 | 0.280 | 0.0010 | 2.0 | 0.525 | no | fail |
| `FRED_STLFSI4` · hazard_logit | evaluated | 19 | 0.053 | 0.922 | 0.384 | 0.0010 | 2.0 | 0.483 | yes | PASS |
| `FRED_STLFSI4` · hazard_logit_rolling | evaluated | 19 | 0.053 | 0.902 | 0.365 | 0.0010 | 3.5 | 0.525 | no | fail |
| `FRED_STLFSI4` — **indicator verdict** | PASS (any declared scorer, Holm-adjusted) | | | | | | | | | |
| `FRED_T10Y2Y` · tan_frozen | evaluated | 16 | 0.059 | 0.555 | 0.119 | 0.0010 | 10.0 | 3.473 | no | fail |
| `FRED_T10Y2Y` · tan_rolling | evaluated | 16 | 0.059 | 0.557 | 0.117 | 0.0010 | 11.5 | 3.687 | no | fail |
| `FRED_T10Y2Y` · hazard_logit | evaluated | 16 | 0.059 | 0.389 | 0.049 | 1.0000 | 36.0 | 2.754 | no | fail |
| `FRED_T10Y2Y` · hazard_logit_rolling | evaluated | 16 | 0.059 | 0.383 | 0.049 | 1.0000 | 36.0 | 2.735 | no | fail |
| `FRED_T10Y2Y` — **indicator verdict** | fail (any declared scorer, Holm-adjusted) | | | | | | | | | |
| `FRED_T10Y3M` · tan_frozen | evaluated | 19 | 0.062 | 0.663 | 0.142 | 0.0010 | 10.0 | 4.202 | yes | fail |
| `FRED_T10Y3M` · tan_rolling | evaluated | 19 | 0.062 | 0.654 | 0.108 | 0.0010 | 7.5 | 5.366 | no | fail |
| `FRED_T10Y3M` · hazard_logit | evaluated | 19 | 0.062 | 0.444 | 0.060 | 0.8132 | 42.0 | 3.362 | no | fail |
| `FRED_T10Y3M` · hazard_logit_rolling | evaluated | 19 | 0.062 | 0.366 | 0.048 | 1.0000 | nan | 5.485 | no | fail |
| `FRED_T10Y3M` — **indicator verdict** | fail (any declared scorer, Holm-adjusted) | | | | | | | | | |
| `FRED_VIXCLS` · tan_frozen | evaluated | 16 | 0.044 | 0.926 | 0.395 | 0.0010 | 8.0 | 2.74 | no | fail |
| `FRED_VIXCLS` · tan_rolling | evaluated | 16 | 0.044 | 0.922 | 0.377 | 0.0010 | 8.0 | 2.896 | no | fail |
| `FRED_VIXCLS` · hazard_logit | evaluated | 16 | 0.044 | 0.796 | 0.115 | 0.0010 | 7.0 | 4.723 | no | fail |
| `FRED_VIXCLS` · hazard_logit_rolling | evaluated | 16 | 0.044 | 0.852 | 0.141 | 0.0010 | nan | 5.271 | no | fail |
| `FRED_VIXCLS` — **indicator verdict** | fail (any declared scorer, Holm-adjusted) | | | | | | | | | |

## Criteria (frozen pre-run; identical thresholds in every protocol version)

0. Alarm rule and scorers are declared per protocol version: this run used alarm quantile 0.98 and scorer(s) tan_frozen, tan_rolling, hazard_logit, hazard_logit_rolling
0b. Per-track step semantics (declared pre-run; the daily row restates the frozen v1-v3 constants):
   - daily: horizon 21 step(s), min_duration 5, max_lead 42, lead floor 10 step(s) (~10 business days), 252 steps/year, hazard lookback 63 step(s)
   - quarterly: horizon 1 step(s), min_duration 1, max_lead 2, lead floor 1 step(s) (~63 business days), 4 steps/year, hazard lookback 1 step(s)
   - weekly: horizon 4 step(s), min_duration 1, max_lead 8, lead floor 2 step(s) (~10 business days), 52 steps/year, hazard lookback 13 step(s)
   Rolling scorers are graded against baselines recomputed on their own grids (declared: per_scorer_grids).
1. median lead >= 10 business days (max_lead 42, earliest-alarm convention)
2. false alarms <= 4 per quiet year (an alarm simultaneous with an event counts as false: it warned nobody)
3. AUC and AP both strictly above the persistence AND the AR(1) baseline on the identical grid
4. AP above the event base rate, with a permutation p-value (1000 shuffles, seed 20260917) surviving Holm-Bonferroni at 0.05 across the tested family

## Skips and exclusions (data availability or licence, applied before any metric)

- `BANK_EQUITY_INDEX`: **excluded** —  operator-reported series; no public source in the evaluation environment
- `CDS_PREMIUM`: **excluded** —  operator-reported series; no public source in the evaluation environment
- `ECB_CISS`: **skipped** — fetch_failed licence screen could not read series metadata: metadata HTTP 400
- `FRED_BAMLH0A0HYM2`: **skipped** — licence_prohibits_reproduction series notes contain: 'Reproduction of this data in any form is prohibited' -- committing it as provenance would violate the terms
- `FRED_KCFSI`: **skipped** — frequency_not_weekly median observation gap 31 days (monthly); the declared track is weekly
- `FRED_RRPONTSYD`: **excluded** —  owner decision: the registry itself flags its direction as a funding-sense judgement (proposal section 6)
- `FRED_SOFR`: **skipped** — insufficient_coverage coverage 0.36 < 0.6 or 4 covered episodes < 3
- `FX_SWAP_BASIS`: **excluded** —  operator-reported series; no public source in the evaluation environment
- `HQLA_LEVEL`: **excluded** —  operator-reported series; no public source in the evaluation environment
- `LCR_RATIO`: **excluded** —  operator-reported series; no public source in the evaluation environment
- `NSFR_RATIO`: **excluded** —  operator-reported series; no public source in the evaluation environment

## Deviations (declared in the protocol)

- early_warning_v4 runs in-process rather than via the Celery job queue (protocol section 'Execution'); the computation mirrors run_backtest's event idiom
- chronological holdout (train <= 2006, evaluate 2007-2024) rather than CPCV; CPCV is a declared future upgrade

## Data provenance

Every series was fetched through the platform's own FRED plugin,
licence-screened where the protocol requires it, certified by the real quality gate
before scoring, and recorded in the protocol's `manifest.json` with endpoint (API key
redacted), fetch timestamp, SHA-256, row counts, measured frequency, coverage and the
series' own licence lines. Labels come from `label_events` on raw series; the model
never saw the evaluation window during training.
v4 additionally fetches the BIS credit-to-GDP gap keyless from stats.bis.org (SDMX CSV),
licence-screened against data.bis.org/help/legal, with the attribution recorded in the
manifest; quarter periods map to quarter-end dates (declared convention).
