# CI/CD workflows

This directory contains the GitHub Actions automation for BEACON: five
workflows, Dependabot configuration, and a pull-request template.

| File | Purpose | Triggers |
| --- | --- | --- |
| `backend-ci.yml` | Compile and test the FastAPI/Celery/PyTorch backend on Python 3.12 and upload a coverage report. | `push` to `main`, every `pull_request`, manual `workflow_dispatch`. |
| `frontend-ci.yml` | Build the React/Vite app on Node 24 and run the Playwright end-to-end suite. | `push` to `main`, every `pull_request`, manual `workflow_dispatch`. |
| `docker-backend.yml` | Validate every compose file and build the backend CPU image. **Manual only.** | `workflow_dispatch` (*Actions → Docker backend image → Run workflow*). |
| `docker-frontend.yml` | Build the frontend image. **Manual only.** | `workflow_dispatch` (*Actions → Docker frontend image → Run workflow*). |
| `security.yml` | Advisory dependency audits: `pip-audit` for `backend/requirements.txt` and `npm audit` for `frontend/`. Never blocks a merge. | `push` to `main`, every `pull_request`, weekly `schedule` (Mondays 06:17 UTC), manual `workflow_dispatch`. |
| `versioning-ci.yml` | Runs `scripts/check_versioning.py`: VERSION is strict semver, `frontend/package.json` and `backend.__version__` agree with it, and the top changelog block is `[Unreleased]` or the current version. | `push` to `main`, every `pull_request`. |
| `../dependabot.yml` | Version-update PRs for `github-actions`; security-update PRs for `pip` and `npm`. No `docker` entry. | GitHub's scheduler (see the policy below). |

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
- **Steps:** `python -m compileall -q backend` (fast syntax gate) →
  `python scripts/generate_api_docs.py --check` (the generated endpoint inventory
  matches the app) → `alembic upgrade head --sql` (render check only) →
  `python scripts/validate_compose.py` (the merged compose stack and every
  Dockerfile COPY source, no daemon required) → `python -m pytest` with coverage →
  upload the `backend-coverage` artifact (`coverage.xml`, `htmlcov/`) → an advisory
  `ruff` check that reports real defects without blocking.
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

**Both are manual only: `workflow_dispatch` and nothing else.** They are the
"build the real image" button, not a merge gate. No push, pull request or schedule
can start them, so no wait they create can land in front of ordinary work.

They exist because `backend-ci.yml` and `frontend-ci.yml` test the code on the
*runner's* interpreter and Node install, and never build the images. That gap is
not theoretical — both halves of it have already bitten this repository:

- A Dependabot PR proposed `python:3.14-slim` for `backend/Dockerfile.cpu`,
  which passes every Python test (CI uses `setup-python`, not the image) but
  cannot build, because `torch` and `numpy` publish no cp314 wheels.
- `frontend/Dockerfile` used `npm install --legacy-peer-deps`, which skips peer
  dependencies. `@deck.gl/widgets` (a peer of `@deck.gl/react`) was therefore
  absent and the image build failed with *"Rollup failed to resolve import
  '@deck.gl/widgets'"* while Frontend CI stayed green. Now fixed with `npm ci`.

**What manual-only gives up.** Nothing validates a Dockerfile, base image or
compose change automatically any more. Two things cover most of that gap without
a build:

- Backend CI installs the *same* `backend/requirements*.txt` on the *same* Python
  3.12 interpreter, so an uninstallable pin still fails there in ~2 minutes, and
  a Python-version bump that cannot resolve is caught the same way.
- Frontend CI runs `npm ci && npm run build` on Node 24, which catches a broken
  dependency graph — but **not** a peer-dependency gap in the image, because that
  only appears when the image resolves its own tree.

Everything else — a broken base-image tag, a Dockerfile instruction error, a
compose edit — is found when someone runs the workflow. Two changes make that
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

- **Coverage is off for pull requests.** Instrumentation slows this suite by
  roughly **3.5x** (measured 0.63s → 2.19s on the fastest modules). PRs now run
  plain pytest for a fast pass/fail signal; coverage is produced on `main` and
  on manual dispatches, where the report and artifact are actually used.
- **Backend installs use `uv`**, not pip: the CPU torch install went from 23s to
  **3s** and the project dependencies from 39s to **4s** (62s → 7s total). The
  uv cache is keyed on both requirements files.
- **A requirements change never needs a Docker image build.** Backend CI
  installs the same files on the same Python 3.12 interpreter, so an
  uninstallable pin is caught in ~2 minutes without paying for a torch image
  build.
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
Frontend CI catches real breakage. The image-build gap is covered on demand:
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
