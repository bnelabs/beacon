# CI/CD workflows

This directory contains the GitHub Actions automation for BEACON: five
workflows, Dependabot configuration, and a pull-request template.

| File | Purpose | Triggers |
| --- | --- | --- |
| `backend-ci.yml` | Compile and test the FastAPI/Celery/PyTorch backend on Python 3.12 and upload a coverage report. | `push` to `main`, every `pull_request`, manual `workflow_dispatch`. |
| `frontend-ci.yml` | Build the React/Vite app on Node 24 and run the Playwright end-to-end suite. | `push` to `main`, every `pull_request`, manual `workflow_dispatch`. |
| `docker-backend.yml` | Validate every compose file and build the backend CPU image. | `push`/`pull_request` restricted to backend Dockerfile, backend requirements, compose and `configs/` paths, plus `workflow_dispatch`. |
| `docker-frontend.yml` | Build the frontend image. | `push`/`pull_request` restricted to `frontend/Dockerfile` and the frontend package files, plus `workflow_dispatch`. |
| `security.yml` | Advisory dependency audits: `pip-audit` for `backend/requirements.txt` and `npm audit` for `frontend/`. Never blocks a merge. | `push` to `main`, every `pull_request`, weekly `schedule` (Mondays 06:17 UTC), manual `workflow_dispatch`. |
| `../dependabot.yml` | Version-update PRs for `github-actions`, `pip`, `npm`, and `docker`. | GitHub's scheduler (see the policy below). |

## Concurrency

Every workflow uses a per-ref `concurrency` group, but cancellation is
**conditional**: `cancel-in-progress: ${{ github.ref != 'refs/heads/main' }}`.

- On a pull request or feature branch, a superseded run is cancelled — it
  produces no useful signal and wastes runner minutes.
- **On `main` a run is never cancelled.** A cancelled run leaves the commit
  permanently unverified, and a manual `workflow_dispatch` shares the same
  concurrency group as a `push`, so unconditional cancellation could discard the
  only real run for a commit.

## Backend CI (`backend-ci.yml`)

- **Python 3.12** — the same minor version as `backend/Dockerfile.cpu`
  (`FROM python:3.12-slim`) and the interpreter installed by `backend/Dockerfile`.
  The pinned scientific stack (scipy 1.18, scikit-learn 1.9, matplotlib 3.11)
  requires Python >= 3.12.
- **CPU-only PyTorch.** The torch version is read from `backend/requirements.txt`
  at run time and installed from `https://download.pytorch.org/whl/cpu` *before*
  the requirements files, so the runner does not download the multi-GB CUDA
  bundles and the two can never drift apart.
- **No database service.** The suite does not need a live PostgreSQL. The tests force
  SQLite through `USE_SQLITE=true` (`test_api_smoke.py`, `test_pipeline_integration.py`)
  and drive the app with FastAPI's in-process `TestClient`. The only Docker/Postgres test,
  `test_country_scope.py`, is skipped unless `RUN_DOCKER_SCOPE_TESTS=1`, which CI never
  sets. See the `# why:` comment at the top of the job for details.
- **Steps:** `python -m compileall -q backend` (fast syntax gate) → `python -m pytest`
  with coverage → upload the `backend-coverage` artifact (`coverage.xml`, `htmlcov/`) →
  an advisory `ruff` check that reports real defects without blocking.
- The target and coverage flags are passed explicitly as well as living in
  `pytest.ini` (which uses the correct `[pytest]` header and sets
  `testpaths = backend/tests`). Keeping them in the workflow makes the invocation
  self-describing and immune to config drift.

## Frontend CI (`frontend-ci.yml`)

- **Node 24** (Active LTS until 2028-04), matching the `node:24-alpine` base in
  `frontend/Dockerfile`.
- **All JavaScript actions run on Node 24.** `actions/checkout@v7`,
  `actions/setup-node@v7`, `actions/setup-python@v7`,
  `actions/upload-artifact@v7`, `docker/setup-buildx-action@v4` and
  `docker/build-push-action@v7` all declare `runs.using: node24`, so no action is
  forced onto a newer runtime and the Node 20 deprecation warning does not appear.
  When bumping an action, check its `action.yml` for `using: node24` rather than
  assuming the highest tag is current.
- **Steps:** `npm ci` → `npm run build` → `npx playwright install --with-deps chromium`
  → `npm test` → upload Playwright traces/results only on failure.
- **No live backend is started.** The Playwright suite is fully mocked:
  `frontend/tests/full-frontend.spec.js` installs `frontend/tests/apiMocks.js`, which
  intercepts every `**/api/**` request via `page.route(...)`. Playwright's `webServer`
  block only starts the Vite dev server on `127.0.0.1:8173`.

## Docker image builds (`docker-backend.yml`, `docker-frontend.yml`)

These exist because `backend-ci.yml` and `frontend-ci.yml` test the code on the
*runner's* interpreter and Node install, and never build the images. That gap is
not theoretical — both halves of it have already bitten this repository:

- A Dependabot PR proposed `python:3.14-slim` for `backend/Dockerfile.cpu`,
  which passes every Python test (CI uses `setup-python`, not the image) but
  cannot build, because `torch` and `numpy` publish no cp314 wheels.
