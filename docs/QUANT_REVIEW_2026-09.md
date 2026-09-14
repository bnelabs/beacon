# Independent Quantitative Review — BEACON (September 2026, fourth round)

An external review of the repository as cloned on 2026-09-14
(`main` @ `4464eb1`), focused on the quantitative logic: the training,
validation, inference and scoring paths, the systemic-risk models, and the
data-governance machinery behind them. Per the commission, authentication,
Grafana and Prometheus are out of scope.

Standard of evidence: every defect below was **reproduced**, not inferred.
The reproduction script for the two training defects is preserved in
`§9 Verification`. The full backend suite was run in a clean environment
(`torch 2.14.0+cpu`, `numpy 2.4.6`, `pandas 2.2.3`, Python 3.11):
**1725 passed, 7 skipped, 0 failed** in 5 minutes. The suite is green.
The most serious findings below are defects the suite does not touch —
which is itself the round's central lesson, and the reason this document
exists in the repository rather than in an issue tracker.

---

## 0. Verdict

**The research layer of this repository is genuinely strong; the production
learning path is broken in ways a green test suite cannot see.**

The systemic-risk modules (Eisenberg–Noe multiplex clearing, the coupled
Greenwood–Landier–Thesmar fire-sale solver, the Brunnermeier–Pedersen spiral,
Basel III translation, crowded-trade overlap, persistence-vector topology)
are textbook-correct, hand-verified against closed forms, and honestly
documented about their own limits. The data-governance spine (typed errors,
no synthetic fallbacks, attestations, fail-closed prediction gating, the
reachability census) is better engineering discipline than most production
risk codebases ever achieve.

But the path that actually produces the numbers the product displays —
`POST /api/v1/pipeline` → `EngineOrchestrator` → `ResultsGenerator`, and
`run_training` → `MultiScaleTrainer` — contains defects that make its
outputs either unrunnable, uninterpretable, or both:

1. **Training cannot run at all under the repository's own pinned torch.**
   `ReduceLROnPlateau(verbose=True)` was removed in torch 2.x's later
   releases; `requirements.txt` pins `torch==2.14.0`. Both trainers raise
   `TypeError` at scheduler construction. Every `run_training` job fails
   before epoch one. *(Fixed in this round; regression-tested.)*

2. **When the validation split is empty — which is the normal case for
   multi-source production data — training silently ships the epoch-0
   checkpoint.** `_validate` returns `0.0` for an empty loader; `0.0 < inf`
   is true exactly once, at epoch 0, and never again. Reproduced:
   `best_epoch=0`, `val_loss=[0.0]*N`, 50 epochs of compute discarded.
   *(Fixed: empty validation is now a loud `ValueError`.)*

3. **Validation/test normalization statistics are computed from the
   validation/test splits themselves**, while the model was trained in the
   train split's standardized space. Reported test MSE/MAE/R² are computed
   in a space the deployed model never inhabited; the direction of the
   distortion is arbitrary. Reproduced: reported error 0.93× the true
   deployment error on one seed, with per-source mean offsets of 11–190
   raw units. This is both a leak (test-window statistics inform the
   reported metric) and a mismatch (the metric does not describe the
   artifact that ships). *(Fixed: train-split statistics are now the only
   statistics; val/test datasets receive them explicitly.)*

4. **The pipeline route scores raw-scale, source-pooled windows through a
   per-source-standardized model, with `source_id=0` for everything, and
   when no checkpoint exists it scores them through a randomly initialized
   LSTM and calls the output a risk score.** `EngineOrchestrator._predict`
   reads the concatenated long-format frame as one series: windows straddle
   source seams (the exact artefact `backtesting.py` exists to prevent),
   no `source_stats` are applied even though `_get_model` loads them, and
   `_compute_risk_scores` thresholds the raw model output at 30/60/80 as
   if it were a 0–100 scale. The resulting `overall_risk_score`,
   `risk_level`, executive summary, PDF and risk-map inputs are not
   measurements of anything. *(Fixed in this round: fail-closed without a
   checkpoint; per-source normalized, seam-free windows; honest
   "uncalibrated" semantics.)*

