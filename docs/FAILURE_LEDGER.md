# Failure ledger

Every material failure BEACON has found in itself — bugs, licence violations,
unreachable criteria, negative scientific results, infrastructure that lied —
with how it was detected, what it cost, what was done about it, and where the
evidence lives. The platform grows by chasing errors, faults and misleads and
fixing them one by one; this file is the record of the chase.

## Rules of the ledger

1. **An entry is opened when the failure is confirmed**, not when it is fixed.
   Negative results are entries too: a published NO is a finding, not an
   embarrassment, and it is recorded with the same discipline as a bug.
2. **An entry closes only when its mitigation is merged and verified** (test,
   CI gate, or tagged run). "Will fix" is a status, never a closure.
3. **Evidence is a pointer, not a narrative**: CHANGELOG entry, tagged
   pre-registration, probe document, or test name. If an entry has no pointer,
   it is not ready to be written.
4. **Nothing is silently deleted.** Withdrawn data keeps its removal note;
   published history (git tags, run reports) is never rewritten.

Statuses: **FIXED** (mitigation merged + verified) · **RECORDED** (published
result; no code fix applies) · **PARKED** (deliberate suspension with recorded
resumption axes) · **WITHDRAWN** (artefact removed, note kept) · **OPEN**.

---

## A. Scientific negative results (the early-warning line)

**L-1. Crisis early-warning v1: the family was too thin to grade.**
Of six publicly-fetchable candidate indicators, only the 10y–2y yield curve
survived the declared quality rules (others weekly/monthly, too short, or
licence-blocked). One indicator is below the declared family minimum of three,
so no system-level claim was gradeable. Detected by: the frozen quality gate
inside the tagged run. Mitigation: published unchanged; v2 curated a real
family (10y–3m, VIX) with directions declared pre-fetch. Status: **RECORDED** —
tag `prereg-early-warning-v1`, `docs/prereg/runs/early_warning_v1/report.md`.

