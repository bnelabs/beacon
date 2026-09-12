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

Scope: BEACON core only. API authentication and operational monitoring are
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
the core is defensible for regulated use. API auth and operational monitoring
were out of scope and are unchanged.

---

# Third Review Round — Reachability, Stationarity and the Clearing–Spiral Join

This round answers a *trajectory* review that credited BEACON with several
state-of-the-art capabilities. Most of that credit was accurate. The organising
finding of this round is narrower and more uncomfortable: **two of the
capabilities the review praised most confidently were implemented and thoroughly
tested but not reachable from the engine at all.**

That makes reachability a *recurring* failure mode here, not a one-off. The same
defect had already been found and closed twice (§2.10 of `G_SIB_BUILD.md`, for the
fire-sale and TNCM-VAE modules), and the document at that point claimed: *"Every
one of the nine review items is therefore both implemented and reachable from the
engine."* It was not. Two more had been missed, and a third orphan layer is
recorded below.

## 5.0 The finding: implemented is not reachable

**Method.** For each module the review credits, the import graph was traversed:
grep the symbol across the repository, drop matches inside the defining module
itself, drop `tests/` and `docs/`, and ask what remains. What remains is what runs.

| Module | Lines | Test lines | Non-test importers before this round |
|---|---|---|---|
| `backend/modules/engine/cpcv.py` | 335 | 414 | **none** — only `tests/test_cpcv.py` |
| `backend/modules/engine/neural_sde.py` | 950 | 1141 | **none** — only `tests/test_neural_sde.py` |

The review's two headline claims were therefore false as stated:

* *"The system uses Combinatorial Purged Cross-Validation (CPCV) with Embargo."*
  It did not. Production validated with `backtesting.generate_walk_forward_folds`
  — walk-forward with an optional embargo, a genuinely weaker method — while
  `cpcv.py` sat unused.
* *"Neural SDEs: Replaces deterministic Neural ODEs."* They replaced nothing,
  because nothing called them.

A third case was found while checking the second, and it is a *finer-grained*
version of the same defect rather than a module-level one:
`backend/modules/engine/temporal_graph.py` is now loaded, because `neural_sde`
reuses its memory primitives (`MemoryState`, `NeuralODEField`, `TimeEncoder`,
`rk4_integrate`). But its actual model, `TemporalGraphNetwork`, is referenced
nowhere outside its own file — the module is on the import path and contributes no
capability. That is why the regression test below checks reachability *from the
production roots* rather than "has an importer", and separately checks recorded
symbols.

This is the reason the round is framed as reachability rather than as model work:
a tested module that nothing calls is indistinguishable from a capability the
system does not have, except that it makes the documentation overstate the system
to a reader who trusts it — which, for an auditor, is the worse failure.

## 5.1 CPCV is now the production validation scheme — *Done*

`backtesting.py` gains `generate_cpcv_folds`, `cpcv_split_boundaries`,
`CPCVFoldResult`, `CPCVBacktestResult` and `CPCVBacktester`, and `ModelTrainer`
selects the scheme from configuration (`validation_scheme` ∈
`walk_forward` / `cpcv` / `both`).

Three design points that are not incidental:

* **Predictions are not concatenated.** `WalkForwardBacktester` concatenates fold
  predictions because its test blocks are disjoint and cover the sample once.
  CPCV does not have that property: with `n_groups=6, n_test_groups=2` every
  observation is test data in five of the fifteen splits, so a concatenated series
  would be longer than the sample and would score the same observation repeatedly.
  The result is therefore a *distribution* (mean, dispersion, min, max across
  splits), and `CPCVBacktestResult` deliberately exposes no `predictions` key.
  A test asserts that the test sets overlap, which is the property that forbids
  concatenation.
* **Fold sizes are counted, not spanned.** `FoldResult` derives
  `n_train = train_end - train_start`, which assumes contiguity. A CPCV training
  set is the complement of the test groups *minus* purged and embargoed rows, so
  it has holes and its span overstates its size. A dedicated `CPCVFoldResult`
  records the counted sizes, and a test asserts the count is below the span for a
  split with an interior test group.
* **An unusable configuration raises.** A configuration whose splits are all
  purged to nothing raises rather than returning an empty fold list, because an
  empty list reads downstream as "the model was validated". Degenerate individual
  splits are returned and counted rather than dropped, so the fold count is
  auditable.
* **A misspelled scheme raises.** `validation_scheme: "CPVC"` raises instead of
  silently falling back to walk-forward, which would let a caller believe a
  stronger check ran than did.

Directional scoring pools within each contiguous test block, via the existing
`boundaries` argument, for the same reason walk-forward pools within folds: two
non-adjacent held-out groups are not adjacent in time, and differencing across
the gap scores a transition that never occurred.

**Tests:** `backend/tests/test_cpcv_wiring.py` (15 tests), including reachability
through `ModelTrainer._baseline_comparison`. Existing walk-forward behaviour is
unchanged and still tested: `test_cpcv.py` (38), `test_backtesting.py` (43),
`test_baselines.py` (7).

## 5.2 The clearing engine now drives the liquidity spiral — *Done*

The spiral's own docstring claimed it "composes with the clearing engine", and
`G_SIB_BUILD.md` recorded that the module had been un-orphaned. Both were
partly true: the spiral was reachable through `fire_sale.py`, but the *join the
review asked for* did not exist. Clearing produced a cash shortfall; the spiral
expected a price shock; nothing translated between them.

