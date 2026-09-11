# CI/CD workflows

This directory contains the GitHub Actions automation for BEACON. There are three
workflows plus Dependabot configuration, and a pull-request template.

| File | Purpose | Triggers |
| --- | --- | --- |
| `backend-ci.yml` | Compile and test the FastAPI/Celery/PyTorch backend on Python 3.12 and upload a coverage report. | `push` to `main`, every `pull_request`, manual `workflow_dispatch`. |
| `frontend-ci.yml` | Build the React/Vite app on Node 20 and run the Playwright end-to-end suite. | `push` to `main`, every `pull_request`, manual `workflow_dispatch`. |
| `security.yml` | Advisory dependency audits: `pip-audit` for `backend/requirements.txt` and `npm audit` for `frontend/`. Never blocks a merge. | `push` to `main`, every `pull_request`, weekly `schedule` (Mondays 06:17 UTC), manual `workflow_dispatch`. |
| `../dependabot.yml` | Weekly version-update PRs for the `pip`, `npm`, `github-actions`, and `docker` ecosystems. | GitHub's scheduler (weekly). |

All workflows use a per-ref `concurrency` group with `cancel-in-progress: true`, so
pushing again to the same branch cancels the older run instead of queueing two.

## Backend CI (`backend-ci.yml`)

- **Python 3.12** — the same minor version as `backend/Dockerfile.cpu`
  (`FROM python:3.12-slim`) and the interpreter installed by `backend/Dockerfile`.
  The pinned scientific stack (scipy 1.18, scikit-learn 1.9, matplotlib 3.11)
  requires Python >= 3.12.
- **CPU-only PyTorch.** The torch version is read from `backend/requirements.txt`
  and installed from `https://download.pytorch.org/whl/cpu` *before* the
  requirements files, so the runner does not download the multi-GB CUDA bundles
  and can never drift from the pinned version.
- **No database service.** The suite does not need a live PostgreSQL. The tests force
  SQLite through `USE_SQLITE=true` (`test_api_smoke.py`, `test_pipeline_integration.py`)
  and drive the app with FastAPI's in-process `TestClient`. The only Docker/Postgres test,
  `test_country_scope.py`, is skipped unless `RUN_DOCKER_SCOPE_TESTS=1`, which CI never
  sets. See the `# why:` comment at the top of the job for details.
- **Steps:** `python -m compileall -q backend` (fast syntax gate) → `python -m pytest`
  with coverage → upload the `backend-coverage` artifact (`coverage.xml`, `htmlcov/`) →
  an advisory `ruff` check that reports real defects without blocking.
- **pytest configuration caveat.** The root `pytest.ini` uses the `[tool:pytest]` header,
  which is only valid in `setup.cfg`; modern pytest ignores its options (including the
  `--cov` flags). The workflow therefore passes `backend/tests` and the coverage flags
  explicitly.

## Frontend CI (`frontend-ci.yml`)

- **Node 20**, matching the `node:20-alpine` base in `frontend/Dockerfile`.
- **Steps:** `npm ci` → `npm run build` → `npx playwright install --with-deps chromium`
  → `npm test` → upload Playwright traces/results only on failure.
- **No live backend is started.** The Playwright suite is fully mocked:
  `frontend/tests/full-frontend.spec.js` installs `frontend/tests/apiMocks.js`, which
  intercepts every `**/api/**` request via `page.route(...)`. Playwright's `webServer`
  block only starts the Vite dev server on `127.0.0.1:8173`. Starting Postgres, Redis, a
  worker, or `uvicorn` would add minutes of startup and still exercise nothing extra.

## Security audit (`security.yml`)

- `pip-audit -r backend/requirements.txt` and `npm audit --audit-level=high` in
  `frontend/`.
- Every audit step is `continue-on-error: true`: findings show up in the checks UI but do
  not block merges. Fix findings as a dedicated, reviewable dependency bump.

## Dependabot (`../dependabot.yml`)

Weekly PRs for `pip` (`/backend`), `npm` (`/frontend`), `github-actions` (`/`), and
`docker` (`/backend` for the Dockerfiles, `/` for the compose files). Minor and patch
updates are grouped per ecosystem; major updates arrive individually.

## Run this locally before opening a PR

**Backend** (from the repository root):

```bash
python -m pip install torch==2.5.1 --index-url https://download.pytorch.org/whl/cpu
python -m pip install -r backend/requirements.txt -r backend/requirements-dev.txt
python -m compileall -q backend
python -m pytest backend/tests \
  --cov=backend --cov-report=term-missing
```

**Frontend** (from `frontend/`):

```bash
npm ci
npm run build
npx playwright install --with-deps chromium   # first time only on a fresh machine
npm test
```

**Security audits** (optional but recommended):

```bash
pip-audit -r backend/requirements.txt
(cd frontend && npm audit --audit-level=high)
```
