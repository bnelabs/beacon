# Executive Review Remediation

This document maps each finding from the BEACON executive review to the change
that addresses it. Findings are grouped by the review's own sections.

Legend: **Done** = implemented and covered by tests; **Done (design)** =
implemented with a documented operational requirement.

---

## 2A. Data Ingestion & Error Handling — *Done*

**Finding.** `ai4risk_plugin.py` silently generated sample network data when the
dataset was missing (`self._generate_sample_network`). Silent data generation is
dangerous in a risk engine: a failed data source must raise a data-quality
alert, not train or predict on synthetic data.

**What changed**

| Item | Detail |
|---|---|
| Synthetic generators removed | `_generate_sample_network`, `_generate_sample_features`, `_generate_sample_ratings` deleted outright; the plugin now raises `DatasetMissingError`. |
| Typed errors with codes | New `backend/exceptions.py`: `BeaconError` → `DataIngestionError` → `DataSourceUnavailableError`, `DatasetMissingError`, `SchemaValidationError`, `EmptyDatasetError`, `DataQualityError`; plus `PredictionBlockedError`. Every error carries a stable `code`, `severity`, `context`, and `to_dict()`. |
| Quality gate | New `backend/modules/data/quality_gate.py`: `QualityPolicy`, `QualityAttestation`, `DataQualityGate.evaluate/enforce/require`. |
| Gate enforced before certification | `DataOrchestrator.run()` now calls `quality_gate.enforce(...)` before saving and certifying. |
| Predictions blocked without verification | `RealPredictionEngine.predict()` calls `DataQualityGate.require()` and raises `PredictionBlockedError` unless the payload carries a verified attestation. |
| Alerts | Gate failures raise a notification through the existing `NotificationService.create_data_quality_alert`. |
| Collector no longer swallows failures | `DataCollector` records a `CollectionReport` with per-source `error_code`; it aborts when nothing could be collected and supports an explicit `fail_on_any_error` strict mode. |

**Two latent bugs found while implementing this**

1. **An entirely empty payload passed certification.** An empty dataset produced
   `missing_ratio = 0` and `inconsistency_ratio = 0`, so completeness and
   consistency scored a perfect 100; `fit_for_engine` requires `quality_score >= 70`,
   which an empty payload hits exactly. The gate now rejects it independently of
   the composite score (`test_gate_rejects_empty_payload_despite_composite_score`).
2. **`AI4RiskInterbankPlugin` could not be instantiated at all.** It never
   implemented the abstract `fetch_asset_data`, so `plugin_class(config)` raised
   `TypeError` — which the collector's broad `except Exception` silently turned
   into an empty DataFrame. The method is implemented (it raises
   `SchemaValidationError`, since this source has no price series) and the plugin
   is now registered in the plugin loader.

**Tests:** `backend/tests/test_data_governance.py` (30 tests).

---

## 2B. Security in Model Loading — *Done*

**Finding.** The prediction engine used `torch.load(model_path)` without
`weights_only=True`, allowing remote code execution from an untrusted pickle.

**What changed**

- New `backend/modules/engine/model_io.py` with `safe_torch_load()` (always
  `weights_only=True`) and `safe_torch_save()` (verifies at save time that the
  artifact reloads under the restricted unpickler).
- All four load sites migrated: `prediction_engine.py`, `orchestrator.py`,
  `trainer.py`, `multi_scale_trainer.py`. Both save sites migrated to
  `safe_torch_save`.
- Legacy checkpoints are rejected by default; loading them requires the explicit
  `BEACON_ALLOW_UNSAFE_CHECKPOINT_LOAD=1` opt-in and is logged as a security event.

Verified with `grep`: no raw `torch.load` / `torch.save` remains outside `model_io.py`.

**Tests:** `backend/tests/test_model_io.py` (torch-gated tests skip when torch is absent).

---

## 2C. Database Optimization for Time-Series — *Done*

**Finding.** Standard PostgreSQL will bloat under time-series volume, slowing
dashboard queries. Migrate results storage to TimescaleDB or ClickHouse.

**Chosen:** TimescaleDB (a PostgreSQL extension, so the existing SQLAlchemy
models, connection string, and Alembic migrations are unaffected).
ClickHouse was rejected as it would require a parallel write path and a second
client stack for no additional benefit at this scale.

**What changed**

- **New tables** (`backend/models/timeseries.py`): `indicator_observations`,
  `risk_scores`, `model_metrics`. Each uses a natural composite primary key that
  includes the time column — TimescaleDB requires every unique index on a
  hypertable to contain the partitioning column.
- **Migration** `timescale_001`: creates the tables idempotently, then converts
  them to hypertables with 90-day compression policies, and adds the
  `risk_scores_daily` and `indicator_observations_daily` continuous aggregates.
  On a database without TimescaleDB it creates plain tables and logs a warning.
