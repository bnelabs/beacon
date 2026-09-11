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

- **Backend installs use `uv`**, not pip. `uv pip install` resolves and installs
  the pinned stack in seconds where pip took the better part of a minute, and
  its cache is keyed on the two requirements files.
- **The remaining dominant cost is the test run itself** (~98s for 150+ tests,
  including a full offline pipeline execution that trains a model), not installs.
- **Both Dockerfiles use `uv`**, and `frontend/Dockerfile` uses `npm ci`, which
  is faster and reproducible.
- **Docker builds are path-scoped and layer-cached**, so an ordinary code change
  triggers no image build at all.

## Security audit (`security.yml`)

- `pip-audit -r backend/requirements.txt` and `npm audit --audit-level=high` in
  `frontend/`.
- The `pip-audit` version is read from `backend/requirements-dev.txt` rather than
  hard-coded, so the audit tool cannot drift from the pinned dev dependency set.
- Every audit step is `continue-on-error: true`: findings show up in the checks UI but do
  not block merges. Fix findings as a dedicated, reviewable dependency bump.

## Dependabot (`../dependabot.yml`)

The policy is deliberately conservative about the stack where a "minor" version
bump is breaking in practice.

| Ecosystem | Cadence | Automatic? |
| --- | --- | --- |
| `github-actions` (`/`) | weekly | Yes — all updates, grouped. |
| `pip` (`/backend`) | monthly | Minor/patch grouped. The ML/scientific stack (`torch`, `torch-geometric`, `numpy`, `scipy`, `scikit-learn`, `matplotlib`, `pandas`) is exempt from major **and** minor bumps. Framework majors (`fastapi`, `pydantic`, `sqlalchemy`, `celery`) are exempt. |
| `npm` (`/frontend`) | monthly | Minor/patch grouped; majors ignored. |
| `docker` (`/backend`) | monthly | The `python` base image is exempt from major **and** minor bumps; `nvidia/cuda` likewise. |
| `docker` (`/`) | monthly | Compose image majors (`postgres`, `timescale/timescaledb`, `redis`, `nginx`) ignored. |

Why the ML stack is exempt: Dependabot classified `torch` 2.5.1 → 2.14.0,
`scipy` 1.13 → 1.18, `scikit-learn` 1.5 → 1.9 and `matplotlib` 3.9 → 3.11 as
*minor* updates and grouped them into one PR. That PR was not installable —
`scipy` 1.18 requires `numpy>=2.0` while `numpy` was pinned to 1.26, and those
packages require Python >= 3.12 while the image shipped 3.10 — so resolving it
meant moving the Python version and the numpy major together. That is a
migration, not a chore.

`ignore` rules and `open-pull-requests-limit` do **not** affect **security**
updates, which have their own internal limit. Vulnerability alerts therefore keep
working even with this policy.

## Run this locally before opening a PR

**Backend** (from the repository root):

```bash
# Match the pinned torch without pulling CUDA bundles.
TORCH_VERSION="$(grep -E '^torch==' backend/requirements.txt | head -1 | cut -d= -f3)"
python -m pip install "torch==${TORCH_VERSION}" --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
python -m compileall -q backend
python -m pytest backend/tests --cov=backend --cov-report=term-missing
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
