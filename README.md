# BEACON Liquidity Risk Platform

**Banking Early Alert Comprehensive Observation Network (BEACON)** – a systemic liquidity risk monitoring platform powered by the Banking Network Engine (BNE).

Systemic liquidity-risk predictions from temporal graph models, with a 2D geographic risk map and a data-quality gate that fails closed.

---

## Quick Start

```bash
# Build and start all services
docker compose build
docker compose up -d

# Access the platform
open http://localhost:9876      # Frontend UI
open http://localhost:3456/docs # API Documentation
```

**View logs:**

```bash
docker compose logs -f backend
```

**Stop services:**

```bash
docker compose down
```

---

## Architecture

```
Frontend (React 18 + Vite + Deck.gl)
  └── 2D geographic risk map (heatmap, scatter, interbank arcs) - no GPU globe
  └── Pages: Dashboard, Risk Map, Models, Jobs, Results, Data Sources, Countries,
      Data Quality, Model Performance, Analytics, Settings, Help
  └── Nginx production server (port 9876)

Backend (FastAPI + Celery + Redis)
  └── 6-stage data pipeline (collection → validation → cleaning → formatting → analysis → certification)
  └── Data-quality gate: nothing is certified or predicted on without a verified attestation
  └── 15 data plugins: ECB, FRED, BIS, IMF, World Bank, Yahoo Finance, FDIC, FMP, SEC, AI4Risk, Kaggle, Alpha Vantage
  └── Temporal graph models with a frozen Toto 2.0 node encoder
  └── RESTful API (port 3456); job progress is refreshed by polling

Storage (TimescaleDB + Redis)
  └── TimescaleDB: PostgreSQL with hypertables, compression, and continuous
      aggregates for indicator observations, risk scores, and model metrics
  └── Redis: Celery broker and result backend

ML Stack (PyTorch)
  └── Toto 2.0 foundation-model node encoder (loaded from a local model folder)
  └── Temporal Attention Networks and continuous-time temporal graph memory
  └── Regime detection (Gaussian and Student-t HMM), Neural SDE latent dynamics,
      NOTEARS causal discovery with declared-structure validation
  └── Systemic risk: Basel III LCR/NSFR/leverage translation, coupled fire-sale
      equilibrium, crowded-trade overlap, persistence-vector topology
  └── Metrics: MSE, MAE, RMSE, R², directional accuracy
  └── Walk-forward backtesting with Sharpe, Sortino, Calmar, max drawdown, VaR/CVaR
  └── SHAP values, attention weights, feature importance
  └── CUDA + mixed precision training
```

---

## Data Governance

Risk scores are only as trustworthy as the data behind them, so the platform
refuses to guess:

- **No synthetic fallbacks.** If a dataset is missing or a provider fails, the
  plugin raises a typed error (`DatasetMissingError`, `DataSourceUnavailableError`,
  `SchemaValidationError`, `EmptyDatasetError`) with a stable error code. It never
  generates stand-in data.
- **Enforced quality gate.** Collected data is evaluated against an explicit
  `QualityPolicy` (row counts, required columns, missing-value ratio, freshness,
  minimum score) before it is certified. Failures raise `DataQualityError` and
  emit a data-quality notification.
- **Predictions are gated.** A prediction or backtest requires a data-quality
  attestation from the DATA stage and raises `PredictionBlockedError` without one.
- **Every failure is reported.** Ingestion failures are returned in the
  collection report as typed `CollectionFailure` entries carrying the plugin and
  a stable `error_code`, so a partial run is auditable rather than silent.

See [docs/EXECUTIVE_REVIEW_REMEDIATION.md](docs/EXECUTIVE_REVIEW_REMEDIATION.md)
for the mapping from review findings to code.

---

## Model Security

Model checkpoints are loaded with `torch.load(..., weights_only=True)` through
`backend/modules/engine/model_io.py`. Legacy checkpoints that are not
weights-only serialisable are rejected unless an operator explicitly sets
`BEACON_ALLOW_UNSAFE_CHECKPOINT_LOAD=1`, which is logged as a security event.
Training writes checkpoints through `safe_torch_save`, which verifies at save
time that the artifact will load under the restricted unpickler.

---

## Backtesting

Backtest jobs run a walk-forward evaluation (expanding or rolling windows with
an optional embargo) and report both ML and quantitative-finance metrics:

`sharpe_ratio`, `sortino_ratio`, `max_drawdown`, `calmar_ratio`,
`annualized_volatility`, `hit_rate`, `var_95`, `cvar_95`, plus per-fold results.

A rising predicted risk is treated as a negative return. Available via
`GET /api/v2/reports/backtest/{job_id}`.

---

## Database Migrations

Alembic is configured at the repository root:

```bash
export DATABASE_URL=postgresql://beacon_user:beacon_password@localhost:5432/beacon_db
alembic upgrade head        # apply migrations
alembic history             # show the revision chain
alembic revision --autogenerate -m "describe change"

# Render SQL for review without touching a database
alembic upgrade head --sql > migrations.sql
# Include the TimescaleDB hypertable/aggregate DDL (offline mode cannot probe
# for the extension, so it must be forced explicitly)
alembic -x timescaledb=1 upgrade head --sql > migrations_timescale.sql
```

The time-series tables are converted into TimescaleDB hypertables with
continuous aggregates by migration `timescale_001`. If TimescaleDB is not
available the migration creates plain tables and logs a warning; the
application keeps working and `TimeSeriesStore` falls back to base-table
aggregation. `configs/timescaledb/timescale_setup.sql` applies the same
partitioning/compression DDL manually for DBAs.

---

## CI/CD

| Workflow | Purpose |
|---|---|
| `.github/workflows/backend-ci.yml` | Compile + `pytest` with coverage on push/PR |
| `.github/workflows/frontend-ci.yml` | `npm run build` + Playwright e2e on push/PR |
| `.github/workflows/security.yml` | Advisory `pip-audit` and `npm audit`, plus a weekly run |

Dependabot keeps pip, npm, GitHub Actions, and Docker images current. See
[.github/workflows/README.md](.github/workflows/README.md) for local commands.

---

## API Usage

```bash
# Create a data collection job
curl -X POST http://localhost:3456/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type":"data_collection","parameters":{"regions":["PACIFIC"],"countries":["Japan"]}}'

# Check job status
curl http://localhost:3456/api/v1/jobs/{jobId}

# Reports
curl http://localhost:3456/api/v2/reports/brief/{jobId}
curl http://localhost:3456/api/v2/reports/detailed/{jobId}
```

---

## Prerequisites

- Docker 20.10+ and Docker Compose v2
- Optional: NVIDIA driver for GPU acceleration
- No local Python/Node installs required

---

## Technology Stack

**Frontend**: React 18.3, Vite 7.1, Deck.gl 9, Zustand 5, TanStack Query 5, Tailwind CSS 3.4

**Backend**: FastAPI 0.141, Celery 5.6, SQLAlchemy 2.0.52, Alembic 1.19, Pydantic 2.13

**Storage**: TimescaleDB (PostgreSQL 15), Redis 7

**ML**: PyTorch 2.14.0, pandas 2.2, NumPy 2.5, scikit-learn 1.9

---

## Documentation

Full index: [`docs/README.md`](docs/README.md).

| Document | Contents |
|---|---|
| [`docs/api.md`](docs/api.md) | API protocol: error codes, jobs vs. pipeline, WebSocket, quality score, notifications |
| [`docs/api-endpoints.md`](docs/api-endpoints.md) | **Generated** endpoint inventory — do not edit by hand |
| [`docs/frontend.md`](docs/frontend.md) | UI pages, navigation, search, onboarding, risk map, known gaps |
| [`docs/deployment.md`](docs/deployment.md) | Deploying on this host: Compose, GPU, model weights, secrets |
| [`docs/data_connectors.md`](docs/data_connectors.md) | NBFI/CCP ingestion feeds and their publication clocks |
| [`docs/G_SIB_BUILD.md`](docs/G_SIB_BUILD.md) | G-SIB-grade build: added, verified, and still missing |
| [`docs/EXECUTIVE_REVIEW_REMEDIATION.md`](docs/EXECUTIVE_REVIEW_REMEDIATION.md) | Review findings mapped to code |
| [`.github/workflows/README.md`](.github/workflows/README.md) | CI/CD workflows and local equivalents |

- **Swagger UI**: http://localhost:3456/docs
- **Configuration**: edit `.env` (see `.env.example`) for API keys and database credentials

---

Built with ❤️ by the BEACON team
