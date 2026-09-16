# CI/CD workflows

This directory contains the GitHub Actions automation for BEACON: seven
workflows, Dependabot configuration, and a pull-request template.

The design rule is a **two-tier split**: everything that runs in front of a
push or pull request must finish in **under a minute**, and everything that
takes longer runs nightly and on demand. A pre-merge gate that takes ten
minutes is a gate people stop waiting for; a nightly deep run surfaces the
same regression at most one day later — and immediately, by hand, for any
change that deserves it (`gh workflow run <file> --ref <branch>`).

**Tier 1 — pre-merge gates (every push to `main`, every PR; each < 1 min):**

| File | Purpose | Budget |
| --- | --- | --- |
| `backend-ci.yml` | Syntax gate (`compileall`, stdlib only) + the compose/Dockerfile validator (`validate_compose.py`, PyYAML only). | seconds |
| `frontend-ci.yml` | Strict `tsc --noEmit` over the all-TypeScript `frontend/src` + the e2e mock-coverage audit. `node_modules` is cached by lockfile hash; Playwright's browser download is skipped (no browser runs here). | ~30s warm |
| `versioning-ci.yml` | Runs `scripts/check_versioning.py`: VERSION is strict semver, `frontend/package.json` and `backend.__version__` agree with it, and the top changelog block is `[Unreleased]` or the current version. | seconds |

**Tier 2 — deep validation (nightly `schedule` + `workflow_dispatch`):**

| File | Purpose | When |
| --- | --- | --- |
| `backend-tests.yml` | The full backend leg: uv-installed pinned stack + CPU torch, pytest with coverage, the live-migration PostgreSQL service, the generated-API-docs check, offline migration render, advisory ruff. | nightly 03:47 UTC + manual |
| `frontend-e2e.yml` | Production `vite build` + the fully mocked Playwright suite on chromium, artifacts on failure. | nightly 03:26 UTC + manual |
| `security.yml` | Advisory dependency audits: `pip-audit` for `backend/requirements.txt` and `npm audit` for `frontend/`. Never blocked a merge (every step is `continue-on-error`), so it no longer queues in front of one. | weekly (Mondays 06:17 UTC) + manual |

**Manual only:**

| File | Purpose | Triggers |
| --- | --- | --- |
| `docker-backend.yml` | Validate every compose file and build the backend CPU image. | `workflow_dispatch` (*Actions → Docker backend image → Run workflow*). |
| `docker-frontend.yml` | Build the frontend image. | `workflow_dispatch` (*Actions → Docker frontend image → Run workflow*). |

| File | Purpose | Triggers |
| --- | --- | --- |
| `../dependabot.yml` | Version-update PRs for `github-actions`; security-update PRs for `pip` and `npm`. No `docker` entry. | GitHub's scheduler (see the policy below). |

Run the deep workflows by hand before merging the changes they exist for:
`backend-tests.yml` for anything touching requirements, models, migrations,
the pipeline or the API surface; `frontend-e2e.yml` for anything touching
routing, the API client, or a flow the mocked suite walks; the docker
workflows for any Dockerfile or base-image change.

## Concurrency

Every workflow uses a per-ref `concurrency` group, but cancellation is
**conditional**: `cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}`.

- On a pull request or feature branch, a superseded run is cancelled — it
  produces no useful signal and wastes runner minutes.
- **On `main` a run is never cancelled.** A cancelled run leaves the commit
  permanently unverified, and a manual `workflow_dispatch` shares the same
  concurrency group as a `push`, so unconditional cancellation could discard the
  only real run for a commit.

## Backend CI (`backend-ci.yml`) and deep tests (`backend-tests.yml`)

`backend-ci.yml` is the pre-merge gate and runs two checks that need no
dependency tree: `python -m compileall -q backend` (a syntax error fails in
seconds, on the stock interpreter) and `python scripts/validate_compose.py`
(after `pip install pyyaml` — its only third-party import). Everything below
describes `backend-tests.yml`, which carries the full leg nightly and on
demand; installing the pinned stack (CPU torch included) is the single
biggest cost in CI and can never fit a sub-minute budget.

- **Python 3.12** — the same minor version as `backend/Dockerfile.cpu`
  (`FROM python:3.12-slim`) and the interpreter installed by `backend/Dockerfile`.
  The pinned scientific stack (scipy 1.18, scikit-learn 1.9, matplotlib 3.11)
  requires Python >= 3.12.
- **CPU-only PyTorch.** The torch version is read from `backend/requirements.txt`
  at run time and installed from `https://download.pytorch.org/whl/cpu` *before*
  the requirements files, so the runner does not download the multi-GB CUDA
  bundles and the two can never drift apart.
