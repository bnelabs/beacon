# Changelog

All notable changes to the BEACON platform. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project
adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html) as
specified in [`docs/VERSIONING.md`](docs/VERSIONING.md). The version of
record is the root `VERSION` file; `scripts/release.py` moves the
`[Unreleased]` block here when cutting a release.

## [Unreleased]

### Added
- **The v5 early-warning run executed — family verdict NO (2 of 11), and the
  line remains parked as its own protocol declared.** One clean run under tag
  `prereg-early-warning-v5` (tag → fetch → evaluate; a single attempt, run
  detached under the v4 attempt-1 lesson; zero retries; 1h50m on 2 CPUs; key
  grep-verified absent from every committed file; licence screen refused the
  ICE BofA series pre-download again; CISS's declared keyless attempt recorded
  HTTP 400, not substituted). The wider family delivered exactly what the
  probe projected: **11 testable indicators across four tracks and three
  publishers** (4 daily, 3 weekly, 3 monthly, 1 quarterly). **Passed: 2 of
  11 — `FRED_STLFSI4` and `FRED_DCOILWTICO`, both via the *frozen* hazard
  logit.** STLFSI4 reproduced its v4 pass byte-identically on a fresh fetch
  (AUC 0.9223, AP 0.3836, p=0.0010, median lead 2.0 weeks ≈10 business days,
  FA 0.483/quiet-year); DCOILWTICO (WTI crude, daily) is the record's second
  pass and first on the daily track: AUC 0.813, AP 0.309, median lead 14.5
  business days, FA 1.14/quiet-year, strictly above both baselines, p=0.0010,
  Holm-surviving across the 44-pair pool. Two of eleven is published as fact
  and NOT upgraded into a system claim: the frozen family rule requires at
  least half (≥6), so under the outcome handling frozen before the run the
  line **remains parked with a five-run record; there is no planned v6** —
  any resumption is again an owner decision plus a new protocol with new
  recorded axes. Findings published as measured: the frozen hazard logit is
  the only scorer that has ever passed (2 of 2 passes; rolling refits again
  rescue nothing, and the rolling hazard passes no indicator); the monthly
  track starves the lead criterion (KCFSI reaches AUC 0.917 but detects
  nothing within its 2-month max_lead; FEDFUNDS' p=0.031 does not survive
  Holm at the wider pool); NFCI is significant (p=0.0010) yet persistence
  still beats it — the weekly composite's lift, not its significance, is the
  binding gap; the quarterly credit gap reproduces v4 exactly (3 events,
  under-powered by construction); T10Y3M's frozen TAN misses the FA ceiling
  by 0.2 for the THIRD consecutive run (4.202, identical). Reproducibility
  held a fifth time and at its strongest: **all 20 shared v4 pairs (5
  indicators × 4 scorers, frozen AND rolling) are byte-identical on fresh
  fetches with new SHA-256s.** README gate updated to the five-run record;
  execution log carries the attempt table, per-indicator timings, fetch facts
  and the reproducibility diff.
- **Early-warning pre-registration v5 — the owner-initiated wider family.**
  v4 published family NO (1/5) with the record's first criteria-passing pair
  (`FRED_STLFSI4` × frozen hazard logit) and confirmed the standing
  diagnosis: the constraint is the family, not the machinery. Its outcome
  handling recorded "there is no planned v5" — a statement about the record,
  not a lock; every version since v1 says any resumption is owner-initiated,
  a new protocol, frozen before its run, and the owner initiated this one
  (2026-09-18) with one explicit aim: a wider family from multiple sources.
  v5 changes the family and adds the monthly track it needs; **no grading
  criterion changes** — the four frozen criteria, labeller quantile, windows,
  model config, seed protocol, baselines, alarm point (q98), permutation
  test, Holm level, family rule and single-run rule are identical to v1–v4
  by shared code, pinned by `test_prereg_v5.py` beside the untouched v4
  pins. Family (probe-first, criteria declared before any request —
  `docs/probes/prereg_v5_source_probe.md`): daily `FRED_DCOILWTICO` (EIA,
  1986–, GREEN); weekly `FRED_MORTGAGE30US` (Freddie Mac, 1971–, GREEN,
  copyright line recorded) and `FRED_NFCI` (Chicago Fed, 1971–, GREEN);
  monthly `FRED_FEDFUNDS` (1954–), `FRED_UMCSENT` (1952–, direction −1,
  citation recorded) and `FRED_KCFSI` **reassigned weekly→monthly** at its
  measured ~31-day cadence (v4's weekly refusal is the evidence; no
  resampling then, none now); quarterly `BIS_CREDIT_GAP_US` revalidated
  GREEN (274 rows, 1957-Q4–2026-Q1). Probe-RED excluded pre-fetch:
  `FRED_DTWEXBGS` (history starts 2006 — under one year of pre-2007
  training data) and the NY Fed recession probability (the documented URL
  serves HTML; no structured transport in the plugin zoo — recorded, not
  substituted). All five new directions declared in the semantics registry
  with literature rationale BEFORE any fetch. Declared pre-run consequences:
  the wider family makes the family rule HARDER (~11 testable ⇒ a system
  claim needs ≥6 full passes); Holm feasibility at the 44-pair pool checked
  against published numbers (min attainable p 0.001 × 44 = 0.044 ≤ 0.05);
  monthly alarm arithmetic (q98 ⇒ ~0.24 alarms/yr ⇒ the FA ceiling cannot
  bind; lift and lead bind) and the stricter monthly lead floor (1 step ≈ 21
  bd vs the 10-bd intent) are declared, not hidden. New mechanics are
  data-availability only: the monthly `TRACK_PARAMS` row (intent
  translation pinned by test), the per-track coverage expectation at the
  track's own cadence, and the v5 protocol entry. Outcome handling frozen
  before the run: PASS ⇒ the README gate moves carrying these numbers;
  FAIL ⇒ the line remains parked with a five-run record and there is no
  planned v6. `docs/prereg/early_warning_v5.md` + `configs/event_eval_v5.yaml`,
  to be tagged `prereg-early-warning-v5` before the single run.
- **The v4 early-warning run executed — family verdict NO (1 of 5), and the
  line remains parked as its own protocol declared.** One clean run under tag
  `prereg-early-warning-v4` (tag → fetch → evaluate; attempt 3 is the run of
  record — attempts 1–2 died pre-metric, one to an environment process-group
  kill and one to an executor defect, both documented with diffs in the
  execution log with zero metrics computed or observed; zero retries
  thereafter). Five testable indicators across three tracks: the daily trio,
  weekly `FRED_STLFSI4`, and quarterly `BIS_CREDIT_GAP_US` (1957-Q4 onward,
  keyless SDMX, licence GREEN with attribution) — the credit-gap family the
  recorded axes named, admitted at last. Skips all by declared rule: KCFSI
  refused by the weekly track (FRED serves it monthly — no resampling), SOFR
  (coverage), HY OAS (licence, refused pre-download), CISS (recorded, not
  substituted). **The record's first criteria-passing pair:** STLFSI4 via the
  *frozen* hazard logit — AUC 0.9223, AP 0.3836, median lead 2.0 weeks (≈10
  business days), 0.483 FA/quiet-year vs the ceiling of 4, strictly above
  both baselines, permutation p=0.001, Holm-surviving across the 20-pair
  pool. One pair of twenty does not meet the family rule (at least half of
  the tested family), so the claim gate stays closed and, under the outcome
  handling frozen before the run, the line **remains parked with a four-run
  record; there is no planned v5**. Findings published as measured: rolling
  refits did not rescue the daily family (T10Y3M's rolling TAN got worse —
  FA 4.20→5.37, lead 10.0→7.5 below the floor; T10Y2Y/VIX rolling ≈ frozen),
  closing that recorded axis; the quarterly credit gap was weak under this
  operationalisation (AUC 0.39–0.65, 3 labelled events, no detection within
  max_lead — under-powered by construction at quarterly resolution); the
  frozen hazard beat its rolling counterpart on the one passing indicator —
  the opposite of the v3 diagnosis' expectation, recorded as the finding it
  is. Reproducibility held a fourth time: all six frozen-scorer × daily pairs
  match v3's published numbers exactly on a fresh fetch (new SHA-256s in the
  manifest). README gate updated to the four-run record; execution log
  carries the full attempt table, defect diffs and provenance.