- `frontend/Dockerfile` used `npm install --legacy-peer-deps`, which skips peer
  dependencies. `@deck.gl/widgets` (a peer of `@deck.gl/react`) was therefore
  absent and the image build failed with *"Rollup failed to resolve import
  '@deck.gl/widgets'"* while Frontend CI stayed green. Now fixed with `npm ci`.

**They are two workflows, not one, for cost reasons.** A single workflow with a
shared `paths:` filter rebuilds the backend image (torch — the expensive one) on
any frontend change. Scoping each trigger to its own paths keeps cost
proportional to the change.

- `docker-backend.yml` runs `docker compose config` over the base file and both
  overlays (`.cpu`, `.gpu`), then builds `backend/Dockerfile.cpu`.
- `docker-frontend.yml` builds `frontend/Dockerfile`.
- Both use the GitHub Actions build cache (`type=gha,mode=max`), so only a run
  that actually changes the dependency set pays the full install cost.

## Speed notes

Measured improvements, in order of impact:

- **Coverage is off for pull requests.** Instrumentation slows this suite by
  roughly **3.5x** (measured 0.63s → 2.19s on the fastest modules). PRs now run
  plain pytest for a fast pass/fail signal; coverage is produced on `main` and
  on manual dispatches, where the report and artifact are actually used.
- **Backend installs use `uv`**, not pip: the CPU torch install went from 23s to
  **3s** and the project dependencies from 39s to **4s** (62s → 7s total). The
  uv cache is keyed on both requirements files.
- **`backend/requirements*.txt` no longer triggers a Docker image build.**
  Backend CI installs the same file on the same Python 3.12 interpreter, so a
  bad pin is already caught in ~2 minutes. Treating it as a Docker trigger made
  every Dependabot pip PR pay a ~10-minute image build.
- **The Docker image builds are split and path-scoped** (`docker-backend.yml`,
  `docker-frontend.yml`), so a frontend change never rebuilds the backend image
  and vice versa.
- **The Dockerfiles use BuildKit cache mounts** for the uv and npm caches. A
  cache mount is keyed by path rather than by layer hash, so downloaded wheels
  and tarballs survive a base-image change instead of being re-fetched.
- **Docker builds keep `type=gha,mode=max` layer caching**, so only a run that
  genuinely changes a layer pays the full install cost.

What remains dominant is the test work itself: a full offline pipeline
execution that trains a model, plus FastAPI application start-up.

## Security audit (`security.yml`)

- `pip-audit -r backend/requirements.txt` and `npm audit --audit-level=high` in
  `frontend/`.
- The `pip-audit` version is read from `backend/requirements-dev.txt` rather than
  hard-coded, so the audit tool cannot drift from the pinned dev dependency set.
- Every audit step is `continue-on-error: true`: findings show up in the checks UI but do
  not block merges. Fix findings as a dedicated, reviewable dependency bump.

## Dependabot (`../dependabot.yml`)

Short answer to "do we actually need this?": **yes, but only for the parts that
work.** Routine version updates are disabled for the two ecosystems that
repeatedly caused damage or failed outright; security updates remain enabled
everywhere.

| Ecosystem | Routine version updates | Policy |
| --- | --- | --- |
| `github-actions` (`/`) | **Yes** — weekly, grouped, limit 3 | Low risk, high value, no application code. |
| `docker` (`/backend`) | **Yes** — monthly, limit 2 | `python` and `nvidia/cuda` exempt from minor **and** major bumps. |
| `docker` (`/frontend`) | **Yes** — monthly, limit 2 | `node` and `nginx` exempt from minor **and** major bumps. |
| `pip` (`/backend`) | **No** — `open-pull-requests-limit: 0` | Security updates only. |
| `npm` (`/frontend`) | **No** — `open-pull-requests-limit: 0` | Security updates only. |

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
Frontend CI plus the Docker frontend image build already catch real breakage.

**Base images are exempt where the version is contractual.** `python` defines
the interpreter the whole stack is compiled against (Dependabot called
`3.10 → 3.14` a *minor* bump; it cannot build — no cp314 wheels for
torch/numpy). `node` must track an Active LTS line, not the newest release
(26 is not LTS until 2026-10-28). `nginx` publishes stable (even minor) and
mainline (odd minor) lines, so a minor bump silently switches release lines.

**What is left alone deliberately.** There is no `docker` entry for the
repository root: Dependabot's docker ecosystem scans Dockerfiles, not compose
files, and no root Dockerfile exists. The previous entry failed on every run
with *"No Dockerfiles nor Kubernetes YAML found in /"*. Compose images
(`postgres`/`timescaledb`, `redis`) are therefore bumped by hand.

`ignore` rules and `open-pull-requests-limit` do **not** affect **security**
updates, which have their own internal limit — so this policy costs no
vulnerability coverage. To re-enable routine bumps for an ecosystem, set its
`open-pull-requests-limit` back to 3 and (for the base images) narrow the
`ignore` list.

## Run this locally before opening a PR

**Backend** (from the repository root):

```bash
# Match CI: uv installs the pinned stack far faster than pip.
#   curl -LsSf https://astral.sh/uv/install.sh | sh
TORCH_VERSION="$(grep -E '^torch==' backend/requirements.txt | head -1 | cut -d= -f3)"
uv pip install --system "torch==${TORCH_VERSION}" --index-url https://download.pytorch.org/whl/cpu
uv pip install --system -r backend/requirements.txt -r backend/requirements-dev.txt
python -m compileall -q backend
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
