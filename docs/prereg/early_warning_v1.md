# Pre-registered early-warning evaluation — protocol v1

**Status: FROZEN, pending run.** This document plus
[`configs/event_eval_v1.yaml`](../../configs/event_eval_v1.yaml) is the
pre-registration required by
[`docs/probes/event_target_proposal.md`](../probes/event_target_proposal.md)
§4. Owner sign-off: given in chat on 2026-09-17 ("do these one by one"),
with the proposal's defaults — 7-episode family, registry indicator family,
RRPONTSYD excluded, thresholds as proposed. Both files are committed and
git-tagged `prereg-early-warning-v1` **before** the evaluation runs; after
the tag, any change requires protocol v2 plus a CHANGELOG entry saying what
changed and why. The run report (added after the run, never before) is the
only artefact that may state results.

## 1. Claim under test

"BEACON's per-source risk series would have provided actionable early
warning of the declared systemic stress episodes." The README's honest
default is that this claim is **not** warranted; only a passing run of this
tagged protocol changes that sentence, and only with these numbers attached.

## 2. Family and dispositions (frozen before any fetch)

Every code in `backend/modules/data/semantics.py`, dispositioned up front:

| Code | Disposition | Why (data availability or owner decision — never a result) |
|---|---|---|
| `FRED_STLFSI4` | testable candidate | FRED, keyless via the platform's own plugin |
| `FRED_KCFSI` | testable candidate | FRED, keyless |
| `FRED_SOFR` | testable candidate | FRED, keyless |
| `FRED_BAMLH0A0HYM2` | testable candidate | FRED, keyless |
| `FRED_T10Y2Y` | testable candidate | FRED, keyless |
| `ECB_CISS` | testable candidate | one declared keyless attempt at FRED id `CISS`; no substitute improvised |
| `FRED_RRPONTSYD` | **excluded (owner)** | the registry itself flags its direction as a funding-sense judgement |
| `HQLA_LEVEL`, `LCR_RATIO`, `NSFR_RATIO`, `BANK_EQUITY_INDEX`, `FX_SWAP_BASIS`, `CDS_PREMIUM` | **excluded** | operator-reported series; no public source in the evaluation environment |

Skip rules (applied at fetch/certification time, before any metric exists):
`fetch_failed`, `frequency_not_daily` (the protocol step is one business day;
resampling weekly/monthly series would be a researcher degree of freedom
invented mid-run — declared v2 work instead), `insufficient_coverage`
(<60% of eval-window business days or <3 of the 7 episodes fully covered),
`quality_gate_failed` (the platform's real gate), `no_events_in_window`.

## 3. Windows, labels, scores (frozen)

- **Split:** train ≤ 2006-12-31; evaluate 2007-01-01 → 2024-12-31. The model
  never sees the evaluation span during training; normalisation statistics
  come from the training span and travel with the checkpoint.
- **Labels:** `label_events` on the raw series with the registry's stress
  direction, quantile 0.95 of the horizon-move distribution, horizon 21
  business days, persistence 5 steps, threshold span = the full evaluation
  window (declared historical mode). Labels see the future by construction —
  that is what a label is — and never touch features.
- **Scores:** per-timestep out-of-sample risk series from
  `predict_risk_series` on a frozen small TAN (config in the YAML; seed 11;
  small by design so the run fits a 2-CPU host — pre-registration is about
  the rules, not the compute). Scores are sign-adjusted by the registry
  direction so higher always means more stress, and joined to labels via
  `row_offset` (the documented `RiskSeriesResult` contract), never by
  truncation.
- **Alarms:** `score >= quantile(score, 0.95)` over the evaluation span —
  the `run_backtest` idiom.
- **Baselines:** persistence (sign-adjusted standardized level) and AR(1)
  (OLS fitted on the training span), on the identical aligned grid with the
  identical alarm rule.

## 4. Criteria (ALL must hold for an indicator to pass)

1. median lead ≥ **10 business days** (earliest-alarm convention, max lead 42);
2. false alarms ≤ **4 per quiet year** (quiet year = 252 non-event steps; an
   alarm simultaneous with an event is false — it warned nobody);
3. AUC **and** AP strictly above **both** baselines;
4. AP above the event base rate, with a permutation p-value (1000 label
   shuffles, seed 20260917) surviving **Holm–Bonferroni at α = 0.05** across
   the tested family.

**Family verdict:** ≥ half of the tested indicators pass all criteria, **and**
at least **3** indicators were testable. Fewer than 3 tested ⇒ no
system-level claim regardless of outcomes — a claim graded on one indicator
is a claim graded on an anecdote.

## 5. Run rules

- **Single run** per tagged protocol. Re-runs only for documented
  infrastructure defects, each logged with its diff.
- **Negative results are published unchanged.** The README claim gate moves
  only on a passing run; a failing run leaves the honest default in place
  and still lands its numbers here.
- **Sensitivity ≠ selection:** any post-run exploration (other horizons,
  quantiles, windows) is reported as sensitivity in a *new* document and
  never retro-fitted into this protocol's verdict.
- **Deviations, declared:** v1 executes in-process
  (`scripts/run_preregistered_eval.py`) rather than through the Celery job
  queue, mirroring `run_backtest`'s event idiom (same labeller, metric
  functions and alarm rule) with the corrected alignment/sign handling that
  idiom received in the same change; v1 uses the chronological holdout,
  with CPCV declared as the v2 upgrade.

## 6. Data provenance

Every series is fetched through the platform's own FRED plugin (keyless
`fredgraph.csv` path), certified by the real quality gate before scoring,
and recorded in `data/prereg/manifest.json` with endpoint URL, fetch
timestamp, SHA-256, row counts, measured frequency and coverage. The
manifest is part of the tagged artefact: the family that runs is the family
the data-availability rules produced, frozen before any metric existed.