- **Early-warning pre-registration v4 — the owner-initiated resumption,
  testing exactly the two recorded axes.** v3's terminal clause parked the
  line and recorded what a resumption would carry: rolling refits (the
  discipline the frozen hazard logit's out-of-sample collapse diagnosed) and
  weekly/monthly tracks admitting the credit-gap family (the literature's
  best EWS variables, which a frozen daily step could never admit). v4 tests
  those axes and **changes no grading criterion** — the four frozen criteria,
  labeller quantile, windows, model config, seed protocol, baselines,
  permutation test, Holm level, family rule and single-run rule are identical
  to v1–v3 by shared code, pinned by tests (`TRACK_PARAMS["daily"]` restates
  the frozen constants and `test_prereg_v4.py` asserts the equality). New
  mechanics, all declared pre-run: three tracks (daily/weekly/quarterly) with
  per-track step semantics translating the same design intent at each grid's
  coarsest granularity (weekly lead floor 2 steps ≈ 10 bd; quarterly 1 step
  ≈ 63 bd — stricter, declared not hidden); two rolling scorers
  (`tan_rolling`, `hazard_logit_rolling`) refit at every calendar-year
  boundary on the expanding window strictly before it, causality pinned by
  test, a window that cannot support a fit contributing declared absence
  rather than zeros; per-scorer grids with baselines recomputed on each
  scorer's own grid; the uniform q98 alarm point with per-track arithmetic
  from published facts (weekly/quarterly: the FA ceiling cannot bind — lift
  and lead bind, declared consequence); Holm pools all four scorers × tested
  indicators. Family: the daily trio as v2/v3, weekly STLFSI4/KCFSI
  (directions predate v4) with the declared CISS keyless attempt
  recorded-not-substituted, and quarterly `BIS_CREDIT_GAP_US`
  (`WS_CREDIT_GAP/Q.US.P.A.C.E` — the GAP variant, US private non-financial,
  1957-Q4 onward, keyless, licence GREEN with attribution), its registry
  direction (+1, credit boom = risk build-up) declared BEFORE any fetch. The
  BIS debt service ratio was probed fetchable but YELLOW (US history from
  1999-Q1 — ~32 pre-2007 quarters cannot honestly train the declared
  architecture) and is **excluded pre-fetch** under the probe's declared
  disposition rule. Transport: keyed FRED (env-only, redacted) + keyless BIS
  SDMX CSV (quarter-end date convention; a payload mixing dimension values is
  a format-drift refusal); the licence screen extends to BIS — the live terms
  page must show its permission sentence or the series is refused as
  `licence_unconfirmed` (the BoE-404 precedent: unconfirmed is never
  assumed). Outcome handling frozen before the run: pass → the README gate
  moves carrying these numbers; fail → the line stays parked with a four-run
  record and there is no planned v5. Probes executed criteria-first and
  recorded: `docs/probes/prereg_v4_source_probe.md` (BIS GREEN / DSR YELLOW /
  CISS RED with verbatim evidence) and `docs/probes/pra_endpoint_probe.md`
  (**YELLOW**: aggregate PRA-sourced releases exist; bank-level exposures are
  supervisory-confidential — the operator-onboarding route is the only path;
  this closes the last open action of the BoE probe's YELLOW path).
  `docs/prereg/early_warning_v4.md` + `configs/event_eval_v4.yaml`, to be
  tagged `prereg-early-warning-v4` before the single run (tag → fetch →
  evaluate, the v3 sequence).

### Fixed
- **A test module's parent-only delete reddened the deep suite two modules
  away.** The deep run on `main` (`e78f6ba`, 2026-09-22) failed
  `test_sync_scheduler.py::test_enqueue_creates_the_same_job_a_human_does` with
  `assert [76, 87] == [87]` — 1 failed / 2124 passed — while all eight pipeline
  merges (#102–#109) had passed every pre-merge gate and every targeted module
  run. Cause: the new `test_data_quality_routes.py` (#103) clears the writers
  its endpoints aggregate, correctly, because those endpoints aggregate globally
  — but it deleted `DataSource` rows an earlier module had seeded **without the
  rows pointing at them**, and SQLite hands freed parent ids to the next
  module's INSERT. `test_sync_scheduler`'s fresh source then selected catalogue
  items it never created, and failed as if the scheduler had chosen the wrong
  series. The same fixture deleted `PipelineJob` while leaving `EngineJob` and
  `ResultJob` behind — the identical defect, two lines apart. Mitigation: both
  wipes clear children before parents, and every child of a parent they take
  (`DataCatalogueItem`, `Asset`, `EngineJob`, `ResultJob`); `test_sync_scheduler`
  now states its precondition — the source id it was handed is fresh — so a
  future leak names itself instead of reading as a product bug; and
  `conftest.py` enforces the cleanup convention it already documents, sweeping
  every registered FK in `Base.metadata` at the end of each run and failing the
  suite with the offending table pair named. One new test pins the invariant at
  the module that broke it. Reproduced locally in 3.5 s as the exact CI triple
  (`test_api_smoke` + `test_data_quality_routes` + `test_sync_scheduler`): red
  before the fix, green after — which is also the record of why targeted runs
  cannot see this class at all, and why "targeted pytest: N passed" on a
  pipeline PR proves less than it appears to.
- **CONTRIBUTING claimed a safety net that is not wired.** It said "deep suites
  run on merges to `main`"; `backend-tests.yml`, `frontend-e2e.yml` and
  `bundle-budget.yml` trigger on `schedule` and `workflow_dispatch` only, so
  eight pipeline merges landed on `main` under nothing but the sub-minute gates
  — and a reviewer who believed that sentence had no reason to dispatch the deep
  run. The text now says what the workflows do, and states the rule the
  two-tier design actually requires: a pipeline-touching change is proven by
  hand (`gh workflow run backend-tests.yml --ref <branch>`) or by the local full
  suite before it merges.
- **A cache-served "success" no longer silently clears a down feed's backoff
  (pipeline-review finding F9).** The HTTP layer's stale-on-outage fallback
  is a sound availability trade — but it made a collection where the
  provider was unreachable end-to-end indistinguishable, in telemetry, from
  a fresh fetch: `record_sync_success` cleared the failure streak (which
  *is* the scheduler's backoff) and stamped the source healthy while every
  row actually came from yesterday's cache. The fallback is now witnessable
  at three levels: `ResilientSession.stale_fallback_hits` counts serves (and
  the response carries `X-Beacon-Stale-Fallback: 1`); the collector reads
  the plugin's session after each fetch and records the item in
  `CollectionReport.degraded` — still *collected* (the data reached the
  pipeline), but flagged, and the flag travels in the job result; and
  `record_sync_success(..., degraded=True)` stamps
  duration/rows/last-successful but **keeps the failure streak and leaves a
  note beside the source** — a degraded success is not evidence of provider
  health. The next genuinely fresh success clears both. Five tests pin the
  chain (counter + header on transport error and on persistent 5xx,
  collector flag, report wiring, scheduler streak semantics).
- **Per-item collection retries are bounded by wall time, not only by
  attempts (pipeline-review finding F8).** `_fetch_with_retry` stopped after
  3 attempts — but each attempt rides on the HTTP layer's own retries
  (`ResilientSession`: up to 4 urllib3 retries with backoff, timeouts up to
  30s each), so one catalogue item could spend ~7 minutes against a
  struggling provider while the beat tick enqueues every five and a
  multi-item source serialises behind it. Retries now also stop at
  `BEACON_FETCH_RETRY_BUDGET_SECONDS` (default 120, invalid values fall
  back with a warning): tenacity evaluates stop conditions *between*
  attempts, so a legitimately long single fetch (ECB paging) is never cut
  off mid-flight — it is further retries, past the budget, that stop. Two
  tests pin the budget and the malformed-override fallback.
- **`as_of_join`'s production status is recorded, not left to rot
  (pipeline-review finding F7).** The point-in-time module's join primitive
  is implemented, exported and covered by `tests/test_pit.py`, but no
  production path calls it: `PITStore`/`Observation` are wired through the
  bilateral-exposure store, while `as_of_join` waits on the event-metrics
  feature attach. The reachability census walks modules, not functions, so
  the module-level "wired" verdict hid the function-level gap — the exact
  silence the census exists to prevent, one granularity down. The module
  docstring now carries the status and a `decide` disposition (wire it into
  the backtest feature path, or delete it), and the census entry for
  `backend.modules.data.pit` names it.
- **The quality gate's KPSS scan now respects panel grain (pipeline-review
  finding F5).** #100 and #101 fixed entity grain in the validator and the
  formatter, but `_stationarity_checks` still ran KPSS over the raw value
  column: for a panel frame (interbank edge tables, per-bank features) that
  tests an interleaved mixture of entity series — a statistically
  meaningless verdict, harmless while stationarity is report-only and
  blocking-legitimate data the moment a deployment sets
  `require_stationarity=True`. The scan now groups by the *same* identity
  registry the validator and formatter use (extracted to
  `validator.identity_columns`; the formatter's duplicate copy delegates),
  date-orders values within each entity, and assesses up to
  `KPSS_PANEL_SERIES_CAP = 25` entity series — a deterministic equispaced
  sample of the sorted keys when a panel is wider, with the check detail
  naming what it actually saw ("assessed 25 of 4,548 entity series…") and
  the offending edges. Per-entity degenerate series (one frozen edge) are
  counted, not failed — the whole-column degeneracy check and the
  declared-event exemption already cover a payload where nothing moves.
  Scalar frames report exactly as before. Six tests in
  `test_stationarity.py` pin the contract (per-entity detection, row-order
  insensitivity, deterministic sampling, blocking policy per entity, frozen
  edge counted, scalar detail unchanged).
- **The validator's integrity findings are enforced at last — the
  orchestrator's `critical_errors` branch was dead code (pipeline-review
  finding F4).** `ValidationReport.critical_errors` was declared and never
  incremented by anything, so the orchestrator's "filter out datasets that
  failed critical validation" branch was unreachable — and its filter
  (`not v.empty`) dropped frames the collector already refuses rather than
  the offenders. Duplicate timestamps (ambiguous: which value is right?) and
  future timestamps (look-ahead at ingest) are integrity breaches by the
  validator's own contract; the report now names the offending datasets
  (`critical_datasets`, with per-dataset `errors` entries), and the
  orchestrator excludes exactly those datasets, alerts the operator through
  the data-quality notification sink, and fails the run only when nothing
  remains — a reduced panel with an alert, never a silent one. Statistical
  findings (outliers, scale breaks, stale runs) stay warnings by design:
  they are evidence about a series, not ambiguous rows. Five tests pin the
  contract in `test_validator_anomalies.py`.
- **`POST /api/v1/pipeline` runs on the worker pool instead of inside the
  API process (pipeline-review finding F3).** The route executed the whole
  DATA → ENGINE → RESULTS run as a FastAPI BackgroundTask: no queue
  visibility, no worker supervision, the entire run lost silently on an API
  restart, and torch stages competing with request handling — while
  `scheduling.py` could claim "exactly one collection path" only because
  this second path was invisible to it. The dispatch is now the
  `run_pipeline` Celery task (a thin transport wrapper; the stage logic
  stays in `_execute_pipeline`, which `test_pipeline_integration` exercises
  directly), and a dispatch that cannot reach the broker marks the
  PipelineJob FAILED with the reason instead of leaving it pending forever —
  a queued run that never queued must not read as health.
  `backend/tests/test_pipeline_route_dispatch.py` pins both behaviours.
- **The Data Quality page read a table the production path never writes
  (pipeline-review finding F2), and two of its own numbers were vacuous.**
  All three `/api/v1/data-quality/*` endpoints took quality scores from
  `DataJob ⋈ PipelineJob` — rows only `POST /api/v1/pipeline` creates, and a
  route the frontend never calls. Every real collection (jobs API, manual
  sync, scheduler) stores the gate's verdict in `Job.result` and its source
  link in `Job.parameters.data_source_id`, so the page showed zeros on any
  deployment collecting through the documented path while collections
  succeeded. The endpoints now read **both** writers through one evidence
  helper (JSON parsed Python-side for SQLite/PostgreSQL parity): `stats`
  aggregates both, `sources` links production jobs to their source via the
  parameter the scheduler has always written (its "jobs are not currently
  linked" comment was stale), and `trends` buckets both by day and counts
  failed collections from the production path too. Two adjacent honesty
  defects fixed with it: the `low_quality` threshold was 0.5 against 0–100
  scores — nothing was ever counted, ever (failure class "infrastructure
  lie"); it is now the gate's certification floor, read from
  `QualityPolicy.min_quality_score` instead of restated. And
  `avg_completeness` was multiplied by 100 although both writers store the
  gate's 0–100 percentage and the frontend renders the value verbatim — a
  97% panel displayed as 9700%. Freshness maths now normalises SQLite's
  naive timestamps (`_ensure_utc`, the precedent `pipeline.py` and
  `scheduling` already set) instead of raising `TypeError` off PostgreSQL.
  `docs/api.md`'s "Data-quality score" section described the removed
  `0.4/0.3/0.3` analyzer blend (finding F6, class "mislead"); it now
  documents the gate-owned composite, its weights and renormalisation, and
  what the endpoints read. `backend/tests/test_data_quality_routes.py` pins
  the contract (4 tests).
- **`indicator_observations` has a production writer at last — the README
  claimed one since 2026-09-17 and none existed (pipeline-review finding
  F1, class "mislead").** `record_observations` and its vintage-log append
  were exercised only by store tests while every real collection wrote
  parquet + job-result JSON and nothing else; the hypertable, its continuous
  aggregate and `observations_as_of` re-derivability were dead in
  production. `persist_observations` (in `tasks/job_tasks.py`, beside the
  other two persistence helpers) now runs in `run_data_collection` after the
  quality gate certifies the package: scalar indicator rows are upserted
  with publisher plugin type, catalogue code, region, the gate's quality
  score and the ingest job id, and every write appends its vintage. Panel
  and asset rows are skipped and counted — the (time, source, indicator,
  region) key would silently collapse them, and the exposure store owns
  network-shaped data; invalid rows and unmapped codes are skipped and
  counted, never zero-filled or invented; duplicate keys inside one payload
  collapse last-wins (one ON CONFLICT statement may not touch a row twice).
  Storage failure degrades to a warning like the other writers; the counts
  travel in the job result. README's storage bullet now names the writer.
  `backend/tests/test_observation_writer.py` pins the contract (6 tests).
- **Two pre-metric executor defects in the v4 runner, found and fixed before
  any result existed (diffs recorded in the v4 execution log).** (1) The BIS
  licence-line extraction recorded JSON-LD page furniture instead of the
  terms sentence (a loose `licen` pattern matched the page header); fixed and
  the fetch phase re-run in full before any metric — both fetches produced
  the same five testable indicators and the same four skips. (2) The
  per-scorer-grid path ranked rolling scorers against the primary grid's
  labels (`_score_card` closed over `events` instead of the grid it was
  handed): the weekly indicator raised a length-mismatch `ValueError` before
  any metric existed, and the mismatch was structural — every rolling grid
  differs from the frozen TAN's warm-up-truncated grid, so all five
  indicators were deterministically doomed. The attempt was terminated
  rather than burn 35 minutes producing five recorded infrastructure
  failures; the two-line fix ships with an end-to-end regression test that
  reconstructs the exact mismatch synthetically and pins criteria on both
  grids. `git diff prereg-early-warning-v4 HEAD` at the run touched only
  those hunks and their tests — no protocol constant, criterion, family
  entry, alarm rule or scorer spec changed (the YAML precedence clause
  covers the executor).
- **`docs/api-endpoints.md` regenerated after the 4.0.0 version bump.** The
  generated inventory embeds the application version; the release tooling
  does not regenerate it, so the 4.0.0 cut left it claiming v3.3.0 — invisible
  to the fast CI gates (the inventory check runs in the deep suite) and
  caught here by the first full-suite run after the release, before any
  nightly. One-line regeneration; the release checklist now carries the step,
  and the failure is recorded as ledger L-25 with the durable tooling guard
  deliberately deferred until the class recurs.

## [4.0.0] - 2026-09-17

### Added
- **`docs/FAILURE_LEDGER.md` — the failure & mitigation ledger, open to
  everyone.** Twenty-four confirmed failures in one place — the three-run
  early-warning record (including the parked verdict and the v2 protocol's
  unreachable-criterion incoherence), the ICE BofA licence violation and its
  withdrawal, the fabricated-scores API bug, the CI gates that lied (a suite
  that could not start, a budget gate permanently tripped and blind), the
  stranded v3.3.0 release — each with how it was detected, what it cost, the
  mitigation, its status, and an evidence pointer. Ledger rules are part of the
  document: an entry opens when a failure is *confirmed* (not when it is
  fixed), closes only when the mitigation is merged and verified, and nothing
  is silently deleted. The CHANGELOG records what changed; the ledger records
  what went wrong and what we did about it. Registered in the docs index and
  README.
- **`CONTRIBUTING.md` — the invitation and the contract for running, checking
  and extending BEACON in public.** The binding norms (freeze before you
  measure; one run, published unchanged; licence-screen before download;
  refuse, don't fabricate; claims point at code; credentials never live in the
  repo), the measured resource profile and exact gate commands (2 CPUs / ~1 GB
  RAM / CPU torch wheel), how to reproduce any tagged pre-registration run
  byte-identically with your own FRED key, how to share analyses with
  provenance (manifest + snapshot id + code tag; negative results explicitly
  welcome), the five issue classes we track (scoring bug, data/licence, claim
  drift, reproducibility failure, infrastructure lie) with required evidence,
  and the maintainer release checklist — whose step 4 ("push the tag") exists
  because v3.3.0 was stranded without it.
- **`docs/operator_series_onboarding.md` — the path for an institution's own
  series to join the platform.** The three-run pre-registered record
  established that public daily stress families are thin and that six
  registry codes (HQLA/LCR/NSFR/bank equity/FX swap basis/CDS) will never
  have a public source; they are the differentiator, and until now onboarding
  them was undocumented tribal knowledge spread across two plugins. The doc
  states the exact contracts — `csv` (`Date[,Indicator],Value` files, mount
  and sync cadence, absence-not-zero semantics) and `custom_api` (indicator
  endpoint shape, auth modes, and the round-seven SSRF guardrails as binding
  contract) — the already-declared stress directions per code, what the
  pipeline does next (quality gate, event labelling, predictive validity,
  volatility track with its ≥120-return floor, refusal-rendering), and the
  boundaries: the parked early-warning line is not reopened by operator
  data, the published v1–v3 records are untouched, and nothing sends data
  outward. Registered in the docs index; README's registry bullet now points
  at it.
- **The volatility track is visible: a Results-page card prices GARCH(1,1)
  against unconditional variance per source.** `run_backtest` has computed it
  since the garch wiring, but nothing rendered it — the claim "does
  complexity earn its keep for volatility?" existed only in job JSON. The
  Results page now fetches the existing (previously frontend-unconsumed)
  `GET /api/v2/reports/backtest/{job_id}` report via `useBacktestReport` and
  renders a per-source table beside the predictive-validity card: MSE of
  variance and MAE of volatility for GARCH vs unconditional, the lift on both
  losses, folds scored, and the fit-health counts (failures, non-stationary,
  non-converged) travelling with the verdict — "earns its keep" only when the
  lift is positive on BOTH declared losses. Declared skips and recorded
  failures render as states, never as zeros; an in-progress or pre-wiring job
  answers "No volatility track" rather than an error wall. E2e: the mock now
  answers the backtest-report route with the real branch logic, the 104
  fixture carries one measured and one skipped source, and a spec
  walk-through asserts both rows (mock-coverage audit stays at zero
  unanswered endpoints).
- **The BoE licence question is resolved — OGL v3, confirmed against the
  source.** The probe's two candidate terms URLs were 404s; the real page is
  `bankofengland.co.uk/legal` (accessed 2026-09-18), whose "Bank of England
  Database" section states that reproduction of Database data "is subject to
  the terms of the UK Open Government Licence", linking OGL v3. The plugin
  docstring, the curated provenance record and the probe document now carry
  the confirmed licence with its quote, the required attribution ("Contains
  public sector information licensed under the Open Government Licence
  v3.0"), and the grant's scope notes: third-party-owned series (the page
  names LSEG spot-FX data) are excluded and need their owner's approval, and
  SONIA-family series carry their own required statement. The pinned test
  now asserts the confirmed licence appears in the provenance record. One
  YELLOW-path action remains open (the PRA probe for bank-level exposures).
- **The v3 early-warning run executed — 0 of 3, and the line is parked as
  its own protocol declared.** One clean run under tag
  `prereg-early-warning-v3` (tag → fetch → evaluate; zero retries; key
  grep-verified absent from every committed file; licence screen refused
  the ICE BofA series before download). The q98 alarm point fixed exactly
  what v2 diagnosed — false alarms fell from ~9–10 to 2.7–4.7 per quiet
  year, clearing the criterion for two of three indicators — and consumed
  lead time exactly as declared pre-run (medians 42→10, 18.5→10, 11.5→8;
  VIX fell through the frozen ≥10-day floor). `FRED_T10Y3M`'s frozen TAN
  failed on the false-alarm criterion **alone, by 0.2** (4.2 vs 4.0) — the
  closest any candidate came in three runs, published as a fail because
  loosening a ceiling after seeing 4.2 is the goalpost-move the protocol
  exists to forbid. The frozen hazard logit failed out-of-sample on both
  spreads (AUC 0.39/0.44): an 18-year extrapolation of a pre-2006 hazard
  fit does not survive the QE-era regime change — recorded as the finding
  it is (frozen-forever scoring and hazard architectures are a poor
  pairing; the literature's rolling refits were outside this protocol's
  discipline). Persistence remains unbeaten on VIX (0.9265 vs 0.9257).
  Reproducibility held a third time: alarm-independent metrics identical
  across v2/v3 for every indicator-scorer pair. Under the terminal clause
  frozen before the run, the early-warning line is **parked** with the
  three-run record; the README gate now says so, and any resumption is a
  new owner-initiated protocol (recorded v4 axes: rolling refits,
  weekly/monthly tracks for the credit-gap family). Report + execution
  log: `docs/prereg/runs/early_warning_v3/`.
- **Early-warning pre-registration v3 — the declared-final iteration.**
  Two changes, both derived from *published* v1/v2 facts, with every
  grading criterion frozen untouched: (1) alarm quantile 0.95 → **0.98** —
  at q95 the false-alarm criterion was arithmetically unreachable for any
  indicator (~12.6 alarms/yr × measured 23–29% precision ⇒ ~9–10 FA per
  quiet year vs the ceiling of 4), a protocol design incoherence now
  measured twice; at q98 the ceiling demands precision ≥ ~20% — demanding,
  not soft. Declared risk accepted pre-run: rarer alarms may shorten median
  lead below the frozen ≥10-day floor. (2) A second frozen scorer,
  **`hazard_logit`** — the crisis-literature EWS architecture (logistic
  hazard of episode onset within 21 days on two declared features: signed
  standardized level and its 63-day change), sklearn defaults, fitted once
  on ≤2006, no exposed knob — graded identically to the retained TAN scorer
  on the same grid, with Holm–Bonferroni pooling **every scorer–indicator
  pair** (multiplicity accounted, not hidden). Terminal clause declared:
  pass → the README claim gate moves with these numbers; fail → the line is
  parked with a three-run documented record. Frozen constants pinned by
  `test_prereg_runner.py::TestProtocolTableIntegrity` (13 helper/contract
  tests: Holm propagation, Wilson, hazard mechanics incl. determinism and
  declared-absence, protocol-table drift). `docs/prereg/early_warning_v3.md`
  + `configs/event_eval_v3.yaml`, tagged `prereg-early-warning-v3` before
  the single run.
- **The v2 early-warning run executed — a better-powered NO, published
  unchanged.** Under tag `prereg-early-warning-v2`, one clean run (zero
  retries, zero infrastructure defects), on licence-screened hashed data
  fetched through the keyed FRED transport: all three testable indicators
  evaluated, **0 of 3 passed** the criteria frozen since before v1, family
  claim **NO** — the README gate did not move. The numbers are now
  informative rather than merely honest: `FRED_T10Y2Y` reproduced v1's
  result byte-identically (same hashes, seed and code path — the frozen
  pipeline is reproducible); `FRED_T10Y3M` validated the literature-backed
  selection (AUC 0.663 vs 0.555, 5 of 7 declared episodes flagged vs 2, and
  the run's only lift-criterion pass — strictly above persistence AND AR(1)
  on both AUC and AP); `FRED_VIXCLS` discriminates its own stress episodes
  strongly (AUC 0.926, AP ≈ 9× base rate, all permutation p=0.001 and
  Holm-surviving) with the endogenous-labels caveat recorded. What binds
  every indicator is the false-alarm criterion (8.9–10.3 per quiet year vs
  the frozen ≤4): the q95 alarm quantile fires on ~5% of days by
  construction — a knob/criterion coherence fact for v3's *pre-declared*
  design, never a post-hoc tuning target. Report + execution log:
  `docs/prereg/runs/early_warning_v2/`.
- **Early-warning pre-registration v2 — same frozen criteria, better-powered
  family.** v1's published NO carried its own diagnosis (one testable
  indicator; the registry skews to operator-reported and low-frequency
  series), so v2 changes the family and nothing else: `FRED_T10Y3M` (the
  short-end curve spread the recession literature documents) and
  `FRED_VIXCLS` (the standard equity-stress gauge, licence-checked) join the
  candidates with registry directions declared before any fetch. Every
  criterion, labelling parameter, alarm rule, model config, seed, window,
  baseline and run rule is frozen identical to v1 — enforced structurally by
  one shared constant block and one shared evaluation path in the runner.
  New mechanics are data-availability only: keyed FRED transport
  (`FRED_API_KEY` from the environment, never written to any file, endpoints
  recorded with `api_key=<redacted>`) and a licence screen that reads each
  series' own FRED notes and refuses to download — let alone commit — any
  series whose terms prohibit reproduction. `docs/prereg/early_warning_v2.md`
  + `configs/event_eval_v2.yaml`, to be tagged `prereg-early-warning-v2`
  before the single run.
- **Two new codes in the semantics registry, directions declared pre-fetch:**
  `FRED_T10Y3M` (-1, same term-structure convention as `FRED_T10Y2Y`) and
  `FRED_VIXCLS` (+1, rising implied equity volatility = stress).

### Changed
- **BREAKING (the 4.0.0 MAJOR justification): `GET /api/v2/predictions/{job_id}`
  serves refusal instead of fabrication.** `PredictionNode.risk` is optional;
  absence travels as `null` with the reason beside it (`uncertainty_status`,
  `uncertainty_reasons`, `confidence_method`), and a missing score is never
  coerced to `0.0` nor substituted from "any numeric column, scanned
  backwards" (which on a refused row would have served epistemic variance as a
  risk score, or 500'd on NaN). Consumers that assumed a numeric score is
  always present **will break — by design**: a platform whose API invents
  numbers under refusal is worse than no platform. Per `docs/VERSIONING.md`
  this is a breaking change to public API semantics, hence MAJOR. Details in
  the Fixed entries below and `docs/api.md`; the UI renders refusals as
  absence (Results page), and the refused-row contract has tests.

### Removed
- **`data/prereg/FRED_BAMLH0A0HYM2.csv` — licence violation, withdrawn.**
  The v1 fetch captured 339 rows of the ICE BofA High Yield OAS keylessly
  (the series was skipped pre-metric for coverage, so no result ever used
  it). The v2 licence screen read the series' own terms: ICE Data Indices
  prohibits reproduction in any form and furnishing the data to third
  parties. Committing the capture as "provenance" was itself the violation;
  the file is removed at HEAD (published history is not rewritten), with
  `data/prereg/REMOVAL_NOTE.md` recording the facts, and v2 screens licences
  BEFORE downloading so this cannot recur. FRED also now serves only a
  rolling 3-year window of the series (metadata observed 2026-09-17), which
  independently disqualifies it from an 18-year evaluation.

- **GARCH(1,1) is priced — the last unblocked `wire` disposition.** The
  module shipped complete but unconsumed because "level baselines price
  levels, not variance"; scoring it against level targets would have been a
  category error. It now runs as its own track: `run_backtest` computes, per
  source and on that source's own contiguous span (returns never difference
  across a seam), a walk-forward comparison of the GARCH's one-step
  conditional variance — seeded from training, stepping on observed *past*
  squared returns, test returns centred by the training mean — against the
  unconditional-variance baseline, on MSE-of-variance and MAE-of-volatility,
  with per-fold parameters, stationarity and convergence reported rather
  than hidden and a positive lift meaning the three parameters earned their
  place (`backtesting.compare_volatility_baselines`, results under
  `backtest_metrics.volatility_baselines.by_source`). A richer volatility
  model now has the honest bar the garch module's docstring always claimed
  it must beat. Census: `garch` moved to `REQUIRED_REACHABLE`. Six tests pin
  the contract, including the load-bearing one: on data from a true
  GARCH(1,1) family the fit must beat unconditional variance on both losses.
- **The UK gap has its first feed: `boe_database` plugin** — action 2 of the
  executed BoE probe's YELLOW path, implemented to the contract the probe
  confirmed. A strict stdlib HTML-table reader for the Interactive Database
  (`FromShowColumns.asp`, `DD/Mon/YYYY`, no auth): typed `BoEDatabaseError`
  on HTTP status / ErrorPage redirect / missing table / unparseable date /
  non-numeric value — schema drift fails loudly, never as empty data; an
  empty window returns `None` per the plugin contract. Evidence-first
  catalogue: only the probe-verified Official Bank Rate (`IUDBEDR`) is
  built in; further series must be operator-declared in config — the plugin
  never guesses codes. Identifying User-Agent, one request per fetch,
  declared century pivot for two-digit years (Bank Rate history reaches
  1694). 19 offline tests parse the **real captured table bytes**; one live
  smoke parsed 63 recent rows and a 22-business-day January-2024 window.
  Registered in the loader list (the omission class that once darkened
  three plugins) and in `CURATED_PROVENANCE` — where the reuse licence is
  recorded as **unconfirmed**: `/copyright` and `/terms-and-conditions`
  both 404 at probe time, and nothing claims a permission that was not
  observed. README's plugin count corrected to 18.
- **The pre-registered early-warning evaluation ran — and the answer is a
  published NO.** Under tag `prereg-early-warning-v1`, on hashed data
  fetched through the platform's own keyless FRED plugin and certified by
  the real quality gate: of the 6 public candidates only `FRED_T10Y2Y`
  survived the declared data-availability rules (weekly/monthly frequency,
  a 2018 start, a licence-windowed anonymous tail and a 404 excluded the
  rest *before any metric existed*). The single testable indicator detected
  its labelled events with a 42-business-day median lead and AP ~2x base
  rate (permutation p=0.001, Holm-surviving) but **failed 2 of the 4 frozen
  criteria**: 9.6 false alarms per quiet year (limit 4) and no lift over
  the persistence baseline (AUC 0.555 vs 0.559 — "stress continues" read
  off the current spread level slightly beat the trained model). Testable
  family 1 < the declared minimum of 3, so the system-level claim is
  automatically unwarranted and the README's honest default stands. Two
  pre-metric infrastructure failures (a wrong class name, then the
  single-scale trainer's engine-incompatible checkpoints) were fixed and
  logged with their diffs in the execution log, as the single-run rule
  requires; no protocol constant changed between tag and run. Report:
  `docs/prereg/runs/early_warning_v1/` — published unchanged, negative
  result included. The first-order finding is about data, not models: a v2
  family needs daily public series curated into the catalogue first.
- **The pre-registered early-warning evaluation exists as a tagged, runnable
  artefact** — steps 1–3 of `docs/probes/event_target_proposal.md`,
  owner-approved with the proposal's defaults (RRPONTSYD excluded). Frozen
  protocol: `docs/prereg/early_warning_v1.md` + `configs/event_eval_v1.yaml`
  (7-episode context family, registry indicator family with per-code
  dispositions declared *before any fetch*, 21-business-day horizon at the
  0.95 quantile with 5-step persistence, chronological 2006/2007 holdout,
  sign-adjusted scores joined via `row_offset`, persistence + AR(1)
  baselines on the identical grid, four pass criteria with Holm–Bonferroni
  across a 1000-shuffle permutation test, minimum testable family of 3 for
  any system-level claim, single-run rule, negative results published).
  Runner: `scripts/run_preregistered_eval.py` (`--fetch` writes
  `data/prereg/` + a hashed manifest through the platform's own keyless FRED
  plugin; `--eval` executes once). The fetch phase ran pre-tag: of the 6
  public candidates only `FRED_T10Y2Y` survived the declared
  data-availability rules (STLFSI4 weekly, KCFSI monthly — the protocol step
  is one business day; SOFR starts 2018; BAMLH0A0HYM2 serves anonymous
  callers a licence-windowed tail; FRED id `CISS` 404s), so v1 evaluates one
  indicator and the family verdict is automatically NO system claim — the
  protocol's first honest finding: the registry skews to operator-reported
  and low-frequency series, and any future claim needs daily public series
  curated into the catalogue first.
- **The BoE probe's YELLOW-path discovery follow-up ran** (~5 further
  polite requests): no stateless CSV/JSON contract exists behind
  `FromShowColumns.asp` (HTML tables only, no download links, no REST
  service referenced; the statistics hub landing links no bulk data files),
  so the documented path is confirmed: a strict HTML-table parser plugin
  with typed errors, aggressive caching and an identifying User-Agent,
  first series Official Bank Rate (`IUDBEDR`). Licence/attribution check
  remains open before shipping. Findings recorded in the probe document.
- **Refused predictions are visible in the UI.** The Results page's
  predictions table grew an Uncertainty column with the three states the
  deep-ensemble wiring can put a row in: `Refused` (clay chip + the
  assessment's reasons; score, prediction and bounds render as em-dashes —
  absence, never a number), `epistemic N%` for assessed rows, and `not
  measurable` for single-checkpoint models. Scenario payload types carry
  the new optional fields; the e2e mock's baseline scenario exercises all
  three states.
- **The Results page has e2e coverage again.** The three-way spec split
  dropped the entire Models → Scenario Builder → Launch Explainability →
  Results walk and the predictive-validity report card — no split spec
  mentioned Results, so the platform's headline output screen had no
  browser guard at all. `frontend/tests/results.spec.js` restores the
  monolith's walk (including the drawer-close race it documented) and adds
  the refusal-rendering contract; the deep e2e workflow picks it up
  automatically (`npm test` runs every spec).
- **`GET /api/v2/predictions/{job_id}` carries the uncertainty state.**
  `PredictionNode.risk` is optional now and absence travels as null with
  the reason beside it (`uncertainty_status`, `uncertainty_reasons`,
  `confidence_method`, decomposition variances in `additional`).
- **The BoE endpoint probe was executed** (2026-09-17, ~9 polite requests)
  and its findings recorded in `docs/probes/boe_endpoint_probe.md` against
  the pre-written criteria: the guessed balance-sheet file 404s,
  `api.bankofengland.co.uk` does not resolve, but the Interactive Database
  (`boeapps/database/FromShowColumns.asp`) serves real series data with no
  authentication — Official Bank Rate `IUDBEDR` = 5.25 returned for
  2–5 Jan 2024, matching published history — as HTML tables (`csv.x=yes`
  did not yield CSV; `DD/Mon/YYYY` dates required). Classified **YELLOW**:
  bounded endpoint-discovery follow-up before any parser work; bank-level
  UK exposures would need a separate PRA probe.
- **Event-target & pre-registered-evaluation proposal**
  (`docs/probes/event_target_proposal.md`, awaiting owner sign-off — nothing
  in it is pre-registered): the declared episode family (seven widely-dated
  systemic episodes, chosen before any indicator data is examined), the
  fixed indicator family (every code in the semantics registry), labelling
  defaults for the existing `EventDefinition` knobs, and the protocol that
  makes the "demonstrated early-warning system" claim a tagged, single-run,
  negative-results-published artefact instead of a vibe. It records what
  already exists (labeller, event metrics, backtest consumption, CPCV
  baselines) so the remaining gap is visible as decisions, not code.
- **Aleatoric/epistemic decomposition is wired — the census's oldest `wire`
  disposition.** A training job with `ensemble_size >= 2` (single-source path)
  now trains that many independently seeded members via
  `trainer.train_ensemble` — each in its own directory, member 0 promoted to
  the canonical `best_model.pt`/`predictions.csv`/`training_history.json` so
  every existing consumer reads an ensembled job exactly like a single-model
  one, members 1..M-1 saved beside it as `ensemble_member_{k}.pt`. The
  prediction engine discovers the members at load and, per source, decomposes
  the final window's variance on exactly the held-out slice the
  split-conformal interval calibrates on: aleatoric from the members'
  residuals, the epistemic ceiling from their disagreement across the slice
  (`EpistemicReference`, level 0.99). An assessment that finds the members
  disagreeing more than the ceiling — the model extrapolating — or model
  ignorance dominating the variance **refuses the source**: score,
  prediction and interval withheld as null/NaN, the reasons recorded on the
  row, `confidence_method` set to `refused_uncertainty_assessment`, and the
  refusal counted in the executive summary and the job result's
  `uncertainty_decomposition` (which the explainability card attaches
  verbatim). A single-checkpoint model reports the split **not measurable**
  rather than a fabricated zero, because a one-member epistemic term is
  identically zero by construction and a reliability flag on that zero would
  understate ignorance — the module's own stated failure direction. The
  multi-scale trainer does not train independent members yet; an
  `ensemble_size` request it cannot honour is recorded in the job result with
  a note instead of being silently dropped. Point scores stay the primary
  frozen model's: the decomposition informs the reliability verdict, it does
  not quietly swap in an ensemble mean.
- **Tracked build artifacts now fail the fast gate.** `backend-ci.yml` gains
  a milliseconds-long index check (`git ls-files` against
  `__pycache__`/`.pyc`/`beacon.db`/`dist`/`node_modules` patterns): the
  restored `.gitignore` prevents artifact leaks at the filesystem level,
  this prevents the task-snapshot class of leak at the index level.

### Fixed
- **The stranded v3.3.0 release is tagged.** The release commit (`57db310`,
  2026-09-16) moved the changelog block and bumped `VERSION`, but the
  annotated tag was never created or pushed — `VERSIONING.md` reserves
  tag-pushing to maintainers and the step was missed. Found by the pre-4.0.0
  audit diffing `git tag -l` against `release:` commits. `v3.3.0` is tagged at
  its release commit alongside this one, and the `CONTRIBUTING.md` release
  checklist now ends with "push the tag; verify it exists" (ledger L-23).
- **`run_backtest`'s event metrics measured the wrong thing twice over.**
  (a) Alignment: labels were joined to the risk series by naive truncation
  (`events[:len(scores)]`), shifting every label by the sequence warm-up
  (~30 business days) — larger than the lead times being measured, so a
  20-day warning read as simultaneous and a simultaneous alarm read as a
  lead. Scores now join through `row_offset`, the documented
  `RiskSeriesResult` contract. (b) Direction: for a `direction=-1` series
  (e.g. `FRED_T10Y2Y`, where stress is *falling* values) the raw score's
  high tail was scored against falling-value labels — measuring the
  opposite of a warning. Scores are now sign-adjusted by the registry
  direction before the alarm quantile, so higher always means more stress.
  Found while building the pre-registered runner, which mirrors this idiom;
  the runner implements the corrected form and the job path now matches it.
- **The v2 predictions API no longer fabricates scores.** `_extract_nodes`
  coerced a missing score to `0.0` and, worse, fell back to "any numeric
  column, scanned backwards" — on a refused row (NaN score, uncertainty
  columns present) that would have served epistemic variance as a risk
  score, or handed NaN to a JSON encoder configured to reject it (a 500
  the moment the first refusal shipped). Scores are now `risk_score`, else
  `prediction`, else null; the refused-row contract has tests.
- **The README's semantics-register bullet was stale in the third
  direction.** It claimed "no per-indicator semantics registry" exists, but
  `backend/modules/data/semantics.py` (round-eight adoption) declares stress
  directions for the curated indicator set and `run_backtest` consumes it
  for event labelling -- with `None` as a refusal, not a default. The
  bullet now states what is real (directions) and what is still missing
  (units and an agreed combination rule for cross-source aggregation). The
  event-target bullet points at the new proposal.
- **Two more stale "not wired" claims corrected** (found by the whole-repo
  audit, same drift class as the transparency card): the README's Storage
  section said nothing writes `RiskScorePoint`/`ModelMetricPoint`, but
  prediction jobs persist risk scores (`persist_risk_scores`) and backtest
  jobs persist metrics (`persist_model_metrics`); and the prediction
  engine's key-findings line claimed "calibrated prediction intervals are
  not reported" while every supported row carries a split-conformal
  interval. Both now state what the code does.
- **The transparency card reports what the job actually carries.** The
  explainability endpoint's uncertainty block asserted a blanket
  `not_calibrated` — "the confidence fields are null" — for every job, but
  split-conformal intervals have been computed per source since `6be3797`
  (2026-09-14) and populate those fields wherever a source's held-out
  residuals support a calibration window. Prediction results now record
  their per-source `confidence_methods` counts, the card derives its status
  from them (`split_conformal_per_source` / `not_calibrated` /
  `not_recorded` for older jobs), and the same stale "until conformal lands"
  sentence was corrected in the README calibration register, the prediction
  engine's module docstring, and the executive-summary template — which now
  counts the intervals the run actually produced instead of claiming none
  are reported.
- **The training task no longer constructs an orchestrator it never calls.**
  `job_tasks.run_training` built an `EngineOrchestrator`, logged a device
  line through it, and then trained via `MultiScaleTrainer`/`ModelTrainer`
  directly — the object implied an architecture the task does not use (the
  orchestrator's real production caller is the pipeline route). Dead
  construction and imports removed; reachability of `engine/orchestrator.py`
  is unaffected.
- **Dead computations removed**: an unused `base_url` in `bis_plugin` (the
  fetch hardcodes the full URL), an unused identity matrix in
  `causal_discovery`, an unused `receipts` vector in `risk/clearing.py`, and
  a duplicate `"btn"` in the Bhutan code set.
- **`test_migrations_live` asserts the error class it means**: the
  "genuine errors must surface" check accepted a blind `Exception`, which a
  bug in the guard itself would also satisfy; it now expects the DB-API
  error the database actually raises.
- **`.env.example` documents the knobs the code reads**: `BEACON_API_TOKEN`
  (the bearer gate over `/api/*`; unset = single-operator, no auth) and the
  custom-API SSRF policy (`BEACON_CUSTOM_API_ALLOW_HTTP`,
  `BEACON_CUSTOM_API_HOST_ALLOWLIST`) were only in the RUNBOOK.

- **The deep backend suite can run again.** The sharded rewrite of
  `backend-tests.yml` could not start at all: `with: { key:
  backend-deps-${{ github.run_id }}, ... }` is invalid YAML (`${{ }}` inside a
  flow mapping), so every run failed with zero jobs; behind that, the test
  jobs restored only `~/.cache/uv` while the dependencies lived in the setup
  job's site-packages on a different runner, and every shard passed `-n auto`
  without pytest-xdist being declared anywhere. The shard globs also silently
  dropped four test files (`test_compose_stack`, `test_counterfactual_coupling`,
  `test_foundation_encoders`, `test_hidden_markov` -- the last two covering
  modules the README lists as wired). Reverted to the proven single-job
  workflow (measured 8-10 min green, not the ~25 min the rewrite claimed as
  its baseline), which also restores the coverage artefact and advisory ruff
  the workflows README documents.
- **The deep e2e suite installs its browser again.** The parallel rewrite of
  `frontend-e2e.yml` dropped `npx playwright install` (keeping only
  `install-deps`, which fetches OS libraries, not chromium) and cached the
  browser under a key with no playwright version in it; it also built and
  cached `dist/` that no test consumed -- the suite runs against the Vite dev
  server. Reverted to the proven single job (measured ~1.2 min, not the ~20
  min the rewrite claimed), with the comment updated for the three-way spec
  split. The split itself (dashboard/pages/search) is kept.
- **`pages.spec.js` control-room test navigates to the page it asserts on.**
  The split from the monolith lost the Data Sources navigation step, so the
  test looked for the schedule selector on the Dashboard and could only ever
  time out. It had never executed anywhere: the workflow that runs it has not
  completed a run since the split.
- **The bundle-budget gate measures what it says it measures.** It read a
  `dist/stats.json` that `vite build --stats` does not produce, budgeted the
  "largest route chunk" by taking the largest of *all* chunks -- the 957 kB
  `deck-vendor` -- against a 40 kB budget, so both of its metrics were
  permanently tripped and could never surface the 33 kB route-chunk
  regression it exists for; its summary table also printed literal
  backslashes from over-escaped `${{ }}` expressions. It now classifies
  chunks the way `vite.config.js` creates them (vendor / geo data / app /
  route), budgets app total ≤450 kB and largest route chunk ≤40 kB, and
  reports vendor bytes as informational. A second-pass review added the
  failure mode the classifier itself needs: if no chunk matches the
  route classification (renamed `manualChunks`, empty build), the analyzer
  exits with a named reason instead of passing silently or crashing opaquely.
- **`test_alert_evaluator.py` survives a second run.** Its `_clean` fixture
  deleted jobs and notifications but not alert rules, and under the
  suite-wide `USE_SQLITE` binding the rules accumulated in the shared
  `./beacon.db` across runs -- so
  `test_due_rules_honour_each_rules_frequency` failed on every re-run against
  a warm database. Rules are cleaned with the other inputs, and the module's
  dead import-time `DATABASE_URL` setup (always overridden by the conftest
  pin) was replaced with a comment saying which database actually runs.
- **`bank_analyzer.py` no longer claims a vectorisation it does not do.** The
  counterfactual-shock loop was relabelled "batched ... using vectorized
  operations" while still calling `clear_multiplex` once per node -- an
  O(n^2) `np.tile` pre-materialisation and a cosmetic reindex were the only
  changes. The honest loop is restored, with a comment that states the real
  cost and points at `scripts/bench_systemic.py` as the baseline any future
  batching claim must beat.
- **The repo's `.gitignore` is the repo's `.gitignore` again.** A task-snapshot
  commit replaced its 131 lines with an LLM's prose about why nothing needed
  ignoring, which stopped ignoring `__pycache__/`, `.env`, virtualenvs and
  build artefacts, and a compiled `analytics.cpython-312.pyc` was committed
  into the tree. The original file is restored and the `.pyc` untracked.
- **`docs/api-endpoints.md` is regenerated, not hand-edited.** The retired
  analytics endpoints were removed from the inventory by hand with a
  "Retired endpoints (Phase 2)" annotation the generator does not know, while
  the header still claimed v3.2.0/124 operations against a live app serving
  v3.3.0/122 -- so `test_api_docs_current` failed. The routes were already
  gone from the code; the inventory now says so the generated way.
- **The Pool teardown guard no longer dies while guarding.**
  `multiprocessing_patch.safe_del` called `logger.debug` inside its
  `AttributeError` handler at interpreter shutdown, where module globals are
  already `None`, producing "Exception ignored in ... safe_del" tracebacks at
  process exit -- noise from the very path whose job is to suppress noise.
- **The feasibility memos state the platform as it is.** The MoE memo claimed
  a "prediction store with `regime_label` field" and a "model registry [that]
  tracks performance by regime"; neither exists -- regime labels ride inside
  `jobs.result` JSON and there is no registry. The temporal-GNN memo claimed
  per-prediction-cycle exposure networks and versioned balance sheets; the
  PIT store holds only what operators upload or estimate. The BoE probe memo
  is now explicitly marked planned-not-executed: it records methodology and
  expected responses, and contains no findings.

## [3.3.0] - 2026-09-16

### Added
- **Failed jobs retry as new jobs.** `POST /api/v1/jobs/{id}/retry` re-queues a
  failed job with exactly its own type and parameters plus `retry_of`
  lineage; 409 unless the job actually failed, because a running job is not a
  draft. The job details card now leads with `user_friendly_error` -- the
  sentence a human can act on -- and keeps the technical string below it in
  mono for the log-driven.
- **A first-run checklist derived from live state**, the successor to the
  guided tour: no sources configured, nothing fetched, nothing scheduled, no
  exposure matrix -- each step appears only while its condition is true and
  clears the moment it is not, and hand-dismissals persist in localStorage.
  A scripted tour describes the product its author had; these steps describe
  the deployment the user has.
- **The network layer's missing half, in the UI.** The Risk Map strip now
  offers "Upload matrix" (`POST /network/exposures`, CSV or parquet with an
  attributing institution and a stored vintage) and "Estimate from marginals"
  (`POST /network/estimate`, declared aggregate claims and obligations
  completed by maximum entropy). The estimate modal renders the response's
  `uncertainty` string verbatim: an estimated network presented without its
  prior-status is the quiet invention this platform refuses everywhere else.
- **Focus traps for overlays.** Modals and the model details drawer trap Tab
  and own Escape through `hooks/useFocusTrap`, and return focus on close.
  They closed on Escape before but never trapped: a keyboard user tabbing
  forward left the dialog and wandered the page behind it, which is the
  difference between an overlay and a suggestion.
- **Alert rules now evaluate.** The beat tick runs `evaluate_alert_rules`:
  each enabled rule is measured on its own frequency over its own window
  (success_rate, execution_time, quality_score, rmse), compared with its
  operator, and a breach raises one notification per cooldown window -- typed
  `alert`, with the measured value, operator and threshold in the message and
  `extra_data`. An unmeasurable metric or an unknown operator is a visible
  skip, never a guess. Rules carried full CRUD and no evaluator before this:
  a monitoring platform whose alerts never fire is quieter, and therefore
  worse, than one with no alert feature.
- **Append-only vintage log for indicator observations**
  (`indicator_vintage_log`, migration `vintage_log_001`, plus
  `alert_evaluation_001` for the rules' evaluation memory). Official series
  are restated; the latest-value store keeps what is currently believed and
  the log keeps what was believed when, so
  `TimeSeriesStore.observations_as_of(source, indicator, as_of)` re-derives
  any past series exactly as it stood at that date. The hypertable's primary
  key stays as it is -- vintages are the audit half, stored beside it.
- **Scheduled collection, per source.** `data_sources.sync_interval_minutes`
  (null = manual-only) plus a `celery-beat` service on the shared backend
  image: beat ticks every five minutes and enqueues whichever sources are due
  through the same `data_collection` job a human creates. Failures double the
  interval up to eight times (one success restores it), a stable hash-of-id
  jitter spreads sources that share a cadence, and an open collection blocks a
  second enqueue. Migration `source_sync_schedule_001` adds the cadence and
  telemetry columns, guarded like every revision that can meet a database it
  did not create.
- **Feed health and live probes.** `GET /api/v1/data-sources/health` answers
  cadence, backoff factor, failure streak with the provider's last reason,
  last start/duration/rows, next due date and `overdue` per feed;
  `POST /api/v1/data-sources/{id}/probe` runs the plugin's own
  `test_connection` with environment-held keys injected exactly as the
  collector injects them (the plugin->env-var map moved to the registry so the
  two cannot drift). The Data Sources page is now a control room -- cadence
  selector, last run, next refresh, failure streak, test-connection verdict --
  and Data Quality gains a "Refresh Cadence" panel: promise versus reality,
  with no row for manual sources because a feed nobody promised to refresh is
  not late.
- **`Sync Now` queues a real collection** (202 + job, 409 while one is open or
  the source is disabled) instead of stamping a timestamp while nothing
  fetched. The docstring said "connect your automated pipelines here later";
  this is that later.
- `scripts/check_e2e_api_coverage.mjs`: runs `apiMocks.js`'s real `**/api/**`
  route handler against every `fetchApi` endpoint in `frontend/src`, by method,
  and names the ones that fall through to the 404 default. It evaluates the
  actual handler rather than grepping for strings, so a path in a comment or a
  mock registered for the wrong method cannot satisfy it. Wired into Frontend CI
  ahead of Playwright and into the backend suite via
  `backend/tests/test_e2e_api_coverage.py`, which also runs it against a copy of
  the frontend containing an invented endpoint to prove it can fail.

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
- **The regime nowcast is batched: ~10–11× on a 20-source job, labels
  provably identical.** `prediction_engine._regime_label` fit a two-state
  Student-t HMM per source in a Python loop over T doing (K=2, K=2) numpy
  work — the measured bottleneck of the prediction path (3.35 s per source at
  T=1 000) and the one lever `docs/LANGUAGE_STRATEGY.md` named but deferred
  until it had "its own change with its own label-equality test". This is
  that change: `fit_viterbi_student_t_batch` runs the same recursion with a
  leading source axis (broadcast seeded stream, per-source convergence
  freeze, the identical scalar brentq for nu, degenerate seedings handed back
  for solo fitting), `_predict_single` nowcasts one batch per window length,
  and `_regime_label` remains the per-source fallback — a batch failure
  degrades to slow, never to different. `test_regime_batch_equivalence.py`
  pins exact Viterbi state-sequence and label equality against solo fits
  across a deterministic corpus including the production T=1 000 shape, and
  `bench_systemic.py` measures the claim in-session: n=20 × T=250 29.04 s →
  2.82 s (10.3×), n=20 × T=1 000 111.53 s → 10.27 s (10.9×). The strategy
  doc's hot-path table and deferred-lever section are updated in the same
  change, as that doc requires.
- **The app no longer calls Google Fonts.** `index.html` linked the
  stylesheet and `src/styles/index.css` `@import`ed the same URL — two
  render-path third-party round trips on every load, in a product whose own
  components state the dashboard "must render in air-gapped deployments"
  (and whose e2e suite had to grow a route interceptor just to stay
  hermetic). Source Serif 4 is now self-hosted: the variable woff2 faces
  (roman + italic, latin + latin-ext, weights 400–700 — exactly what the
  Google URL served, ~460 KB) live in `frontend/public/fonts/` with the OFL
  license, declared in `index.css` with `font-display: swap` and preloaded
  for the primary face. The e2e webfont interceptor is deleted — there is
  nothing left to intercept.
- **The risk-map bundle is split for caching and deferral.** The
  `RiskMapPage` chunk was 975 kB of app + deck.gl in one file: any page edit
  invalidated every byte. `vite.config.js` now carves a `deck-vendor`
  manual chunk (935 kB — content-hashed on the lockfile, not on app code),
  the route chunk drops to 33 kB, and `@deck.gl/aggregation-layers` left the
  static graph entirely: `RiskMap` loads `HeatmapLayer` through a dynamic
  import, so it arrives as its own 89 kB async chunk in parallel with first
  paint (and not at all for a session that never shows the heatmap). Until
  it resolves, every other layer renders unchanged.
- **The frontend now only reads fields the API actually sends, and a test
  keeps it that way.** The typed-call audit (`backend/tests/test_frontend_contract.py`,
  new) parses every `fetchApi<T>`/`fetchJson<T>` call, resolves the endpoint
  against the app's live OpenAPI schema, and fails when a declared field is
  absent from the wire — it immediately earned its keep: `Job` declared
  `name`/`model_id`/`config`/`logs` (no transport sends any of them; the Jobs
  page rendered "Unknown Model" and a permanently-empty Logs card in
  production while the e2e mock served all four), `DataSource` declared six
  invented alternates the cards fell back through (`record_count`,
  `api_endpoint`, `coverage`, ...), `CatalogueItem` declared
  `parameters`/`sample_metrics`/`country_code`/... behind unreachable UI
  branches, and the single `Model` interface conflated two different wire
  shapes — it is now `ModelSummary` + `ModelDetailData` exactly as the
  endpoints define them, with the Models cards, the performance tables and
  the details drawer rewired to real fields (`metrics.r2/rmse/mae`,
  `parameters.config`, `created_at`) instead of invented defaults ("LSTM",
  12, 4). `useSyncDataSource` no longer merges the queued **job** (the sync
  endpoint's actual 202 response) into the cached **source** row. The e2e
  fixtures were rebuilt to the true wire shapes — including a backtest job
  and the validation-report route with the real endpoint's
  validated/not-validated branch logic — and the spec now walks the
  predictive-validity card through the `#/results?jobId=104` deep link. The
  coverage audit's `DECLARED_UNMOCKED` list is empty: all 32 endpoints the
  frontend declares are answered by the mock.
- **Twelve dead hooks and four dead helpers deleted**, with a millisecond
  gate to keep the count at zero: `scripts/check_frontend_hook_reachability.mjs`
  (frontend sibling of `test_reachability.py`) fails CI when any named value
  export of `src/hooks|utils|data|store` has no consumer. Gone: five country
  hooks, five notification hooks, `useModelPerformanceComparison`,
  `useRiskScoreDistribution`, `getRegionById`/`getRegionsByCountry`/
  `getConnectionsForRegion`, the `API_BASE`/`Region`/notification-type
  compat re-exports nobody imported. The endpoints stay documented; a hook
  re-added for a real screen is three typed lines.
- **Invented states removed from three surfaces**, in the register the
  platform holds itself to everywhere else: the Model Performance page no
  longer prints hard-coded "+2.3%" / "−1.8%" trend chips (no endpoint reports
  a period-over-period delta; when one exists the chips can come back wired to
  it). Settings' "Linked data credentials" card claimed FRED was "Connected"
  unconditionally and offered dead "Connect" buttons; it is now "Linked data
  feeds", reading real configured/enabled state per plugin from the data
  sources API, with buttons that go to Data Sources — and the "Team access"
  card (roles, owner badges, invites) is gone, because the same page's own
  copy says BEACON has no user accounts. On the Models page, the Edit/
  Duplicate/Delete card menu (every entry opened a "Placeholder for …" card)
  is removed — no model update/copy/delete endpoint exists — and the
  Create/Train modals no longer collect hyperparameters into buttons that did
  nothing: they explain that models are the output of training jobs and hand
  off to the real training-job flow.
- **The frontend is now entirely TypeScript.** The ratchet from
  `docs/LANGUAGE_STRATEGY.md` is closed: all 23 remaining `.js`/`.jsx` modules
  under `frontend/src` (every page, the two data hooks, and the remaining
  components) converted to `.ts`/`.tsx`, and `tsconfig.json` no longer carries
  `allowJs`, so new JavaScript in `src/` is invisible to the compiler rather
  than merely unchecked. API payload shapes are now declared once in
  `frontend/src/types/api.ts` (jobs, models, scenarios, validation reports,
  catalogue, disclosure, network graph, system status, data quality,
  analytics, countries, notifications) and every hook is typed against them,
  so the envelope/field-name drift that motivated the migration fails
  `npm run typecheck` instead of rendering `undefined%`. `@types/react` and
  `@types/react-dom` are pinned to the React 18 the app actually runs
  (the transitive `@types/react` 19 pair had left `react-dom` untyped and the
  typecheck on `main` failing). No behaviour change: the production bundle
  builds with the same chunk graph and the e2e mock-coverage audit passes.
- **CI is a sub-minute gate plus nightly deep runs.** Everything triggered by
  a push or pull request now finishes in under a minute: `backend-ci.yml`
  keeps the dependency-free checks (syntax `compileall`, compose/Dockerfile
  validator), `frontend-ci.yml` keeps the static ones (strict typecheck with
  a lockfile-keyed `node_modules` cache and no browser download, e2e
  mock-coverage audit), and `versioning-ci.yml` is unchanged. The
  multi-minute legs moved to schedule + `workflow_dispatch`: the full pytest
  suite with the live-migration Postgres service, coverage and API-docs check
  to the new `backend-tests.yml` (nightly 03:47 UTC); the production build
  and the Playwright suite to the new `frontend-e2e.yml` (nightly 03:26 UTC);
  and the always-advisory `security.yml` audits dropped their push/PR
  triggers entirely (weekly + dispatch). The trade is recorded in
  `.github/workflows/README.md`: a regression only a browser or pytest can
  see surfaces at most one day late, or immediately by running the deep
  workflow on the branch before merging.
- Collection telemetry is written by the worker, not guessed: a success stamps
  duration and row count and clears the failure streak (which is what ends the
  backoff); a failure grows the streak and keeps the provider's reason, which
  the card and the cadence panel show instead of letting a quiet feed look
  healthy.
- **The risk map no longer reads a third-party tile service.** The keyless
  CARTO basemap endpoint now serves tiles watermarked "API KEY REQUIRED"
  diagonally across the map -- the "2d globe api required" watermark a
  reviewer hit on the live deployment -- and a tile CDN is also a key
  dependency and an offline failure mode (an earlier README capture showed a
  blank sea where tiles never loaded). The basemap is now a bundled, trimmed
  Natural Earth 1:110m land layer (`frontend/src/data/world-countries.json`,
  public domain, 190 KB), drawn in the paper idiom, with zoom capped at 6 and
  the attribution changed to Natural Earth. `@deck.gl/geo-layers` (TileLayer)
  left with it, and the e2e basemap-tile mock is gone because no tiles are
  fetched any more.
- **Risk-map degraded states are stated above the map, not across it.** The
  network status box (loading, unavailable, request failed with Retry, demo
  fallback, live vintage) was an overlay watermarked on the map canvas; it is
  now a slim status strip above the map card in `RiskMapPage.jsx`, one wording
  and one colour per state. A warning painted over the map read as part of the
  map; the legend and the OSM/CARTO attribution remain the only overlays.
- **README screenshots and Interface section.** Four captioned screens
  (Dashboard, Risk Map, Models, Results) captured from the shipped UI against
  the mocked API replace the two-image table whose risk-map capture showed a
  blank basemap; each caption says what the screen is for. The page list drops
  Help and the guided tour, and says plainly that guided help is absent until
  the system matures.
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
- **Guided help, while the platform is still maturing.** `pages/Help.jsx`, the
  driver.js onboarding tour (`hooks/useOnboarding.js`), `WelcomeBanner`,
  `styles/onboarding.css` and every navigation entry that led to them
  (sidebar, header menu, the global-search palette, breadcrumbs), plus the
  `driver.js` dependency and its `onboarding` vite chunk. Reviewer feedback:
  guided help for a system that is still moving documents behaviour faster
  than it can be written, and reads as confidence the product does not claim
  yet. The e2e suite asserts the tour button, the Help entries and the old
  Help copy stay absent, census-style: a removal is a decision, and decisions
  get tests. `docs/frontend.md` records where guided help returns from when
  the system matures.
- **`docs/QUANT_REVIEW_2026-09.md`.** The fourth-round quant review was a
  round-by-round development narrative -- what broke, what was fixed in that
  round, what the next round queued -- and reviewer feedback was that users
  need the limitations, not the saga. Its findings merged long ago with
  dispositions; its still-open items (no calibrated risk scale, no event
  target, no per-indicator semantics registry) now live as a three-bullet
  register in `README.md` §Scoring and validation, and every pointer to the
  document -- API payloads in `explainability.py` and `orchestrator.py`,
  docstrings, `RUNBOOK.md`, `LANGUAGE_STRATEGY.md`, the docs index -- was
  repointed there. `docs/README.md` keeps the deletion in its Removed table
  with the reason, so the absence stays discoverable.
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
- **The backend suite had been red on main for two days, and the failure
  named the wrong thing.** `test_pipeline_integration` and
  `test_provenance_disclosure` died with "no such table: data_sources" —
  which reads like a schema defect and was an import-order defect:
  `backend.database` binds one process-global engine from the environment at
  first import, and `test_alert_evaluator.py` (added in #61) is collected
  before `test_api_smoke.py` and sets `DATABASE_URL` without `USE_SQLITE`,
  so the suite's engine silently moved to that module's private file. The
  pipeline test's `reload(database)` then landed on an empty `./beacon.db` —
  its reloaded `Base` has no tables registered because every model module is
  already imported against the original `Base`, so its `init_db()` creates
  nothing. `backend/tests/conftest.py` now pins `USE_SQLITE=true` before any
  test module can import (conftest is the only hook pytest guarantees runs
  first), and `test_suite_engine_is_the_shared_sqlite_file` fails with the
  explanation attached if the binding ever moves again.
- **The TypeScript migration briefly shipped an unstyled app.** Tailwind's
  `content` globs still said `src/**/*.{js,jsx}` after every source file
  became `.ts`/`.tsx`, so the generated stylesheet contained no app
  utilities (5.9 kB instead of ~34 kB) and nothing failed: the build
  succeeds, the dev server starts, and only a browser could see the
  collapsed layout -- the dispatched Playwright run caught it via a
  deck.gl canvas covering the sidebar after the risk-map steps. The globs
  now cover `{js,jsx,ts,tsx}`, and a new fast-gate check
  (`scripts/check_tailwind_content.mjs`, ~0.2 s, no dependencies) resolves
  the configured globs against the real tree and fails by name when a
  src-targeting pattern matches zero files, so a silent-empty-stylesheet
  can never reach nightly again.
- **"Save Changes" on a data source was a 200-answering no-op — three ways at
  once.** The frontend nested the edit payload under a `data` key that
  Pydantic dropped; the `DataSourceUpdate` schema lacked the disclosure
  metadata columns the form collects (`registration_url`,
  `registration_required`, `free_tier_limits`, `coverage_description`); and
  the service never applied `sync_interval_minutes` even though the schema
  accepted it — so the schedule dropdown, the "Put a feed on a schedule"
  checklist step and the whole Refresh Cadence feature could never actually
  turn on. The update path is now `exclude_unset` end to end: absent keys
  leave stored values untouched, present keys are applied, and an explicit
  null clears a nullable column (`sync_interval_minutes: null` is the UI's
  "Manual only"). Pinned by `backend/tests/test_data_source_update.py`.
- **The notification bell polled twice.** `useNotifications` already refetches
  every 30 s; the component layered its own out-of-phase 30 s `setInterval`
  on top. The component timer is gone.
- **Analytics metric icons never had their tint.** The chip class was built as
  `bg-${color}/10`, which Tailwind cannot see at build time, so the class did
  not exist in the CSS. Static class map now.
- **Frontend CI has been red on every run since #53**, on `main` and on every
  branch cut from it -- so #54, #55, #56 and #57 all merged with the check
  failing. `GET /api/v1/data-sources/disclosure`, added by #53 and called by
  `DataSources.jsx` through `useDataDisclosure`, was never added to
  `frontend/tests/apiMocks.js`. It fell through to the mock's deliberate
  "unknown GET path: answer 404, as the real API does" branch; the spec fails the
  test on any console error; and TanStack Query *retried* the failed query during
  the create-source mutation's `invalidateQueries(['dataSources'])`. So the POST
  had already returned 201 when the console handler threw, and the run reported
  `expect(dataSourceForm).not.toBeVisible()` with the submit button still
  `disabled` -- an assertion describing a form that had in fact submitted.
  Diagnosed from the Playwright trace's network log, where one 404 sat among 113
  successful requests; not from reading the spec, which pointed at three
  different places first. The endpoint is now mocked, with its payload shape
  copied from the real `build_disclosure` output rather than invented.
- **`46ea089` separately left three stale assertions in the spec**, which is what
  the run would have failed on next: the Help page title changed from "Help
  Center" to "Help", and "Popular walkthroughs" and "Ask Beacon Support" were
  deleted with the marketing content they belonged to. The spec now asserts what
  the page says -- including "Known limitations" and its pointer at
  `docs/QUANT_REVIEW_2026-09.md`, which is why the page was rewritten -- and
  asserts the removed content stays removed.
- **The e2e suite fetched live webfonts.** `index.html` links a Google Fonts
  stylesheet and `src/styles/index.css` `@import`s the same URL, so every page
  load made third-party requests that `apiMocks.js` did not cover. This was *not*
  the cause of the failure above -- the trace shows the fonts resolving, and the
  only 404 is `/disclosure` -- but a suite whose result depends on a third party
  being reachable from a runner is a suite that will produce a red herring
  eventually, and the spec's fail-on-any-console-error handler is exactly how it
  would surface. Both hosts are now served locally: an empty stylesheet and a 204
  for the font files. No assertion measures typography, so glyph fallback costs
  nothing.
- **The same omission is now a named failure instead of a confusing one.**
  `scripts/check_e2e_api_coverage.mjs` runs the mock's real route handler against
  every `fetchApi` endpoint in `frontend/src` and reports the ones that fall
  through, with the file that calls them. Frontend CI runs it *before* Playwright,
  and `backend/tests/test_e2e_api_coverage.py` runs it in the backend suite
  (skipping if node is absent). It found three further endpoints the suite does
  not reach, which are declared in the script with the reason, in the disposition
  style of the reachability census -- a declaration that stops being true fails
  the check. This class of defect had already happened once before: the
  unmocked-notifications comment in `apiMocks.js` records it.

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
