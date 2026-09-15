# Changelog

All notable changes to the BEACON platform. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) as
specified in [`docs/VERSIONING.md`](docs/VERSIONING.md). The version of
record is the root `VERSION` file; `scripts/release.py` moves the
`[Unreleased]` block here when cutting a release.

## [Unreleased]

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
