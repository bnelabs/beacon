# Changelog

All notable changes to the BEACON platform. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) as
specified in [`docs/VERSIONING.md`](docs/VERSIONING.md). The version of
record is the root `VERSION` file; `scripts/release.py` moves the
`[Unreleased]` block here when cutting a release.

## [Unreleased]

### Added
- `backend/tests/test_migrations_live.py`: the Alembic chain applied to a real
  PostgreSQL from each of the three histories a deployed database can have --
  empty, `Base.metadata.create_all()` with no `alembic_version` row, and a
  partial upgrade -- asserting each reaches head and that **the two terminal
  schemas are identical**, compared column by column over every table rather than
  a hardcoded list. 11 of the 12 fail against the pre-fix migrations. They skip
  without a reachable server, so Backend CI now declares a
  `timescale/timescaledb:2.15.2-pg15` service -- the image compose runs -- and
  sets `MIGRATION_TEST_DATABASE_URL`.
- `scripts/validate_compose.py` + `backend/tests/test_compose_stack.py`: 112
  invariants over the merged compose YAML for the base file and both overlays,
  plus every Dockerfile `COPY` source resolved against the build context. Needs
  no daemon, so it runs on every pull request instead of only in the manual
  `docker-backend.yml` workflow. The test also runs it against a deliberately
  broken copy of the stack and asserts a non-zero exit naming the invariant.
- `backend/alembic/guards.py`: existence guards for migrations that have to run
  against databases they did not create. The rule is that an object is skipped
  **only when the inspector says it already exists** -- none of them catches an
  exception, so a wrong column type or a missing foreign-key target still fails
  the deploy instead of hiding behind a green run. Offline (`--sql`) aware, so
  the CI render step keeps working.
- Root and `frontend/` `.dockerignore`, now that the backend build context is the
  whole repository: `.git`, `frontend/`, model weights, local `data/`/`logs/`/
  `results/`, `.env` and caches stay out of the image.

- `TestEMIterationBookkeeping` in `backend/tests/test_hidden_markov.py`: the EM loop's cost and bookkeeping invariants, which nothing previously asserted. `test_one_forward_pass_per_iteration_plus_one_final_score` counts `_forward` invocations and expects `E + 1` for `E` E-steps; it **fails on the pre-fix code** (12 passes for 5 E-steps), so the redundant pass cannot return unnoticed. Also pins the identity the change rests on (`sum(log_scale)` from the E-step's own forward pass *is* `log_likelihood`), that the convergence threshold is scaled to the objective, and that a converged fit stops before the iteration cap.
- `bench_regime_nowcast` in `scripts/bench_systemic.py`: the Student-t regime nowcast at T=250 and T=1 000 -- the one hot path on the *prediction* path rather than the scenario path. `docs/LANGUAGE_STRATEGY.md` embeds the numbers, and that document's own rule is that they come from this script.
- Property-based tests (`backend/tests/test_property_based.py`, new
  `hypothesis` dev dependency): the numerical invariants of the three
  load-bearing modules swept over generated input domains instead of
  hand-picked examples. Fractional differencing: the exact causal prefix
  identity, weights as analytic binomial coefficients, the level residual of
  a truncated window shrinking monotonically with the threshold, and
  linearity. Eisenberg–Noe clearing: payments bounded by nominals with the
  default mask exactly matching the final shortfall, endowment monotonicity
  (more capital never reduces any payment), degree-one homogeneity, and the
  solvency/empty-network limits. Gaussian HMM: log-space forward–backward
  checked against brute-force enumeration of every hidden path with an
  independent density formula, inference invariance under state
  relabelling, EM likelihood monotonicity, and Student-t fit sanity. Runs
  are deterministic (`derandomize=True`).