- **A PostgreSQL service, for the migrations only.** The application tests do not
  need one: they force SQLite through `USE_SQLITE=true` (`test_api_smoke.py`,
  `test_pipeline_integration.py`) and drive the app with FastAPI's in-process
  `TestClient`, and `test_country_scope.py` is still skipped unless
  `RUN_DOCKER_SCOPE_TESTS=1`. What needs a real server is
  `test_migrations_live.py`, which applies the chain to an actual PostgreSQL —
  the same `timescale/timescaledb:2.15.2-pg15` image compose runs — from each of
  the three histories a deployed database can have (empty, `create_all`, partial)
  and asserts they converge on one schema. `MIGRATION_TEST_DATABASE_URL` points it
  at the service; without that variable the tests skip, and a skip is not a pass.
  This job previously declared that no service was needed because the migration
  "test" was `alembic upgrade head --sql`, which cannot detect an ordering defect:
  `baseline_core_001` renders as a deliberate no-op offline. That is how a release
  shipped whose root migration altered a table created five revisions later.
- **Steps (deep):** uv + CPU torch + requirements →
  `python -m compileall -q backend` (repeated so a nightly failure is
  self-contained) → `python scripts/generate_api_docs.py --check` (the
  generated endpoint inventory matches the app) → `alembic upgrade head --sql`
  (render check only) → `python -m pytest` with coverage → upload the
  `backend-coverage` artifact (`coverage.xml`, `htmlcov/`) → an advisory
  `ruff` check that reports real defects without blocking. The compose
  validator stays in the fast gate, where it costs ~100ms.
- The target and coverage flags are passed explicitly as well as living in
  `pytest.ini` (which uses the correct `[pytest]` header and sets
  `testpaths = backend/tests`). Keeping them in the workflow makes the invocation
  self-describing and immune to config drift.

## Frontend CI (`frontend-ci.yml`) and deep e2e (`frontend-e2e.yml`)

`frontend-ci.yml` is the pre-merge gate: install once (a `node_modules`
cache keyed on the lockfile hash skips it entirely on the common run;
`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1` keeps even the cold install inside the
budget), then `npm run typecheck` — which now checks **the whole app**: the
JS→TS migration is complete, every module under `frontend/src` is `.ts`/`.tsx`
under `strict` + `noUnusedLocals` — and `node
scripts/check_e2e_api_coverage.mjs`. The build and the browser suite below
live in `frontend-e2e.yml` (nightly + dispatch).

- **Node 24** (Active LTS until 2028-04), matching the `node:24-alpine` base in
  `frontend/Dockerfile`.
- **All JavaScript actions run on Node 24.** `actions/checkout@v7`,
  `actions/setup-node@v7`, `actions/setup-python@v7`,
  `actions/upload-artifact@v7`, `docker/setup-buildx-action@v4` and
  `docker/build-push-action@v7` all declare `runs.using: node24`, so no action is
  forced onto a newer runtime and the Node 20 deprecation warning does not appear.
  When bumping an action, check its `action.yml` for `using: node24` rather than
  assuming the highest tag is current.
- **Steps (deep):** `npm ci` → `npm run build` →
  `npx playwright install --with-deps chromium` → `npm test` → upload
  Playwright traces/results only on failure.
- **No live backend is started.** The Playwright suite is fully mocked:
  `frontend/tests/full-frontend.spec.js` installs `frontend/tests/apiMocks.js`, which
  intercepts every `**/api/**` request via `page.route(...)`. Playwright's `webServer`
  block only starts the Vite dev server on `127.0.0.1:8173`.
- **The mock's coverage is itself checked in the fast gate, before any
  browser exists anywhere.** The mock
  answers an unknown GET with a deliberate 404 ("as the real API does" — answering
  200 with an empty object once let a wrong URL pass as a successful empty result),
  and the spec fails the test on *any* console error. So an endpoint the frontend
  adopts and the mock does not cover fails the suite at whatever assertion was
  executing when TanStack Query retried the request, not at the thing that is
  missing. `scripts/check_e2e_api_coverage.mjs` runs the mock's real route handler
  against every `fetchApi` endpoint in `frontend/src` and names the ones that fall
  through, which is the difference between "the create-source form would not close"
  and "`GET /api/v1/data-sources/disclosure` is not mocked". `backend/tests/
  test_e2e_api_coverage.py` runs the same check in the backend suite, skipping if
  node is absent.

## Docker image builds (`docker-backend.yml`, `docker-frontend.yml`)

