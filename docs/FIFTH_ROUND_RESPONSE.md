# Fifth Review Round — Response and Wiring Execution

The external executive review received 2026-09 (the "last-mile" review) is
answered here in the repository's standing style: every claim checked against
the tree, what was executed, what was rejected with reasons, and what stays
queued. The review's central thesis — *correct economic core, disconnected
sophistication* — was true of `main` at review time and is the same thesis the
repository's own reachability census has been managing since round three.
This round **executed the wiring slice** of that thesis.

Note on freshness: the review predates open PRs #31 (quant correctness),
#32 (rebrand/docs) and #34 (hygiene/versioning/language). Several of its
findings were already closed there; they are marked *superseded* rather than
re-argued.

## 1. Claim-by-claim audit

| Review claim | Verdict against the current tree |
|---|---|
| Eisenberg–Noe multiplex clearing is SOTA-aligned | **Confirmed.** Greatest-fixed-point iteration, seniority layers, insolvency/illiquidity split; hand-verified in `test_clearing.py`. |
| Coupled GLT fire-sale through the clearing engine is advanced and correct | **Confirmed.** Feedback isolation (λ=0 counterfactual default set) is a first-class output; `test_fire_sale.py` includes a hand-computed three-round fixed point. |
| Temporal attention is reasonable but not SOTA; frontier is temporal multiplex GNNs | **Agreed as direction, rejected as next action.** The TGN exists (`UNUSED_SYMBOLS` in the census) but wiring it requires exposure networks at training time; the PIT exposure store now exists, so this is queued with a concrete precondition, not refused. See §3. |
| Neural SDE sophisticated but "not wired" | **Partly stale.** Wired since round three as a caller-declared latent-stress scenario on the engine path (`REQUIRED_REACHABLE`). The review asks for it as the *default* propagator: rejected, §3. |
| HMM regime detection not wired | **True at review time; now wired.** `predict()` attaches a per-source Student-t HMM regime nowcast (higher-variance state = stress), with absence reported honestly on short payloads. |
| Mixture-of-Experts not wired | **Still true, and now unblocked on its missing input.** The live regime label exists; experts trained on labelled regimes remain the precondition. Census disposition updated accordingly. |
| Causal discovery/validation not wired | **Half stale.** NOTEARS is `REQUIRED_REACHABLE` (engine path). `causal_validation` remains a `decide` item: it compares a declared DAG against a learned one, and no product surface declares a DAG yet. |
| Systemic volatility not captured by the *running* system | **Improved this round.** Regime nowcast + split-conformal intervals now run in inference; the SDE remains a declared-scenario instrument. Full capture still requires calibration (§3). |
| Backtesting methodology (CPCV, embargo, no return-based metrics) is correct | **Confirmed**, and strengthened since: per-source folds, seam-aware directional accuracy, baseline-lift reporting, and (this round) event-based precision/lead-time scoring against declared event definitions. |
| Data governance is a strength | **Confirmed**; unchanged. |
| "Populate empty hypertables" (risk scores / metrics never written) | **True at review time; now wired.** `run_prediction` writes risk-score rows and `run_backtest` writes metric rows through `TimeSeriesStore`, with provenance; storage outages log and degrade rather than void the job. |
| Foundation encoder: integrate or remove | **Executed in #34: removed** (wrapper, benchmark, dependency train), contract and stand-in kept. |
| Persistence-vector topology "mentioned but not implemented" | **Stale.** Implemented (`persistence_vectors.py`) and fed through `BankRiskAnalyzer.topology_parameters` since the G-SIB build; `REQUIRED_REACHABLE`. |
| Heterogeneous price impacts missing from fire-sale | **Stale.** `price_impacts` is per-asset `(A,)` already. Cross-asset impact matrices remain queued. |
| Free/no-key sources missing (FDIC, BIS, ECB, OFR, e-MID, World Bank) | **Half stale.** FDIC, BIS, ECB, SEC EDGAR and World Bank plugins exist and need no key. OFR (×2) and e-MID do not exist; e-MID is a research edgelist whose value is *validation*, queued in §3. |
| Model cards absent | **Agreed in spirit, present in substance.** Every model module carries a limitations section in its docstring by repo convention; a consolidated model-card document is queued. |
| Dead code: delete or fix reachability | **In progress by design.** #34 deleted the Toto stack; this round wired five census items; the census remains the queue, not an excuse — each entry has a blocker, a plan and a next step, and a test fails if the census and the import graph disagree. |

