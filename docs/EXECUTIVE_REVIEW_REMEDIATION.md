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

**Tests:** `backend/tests/test_data_governance.py` (45 tests).

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

**Tests:** `backend/tests/test_backtesting.py` (50 passed). See the second-round
section for the fold-boundary invariant tests and the baseline comparison.

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

### Observability: Prometheus + Grafana — *Removed*

> **Superseded, not current.** This workstream was built and then **removed from
> the project on operator instruction**. `backend/monitoring/`,
> `configs/observability/`, the `prometheus` / `grafana` / `celery-exporter`
> compose services, the `GET /metrics` route, the `prometheus-client`
> dependency and `backend/tests/test_observability.py` no longer exist. What
> follows is a record of what was built and why, not a description of the tree.
>
> Worth knowing before restoring any of it: `drift.py` and `celery_health.py`
> hard-imported the metrics module, so removing the Prometheus instrumentation
> also removed the pure-numpy drift detection (PSI, Kolmogorov–Smirnov,
> Jensen–Shannon, `FeatureDriftMonitor`) and the Celery queue-depth and
> worker-liveness helpers. Those had no Prometheus dependency in substance and
> could be brought back decoupled from it.

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
| `backend/tests/test_data_governance.py` | 45 passed |
| `backend/tests/test_backtesting.py` | 54 passed |
| `backend/tests/test_risk_series.py` | 13 passed (torch-gated, real checkpoint) |
| `backend/tests/test_snapshots.py` | 12 passed |
| `backend/tests/test_reproducibility.py` | 14 passed |
| `backend/tests/test_baselines.py` | 7 passed (torch-gated) |
| `backend/tests/test_timeseries_store.py` | 16 passed |
| `backend/tests/test_model_io.py` | 14 passed |
| `python -m compileall -q backend` | clean |
| `ruff check backend --select E9,F63,F7,F82` | clean |
| **entire backend suite** (pinned dependency set: FastAPI, torch, Celery) | **232 passed, 1 skipped** |
| `frontend`: `npm run build` | passed |
| `frontend`: Playwright e2e | 1 passed |

The single skip is `test_country_scope.py`, which needs the Docker CLI and a
PostgreSQL service. Earlier rounds reported a reduced local subset because torch
and FastAPI were not installed in the throwaway environment; the counts above are
from the full pinned environment (`backend/requirements.txt` +
`backend/requirements-dev.txt`), which is what CI installs.

---

# Core Review Remediation (Second Round)

Scope: BEACON core only. API authentication and the Grafana/Prometheus stack are
explicitly out of scope for this round and no change was made to them.

Verdict accepted from the review: the data-governance model, `safe_torch_load`
with `weights_only=True`, the typed error codes, and the signal-to-return
convention are sound. Two things blocked credibility — a fold-boundary artefact
in aggregate backtest metrics and fragile attestation propagation through
`DataFrame.attrs` — and both are now fixed, with tests that fail if either
regresses.

## Must-fix findings

### 1. Fold-boundary artefact in aggregate backtest metrics — *Fixed*

**Finding.** Concatenating out-of-sample predictions across folds and then
differencing the concatenation creates one artificial transition per fold
boundary. Those transitions never existed in the underlying series, so aggregate
Sharpe, Sortino, drawdown, Calmar, volatility, and VaR/CVaR were biased.

**What changed** (`backend/modules/engine/backtesting.py`)

| Item | Detail |
|---|---|
| Boundary-aware returns | `risk_signal_to_returns(signal, boundaries=...)` differences *within* each segment and concatenates the per-segment return series. New helpers `segment_slices`, `count_segment_transitions`. |
| Boundary-aware directional score | `hit_rate(actual, predicted, boundaries=...)` measures agreement inside each segment and pools with the comparison count as the weight. A segment with no signal is excluded rather than counted as a run of mismatches. |
| `compute_metrics(..., boundaries=...)` | Threads the boundaries through both the derived return series and the directional metrics. Passing an explicit `returns` series *and* `boundaries` is rejected as ambiguous. |
| Backtester | `WalkForwardBacktester.run()` derives the interior fold seams from the fold test-block sizes and applies them. `BacktestResult` now carries `boundaries` and `n_boundary_transitions_removed`, and `to_dict()["aggregation"]` records `returns: "per_fold"`. |
| Doc caveat removed | The paragraph telling readers to "read the aggregate metrics with the boundary transition in mind" is gone, replaced by the actual fix. |

