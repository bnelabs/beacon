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

**L-57. A transient World Bank timeout killed an entire strict collection
run because the plugin misclassified it as empty data.** `world_bank_plugin`
caught *all* exceptions and returned `None`, which the collector reads as
"empty dataset" — and `EmptyDatasetError` is not retried (only
`DataSourceUnavailableError` is: 3 attempts, 120 s budget). Job 14, the first
2000–2026 strict run, failed on a single 30 s read timeout to
api.worldbank.org (`WB_DOMESTIC_CREDIT_ZA`); the upstream data was verified
live seconds later (< 1 s, 25 non-null rows 2000–2024). Detected by: the
2026-09-24 review (F1), with the live probe as the witness. Mitigation: the
plugin now distinguishes 4xx (indicator not in catalogue → `None`, a
decision) from `requests.RequestException` (timeout, connection failure, 5xx
→ `DataSourceUnavailableError`, retryable), mirroring the SEC plugin.
Status: **CLOSED** — fixed in 6.1.0 (PR #143): the plugin now
distinguishes 4xx (`None`) from transport errors (`DataSourceUnavailableError`,
retryable). Verified: job 15 (the retry of failed job 14) completed 71/71,
and the final packages (jobs 16, 20) completed with zero collection
failures.

**L-58. The SEC 13F catalogue item pointed at a retired filer CIK, so the
holdings series silently stopped in 2024-08.** The item resolved ticker
`BLK` to CIK 0001364742 (BlackRock **Finance**, Inc.), whose last 13F-HR is
2024-08-13; the current filer is BlackRock, Inc., CIK 0002012383 (13F-HR
through 2026-08-07). The collector happily fetched the dead CIK's history —
a stale series presented as current. Detected by: the 2026-09-24 review's
per-source freshness audit (F2). Mitigation: `data_catalogue` id 33
endpoint repointed to `0002012383.13F-HR` (verified in the live DB; job 16
then collected the current 8 filings), and `KNOWN_SEC_CIKS["BLK"]` in
`sec_plugin.py` corrected with the retired CIK documented. Status:
**CLOSED** — ops fix (catalogue id 33 repointed to `0002012383.13F-HR`,
verified in the live DB; job 16 then collected the current 8 filings) plus
the code hardening in 6.1.0 (PR #143): `KNOWN_SEC_CIKS["BLK"]` corrected
with the retired CIK documented.

**L-59. The IMF plugin's default path pointed at a retired endpoint, and the
two IMF catalogue items could never resolve.** `dataservices.imf.org/REST/
SDMX_JSON.svc` is retired upstream, so the legacy `Database.Frequency.
Country.Indicator` identifiers (items 41 `FSI.A.US.FSIRE_PA_PT`, 42
`IFS.M.US.RAFA_BP6_USD`) could not resolve, and a DataMapper attempt had
been made against the wrong response shape. The current public API is
DataMapper (`/api/v1/{INDICATOR}/{COUNTRY}`, dict-of-dicts of
year→value — verified live; it ignores the country path segment and the
`periods` parameter, so both are applied locally). Probe result: the
DataMapper catalogue (132 indicators) contains **no FSI family at all**, and
its reserve indicators (BRASS_MI, Reserves_ARA/M2/STD/M) are emerging-market
only with no USA data — so items 41/42 have no current equivalent and stay
disabled, with the reason written into their catalogue descriptions rather
than left as silent dead rows. Mitigation: the plugin's DataMapper path is
now correct and typed (4xx → `None`, network/5xx →
`DataSourceUnavailableError`), verified live on `NGDP_RPCH/USA` (27 points
2000–2026). Status: **CLOSED** — fixed in 6.1.0 (PR #143): the DataMapper path is
correct and typed, verified live on `NGDP_RPCH/USA` (27 points 2000–2026).
Catalogue items 41/42 remain disabled with the reason (no DataMapper
equivalent) written into their descriptions — a declared, not silent, gap.

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
**FIXED** (v6.0.0, PR #123) — `predict_risk_series` now groups by `series_id`
when the payload carries one (else `source_code`), so a panel feed is scored per
entity, never as one interleaved series. The model's per-source embedding stays
feed-keyed and normalisation statistics are looked up at the checkpoint's grain.
`RiskSeriesResult` reports `series_ids`/`n_series`, the frame carries both
`source` and `series`, and boundaries mark series seams; the consumers
(target-alignment seams, walk-forward folds, `by_series` event metrics, the
volatility track and the validation report) were updated in the same breath.

**L-45. The vintage reader's `published_at` compared equal in CI but not on SQLite,
because one backend returned the column aware and the other naive.** `vintage_log_001`
writes `published_at` as `DateTime(timezone=True)`. PostgreSQL hands those values back
aware; SQLite's `DATETIME` has no timezone support and hands back a naive one. So the
assertion that pins the backfill's point-in-time contract — `row.published_at == the
certified snapshot's instant` — was True in CI (Postgres) and False on SQLite: a
backfilled vintage could not be verified as carrying the snapshot's capture instant on
any SQLite deployment, and a live re-run would have "fixed" it by accident of backend.
It was worse than an unequal comparison: `observations_as_of` keys a dict on `row.time`
and `sorted()`s the keys, so a mix of naive and aware period keys raises
`TypeError` the moment a value read from one backend meets one read from another. The
row *was* written and the manifest's `created_at` *was* read — the defect was the read
side, not a refused snapshot or a missed rewrite. Mitigation: `UTCDateTime`, a
`TypeDecorator` over `DateTime(timezone=True)` that normalises the read side so the two
provenance tables (`indicator_vintage_log`, `vintage_backfill_runs`) always come back
aware UTC. Storage DDL is unchanged (SQLite writes the same naive-UTC string it always
did; Postgres was already aware), so no migration is needed and existing rows read back
identically; the decorator is scoped to the two tables that carry as-of semantics, so
the latest-value reads are untouched. Detected by:
`backend/tests/test_vintage_backfill.py::test_a_backfilled_vintage_is_published_at_the_snapshot_instant`
(written red first; the `all(row.published_at == PUBLISHED_AT ...)` assertion failed on
SQLite). Status: **FIXED** — CHANGELOG (Unreleased, Added), PR #116,
`backend/tests/test_vintage_backfill.py`, `backend/tests/test_vintage_log.py`.

**L-51. The multi-scale dataset builder silently trained on 11 of 71 series:
the value-column choice read the schema, not the data.** The joined collection
panel carries `Close` (populated by the OHLC series) on every row, so the
frame-wide rule `'Close' if 'Close' in frame.columns else 'Value'` was always
true and every series read `Close`. The 60 value-only series (all FRED rates,
macro, banking, credit, oil, SEC, BIS, World Bank) read all-NaN and were
dropped as "no observed values": job 17 trained on 5 FX, 5 equities and gold
only, while the certified job-16 package carried 26 years of the rest. The
defect was not confined to training: the same rule in the prediction and
backtest paths fed degenerate all-zero input, which the model scored as a
constant equal to its own risk score (e.g. IR_US_10Y `prediction ==
risk_score == -0.1151`, regime `None`) — garbage that presented as a signal.
Detected by: the 2026-09-24 production review (`REVIEW-2026-09-24.md` F9),
cross-checked against the job-16 parquet per series. Mitigation:
`backend/modules/engine/value_columns.py` (`select_value_column` — the first
candidate column with at least one non-null value, checking the data), used
by all six read sites (trainer dataset builder, baseline comparison, risk
series, prediction, and both backtest metric blocks). Verified on the real
package: all 67 scalar series enter training (was 11), 145,715 sequences
(was 14,511). Status: **CLOSED** — fixed in 6.1.0 (PR #143). Verified end-to-end on
the retrained model: jobs 22 and 26 trained 88,844 sequences from 41 sources
(15,179 series) — the rates/macro/credit feeds the old builder dropped are
in the model — and job 28 scored all 71 sources with real per-series values
(no more `prediction == risk_score` constant rows).

**L-52. The rich `ScenarioParameters` were inert on the API simulate path,
and the engine transforms that were reachable were miscalibrated.** The
simulate route applied only legacy `adjustments` (last-N-days on a value
column list) and never called `engine.apply_scenario`, so `rate_cut_bps`,
`failed_bank_id`, `stock_drop_pct`, `interbank_lending_reduction`, … — the
parameters the schema advertises — did nothing; a `type` without parameters
fell through to `custom` and applied nothing either. Even the reachable
transforms were wrong in four ways: rate shocks used `/10000` on percent-scaled
series (under-scaled by 100×) with the sign inverted against the schema
("negative for hikes"); every transform touched only the `Value` column,
missing the OHLC series (`Close`) the market model actually watches; the
`market_crash` price mask matched `STOCK_VIX`, so volatility took a price
drop and a spike in the same run; and `bank_failure`/`liquidity_freeze`
gated on columns (`bank_id`, whole-frame `Value`) the AI4Risk edge frames
do not carry (`source_bank`/`target_bank`). Detected by: the 2026-09-24
review (F6) plus a read of `apply_scenario` against the schema and the real
edge frame. Mitigation: the route now passes `scenario.scenario
.model_dump(exclude_none=True)` through `apply_scenario`; the type is
inferred from the parameters present when absent; `_transform_values`
applies every candidate value column; rate units/sign corrected; edge
frames handled; `regional_shock` without a `region` column logs a declared
no-op instead of failing silently; `combined` recurses into every applicable
subtype. Status: **CLOSED** — fixed in 6.1.0 (PR #143); unit tests in
`backend/tests/test_scenario_transforms.py`. Verified end-to-end on the
6.1.3 model (job 26): all six scenario responses (baseline, market_crash,
rate_shock, liquidity_freeze, bank_failure, regional_shock) echo
`scenario_parameters` verbatim and the transforms demonstrably hit the data
(the non-uniform bank-failure transform moved the AI4RISK topology feed
0.839→0.790). The separate limitation that the *scores* barely respond to
the uniform transforms is recorded as L-62, not left implicit here.

**L-53. The brief report displayed anomaly findings as failed checks.**
`/api/v2/reports/brief/{id}` rendered `anomalies_detected` under the `failed`
key: job 16 showed "failed: 18197" while 71/71 sources were collected and no
quality check failed — 18,197 validator warnings read at a glance as 18,197
failures. Mitigation: `failed` now carries the collection report's failed
count and `anomalies_detected`/`anomalies_fixed` are their own fields.
Status: **CLOSED** — fixed in 6.1.0 (PR #143); the brief report for the
final package (job 20) shows 0 failed checks with the 18,197 anomalies as
their own field.

**L-54. The backtest reported metrics with no ground truth to compare them
against.** The collection package carries no target column, so the backtest
fell through to a "No ground truth column in the test window" note and
reported only prediction statistics — the numbers that decide "is the model
useful" were never compared to anything. Mitigation: `derive_standardized_targets`
pairs each score with the standardized next-step actual of the same series,
standardized on the pre-test window only (standardizing on the test window
would leak the evaluated split into the target; series without pre-test
history get NaN targets and are excluded rather than scored on statistics
they never saw). The derivation is declared in the job result
(`target_derivation`). Status: **CLOSED** — fixed in 6.1.0 (PR #143).
Verified: backtest job 27 (final model) reports `target_derivation`
populated, 25,264 of 26,056 rows aligned to leakage-free derived ground
truth, and real aligned metrics (R² 0.188, directional accuracy 0.449).
Unit tests in `backend/tests/test_backtest_target_derivation.py`.

**L-55. The multi-scale trainer's walk-forward baseline comparison was
permanently `null`.** The trainer honestly reported "not measured" instead of
lifting the model against persistence/AR(1) baselines — so the complexity of
the multi-scale architecture went unpriced while the single-scale trainer
had reported the same metric since round two. The failure mode was the
same value-column defect as L-51: the denormalized baseline series were read
from the wrong column and the comparison blew up. Mitigated by the L-51 fix
(baseline comparison now selects the value column per series). The job-22
retrain (v6.1.1) confirmed the top-level null is
gone — `baseline_comparison` is populated — but every one of its 53
per-source entries was still skipped, so `mean_lift` remained `null` and the
metric was still unmeasured. Offline replay of the walk-forward guard found
why, and it is recorded as L-61: an off-by-one in the window-count check and
a feature reshape the model cannot consume, both in the same never-measured
path. Closed across three releases: 6.1.0 (PR #143, the value-column
fix), 6.1.2 (PR #147, the L-61 defects 1–3), and 6.1.3 (PR #149, L-61
defect 4). Verified: job 26's `baseline_comparison` measures 30 of 65
candidate sources (all 12 compound-id feeds included, the AI4RISK panel
recorded once), with a finite `mean_lift` (−50.06).

**L-56. The simulate endpoint could not run a network scenario at all.**
`engine.predict` accepts `bank_exposures`/`bank_endowments` for the
Eisenberg-Noe clearing, but nothing in the API path built them: a
`bank_failure` or `liquidity_freeze` scenario transformed the frame but
propagated nothing through the interbank network, so the systemic part of
the scenario catalogue was unreachable from the API. Two further facts make
a naive wiring dishonest, and the wiring declares them instead: the AI4Risk
edge orientation is not documented upstream (the wiring reads
`sourceid → targetid` as "sourceid holds a claim on targetid" and says so in
the output), and the dataset carries no balance sheets, so endowments are a
declared fraction of gross total exposure (parameter `endowment_fraction`,
default 1.0; a failed bank's endowment is zeroed — that is the default
event). Mitigation: `_run_network_clearing` in the simulate route clears the
latest quarter of the edge rows through `clearing.clear_multiplex` and
attaches the result with its `declared_assumptions` block. Status:
**CLOSED** — fixed in 6.1.0 (PR #143); unit tests in
`backend/tests/test_network_scenario_clearing.py`. Verified end-to-end on
the 6.1.3 model (job 26): both network scenarios ran the Eisenberg–Noe
clearing and returned a `network_analysis` block with declared assumptions
— liquidity_freeze (4,412 nodes, 0 defaults, total shortfall 0.0, converged
in 1 iteration, 0 contagion edges) and bank_failure (4,401 nodes, 1 default
for bank "0" — insolvency — total shortfall 4,827,005, 717 contagion edges
in round 1, converged in 2 iterations). The ML scores' near-invariance to
the uniform transforms is a separate finding, L-62.

**L-60. The training objective was dominated by degenerate standardization: a
full-panel retrain reached a val loss of 4.2e18 at epoch 1.** The 6.1.0
value-column fix (L-51) brought 60 previously-dropped series into training.
Several of them are constant or near-constant over their training span —
AI4RISK edge series with zero variance and a constant-1.0 SEC series — and
dividing their values by `std + 1e-8` produced z-scores up to 3.1e10 in the
evaluation split. A single such sample contributes ~1e21 to the mean-squared
objective, so it dominated every real signal: job 21's epoch-1 val loss was
4,230,898,264,780,912,128, and model selection on that metric was
meaningless. A second tier — tiny-but-real stds (an AI4RISK edge drifting
1.6e-5 around 0.27 that steps 1.3 in the evaluation split, z ≈ 8e4, squared
error 6.6e9) — would still dominate. It escaped the test suite because the
tests counted sequences but never trained the full panel; the first
full-panel retrain (job 21, cancelled) surfaced it. Detected by: offline
replay of the job-20 panel through the dataset builder (val max |z| was
31,031,680,000 before the fix; 10 after). Mitigation: (1)
`is_degenerate_standardization` in `multi_scale_trainer` — a series whose
training-split relative std is below 1e-6 is skipped from training with a
warning (internal and external statistics paths; an external split also
refuses degenerate training statistics); (2) every standardized value that
enters the model — training inputs, training targets, `_prepare_sequence`,
the `predict_risk_series` windows and `_calibration_windows` — and the
backtest's derived targets is clipped to ±`STANDARDIZED_VALUE_CLIP` (10.0),
so the objective is bounded and training, inference and backtest share one
space. Status: **CLOSED** — fixed in 6.1.1 (branch
`fix/611-degenerate-standardization`); regression tests in
`backend/tests/test_trainer_composition.py` (`TestDegenerateStandardization`)
and `backend/tests/test_backtest_target_derivation.py`
(`test_targets_follow_the_training_clip_law`). The full-panel retrain on
6.1.1 (job 22) shows epoch-1 val loss 10.13 — O(1), where job 21 showed
4.23e18 — model selection picks epoch 3 on that bounded metric, and every
standardized model input and target is bounded by the ±10 clip (clip
warnings fire on the AI4RISK series, confirming the bound is active).

**L-61. The walk-forward baseline comparison still measured nothing, despite
L-55's fix.** Four latent defects sat in the measurement path:

1. **Off-by-one in the window-count guard.**
   `sliding_window_view(values, seq_len)` yields `n - seq_len + 1` windows,
   but `targets_raw = values[seq_len:]` has `n - seq_len` entries — the last
   window ends on the final observation and has no next value to predict.
   The guard `targets_raw.size != windows.shape[0]` was therefore true for
   *every* series long enough to have any windows at all, so every source
   was skipped as "not enough windows" and `mean_lift` was `null` even for
   daily series with 1,300+ windows. In job 22's `baseline_comparison`,
   every entry that had enough data to measure was skipped for exactly this
   reason; the remainder were honest "series too short" refusals (quarterly
   and annual feeds with fewer than 40 test points).
2. **Adapter reshape the model cannot consume.** The frozen-model adapter
   fed the model `(batch, seq_len, 1)` features while its forward takes
   `(batch, seq_len)`. The resulting `RuntimeError` is not caught by the
   `(TypeError, ValueError)` guard in the loop, so the first series that
   had ever survived the window guard would have crashed the entire
   training job.
3. **`mean_lift` aggregated the wrong shape.** `payload["lift"]` is
   `{baseline: {metric: value|None}}`, but the aggregate loop filtered
   its *values* with `isinstance(lift, (int, float))` — always false for
   the per-metric dicts — so `mean_lift` was `null` even once sources
   were measured.
4. **Silent exclusion of compound-id feeds.** The loop resolved each series
   key through `source_to_id` (feed codes) and silently `continue`d on a
   miss. Feeds whose `series_id` carries a compound entity id — all 12
   FX/equity/VIX/gold feeds, the model's strongest series, e.g.
   `EXR_EUR_USD::USD/EUR` — are never feed codes, so they vanished from the
   report without even a skip entry: job 23 measured 19 of 53 candidates
   that did not include any of them. The same silent skip hid the 15k-entity
   AI4RISK panel, which is genuinely too large to walk forward per entity —
   a cost-based exclusion, but one that must be *recorded*, not silent.

Detected by: offline replay of the job-20 test split through the guard
(IR_US_10Y has 1,335 finite test values → 1,305 valid windows, yet job 22
skipped it), an offline end-to-end run of `_baseline_comparison` on the
real job-20 splits (19 of 53 sources measured after fixes 1–3, `mean_lift`
still null before fix 3), and by diffing job 23's measured candidate set
against the package's feed list — every compound-id feed absent.
Mitigation: drop the trailing window so features and targets align 1:1,
reshape the adapter's features to 2-D, aggregate the per-baseline r2 lift
(positive = model beats the baseline), and resolve series keys to feeds
explicitly — measuring single-series compound feeds on their own window and
recording one honest "panel feed" skip per panel feed instead of a silent
drop. Status: **CLOSED** — fixes 1–3 released in 6.1.2 (PR #147),
fix 4 released in 6.1.3 (PR #149). Regression tests in
`backend/tests/test_trainer_composition.py` (`TestBaselineComparison`,
incl. compound-single-series and panel-skip cases). Closure verified on
the 6.1.3 retrain (job 26): measured entries for the compound-id feeds
(30 of 65 candidates), one recorded skip for the AI4RISK panel feed, and a
finite `mean_lift` (−50.06).

**L-62. The rich scenario parameters do not move the ML scores: uniform
full-history affine transforms are absorbed by per-series standardisation.**
The named scenarios (`market_crash`, `policy_intervention`,
`liquidity_freeze`, `bank_failure`, `regional_shock`) are implemented as
uniform scale/shift (`mul`/`add`) transforms of whole series over their
entire history. But the scoring pipeline standardises each window by
per-series statistics — the checkpoint's statistics when the checkpoint has
them, otherwise statistics computed from the payload itself
(`_prepare_sequence`) — and a uniform scale/shift of a series is an affine
transform that z-scoring cancels. So a 20% price cut, a 60bp rate cut, or a
70% lending freeze applied uniformly leaves (nearly) every model score
unchanged. Measured on the 6.1.3 model (job 26), baseline vs scenario, max
absolute score change over all 71 sources: market_crash 4.8e−7 (float noise),
rate_shock 0.022 (only IR_EURIBOR_1M −0.547→−0.569 and FRED_REPO_RATE
−1.393→−1.392 moved, both via checkpoint-statistics feeds), liquidity_freeze
0, bank_failure 0.049 (only the non-uniform part moved a score: the AI4RISK
topology feed 0.839→0.790, from zeroing the failed bank's equity and
haircutting counterparties), regional_shock 0 (the payload carries no
`region` column, so the shock is a declared no-op). The wiring is correct —
parameters are echoed verbatim, the transforms demonstrably hit the data,
and the network-clearing block (independent of the model) responds properly
(L-56) — but the *scenario's ML score response* is inert for the uniform
shocks by construction. Detected by: the 2026-09-24 scenario re-run
(six responses, job 26). Status: **OPEN — a modelling decision, not a code
bug.** Closing it requires choosing a scenario-relative normalisation (or
shock shapes that change the variance structure rather than the level),
which changes the statistical meaning of the scores; it is recorded here and
in the review report (§7.3, Remaining #6) rather than papered over.

**L-63. The 6.2.0 background scenario jobs completed their simulations but
failed to persist their results — NaN confidence bounds in the strict-JSON
job result column.** The `run_scenario` task stores the full
`ScenarioResponse` as the job `result`; sources without a fitted conformal
interval carry `confidence_lower`/`confidence_upper` as NaN. `json_ready`,
which converts numpy types to native, left non-finite floats alone, and
`json.dumps` (default `allow_nan=True`) emitted the non-standard `NaN`
token, which the Postgres `json` result column rejects: `invalid input
syntax for type json: Token "NaN" is invalid`. All four scenario jobs of
the first live 6.2.0 deployment run (jobs 29–32) failed at progress 90
this way, although every simulation ran to completion (~19 minutes each,
two at a time on the dedicated worker) and its `predictions.json` +
`meta.json` were written to disk. The other job types never store
per-series intervals, which is why the defect surfaced only on the new
scenario path. Status: **CLOSED** — fixed in 6.2.1 (PR #153): `json_ready`
is now module-level and maps every non-finite float (NaN, ±inf) to `null`
before persistence — the same "no interval" meaning the response already
conveys — with unit tests pinning the strict-JSON property
(`backend/tests/test_scenario_job_dispatch.py::TestJsonReady`). Verified:
redeployed 6.2.1 and re-ran the same four scenarios as background jobs
(33–36); all four reached `completed` with their results persisted, each
stored result parses as strict JSON, and the 27 refused intervals are
exactly the 27 `null` bounds in the stored result.

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
(merged `fe70ddd`). The `0.8` consequence is now **CLOSED**: the owner's
decision was made in PR #129 (merged `dfebd2a`) — the rule the suite seeds is
`quality_score lt 70` on the gate scale, sourced from
`QualityPolicy().min_quality_score`, with the unit stated in the module
docstring; an operator-written rule is to be seeded the same way. The
RUNBOOK now carries that example for the operator: a new section 5,
"Alert rules", shows `quality_score lt 70` on the gate scale and
`success_rate`'s native fraction scale, with the why in one line (PR #135).

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
not proven.

Resolved: a clean Node 24 install (`npm ci`, Node 24.21.0) reproduced the red,
so the engine was never the cause. The real defect was a re-render loop in
`Results.tsx`: while the model query is loading, `modelDetail` is undefined, so
`modelDetail?.result || {}` allocated a fresh object on every render, which made
`availableSources` a fresh array on every render and re-ran the
`builderAdjustments` effect on every render. In dev mode React logs "Maximum
update depth exceeded", and the spec's console-error handler turned that into a
failure before `toBeVisible` could observe the (correctly rendered) heading —
the heading renders in ~250ms and nothing reaches the live backend (the suite is
fully mocked). Fixed by reusing stable module-level empty refs for
`baselineMetrics`/`perSourceMetrics`, and by pinning the local e2e engine to
Node 24 (`frontend/.nvmrc` + a `pretest` guard that reads `engines.node` from
`package.json` and fails fast on a mismatched Node). Verified: the three
deep-link tests and the full 15-test suite pass on Node 24 (clean `npm ci`),
locally and in the dispatched `frontend-e2e` run. Status: **FIXED** (v6.0.1,
PR #126) — `frontend/src/pages/Results.tsx`,
`frontend/scripts/ensure-playwright.mjs`, `frontend/.nvmrc`, runs
`35706057051` (`9169be29`) and `35744391049` (`fe70ddd`).

**L-46. The live-migration gate failed as "local auth" on any password-protected
cluster, because the harness stringified the password away.** `test_migrations_live.py`
derives the throwaway database URL with `str(make_url(admin).set(database=name))`. In
SQLAlchemy 2.0, stringifying a `URL` masks the password as `***`, so the derived URL —
used for both the test engine and the alembic subprocess's `DATABASE_URL` — carried a
literal `***` as the password. Every connection to the throwaway database then failed
with `FATAL: password authentication failed`, while the admin connection (same
credentials, never re-stringified) worked. On a developer's password-protected local
cluster all 12 live-migration tests therefore failed as an unexplained "auth" error that
looked environmental and was a harness defect; the gate passed in CI only because CI's
admin URL (`postgresql://beacon_user@...`, trust auth, no password) had nothing to mask.
The whole point of the module — running the migrations against a real PostgreSQL the
guards can inspect — was unreachable from any password-protected cluster. Mitigation:
`render_as_string(hide_password=False)`, so the derived URL actually authenticates.
Verified: 12/12 live tests pass against a password-protected TimescaleDB (fresh, legacy
`create_all`, partial history, no-op re-upgrade, single head). Detected by:
`backend/tests/test_migrations_live.py` (all 12 tests fail on a password cluster before
the fix; the "local PostgreSQL auth only" note in the handoff was this defect, not the
environment). Status: **FIXED** — CHANGELOG (Unreleased, Fixed), PR #116,
`backend/tests/test_migrations_live.py`.

**L-49. The local test suite could silently write to the live Postgres.**
`test_migrations_live.py`'s fallback candidate list ended with hardcoded
`127.0.0.1:5432` URLs carrying the live stack's credentials
(`beacon_user:beacon_password`), so the suite's documented local command
(`pytest backend/tests -q`) created and dropped throwaway databases on the
production server whenever the live stack was up — without anyone making that
decision. A full-suite audit run did exactly that (no data damage: the fixture
only ever created and dropped its own `beacon_migration_test_<uuid>`
database; verified zero leftovers and `beacon_db` intact), but the "postgres
:5432 is read-only" rule held by convention, not by construction: any local
developer following CONTRIBUTING.md was one live stack away from writing to
production Postgres. Detected by: the 2026-09-24 test-suite audit (candidate
list inspection, plus a second full-suite run observed executing the 12 live
migration tests against the live server instead of skipping). Mitigation: the
candidate list is the two env vars only
(`MIGRATION_TEST_DATABASE_URL`, `POSTGRES_MIGRATION_TEST_URL`); a bare local
run skips 12/12 with the explicit reason, and CI names its throwaway service
in the workflow. Verified: bare local run `2192 passed / 12 skipped`; CI
dispatch `2204 passed / 0 skipped` with the 12 live migrations against the
job's service. Status: **FIXED** — PR #141,
`backend/tests/test_migrations_live.py`, `docs/TEST_AUDIT_2026-09-24.md` (F1).

**L-50. The deep CI checkout made the L-48 changelog-history gate unevaluable.**
`backend-tests.yml` checked out with the `actions/checkout` defaults
(`fetch-depth: 1`, `fetch-tags: false` — literally
`git fetch --no-tags --depth=1`), so the clone held no tag refs and no tagged
commit objects. `scripts/check_changelog_history.py`'s base lookup — the
highest-semver release tag reachable from HEAD — therefore had no candidates
on any CI runner, and both `test_changelog_history_gate.py::
test_live_tree_is_covered` and `test_release_tooling.py`'s release dry-run died
with "no release tag reachable from HEAD". The gate worked in local full
clones and at release-cut time; the deep leg was red on every run containing
the L-48 code (first visible: the 2026-09-24 08:46 UTC nightly on `main`, run
`35977227135` — the previous green nightly ran a tree predating the gate,
which had neither the script nor the test). Detected by: the audit's
`gh workflow run backend-tests.yml --ref <branch>` dispatch failing the same
two tests. Impact: the CI leg that should have caught a changelog-history
violation was silently blind — no "green deep run" existed for the gate.
Mitigation: the deep job checks out with `fetch-depth: 0` + `fetch-tags: true`
(the ~145 MB full clone against a 30-minute budget), making the deep leg the
CI equivalent of a local full clone. Verified: post-fix dispatch
`2204 passed / 0 skipped` (run `35986340481`), both gate tests passing against
real tags. Status: **FIXED** — PR #141, `.github/workflows/backend-tests.yml`,
`docs/TEST_AUDIT_2026-09-24.md` (F7).

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
if this class recurs. Status: **FIXED** (tooling guard: was OPEN, deliberately
deferred until a second occurrence justified touching the release script). The
checklist step was exercised at the 5.0.0 cut: `release: v5.0.0` (`85cb051`)
regenerates `docs/api-endpoints.md` in the same commit as the `VERSION` bump, so the
generated inventory reads v5.0.0 and `generate_api_docs.py --check` is green at the
release commit. A second occurrence did follow — the 5.1.0 release left the doc at
v5.0.0 (L-47) — which is exactly what the deferral was waiting on; the guard is now
implemented in `release.py` itself (PR #120), so the bump and the regeneration are
one atomic step rather than a documented two-step.

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
the merge history agree — now implemented in PR #132:
`scripts/check_changelog_history.py` (wired into `release.py` before the
bump) refuses a cut while any merge since the last release tag touches
`backend/`, `frontend/` or `scripts/` without its PR number in the
`[Unreleased]` block; release-branch merges and docs-only merges never
demand entries, and throwaway-repo tests pin both dispositions. Status:
**FIXED** (backfill) — CHANGELOG (Unreleased); the gate for this class is
**CLOSED** (PR #132). The 5.0.0 cycle is the first release that needed no
backfill: `git log v4.0.0..HEAD --no-merges --
CHANGELOG.md` carries an entry commit for every merge from #102 to #113, and those
entries moved into `## [5.0.0]` verbatim.

**L-44. 4.1.0 looked like the obvious bump, and the scan meant to confirm it found
three live defects instead.** The post-4.0.0 work read as a MINOR: four additive
capabilities, no removed route, upgradable migrations. Before cutting it, a consumer
scan asked what a reader of `avg_completeness`, `Job.result` and a saved checkpoint
would see differently — and the answer was that the release was not additive. Three
defects surfaced in the scan itself, none of them reported by a failing job: the
quality unit was declared nowhere and three readers mixed 0–1 with 0–100 in one view
(L-39); the analytics aggregate population omitted one of two writers, so a card, a
trend point and a detector reported 0 for data that existed (L-29's F2 at its
analytics twin, L-35); and panel windows grouped per entity were normalized per feed,
so a 10² entity was scored and reported at 10⁶ (L-42). Each changes what a consumer
reads from the same deployment, which `docs/VERSIONING.md` places under MAJOR, and the
checkpoint-manifest change (`stats_grain`, `series_ids`, series-keyed `source_stats`,
`checkpoint_feed_grain` provenance) removes any remaining doubt. Bumped **5.0.0**,
tagged at the release commit `85cb051` (PR #114) rather than at the merge commit, as
`v4.0.0` was. Durable practice, recorded because it is the reusable part: **decide a
bump by enumerating what a consumer reads differently on unchanged data, not by
counting added endpoints.** L-11 applied that rule to 4.0.0 after the fact; here it
was applied before the cut, which is what turned a planned minor into a fix batch.
Status: **RECORDED** — CHANGELOG (5.0.0, Changed), `v5.0.0`, `docs/VERSIONING.md`.

**L-47. The 5.1.0 release left a generated doc stale — the second occurrence
L-25 deferred a guard for.** `docs/api-endpoints.md` embeds the application version;
the 5.1.0 release (`release: v5.1.0`, `d0664e7`) bumped `VERSION` to 5.1.0 but the
release tooling did not regenerate the inventory, so the committed doc still claimed
v5.0.0. The fast CI gates do not include the inventory check (the deep suite does),
and the release was merged on the fast gates alone, so the staleness was not caught at
merge — it surfaced during the next feature's gate run (PR #119), where
`generate_api_docs.py --check` failed against the stale file. Mitigation: the
inventory was regenerated in PR #119 (one-line version diff); and the durable fix
L-25 deferred — regeneration in the release tooling itself — is now implemented:
`release.py` runs `scripts/generate_api_docs.py` after writing `VERSION` and includes
the doc in the release commit (PR #120), so the bump and the regeneration are one
atomic step. Status: **FIXED** — PR #119 (regen), PR #120 (tooling guard); the 5.2.0
cut is the first to run through the fixed tooling, closing L-25's deferred item.

**L-48. The release surface was tags-only: thirteen release tags shipped with
an empty GitHub Releases page, the RUNBOOK told the operator to tag the wrong
commit, and the changelog gate's base lookup was one prereg mark away from
breaking.** No GitHub Release existed for any release tag, so the public
Releases page was empty for everything since v3.1.0; `docs/RUNBOOK.md`'s
release procedure said "tag the merge commit `vX.Y.Z`" while every real tag
sits on the release commit (`release.py --tag` runs on the release branch
before the merge); and `check_changelog_history.py` found its base tag with
`git describe --tags --abbrev=0` — the *nearest* tag, not the newest release.
The `prereg-early-warning-v*` tags are ancestors of main, so the first
preregistration mark cut after a release would have displaced the base and
failed the gate with "not a release tag" (or measured against the wrong
range). Status: **FIXED** — the Semver release design (PR #138): the tag
stays the machine anchor and the GitHub Release becomes the public artifact
(`release.py publish [VERSION]` creates or refreshes it after the tag is
pushed, notes are the versioned changelog block verbatim, pre-release
versions publish as GitHub pre-releases); the base lookup now takes the
highest-semver release tag reachable from HEAD (both dispositions pinned by
synthetic tests); the required "check" job gained a parity guard
(`check_release_coverage.py`) that fails while any release tag lacks its
GitHub Release; the thirteen releases were backfilled from their changelog
blocks as a maintainer act before the PR; RUNBOOK §7 and VERSIONING.md were
rewritten to the tag/release split.

---

*Adding an entry: open it when the failure is confirmed, with a pointer; close
it only when the mitigation is merged and verified. The CHANGELOG records what
changed; this ledger records what went wrong and what we did about it — both,
always, in public.*
