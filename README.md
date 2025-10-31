# BEACON Liquidity Risk Platform

**Banking Early Alert Comprehensive Observation Network (BEACON)** – A production-ready systemic liquidity risk monitoring platform powered by the Banking Network Engine (BNE).

The platform combines advanced machine learning with multi-source financial data analysis to provide real-time liquidity risk predictions for regulators, central banks, and financial institutions. The modern React 19 UI features an interactive 3D globe for intuitive region and country selection, backed by production-grade ML models and comprehensive data orchestration.

---

## Highlights

- **Globe-first workflow** – select regions or countries on a refined react-three-fiber globe (steady camera, precise overlays).
- **Production-ready ML** – Heterogeneous Graph Transformers (HGT), Temporal Attention Networks, and multi-scale training with real PyTorch metrics (MSE, MAE, RMSE, R²).
- **Comprehensive data sources** – 50+ financial indicators from 15+ integrated plugins (ECB, FRED, BIS, IMF, World Bank, Yahoo Finance, FDIC, FMP, SEC, and more).
- **EU AI Act compliant** – Built-in explainability with SHAP values, attention weights, feature importance, and uncertainty quantification.
- **Scope propagation** – confirmed region/country filters from data jobs persist through training, prediction, and backtest workflows with full v2 reporting.
- **Docker-only validation** – automated integration tests with real data jobs; Playwright E2E tests for frontend globe interactions.
- **No mocks** – every UI panel (datasources, catalogue, data pipeline, training, prediction, backtest) talks to live API endpoints.
- **Enterprise branding** – Tailwind-driven minimal layout, corporate gradients/starfield, panel animations, and conservative typography.

---

## Architecture Overview

```
Frontend (React 19 + Vite + Three.js + Zustand + React Query)
  ├── GlobeCanvas (react-three-fiber, refined OrbitControls, earcut triangulation)
  ├── RegionDataPanel (Datasources → Catalogue → Data Download → Training)
  ├── ModelLibrary / Prediction / Backtest panels
  ├── PredictionPanel (forecast generation + visualization)
  └── API layer hitting /api/v1 (jobs) and /api/v2 (reports, predictions)

Backend (FastAPI + Celery + Postgres + Redis + PyTorch)
  ├── DATA Module: 6-stage pipeline (collection, validation, cleaning, formatting, analysis, certification)
  ├── ENGINE Module: HGT models, multi-scale trainer, prediction engine with explainability
  ├── RESULTS Module: brief/detailed/prediction/backtest reports with scope metadata
  ├── 15+ Data Plugins: ECB, FRED, BIS, IMF, World Bank, Yahoo Finance, FDIC, FMP, SEC, etc.
  ├── API Routes:
  │   ├── /api/v1/jobs, /pipeline, /catalogue, /data-sources, /assets, /config, /models
  │   └── /api/v2/datasources, /datacatalog, /reports/*, /predictions/*
  ├── Celery tasks: run_data_collection, run_training, run_prediction, run_backtest
  ├── Country matching utilities (pycountry + ISO 3166-1) for filtering
  └── Comprehensive error logging with technical + user-friendly messages

ML Stack (Production-Ready)
  ├── PyTorch 2.5.1 + PyTorch Geometric 2.6.1
  ├── Heterogeneous Graph Transformer (HGT) – primary model
  ├── Temporal Attention Networks – time-series focused
  ├── Multi-scale training for heterogeneous data sources
  ├── Real-time metrics: MSE, MAE, RMSE, R², directional accuracy
  ├── Explainability: SHAP values, attention weights, feature importance
  └── GPU acceleration (CUDA) + mixed precision training (FP16)
```

Persistent artefacts (jobs, parquet outputs, trained models, predictions) are mounted into `./data`, `./models`, `./results`, `./logs`. These directories are not meant to be committed.

---

## Prerequisites

- Docker 20.10+ and Docker Compose v2
- Optional: NVIDIA driver for GPU acceleration (docker-compose-gpu.yml)
- No local Python/Node installs required; all commands run in containers.

---

## Key Features

### Data Collection
- **50+ Financial Indicators** across exchange rates, interest rates, banking stats, stocks, bonds, commodities, and economic indicators
- **15+ Integrated Plugins**: ECB, ECB Banking, FRED, BIS, IMF, World Bank, Yahoo Finance, FDIC, FMP, SEC EDGAR, and custom CSV/API support
- **Geographic Scope**: Global, regional (North America, Europe, Asia, Pacific, Latin America, Africa), and country-level (ISO 3166-1)
- **Quality Scoring**: 0-100 automated quality metrics (completeness, consistency, timeliness, accuracy)
- **6-Stage Pipeline**: Collection → Validation → Cleaning → Formatting → Analysis → Certification

### Machine Learning
- **Heterogeneous Graph Transformers (HGT)**: Multi-source temporal encoders with attention-based graph convolutions
- **Multi-Scale Training**: Handles heterogeneous data sources with varying frequencies and granularities
- **Real Metrics**: MSE, MAE, RMSE, R², directional accuracy (no placeholder code)
- **Early Stopping**: Automatic patience-based stopping with learning rate scheduling
- **GPU Support**: CUDA acceleration with mixed precision training (FP16)

### Explainability & Compliance
- **EU AI Act Compliant**: Comprehensive compliance documentation (EU_AI_ACT_COMPLIANCE.md)
- **SHAP Values**: Feature importance analysis for individual predictions
- **Attention Weights**: Visualization of model attention mechanisms
- **Uncertainty Quantification**: Monte Carlo Dropout for confidence intervals
- **Human-Readable Explanations**: Technical + user-friendly error messages throughout

