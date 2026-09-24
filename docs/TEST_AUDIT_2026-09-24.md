# BEACON test-suite audit — 2026-09-24

Scope: every test in the repo (backend pytest suite, frontend Playwright suite, the
static audit scripts CI runs, and the test-like scripts under `scripts/`). Goal:
determine which tests are valid and necessary, which are stale, duplicate, or
never-run, and what cleanup makes the suite clean and tidy without regressing
coverage of live behavior.

## Evidence collected

| Check | Result |
| --- | --- |
| Local full Tier-2 (`pytest backend/tests`, `OMP_NUM_THREADS=2`) | **2204 passed, 1 skipped, 0 failed**, 158–167 s (ran twice) |
| Single skip | `test_country_scope.py` (needs `RUN_DOCKER_SCOPE_TESTS=1`) |
| CI nightly `backend-tests.yml` on main (run 35839454895, 2026-09-23 08:50 UTC) | all steps green: compileall, API-docs current, offline migration render, full pytest with coverage, live migrations against a throwaway Postgres service, ruff |
| CI nightly `frontend-e2e.yml` on main | green (1 m 07 s): production build + all Playwright specs |
| CI nightly `bundle-budget.yml` | green |
| All Tier-1 PR gates (last 12 runs) | green |
| Frontend local static audits | typecheck green; e2e mock coverage **34/34** endpoints; tailwind content OK; hook reachability **54/54** exports |
| Growth | 0 test files (Oct 2025) → 2 (Nov 2025) → 61 (2026-09-15) → 97 (2026-09-24). The explosion is real and concentrated in the phase rebuild over 10 days. |

**Verdict: the suite is not rot.** Every one of the 97 backend files carries a
docstring stating the property it pins and the defect it guards; the repo has
meta-guards (reachability census, API-docs currency, e2e mock coverage,
frontend contract, release parity) that exist precisely to stop the "passing
tests over dead code" failure mode. The numbers exploded because 10 days of
phase work each added their own pinned contracts. Most tests earn their place.
The problems found are specific and few:

## Findings

### F1 — `test_migrations_live.py` silently targets the LIVE postgres by default (safety; fix recommended)

`_CANDIDATE_URLS` falls back, in order, to:

```
postgresql://beacon_user@127.0.0.1:5432/postgres
postgresql://postgres@127.0.0.1:5432/postgres
postgresql://beacon_user:beacon_password@127.0.0.1:5432/postgres   <- the live stack's credentials
postgresql://postgres@localhost:5432/postgres
```

The fixture creates a `beacon_migration_test_<uuid>` database on the first
candidate that answers, runs alembic in it, and drops it on exit. It never
touches existing data — but when the live stack is up (as it currently is) and a
developer runs the documented local command (`python -m pytest backend/tests -q`),
the 12 migration tests **create and drop databases on the production server**.
This audit's own two full-suite runs did exactly that (disclosure: live
`beacon_db` verified untouched, zero leftover test databases). That contradicts
the standing hard rule that `postgres :5432` is read-only and that the migration
tests are "on demand only".

CI is unaffected: `backend-tests.yml` sets `MIGRATION_TEST_DATABASE_URL`
explicitly against its own throwaway service.

**Fix:** keep only the two environment variables in `_CANDIDATE_URLS`
(`MIGRATION_TEST_DATABASE_URL`, `POSTGRES_MIGRATION_TEST_URL`); remove the four
hardcoded local candidates. Local runs then skip the module unless a server is
explicitly named (on-demand, per policy); CI is unchanged. Optionally document
the throwaway TimescaleDB on `:55432` as the on-demand target.

### F2 — `test_country_scope.py` can never run in CI, and running it locally means bringing the live stack down (dead test; deletion recommended)

- No workflow sets `RUN_DOCKER_SCOPE_TESTS=1`, so it is **never executed in any
  automated environment** (it is the single skip in every local and CI run).
- Locally it requires the docker CLI plus `RUN_DOCKER_SCOPE_TESTS=1`, and then
  runs `docker compose up -d postgres redis backend celery-worker` — i.e. the
  **live** compose stack — creates a job against the live API on `:3456`, and
  `docker compose down` in `finally`. Executing it would take the production
  deployment down and up; under the current hard rules it may not be executed.

It therefore pins a behavior no environment will ever verify. **Recommended:
delete the file** (1 test, 94 lines, zero CI value). Alternative if the scenario
must be kept: move it to `scripts/manual/` as a clearly-labelled manual drill.

### F3 — ~269 tests (≈12% of the suite) test modules the reachability census says production does not run (owner decision; keep recommended)

The census in `test_reachability.py` (`KNOWN_UNREACHABLE`) is explicit and
current:

| Disposition | Module | Tests |
| --- | --- | --- |
| park | `data/streaming` | test_streaming (43) |
| park | `engine/federated` | test_federated (36) + test_federated_dropout (29) |
| decide | `engine/foundation_encoders` | test_foundation_encoders (21) |
| decide | `engine/subgraphx` | test_subgraphx (54) |
| decide | `engine/causal_validation` | test_causal_validation (18) |
| wire | `engine/mixture_of_experts` | test_mixture_of_experts (33) |
| wire | `services/lei_service` | part of test_adoption_data |
| wire | `results/vintage_backfill` | test_vintage_backfill (21) |

Cost: ≈18 s of the 167 s local run (federated_dropout alone is 16.8 s, the third
slowest file). These suites are the repo's deliberate "recorded rather than
deleted" insurance: if a parked/queued module is ever wired, the contract is
already pinned. **Recommendation: keep.** Cutting them is a product decision —
and it would have to remove module + tests + census entry together, which is not
a tidiness task, it is a capability decision.

### F4 — Stale numbers in the docs (trivial; fix recommended)

- `CONTRIBUTING.md`: "≈2000 tests" → actual 2205; "local full suite (~7 min on 2
  CPUs)" → measured 158–167 s on this machine.
- `frontend-e2e.yml`: one comment says "the three mocked navigation specs
  (dashboard/pages/results/search)", another says "the four mocked navigation
  specs" — there are four files (dashboard, pages, results, search).
- `docs/` has no test-policy page; the policy currently lives in file docstrings
  and workflow comments. (No change required; noted for completeness.)

### F5 — Structural note, not a defect

Tier-1 PR gates run **zero** tests (static only, by design, sub-minute budget);
the real evidence is the nightly Tier-2 plus manual dispatch. That is deliberate
and documented in `.github/workflows/README.md`. No change recommended.

### F6 — Warnings surfaced by the suite (follow-ups, not test validity)

6 warnings in the local run: NumPy `generic` timedelta deprecation (boe_database
plugin, validator_anomalies test), `datetime.utcnow()` (fred_plugin), a torch
`requires_grad` user warning (mixture_of_experts test), and a Starlette
testclient deprecation from the venv. Code-side cleanup candidates; none affect
validity.

## Cost profile (167 s local run, top consumers)

```
33.2 s  test_migrations_live.py          (12 tests; live Postgres — see F1)
22.9 s  test_data_governance.py          (6 slow retry-budget tests)
16.8 s  test_federated_dropout.py        (parked module — see F3)
15.8 s  test_regime_batch_equivalence.py (regression guard)
11.8 s  test_data_pipeline_stages.py
10.7 s  test_hidden_markov.py
10.6 s  test_student_t_hmm.py
 4.5 s  test_ecb_plugin.py
 4.0 s  test_pit.py
 3.7 s  test_prereg_v4.py
```

Everything else is under 4 s per file; 6006 test durations are below 5 ms.

## Resolution (approved and landed as one PR)

All four items were approved on 2026-09-24 and landed together:

1. `test_migrations_live.py`: env-var-only candidate list (F1) + docstring note.
2. `backend/tests/test_country_scope.py` deleted (F2); workflow comments that
   referenced it updated (`backend-tests.yml`, `workflows/README.md`).
3. Stale figures fixed in `CONTRIBUTING.md` and the spec-count comment in
   `frontend-e2e.yml` (F4).
4. F3 resolved as **keep all**: the ~269 tests over census-listed modules stand
   as the repo's deliberate "recorded rather than deleted" insurance.

Post-cleanup local numbers: a bare local run is `2192 passed, 12 skipped` (the
12 live-migration tests skip without the env var; CI carries their evidence).
If the "local is the real evidence" principle must hold for migrations too, point
`MIGRATION_TEST_DATABASE_URL` at the throwaway TimescaleDB on `:55432` on demand.

Changelog: per the L-41 flow, this PR's `[Unreleased]` entry naming the PR
number lands on the next release branch (this PR touches `backend/`, so the
release-time gate will require it).

Note on post-cleanup local numbers: with F1+F2, a bare local run becomes
`2192 passed, 12 skipped` (the 12 live-migration tests skip without the env var;
CI carries their evidence) — the skips are honest. If the "local is the real
evidence" principle must hold for migrations too, the alternative is to point
`MIGRATION_TEST_DATABASE_URL` at the throwaway TimescaleDB on `:55432` on demand.

Explicitly NOT recommended without an owner decision:
- removing the ~269 tests over census-listed (F3) modules;
- moving Tier-2 to per-PR;
- deleting any of the release-tooling, reachability, frontend-contract, or
  e2e-coverage guard tests — each was read and verified to pin a distinct,
  live property.