### Changed
- `GaussianHMM._fit_once` no longer runs a **second forward pass after every M-step**. It did so only to record the updated parameters' likelihood, but `_forward` already returns the per-step normalisers and their sum is `log p(X)` under the parameters that produced them -- the identity was sitting in `_forward`'s own docstring. The parameters are now scored once, after the loop, which is the only place the `history[-1] == log_likelihood(returned parameters)` invariant needs it. Measured with `scripts/bench_systemic.py --reps 6`: the production regime nowcast (`StudentTHMM(n_states=2)`, T=1 000) **5.264 s -> 3.349 s (1.57x)**, T=250 **1.401 s -> 0.842 s (1.67x)**, and the HMM/Student-t/property-based suite **76.3 s -> 44.3 s**. The final log-likelihood is **bit-identical** (-3618.940508 before and after) and so are the returned parameters. `history[:-1]` now records the likelihoods *entering* each M-step, a one-iteration lag that leaves `np.diff(history)` the same sequence of EM improvements the monotonicity tests assert on; the improvement that trips the convergence test is recorded before the break rather than discarded by it.
- The EM convergence test is **scaled to the objective** (`tolerance * max(1, |log-likelihood|)`) instead of absolute. The objective is summed over `T` observations, so a fixed 1e-6 means a relative tolerance of ~1e-9 at T=1 000 and tightens further with series length and with the units the data is expressed in. **Recorded honestly as a latent defect closed, not as a speedup:** on every dataset tried -- Gaussian and Student-t, T=250 to T=20 000, random walks and well-separated mixtures -- the absolute test also converged, so this changes no measured number. What it removes is a scale-dependence that would bite on a longer series or a change of units.
- `docs/LANGUAGE_STRATEGY.md` **restored**. It was deleted by `0ecd76f` ("Document language strategy and migration plans"), a commit whose entire diff was 85 deletions of this file, while `docs/README.md` kept indexing it and `scripts/bench_systemic.py` -- added by `8dff9e2` so the document's numbers could be re-measured rather than trusted -- was left in the tree with nothing pointing at it. Restored from `8dff9e2`, re-benchmarked, and extended with the regime-nowcast measurement and with the record of an external four-language migration proposal that was declined on evidence.
- `README.md` architecture block: the two duplicated ML sections are one, and the TimescaleDB/Redis bullets misfiled under "ML (PyTorch)" are back under Storage. `hidden_markov` promoted to `REQUIRED_REACHABLE` in the reachability census, per that file's own instruction to promote a wired capability rather than leave it unlisted.
- Declined on measurement, and recorded so it is not re-proposed: **capping `max_iterations` for the regime nowcast.** It is the obvious 4x, but across 12 series x 4 caps, reducing 100 -> 15/25/40 **flipped the returned regime label in 3 of 48 cases**. That label is the input to `NetworkQualityGate`, which fails closed on an unseen regime, so a cap that moves labels changes which predictions are blocked. Also declined: porting the loop to Rust, per the binding decision rule in `docs/LANGUAGE_STRATEGY.md` -- a port of the pre-fix loop would have been a fast implementation of a redundant forward pass. The lever that remains is batching the independent per-source fits into one `(n_sources, T, K)` recursion; that is a structural change to `_predict_single`'s loop and belongs in its own change with a label-equality test.
- `backend/Dockerfile`: `CUDA_VISIBLE_DEVICES` is a build `ARG` (image
  default unchanged: `0`) instead of a baked-in `ENV`. The hard-coded value
  silently overrode the `count: all` device reservation of
  `docker-compose.gpu.yml`, so the overlay now passes the arg through
  (defaulting to `all` to match its reservation) and `.env.example`
  documents the variable.

### Removed
- The dead Toto-2.0 weights mount from `docker-compose.yml`
  (`BEACON_MODEL_HOST_DIR` with a one-developer machine as its default,
  `BEACON_MODEL_DIR`, and the read-only `/models` bind). The encoder stack
  it fed was deleted in the 2026-09 hygiene round (census `REMOVED`
  register) and nothing in the runtime read the mount; the compose comment
  and `docs/deployment.md` record what returns with a foundation encoder if
  one is ever wired. The deployment verification snippets now construct the
  deterministic `HashedFallbackEncoder` instead of the deleted
  `TotoEncoder`, and the deferred ledger in `docs/README.md` gains the
  open proposals (BoE, OpenFIGI, EBA risk dashboard,
  `docker-compose.simple.yml`) with the precondition each waits on.