* `liquidity_spiral.shock_from_shortfall(shortfall, *, price, price_impact)`
  performs the translation: a shortfall `S` requires selling `S / price` units,
  which at impact `λ` moves the price by `λ · S / price`, returned negative. The
  docstring states the first-order approximation explicitly and records what is
  **not** double-counted (the shortfall-driven sale is the exogenous shock; the
  spiral's own sales are the separate leverage-driven ones).
* `analyze_multiple_banks` gains `spiral_parameters`, a new
  `MultiBankAnalysis.liquidity_spiral` field, and its `to_dict()` entry.
* `RealPredictionEngine.predict` and `_predict_multi_bank` forward the parameter,
  and `_generate_multi_bank_explanation_report` renders the section, with an
  explicit `UNAVAILABLE` branch naming the reason when it is absent.

Fail-closed behaviour, matching the reasoning already used for the regulatory
table: spiral parameters supplied **without** a clearing equilibrium raise
(the shock *is* the shortfall, so there is nothing to propagate and none is
invented from the model score); a table that omits a defaulting institution
raises (a partial table reads as though that institution had no spiral); an
unknown institution raises; a wrongly typed value raises.

**Tests:** `backend/tests/test_clearing_spiral_coupling.py` (23 tests), including
a check that deepening the default (by halving the endowment) deepens the shock,
and reachability through `RealPredictionEngine._predict_multi_bank`.

## 5.3 Stationarity: the review was half right — *Done*

The review asked to "add ADF and KPSS to `validator.py`". ADF was already
implemented and tested (`backend/modules/data/fractional.py`), so only KPSS was a
real gap; and the gate that matters is `quality_gate.py`, not `validator.py`.

`kpss_test` / `kpss_statistic` / `KPSSResult` were added alongside the existing
ADF implementation, mirroring its return shape, with the Newey-West/Bartlett
long-run variance and the same Schwert lag rule. **Verified independently**: a
from-the-definition reimplementation written without reference to the module
agrees to `1e-9` on white noise, a random walk and a trend-plus-noise series, under
both the level and trend variants. Critical values are the published KPSS (1992)
Table 1 values.

Two deliberate choices, both documented in the module:

* **Non-stationarity is reported by default, not fatal.** The gate certifies
  *raw* collected data, and raw financial levels are I(1) by construction; failing
  every unit root would reject the standard input of the models built to handle
  it (`fractional.py` already ships fractional differencing for the feature
  stage), and operators would simply disable the gate. The finding is always
  recorded and logged, never silent, and `require_stationarity=True` makes it
  blocking for a deployment that wants that.
* **Both variants must reject.** A trend-stationary series rejects the level
  variant but not the trend variant, and is accepted. Without this rule the gate
  would flag every deterministic trend as non-stationary.

The empty-payload guarantee from §2A is preserved and re-tested: an empty payload
still raises `EmptyDatasetError` even under `require_stationarity=True`. Stationarity
is deliberately kept out of `_structural_checks`, so the composite score
arithmetic is unchanged.

**Tests:** `backend/tests/test_stationarity.py` (18 tests); `test_fractional.py`
and `test_data_governance.py` stay green (84 passed together).

## 5.4 Legacy heuristics: verified absent, and one real drift fixed — *Done*

The review asked to "ensure no legacy code remains" that divides by `1e9` or uses
an arbitrary `risk > 0.8` failure rule. Rather than grep — which cannot tell a
docstring from a live expression — the check was done with `ast`: every numeric
and string constant was located, and constants that are docstrings (the first
statement of a module, class or function) were excluded.

* `1e9` / `1e10` scaling: **0 occurrences in executable code.**
* `HGT` / `MultiScaleGNN`: **0 occurrences in executable code.**

Both survive only inside docstrings that *document the removal* (`clearing.py`,
`bank_analyzer.py`, `models.py`, `orchestrator.py`). The review also asked to
delete those references. They are deliberately kept: `models.py` states plainly
that the graph models "were dead code that made the system *claim* a capability it
never used", which is exactly the audit trail a reader needs. Deleting the note
that a defect existed is how the defect returns.

**Correction to the review on `validator.py` and one genuine fix.** The surviving
`0.8`/`0.85` literals outside tests are train/test split fractions, Basel RSF
weights, inline R² bands, or the documented constants in `constants.py`. Two of
them were a real defect: `constants.py` carried the risk bands twice — a 0-1 scale
(`RISK_THRESHOLD_HIGH = 0.85`) and a 0-100 scale (which read `80`) — so 0.82 was
"high" on one scale and "critical" on the other; and `bank_analyzer._risk_to_text`
repeated the literals a third time instead of importing them, so the narrative
summary could silently disagree with the per-institution band it summarises. The
percentage scale is now *derived* from the 0-1 scale, and `_risk_to_text` reads
the named constants.

**Tests:** `backend/tests/test_risk_thresholds.py` (21 tests) locks the derivation
and asserts the two renderings describe the same band across a score grid.

## 5.5 A recommendation rejected on evidence: no graph database — *Rejected, with reasons*

The review recommends integrating "a specialized graph engine (like TigerGraph,
Neo4j, or DuckDB) to handle the heavy matrix multiplications ... more efficiently
than Postgres", on the stated premise that "querying dense adjacency matrices
(graph structures) in Postgres is inefficient".