**Both are manual only: `workflow_dispatch` and nothing else.** They are the
"build the real image" button, not a merge gate. No push, pull request or schedule
can start them, so no wait they create can land in front of ordinary work.

They exist because the automated workflows test the code on the *runner's*
interpreter and Node install, and never build the images. That gap is
not theoretical — both halves of it have already bitten this repository:

- A Dependabot PR proposed `python:3.14-slim` for `backend/Dockerfile.cpu`,
  which passes every Python test (CI uses `setup-python`, not the image) but
  cannot build, because `torch` and `numpy` publish no cp314 wheels.
- `frontend/Dockerfile` used `npm install --legacy-peer-deps`, which skips peer
  dependencies. `@deck.gl/widgets` (a peer of `@deck.gl/react`) was therefore
  absent and the image build failed with *"Rollup failed to resolve import
  '@deck.gl/widgets'"* while Frontend CI stayed green. Now fixed with `npm ci`.

**What manual-only gives up, and what now covers it.** This used to say that
nothing validates a Dockerfile, base image or compose change automatically. That
was true, and it cost a release: `c03f4af` added `COPY backend/entrypoint.sh` to
both Dockerfiles while compose built them with `context: ./backend`, so the source
path resolved to `backend/backend/entrypoint.sh` and **the backend image could not
be built at all**. It shipped, and was found by someone trying to deploy.

Three things now cover most of that gap without a build:

- **Backend CI runs `python scripts/validate_compose.py`** — 112 invariants over
  the merged compose YAML for the base file and both overlays (one shared backend
  image, exactly one build, a one-shot `migrate` that everything waits on,
  healthcheck-driven ordering, no fixed `container_name`, `CUDA_VISIBLE_DEVICES`
  never `all`), **plus every Dockerfile `COPY` source resolved against the
  declared build context**, which is the check that would have caught `c03f4af`.
  No daemon, ~0.1s. `backend/tests/test_compose_stack.py` runs it in the suite
  too, and also runs it against a deliberately broken copy of the stack to prove
  it can fail.
- The nightly `backend-tests.yml` installs the *same* `backend/requirements*.txt`
  on the *same* Python 3.12 interpreter, so an uninstallable pin still fails
  there in ~2 minutes, and a Python-version bump that cannot resolve is caught
  the same way.
- The nightly `frontend-e2e.yml` runs `npm ci && npm run build` on Node 24,
  which catches a broken dependency graph — but **not** a peer-dependency gap
  in the image, because that only appears when the image resolves its own
  tree.

What is still only found by running the workflow: a broken base-image tag, and
anything about the image that only exists once built. Two changes make that
cheap enough to do on demand:

- `docker-backend.yml` runs `docker compose config` over the base file and both
  overlays (`.cpu`, `.gpu`) in seconds, then builds `backend/Dockerfile.cpu`. The
  build installs torch, torch-geometric and scipy: about **5 minutes warm**
  (measured 282s) and up to **11 minutes cold**.
- `docker-frontend.yml` builds `frontend/Dockerfile` in about 80 seconds.
- Both use the GitHub Actions build cache (`type=gha,mode=max`), and the
  Dockerfiles use BuildKit cache mounts, so a re-run that changes nothing about
  the image finishes in seconds (measured 25s).

Running them before merging a Dockerfile or base-image change is the point: a
`backend/Dockerfile` bump was once merged on the strength of a build that had run
*before* a later Dockerfile change, and proving it afterwards meant starting a
five-minute job by hand.

```bash
# Trigger either workflow on main from the CLI instead of the Actions tab:
gh workflow run docker-backend.yml --ref main
gh workflow run docker-frontend.yml --ref main
```

## Speed notes

Measured improvements, in order of impact:

- **The pre-merge path is static-only and finishes in under a minute.** The
  three gate workflows (syntax + compose validation, typecheck + mock-coverage
  audit, versioning) run no browser, install no torch, and build no bundle;
  the multi-minute legs moved to nightly + dispatch workflows. The trade is
  explicit: a runtime regression that only a browser or a pytest run can see
  is caught at most one day later — or immediately, by running
  `backend-tests.yml` / `frontend-e2e.yml` on the branch before merge.
- **`node_modules` is cached by lockfile hash** in the frontend gate, so the
  common run skips `npm ci` entirely (~40-70s saved), and the cold run skips
  Playwright's ~150MB browser download (`PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1`).
- **Coverage is produced only in the nightly/dispatch backend workflow.**
  Instrumentation slows the suite by roughly **3.5x** (measured 0.63s → 2.19s
  on the fastest modules), and the report and artifact are consumed there,
  not on a PR.
