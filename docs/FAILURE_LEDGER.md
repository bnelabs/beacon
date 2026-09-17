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

---

*Adding an entry: open it when the failure is confirmed, with a pointer; close
it only when the mitigation is merged and verified. The CHANGELOG records what
changed; this ledger records what went wrong and what we did about it — both,
always, in public.*