**The premise is false for this codebase.** Verified: the database schema defines
17 tables (`notifications`, `error_logs`, `pipeline_jobs`, `data_jobs`,
`engine_jobs`, `result_jobs`, `jobs`, `indicator_observations`, `risk_scores`,
`model_metrics`, `country_profiles`, `country_indicators`, `country_comparisons`,
`alert_rules`, `data_catalogue`, `assets`, `data_sources`) and **none of them
stores an adjacency or exposure matrix**. The network is built in memory as a
numpy array from a caller-supplied `(debtor, creditor) -> amount` mapping and
cleared by `clear_multiplex`; the multiply-heavy work is already dense
linear algebra in numpy.

Adding a graph engine would therefore: add an operational dependency; introduce a
second, redundant representation of the network to keep in sync; and solve no
query the system performs. The recommendation is recorded as **rejected**, not
deferred, and the reason is the evidence above rather than effort.

The *real* gap the review was reaching for is that exposures had no persistence at
all — a caller had to hold the matrix in memory. That is now addressed by the
bilateral exposure store and upload endpoint (§5.6).

## A third orphan layer, recorded rather than fixed: the data connectors

While checking the SDE's reachability, a third instance of the same defect was
found, and it is larger than either of the first two. **The entire
`backend/modules/data/connectors/` package is orphaned.**

The package contains a base class, a lazy registry and five connectors:

| Connector | Source | Test lines |
|---|---|---|
| `sec_n_mfp` | SEC Form N-MFP money-market fund portfolios | 863 |
| `payments` | Payments data | 793 |
| `ecb_ccp` | ECB / CPMI-IOSCO CCP disclosures | 640 |
| `bis_credit` | BIS total credit to the private non-financial sector | 604 |
| `sec_form_pf` | SEC Form PF — refuses by design (confidential) | — |

**Evidence of orphaning.** Traversing every reference to `build_connector`,
`available_connectors`, and each connector's module name: outside `tests/` and
`docs/`, every hit is *inside the package itself* — the registry in `__init__.py`
and its docstring examples. Nothing in the production ingestion path uses them.
That path uses a different abstraction: `backend/modules/data/collector.py` and
`backend/services/data_source_service.py` both call
`backend.plugins.base.get_plugin`. A check for a name-based or config-based
invocation found none: no connector key appears in `configs/`, and there is no
dynamic dispatch to the registry.