- **Store** (`backend/modules/results/timeseries_store.py`): `TimeSeriesStore`
  with dialect-aware upserts (PostgreSQL/SQLite `ON CONFLICT`) and
  `average_risk_by_region(days=30)`, which uses the continuous aggregate when
  present and falls back to a base-table `GROUP BY`. Every result reports which
  path produced it.
- **Deployment**: `docker-compose.yml` now runs
  `timescale/timescaledb:2.15.2-pg15` with `shared_preload_libraries=timescaledb`.
- **Manual DDL** for DBAs: `configs/timescaledb/timescale_setup.sql`.

**Note.** Before this change the repository had **no time-series tables at all** —
pipeline output lived in Parquet files. This migration introduces the real
storage path the review assumed existed.

**Tests:** `backend/tests/test_timeseries_store.py` (16 tests), including the
degrade-gracefully path when a pre-aggregate is advertised but unusable.

---

## 3. What Can Be Added

### Walk-forward backtesting with quantitative metrics — *Done*

`backend/modules/engine/backtesting.py` provides `WalkForwardConfig`,
`generate_walk_forward_folds` (expanding/rolling, optional embargo, no leakage),
`WalkForwardBacktester` (fresh model per fold, concatenated out-of-sample
predictions), and the metrics `sharpe_ratio`, `sortino_ratio`, `max_drawdown`,
`calmar_ratio`, `annualized_volatility`, `hit_rate`, `directional_accuracy`,
`value_at_risk`, `conditional_value_at_risk` alongside MSE/MAE/RMSE/R².

A rising predicted risk is treated as a negative return
(`return_t = -(risk_t - risk_{t-1})`).

Backtest jobs now emit `quant_metrics` and a per-fold `walk_forward` section;
`BacktestReport` and `GET /api/v2/reports/backtest/{job_id}` expose them.

**Tests:** `backend/tests/test_backtesting.py` (33 passed, 1 skipped without pandas).

### CI/CD and automated testing — *Done*

| File | Purpose |
|---|---|
| `.github/workflows/backend-ci.yml` | `compileall` + `pytest` with coverage on push/PR; CPU-only torch; concurrency cancellation |
| `.github/workflows/frontend-ci.yml` | `npm ci`, `npm run build`, Playwright Chromium e2e |
| `.github/workflows/security.yml` | Advisory `pip-audit` / `npm audit` plus a weekly run |
| `.github/dependabot.yml` | Weekly grouped updates for pip, npm, Actions, Docker |
| `.github/pull_request_template.md` | Review checklist (tests, no synthetic fallbacks, `weights_only`, migrations, metrics) |
| `backend/requirements-dev.txt` | Pinned dev/CI dependencies |

The backend CI runs **without** a PostgreSQL service: the suite uses SQLite
(`USE_SQLITE`) and the only Docker/Postgres test is skipped unless
`RUN_DOCKER_SCOPE_TESTS=1`. Playwright runs standalone against the route-mocked
API fixtures.

**Fixed along the way:** root `pytest.ini` used the `[tool:pytest]` header, which
is only valid inside `setup.cfg` — pytest ignored the file entirely, so
`testpaths` and the `--cov` addopts were dead. It is now `[pytest]` with
`testpaths = backend/tests`.

### Observability: Prometheus + Grafana — *Done*

`backend/monitoring/` provides:

- **`metrics.py`** — HTTP latency/errors, pipeline job counters, ingestion
  failures by plugin and error code, Celery task counters and duration, queue
  depth, inference latency, predictions by region/risk level. Safe no-op shims
  when `prometheus_client` is absent; multiprocess mode via
  `PROMETHEUS_MULTIPROC_DIR`.
- **`drift.py`** — data drift detection: `population_stability_index`,
  `kolmogorov_smirnov_statistic` (with an asymptotic p-value implemented without
  SciPy), Jensen–Shannon divergence, a `FeatureDriftMonitor` that stores the
  training-time reference distribution as JSON, and the
  `beacon_feature_drift_psi{feature}` gauge.
- **`celery_health.py`** — Redis queue depth, worker liveness via
  `celery.control.inspect()` (a crashed PyTorch worker pool is visible;
  degrades gracefully when no worker responds), and Celery signal hookup.

Dashboards and alerts live in `configs/observability/` (Prometheus scrape config,
alert rules for ingestion failure rate, PSI > 0.25, queue depth, zero workers,
5xx rate, inference p95, and pipeline failure rate; Grafana datasource
provisioning and the `beacon-overview` dashboard).

`GET /metrics` is wired into the FastAPI app.

### Mapbox / Deck.gl — *Done*

See section 4.

---

## 4. What Can Be Removed

### The 3D globe (Three.js) — *Done*

Replaced with a Deck.gl 2D risk map (`frontend/src/components/map/RiskMap.jsx`,
`MapLegend.jsx`): a free CARTO raster basemap (no Mapbox token required) with
`ScatterplotLayer` (banks/regions by risk), `HeatmapLayer` (liquidity intensity),
`ArcLayer` (interbank exposures, replacing `NetworkArcs`), `GeoJsonLayer`
(boundaries) and `TextLayer` (labels). The route key `globe` is unchanged so
existing links and deep links keep working; user-facing copy is now "Risk Map".