5. **The semantic bridge from model output to "risk" does not exist.**
   Everywhere in the product, the model's output — a one-step-ahead
   prediction of the *standardized next value* of an indicator — is
   presented as a bounded risk level: thresholded at 0.3/0.6/0.85 for
   low/medium/high/critical, multiplied by 100 and printed as
   "Overall Risk Level: -31.4%", rendered as "Average predicted liquidity
   stress". A predicted next value is not a probability, not bounded, and
   its sign meaning depends on the indicator (a rising HQLA level is good;
   a rising FX-swap basis is bad). No per-indicator sign convention exists.
   This round makes the pipeline path say "uncalibrated" instead of
   inventing a level; the real fix is a defined risk target and
   calibration (§8, Phase 2), which must not be improvised.

None of these five was visible to the test suite, because **no test
exercises `ModelTrainer.train`, `MultiScaleTrainer.train`, or
`EngineOrchestrator._predict`/`_compute_risk_scores` end-to-end.** The
suite tests components with unusual rigor (closed forms, independent
optimizers, hand-computed equilibria) and then leaves the composition —
the thing that actually runs — untested. The reachability census fixed
"implemented but unreachable"; this round's guard must fix "reachable but
never composed in a test". Tests for the composition are added here.

---

## 1. Is the logic on the true trajectory?

**Direction: yes. Altitude: the research fleet is three decks above the
engine room.**

The stated goal — systemic liquidity-risk prediction from temporal graph
models, gated by data quality — decomposes into four sub-problems, and the
repository is at genuinely different maturity levels on each:

| Sub-problem | State | Trajectory |
|---|---|---|
| Data governance (PIT, attestations, quality gate, no fabrication) | Strong, wired, tested | Correct trajectory; closest to production-grade |
| Systemic scenario mechanics (clearing, fire-sale, spiral, regulatory translation, overlap, topology) | Strong, wired via `BankRiskAnalyzer`, tested against hand-computed fixed points | Correct trajectory; limited by *inputs*, not code (§4) |
| Supervised ML forecasting (attention/LSTM next-value regression) | Broken in composition (findings 1–4); the components are fine | Off trajectory until the target is defined (finding 5) |
| Calibration & uncertainty (conformal, HMM regimes, uncertainty decomposition, MoE) | Implemented, tested, **not wired** — recorded honestly in the census | Right modules, queued decisions |

The trajectory problem in one sentence: the platform is building
increasingly sophisticated *machinery* on top of a supervised-learning
core whose **target variable has never been defined**. "Liquidity risk"
is not a column in any feed. The model regresses the next standardized
value of whatever indicator the catalogue selected, and the product
narrates that number as risk. Every downstream sophistication (conformal
intervals, regime labels, uncertainty decomposition) will inherit that
ambiguity unless the target question is answered first: *risk of what,
measured how, over what horizon, labelled from which observable?*

The honest answer available in this codebase is already written down —
`event_metrics.py` needs "a labelled event target series, which the
pipeline does not produce" (census, `decide`). That is the true
trajectory: define the event (e.g. a stress episode where an indicator
crosses a declared quantile threshold within h days, or a realized
clearing shortfall under the scenario engine), label history with it, and
train toward the label. Everything else — Student-t HMM regimes as
features, conformal intervals as outputs, CPCV as validation — is already
built and waiting for exactly this.

## 2. Are the processes viable, correct, and SOTA for the given tasks?

By subsystem, with the honest qualifier of what "SOTA" means for a
monitoring platform of this size:

**Viable and correct (wired):**
- *Eisenberg–Noe multiplex clearing* — greatest-fixed-point iteration with
  seniority-ordered allocation; insolvency vs illiquidity separated. This
  is the standard, and the implementation matches the literature.
- *Coupled fire-sale equilibrium* — round-based fixed point closing the
  clearing shortfall through margin-constrained liquidation and linear
  price impact, with λ=0 feedback isolation and λ* stability boundary.
  Greenwood–Landier–Thesmar done properly, reusing (not reimplementing)
  the clearing engine and the spiral's margin law.