**L-2. Crisis early-warning v1: the one testable indicator failed.**
10y–2y warned early (median 42 business days) but fired 9.6 false alarms per
quiet year against a ceiling of 4, and naive persistence slightly beat it.
Mitigation: published unchanged — the README claim ("not a demonstrated
early-warning system") kept, now with tagged evidence. Status: **RECORDED** —
same pointers as L-1.

**L-3. Crisis early-warning v2: 0 of 3, and the criterion was unreachable.**
All three indicators failed the false-alarm ceiling (~9–10 per quiet year vs
≤4). Post-run arithmetic showed the frozen q95 alarm rule made the ceiling
unreachable for *any* indicator at the observed precision (23–29%) and base
rate (~6%): a design incoherence in the protocol itself (see L-19).
Mitigation: the incoherence was published as the run's diagnosis, not applied
retroactively to the numbers; v3 declared a coherent alarm point by arithmetic
on published facts before freezing. Status: **RECORDED** — tag
`prereg-early-warning-v2`, `docs/prereg/runs/early_warning_v2/report.md`.

**L-4. Crisis early-warning v3: 0 of 3 — the line is parked.**
With the coherent q98 alarm point, false alarms fell to 2.7–4.7 per quiet year
(criterion reachable, as declared pre-run) and lead times fell exactly as
declared (medians 42→10, 18.5→10, 11.5→8 days; VIX fell through the frozen
≥10-day floor). `FRED_T10Y3M`'s frozen TAN missed passing on the
false-alarm criterion **alone, by 0.2** (4.2 vs 4.0) — published as a fail,
because loosening a ceiling after seeing the number is the goalpost-move
pre-registration exists to forbid. The frozen onset-hazard logit failed
out-of-sample on both spreads (AUC 0.39/0.44): an 18-year extrapolation of a
pre-2006 fit does not survive the QE-era regime change. Persistence remains
unbeaten on VIX (0.9265 vs 0.9257). Under the terminal clause frozen before
the run, the line is **parked**; recorded v4 axes (not deviations): rolling
refits and weekly/monthly tracks admitting the BIS credit-gap/DSR family. Any
resumption is owner-initiated, a new protocol, frozen before its run.
Status: **PARKED** — tag `prereg-early-warning-v3`,
`docs/prereg/runs/early_warning_v3/report.md`, README claim gate.

**L-5. The backtest event path measured the wrong thing, twice.**
(a) Alignment: event labels were joined to risk scores by naive truncation
(`events[:len(scores)]`), shifting every label by the sequence warm-up (~30
business days) — larger than the lead times being measured, so a 20-day
warning read as simultaneous and vice versa. (b) Direction: for
`direction=-1` series (stress = *falling* values, e.g. the yield curve) the
raw score's wrong tail was scored as stress. Detected by: building the
pre-registration runner against the existing event path (v1 freeze). Impact:
every event-path metric computed before the fix was meaningless; no published
claim depended on them (the prereg line started after). Mitigation: labels
join through the documented `row_offset` contract; direction-aware tail
scoring; regression tests. Status: **FIXED** — CHANGELOG (4.0.0 block),
PR #80.

**L-6. A frozen-forever scorer and a hazard architecture are a poor pairing.**
The literature's early-warning models are refit on rolling windows; v1–v3
froze one model on pre-2007 data and extrapolated 18 years. The hazard logit's
out-of-sample collapse (L-4) is the measured cost of that choice. Recorded as
the finding it is; rolling refits are a v4 axis, deliberately outside the
frozen protocols' discipline. Status: **RECORDED** — v3 report, README gate.

**L-26. Crisis early-warning v4: family NO (1 of 5) — the line stays parked,
and both recorded axes are now empirically closed.** The owner-initiated
resumption tested rolling annual refits and weekly/quarterly tracks (the BIS
credit-to-GDP gap admitted at last, 1957-Q4 onward, licence GREEN). Verdict:
1 of 5 indicators passed against a rule requiring at least half — the claim
gate stays closed. The run produced the record's **first criteria-passing
pair** (`FRED_STLFSI4` weekly via the *frozen* hazard logit: AUC 0.922,
0.48 FA/quiet-year, 2-week median lead, both baselines beaten, p=0.001,
Holm-surviving) — published as a fact, never upgraded into a system claim.
Measured findings, all pre-declared as possible outcomes: rolling refits did
not rescue the daily family (T10Y3M's rolling TAN got *worse*), closing the
regime-drift hypothesis for these indicators; the quarterly credit gap was
weak under this operationalisation (3 labelled events — under-powered by
construction); the frozen hazard beat its rolling counterpart on the passing
indicator, the opposite of the v3 diagnosis' expectation. Reproducibility
held a fourth time (6/6 shared frozen pairs byte-identical to v3). Two
pre-metric executor defects (licence-line extraction; a grid mismatch that
doomed every indicator) were found, fixed with pinned tests, and documented
with diffs — attempts 1–2 produced zero metrics, so the restarts are within
the run rules' documented-defect clause, recorded in full in the execution
log. Status: **PARKED** (four-run record; no planned v5 — resumption needs a
new owner decision and new recorded axes) — tag `prereg-early-warning-v4`,
`docs/prereg/runs/early_warning_v4/report.md` + `execution_log.md`.

**L-27. Crisis early-warning v5: family NO (2 of 11) — the wider family
produced a second pass and the same verdict, and the line stays parked.**
The owner initiated the second resumption (2026-09-18: "wider data collection
from multiple sources") — the family axis the four-run record kept
diagnosing. Criteria-first probe admitted five new series across four tracks
and three publishers (11 testable; DTWEXBGS excluded RED on history length,
the NY Fed recession probability RED on transport — both recorded, not
substituted); no grading criterion changed; the declared pre-run consequence
held: the wider family made the family rule HARDER (≥6 of 11 needed).
Verdict: 2 of 11 passed — `FRED_STLFSI4` (reproducing its v4 pass
byte-identically) and new `FRED_DCOILWTICO` (WTI crude, daily, frozen hazard
logit: AUC 0.813, AP 0.309, 14.5-business-day median lead, 1.14
FA/quiet-year, both baselines beaten, p=0.001, Holm-surviving across the
44-pair pool) — published as facts, NOT upgraded into a system claim. The
claim gate stays closed; under the outcome handling frozen before the run the
line **remains parked with a five-run record; there is no planned v6.**
Measured findings: the frozen hazard logit is the only scorer that has ever
passed (2 of 2; rolling refits again rescue nothing — that axis is now closed
by two independent runs); the monthly track starves the lead criterion (KCFSI
AUC 0.917, zero detections inside its 2-month max_lead; FEDFUNDS p=0.031 does
not survive Holm at the wider pool — multiplicity working as designed, not a
defect); NFCI is significant yet persistence still beats it; T10Y3M's frozen
TAN missed the FA ceiling by 0.2 for the third consecutive run, identically.
Reproducibility held a fifth time at its strongest: 20/20 shared v4 pairs
(5 indicators × 4 scorers, frozen AND rolling) byte-identical on fresh
fetches. Single attempt, run detached (the v4 process-group lesson applied),
zero retries, zero pre-metric defects. Status: **PARKED** (five-run record;
resumption needs a new owner decision and new recorded axes) — tag
`prereg-early-warning-v5`, `docs/prereg/runs/early_warning_v5/report.md` +
`execution_log.md`.

## B. Data and licence compliance

**L-7. The repo committed data its licence prohibits reproducing.**
v1's fetch phase captured 339 rows of the ICE BofA US High Yield OAS series
(`data/prereg/FRED_BAMLH0A0HYM2.csv`) as "provenance". The series was skipped
before any metric existed (insufficient coverage), so no result ever consumed
the bytes — but ICE Data Indices' terms (read in full during v2's licence
screen) prohibit reproduction in any form and furnishing the data to third
parties; committing the capture was itself the violation. Detected by: v2's
licence screen, which reads each series' own FRED notes and refuses to
download prohibited series — it caught this one on first use. Mitigation: file
withdrawn at HEAD with `data/prereg/REMOVAL_NOTE.md`; published history not
rewritten (reachable at tag `prereg-early-warning-v1`); frozen v1 manifest
left byte-identical; licence-before-download is now a permanent rule of the
runner and recorded in the protocol YAML. Status: **WITHDRAWN**, guard
**FIXED** — CHANGELOG (4.0.0), PR #84.

**L-8. FRED's HY OAS window makes the series unusable for long evaluations.**
Independent of licence: FRED now serves everyone (key or no key) only a
rolling ~3-year window of the series (`observation_start` 2023-09-18 observed
2026-09-17), disqualifying it from an 18-year evaluation. Mitigation:
recorded; the credit-spread axis moves to the weekly/monthly v4 track if the
line resumes. Status: **RECORDED** — v2 removal note + report.

**L-9. The BoE's published terms-of-use URLs were 404s.**
The plugin shipped with the reuse licence recorded as *unconfirmed* everywhere
rather than guessed. Detected by: live probe of both candidate URLs.
Mitigation: the real page was later found (`bankofengland.co.uk/legal`,
accessed 2026-09-18): Database data is **UK Open Government Licence v3**, with
required attribution and scope caveats (third-party-owned series such as LSEG
spot-FX excluded; SONIA-family carries its own statement). Plugin docstring,
provenance record and probe document updated; a pinned test asserts the
confirmed licence appears in the provenance record. Status: **FIXED** —
`docs/probes/boe_endpoint_probe.md`, PR #88.

**L-10. Credentials were pasted in plaintext chat.**
The GitHub PAT and FRED API key travelled through the working channel in clear
text. Mitigation in-repo: both were used environment-only, never written to
any tracked file (grep-verified at every phase), recorded endpoints redact
`api_key=<redacted>`, and `.git/config` is token-free. Mitigation owner-side:
**rotate both** — until confirmed, treat both as burned. Status: **OPEN**
(owner action).

## C. API and engine honesty bugs

**L-11. The v2 predictions API fabricated scores.** `_extract_nodes` coerced
a missing score to `0.0` and fell back to "any numeric column, scanned
backwards" — on a refused row that would serve epistemic variance as a risk
score, or hand NaN to a strict JSON encoder (a 500 the moment the first
refusal shipped). Detected by: the refused-row contract work. Mitigation:
scores are `risk_score`, else `prediction`, else `null`, with the uncertainty
state beside it; refused-row tests. **This is a breaking semantics change to
`GET /api/v2/predictions/{job_id}`** — consumers relying on a score always
being present break — and is the recorded justification for the 4.0.0 MAJOR
bump. Status: **FIXED** — CHANGELOG (4.0.0), `docs/api.md`.

**L-12. The transparency card asserted a blanket "not calibrated".** The
explainability endpoint's uncertainty block claimed every job's confidence
fields were null while split-conformal intervals had been computed per source
since 2026-09-14. Detected by: whole-repo claim audit. Mitigation: the card
derives its status from the job's actual per-source `confidence_methods`
counts. Status: **FIXED** — CHANGELOG (4.0.0).

**L-13. README claims drifted from the code, in both directions.** Three
stale claims found by the whole-repo audit: "no semantics registry" (one
exists and gates event labelling; an undeclared direction is a refusal),
"nothing persists risk scores/metrics" (both are persisted), "calibrated
intervals are not reported" (they are, per source, where residuals support
them). Mitigation: text now states what the code does, with pointers; the
audit that found them is repeatable. Status: **FIXED** — CHANGELOG (4.0.0).

**L-14. Feasibility memos described infrastructure that does not exist.**
The MoE memo claimed a prediction store with a `regime_label` field and a
regime-tracking model registry; the temporal-GNN memo claimed per-cycle
exposure networks and versioned balance sheets. None existed. Detected by:
the parked-features census cross-check. Mitigation: memos rewritten to state
the platform as it is; the BoE probe memo was explicitly marked
planned-not-executed until the probe ran. Status: **FIXED** — CHANGELOG
(4.0.0), `backend/tests/test_reachability.py` census.

**L-15. Dead weight constructed on the hot path.** The training task built an
orchestrator it never called; `bis_plugin` carried an unused `base_url`;
`bank_analyzer` claimed a vectorisation it did not do. Mitigation: removed /
docstring corrected. Status: **FIXED** — CHANGELOG (4.0.0).

**L-28. `indicator_observations` had a documented writer and no production
one.** The README's storage bullet named the hypertable, its continuous
aggregate and `observations_as_of` re-derivability, and `record_observations`
with its vintage log existed behind store tests — but every real collection
wrote parquet plus job-result JSON, so the table stayed empty in production
(class "mislead"). Detected by: the review tracing each documented writer to a
call site. Mitigation: `persist_observations` (`tasks/job_tasks.py`) runs in
`run_data_collection` after the gate certifies the package, upserting scalar
indicator rows with plugin type, catalogue code, region, the gate's quality
score and the ingest job id, appending a vintage per write; panel and asset
rows are skipped and counted rather than silently collapsed on the (time,
source, indicator, region) key, invalid rows and unmapped codes are skipped and
counted, never zero-filled; a storage failure degrades to a warning like the
other writers, and the counts travel in the job result. The README now names
the writer. Status: **FIXED** — CHANGELOG (Unreleased), PR #102,
`backend/tests/test_observation_writer.py`.

**L-29. The Data Quality page aggregated a table the documented production
path never writes.** All three `/api/v1/data-quality/*` endpoints took their
scores from `DataJob ⋈ PipelineJob` — rows only `POST /api/v1/pipeline`
creates, on a route the frontend never calls — while every real collection
(jobs API, manual sync, scheduler) stores its verdict in `Job.result` and its
source in `Job.parameters.data_source_id`: the page showed zeros on exactly the
deployments the README documents. Two numbers in the same endpoints were
vacuous by the same mechanism — `low_quality` counted against a 0.5 threshold
on 0–100 scores, so nothing was ever counted, ever (class "infrastructure lie",
cf. L-18), and `avg_completeness` was multiplied by 100 although both writers
already store the gate's percentage, so a 97% panel read 9700%. `docs/api.md`
described a removed `0.4/0.3/0.3` analyzer blend (class "mislead", cf. L-13).
Detected by: the same review, one endpoint at a time. Mitigation: the endpoints
read both writers through one shared `quality_evidence` helper (JSON parsed
Python-side for SQLite/PostgreSQL parity), the threshold is read from
`QualityPolicy.min_quality_score` instead of restated, freshness maths
normalises SQLite's naive timestamps via `_ensure_utc`, and the API doc
describes the gate-owned composite. Status: **FIXED** — CHANGELOG (Unreleased),
PR #103, `backend/tests/test_data_quality_routes.py`.

**L-30. `POST /api/v1/pipeline` ran the whole run inside the API process.**
DATA → ENGINE → RESULTS executed as a FastAPI BackgroundTask: no queue
visibility, no worker supervision, the entire run lost silently on an API
restart, torch stages competing with request handling — and `scheduling.py`
could claim "exactly one collection path" only because this second path was
invisible to it. Mitigation: the route dispatches the `run_pipeline` Celery
task through a thin transport wrapper, stage logic kept in `_execute_pipeline`
(which `test_pipeline_integration` exercises directly); a dispatch that cannot
reach the broker marks the PipelineJob FAILED with the reason instead of
leaving it pending forever — a queued run that never queued must not read as
health. Status: **FIXED** — CHANGELOG (Unreleased), PR #104,
`backend/tests/test_pipeline_route_dispatch.py`.

**L-31. The validator's integrity findings were advisory: the enforcement
branch was dead code.** `ValidationReport.critical_errors` was declared and
never incremented, so the orchestrator's "filter out datasets that failed
critical validation" branch was unreachable, and its filter (`not v.empty`)
dropped frames the collector already refuses rather than the offenders.
Duplicate timestamps (ambiguous which value is right) and future timestamps
(look-ahead at ingest) are integrity breaches by the validator's own contract,
and they reached the engine unfiltered. Mitigation: the report names the
offenders (`critical_datasets`, per-dataset `errors`), the orchestrator excludes
exactly those, alerts the operator through the data-quality notification sink,
and fails the run only when nothing remains — a reduced panel with an alert,
never a silent one. Statistical findings (outliers, scale breaks, stale runs)
stay warnings by design: they are evidence about a series, not ambiguous rows.
Status: **FIXED** — CHANGELOG (Unreleased), PR #105,
`backend/tests/test_validator_anomalies.py`.

**L-32. The quality gate's stationarity scan tested an interleaved mixture
instead of the panel grain.** After #100 and #101 put entity grain into the
validator and the formatter, `_stationarity_checks` still ran KPSS over the raw
value column: for a panel frame — interbank edge tables, per-bank features —
that concatenates different entities into one series, the verdict is
statistically meaningless. Harmless while stationarity is report-only; blocking
on legitimate data the moment a deployment sets `require_stationarity=True`.
Mitigation: the scan groups by the *same* identity registry the validator and
formatter use (extracted to `validator.identity_columns`; the formatter's
duplicate copy delegates), date-orders values within each entity, and assesses
up to `KPSS_PANEL_SERIES_CAP = 25` entity series — a deterministic equispaced
sample of the sorted keys when a panel is wider — with the check detail naming
what it actually saw ("assessed 25 of 4,548 entity series…") and the offending
edges. Per-entity degenerate series are counted, not failed; scalar frames
report exactly as before. Status: **FIXED** — CHANGELOG (Unreleased), PR #106,
`backend/tests/test_stationarity.py`.

**L-33. Per-item collection retries were bounded by attempts while the cost
was wall time.** `_fetch_with_retry` stopped after 3 attempts, but each attempt
rides `ResilientSession`'s own retries (up to 4 urllib3 retries with backoff,
timeouts up to 30 s each), so one catalogue item could spend ~7 minutes against
a struggling provider while the beat tick enqueues every five, and a
multi-item source serialises behind it. Mitigation: retries also stop at
`BEACON_FETCH_RETRY_BUDGET_SECONDS` (default 120; an invalid override falls
back with a warning). Tenacity evaluates stop conditions *between* attempts, so
a legitimately long single fetch — ECB paging — is never cut off mid-flight; it
is further retries past the budget that stop. Status: **FIXED** — CHANGELOG
(Unreleased), PR #108, `backend/tests/test_data_pipeline_stages.py`.