## 2. Executed this round (branch `feat/wiring-round-five`)

1. **Split-conformal intervals in live inference.** Per source, the frozen
   model rolls over a held-out tail of the payload; residuals against observed
   next values calibrate a `SplitConformalCalibrator(alpha=0.1)`; the point
   score's interval is denormalized with the same statistics and reported in
   `confidence_lower/upper` with `confidence_method`. Short payloads report
   `insufficient_history_for_calibration` — absence, never a fake interval.
   Retires the census `wire` item for `conformal`.
2. **Live regime nowcast.** Student-t HMM (2 states) per source; stress =
   higher-variance state; label + method on every prediction row; absence on
   short history. Retires the census `wire` item for `hidden_markov` and
   produces the input `mixture_of_experts` was missing.
3. **Event labeller** (`backend/modules/data/event_labeller.py`): declarative,
   point-in-time-disciplined stress-event labels (direction, tail quantile of
   the horizon move, minimum duration, decay), with the threshold span carried
   on the result so what the threshold saw is auditable. Wired into
   `run_backtest` via an optional `event_definition` job parameter: per-source
   ROC AUC, average precision and conservative earliest-alarm lead time from
   `event_metrics`. Retires the census `decide` item for `event_metrics` and
   makes the review's Phase 4 (lead time, false-positive rates) computable.
4. **Hypertable writers.** `run_prediction` → `record_risk_scores`;
   `run_backtest` → `record_model_metrics`. Uncalibrated scores persist with
   `risk_level` null. Retires the census `wire` item for `timeseries_store`.
5. **Topology gate wired.** `BilateralExposureStore.assess_topology()` builds
   the reference from the matrix's own PIT vintages (`load_as_of` per published
   stamp) and assesses the live signature; `ingest` attaches the assessment to
   the manifest. Fewer than two vintages reports *unavailable, not passed*.
   Retires the census `wire` item for `network_gate`.
6. **Census updated**: five modules promoted to `REQUIRED_REACHABLE`,
   `event_labeller` added, MoE disposition rewritten. The guard test fails if
   any promotion is false.

Tests: `test_event_labeller.py`, `test_prediction_uncertainty.py`, plus the
reachability guard; full suite green on the branch (count in the PR body).

## 3. Rejected or queued, with reasons

- **Neural SDE as the default latent propagator — rejected.** A diffusion's
  drift and volatility must be calibrated or they are fiction; the honest
  instrument today is a caller-declared scenario, labelled as such in every
  output. Defaulting it would manufacture dispersion the data never asserted.
  Queue: calibrate the SDE to regime-conditional residuals, then revisit.
- **MoE as the primary forecaster — queued, not refused.** Experts routed by
  regime need training targets per regime; wiring an untrained gate in front
  of the only working forecaster would degrade a measured system for an
  unmeasured one. Precondition: labelled regimes from the event labeller.
- **Temporal multiplex GNN — queued with its precondition named.** The TGN
  needs exposure snapshots aligned to training windows; the PIT exposure
  store and the topology gate now make that constructible. Design next round;
  no code until a training set exists.
- **Generalized-hyperbolic HMM — queued** (asymmetric tails; the Student-t
  limitation is documented in the module and unchanged).
- **OFR / e-MID plugins — queued.** e-MID's value is a validation harness for
  the clearing engine (ground-truth edgelist), not a live feed; that harness
  is the right next use. OFR endpoints need a stability review before a
  plugin promises them.
- **Cross-asset fire-sale impact matrices — queued**; per-asset impacts exist.
- **Consolidated model-card document — queued**; module docstrings carry the
  limitations today.

## 4. How successful can it be

Unchanged from the fourth round's assessment, one step closer: the platform's
scenario engine and governance were already defensible; inference now carries
calibrated intervals, regime state and event-based validation, and its outputs
persist with provenance. The remaining distance to an early-warning *product*
is calibration of the SDE/regime layer and a trained, labelled forecaster —
both queued above with their preconditions, neither improvisable.