- **Backend installs use `uv`**, not pip: the CPU torch install went from 23s to
  **3s** and the project dependencies from 39s to **4s** (62s → 7s total). The
  uv cache is keyed on both requirements files.
- **A requirements change never needs a Docker image build.** The nightly
  `backend-tests.yml` installs the same files on the same Python 3.12
  interpreter, so an uninstallable pin is caught there in ~2 minutes without
  paying for a torch image build.
- **No image build runs automatically at all.** `docker-backend.yml` and
  `docker-frontend.yml` are `workflow_dispatch`-only, so a push or a pull request
  never pays for one. The trade is explicit: a Dockerfile or base-image change is
  validated when someone runs the workflow, not on every change. See the Docker
  section above for what still catches what.
- **The Dockerfiles use BuildKit cache mounts** for the uv and npm caches. A
  cache mount is keyed by path rather than by layer hash, so downloaded wheels
  and tarballs survive a base-image change instead of being re-fetched.
- **Docker builds keep `type=gha,mode=max` layer caching**, so only a run that
  genuinely changes a layer pays the full install cost.

What remains dominant is the test work itself: a full offline pipeline
execution that trains a model, plus FastAPI application start-up.

## Security audit (`security.yml`)

- Weekly (Mondays 06:17 UTC) and on dispatch only. Every step was already
  `continue-on-error`, so it never gated a merge — it only queued in front of
  one. A newly published CVE now surfaces within the week, which is the
  cadence an advisory signal needs.
- `pip-audit -r backend/requirements.txt` and `npm audit --audit-level=high` in
  `frontend/`.
- The `pip-audit` version is read from `backend/requirements-dev.txt` rather than
  hard-coded, so the audit tool cannot drift from the pinned dev dependency set.
- Every audit step is `continue-on-error: true`: findings show up in the checks UI but do
  not block merges. Fix findings as a dedicated, reviewable dependency bump.

## Versioning guard (`versioning-ci.yml`)

Runs `scripts/check_versioning.py` on every pull request and every push to
`main`: `VERSION` must be strict semver, `frontend/package.json` and
`backend.__version__` must agree with it, and the top block of `CHANGELOG.md`
must be `[Unreleased]` or the current version. This is the mechanism that makes
the policy in [`../../docs/VERSIONING.md`](../../docs/VERSIONING.md) impossible
to skip by accident; see that document for what each bump level means and how
`scripts/release.py` cuts a release.

## Dependabot (`../dependabot.yml`)

Short answer to "do we actually need this?": **yes, but only for the parts that
work.** Routine version updates are disabled for the ecosystems that repeatedly
caused damage or failed outright, and the `docker` ecosystem is gone entirely.
Security updates remain enabled wherever they are actually supported.

| Ecosystem | Routine version updates | Policy |
| --- | --- | --- |
| `github-actions` (`/`) | **Yes** — weekly, grouped, limit 3 | Low risk, high value, no application code. |
| `pip` (`/backend`) | **No** — `open-pull-requests-limit: 0` | Security updates only. |
| `npm` (`/frontend`) | **No** — `open-pull-requests-limit: 0` | Security updates only. |
| `docker` (`/backend`, `/frontend`) | **No — the entry is removed entirely** | Base images (`python`, `nvidia/cuda`, `node`, `nginx`) are bumped by hand and the image built on demand. |

