# Beacon Frontend/Backend Cleanup TODO

- [x] `frontend-v2/src/components/GlobeCanvas.jsx:158` – Import the `earcut` triangulation helper so polygon meshes don’t throw `ReferenceError: earcut is not defined`.
- [x] `backend/api/main.py:50` – Point the catalogue seeding import at `backend.scripts.populate_catalogue` to avoid `ModuleNotFoundError` on startup.
- [x] `frontend-v2/src/config/regions.js` – Remove unused placeholder metrics/narratives so UI data stays API-driven.
- [x] `backend/services/job_service.py:74` – Swap the stale `error_translator` import for the new `enhanced_error_translator.translate_error_enhanced`.
- [x] `backend/tasks/job_tasks.py:145` – Derive default `start_date`/`end_date` from the current date instead of using the frozen 2019–2024 window.
- [x] `frontend/src/components/Globe/DataSourceSelector.tsx:63` – Use the shared API client / `VITE_API_BASE_URL` instead of hard-coding `http://localhost:3456`.
- [x] `backend/api/routes/catalogue.py:73` – Implement the pending country-filter logic rather than leaving the `TODO` stub.
- [x] `scripts/start.sh:271` – Query `/api/v1/catalogue/summary` (or expose `/stats`) so the boot check works.
- [x] `backend/plugins/alphavantage_plugin.py` – Reconcile this deprecated plugin with the current registry (remove or port to `DataSourcePlugin`).
- [x] `backend/plugins/fmp_plugin.py:38` – Require a real API key (no default `'demo'`) and validate configuration before use.

## New TODO

- [x] `modules/engine/multi_scale_trainer.py` – handle short windows so single-series jobs don’t fail with “Training dataset is empty”.
- [x] `backend/scripts/populate_catalogue.py` / data orchestration – persist country coverage metadata (`parameters.country_codes`) so `/api/v1/catalogue?countries=` returns results.
- [x] `frontend-v2/eslint.config.js` & related components – configure React lint rules properly and resolve the reported hook-usage / unused import problems.
- [x] `.gitignore` – add `data/` so job artifacts from Docker runs never pollute git status.
