# Contributing to BEACON

BEACON grows by chasing errors, faults and misleads and fixing them one by one.
This document is the invitation and the contract: how to run the platform, how
to reproduce its published science, how to report what's wrong, and the norms
every contribution — human or machine — is held to.

Read first: [`docs/FAILURE_LEDGER.md`](docs/FAILURE_LEDGER.md) (what has gone
wrong and what we did about it) and the README's claim gate (what the platform
does **not** claim: it is a data-governance and scenario laboratory, **not a
demonstrated early-warning system** — three pre-registered runs say so, tagged
and published unchanged).

## Norms (binding, and the reason the record is believable)

1. **Freeze before you measure.** Evaluation criteria, labelling, alarm rules
   and model configs are committed and git-tagged *before* a run executes.
2. **One run, published unchanged.** A pre-registered run executes once. The
   result — pass or fail — is published as-is. Loosening a criterion after
   seeing the number is the goalpost-move the protocol exists to forbid.
3. **Licence-screen before you download.** A series' own terms are read and
   recorded before fetch; prohibited data is never downloaded, let alone
   committed. Absence of a licence confirmation is recorded as unconfirmed,
   never guessed.
4. **Refuse, don't fabricate.** Missing data is absence, not zero; an
   undeclared stress direction is a refusal, not a default; an unsupported
   confidence field is `null` with the reason beside it.
5. **Claims point at code.** Every capability claim in the docs has a module,
   test or tagged artefact behind it. A stale claim is a bug (ledger class
   "mislead") — the whole-repo claim audit is repeatable; run it.
6. **Credentials never live in the repo.** Keys and tokens are environment-only
   at run time; recorded endpoints redact them. If a credential is exposed
   anywhere (chat, log, commit), rotate it and say so.

## Running it

