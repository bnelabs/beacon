# Event Target & Pre-Registered Evaluation — Proposal

> **Status: PROPOSAL — awaiting owner approval.** Nothing in this file is
> pre-registered until the protocol below is signed off, written into the
> artefacts it names, and git-tagged. This is a design document, not
> evidence; per the probe discipline, the evidence comes from the run.

## 1. The claim this gates

The README states the platform's own limit: *"Crisis early-warning needs a
labelled stress-event target (event labeller) and a pre-registered
evaluation … Until both exist the platform is a data-governance and scenario
laboratory, not a demonstrated early-warning system, and it does not claim
to be one."*

The machinery half **already exists, is wired, and is tested**:

| Piece | Where | State |
|---|---|---|
| Declarative event labelling (horizon-cumulative move × quantile × persistence, PIT threshold discipline, leakage rules) | `backend/modules/data/event_labeller.py` | wired, `test_event_labeller` |
| Early-warning metrics: ROC-AUC, step-sum average precision, precision-at-recall, earliest-alarm lead-time stats (incl. `n_zero_lead`), false-alarm cost stats | `backend/modules/engine/event_metrics.py` | wired, `test_event_metrics` |
| Backtest jobs accept a declared `event_definition`, resolve per-source direction from the semantics registry, label, align and score | `run_backtest` in `backend/tasks/job_tasks.py` | wired |
| Per-indicator stress-direction registry (13 codes, curated; `None` = refusal, not a default) | `backend/modules/data/semantics.py` | wired for event labelling |
| CPCV + walk-forward with embargo, lift over persistence/AR(1)/linear baselines that refit per fold | `backend/modules/engine/{cpcv,backtesting,baselines}.py` | wired |

What is missing is **decisions, not code**: a declared event taxonomy,
declared labelling parameters per indicator, and a pre-registered protocol
with decision rules frozen before anyone looks at results.

## 2. Event taxonomy

### 2.1 Series-level stress events (labelable today)

An event is what `EventDefinition` already means: the indicator's own
horizon-cumulative move in its registered stress direction crossing a
declared quantile of that move's distribution, persisting a declared
minimum duration. Labels may see the future by construction; they never
enter the feature side (the labeller's leakage rule, restated here because
the whole claim rests on it).