### Fixed
- **Frontend CI has been red on every run since `46ea089`**, on `main` and on every
  branch cut from it — including #53, #54, #55 and #56, which all merged with the
  check failing. That commit rewrote `Help.jsx` and left three assertions in
  `full-frontend.spec.js` describing the page it replaced: the title changed from
  "Help Center" to "Help", and "Popular walkthroughs" and "Ask Beacon Support"
  were deleted with the marketing content they belonged to. The spec now asserts
  what the page actually says — including "Known limitations" and its pointer at
  `docs/QUANT_REVIEW_2026-09.md`, which is the point of the rewrite — and asserts
  the removed content stays removed.
- **"Help Center" survived the Help rewrite in four places** -- the Header menu,
  `Breadcrumbs`, the onboarding tour and the Settings pointer -- while the
  Sidebar and the page itself said "Help". Aligned on "Help", the page's actual
  title, so the breadcrumb and the nav no longer disagree with the heading they
  lead to. Found while verifying the e2e fix rather than by looking for it.

- **The e2e suite depended on the network.** `index.html` links a Google Fonts
  stylesheet and `src/styles/index.css` `@import`s the same URL, so every page
  load made live third-party requests that `apiMocks.js` did not cover — it
  mocked `basemaps.cartocdn.com` and `**/api/**` and nothing else. Because the
  spec fails the test on *any* console error, a font request that stalled or
  failed turned an unrelated assertion red and reported the failure wherever the
  test happened to be standing. Both hosts are now served locally: an empty
  stylesheet and a 204 for the font files. No assertion in the suite measures
  typography, so glyphs falling back to the local stack costs nothing.

- **A fresh database could not be migrated at all.** `003` is the root revision
  and added columns to `data_sources`, which `baseline_core_001` creates five
  revisions later, so `alembic upgrade head` on an empty database failed with
  `UndefinedTable: relation "data_sources" does not exist`. backend and
  celery-worker each ran it from their entrypoints, so both restart-looped -- 64
  restarts observed on a real deployment -- while `docker compose ps` reported
  `Up`, because both containers were up and neither had ever served a request.
  The released image was not installable on a clean volume.
- **A legacy database could not be migrated either.** `init_db()` called
  `Base.metadata.create_all()` on every API boot, PostgreSQL included, so an
  app-built database had every table and no `alembic_version`; the next
  `upgrade head` replayed the chain over an existing schema and failed with
  `DuplicateColumn` / `DuplicateTable`. `init_db()` is now called only for
  SQLite, and on PostgreSQL the schema has exactly one owner: the compose
  `migrate` service.
- **`notifications` had two different columns depending on its history.**
  `20251107_152125` created `metadata`; `backend/models/notification.py:46` and
  `backend/schemas/notification.py:20` have always declared `extra_data`. A
  `create_all` database got the model's column and a migrated database got one no
  ORM query references, so any notification write touching `extra_data` failed
  with `UndefinedColumn` on a migrated-from-empty database. Found by comparing
  the two histories rather than reading either; the notification route tests run
  on SQLite built by `create_all`, which was the path that happened to be
  correct. `notifications_extra_data_001` renames it where the wrong name landed.
- **The backend image could not be built.** Both Dockerfiles ended with
  `COPY backend/entrypoint.sh` while compose built them with `context: ./backend`,
  so the source resolved to `backend/backend/entrypoint.sh`. Added by `c03f4af`;
  nothing caught it because the image-building workflow is manual-only and states
  that consequence in its own header. `alembic.ini` was never in the image either
  -- it lives at the repository root, and alembic resolves both it and
  `script_location` against the working directory. The context is now the
  repository root and `alembic.ini` is copied explicitly.
- **Two containers raced to migrate.** `migrate` is now a one-shot service
  (`restart: "no"`) that must exit 0; backend and celery-worker set
  `BEACON_RUN_MIGRATIONS=0` and depend on it with
  `service_completed_successfully`. A migration failure stops the stack with a
  readable error instead of presenting as a backend that will not answer.