- *Validation harness* — seam-aware directional metrics, walk-forward with
  embargo, CPCV with path counting. CPCV is the current best practice for
  financial backtest overfitting (López de Prado); having it wired as a
  selectable scheme is ahead of most production shops.
- *Basel III translation* — LCR/NSFR/leverage with named constants,
  HQLA waterfall, None-as-breach. Documented subset, honestly bounded.
- *Data governance* — typed failures, no synthetic fallbacks (with two
  real fabrications found and removed in round three), attestation-gated
  prediction, content-addressed snapshots, PIT vintages.

**Correct but not SOTA (acknowledged in-repo):**
- *Student-t HMM* — symmetric tails only; no skew-t, no generalized
  hyperbolic, no semi-Markov durations (regime persistence is geometric).
  For crisis monitoring, duration modelling is the known next step; the
  module's own docstring says so.
- *Neural SDE* — Euler–Maruyama/Milstein verified at the right strong
  convergence orders, but a diffusion cannot jump. Crisis liquidity events
  are jump-heavy. Acknowledged; a jump-diffusion (Merton/Hawkes-driven)
  would be the upgrade.
- *NOTEARS causal discovery* — correct linear + nonlinear basis with
  declared-structure validation; no FCI, so latent confounding is not
  handled. The finding that z-scoring breaks equal-noise-variance
  identification is a real, non-obvious correctness result — good.