**L-34. A cache-served "success" cleared the backoff of a feed that was
down.** The HTTP layer's stale-on-outage fallback is a sound availability
trade, but it made a collection in which the provider was unreachable
end-to-end indistinguishable, in telemetry, from a fresh fetch:
`record_sync_success` cleared the failure streak — which *is* the scheduler's
backoff — and stamped the source healthy while every row came from yesterday's
cache. Mitigation: the fallback is witnessable at three levels —
`ResilientSession.stale_fallback_hits` counts serves and the response carries
`X-Beacon-Stale-Fallback: 1`; the collector reads the plugin's session after
each fetch and records the item in `CollectionReport.degraded`, so it is still
collected but flagged, and the flag travels in the job result;
`record_sync_success(..., degraded=True)` stamps duration, rows and
last-successful while keeping the failure streak and leaving a note beside the
source. The next genuinely fresh success clears both. Status: **FIXED** —
CHANGELOG (Unreleased), PR #109, `test_plugin_http_client.py`,
`test_data_pipeline_stages.py`, `test_sync_scheduler.py`.

**L-35. `/api/v1/analytics/*` read the same table production never writes, in
three places — L-29's twin, one PR and one page later.** #103 moved the
data-quality endpoints onto both writers and left the analytics routes on
`DataJob ⋈ PipelineJob`: the overview card, the `quality` and `completeness`
trend series, and the `quality_degradation` anomaly detector. On every
deployment the README documents the "Data Quality Metrics" card reported 0 while
collections succeeded and their gate verdicts sat unread in `Job.result`, and a
90 → 40 slide could not be reported because the detector had nothing to compare
— a guard that cannot fire is worse than no guard. No test requested
`/api/v1/analytics/*` before this, and `test_frontend_contract.py` waives the
analytics and data-quality shapes as untyped, which is how the gap survived
every contract check. Mitigation: all three consumers read
`data_quality.quality_evidence`, renamed public for exactly this reason — one
evidence list, three consumers, #106's precedent — and
`backend/tests/test_quality_unit_contract.py` seeds job-path collections and
asserts the card, both series, and the anomaly firing; verified to fail three
tests against the pre-fix readers. Status: **FIXED** — CHANGELOG (Unreleased),
PR #111 (`36a85c4`, merged `fe70ddd`); dispatched deep runs green at the branch
commit (backend-tests `35739396990`, frontend-e2e `35739400886`).