- **`frontend` waited on a *started* backend, not a working one**
  (`depends_on: [backend]`), which is what produced a healthy nginx serving the
  SPA in front of an API that reset every connection. It now waits on
  `service_healthy`, against a healthcheck the backend did not previously
  declare.
- **celery-worker was a second image**, so a GPU build downloaded the multi-GB
  CUDA torch wheel twice into two layer sets -- 17.5 GB of BuildKit cache on a
  single host -- and the two could drift, leaving the worker running different
  code from the API it takes jobs from. All three services share
  `${BEACON_BACKEND_IMAGE:-beacon-backend:latest}` and only `backend` builds.
- **`CUDA_VISIBLE_DEVICES=all` hid the GPU from PyTorch.** `all` is valid for
  `NVIDIA_VISIBLE_DEVICES`, which the container runtime reads; torch parses
  `CUDA_VISIBLE_DEVICES` as a device list, matches nothing, and reports
  `torch.cuda.is_available() == False` in a container that can see the GPU. The
  image baked `all` in and the gpu overlay passed it through. The two are now set
  separately and documented as not interchangeable.
- **The postgres healthcheck hardcoded `beacon_user` / `beacon_db`**, so setting
  `POSTGRES_USER` or `POSTGRES_DB` in `.env` made postgres permanently unhealthy
  and hung the whole stack on a database that was fine. It now interpolates both.
- `container_name` removed from all five services: a fixed name collides with a
  second checkout, release or compose project on the same host, and service DNS
  never needed them.
- `.dockerignore` was listed in `.gitignore` under "# Docker" since the original
  restructure, which is why the repository never had one. It is build
  configuration, not an artefact, and an untracked one makes a build reproducible
  only on the machine that wrote it.

- `README.md` advertised two things the tree does not contain. "Gaussian and Student-t HMM regime detection *(not wired)*" -- it is wired: `_regime_label` fits a two-state Student-t HMM per source at `prediction_engine.py:1005`, which is what the mixture-of-experts census disposition means by "the live regime label now exists". And "Toto 2.0 foundation-model node encoder: loadable from a local model folder, and constructed only by `backend/scripts/compare_encoder_sizes.py`" -- that script and the whole encoder dependency train were deleted in the 2026-09 hygiene round and are recorded in the census `REMOVED` register. `hidden_markov` was also in *neither* census registry despite being reachable, so nothing would have failed had it been unwired.
- `scripts/release.py` annotated `fail()` as `"NoReturn"` with a `# type: ignore[name-defined]` instead of importing it, so the advisory ruff step in Backend CI reported F821 on every run -- one of the two errors that step was reporting on main. `NoReturn` is now imported and the suppression is gone; `ruff check backend scripts --select E9,F63,F7,F82` is clean.

- `foundation_encoders.__all__` still exported `resolve_model_dir` and
  `local_model_path` after the 2026-09 hygiene round deleted them, so a
  star-import of the module raised `AttributeError` (the advisory ruff CI
  step had been reporting the F822 all along; `continue-on-error` kept it
  off the merge gate). The orphaned model-tree constants that described the
  deleted weight-loading machinery went with them.

## [3.2.0] - 2026-09-15

### Added
- `POST /api/v1/network/estimate`: estimated bilateral networks as a
  production scenario input. Maximum-entropy **and** minimum-support
  completions of declared aggregate interbank marginals bracket the unknown
  structure; Eisenberg–Noe clearing is propagated over marginal-preserving
  structure-bootstrap draws with percentile bands of total shortfall and
  default count, and the estimator's caveat travels with every response.
  Estimates are never persisted to the exposure store
  (`persistence: "not_stored"`), so an estimate can never be mistaken for an
  uploaded observation.
- Keyless FRED access: indicator fetches and the connection probe fall back
  to the `fredgraph.csv` endpoint when no API key is configured, with typed
  `FredKeylessError` for renamed/retired series and unparseable payloads;
  `.` gaps are dropped, never zero-filled. Verified live against FRED.