So BEACON has **two overlapping ingestion layers**: `backend/plugins/` (14
plugins, one of them the live path) and `backend/modules/data/connectors/` (5
connectors, none of them the live path). `docs/data_connectors.md` documents the
second layer as a capability, including its point-in-time guarantees ("revision
history is mostly absent", "assumed" late bounds) — which is exactly the kind of
honest documentation that makes the orphaning misleading to a reader.

**Why this is recorded and not fixed in this round.** Closing it is a design
decision, not a wiring task, and the two candidate resolutions have different
consequences:

1. *Migrate* the production ingestion path onto the connectors. The connectors
   carry stricter point-in-time semantics than the plugins layer, so this is
   probably the right long-term answer — but it is a migration of the ingestion
   path for five public sources, and it needs its own round with its own tests.
2. *Bridge* the connectors into the plugin registry so both are reachable, at the
   cost of keeping two abstractions indefinitely.

Choosing between them is the maintainer's call. What this round establishes is the
fact the review did not: the connectors are not a capability the system has.

## Reachability census: what the engine actually runs

Because the defect kept recurring, the whole backend was scanned once rather than
chasing individual modules. The scan parses every non-test module's imports with
`ast` (resolving relative imports), then reports modules that nothing else
imports. Every entry below was additionally confirmed with a direct grep for both
the module name and its principal class/function names, to rule out string- or
registry-based dynamic dispatch.

**Modules with a complete implementation and a test suite but zero production
importers:**

| Module | Review said | Reality |
|---|---|---|
| `engine/conformal.py` | "implements Split Conformal Prediction and ACI" | implemented; **unreachable** |
| `engine/hidden_markov.py` (`StudentTHMM`) | "Gaussian assumptions replaced with Student-t" | implemented; **unreachable** |
| `engine/federated.py` | "correctly implements Bonawitz secure aggregation" | implemented; **unreachable** |
| `engine/uncertainty.py` | — | implemented; **unreachable** |
| `engine/subgraphx.py` | "SubgraphX modules" | implemented; **unreachable** |
| `engine/event_metrics.py` | — | implemented; **unreachable** |
| `engine/causal_validation.py` | counterfactual validation | implemented; **unreachable** (needs two graphs on a job result, which no producer supplies) |
| `engine/mixture_of_experts.py` | — | implemented; **unreachable** |
| `data/network_gate.py` | — | implemented; **unreachable** |
| `data/streaming.py` | — | implemented; **unreachable** |
| `results/timeseries_store.py` | "uses PostgreSQL with TimescaleDB" | implemented; **no runtime caller** |
| `data/connectors/*` (5 modules) | "plugin ecosystem is extensive" | implemented; **unreachable** |

This is the honest answer to the review's central question. The review's verdict
was that BEACON "has successfully transitioned into a G-SIB grade platform" and
that its logic "is leading the industry standard". Several of the specific
capabilities it credited — conformal intervals, Student-t regimes, federated
aggregation, SubgraphX attribution — are implemented to a high standard and are
**not running**. The engine was also observed telling the truth about this: the
production `PredictionResult` reports `confidence_intervals` as `(None, None)` and
its own docstring says no calibrated interval exists yet, while
`docs/G_SIB_BUILD.md` describes the conformal machinery as built.

**Method limits, stated so the table is not over-read.**

* Plugins (`backend/plugins/*`) load by *name* through `get_plugin`, so they are
  excluded: they are an intentional dynamic registry, not orphans. Their
  reachability was checked separately — `collector.py` and
  `data_source_service.py` call `get_plugin`, so the registry is live.
* Alembic migrations, `backend/scripts/`, `__init__.py` packages and entry points
  are excluded: they are not capabilities.
* "Zero importers" is a sufficient condition for an orphan, not a proof of
  usefulness for the rest. A module can be imported and still be dead.

**Recommendation, not performed in this round.** Wiring twelve modules is twelve
integration decisions, each of which needs a real production entry point and a
semantic decision (where do conformal calibration labels come from? what supplies
the federated training coordinator? what is SubgraphX's game value on a real
network?). Rushing them would produce exactly the defect this round is about — code
that looks integrated and is not. The two with the clearest production homes, and
therefore the recommended first two, are:

1. `conformal.py` — the engine already reports intervals as unavailable *pending
   conformal calibration*, so the entry point is written down already.
2. `hidden_markov.py` — a regime label attached to the existing per-source score.

## 5.6 The network is now served live, and exposures can be uploaded — *Done*

The review's most concrete UI finding was correct and verified: `RiskMap.jsx`
imported `networkConnections` and `regions` from static JSON files, and no
network-graph endpoint existed anywhere in the API.

**`GET /api/v1/network/graph`** returns the current multiplex network. It returns
`status: "available"` with real nodes, edges and layers, or `status:
"unavailable"` with a reason and empty arrays. It never fabricates a node or an
edge — the repo treats invented network data as a serious defect, and an
unavailable network is a fact worth reporting rather than papering over.

**`POST /api/v1/network/exposures`** accepts an institution's bilateral matrix as
CSV or Parquet and persists it through `backend/services/bilateral_exposure_store.py`,
which also exposes `load_bank_exposures()` — the exact
`(debtor, creditor) -> amount` shape `analyze_multiple_banks` accepts.

Verification of the security-relevant properties, done after the fact rather than
taken on trust: the Parquet reader is pinned to `pyarrow`, so an upload cannot
execute code the way a pickle-based engine could; the byte cap is enforced
(64 MiB default, env-overridable); writes are atomic (temp file plus `os.replace`),
so a crash cannot leave a truncated adjacency matrix for a later reader to open;
and `source_institution` is stored as manifest metadata only, never used to build
a path, so it cannot traverse directories.

Three decisions worth recording, because they were judgement calls:

* **Geography stays static; exposures do not.** Region boundaries and centroids
  are reference data and legitimately static. Institution-level ids have no
  coordinates, so an institution-level edge that cannot be placed is reported in
  the UI as unplaced rather than being given an invented position.
* **No invented risk score.** Uploaded exposures carry no risk score, so the API
  returns `risk_score: null` and the UI says "unavailable" instead of colouring an
  arc from a number nobody computed.
* **Auth.** There is no auth layer in this application; the upload endpoint
  follows the existing convention and is documented in its module docstring as
  **unprotected** — anyone who can reach the API can replace the matrix that drives
  the map and (once wired) clearing. This is a platform-level decision that was
  not invented locally.

**Honest status of the wiring.** The uploaded matrix is reachable through the API
and through `load_bank_exposures()`, but the prediction engine does **not** yet
pull it automatically; a caller still passes exposures explicitly. That is
recorded here rather than papered over. Closing it is a semantic decision (should
an uploaded matrix silently change engine output for every existing caller?), and
the safe form is an explicit opt-in rather than a default.

The static fixture file survives, relabelled as a fixture and gated behind
`VITE_ALLOW_STATIC_NETWORK_FALLBACK=true` plus an explicit prop, with a visible
"DEMO NETWORK" banner when used. A silent fallback would have hidden backend
failure, which is the behaviour the review was right to object to.

**Verification:** `backend/tests/test_network_api.py` (17 tests), `npm run build`
clean, and the existing Playwright e2e suite passes against the changed UI.

## 5.7 The Neural SDE is on the engine path — *Done*

`neural_sde.py` is no longer an orphan. A new
`backend/modules/engine/latent_dynamics.py` exposes a caller-declared scenario for
propagating latent stress forward under the SDE; `analyze_multiple_banks` accepts
it, `RealPredictionEngine.predict` forwards it, and the multi-institution report
renders the section (with an explicit `UNAVAILABLE` branch when absent). The
integration follows the same shape as the clearing–spiral join in §5.2.

The most important property of this change is what it **refuses** to do. This
repository rejects fake uncertainty: `prediction_engine.py` refuses to report
MC-dropout intervals because they describe a different network from the one
loaded, and `bank_analyzer.CONFIDENCE_METHOD_PENDING` records that calibrated
intervals do not exist yet. An SDE dispersion is exactly the kind of plausible
number that could be smuggled into `confidence_lower`/`confidence_upper`, so:

* the result has **no** `confidence_*` field at all;
* it carries `calibrated: bool = False` (always) and
  `label = "simulated_terminal_dispersion_under_declared_sde"`;
* its docstrings and the rendered report section both state that it is a
  simulated dispersion under a declared SDE, not a calibrated interval;
* a test asserts the confidence fields remain unset.

The drift and diffusion are declared by the caller, not fitted — the module fits
nothing, and says so.

**Tests:** `backend/tests/test_latent_dynamics.py`, including determinism under a
fixed seed, zero-diffusion reproducing the deterministic drift-only path, and
widening diffusion widening the terminal dispersion. Verified together with the
existing `test_neural_sde.py`: 171 passed.

## 5.8 Dropout-resilient federated aggregation — *Implemented, still unreachable*

`federated.py` previously documented its own gap: no dropout recovery, so the
aggregator refused to aggregate when participants were missing rather than
returning a corrupted number. That gap is now closed with the Bonawitz
construction: each participant's finite-field Diffie-Hellman key is Shamir-shared
`t`-of-`n`, Feldman VSS commitments authenticate the shares, and on dropout the
server reconstructs the missing key from at least `t` verified shares and
regenerates the pairwise masks that no longer cancel. Only the reconstructed
integer secret crosses into floating point (by seeding the PRG), so masks
regenerate bit-for-bit and recovery is exact. It fails closed when survivors fall
below the threshold, which is the same honest failure mode the module had before —
just at a higher threshold.

**The cryptographic foundation was verified independently**, not taken on trust:
the 2048-bit modulus is prime, `(P-1)/2` is prime (so it is a genuine safe prime),
and 2 lies in the order-`(P-1)/2` subgroup. The construction is the standard one
and the parameters are the RFC 3526 Group 14 group. **Tests:**
`backend/tests/test_federated_dropout.py` (43 tests, 75 with the existing file).

**It remains unreachable from production, and this is documented rather than
hidden.** A real integration needs a multi-institution training coordinator owning
the participant roster, model shape and transport — `EngineOrchestrator` and
`ModelTrainer` are both single-node, so any call site today would be an import
that never exercises masking, sharing or recovery. Adding one would be precisely
the "green import, no capability" defect this round exists to remove. The module
docstring now carries a "Reachability (honest status)" section naming what calls
it (nothing), what does not, and what a real integration requires.

## 5.9 A guard against recurrence — *Done*

`backend/tests/test_reachability.py` makes the defect a test failure instead of a
discovery. It walks the import graph **from the production roots**
(`backend.api.main` and `backend.tasks.celery_app`) and asserts that every module
in a declared capability list is reachable, and that every module in a declared
orphan list is not. It also checks recorded *symbols*, because a module can be on
the import path and still contribute nothing.

Two details are the point of the file rather than incidental:

* Reachability is computed **transitively from the roots**, not as "has an
  importer". A direct-importer check misclassified `temporal_graph`: it is
  imported by `neural_sde`, but for its memory primitives, and its
  `TemporalGraphNetwork` model is referenced nowhere. "Imported by another orphan"
  must not read as reachable.
* The orphan list is asserted to be **still orphaned**. If someone wires one, the
  test fails and forces the entry to be promoted into the capability list — so the
  census cannot rot into a stale claim, which is how the original problem went
  unnoticed.

## Verification summary for this round

Starting point: **1676 passed, 7 skipped** (measured before any change).

| Check | Result |
|---|---|
| Full backend suite | **1880 passed, 7 skipped** |
| Coverage of the CI correctness gate (`ruff --select E9,F63,F7,F82`) | passes |
| Frontend production build (`npm run build`) | passes |
| Frontend Playwright e2e (`npx playwright test`) | 2 passed |
| KPSS statistic re-derived independently from the definition | agrees to `1e-9`, level and trend |
| Federated DH group re-checked for primality / safe-prime / subgroup order | 2048-bit prime, `(P-1)/2` prime, `2` of order `(P-1)/2` |
| Legacy `1e9` / `HGT` / `MultiScaleGNN` in executable code (AST, docstrings excluded) | 0 occurrences |

Tests are the evidence for the rest, and each new file states the property it
exists to establish rather than restating the implementation.

## What this round did not do

Recorded plainly, because the value of a remediation record is that a reader can
tell the difference between "verified" and "asserted".

* **The orphaned modules other than `cpcv`, `neural_sde`, `causal_discovery` and
  `tncm_vae` are still orphaned.** They are now enumerated, each with what a real
  integration would require, and guarded by a test that fails if the census drifts.
  Wiring the rest is the largest remaining item and is deliberately not rushed
  here.
* **The uploaded exposure matrix does not yet drive the engine automatically.**
  The endpoint, validation, persistence and an engine-ready reader all exist; an
  explicit opt-in to consume them was not added, because changing engine output
  for existing callers is a semantic decision rather than a wiring detail.
* **The connector layer is still unreachable.** Migrating ingestion onto it is a
  design decision between two overlapping abstractions, not a wiring task.
* **`TemporalGraphNetwork` is still unused.** Its module is loaded; its model is
  not constructed.
* **API authentication remains absent**, including on the new upload endpoint,
  which can replace the matrix driving the map. This is pre-existing and
  platform-level; the module docstring says so rather than implying protection
  that does not exist.
* **`causal_validation.py` remains unreachable.** It validates a *pair* of graphs
  (declared against learned); nothing in the pipeline produces both on a job
  result, so it needs a product decision about where that comparison belongs, not
  a call site.

**Superseded by the third sitting below.** This list was accurate when written but
it was also incomplete, and its flat form hid that: two more orphans
(`data/pit.py`, `engine/foundation_encoders.py`) were missing entirely, and every
entry here now carries a blocker plan and a next step in the disposition census.
Read the third sitting for the current state.

---

# Second sitting: the remaining objective items

The four items below closed after the first sitting was committed and merged as
PR #27. They are recorded separately so the change sets stay legible.

## 5.10 Non-linear causal discovery — *Done*

The review asked to "upgrade this to NOTEARS-MLP or DAG-GNN to capture complex,
non-linear causal drivers". What shipped is a non-linear **basis expansion**, and
the deviation is the interesting part.

The MLP form was implemented first and **rejected on evidence**. Its
augmented-Lagrangian landscape has a fatal property: ``h(W) = tr(exp(W o W)) - d``
is exactly zero at ``W = 0``, and so is the penalty gradient there, which makes
the all-zero model a global minimum of the penalty that trivially satisfies the
constraint. On ``X2 = sin(X1) + e`` the unconstrained MLP fits well and reaches
``h(W) ~ 1.16e6`` — a good fit that is wildly cyclic — and then every
augmented-Lagrangian run collapsed to the **empty graph**, under L-BFGS-B with
strong Wolfe *and* under Adam, across penalty ceilings from ``1e4`` to ``1e16``
and L1 strengths from ``0.001`` to ``0.2``. An empty graph satisfies every
structural check the module performs and reports ``converged=True``, which is the
exact failure this round exists to remove, so it was not shipped.

The basis expansion keeps each structural equation linear in its parameters —
``X_i = sum_j <b_ij, phi_j(X)> + E_i`` with ``phi_j`` the powers of ``x_j`` — and
applies the same grouped-norm constraint ``W[i, j] = ||b_ij||_2``. That keeps the
loss quadratic in the parameters, which is the regime the linear solver's penalty
schedule is already demonstrated to work in. It recovers the non-linear graph
exactly at ``degree`` 2 and 3 where the linear solver misses it:

| Solver | Edges recovered on ``X1 -> X2 -> X3`` with ``X2 = sin(X1)``, ``X3 = X2^2`` |
|---|---|
| `notears_linear` | `{X1 -> X2}` — **misses the quadratic edge** |
| `notears_basis(degree=2)` | `{X1 -> X2, X2 -> X3}` — exact |

**One bug worth recording, because it was invisible to the constraint.** The
group norm was first returned as ``[output, variable]`` while the module's
documented convention is ``weights[parent, child]``. ``h(W) = h(W^T)``, so the
constraint value, the convergence test and the acyclicity check all passed
regardless — but ``edge_list`` reported **every edge backwards**. Only comparing
against a known graph catches that, which is what the tests now do.

`NoteArsResult` gained a ``solver`` field ("linear" / "basis") because ``weights``
is a structural coefficient for one and a block norm for the other. Without it,
any consumer converting weights into coefficients would read a norm as an effect
size. The field is what lets the counterfactual seam below refuse a non-linear fit
instead of inventing coefficients from it.

**Tests:** `backend/tests/test_notears_nonlinear.py` (45 tests): exact recovery at
two degrees, the linear model's failure on the same data asserted as the premise,
acyclicity after thresholding, determinism, the non-vacuousness check (`W = 0`
converges and is acyclic, so emptiness is asserted against directly), and the full
fail-closed matrix.

## 5.11 Counterfactual analysis is on the engine path — *Done*

`tncm_vae.py` is no longer an orphan, and neither is `causal_discovery.py`: a new
`backend/modules/engine/counterfactual.py` exposes a caller-declared ``do`` query,
`analyze_multiple_banks` accepts it, `RealPredictionEngine.predict` forwards it,
and the multi-institution report renders it. The reachability guard immediately
caught the promotion and demanded the census be updated, which is the behaviour it
exists for.

The seam the `NoteArsResult` docstring always described now exists:
`structural_model_from_weights` builds a `StructuralCausalModel` from a **linear**
NOTEARS fit, and refuses a basis fit with an explicit reason — its weights are
group norms, so reading them as coefficients would fabricate the coefficients of
the model. It also refuses a non-acyclic fit, which is not a structural model.

The honesty property is the same one imposed on the SDE: the outcome carries
``is_forecast: False`` and an explicit conditionality note, the report header says
"conditional on the caller-declared structural model; NOT a forecast", and the
counterfactual is deliberately **not** required to cover the analysed
institutions, because its variables are factors rather than banks — forcing that
match would make a caller mislabel one as the other.

**Tests:** `backend/tests/test_counterfactual_coupling.py` (29 tests), including
the basis-fit rejection, the cyclic-fit rejection, constraint violations reported
rather than clipped, and reachability through `_predict_multi_bank` with both the
rendered and the `UNAVAILABLE` branch.

## 5.12 The graph-engine recommendation: rejected, now with a measurement — *Rejected*

§5.5 rejected this on the structural argument that no table stores an adjacency.
That argument is now backed by a measurement, because "we looked and it seemed
fine" is weaker than a number.

| Workload | Measured |
|---|---|
| `clear_multiplex`, n = 1000 nodes, ~4% density | **2.8 ms** |
| 10 full contagion clears at n = 1000 | **30 ms** |
| `analyze_multiple_banks`' real workload: one clear **per institution** at n = 200 | tens of milliseconds |

A database-backed graph engine would add a network round trip per iteration to
work that currently finishes in single-digit milliseconds. There is nothing to
make faster, so integration would buy an operational dependency, a second
representation of the network to keep in sync, and no query the system performs.

`backend/tests/test_analytical_capacity.py` (6 tests) locks this in with
deliberately loose bounds — roughly 1000x the measured cost — so it catches an
accidental complexity regression (a per-edge round trip, an O(n^4) rewrite)
without asserting a benchmark number a shared CI runner would make flaky.

## Verification for the second sitting

| Check | Result |
|---|---|
| Full backend suite | **1961 passed, 7 skipped** (was 1880 at the first sitting, 1676 before the round) |
| Non-linear recovery distinguished from linear | asserted as the test's premise |
| Reachability guard | caught the `causal_discovery`/`tncm_vae` promotion and required the census update |
| Generated API inventory | guarded by `test_api_docs_current.py` after a stale file turned `main` red |

---

# Third sitting: the disposition census

The round above enumerated the orphans and left them undifferentiated, recording
that wiring them was "the largest remaining item and is deliberately not rushed
here". This sitting does not wire them either. It does the three things the
enumeration could not: **makes the census complete**, **turns each orphan into a
named decision rather than an anonymous entry**, and **deletes the one thing that
was genuinely empty**.

## The census was incomplete, which is worse than the orphans

The guard asserted each list *independently* — "these are reachable", "these are
not" — and never that the two covered the tree. So an orphan could appear between
them and nothing failed. Two already had, and both were missing from the census
that claimed to have scanned the whole backend:

| Module | Lines | Why it was invisible |
|---|---|---|
| `data/pit.py` | 509 | Its only non-test importers are the unreachable connectors, so it died with them — dead collateral of a decision that had not been made |
| `engine/foundation_encoders.py` | 697 | Commit `4f4e070` fixed it so it could *load* and verified 312,684,608 params in the container, but its only caller is `scripts/compare_encoder_sizes.py`. **Loading is not reachability** |
| `modules/explainability/` | 0 | An empty package: `__init__.py` was zero bytes and nothing imported it. The explainability *routes* live in `backend/api/routes/` and are unaffected |

`test_reachability.py` now computes the census universe — every non-package
production module reachable from `backend.api.main` or `backend.tasks.celery_app`
— and asserts the unreachable set equals the declared census **exactly**.
Exclusions are declared with reasons (`backend/plugins` resolves by name through
`get_plugin`; migrations and scripts are not production entry points) rather than
being silent. The check was verified by simulation, not assumed: omitting
`data/pit.py` from the census now fails the test, naming it.

## The orphan list is now three registers

Each of the 19 unreachable modules carries a blocker, a plan and a concrete next
step, so the census reads as a queue instead of a list:

| Register | Count | Meaning |
|---|---|---|
| `wire` | 6 | A production home exists or is cheap to add |
| `decide` | 11 | Blocked on a product or design call, not on effort |
| `park` | 2 | No input exists and none is planned |

The `wire` register is the next work items, and two of them are worth naming
because the blockers were already written down in code rather than invented here:
`conformal.py` (the prediction engine reports `(None, None)` at
`prediction_engine.py:731` with a comment saying no calibrated interval exists
yet) and `timeseries_store.py` — which turns out to be the cheapest one in the
pile, because **the infrastructure is already deployed**: `docker-compose.yml`
runs TimescaleDB, the `timescale_timeseries` migration builds the hypertables, and
`models/timeseries.py` is imported by nothing but the migration and this store.
The risk-score and model-metric hypertables are migrated and empty. Wiring
`record_risk_scores` at job completion turns sunk infrastructure into a
capability; deleting the store would mean also deleting the migration and the
Compose service.

Two entries were grouped rather than listed separately: `hidden_markov.py`
produces the regime label that `mixture_of_experts.py` needs as input, so they are
one integration, not two. And `uncertainty.py` was re-described — the previous
census called it "superseded-or-pending relative to conformal", which is wrong.
Conformal answers *how wide* the interval is; `uncertainty.py` separates aleatoric
from epistemic variance to answer *whether the width means the model is lost*, and
its docstring says an epistemic spike should refuse the prediction outright. They
are complementary, and it is conformal's downstream consumer.

## What was deleted, and what was not

**Deleted:** `modules/explainability/` — an empty package. That is the only
unambiguous deletion the sweep found.

**Not deleted, and this is the important part.** A duplication scan across the
census (`roc_auc`, `average_precision`, `precision_recall_curve`,
`wasserstein_1d`, Shapley values, HMM state labelling, uncertainty decomposition)
found **no second implementation anywhere**. Nothing in the pile is superseded.
Every module there is unique, implemented and tested; what it lacks is an input,
not a reason to exist. Deleting them to make the count go down would throw away
real options and repeat the original defect in the opposite direction — this time
by destroying capability instead of advertising it. The honest finding is that
**the pile is not dead code, it is decision debt.**

`data/streaming.py` was considered for deletion and parked instead: no streaming
source is configured and its only transport is an in-memory test double, but
`temporal_graph.py` and two test files use it as a harness, so it has
test-level integration. It is one line in the `park` register with the reason.

## The Toto dependency is a live cost, not a dormant one

`foundation_encoders.py` is not merely unreachable — the production image pays for
it. `requirements.txt` declares `toto-2==2.0.0`, which drags `einops`,
`gluonts[torch]`, `safetensors`, `jaxtyping`, `dd-unit-scaling` and
`huggingface-hub` into the image, and `docs/deployment.md` records 1.2 GB / 3.9 GB
/ 9.2 GB of local checkpoints. The only thing that constructs `TotoEncoder` is
`backend/scripts/compare_encoder_sizes.py`, a developer benchmark. That is the
decision the `decide` register carries: construct it in the engine, or drop the
dependency and the encoder together.

## Documentation corrected rather than left to mislead

The README advertised, in its feature list, "SHAP values, attention weights,
feature importance". **No SHAP implementation exists anywhere in the backend**,
and `prediction_engine.py:974` removed exactly that routine, describing it as
"gradient\*input scaled by uniform attention weights" presented as SHAP values —
removed rather than re-tuned. The README was advertising the thing the engine had
deleted for being fabricated. It now states that no attribution is reported, that
the Toto encoder and HMM regime detection are implemented but not wired, and that
the risk-score and model-metric hypertables have a schema but no writer. A
**Reachability** section points at the guard as the source of truth.

The `G_SIB_BUILD.md` sentence claiming the guard "fails when the census and the
code disagree in either direction" was half true before this sitting — one
direction was unasserted. It is true now.

## Verification for the third sitting

| Check | Result |
|---|---|
| Full backend suite | **1966 passed, 7 skipped** (was 1961 before this sitting; the guard grew 7 → 12 tests) |
| Census completeness | `test_the_census_is_complete` — 92 production modules, 19 unreachable, all declared |
| Guard power, verified by simulation | omitting `data/pit.py` fails the test and names it |
| Duplication scan | no orphan re-implements a reachable module |
| `data/streaming.py` deletion reconsidered | parked, not deleted: two test files depend on it |
| Removed-package check | `test_removed_modules_do_not_reappear` fails if `explainability/` returns |

---

# Fourth sitting: the connector layer is deleted, and point-in-time has a home

The third sitting left the connectors in the `decide` register with two options:
migrate the ingestion path onto them, or bridge them into the plugin registry. A
spike on `ecb_ccp` closed **both** with evidence, so the entry is resolved rather
than deferred a fourth time. The full findings live in
`docs/data_connectors.md`.

## The spike's two negative results

Both are worth recording because each one kills one of the options.

**No consumer at the required granularity.** `ecb_ccp` looked like the producer
for `build_ccp_exposure_layer`, which wants per-clearing-member obligations to the
CCP. The ECB `CCP` dataflow has no clearing-member dimension at all: its
`entity_id` is the CCP system and its values are annual aggregates — participant
*counts* by type and securities transfer volumes. Participants are grouped, never
identified, so the two are not the same object at different resolution. Wiring
them would have produced exactly the defect the census exists to find: a green
import with nothing flowing. The other four feeds are the same shape.

**The plugin contract cannot carry the two clocks.** `fetch_indicator_data`
returns `Date, Value` — one clock — and a grep for `observed_at` or `revision`
across `backend/plugins/`, `collector.py` and `data_source_service.py` returns
nothing. The connectors' defining guarantee, that collapsing `valid_time` and
`observed_at` "is what makes a backtest silently clairvoyant", had no field to
live in. Bridging was therefore refuted, not deferred, and migration meant
changing the ingestion contract rather than adding a registry entry.

So the question was never "which abstraction wins" but "does the platform need
point-in-time data" — and with no consumer for any of the five feeds, the answer
in practice was no.

## Deleted, and kept

**Deleted:** the seven connector modules (~4,558 lines) and their five test files
(~3,100 lines). All seven are recorded in `REMOVED` in the reachability guard, so
a reappearance is a test failure rather than a surprise.

**Kept:** `data/pit.py`. Deleting five source parsers does not delete the
point-in-time design — `pit.py` always encoded it, in `Observation`'s two-clock
rule, `PITStore`'s as-of retrieval and `as_of_join`. What the connectors
contributed was parsing for feeds nobody consumed.

## The new home, and the defect it caught

`pit.py` now runs in production rather than in the census. The bilateral exposure
store's manifest already carried both clocks — `as_of` is the vintage a matrix
*describes*, `uploaded_at` is when it *became known* — so
`BilateralExposureStore.load_as_of()` resolves a matrix through `PITStore`, and
`GET /api/v1/network/graph?as_of=<ISO 8601>` serves it. A cut-off before the
stored matrix was uploaded returns `unavailable` with a reason naming the cut-off:
**the current matrix is never substituted for a vintage that did not exist yet.**
That is the anti-clairvoyance guarantee the connectors were built to provide,
applied to the exposure path the engine actually consumes.

Wiring it found a real defect, which is the argument for tests over prose. The
first implementation checked "is anything stored" *before* parsing its argument,
so a malformed `?as_of=not-a-timestamp` fell into the nothing-stored branch and
returned `200 unavailable` — the "nothing was known then" answer — instead of
`422`. The cut-off is now parsed before anything is read, and
`test_a_malformed_as_of_is_a_422` fails against the old ordering.

## Verification for the fourth sitting

| Check | Result |
|---|---|
| Full backend suite | **1725 passed, 7 skipped** (was 1966; the connector suites held ~256 tests and the new vintage suite adds 15) |
| Census after the deletion | 86 production modules, **12 unreachable**, all declared — the `decide` register fell from 11 to 4 |
| `pit.py` | promoted from `KNOWN_UNREACHABLE` to `REQUIRED_REACHABLE`, reached through the exposure store |
| No look-ahead | `load_as_of` returns nothing for a cut-off before the upload, asserted at both the store and the endpoint |
| Malformed cut-off | `422`, not a `200` unavailable state — the ordering bug above |
| Generated API inventory | `generate_api_docs.py --check` reports current (the new query parameter does not alter the inventory) |