### Testing & Quality
- **Backend Integration Tests**: Pytest with SQLite for API smoke tests, Docker-based country scope tests
- **Frontend E2E Tests**: Playwright tests for globe interactions
- **Real-Time Progress Tracking**: Celery task callbacks with 0-100% progress monitoring
- **Comprehensive Logging**: ErrorLogger service with stack traces and context

---

## Quick Start (Docker)

```bash
# 1. Build backend & frontend containers
docker compose build backend celery-worker frontend

# 2. Start the core services (Postgres, Redis, API, Celery, Frontend)
docker compose up -d postgres redis backend celery-worker frontend

# 3. Open the UI
# http://localhost:5173
```

Useful helper commands:

```bash
# View API docs
open http://localhost:3456/docs

# Tail backend logs
docker compose logs -f backend

# Stop and clean
docker compose down
```

---

## Frontend Workflow

1. **Select regions/countries on the globe**  
   Orbit/pinch now respect manual placement (no auto-snap) and overlays remain aligned while zooming.
2. **Datasources → Catalogue → Data Download**  
   After a data job completes the confirmed geographic scope is cached in the store and displayed in the panels.
3. **Training**  
   Shows server-provided defaults; the scope summary reflects the data job, not transient UI selections.
4. **Model Library → Prediction / Backtest**  
   When launching jobs the confirmed scope is sent alongside the model ID so backend analytics stay aligned.  
   Once reports finish the new `/api/v2/predictions` and `/api/v2/reports/backtest` responses include the same filters.

All panels rely on React Query for fetching/polling and Zustand for workflow state.

---

## Backend Changes of Note

- **Scope propagation** – `run_data_collection` stores `regions`/`countries`; downstream Celery tasks for training & prediction copy them into job results.  
- **Prediction/Backtest reports** – v2 endpoints now expose the scope metadata so the frontend can display it post-run.  
- **Country matcher** – `backend/modules/data/country_utils.py` normalises UI tokens (supports ISO aliases & currency symbols) and filters catalogue items accordingly.  
- **Orbit-friendly datasets** – overlays use higher-density meshes and polygon offsets to remove z-fighting.  
- **Integration test** – `backend/tests/test_country_scope.py` documents a full Japan-only flow; it’s automatically skipped when the docker CLI isn’t available in-container.

---

## Optional: Country Scope Regression (Docker-only)

```bash
docker compose up -d postgres redis backend celery-worker

# Runs a PACIFIC/Japan data job and asserts the brief report mirrors the scope.
RUN_DOCKER_SCOPE_TESTS=1 docker compose run --rm backend pytest tests/test_country_scope.py

docker compose down
```

> Note: the test shells out to `docker`—it will skip automatically if the CLI is unavailable (e.g. inside locked-down environments).

---

## Day-to-day Commands

```bash
# Trigger a data job (regions/countries come from globe selection)
curl -X POST http://localhost:3456/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type":"data_collection","parameters":{"regions":["PACIFIC"],"countries":["Japan"]}}'

# Poll job status
curl http://localhost:3456/api/v1/jobs/{jobId}

# Fetch new v2 reports
curl http://localhost:3456/api/v2/reports/brief/{jobId}
curl http://localhost:3456/api/v2/reports/detailed/{jobId}
curl http://localhost:3456/api/v2/predictions/{predictionJobId}
curl http://localhost:3456/api/v2/reports/backtest/{backtestJobId}
```

---

## Repository Tips

- The tree contains large generated folders (`data/`, `results/`, `logs/`). Keep them out of commits.  
- When rebuilding containers after backend changes run `docker compose build backend celery-worker`.  
- The frontend is served from Vite in the container (`http://localhost:5173`). To develop locally, use `docker compose run --rm frontend npm run dev` to ensure dependencies stay sandboxed.

---

## Documentation

- **EU_AI_ACT_COMPLIANCE.md** – Comprehensive EU AI Act compliance documentation
- **PLATFORM_SUPPORT.md** – Multi-platform deployment guide (macOS, Linux, GPU/CPU)
- **ROADMAP.md** – Detailed three-module architecture (DATA-ENGINE-RESULTS)
- **API Documentation** – Interactive Swagger UI at http://localhost:3456/docs

---

## Remaining Backlog

- Globe visuals: adopt brand-consistent sky gradient, subtle bloom and corporate starfield
- Enhance automation: add CI job invoking the Docker scope regression when the CLI is available
- Expand prediction/backtest UI to display scope from the new report metadata once jobs succeed
- Enrich training data in demo datasets so end-to-end sample runs succeed without manual tweaks
- Add SHAP visualizations to frontend prediction panel

---

## Technology Stack

**Frontend**: React 19.1.1, Vite 7.1.7, Three.js 0.170.0, @react-three/fiber 9.0.0, Zustand 5.0.0, TanStack React Query 5.62.7, Tailwind CSS 3.4.17, Framer Motion 11.18.1

**Backend**: FastAPI 0.109.0, Celery 5.3.6, SQLAlchemy 2.0.25, Pydantic 2.5.3, Uvicorn with uvloop

**ML/Data**: PyTorch 2.5.1, PyTorch Geometric 2.6.1, pandas 2.2.3, NumPy 1.26.4, scikit-learn 1.5.2, matplotlib 3.9.2, plotly 5.24.1

**Infrastructure**: PostgreSQL 15-alpine, Redis 7-alpine, Docker 20.10+, NVIDIA CUDA 12.6.0 (optional)

---

Built with ❤️ by the BEACON team – feedback and pull requests welcome.