**L-42. Panel windows were grouped per entity but standardized per feed, so a
10² entity was scored at 10⁶.** #101 gave the trainer the panel grouping the data
needed (`series_column = 'series_id'` when the frame carries one) and left the
statistics keyed by `source_code`; a sample carried only its feed id. Inside a panel
feed one map — whichever group wrote last at the feed label — standardized every entity
and reversed every prediction back out. Two consequences, both measured on a
two-entity fixture (levels 100 and 1 000 000 in one feed): the smaller entity's history
collapses to a near-constant in the model's space (spread 0.16 in standardized units,
target mean ≈ −19.9, far outside the O(1) space the other series occupy), and its
predictions and errors are reversed through the larger entity's scale. The red
baseline's `predictions.csv`: `actual 96.375, predicted 1004496.90, error
-1004400.500, pct_error 1.042180e+06` beside `actual 983953.100, predicted
1014015.94` — and `Job.result`'s feed-level MAE/RMSE were the story of the wrong
entity. Detected by: `backend/tests/test_panel_normalization.py`, written red first;
12 of 13 failed on `main` at `0122bea`, each on a missing contract (`stats_grain`,
series-keyed statistics on a series-grouped dataset, per-sample series identity, the
`series` column, `per_series_metrics`, the manifest grain, the orchestrator's grain).
Mitigation, one invariant: **the grain of the normalization statistics must match the
grain of the grouping, and where they cannot agree the run says so instead of inventing
a number.** `stats_grain` is recorded on the dataset and in `best_model.pt` (with
`series_ids`); each sample carries its series id beside its feed id so a shuffled
loader cannot mislabel a prediction; `denormalize(values, series_ids=...)` reverses
through the sample's own series and refuses an id it never standardized, keeping the
feed-keyed path only where the grains agree; an evaluation series with no
training-split statistics is skipped rather than standardized with another series' map;
`per_series_metrics` is reported beside `per_source_metrics` in
`training_history.json`, `MultiScaleTrainingMetrics` and `Job.result`.
`EngineOrchestrator` looks up at the checkpoint's declared grain, keys
`stats_provenance` by series label, and labels a feed-grain manifest serving entity
windows `"checkpoint_feed_grain"` with one warning per load. Status: **FIXED** —
CHANGELOG (Unreleased), PR #113, `backend/tests/test_panel_normalization.py`.

**L-43. `predict_risk_series` collapses a panel feed into one fabricated series, and
its consumers read those labels as feed codes.** L-42 fixed the statistics grain on the
training path and in the orchestrator's scoring loop, which groups by `series_id`.
`RealPredictionEngine` has no series concept: `predict_risk_series` groups
`working.groupby('source_code', sort=True)`, so a panel payload is scored as a single
series whose window interleaves entities, and `_predict_single` reports one row per
source. The grouping was deliberately **not** changed in #113 because the blast radius
is a contract change rather than a bug fix: `RiskSeriesResult.sources`/`n_sources`, the
walk-forward segment labels, `by_source` event metrics, risk-score persistence, and
`job_tasks.py`'s joins of `frame["source"]` to `test_data['source_code']` all treat
those labels as feed codes. What #113 did instead: the engine records `stats_grain`, and
a series-grain checkpoint consulted by feed label no longer borrows an entity's scale
— it normalizes the window from its own observations and warns once that the grains
disagree (`test_panel_normalization.py::TestPredictionPathReportsItsGrain`). Status:
**OPEN** — the grouping decision belongs to a change that updates the consumers in the
same breath; found while fixing L-42 and left out of that PR's scope on purpose.

## D. Test and CI infrastructure that lied

**L-16. The deep backend suite could not start at all.** The sharded rewrite
of `backend-tests.yml` put `${{ }}` inside a flow mapping (invalid YAML —
every run failed with zero jobs), restored only `~/.cache/uv` while
dependencies lived in another job's site-packages, passed `-n auto` without
pytest-xdist declared, and its shard globs silently dropped four test files.
Detected by: attempting to run deep CI. Impact: the "green" signal was absent,
not passing. Mitigation: workflow repaired; the dropped files re-included;
suite verified end-to-end. Status: **FIXED** — CHANGELOG (4.0.0).

**L-17. The deep e2e suite could not install its browser.** The parallel
rewrite dropped `npx playwright install`, cached the browser under a
versionless key, and built a `dist/` no test consumed (the suite runs against
the Vite dev server); it claimed ~20 min where the proven single job measures
~1.2 min. Mitigation: reverted to the proven job, kept the three-way spec
split, comment corrected. Status: **FIXED** — CHANGELOG (4.0.0).

**L-18. The bundle-budget gate was permanently tripped and blind.** It read a
`dist/stats.json` that `vite build --stats` does not produce and budgeted the
"largest route chunk" as the largest of *all* chunks — the 957 kB
`deck-vendor` against a 40 kB budget — so it could never surface the 33 kB
route-chunk regression it exists for. Mitigation: chunks classified the way
`vite.config.js` creates them. Status: **FIXED** — CHANGELOG (4.0.0).

**L-19. The v2 protocol froze criteria that contradicted each other.**
A protocol-author error: the false-alarm ceiling (≤4/quiet-year) and the
alarm rule (top 5% of scores at ~23–29% precision, ~6% base rate) were each
reasonable and jointly unreachable — no feasibility check was run between the
criteria before freezing. Detected by: arithmetic on v2's own published
numbers. Mitigation: v3 declared its alarm point by pre-run arithmetic on
published facts; the lesson is a standing rule — **criteria must be
feasibility-checked against each other before a freeze, using only published
numbers**. Status: **FIXED** (process) — v2/v3 reports.

**L-20. The e2e suite depended on the live internet.** `index.html` and
`index.css` pulled Google Fonts, uncovered by the API mocks; any stalled font
request reddened an unrelated assertion. Mitigation: the display face is
self-hosted; font requests answered locally (empty stylesheet / 204).
Status: **FIXED** — CHANGELOG (4.0.0).

**L-21. Assorted tests asserted the wrong thing.** `pages.spec.js`
control-room navigated to a page other than the one it asserted on;
`test_alert_evaluator` failed on a second run (non-idempotent `_clean`
fixture); the Pool teardown guard died while guarding;
`test_migrations_live` asserted the wrong error class. Mitigation: each
corrected with the intent stated. Status: **FIXED** — CHANGELOG (4.0.0).

**L-22. A task snapshot overwrote `.gitignore` and leaked the artefact
class.** Build artefacts became trackable; `docs/api-endpoints.md` had been
hand-edited into drift. Mitigation: `.gitignore` restored; a milliseconds-long
index check (`git ls-files` against artefact patterns) fails the fast gate on
any tracked artefact; `api-endpoints.md` regenerated from the live app and
guarded by `test_api_docs_current.py`. Historic `task snapshot <uuid>` commits
remain in published history (not rewritten); the gates prevent the class going
forward. Status: **FIXED** (contained) — CHANGELOG (4.0.0).

**L-36. A test module deleted parents without their children and reddened
`main` two modules away.** The deep run on `main` at `e78f6ba` (2026-09-22)
failed `test_sync_scheduler.py::test_enqueue_creates_the_same_job_a_human_does`
with `assert [76, 87] == [87]` — 1 failed / 2124 passed — while all eight
pipeline merges #102–#109 had passed every pre-merge gate and every targeted
module run. Cause: the new `test_data_quality_routes.py` (#103) clears the
writers its endpoints aggregate, correctly, because those endpoints aggregate
globally — but it deleted `DataSource` rows an earlier module had seeded
*without* the rows pointing at them, and SQLite hands freed parent ids to the
next module's INSERT. The scheduler test's fresh source then selected catalogue
items it never created, and failed as if the scheduler had chosen the wrong
series. The same fixture deleted `PipelineJob` while leaving `EngineJob` and
`ResultJob` behind: the identical defect, two lines apart. Mitigation: both
wipes clear children before parents and every child of a parent they take
(`DataCatalogueItem`, `Asset`, `EngineJob`, `ResultJob`); `test_sync_scheduler`
states the precondition its id carries, so a future leak names itself instead of
reading as a product bug; `conftest.py` now enforces the cleanup convention it
already documents, sweeping every registered FK in `Base.metadata` at the end of
each run and failing the suite with the offending table pair named. Reproduced
locally as the exact CI triple (`test_api_smoke` + `test_data_quality_routes` +
`test_sync_scheduler`, 3.5 s): red before the fix, green after — the record of
why targeted runs cannot see this class at all, and why "targeted pytest: N
passed" on a pipeline PR proves less than it appears to. Product code was left
alone deliberately: hardening `scheduling.collection_parameters` would have
masked the leak. Status: **FIXED** — CHANGELOG (Unreleased), PR #110
(`9453f6b`, merged `41e5a96`); red run `35721165875` at `e78f6ba`, green
dispatch `35726693642`.

**L-37. `CONTRIBUTING.md` promised a safety net the workflows do not
implement.** It said the deep suites run on merges to `main`. `backend-tests.yml`,
`frontend-e2e.yml` and `bundle-budget.yml` trigger on `schedule` and
`workflow_dispatch` only, so eight pipeline merges landed on `main` under nothing
but the sub-minute gates — and a reviewer who believed that sentence had no
reason to dispatch the deep run that found L-36. Detected by: L-36's red run
read against the trigger headers in `.github/workflows/`. Mitigation: the text
now states what the workflows do (nightly, on demand) and the rule the two-tier
design actually requires — a pipeline-, model-, migration- or
API-surface-touching change is proven *before* it merges, by
`gh workflow run backend-tests.yml --ref <branch>` or by the local full suite —
with "don't merge a vacuous green" stated next to the fact that a targeted run
cannot see cross-module state leaks. Wiring Tier 2 into merge is a CI-budget
decision, not a documentation fix, and the gap itself remains by design.
Status: **FIXED** (text) — CHANGELOG (Unreleased), PR #110.

**L-38. The reachability census walks modules, not functions, so a function
rotted under a "wired" verdict.** `as_of_join` is implemented, exported and
covered by `tests/test_pit.py`, but no production path calls it:
`PITStore`/`Observation` are wired through the bilateral-exposure store
(`load_as_of`), while the join waits on the event-metrics feature attach. The
census's module-level verdict for `backend.modules.data.pit` hid the
function-level gap — the exact silence the census exists to prevent, one
granularity down (same class as L-14: infrastructure a document implies exists).
Mitigation: the module docstring carries the status and an explicit `decide`
disposition — wire it into the backtest feature path, or delete it — and the
census entry for `backend.modules.data.pit` names the gap and the disposition,
so the next pass inherits a decision to make instead of an ambiguity to
rediscover. Status: **FIXED** (the blindness) — CHANGELOG (Unreleased), PR #107,
`backend/tests/test_reachability.py`; the disposition itself is **OPEN** as an
owner decision.

**L-39. The quality unit was declared nowhere, and the only tests that could
have seen it asserted labels, never a number.** The gate works in percentages —
`QualityPolicy.min_quality_score = 70.0`, `min_completeness = 80.0`,
`completeness = 100 * (1 - missing_ratio)` — `Job.result` stores those numbers
and every endpoint returns them verbatim, while three frontend readers treated
them as 0–1 fractions: `DataQuality.tsx` tested its bands against 0.7/0.5 and
multiplied a second time (a real 85.6 rendered as `8560.0%`, coloured
"excellent"), `Analytics.tsx` did the same to both scores, and `Jobs.tsx`
guessed the unit per value (`numeric > 1 ? numeric : numeric * 100`), which made
0.9 and 92 both print 90% and made the disagreement unprovable. The e2e mocks
carried both scales at once — `avg_quality_score: 0.76` beside
`avg_completeness: 92` in one `dataQualityStats` object — and `pages.spec.js`
asserted headings and labels but no number, so a Tier-2 run was green because it
measured nothing (same class as L-21 and L-18). Mitigation: mocks carry
gate-scale values, the readers render them verbatim against the policy floors,
`types/api.ts` and `docs/api.md` state the unit, and the specs assert
`76.0%`/`92.0%`/`88.0%`/`82.0%`/`90.0%` plus "no percentage with a four-digit
integer part anywhere on either page" — 7 Playwright tests pass with the fix, 2
fail with the old readers restored; `test_quality_unit_contract.py` pins the
scale at the boundary and both writers at each analytics reader. Recorded rather
than silently reinterpreted: the only alert rule this repository's suite
evaluates compares `quality_score` against `0.8`, so a data-quality floor
written that way can never breach a gate-scale score; the suite pins both
dispositions (`lt 0.8` reports "ok" on a 42.0 dataset, `lt 70` triggers on the
same data). Re-basing any operator-written rule is an owner decision, not a
migration in disguise. Status: **FIXED** — CHANGELOG (Unreleased), PR #111
(merged `fe70ddd`); the `0.8` consequence is **OPEN** (owner action) regardless
of the merge.

**L-40. The frontend suite is deterministically red locally and green in CI on
the same commit.** Three tests in `frontend/tests/results.spec.js` — "predictive
validity report card on Results", "volatility baselines card on Results", "a
refused prediction renders as absence, never as a number" — fail on a pristine
local `main` with React's "Maximum update depth exceeded" at the Results page,
while the `frontend-e2e` nightly on the same SHA passed (run `35706057051`,
`9169be29`, job "Build and Playwright e2e (Node 24)"). Infrastructure that lied
in both directions: a local red that blocks honest local verification, and a
nightly green that has never measured this state. Re-checked on `fe70ddd`: the
local tree still fails those three, the dispatched `frontend-e2e` on that SHA
passed all 15 tests (run `35744391049`). Eliminated, each verified
against the working tree: dependency drift (installed `@playwright/test` 1.56.1,
`react` 18.3.1, `vite` 7.1.12 match `frontend/package-lock.json` exactly), stale
Vite dep cache (cleared, identical failures), a leftover dev server on port 8173
(none), and this change's own edits (a control run on a stashed tree fails
identically). The remaining known difference is Node 22 locally against Node 24
in CI, where `frontend/package.json` declares `engines.node >= 24` — asserted,
not proven. Status: **OPEN** — `frontend/tests/results.spec.js`, runs
`35706057051` (`9169be29`) and `35744391049` (`fe70ddd`).

## E. Release and process hygiene

**L-23. The v3.3.0 release was stranded: cut, but never tagged.** The release
commit (`57db310`, 2026-09-16) moved the changelog block and bumped `VERSION`,
but the annotated tag was never created or pushed — `VERSIONING.md` reserves
tag-pushing to maintainers and the step was simply missed. Detected by: the
pre-4.0.0 audit (2026-09-18) comparing `git tag` against release commits.
Mitigation: tag `v3.3.0` applied at the release commit during the 4.0.0
release; release checklist in `CONTRIBUTING.md` now includes "push the tag".
Status: **FIXED** — this release.

**L-24. Ten months of stale docs nobody could find.** Five documents were
reachable only by knowing their filenames, which is how they stayed stale
without anyone noticing. Mitigation: `docs/README.md` exists as the index;
this ledger and `CONTRIBUTING.md` are registered in it; the whole-repo claim
audit (L-13) is the recurring sweep. Status: **FIXED** — `docs/README.md`.

**L-25. The 4.0.0 release left a generated doc stale.** `docs/api-endpoints.md`
embeds the application version; the release bumped `VERSION` to 4.0.0 but the
regeneration step was not part of the release tooling, so the committed
inventory still claimed v3.3.0. The fast CI gates do not include the
inventory check (the deep suite does), so the release merge looked green —
the staleness was caught by the first full-suite run after the release,
before it could reach a nightly. Mitigation: the inventory was regenerated
(one-line diff) in the v4-freeze change; the `CONTRIBUTING.md` release
checklist now carries "regenerate `docs/api-endpoints.md` immediately after
`release.py`" as a numbered step; a release-tooling guard (fail when the
generated inventory disagrees with `VERSION`) is recorded as the durable fix
if this class recurs. Status: **FIXED** (tooling guard: OPEN, deliberately
deferred until a second occurrence justifies touching the release script).

**L-41. Five merges landed after v4.0.0 with no changelog entry.** #97 (plugin
configuration and provider hardening), #98 (ECB/FRED/SEC collection hardening,
with a catalogue migration), #99 (explicit partial collection runs), #100 (panel
and filing grains) and #101 (frequency and series boundaries) all touch
`backend/`, and none of them touched `CHANGELOG.md`: `git log v4.0.0..HEAD --
CHANGELOG.md` begins with #102's commit. The consequence is not cosmetic.
`## [Unreleased]` is the pointer this ledger and the next release note read, so
the two grain fixes appeared only as background inside L-32, and a release cut
from this block would have omitted them — and no gate enforces "land work under
`## [Unreleased]`", so nothing would have noticed a sixth. Mitigation: the five
entries were written back into `## [Unreleased]` from their merge commits and
diffs rather than from memory, and every entry in this batch carries its PR
number from `git log`/`gh pr list` rather than from the changelog. The durable
fix is the same one L-25 deferred — a release-time check that the changelog and
the merge history agree — still unowned. Status: **FIXED** (backfill) —
CHANGELOG (Unreleased); the gate for this class remains **OPEN**.

---

*Adding an entry: open it when the failure is confirmed, with a pointer; close
it only when the mitigation is merged and verified. The CHANGELOG records what
changed; this ledger records what went wrong and what we did about it — both,
always, in public.*