**Invariant test.** With a model whose predictions are constant inside each fold
but differ across folds, the aggregate return series must be *exactly* flat —
zero return at every position, zero drawdown, zero Sharpe. Before the fix that
series contained three spurious spikes. Also covered: aggregate returns equal the
concatenation of the per-fold returns (so the correction is provably per-fold,
not a hand-applied mask), and the naive series is shorter by exactly
`n_splits - 1`.

### 2. Attestation propagation through `input_data.attrs` — *Fixed*

**Finding.** Pandas does not reliably preserve `attrs` through `groupby`,
`merge`, `concat`, or most reshaping. Any pipeline that transformed the frame
before prediction could silently lose the attestation.

**What changed**

- `RealPredictionEngine._enforce_data_quality()` no longer reads
  `input_data.attrs`. The verdict is an explicit value:
  `engine.predict(frame, attestation=...)`, with the engine-level attestation as
  the fallback. Both the 2-D and multi-bank paths resolve it the same way.
- Resolution moved into `AttestationResolver` in `quality_gate.py`, which is the
  single, torch-free place where a prediction is allowed to proceed. It returns
  the verified attestation so callers can thread its `attestation_id` onward.
- All in-repo call sites pass the attestation explicitly:
  `job_tasks.py` (prediction job, backtest job), `models_v1.py` (scenario
  prediction — where the frame *is* transformed by `_apply_adjustments`).
- Regression guards: an AST-level test asserts that neither `quality_gate.py` nor
  `prediction_engine.py` contains any `.attrs` attribute access, and a pandas
  test documents that `groupby`/`concat` drop attrs while `sort_values` keeps
  them — exactly the inconsistency that made the old path unsafe.

### 3. The gate accepted an externally computed composite score — *Fixed*

**Finding.** The gate re-derived its own verdict, but still accepted
`quality_score: Optional[float]` from the caller, so it inherited the weighting
flaw of whatever produced that number.

**What changed**

- `quality_score` was **removed** from `DataQualityGate.evaluate`/`enforce`. A
  test asserts the parameter does not exist, so it cannot be reintroduced
  quietly.
- The pipeline now hands over `QualityComponents` (completeness, consistency,
  timeliness, accuracy) and the gate computes the weighted composite itself.
- `DEFAULT_COMPONENT_WEIGHTS` lives in the gate; `QualityPolicy.score_weights`
  can override it. The weights are identical to the previous analyzer weights, so
  historic scores remain comparable.
- Unmeasured components are `None` and are excluded with weights renormalised,
  rather than being zero-filled.
- Out-of-range or non-finite components raise `ValueError` instead of being
  clamped.
- **Duplicated scoring removed:** `DataOrchestrator._generate_quality_report()`
  no longer computes a weighted average at all — it produces sub-scores only.
  `run()` sets `quality_report.quality_score` from the attestation and
  `fit_for_engine` from `attestation.verified`, so the flag is now literally the
  gate's verdict rather than a parallel computation.
- **A payload with no non-empty dataset scores exactly 0.0.** Previously the
  missing-value and consistency terms were vacuously perfect (the 70/100 empty
  payload). `measure_components()` now short-circuits to
  `completeness=0.0, consistency=0.0`.

### 4. `fail_on_any_error` defaulted to permissive — *Fixed*

**Finding.** Strict mode was opt-in. For a risk engine, partial data flowing
downstream with only a log entry is not acceptable.

**What changed** (`backend/modules/data/collector.py`)

