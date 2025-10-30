# BEACON Liquidity Risk Platform

Modernised frontend + backend APIs for the Bank Network Engine (BNE) liquidity platform.  
The legacy UI has been replaced with a React (Vite) experience centred on an interactive 3D globe.  
All data flows continue to rely on existing ingestion, QC, training and inference stacks.

---

## Highlights

- **Globe-first workflow** – select regions or countries on a refined react-three-fiber globe (steady camera, precise overlays).  
- **Scope propagation** – the confirmed region/country filters from the data job are persisted through training, prediction and backtest payloads as well as v2 reporting endpoints.  
- **Docker-only validation** – optional integration test spins the stack, runs a real data job (e.g. PACIFIC/Japan) and asserts the brief report mirrors the requested scope.  
- **No mocks** – every UI panel (datasources, catalogue, data pipeline, training, prediction, backtest) talks to live API endpoints.  
- **Enterprise branding** – Tailwind-driven minimal layout, corporate gradients/starfield, panel animations, and conservative typography.

---

## Architecture Overview

```
Frontend (React 18 + Vite + Zustand + React Query)
  ├── GlobeCanvas (react-three-fiber, refined OrbitControls)
  ├── RegionDataPanel (Datasources → Catalogue → Data Download → Training)
  ├── ModelLibrary / Prediction / Backtest panels
  └── API layer hitting /api/v1 (jobs) and new /api/v2 routes at runtime

Backend (FastAPI + Celery + Postgres + Redis)
  ├── /api/v2/datasources, /datacatalog, /reports/brief, /reports/detailed
  ├── /api/v2/predictions/{jobId}, /api/v2/reports/backtest/{jobId}
  ├── Celery tasks for data_collection, training, prediction, backtest
  ├── Data orchestrator + collector now aware of country filters
  └── Country matching utilities (pycountry) mapping UI selections to catalogue items
```

Persistent artefacts (jobs, parquet outputs, predictions) are mounted into `./data`, `./results`, etc. These directories are not meant to be committed.

---

## Prerequisites

- Docker 20.10+ and Docker Compose v2  
- Optional: NVIDIA driver for GPU acceleration (-gpu compose file)  
- No local Python/Node installs required; all commands run in containers.

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

## Remaining Backlog

- Globe visuals: adopt brand-consistent sky gradient, subtle bloom and corporate starfield.  
- Enhance automation: add CI job invoking the Docker scope regression when the CLI is available.  
- Expand prediction/backtest UI to display scope from the new report metadata once jobs succeed.  
- Enrich training data in demo datasets so end-to-end sample runs succeed without manual tweaks.

---

Built with ❤️ by the BEACON team – feedback and pull requests welcome.
