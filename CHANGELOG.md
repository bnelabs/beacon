# Changelog

All notable changes to the BEACON platform. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) as
specified in [`docs/VERSIONING.md`](docs/VERSIONING.md). The version of
record is the root `VERSION` file; `scripts/release.py` moves the
`[Unreleased]` block here when cutting a release.

## [Unreleased]

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
