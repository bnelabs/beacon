# BEACON

**Banking Early-Alert Comprehensive Observation Network** — a systemic
liquidity-risk monitoring platform for banking networks, powered by the
Banking Network Engine (BNE).

BEACON answers one question with discipline: *how stressed is the liquidity
position of this set of institutions, what would contagion do if one of them
failed to pay, and how much of the answer is measurement versus assumption?*
It combines a governed multi-source data pipeline, a scenario engine built on
the standard contagion models of the literature, and temporal-model
forecasting — behind a data-quality gate that refuses to produce a number from
data that did not pass certification.

---

## What the platform does

- **Monitors** indicator history across US, European and Asian sources
  (ECB, FRED, BIS, IMF, World Bank, FDIC, SEC, market data) through a
  six-stage pipeline: collection → validation → cleaning → formatting →
  analysis → certification.
- **Scores** each monitored series with temporal sequence models and reports
  the score for what it is: a standardized one-step-ahead prediction with
  stated provenance — never a disguised probability (see
  [Scoring and validation](#scoring-and-validation)).
- **Simulates** contagion on declared balance sheets: Eisenberg–Noe
  multiplex clearing with seniority, the coupled Greenwood–Landier–Thesmar
  fire-sale spiral, Brunnermeier–Pedersen liquidity spirals, and Basel III
  ratio translation under stress.
- **Gates** everything: no prediction or backtest runs without a verified
  data-quality attestation, and no synthetic substitute is ever invented for
  missing data.

---

## Interface

A single-page application in a warm-paper, print-briefing idiom — serif
mastheads, hairline rules, tabular figures, and a moss→ochre→rust→clay risk
scale shared by badges, map markers and the legend. The full design system is
specified in [`docs/frontend.md`](docs/frontend.md). Four screens carry the
daily work; each is shown as it ships, against the mocked API, with no
invented data.

| | |
|---|---|
| ![Dashboard](docs/images/dashboard.png) | ![Risk Map](docs/images/risk-map.png) |
| **Dashboard** — the morning view: job activity, data-quality gate status and live host status (CPU, memory, disk, GPU, measured from `GET /api/v1/system/status`, never asserted). | **Risk Map** — geographic liquidity heat, institution markers and interbank exposure arcs on a bundled public-domain basemap; degraded backend states are stated in a strip above the map, never painted over it. |
| ![Models](docs/images/models.png) | ![Results](docs/images/results.png) |
| **Models** — the catalogue: architecture, training configuration and status per model, with the scenario builder that declares stress inputs explicitly. | **Results** — one job's output: predictions with conformal intervals where they exist, regime nowcast, and the reports every run leaves behind. |

Pages: Dashboard · Risk Map · Models · Jobs · Results · Data Sources ·
Country Profiles · Performance · Data Quality · Analytics · Settings.
Global search (⌘K), WebSocket job progress and CSV/JSON/PDF/Excel export are
built in. Guided help (a tour, a help centre) is deliberately absent while the
platform is still maturing; it returns when the system does.

---

## Architecture

```
Frontend (React 18 + Vite + Deck.gl + Tailwind)
  └── Single-page app, Zustand navigation, TanStack Query server state
  └── Design system: paper/ink/pine tokens, serif display, tabular figures
  └── Error boundary per view: a failing page degrades, the shell never blanks

Backend (FastAPI + Celery + Redis)
  └── DATA: 17 plugins → validation → cleaning → formatting → quality gate
  └── ENGINE: training, inference, backtesting, systemic scenario modules
  └── RESULTS: reports (JSON/Excel/PDF), prediction artefacts
  └── Jobs API (v1) + WebSocket progress relayed over Redis

Storage (TimescaleDB + Redis)
  └── Hypertables with compression and continuous aggregates for observations
  └── Point-in-time store for bilateral exposure vintages (as-of queries)
  └── Redis: Celery broker, result backend, WebSocket relay
  └── The schema covers indicator observations, risk scores and model
      metrics, and all three now have writers: observations via the DATA
      pipeline, risk scores via `persist_risk_scores` on prediction jobs
      (null-scored/refused rows are skipped), model metrics via
      `persist_model_metrics` on backtest jobs

ML (PyTorch)
  └── Temporal Attention Networks and LSTM sequence models, per-source
      normalization, continuous-time temporal graph memory primitives
  └── Neural SDE latent dynamics, NOTEARS causal discovery with
      declared-structure validation
  └── Gaussian and Student-t HMM regime detection — **wired**: the Student-t fit
      supplies the live per-source regime label in `prediction_engine.
      _regime_label`, which is what the mixture-of-experts census entry was
      waiting on
  └── Aleatoric/epistemic decomposition (deep ensembles) — **wired where
      members exist**: a training job with `ensemble_size >= 2` saves
      independently seeded members beside `best_model.pt`; the prediction
      engine decomposes each source's variance on the conformal calibration
      slice and *refuses* a prediction whose epistemic term spikes (the
      refusal is absence, never a number). A single-checkpoint model reports
      the split as not measurable rather than a fabricated zero
  └── Walk-forward and CPCV validation with lift over persistence/AR/linear
      baselines; seam-aware metrics that never difference across sources
  └── Systemic risk: Basel III LCR/NSFR/leverage translation, coupled fire-sale
      equilibrium, crowded-trade overlap, persistence-vector topology
  └── Metrics: MSE, MAE, RMSE, R², directional accuracy
  └── Walk-forward backtesting with seam-aware metrics; return-based portfolio
      statistics (Sharpe, drawdown, VaR) are deliberately NOT computed -- a risk
      score is a latent state, not a priced return
  └── No attribution is reported. The routine that presented gradient*input as
      SHAP values was removed rather than re-tuned, and SubgraphX, which replaced
      it, is implemented but not wired. Prediction results carry an empty
      `feature_importances` and no attention weights
  └── No foundation-model encoder. The Toto 2.0 wrapper and its dependency train
      were deleted in the 2026-09 hygiene round because no production path ever
      embedded a node with them; the `REMOVED` register in
      `backend/tests/test_reachability.py` records what returns with one
  └── CUDA + mixed precision training
```

### Reachability is a tested property

"Implemented" and "running" are different claims. `backend/tests/
test_reachability.py` walks the import graph from the production entry points
and fails if any module is unreachable and unaccounted for, if a module
recorded as unreachable quietly becomes reachable, or if a module marked as
wired contributes nothing. Every unreachable module carries a disposition
(`wire` / `decide` / `park`) with its blocker and next step, so a gap is a
queued decision rather than a silent one.

---

## Quick start

```bash
docker compose build
docker compose up -d

open http://localhost:9876      # Frontend
open http://localhost:3456/docs # API documentation (Swagger UI)
```

```bash
# Create a data collection job
curl -X POST http://localhost:3456/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type":"data_collection","parameters":{"regions":["PACIFIC"],"countries":["Japan"]}}'

# Check job status / reports
curl http://localhost:3456/api/v1/jobs/{jobId}
curl http://localhost:3456/api/v2/reports/brief/{jobId}
```

**Prerequisites:** Docker 20.10+ with Compose v2. No local Python/Node installs
required. GPU is optional (`docker-compose.gpu.yml`); see
[`docs/deployment.md`](docs/deployment.md) for weights, secrets and
verification.

---

## Data governance

Risk scores are only as trustworthy as the data behind them, so the platform
refuses to guess:

- **No synthetic fallbacks.** A missing dataset or failed provider raises a
  typed error (`DatasetMissingError`, `DataSourceUnavailableError`,
  `SchemaValidationError`, `EmptyDatasetError`) with a stable code. Nothing
  generates stand-in data.
- **Enforced quality gate.** Collected data is evaluated against an explicit
  `QualityPolicy` (row counts, required columns, missing-value ratio,
  freshness, minimum score) before certification. Failures raise
  `DataQualityError` and emit a data-quality notification.
- **Predictions are gated.** Prediction and backtest jobs require a verified
  DATA-stage attestation and raise `PredictionBlockedError` without one.
- **Point-in-time exposure vintages.** As-of queries on the bilateral exposure
  store never substitute a current matrix for one that did not exist yet.
- **Every failure is reported.** Ingestion failures return as typed
  `CollectionFailure` entries carrying the plugin and error code, so a partial
  run is auditable rather than silent.

---

## Scoring and validation

Sequence models are trained per source on standardized windows and evaluated
the way a monitor should be: chronologically, with embargoed walk-forward
folds or **CPCV** (combinatorial purged cross-validation), folded *within*
each source so no fold trains on one indicator and tests on another, and
scored against seam-aware metrics (`mse`, `mae`, `rmse`, `r2`,
`directional_accuracy`, `hit_rate`). Lift over persistence, AR(1) and linear
baselines is reported with the frozen model competing against baselines that
refit per fold — the conservative direction for a complexity claim.

Two honesty rules govern every reported number:

1. **A model score is not a risk probability.** The engine's output is a
   standardized one-step-ahead prediction of the monitored indicator. Until a
   calibrated mapping exists, risk levels are reported as *uncalibrated* with
   their semantics attached, rather than banded against an invented scale.
   Return-based portfolio statistics (Sharpe, drawdown, VaR) are deliberately
   not computed on a risk-state series: they characterise a priced asset.
2. **Absence is reported as absence.** Missing measurements render as
   unavailable — in the API, the reports and the UI — never as zero, and
   never as a rescaled copy of something else.
3. **Restatements leave tracks.** Every observation write appends to an
   append-only vintage log, so any past number can be re-derived as of
   any date; a revised figure never silently rewrites what yesterday's
   decision could have seen.

The calibration roadmap (event labelling, per-indicator semantics) used to
live in a round-by-round review narrative. That narrative was development
history, not user documentation, and it was deleted; this list is the
register now, and it is kept short on purpose:

- **No calibrated risk scale.** Risk levels are reported as *uncalibrated*;
  nothing bands a standardized score against an invented 0–100 scale.
  Prediction *intervals* are a separate, wired matter: split-conformal bounds
  are computed per source wherever the payload's own held-out residuals
  support a calibration window, and are `null` — with `confidence_method`
  recording why — wherever they do not.
- **No event target yet.** Crisis early-warning needs a labelled stress-event
  target (event labeller) and a pre-registered evaluation — lift over
  persistence/AR baselines under CPCV, event precision and lead time. Until
  both exist the platform is a data-governance and scenario laboratory, not a
  demonstrated early-warning system, and it does not claim to be one. The
  labelling machinery and metrics are wired; what is missing is the declared
  target and the frozen protocol — see
  [`docs/probes/event_target_proposal.md`](docs/probes/event_target_proposal.md)
  (proposal awaiting sign-off; nothing in it is pre-registered yet).
- **No cross-source score aggregation.** A per-indicator stress *direction*
  registry does exist (`backend/modules/data/semantics.py`, used by the
  event labelling in backtests; an undeclared orientation is a refusal, not
  a default). Aggregation still waits on per-indicator *units* and an
  agreed combination rule; without them, averaging scores across sources
  would average apples with inverted apples.

---

## Systemic-risk engine

Scenario modules consume declared inputs only — balance sheets, holdings,
margins, price impacts — and state their limits in their own docstrings:

| Module | Model |
|---|---|
| `risk/clearing.py` | Eisenberg–Noe clearing vector over a multiplex with seniority-ordered layers; insolvency vs illiquidity separated |
| `risk/fire_sale.py` | Greenwood–Landier–Thesmar fire-sale fixed point closed through the clearing engine, with λ=0 feedback isolation and λ* stability boundary |
| `risk/liquidity_spiral.py` | Brunnermeier–Pedersen margin/price spiral; shock derived from the clearing shortfall |
| `risk/regulatory.py` | Basel III LCR / NSFR / leverage translation under stress, HQLA waterfall, `None`-as-breach |
| `engine/portfolio_overlap.py` | Crowded-trade overlap and correlated-unwind measures |
| `engine/persistence_vectors.py` | Fixed-width topological signature (landscapes + images) of the exposure network |
| `engine/hidden_markov.py` | Gaussian and Student-t HMM regime detection (fitted degrees of freedom) |
| `engine/neural_sde.py` | Neural SDE latent stress scenarios, Milstein-verified strong convergence |
| `engine/causal_discovery.py` | NOTEARS (linear + non-linear basis) with declared-structure validation |

---

## Model security

Checkpoints load through `backend/modules/engine/model_io.py` with
`torch.load(..., weights_only=True)`. Legacy checkpoints that are not
weights-only serialisable are rejected unless an operator explicitly sets
`BEACON_ALLOW_UNSAFE_CHECKPOINT_LOAD=1`, which is logged as a security event.
Training writes checkpoints through `safe_torch_save`, which verifies at save
time that the artefact will load under the restricted unpickler. Scoring
without any trained checkpoint fails closed rather than falling back to
untrained weights.
Backtest jobs run a walk-forward evaluation (expanding or rolling windows with
an optional embargo), folded *within each source's own contiguous span* so no
fold trains on one indicator and tests on another, and report the supervised
metrics that are meaningful for a risk-state series:

`mse`, `mae`, `rmse`, `r2`, `directional_accuracy`, `hit_rate`, plus per-fold
results and per-source skips.

Return-based portfolio statistics (Sharpe, Sortino, Calmar, drawdown,
volatility, VaR/CVaR) are deliberately not computed: they characterise the
return of a priced asset, and a liquidity-risk score is a latent state, not a
price. Ground truth, when a target column exists, is joined on
`predicted_row_offset` -- the score for the window ending at row `t` predicts
row `t+1` of the same source. Available via
`GET /api/v2/reports/backtest/{job_id}`.

---

## Database Migrations

Alembic is the single source of truth for schema. Containers run
`alembic upgrade head` from `backend/entrypoint.sh` before the API or worker
starts (retry-looped for first-boot races; `BEACON_RUN_MIGRATIONS=0` opts
out), so deployments receive hypertables and continuous aggregates rather
than silently running on the base-table fallback. The baseline migration
`baseline_core_001` reconciles tables that historically came from
`Base.metadata.create_all`; every change after it is an explicit migration.

```bash
export DATABASE_URL=postgresql://beacon_user:beacon_password@localhost:5432/beacon_db
alembic upgrade head        # apply migrations (idempotent; inspector-guarded)
alembic history             # revision chain
alembic upgrade head --sql  # render SQL for review without touching a database
```

Time-series tables become TimescaleDB hypertables with continuous aggregates
via `timescale_001`; without TimescaleDB the migration creates plain tables
and logs a warning, and `TimeSeriesStore` falls back to base-table
aggregation. The Alembic migrations are the single source of truth for the
schema; there is deliberately no second copy of the DDL that could drift.

## CI/CD

CI is split into a **sub-minute pre-merge gate** (static checks that need no
browser, no torch, no bundler) and **nightly/on-demand deep runs** (the full
test suite, the production build, the Playwright suite). A gate that takes ten
minutes is a gate nobody waits for; the deep runs surface the same regressions
at most a day later — or immediately via `gh workflow run <file> --ref <branch>`.

| Workflow | Purpose | Triggers |
|---|---|---|
| `.github/workflows/backend-ci.yml` | Syntax gate (`compileall`) + compose/Dockerfile validation — no dependency tree | push/PR (**< 1 min**) |
| `.github/workflows/frontend-ci.yml` | Strict `tsc --noEmit` over all of `frontend/src` + e2e mock-coverage audit | push/PR (**< 1 min**) |
| `.github/workflows/versioning-ci.yml` | Version-policy guard | push/PR (**< 1 min**) |
| `.github/workflows/backend-tests.yml` | Full `pytest` + coverage, live-migration Postgres, generated-API-docs check | nightly + dispatch |
| `.github/workflows/frontend-e2e.yml` | Production `vite build` + mocked Playwright suite | nightly + dispatch |
| `.github/workflows/security.yml` | Advisory `pip-audit` and `npm audit` | weekly + dispatch |
| `.github/workflows/docker-backend.yml` / `docker-frontend.yml` | Build the real images | dispatch only |

Dependabot keeps GitHub Actions current (pip/npm security-only; no Docker
entry). Local equivalents for every job:
[`.github/workflows/README.md`](.github/workflows/README.md).

---

## Documentation

Full index: [`docs/README.md`](docs/README.md).

| Document | Contents |
|---|---|
| [`docs/api.md`](docs/api.md) | API protocol: error codes, jobs vs. pipeline, WebSocket, quality score, notifications |
| [`docs/api-endpoints.md`](docs/api-endpoints.md) | **Generated** endpoint inventory — do not edit by hand |
| [`docs/frontend.md`](docs/frontend.md) | Design system and brand, pages, navigation, search, risk map, known gaps |
| [`docs/deployment.md`](docs/deployment.md) | Compose, GPU, model weights, secrets, verification |
| [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | Operate it: boot, environment, health checks, failure matrix, backup/restore drill |
| [`docs/VERSIONING.md`](docs/VERSIONING.md) | SemVer policy, changelog rules, release script, what CI enforces |
| [`docs/LANGUAGE_STRATEGY.md`](docs/LANGUAGE_STRATEGY.md) | Measured Python/Rust boundary and the rule for moving it |

- **Swagger UI**: http://localhost:3456/docs
- **Configuration**: `.env` (see `.env.example`)

---

## Technology stack

**Frontend**: React 18.3, Vite 7.1, Deck.gl 9, Zustand 5, TanStack Query 5,
Tailwind CSS 3.4, Source Serif 4 / system sans / monospace type system

**Backend**: FastAPI 0.141, Celery 5.6, SQLAlchemy 2.0.52, Alembic 1.19,
Pydantic 2.13

**Storage**: TimescaleDB (PostgreSQL 15), Redis 7

**ML**: PyTorch 2.14, pandas 2.2, NumPy 2.5, scikit-learn 1.9

---

Built by the BEACON team. The name is earned one gated number at a time.