**Episode family — declared before any indicator data is examined** (the
selection rule is "widely-dated systemic episodes in the platform's
monitored geography", not "episodes where our series look good"):

| # | Episode | Declared window (stress period) |
|---|---|---|
| E1 | Global financial crisis | 2007-08-01 → 2009-03-31 |
| E2 | Euro-area sovereign crisis | 2010-05-01 → 2012-07-31 |
| E3 | EM/China capital-outflow shock | 2015-08-01 → 2016-02-29 |
| E4 | Repo-market spike | 2019-09-15 → 2019-10-15 |
| E5 | Dash-for-cash (COVID) | 2020-02-20 → 2020-04-15 |
| E6 | UK LDI / gilt turmoil | 2022-09-23 → 2022-10-31 |
| E7 | US regional-bank run, UBS/Credit Suisse | 2023-03-08 → 2023-05-31 |

**Indicator family — every code currently in the semantics registry** (a
fixed, already-curated set; no post-hoc additions):
`FRED_STLFSI4`, `FRED_KCFSI`, `ECB_CISS`, `FRED_SOFR`,
`FRED_BAMLH0A0HYM2`, `FRED_RRPONTSYD`, `FRED_T10Y2Y`, plus the registry's
remaining entries as at tag time. Indicators whose orientation the registry
does not declare are excluded by construction — the registry's `None` is a
refusal.

*Note for the owner:* the registry itself flags `FRED_RRPONTSYD`'s
direction as a funding-sense judgement; decide at sign-off whether it
participates.

### 2.2 System-level events (explicitly out of scope)

Bank failures and official interventions would need an institution-level
event calendar and per-bank data BEACON does not collect. Claimed nowhere,
built nowhere; listed here so the absence is a decision rather than a gap.

## 3. Labelling specification (defaults to freeze at sign-off)

All four knobs are existing `EventDefinition` parameters:

- horizon `h` = 21 business days (~1 month of realised stress);
- quantile `q` = 0.95 of the horizon-move distribution in the stress direction;
- persistence = 5 consecutive crossing days (a single spike is not an event; a slow burn is);
- `threshold_span`: the certified evaluation window for historical validation (declared up front, as the labeller requires); expanding point-in-time spans for any live use.

Sensitivity analysis (h ∈ {10, 21, 63}, q ∈ {0.90, 0.95, 0.99}) is reported
**as sensitivity, never as selection**: the headline numbers come from the
frozen configuration only.

## 4. Pre-registration protocol

1. **Artefacts.** `docs/prereg/early_warning_v1.md` (human protocol) plus
   `configs/event_eval_v1.yaml` (machine-readable: episodes, indicator
   family, labelling parameters, metric list, decision rules). Both are
   committed and git-tagged `prereg-early-warning-v1` **before** the
   evaluation run. Any change after tagging requires a new version and a
   CHANGELOG entry stating what changed and why — no silent edits, no
   untagged runs.
2. **Data requirements.** Every indicator's evaluation window must carry a
   DATA-stage quality attestation (the existing gate); minimum history per
   indicator = labeller minimum + horizon + persistence; no synthetic
   backfill anywhere (existing platform rule, restated because a
   pre-registration is only as good as its inputs).
3. **Metrics — all pre-registered, all reported per indicator, no
   cherry-picking:** event precision at the alarm window; recall;
   `lead_time_stats` (median and minimum lead, `n_zero_lead`);
   `false_alarm_stats` (cost per quiet year); ROC-AUC and step-sum average
   precision of the risk series against labels; and lift over persistence
   and AR(1) under CPCV, folded within each source, embargoed.
4. **Decision rules — declared here, evaluated once.** The headline
   "demonstrated early-warning" claim for an indicator requires ALL of:
   median lead ≥ 10 business days; false alarms ≤ 4 per quiet year;
   positive lift over both baselines under CPCV; average precision above
   the pre-declared event base rate. A **system-level** claim additionally
   requires the indicator-level bar to be met by at least half the family
   after Holm–Bonferroni adjustment across the family. These thresholds
   are proposals; the owner may change them **at sign-off only** — after
   the tag they are frozen.
5. **Single-run rule.** One evaluation run per tagged protocol. Re-runs
   only for documented infrastructure defects, each logged with its diff.
6. **Known limits, stated in advance.** Seven episodes is a small sample:
   confidence intervals will be wide (Wilson intervals reported for
   precision/recall); events across indicators overlap in time and are not
   independent, so no pooled cross-indicator statistic is reported as if it
   were; a pass demonstrates skill *on the declared family and window*, not
   universal early-warning ability.
7. **Negative results are published.** A failed run updates nothing in the
   claim language and still lands its numbers in the report artefact —
   absence of a claim stays honest in both directions.

## 5. Implementation steps (glue, not machinery)

1. Owner sign-off on §2–§4 (family, episodes, defaults, thresholds) — the decision gate.
2. Write `configs/event_eval_v1.yaml` + `docs/prereg/early_warning_v1.md`; tag.
3. `scripts/run_preregistered_eval.py`: reads the YAML, enqueues one
   backtest job per indicator with its declared `event_definition`
   (`run_backtest` already consumes it), collects the per-source
   `event_metrics` payloads, applies the frozen decision rules, and writes
   a single report artefact (metrics + CIs + provenance manifest — the
   reproducibility machinery for model manifests already exists).
4. README/claim gate: the "not a demonstrated early-warning system"
   sentence is edited **only** in the same change that links the tagged
   protocol and its run artefact.

Estimate: steps 2–4 are days of glue work; step 1 is the owner's call, and
data collection over the certified windows is the long pole.

## 6. What this proposal does NOT claim

- No result exists yet; no number in this file is an evaluation outcome.
- The labelling defaults in §3 are starting proposals, not tuned values —
  tuning them on outcomes would void the pre-registration.
- Indicator-level events are not bank-level early warning; §2.2 stays out
  of scope until institution-level event data exists.

---
*Deliverable of the post-audit roadmap (item 3). Companion artefacts: the
semantics-registry correction to the README ships with this proposal.*