- `fail_on_any_error` now defaults to `True`. The first failing source aborts the
  collection with `DataQualityError`, and the error context names what *was*
  collected, the success ratio, and the explicit opt-out wording.
- `DataOrchestrator` calls `collector.collect(...)` without overriding it, so the
  DATA pipeline is strict by default.
- The old test that asserted silent partial success was rewritten as an explicit
  opt-out test, and a new test pins the strict default.

### 5. `allow_unverified_data` override — *Fixed (environment-gated)*

**Finding.** An override that lets the engine predict with no quality
attestation is a footgun, even when logged.

**What changed**

- The `allow_unverified_data` **config flag is gone**; setting it (or
  `require_quality_attestation: false`) now logs that it is ignored. There is no
  config path to skip the gate.
- The only override is the `BEACON_ALLOW_UNVERIFIED_DATA` environment variable,
  and only outside production.
- Requesting it in `production`/`prod` (read from `BEACON_ENV`, `ENVIRONMENT`, or
  `APP_ENV`) raises `PredictionBlockedError` at resolver construction, so the
  process fails to start rather than silently weakening the gate.
- Outside production it is still loud: a warning at construction and a warning on
  every prediction that runs unattested.
- The engine orchestrator also verifies the attestation embedded in the data
  package (`DataQualityGate.require`), and no longer substitutes a default
  quality score of `80.0` when the metadata carries none — that silently
  manufactured an operational-risk number out of nothing.

## Additions

### Baseline comparison with reported lift — *Done*

`backend/modules/engine/backtesting.py` gains three numpy-only baselines —
`PersistenceBaseline` (random walk), `AR1Baseline` (the ARIMA(1,0,0) case, fitted
by OLS on lagged levels and clamped to the stationary range), and
`LinearBaseline` — plus `baseline_factory()` and
`WalkForwardBacktester.compare(X, y, baselines=(...))`, returning a
`BaselineComparison` whose `lift()` maps each baseline to per-metric
improvements.

**Lift convention:** `primary - baseline` for metrics where larger is better,
`baseline - primary` for the metrics in `LOWER_IS_BETTER` (mse, mae, rmse,
max_drawdown, annualized_volatility, var_95, cvar_95). Positive always means the
primary model is better, and `lift_convention` is recorded in the payload so the
sign cannot be misread.

**Wired in:** `ModelTrainer` runs the comparison after test evaluation
(`_baseline_comparison`), using a `_FrozenSequenceModelAdapter` so the trained
artefact is evaluated frozen while the baselines refit on every fold — the
conservative direction for a credibility claim. The result lands in
`TrainingMetrics.baseline_comparison`, the training job result, and the model
manifest.

The adapter/harness integration is covered by `backend/tests/test_baselines.py`
(torch-gated). Writing that test immediately caught a real defect in the wiring —
the adapter was passed to the harness as a value rather than as a zero-argument
factory, so every baseline comparison silently degraded to "skipped". The test
fails if the primary model never actually runs.

**Known gap:** the multi-scale trainer does not report a comparison yet. Its model
consumes several heterogeneous inputs, so the flat design matrix the harness
needs does not describe it; `baseline_comparison` is therefore `null` for
multi-source training, which the job result and manifest both record as "not
measured" rather than "no lift".

### Model registry / reproducibility manifest — *Done*

New `backend/modules/engine/reproducibility.py`:

| Field | Meaning |
|---|---|
| `git_sha` | Revision of the training code (env vars first, then `.git/HEAD`, including packed-refs and worktree `gitdir:` files) |
| `config_hash` | sha256 of the canonicalised training configuration |
| `attestation_id` | Content address of the DATA quality verdict |
| `snapshot_id` | Content address of the exact rows that were verified |
| `model_artifact_hash` | sha256 of the model file |
| `dataset_row_counts`, `training_metrics`, `backtest`, `extra` | Supporting context |