**Not viable as wired (this round's findings):**
- The training path (findings 1–3) and the pipeline scoring path
  (finding 4). Before this round's fixes, a production deployment could
  not train at all, and its pipeline route reported fabricated risk
  levels.

**Neither viable nor dead — the parked layer:**
Toto foundation encoders (a live multi-GB dependency cost for an encoder
only a benchmark script constructs), SubgraphX (needs a game value nothing
produces), federated learning with Bonawitz masking (needs a coordinator
that does not exist), event metrics (needs labels that do not exist). The
census records these honestly. The pragmatic call: **decide or delete
Toto** (the dependency is paid on every image build), keep SubgraphX and
event_metrics as the consumption points for Phase 2's labels and game
values, keep federated parked.

## 3. Do the approaches introduce new horizons?

Three things here are more thoughtful than the field's default:

1. **The reachability census** (`test_reachability.py`) — a mechanical
   import-graph assertion that "implemented" and "running" never silently
   diverge, with per-orphan dispositions. This is a governance innovation
   worth exporting to other quant codebases; the three-times-burned
   docstring is the correct institutional memory.
2. **Multiplex clearing with seniority + FX-swap exposure/basis layer
   separation** — refusing to clear a *price* layer (`require_exposure`)
   encodes a category error most network-contagion papers commit silently.
3. **Persistence-vector topology as a fixed-width gate input** —
   topological signatures of the exposure network feeding a quality gate
   is a genuinely novel composition, and the stability property (lifetime
   monotonicity) is tested rather than asserted.

What is *not* a new horizon, said plainly: the ML core is a small
transformer/LSTM next-value regressor — a 2019-vintage baseline. That is
fine *if* the target were well-defined and the lift over baselines were
measured (the single-scale trainer does report walk-forward lift over
persistence/AR(1)/linear baselines — the multi-scale trainer does not,
and should). The horizon claim of the README ("systemic liquidity-risk
predictions from temporal graph models") currently rests on a temporal
attention model over per-source indicator series; the *graph* enters only
through the scenario modules, not the predictor. The TGN
(`TemporalGraphNetwork`) exists but is constructed nowhere (census,
`UNUSED_SYMBOLS`). Until either the event target lands or the TGN is
wired, the honest description is: **a governed data platform with a
textbook systemic-scenario engine and a baseline forecaster.**

## 4. Are systemic volatilities captured?

Captured **mechanically**, yes; captured **empirically**, no — and the gap
is inputs, not code:

- Heavy tails: Student-t emissions (fitted ν per state, EM, verified
  against `scipy.stats.t.fit`) — but unwired.
- Stochastic volatility: neural SDE latent dynamics — wired as a
  *caller-declared scenario*, never calibrated to data. The repo says so
  explicitly ("simulated scenario dispersion under a declared SDE, not a
  calibrated prediction interval"). Correct labeling; zero empirical
  content until calibration exists.
- Contagion: clearing + fire-sale + spiral coupling — again, scenario
  inputs (endowments, liabilities, margins, price impacts, holdings) are
  caller-supplied. The PIT bilateral-exposure store and the upload API
  exist, but no feed populates real interbank matrices (granularity is the
  known industry wall; the connectors decision record documents this).
- Funding stress: FX-swap/basis layer design is right; no live basis feed.
- Crowding: overlap measures are hand-verified; holdings frames are
  caller-supplied.

So the platform's systemic volatility story is: **every amplifier is
modeled, none is measured.** The failure mode to avoid next is
calibrating these amplifiers to invented matrices. The correct next input
frontiers, in order of public availability: (1) realized stress episodes
from indicator history (labels — feeds §1's target), (2) FDIC call-report
derived exposures for US banks (the FDIC plugin exists), (3) ECB/FX basis
series via existing plugins, (4) declared G-SIB balance-sheet approximations
with explicit uncertainty. Absent those, the scenario engine should be
presented as what it is: a conditional laboratory, not a monitor.

## 5. How successful can it be? (pragmatic assessment)

- **As a data-governance + scenario-laboratory platform:** high
  probability of real value, near-term. The gate/attestation/PIT spine and
  the scenario engine are defensible, auditable, and already honest about
  their inputs. A supervisor or risk team could use it this quarter to run
  declared-scenario contagion analysis with full provenance.
- **As a predictive early-warning system:** not yet, and the binding
  constraint is not model capacity — it is the missing target definition
  and the missing calibration (Phase 2). With those, the building blocks
  (CPCV, conformal, Student-t regimes, baselines-lift reporting) are
  already in place, which is more than most teams attempting this have.
  Literature base rates for crisis early-warning are humbling: honest
  systems achieve useful-but-imperfect signal (think AUC 0.7–0.85 on
  1–2-year horizons with heavy class imbalance), and any demo showing
  R²>0.9 on "risk" is measuring the wrong thing. Success here should be
  pre-registered as: lift over persistence/AR baselines under CPCV, with
  event-based precision/lead-time from `event_metrics.py` — both harnesses
  already exist in this repo, waiting for labels.
- **Trajectory risk:** the pattern of three review rounds finding the same
  class of defect (capability exists ≠ capability runs ≠ capability means
  what its label says) will recur at the *semantic* layer unless the
  composition-test guard added this round is extended: every product-facing
  number needs a test that asserts its *interpretation*, not just its
  arithmetic.

## 6. What to add / what to remove

**Add (priority order):**
1. Composition tests for the live paths (added this round: trainer smoke
   tests, pipeline scoring tests). Extend to `run_training`/`run_backtest`
   task bodies with an in-process Celery eager mode.
2. An **event labeller** module: from certified indicator history and a
   declared threshold quantile + horizon, produce the binary stress-event
   target series; feed `event_metrics.py` (retires a census `decide`).
3. **Conformal wiring** in `RealPredictionEngine` per the census's own
   next-step: held-out rolling residuals per source →
   `SplitConformalCalibrator` → populate `confidence_lower/upper` and
   `confidence_method` (currently `(None, None)`), then
   `uncertainty.py` decomposition behind it (retires two census items).
4. A **per-indicator semantics registry**: for each catalogue item, the
   direction in which the indicator signals stress (+1/−1), its unit, and
   whether higher levels or higher *changes* are the risk object. Without
   this, no score aggregation across sources is meaningful — today's
   `avg_risk` averages apples and inverted apples.
5. Data-driven train/val/test split defaults (added this round: splits
   derive from the payload's own date range, chronologically, per source).
6. Multi-scale trainer baseline-lift reporting (parity with single-scale).
7. HSMM durations and a jump component in the latent SDE — only after 2–4.

**Remove / decide:**
1. ~~Random-weight `SimpleRiskPredictor` fallback as a silent default~~
   (removed this round; survives only behind an explicit env override for
   tests, mirroring the unsafe-checkpoint-load pattern).
2. ~~`stability_score = 1/(1+std(diff))`~~ — a smoothness statistic
   dressed as a quality metric (removed this round; smoothness of an
   uncalibrated score is not evidence of anything).
3. Static boilerplate `key_recommendations` in every report regardless of
   data — either derive from findings or label as generic guidance
   (flagged; left to the report owner).
4. `toto-2` + `gluonts` + `einops` + `huggingface-hub` from the production
   image until the Toto decision is made — the census already names this
   as a live cost.
5. README's stale backtesting claims (Sharpe/Sortino/VaR/CVaR) — the code
   deliberately deleted them; the README still advertises them (fixed this
   round).

## 7. Findings register (with dispositions)

| # | Severity | Finding | Location | Disposition |
|---|---|---|---|---|
| F1 | P0 | `ReduceLROnPlateau(verbose=True)` crashes under pinned torch 2.14 — no training job can run | `trainer.py:232`, `multi_scale_trainer.py:366` | **Fixed** + regression test |
| F2 | P0 | Empty validation loader → `_validate()==0.0` → best checkpoint frozen at epoch 0 (multi-scale); `ZeroDivisionError` (single-scale) | `multi_scale_trainer.py:487`, `trainer.py:465` | **Fixed**: loud `ValueError` + tests |
| F3 | P0 | Val/test normalization stats computed per split; evaluation denormalizes train-space outputs with test stats — reported metrics ≠ deployment, plus test-window leak | `MultiSourceDataset`, `TimeSeriesDataset`, both trainers | **Fixed**: train-split stats passed explicitly + tests |
| F4 | P0 | Pipeline route: source-pooled raw-scale windows, `source_id=0`, no checkpoint normalization; random-weight LSTM fallback presented as risk scores; standardized output thresholded on a 0–100 scale | `engine/orchestrator.py` `_predict`/`_get_model`/`_compute_risk_scores` | **Fixed**: fail-closed, per-source seam-free normalized scoring, `risk_level="uncalibrated"` + tests |
| F5 | P0 | Hardcoded default train/test windows (2023-01-01…2024-12-31) silently discard live data; positional `iloc` 80/20 train/val split over a source-major frame splits by *source*, not time — and empties validation (triggers F2) | `tasks/job_tasks.py` `run_training` | **Fixed**: chronological per-source split helper, data-derived defaults + tests |
| F6 | P1 | Product semantics: standardized next-value regression presented as bounded risk (0.3/0.6/0.85 bands; "Overall Risk Level: {x*100}%"; "Average predicted liquidity stress") with no per-indicator sign convention | `bank_analyzer._score_bank`→`_risk_level`, `prediction_engine._predict_single`, `results/generator.py` | **Partly fixed** (pipeline path now says "uncalibrated"); full fix = Phase 2 target+calibration+semantics registry |
| F7 | P1 | Latent off-by-one: model predicts row t+1; backtest aligns `risk_score` at window-end row t with `target[t]` — wrong the moment any producer supplies a target column | `prediction_engine.predict_risk_series` / `job_tasks.run_backtest` | **Fixed**: explicit `predicted_row_offset` convention, seam-guarded + test |
| F8 | P1 | Train/inference padding mismatch: `mode='edge'` in `MultiSourceDataset` vs zero-pad in `_prepare_sequence` | `multi_scale_trainer.py:127` | **Fixed**: both zero-pad at the standardized mean + test |
| F9 | P1 | `stability_score` fabricated metric; boilerplate recommendations; "Funding Pressure" factor rendered with NaN score | `engine/orchestrator._evaluate`, `results/generator.py` | **Fixed** (stability_score removed); remainder flagged for report owner |
| F10 | P2 | README advertises deleted backtest metrics (Sharpe/Sortino/Calmar/VaR/CVaR, "rising risk = negative return") | `README.md` §Backtesting | **Fixed** |
| F11 | P2 | No test composes the trainers or the pipeline scoring path — the class of defect F1–F5 is invisible to a green suite | test suite | **Fixed** (composition tests added); extend to task bodies next |
| F12 | P2 | Census `decide` items aging: Toto dependency cost, SubgraphX game value, event labels, causal-validation producer | `test_reachability.py` | Documented; Phase 2 consumes event labels |
| F13 | P2 | Frontend risk map mixes live API with bundled `networkConnections` demo data (labeled "DEMO NETWORK" — honest, but static arcs still render beside live layers) | `frontend/src/components/map/RiskMap.jsx` | Flagged (out of quant scope) |

## 8. The fix plan

**Phase 1 — Make the live path true (executed in this PR).**
F1–F5, F7–F11 as dispositioned above. Principle: every product-facing
number is either a measurement with stated semantics or explicitly
unavailable. No scale inventions, no silent fallbacks.

**Phase 2 — Define the target and calibrate (next PR; design fixed here).**
1. `backend/modules/data/event_labeller.py`: from a certified payload and
   a declared `EventDefinition(indicator, quantile_threshold, horizon_days,
   direction)`, emit the binary stress-event series (PIT-safe: uses only
   observations published as of each date). Wire into `event_metrics.py`
   (retires census item) and expose as a training target option.
2. Semantics registry (§6.4) attached to catalogue items; `_score_bank`
   and the risk-series path consult it so aggregation never averages
   inverted indicators.
3. Conformal wiring in `RealPredictionEngine.predict` per census next-step:
   per source, roll the frozen model over a held-out tail (default last
   `calibration_window=120` rows, excluding the final window), fit
   `SplitConformalCalibrator(alpha=0.1)`, populate `confidence_lower/upper`
   (denormalized) and `confidence_method="split_conformal"`; report
   empirical coverage in the job result. Then `uncertainty.py`
   decomposition behind the same seam (retires two census items).
4. Train the classifier head toward the event label (keeping the
   regression head for the level), report lift over baselines under CPCV
   and precision/lead-time under `event_metrics`. Multi-scale trainer
   gains the same baseline-lift report the single-scale trainer has.
5. Only then: Student-t HMM regime label attached per source (census
   `wire` item), feeding `mixture_of_experts`.

**Phase 3 — Empirical grounding (product decision, not code).**
Real exposure inputs (FDIC-derived, declared approximations with stated
uncertainty), live FX-basis feed, and a pre-registered evaluation
protocol for the early-warning claim. Jump-diffusion latent dynamics and
HSMM durations after the target exists.

## 9. Verification

- Full suite before this round's code changes: **1725 passed, 7 skipped**
  (torch 2.14.0+cpu / numpy 2.4.6 / pandas 2.2.3 / Python 3.11; the seven
  skips are pre-existing platform skips; `pyarrow` is required for
  `test_network_api` and `test_pipeline_integration` — the only failures
  seen in a clean env were its absence).
- F1 reproduction: instantiating either trainer under torch 2.14 raises
  `TypeError: ReduceLROnPlateau.__init__() got an unexpected keyword
  argument 'verbose'` at the first `train()` call.
- F2/F3 reproduction (synthetic 5-source frame, source-major concatenation
  identical to the formatter's, `iloc` 80/20 split exactly as
  `run_training` performs it):
  `len(val_dataset) == 0`; `best_epoch == 0`; `val_loss == [0.0]*epochs`;
  per-source train-vs-test-window stat offsets of 0.19–190 raw units;
  reported test MSE 0.93× the same frozen model's deployment-space MSE
  (denormalized with train stats, which is what inference does).
- New tests added this round:
  `test_trainer_composition.py` (F1, F2, F3, F8, split helper F5),
  `test_engine_orchestrator_scoring.py` (F4, F9),
  `test_risk_series.py` extension (F7),
  `test_pipeline_integration.py` updated for the fail-closed fallback (F4).
- After the fixes: full suite **1758 passed, 7 skipped** in the same environment
  (+33 new composition tests; `ruff check backend --select E9,F63,F7,F82` clean).

*Reviewer's note: this document deliberately states what was NOT fixed.
F6's full resolution, Phase 2 and Phase 3 are queued decisions with named
next steps, in the disposition-census style the repository established —
because "the review said it was addressed" is how the last three rounds'
gaps survived.*