- Provenance disclosure: `GET /api/v1/data-sources/disclosure` serves, per
  feed, the publisher, a closed-vocabulary provenance class, what it
  provides, access facts derived from each plugin's own declaration, and
  live configured/enabled/catalogue counts for this deployment, plus the
  platform data policy and the inferred-inputs register. The Data Sources
  page renders it and the create-form plugin options now come from the
  runtime registry instead of a hand-maintained list.

### Changed
- Reachability census: `backend.modules.risk.network_estimation` moved from
  `KNOWN_UNREACHABLE(wire)` to `REQUIRED_REACHABLE`.
- Plugin registry integrity: `fdic`, `cftc_cot` and `nyfed` were absent from
  the loader list and never reached the runtime registry, so no data source
  could select them; the FDIC plugin additionally imported a base module
  that never existed in git history while the UI advertised it as enabled.
  All 17 plugins now register, and a guard test fails when a concrete plugin
  class is defined but unregistered.
- FDIC plugin rewritten against the live BankFind Suite API (fields and
  filter syntax verified by probe on 2026-09-15); only verified fields are
  served, undeclared fields raise `FDICFieldError` instead of being guessed
  at a supervisory API.
- The Data Sources page reports the real most-recent fetch timestamp instead
  of a fabricated "2 hours ago".
- Stooq rejected as a keyless feed on evidence: its CSV endpoint sits behind
  an anti-bot challenge (HTTP 200 + HTML, probed 2026-09-15); the decision
  is recorded in `docs/README.md` rather than shipping a dead plugin.

### Fixed
- `scripts/release.py` now syncs both version fields of
  `frontend/package-lock.json`, and `scripts/check_versioning.py` fails on
  lock drift; the lock had been stuck at 3.0.0 while `package.json` moved to
  3.1.1, so every `npm install` produced an uncommitted diff.

## [3.1.1] - 2026-09-15

### Removed
- Four closed review logs: `docs/G_SIB_BUILD.md`,
  `docs/EXECUTIVE_REVIEW_REMEDIATION.md`, `docs/data_connectors.md`,
  `docs/FIFTH_ROUND_RESPONSE.md`. Every item in them is merged; the still-true
  facts live in the reachability census and the `QUANT_REVIEW_2026-09.md`
  register, and the reasoning that still governs decisions is summarised in
  `docs/README.md` ("Audit history and standing decisions").
- `configs/timescaledb/timescale_setup.sql`: a drifted second copy of the
  migration DDL (it lacked the three baseline tables). The Alembic migrations
  are the only source of schema truth; the migration's own error messages now
  state the manual step instead of pointing at the copy.
- `configs/scenario_library.json`: zero references from any code, test,
  workflow or document.

### Changed
- `docs/api.md` authentication section: the stale "there is none" claim
  replaced with the actual optional `BEACON_API_TOKEN` bearer gate, its scope
  and its limits.
- `docs/README.md`: index rebuilt around the live set (RUNBOOK, VERSIONING and
  LANGUAGE_STRATEGY were missing from it); dead logs moved to the Removed
  table with reasons.
- Dead cross-references to the deleted logs removed from `README.md`,
  `docs/api.md`, the `federated.py` docstring and the reachability census
  docstring; the census now cites only itself.
- `docs/images/` screenshots audited and **kept**: regenerated after the
  rebrand, they show the current UI.

## [3.1.0] - 2026-09-15

### Added
- Container entrypoint runs `alembic upgrade head` before the API/worker starts;
  `baseline_core_001` reconciles the core tables; CI renders the chain offline.
- SSRF fetch policy for the custom-API plugin (https-only default, refused
  ranges, resolved-address inspection, operator allowlist).
- Pipeline-stage tests (formatter/cleaner/collector retry), release-tooling
  guards, dashboard/panel docs and a real Help reference page.

### Changed
- Analyzer accuracy is now `None` (unmeasured) instead of a hand-rolled weight
  blend; validator anomalies propagate as a measured integrity count.