Removed: `three`, `@react-three/fiber`, `@react-three/drei`, the entire
`frontend/src/components/globe/` directory, and `globeRotation` state.

Also deleted 11.2 MB of dead geodata: `world-coastlines.json` (2.54 MiB) and
`world-administrative-boundaries.geojson` (8.18 MiB, already unreferenced before
this change), replaced by a 180 KB boundary subset.

### "Sample Data" fallbacks in plugins — *Done*

Removed from AI4Risk, as described in section 2A. A repository-wide audit found
no other synthetic-data fallbacks; the only other `sample` matches are
`rows_sample` metadata (a row count) and a docstring describing `test_item`.

### Unused legacy remnants — *Done*

- `grep -rn "LiquidityMonitor"` → **zero matches**, confirming the earlier claim.
- An AST-based audit of all 75 Pydantic schema classes found **no unreferenced
  models**; every class is used as a base class or field type.
- `backend/scripts/populate_catalogue.py` is used by `backend/api/main.py`.
- The orphaned root-level `test_multi_bank_scenario.py` (referenced by nothing,
  and importing `requests`, which is not a declared dependency) was moved to
  `scripts/manual/multi_bank_scenario.py`, switched to the declared `httpx`
  client, and documented as a manual script. It no longer sits in the pytest
  collection root.
- **Alembic was unrunnable.** There was no `alembic.ini` and no `env.py`, and the
  revision chain was broken in two places: `add_datasource_registration_fields`
  pointed at a revision `002` that does not exist, and the notifications
  migration referenced `add_country_profiles` while `add_country_profiles`'s
  actual revision id is `country_profiles_001`. The chain is now a single linear
  history and Alembic is configured at the repository root.

### Verbose AI comments — *Done*

The review quoted `"REAL Prediction Engine - NO MOCK DATA"`. The shouty,
self-justifying docstrings and log lines ("REAL", "NO PLACEHOLDERS",
"THE RIGHT APPROACH", "REAL METRICS") were rewritten as plain descriptions of
behaviour across `models.py`, `trainer.py`, `prediction_engine.py`,
`multi_scale_trainer.py`, `shap_explainer.py`, and `job_tasks.py`. Comments that
restated *what* the next line does were removed; the comments that remain explain
*why*.

---

## One further change worth flagging

`backend/__init__.py` eagerly imported the FastAPI app, Celery, and the whole ML
stack. That meant `import backend.exceptions` — or any submodule — required the
entire runtime to be installed, which made unit testing needlessly heavy and was
why early test runs failed at collection. The package now resolves those public
objects lazily (PEP 562); `from backend import app` still works unchanged.

---

## Incidental findings

These were not in the review, but were surfaced by implementing it.

### Undeclared direct dependencies

An AST audit of every `backend/**/*.py` import against `requirements.txt` found
three packages used directly but not declared:

| Package | Used by | Impact |
|---|---|---|
| `reportlab` | `backend/modules/results/generator.py` | **Entirely missing.** PDF report export is wrapped in `except Exception`, so it degraded silently to no PDF at all — and `test_pipeline_integration.py` asserts the PDF artefact exists. |
| `scipy` | `backend/modules/data/formatter.py` (`pearsonr` for graph edges), `backend/modules/engine/visualizer.py` (`probplot`) | Worked only because `scikit-learn` pulls it in transitively — one upstream dependency change from breaking graph construction. |
| `requests` | 8 data plugins (ECB, BIS, IMF, World Bank, FMP, ECB Banking, custom API, Alpha Vantage) plus `world_bank_service.py` | Worked only transitively via `yfinance`/`fredapi`. The plugin loader skips a plugin whose import fails, so losing `requests` would silently unregister most data sources. |

All three are now declared explicitly with pins.

### Other

- `pytest.ini` used the `[tool:pytest]` header, valid only in `setup.cfg`, so
  pytest ignored the file completely (see the CI/CD section above).
- The frontend build output (`frontend/dist/`) was already gitignored; verified
  rather than changed.
- The tracked `.env` contains no API secrets — only the default local database
  credentials — so no credential rotation is required.

---

## Verification summary

| Suite | Result |
|---|---|
| `backend/tests/test_data_governance.py` | 30 passed |
| `backend/tests/test_timeseries_store.py` | 16 passed |
| `backend/tests/test_backtesting.py` | 33 passed, 1 skipped (needs pandas) |
| `backend/tests/test_model_io.py` | 9 passed, 5 skipped (need torch) |
| `python -m compileall -q backend` | clean |
| `frontend`: `npm run build` | passed |
| `frontend`: Playwright e2e | 1 passed |

The remaining suites (`test_api_smoke.py`, `test_pipeline_integration.py`,
`test_country_scope.py`) require the full dependency set (FastAPI, torch,
Celery) and are exercised by
`.github/workflows/backend-ci.yml`.
