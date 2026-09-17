# Pre-registered early-warning evaluation — run report (protocol v1)

*Run at 2026-09-17T12:24:43+00:00 against tag `prereg-early-warning-v1`. Single-run rule: these numbers are the run.*

## Family verdict

- Tested: **1** indicator(s): FRED_T10Y2Y
- Passed all frozen criteria (Holm-adjusted): **0** — none
- Family rule: at least half of the tested family passes all criteria (Holm-adjusted AP included), AND at least 3 indicators were testable -- a claim graded on fewer than that is a claim graded on an anecdote
- **System-level 'demonstrated early-warning' claim warranted: NO**
- ⚠️ only 1 indicator(s) survived the declared data-availability rules; per-indicator results below are still reported, but no system-level claim can be made

## Per-indicator results

| code | status | events | base rate | AUC | AP | AP p (perm) | median lead | FA/quiet-yr | beats baselines | passed |
|---|---|---|---|---|---|---|---|---|---|---|
| `FRED_T10Y2Y` | evaluated | 16 | 0.059 | 0.555 | 0.119 | 0.0010 | 42.0 | 9.579 | no | fail |

## Criteria (frozen pre-run)

1. median lead >= 10 business days (max_lead 42, earliest-alarm convention)
2. false alarms <= 4 per quiet year (an alarm simultaneous with an event counts as false: it warned nobody)
3. AUC and AP both strictly above the persistence AND the AR(1) baseline on the identical grid
4. AP above the event base rate, with a permutation p-value (1000 shuffles, seed 20260917) surviving Holm-Bonferroni at 0.05 across the tested family

## Skips and exclusions (data availability, applied before any metric)

- `BANK_EQUITY_INDEX`: **excluded** —  operator-reported series; no public source in the evaluation environment
- `CDS_PREMIUM`: **excluded** —  operator-reported series; no public source in the evaluation environment
- `ECB_CISS`: **skipped** — fetch_failed empty payload
- `FRED_BAMLH0A0HYM2`: **skipped** — insufficient_coverage coverage 0.07 < 0.6 or 0 covered episodes < 3
- `FRED_KCFSI`: **skipped** — frequency_not_daily median observation gap 31 days (monthly); the protocol step is one business day
- `FRED_RRPONTSYD`: **excluded** —  owner decision: the registry itself flags its direction as a funding-sense judgement (proposal section 6)
- `FRED_SOFR`: **skipped** — insufficient_coverage coverage 0.36 < 0.6 or 4 covered episodes < 3
- `FRED_STLFSI4`: **skipped** — frequency_not_daily median observation gap 7 days (weekly); the protocol step is one business day
- `FX_SWAP_BASIS`: **excluded** —  operator-reported series; no public source in the evaluation environment
- `HQLA_LEVEL`: **excluded** —  operator-reported series; no public source in the evaluation environment
- `LCR_RATIO`: **excluded** —  operator-reported series; no public source in the evaluation environment
- `NSFR_RATIO`: **excluded** —  operator-reported series; no public source in the evaluation environment

## Deviations (declared in the protocol)

- v1 runs in-process rather than via the Celery job queue (protocol section 'Execution'); the computation mirrors run_backtest's event idiom
- chronological holdout (train <= 2006, evaluate 2007-2024) rather than CPCV; CPCV is the declared v2 upgrade

## Data provenance

Every series was fetched through the platform's own FRED plugin (keyless `fredgraph.csv`),
certified by the real quality gate before scoring, and recorded in `data/prereg/manifest.json`
with URL, fetch timestamp, SHA-256, row counts and coverage. Labels come from `label_events`
on raw series; the model never saw the evaluation window during training.