- Report pipeline carries no legacy channel aliases: `model_score_report`
  with semantics, funding as explicit `not_measured`, institutional profiles
  without invented narrative.
- `FMP_API_KEY` reaches the containers; deployment docs no longer reference
  the removed Toto stack.

### Fixed
- The README's migration procedure no longer crashes on booted databases
  (unguarded `create_table`); neither schema tool was a complete source of
  truth before `baseline_core_001`.

### Added
- Frontend design system ("field report"): warm-paper surfaces, pine brand,
  moss→ochre→rust→clay risk scale, serif display type, monogram chips, new
  beacon mark and favicon; reference screenshots under `docs/images/`.
- `ErrorBoundary` around the routed page: a failing view degrades to a quiet
  panel instead of blanking the shell.
- Dashboard System Status card backed by `GET /api/v1/system/status`
  (measured CPU/memory/disk/GPU; unreachable backend renders *Unreachable*).
- Unified API client `frontend/src/utils/apiClient.ts` — the first TypeScript
  module, strict-checked by `npm run typecheck` and a CI step.
- Build-version stamp (`__APP_VERSION__`) in the sidebar footer; version and
  git revision exposed by `/api/v1/system/status`.
- Versioning system: root `VERSION`, this changelog, `docs/VERSIONING.md`,
  `scripts/release.py`, `scripts/check_versioning.py` and a CI guard.
- `scripts/bench_systemic.py` and `docs/LANGUAGE_STRATEGY.md`: measured
  hot-path benchmarks and the decision rule for language changes.
- Split-conformal calibration design and event-labeller plan (Phase 2) in
  `docs/QUANT_REVIEW_2026-09.md`.

### Changed
- Training path correctness: scheduler crash under pinned torch 2.14 fixed;
  empty validation splits now fail loudly instead of freezing model selection
  at epoch 0; validation/test splits reuse the training split's normalization
  statistics; chronological, data-derived train/val/test windows replace the
  hardcoded 2023–2024 defaults and the positional `iloc` cut.
- Pipeline scoring fails closed without a trained checkpoint; `_predict`
  normalizes per source with checkpoint statistics and never strides source
  seams; risk levels are reported as `uncalibrated` with explicit semantics
  instead of thresholding standardized output on a 0–100 scale.
- Backtest ground truth joins on `predicted_row_offset` (the row a score
  predicts), never on the window-end row.
- Explainability endpoints serve an honest transparency card: no compliance
  claims, explicit not-computed/not-calibrated statuses, no percentage
  conversions, absent measurements stay null.
- Results reports list unmeasured risk channels as `not_measured` instead of
  rendering NaN factors.
- Risk map moved to a light basemap with the warm palette; legend documents
  the bands and the *uncalibrated* state.
- README rewritten as the professional project description;
  `docs/frontend.md` gained the design-system specification.

### Removed
- Toto 2.0 encoder wrapper, its weights-resolution machinery, the
  `compare_encoder_sizes.py` benchmark and the `toto-2` dependency train
  (implemented and tested but never constructed by a production path, while
  every image paid gigabytes). Decision record: REMOVED register in
  `backend/tests/test_reachability.py`.
- Committed prediction artefacts (`data/predictions/*.parquet`).
- Five duplicate fetch helpers in the frontend (one lacked the 204 fix).
- Emoji iconography; hardcoded "v3" footer; fabricated dashboard deltas and
  static system-status badges; the `stability_score` pseudo-metric.

### Fixed
- Header profile button referenced an undefined state setter (crash on click).
- `useNotifications` fetch helper lacked the 204/no-body guard.
- Data Quality completeness card rendered `undefined%` for absent payloads.

## [3.0.0] — baseline (untagged)

State of the platform before the versioning system existed: six-stage data
pipeline with fail-closed quality gate, Eisenberg–Noe multiplex clearing,
coupled fire-sale and liquidity-spiral solvers, Basel III translation,
walk-forward/CPCV backtesting, reachability census, 2D risk map. Recorded as
the baseline from which SemVer counts; no tag was cut for it.
