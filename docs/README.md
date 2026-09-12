# Documentation index

Everything in `docs/`, plus the docs kept at the repository root and under
`.github/`. Written because the previous set was not linked from anywhere: five
documents were reachable only if you already knew their filenames, which is how
they stayed stale for ten months without anyone noticing.

## Current

| Document | Contents |
|---|---|
| [`../README.md`](../README.md) | Project entry point: quick start, architecture, data governance, model security, backtesting, migrations, CI |
| [`api.md`](api.md) | API protocol — error envelope and codes, jobs vs. pipeline, prediction gating, data-quality score, notifications, the job WebSocket |
| [`api-endpoints.md`](api-endpoints.md) | **Generated.** Every route and tag, read from the FastAPI app |
| [`frontend.md`](frontend.md) | UI stack, pages and navigation model, data fetching, ⌘K search, onboarding, risk map, jobs/WebSocket status |
| [`deployment.md`](deployment.md) | Deploying on this host: Docker Compose, GPU, model weights, secrets, verification |
| [`../.github/workflows/README.md`](../.github/workflows/README.md) | CI/CD workflows and how to reproduce each locally |

## Historical records

These describe work that is **done and closed**. They are kept because the
reasoning matters for a regulated codebase — why a thing was built the way it
was, and what was deliberately refused — not because they describe the current
tree.

| Document | Contents |
|---|---|
| [`EXECUTIVE_REVIEW_REMEDIATION.md`](EXECUTIVE_REVIEW_REMEDIATION.md) | Finding-by-finding remediation of the executive review, then second and third core-review rounds |
| [`G_SIB_BUILD.md`](G_SIB_BUILD.md) | The G-SIB-grade build: what was added, how each item is verified, and what is explicitly still not done |
| [`data_connectors.md`](data_connectors.md) | Decision record: the NBFI / CCP connector layer — why it was deleted, and the point-in-time exposure path that replaced it |

## Deliberately not duplicated here

- **Request/response field detail** lives in the Pydantic schemas and is served
  at `/docs` (Swagger UI) and `/openapi.json`. Copying it into Markdown is
  exactly how the removed `api_v2.md` came to document seven endpoints that did
  not exist.
- **Configuration**: `.env` (see `.env.example`).

## Removed

Four documents were deleted because they had drifted into being wrong, and one
was replaced by a generator:

| Removed | Why |
|---|---|
| `docs/api_v2.md` | 7 of its 14 endpoints did not exist; described a "Globe-first UI" that was replaced. Superseded by [`api.md`](api.md) + the generated [`api-endpoints.md`](api-endpoints.md) |
| `docs/priority_3_features.md` | Wrong notification contract (`urgent` priority, `data_quality`/`pipeline` categories — none exist), wrong response field names, stale `localhost:8000` URLs. True content folded into [`api.md`](api.md) and [`frontend.md`](frontend.md) |
| `IMPLEMENTATION_SUMMARY.md` | Documented a Three.js 3D globe deleted with `src/components/globe/`; internally contradictory (listed WebSocket as both "Not Implemented" and "Added"); referenced `src/lib/utils/export.js`, which had moved |
| `REAL_TIME_JOBS_DOCUMENTATION.md` | Claimed live WebSocket job updates shipped. Neither half was ever wired: nothing calls `broadcast_job_update()`, and the client used port 8000. Current status in [`frontend.md`](frontend.md) and [`api.md`](api.md) |

Their content survives in git history, and every still-true fact was carried
forward before deletion.