Resource profile (measured): the full backend suite runs on **2 CPUs / ~1 GB
RAM** in ~7 minutes; the environment needs ~2 GB of disk with the **CPU torch
wheel** (the PyPI default pulls gigabytes of CUDA libraries — don't):

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install --index-url https://download.pytorch.org/whl/cpu torch==2.14.0
pip install -r backend/requirements.txt -r backend/requirements-dev.txt

# gates, in the order CI runs them
python -m compileall -q backend scripts
ruff check backend scripts --select E9,F63,F7,F82
python scripts/check_versioning.py
OMP_NUM_THREADS=2 python -m pytest backend/tests -q     # ~2200 tests
# (the live-migration module skips locally unless MIGRATION_TEST_DATABASE_URL
# names a server it may create and drop databases on -- never the live stack)
```

Frontend and end-to-end: see `docs/frontend.md` and
`.github/workflows/README.md` (every CI gate is reproducible locally).
Deployment: `docs/deployment.md`; operations: `docs/RUNBOOK.md`.

## Reproducing the published science

The early-warning record is reproducible by design — alarm-independent metrics
came out byte-identical across all three protocol versions:

```bash
git checkout prereg-early-warning-v3          # or v1 / v2
FRED_API_KEY=<your-own-key> python scripts/run_preregistered_eval.py \
    --protocol v3 --eval                       # fetch → evaluate, single run
```

Use your own FRED key (free, fred.stlouisfed.org); it is read from the
environment only. Reports of record live under `docs/prereg/runs/` and must not
be edited: a reproduction that disagrees with a published report is itself a
finding — open an issue, don't overwrite the record.

## Sharing analyses and outputs

Want to run BEACON on your own data and publish what it says? Do, and please
hold the outputs to the same bar:

- **Onboarding your series**: `docs/operator_series_onboarding.md` gives the
  exact contracts (`csv` and `custom_api`), the already-declared stress
  directions, and what the pipeline does next. Six registry codes
  (HQLA/LCR/NSFR/bank equity/FX swap basis/CDS) have no public source and
  never will — operator data is the differentiator.
- **Provenance travels with the output**: commit the manifest, the input
  snapshot id and the code revision (git tag) your run used. An output without
  provenance is an anecdote.
- **Negative results are welcome.** A well-powered NO with a tagged protocol
  is worth more than an unrepeatable yes. The three-run early-warning record
  is the worked example.
- **New evaluation protocols**: draft the protocol document, freeze it in a
  PR, tag it, run it once, publish whatever it says. If you change a frozen
  criterion, that is a new protocol version — say so explicitly.

## Reporting errors, faults and misleads

Open an issue with the class and the evidence. Classes we track (mirroring the
ledger's sections):

| Class | Examples | Include |
|---|---|---|
| **Scoring/engine bug** | wrong metric, misaligned labels, wrong tail | minimal repro, expected vs observed, code revision |
| **Data or licence** | format drift, terms prohibit reuse, wrong vintage | URL + access date, the terms text, plugin name |
| **Claim drift ("mislead")** | a doc/README/UI sentence the code contradicts | the sentence, the contradicting module/test |
| **Reproducibility failure** | a tagged run that won't reproduce | tag, command, environment, diff against the published report |
| **Infrastructure lie** | a gate that passes vacuously or is permanently tripped | workflow/job output showing the gate not measuring |

Security or credential exposure: do **not** open a public issue — contact the
maintainers privately, rotate first, document after.

Every confirmed failure gets a [`docs/FAILURE_LEDGER.md`](docs/FAILURE_LEDGER.md)
entry when it is confirmed (not when it is fixed), and the entry closes only
when its mitigation is merged and verified.

## Pull requests

- Land work under `## [Unreleased]` in `CHANGELOG.md` (Keep a Changelog);
  `scripts/release.py` moves the block when a release is cut. See
  `docs/VERSIONING.md` for what MAJOR/MINOR/PATCH mean here — a MAJOR needs a
  breaking contract change, stated explicitly in the notes.
- Keep `docs/README.md` (the index) current: a new document that isn't
  registered is a document that will go stale unnoticed (ledger L-24).
- Every PR runs Backend CI, Frontend CI and the versioning gate; the deep
  suites do **not** run on a merge — `backend-tests.yml`, `frontend-e2e.yml` and
  `bundle-budget.yml` trigger nightly and on demand (see
  `.github/workflows/README.md`). So a pipeline-, model-, migration- or
  API-surface-touching change is proven before it merges, by hand:
  `gh workflow run backend-tests.yml --ref <branch>`, or the local full suite
  (~3 min on 2 CPUs; the CI leg is ~8 min including installs). Eight pipeline
  merges landed on `main` under nothing but
  the sub-minute gates because this line used to claim the deep suites ran on
  merge; a red deep run found it two modules away from its cause.
- Don't merge red, and don't merge a vacuous green (see "Infrastructure lie"
  above). "Targeted pytest: N passed" on a pipeline PR is not proof: the shared
  test database makes cross-module state leaks invisible to any run that does
  not include the whole suite.

## Release checklist (maintainers)

1. `main` green; `[Unreleased]` block complete and honest (failures included).
2. `python scripts/release.py major|minor|patch --dry-run`, read the diff.
3. `python scripts/release.py major|minor|patch --tag` — moves the changelog
   block, bumps `VERSION`, syncs `frontend/package.json`, commits atomically,
   tags locally.
4. **Regenerate `docs/api-endpoints.md` immediately after** (`PYTHONPATH=.
   python scripts/generate_api_docs.py`) — the inventory embeds the new
   version and goes stale the moment `VERSION` moves; the deep suite guards
   it (ledger L-25 — it happened to 4.0.0). Land it with the release.
5. **Push the commit and the tag.** A release cut without its tag is a stranded
   release (ledger L-23 — it happened to v3.3.0).
6. Verify CI on the release commit; verify `git tag -l` contains the new
   version; run the full suite once before the next nightly does.

---

*If you find this document contradicts the code, that is a claim-drift bug:
report it, and it becomes a ledger entry. The system is supposed to bend
toward the truth when someone pushes on it — pushing is the contribution.*