**Why `docker` has no entry at all.** Two reasons. First, base images define the
interpreter, CUDA line and runtime contract the whole stack is compiled against,
so they move deliberately rather than monthly; the entries that used to exist
opened patch PRs for tags already pinned on purpose, and raised `24-alpine →
26-alpine` the moment they existed (Node 26 is not LTS until 2026-10-28).
Second, nothing in CI builds the image any more, so those PRs could not be
validated before merging. **This costs no vulnerability coverage:** Dependabot
*security* updates do not support the `docker` ecosystem at all — only version
updates — per the supported-ecosystems table
([docs.github.com](https://docs.github.com/en/code-security/reference/supply-chain-security/supported-ecosystems-and-repositories),
Docker: version updates ✓, security updates ✗).

| Base image | Where | Move it how |
| --- | --- | --- |
| `python:3.12-slim` | `backend/Dockerfile.cpu` | Interpreter contract for the whole ML stack. Check torch/numpy publish wheels for the new minor before moving. |
| `nvidia/cuda:12.6.x` | `backend/Dockerfile` | Must match the PyTorch build; a patch bump is safe, a minor is not. |
| `node:24-alpine` | `frontend/Dockerfile` | Must track an Active LTS line and match `frontend-ci.yml`. |
| `nginx:1.30-alpine` | `frontend/Dockerfile` | Even minor = stable line, odd minor = mainline. A "minor" bump can switch lines. |

After editing any of them, build the real image before merging:
`gh workflow run docker-backend.yml --ref main` or `... docker-frontend.yml ...`.

**Why `pip` routine updates are off.** Dependabot classified `torch` 2.5.1 →
2.14.0, `scipy` 1.13 → 1.18, `scikit-learn` 1.5 → 1.9 and `matplotlib` 3.9 →
3.11 as *minor* updates and grouped them into a single PR. That PR was not
installable: `scipy` 1.18 requires `numpy>=2.0` while `numpy` was pinned to
1.26, and those packages require Python >= 3.12 while the image shipped 3.10.
Resolving it meant moving the Python version and the numpy major together. That
is a migration, not a chore, and it needs a human who can change the
interpreter, the numpy major and the image in one commit.

**Why `npm` routine updates are off.** Dependabot's npm updater cannot resolve
this dependency graph. Every scheduled run failed with:

```
npm error notarget No matching version found for @loaders.gl/worker-utils@4.5.1
dependency_file_not_resolvable {message: "Error while updating peer dependency."}
```

while walking `@tanstack/react-query`'s peers through deck.gl's large peer set.
A job that fails on every run and produces nothing is worse than no job, and
the frontend gate (typecheck) plus nightly e2e (build + suite) catch real
breakage. The image-build gap is covered on demand:
`docker-frontend.yml` is the only thing that resolves peers *inside the image*, so
run it manually when a frontend dependency changes.

**Base images are hand-managed, not exempt.** They used to be `ignore`d within a
`docker` entry; now there is no entry, so there is nothing to exempt. The table
above records what each one is coupled to. `python` defines the interpreter the
whole stack is compiled against (Dependabot called `3.10 → 3.14` a *minor* bump;
it cannot build — no cp314 wheels for torch/numpy). `node` must track an Active
LTS line, not the newest release. `nginx` publishes stable (even minor) and
mainline (odd minor) lines, so a minor bump silently switches release lines.

**What is left alone deliberately.** There is no `docker` entry for the
repository root either: Dependabot's docker ecosystem scans Dockerfiles, not
compose files, and no root Dockerfile exists. The previous entry failed on every
run with *"No Dockerfiles nor Kubernetes YAML found in /"*. Compose images
(`postgres`/`timescaledb`, `redis`) are therefore bumped by hand; the
`Docker backend image` workflow runs `docker compose config` before it builds.

`ignore` rules and `open-pull-requests-limit` do **not** affect **security**
updates, which have their own internal limit — so this policy costs no
vulnerability coverage. To re-enable routine bumps for an ecosystem, set its
`open-pull-requests-limit` back to 3 and (for the base images) narrow the
`ignore` list.

## Run this locally before opening a PR

The fast gates (what CI will run on the PR):

```bash
python -m compileall -q backend                # backend syntax gate
python scripts/validate_compose.py             # needs only PyYAML
python scripts/check_versioning.py             # version policy
cd frontend && npm run typecheck               # strict TS over all of src/
node ../scripts/check_e2e_api_coverage.mjs     # e2e mock coverage
```

The deep runs (nightly in CI; run these by hand for the change you made):

**Backend** (from the repository root):

```bash
# Match CI: uv installs the pinned stack far faster than pip.
#   curl -LsSf https://astral.sh/uv/install.sh | sh
TORCH_VERSION="$(grep -E '^torch==' backend/requirements.txt | head -1 | cut -d= -f3)"
uv pip install --system "torch==${TORCH_VERSION}" --index-url https://download.pytorch.org/whl/cpu
uv pip install --system -r backend/requirements.txt -r backend/requirements-dev.txt
python -m compileall -q backend
PYTHONPATH=. python scripts/generate_api_docs.py --check   # generated docs in sync
python -m pytest backend/tests                       # fast, no coverage
python -m pytest backend/tests --cov=backend --cov-report=term-missing   # optional
```

**Frontend** (from `frontend/`):

```bash
npm ci
npm run build
npx playwright install --with-deps chromium   # first time only on a fresh machine
npm test
```

**Docker and compose** (from the repository root):

```bash
docker compose -f docker-compose.yml config --quiet
docker compose -f docker-compose.yml -f docker-compose.cpu.yml config --quiet
docker compose build
```

**Security audits** (optional but recommended):

```bash
pip-audit -r backend/requirements.txt
(cd frontend && npm audit --audit-level=high)
```
