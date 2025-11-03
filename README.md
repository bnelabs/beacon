# BEACON Liquidity Risk Platform

**Banking Early Alert Comprehensive Observation Network (BEACON)** – A production-ready systemic liquidity risk monitoring platform powered by the Banking Network Engine (BNE).

The platform combines advanced machine learning with multi-source financial data analysis to provide real-time liquidity risk predictions for regulators, central banks, and financial institutions. The modern React 19 UI features an interactive 3D globe for intuitive region and country selection, backed by production-grade ML models and comprehensive data orchestration.

---

## Highlights

- **Ultra-lightweight Frontend** – Production-ready React 19 app with **77.5MB Docker image**, zero Playwright dependencies, ~323KB gzipped bundle, and <20s production builds.
- **Globe-first workflow** – select regions or countries on a refined react-three-fiber globe (steady camera, precise overlays).
- **Production-ready ML** – Heterogeneous Graph Transformers (HGT), Temporal Attention Networks, and multi-scale training with real PyTorch metrics (MSE, MAE, RMSE, R²).
- **Comprehensive data sources** – 50+ financial indicators from 15+ integrated plugins (ECB, FRED, BIS, IMF, World Bank, Yahoo Finance, FDIC, FMP, SEC, and more).
- **EU AI Act compliant** – Built-in explainability with SHAP values, attention weights, feature importance, and uncertainty quantification.
- **Scope propagation** – confirmed region/country filters from data jobs persist through training, prediction, and backtest workflows with full reporting.
- **Docker-only validation** – automated integration tests with real data jobs and comprehensive API coverage.
- **No mocks** – every UI panel (datasources, catalogue, data pipeline, training, prediction, backtest) talks to live API endpoints.
- **Enterprise branding** – Tailwind-driven minimal layout, corporate gradients, panel animations, and conservative typography.

---

## Architecture Overview

```
Frontend (Production - 77.5MB Docker image)
  ├── React 19 + Vite 7 + Three.js + Zustand + TanStack Query
  ├── 6 Pages: Dashboard, Globe View, Models, Jobs, Results, Data Sources
  ├── GlobeCanvas (react-three-fiber, OrbitControls, 14 banking regions)
  ├── State-based routing (Zustand router, no react-router)
  ├── 20+ UI components (Button, Card, Badge, LoadingSpinner, etc.)
  ├── API hooks (useJobs, useModels, useDataSources, etc.)
  └── Nginx production server (gzip, caching, API proxy on port 3001)

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
# 1. Build all services
docker compose build

# 2. Start the platform (Postgres, Redis, API, Celery, Frontend)
docker compose up -d

# 3. Open the UI
open http://localhost:3001

# 4. View API docs
open http://localhost:3456/docs
```

**Useful Commands:**

```bash
# Tail backend logs
docker compose logs -f backend

# Rebuild after code changes
docker compose build backend celery-worker frontend

# Stop all services
docker compose down

# View all running services
docker compose ps
```

---

## Frontend Architecture

**Production-ready lightweight frontend** with exceptional performance:

### Performance Metrics
- **Docker Image**: 77.5MB (ultra-lightweight Alpine-based build)
- **Bundle Size**: ~323KB gzipped (optimized production bundle)
- **Build Time**: ~19 seconds (production build)
- **Dependencies**: 14 packages (minimal, carefully selected)
- **Zero Playwright**: No heavyweight E2E dependencies

### Bundle Breakdown
```
three-vendor.js:  998.9KB → ~283KB gzip (3D globe components)
index.js:         76.8KB  → ~19KB gzip  (application logic)
query-vendor.js:  38.2KB  → ~12KB gzip  (TanStack Query)
react-vendor.js:  11.5KB  → ~4KB gzip   (React 19)
index.css:        16.6KB  → ~5KB gzip   (Tailwind CSS)
───────────────────────────────────────────────────
Total:            1.14MB  → ~323KB gzip
```

### Complete Feature Set (6 Pages)
1. **Dashboard** – System overview with stats, recent jobs, quick actions
2. **Globe View** – Interactive 3D globe with 14 banking regions
3. **Models** – Model library with training status and configuration
4. **Jobs** – Real-time job monitoring with progress tracking
5. **Results** – Performance metrics, predictions, feature importance
6. **Data Sources** – Plugin management (FDIC, ECB, FMP, etc.)

### Technology Stack
- **React 19.1.1** – Latest concurrent features
- **Vite 7.1.7** – Lightning-fast builds with esbuild
- **Three.js 0.170.0** + **@react-three/fiber 8.17.10** – 3D globe
- **Zustand 5.0.0** – Minimal state management (0.9KB)
- **TanStack Query 5.62.7** – Smart server state caching
- **Tailwind CSS 3.4.17** – Utility-first styling
- **Nginx 1.27-alpine** – Production server with gzip & caching

### Architecture Highlights
- **Multi-stage Docker build** – Optimized 3-stage Alpine build (deps → builder → production)
- **State-based routing** – Lightweight Zustand router (no react-router overhead)
- **Component library** – 20+ reusable UI components (Button, Card, Badge, etc.)
- **API integration** – React Query hooks for all backend endpoints
- **Real-time updates** – Polling and caching with smart invalidation

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

**Frontend**: React 19.1.1, Vite 7.1.7, Three.js 0.170.0, @react-three/fiber 8.17.10, Zustand 5.0.0, TanStack React Query 5.62.7, Tailwind CSS 3.4.17, Nginx 1.27-alpine

**Backend**: FastAPI 0.109.0, Celery 5.3.6, SQLAlchemy 2.0.25, Pydantic 2.5.3, Uvicorn with uvloop

**ML/Data**: PyTorch 2.5.1, PyTorch Geometric 2.6.1, pandas 2.2.3, NumPy 1.26.4, scikit-learn 1.5.2, matplotlib 3.9.2, plotly 5.24.1

**Infrastructure**: PostgreSQL 15-alpine, Redis 7-alpine, Docker 20.10+, NVIDIA CUDA 12.6.0 (optional)

---

Built with ❤️ by the BEACON team – feedback and pull requests welcome.