`ModelManifest.write()` writes `reproducibility.json` next to the artefact;
`load()` accepts the model path, the directory, or the manifest path;
`verify()` re-hashes the artefact, so a swapped or corrupted checkpoint is
detected rather than assumed away. The training job writes the manifest and
includes `manifest.describe()` in the job log.

### Dataset lineage / content-addressed snapshots — *Done*

New `backend/modules/data/snapshots.py`. A `DatasetSnapshot` fingerprints the
payload — per-dataset content hash (via `pd.util.hash_pandas_object`), row and
column counts, column names, and date span — and derives its `snapshot_id` from
that fingerprint, so the id is a *content address*: any changed cell changes it.
`DatasetSnapshotter` persists a copy plus `snapshot.json` and can verify both the
live frames and the bytes on disk.

The attestation now carries `snapshot_id`, so a verdict names the exact data it
was issued against. `DataOrchestrator.run()` snapshots `clean_data` before the
gate runs and passes the id into `enforce(...)`; the DATA job result exposes both
`snapshot_id` and `dataset_snapshot`.

### Core tests for the two blockers — *Done*

| Test | Guards |
|---|---|
| `test_piecewise_constant_predictions_produce_a_flat_return_series` | No seam contributes a non-zero return |
| `test_aggregate_returns_equal_concatenated_per_fold_returns` | The correction is per-fold, not a mask |
| `test_naive_aggregation_would_have_been_biased` | The artefact really existed (`n_splits - 1` extra transitions) |
| `test_hit_rate_pools_within_segments` | A seam is never scored |
| `test_hit_rate_skips_segments_without_signal` | Signal-less segments do not dilute the pool |
| `test_dataframe_attrs_are_not_a_reliable_attestation_carrier` | `groupby`/`concat` drop attrs, which is why they cannot carry a verdict |
| `test_governance_modules_never_read_dataframe_attrs` | AST guard against reintroducing `.attrs` |
| `test_resolver_prefers_the_explicit_argument_over_its_default` | The argument, not frame metadata, decides |
| `test_unverified_override_is_environment_gated` | Production refuses the override |
| `test_baselines.py::test_reports_lift_over_the_baselines` | The primary model actually runs through the harness, and its lift is reported |
| `test_risk_series.py::test_last_step_matches_the_point_prediction` | The rolling series and the point prediction agree on the row they share |
| `test_risk_series.py::test_series_is_aligned_time_ordered_and_seam_bounded` | Every prediction is paired with the row it was made for |
| `test_per_segment_folds_stay_inside_their_segment` | No fold trains on one source and tests on another |

## Removals

- `allow_unverified_data` as a config flag — replaced by the environment-gated
  override described above.
- The external `quality_score` parameter on the gate.
- The duplicated composite scoring in the DATA orchestrator.
- The `DataFrame.attrs` attestation read.
- The documentation caveat about fold-boundary transitions — replaced by the fix.
- The silent `quality_score` default of `80.0` in the engine orchestrator.

## Additional finding, not in the review

While fixing the aggregate-metric path, the backtest job's per-observation
metrics turned out to be comparing two different things: `RealPredictionEngine`
returns **one risk score per data source**, while the target column is **per
row**. The old code truncated the longer series with `min(len(...))` and computed
MSE, R², directional accuracy, Sharpe, and friends across the misaligned pair —
differencing a concatenation of *unrelated entities*, which is the same class of
error as the fold-seam artefact but larger.

**First response (insufficient).** The job refused to publish metrics it could
not justify, reporting `quant_metrics_skipped` with a reason. Honest, but it left
the backtest job producing no numbers at all, which is not acceptable for a
platform whose whole point is validating a model.

**Proper fix.** `RealPredictionEngine.predict_risk_series()` rolls the same
window, the same source mapping and the same normalisation across the payload,
producing **one prediction per timestep**:

| Property | Detail |
|---|---|
| Alignment | Each prediction carries the `row_offset` of the very row whose window it used, so it pairs with that row's target without relying on a unique frame index. |
| Ordering | Rows are grouped by source and time-ordered inside each group. |
| Seams | `boundaries` records the offset between consecutive sources, so returns, the equity curve and the directional score never difference across a seam. The job passes those boundaries straight into `compute_metrics`. |
| Folds | `walk_forward_folds_per_segment()` generates each source's folds inside that source's own contiguous span and shifts the indices back into the concatenated series. Folding across sources would train on one entity and test on another. |
| Cost | `max_steps` (default 2000 per source, configurable per job via `parameters["risk_series"]`) caps the timesteps inferred, keeping the most recent; `batch_size` shares a forward pass across windows. Rows dropped by the cap are reported in `truncated`. |
| Consistency | The final step of a source's series equals the point prediction `predict()` returns for that source — asserted in `test_risk_series.py`. |

Reproduced by `backend/tests/test_risk_series.py` against a **real checkpoint**
(the test builds one with `MultiScaleTemporalAttentionModel` and `safe_torch_save`),
so it exercises the same model-call convention the live engine uses.

**Second finding while implementing this.** The rolling series normalises each
source with the checkpoint's training-time statistics when they exist. When a
checkpoint carries no `source_stats`, the only available statistics are computed
over the window being evaluated — which lets the normalisation see the future and
makes the resulting metrics optimistic. That fallback still happens (it is what
`predict()` does too), but it is now *recorded*: `stats_provenance` maps each
source to `"checkpoint"` or `"payload_window"`, and a warning names the sources
affected. A backtest can therefore state whether its normalisation was leak-free.

The metrics are no longer dropped: a series that exists is scored, and a target
column is optional (without one, the return-based metrics still describe the
model's own risk trajectory). `quant_metrics_skipped` now appears only when no
per-timestep series could be built at all, and it still carries the exception
that caused it.

## A pre-existing integration bug this work runs into

`ModelTrainer` (the single-scale path, chosen when the training frame has no
`source_code`) saves a **`TemporalAttentionNetwork`** checkpoint and does not
persist `source_stats`. `RealPredictionEngine._load_model` unconditionally builds
a **`MultiScaleTemporalAttentionModel`**, so that checkpoint cannot be loaded at
all:

```
RuntimeError: Error(s) in loading state_dict for MultiScaleTemporalAttentionModel:
  Missing key(s) in state_dict: "source_encoders.0.0.weight", ...
```

Verified directly (build a `create_model("temporal_attention", ...)` checkpoint
with `safe_torch_save`, hand it to `RealPredictionEngine`, observe the
`RuntimeError`). The consequence is that a single-source-trained model cannot
reach the prediction or backtest jobs at all.

This is pre-existing and out of the selected scope, so it is recorded rather than
fixed: closing it means deciding which architecture the engine should serve, or
teaching `_load_model` to dispatch on `model_type`. Two things follow from it
that are worth knowing:

* The engine only ever loads a `MultiScaleTrainer` artefact, and that trainer
  **does** persist `source_stats` and `sources` (in `multi_scale_trainer.py`).
  So the leak-free `"checkpoint"` normalisation described above is the normal
  case in practice, and the optimistic `"payload_window"` path is only reached by
  a checkpoint that carries no stats.
* The rolling risk series is therefore tested against a
  `MultiScaleTemporalAttentionModel` checkpoint, which is exactly what the live
  engine can load.

## Trajectory

Confirmed sound and left alone: the signal-to-return convention
(`return_t = -(risk_t - risk_{t-1})`), `safe_torch_load` with `weights_only=True`,
the typed error codes with stable `code` values, the gate's independent
re-derivation of its own verdict, and the leakage-free fold generation (the
embargo/gap logic is untouched and still tested).

With the two blockers fixed, a baseline reported as lift, and every artefact
carrying a verifiable provenance manifest and a content-addressed data snapshot,
the core is defensible for regulated use. API auth and the Grafana/Prometheus
stack were out of scope and are unchanged.
