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
| [`frontend.md`](frontend.md) | Design system and brand, UI stack, pages and navigation model, data fetching, ⌘K search, onboarding, risk map, jobs/WebSocket status |
| [`deployment.md`](deployment.md) | Deploying on this host: Docker Compose, GPU, model weights, secrets, verification |
| [`RUNBOOK.md`](RUNBOOK.md) | Operating the deployment: boot order, environment, health checks, failure matrix, backup/restore drill |
| [`VERSIONING.md`](VERSIONING.md) | SemVer policy, changelog discipline, release tooling, what CI enforces |
| [`LANGUAGE_STRATEGY.md`](LANGUAGE_STRATEGY.md) | The measured Python/Rust boundary and the rule for moving it |
| [`../.github/workflows/README.md`](../.github/workflows/README.md) | CI/CD workflows and how to reproduce each locally |
| [`QUANT_REVIEW_2026-09.md`](QUANT_REVIEW_2026-09.md) | Fourth-round external quant review: trajectory, per-subsystem verdicts, findings register with dispositions, phased fix plan — the live limitations register |

## Audit history and standing decisions

Five external review rounds (executive ×3, quant, last-mile) ran against this
tree between 2025 and 2026-09. Their per-finding logs were deleted once every
item in them closed; the reasoning that still governs decisions lives here and
in the reachability census (`backend/tests/test_reachability.py`), not in
archived narratives:

- **Point-in-time is the only exposure path.** The NBFI/CCP connector layer was
  deleted (no production caller, granularity the engine cannot consume, and the
  plugin interface cannot carry its two-clock guarantee). Revision-vintage
  exposures go through the PIT store; the census `REMOVED` register holds the
  evidence.
- **Neural SDE stays a caller-declared latent-stress scenario**, not the default
  propagator: the default must remain the verified Eisenberg–Noe/GLT core.
- **Parked, not deleted, with preconditions:** temporal GNN (needs exposure
  vintages at training time), mixture-of-experts (needs labelled regime
  history), subgraph explanations, causal validation, streaming/federated
  training. Each census disposition names its unblocking input.
- **Deferred with reasons:** copula dependence (the clearing engine already
  propagates joint stress), generalized-hyperbolic tails (the Student-t HMM
  covers the regime-variance channel first).
- **Deferred data sources, with the precondition each is waiting on:**
  Bank of England (its statistics are served through an interactive database;
  a plugin lands only after a stable keyless endpoint and its field names are
  probe-verified live, the discipline the FDIC rewrite set), OpenFIGI (an
  identifier-mapping service, and no BEACON input is security-level — it
  becomes relevant with the EBA/security granularity, not before), and the EBA
  risk dashboard (bank-by-bank bundles published per reporting period with no
  bulk API; the census already ties EBA transparency ingest to LEI
  resolution). Proposing a source is cheap; declaring one the UI shows as
  enabled but that cannot fetch is the exact failure `test_keyless_feeds.py`
  guards against.
- **Deferred: a minimal `docker-compose.simple.yml`.** The CPU overlay already
  is the no-GPU topology and the base file is the product; a third variant
  multiplies the compose configurations CI must keep valid without a
  deployment scenario the two existing files do not cover.
- **Rejected on evidence: Stooq as a keyless price feed.** Its CSV download
  endpoint answers an anti-bot challenge page (HTTP 200 carrying HTML) rather
  than data as of 2026-09-15, so a plugin against it would be dead on arrival.
  The registry-integrity test (`test_keyless_feeds.py`) exists precisely
  because the previous FDIC plugin was exactly that: a file referencing a base
  module that never existed, advertised by the UI as enabled. FDIC has been
  rewritten against the live BankFind Suite API with only field names verified
  by probe; interbank marginal fields are declared only once verified the same
  way.
- **No hand-maintained endpoint documentation.** The inventory is generated
  (`api-endpoints.md`, guard test) after a hand-written one documented seven
  endpoints that did not exist.
- **Auth is an optional bearer gate** (`BEACON_API_TOKEN`), not a user model;
  multi-user deployments are out of scope and say so in `deployment.md`.
- **Removed modules stay removed in the census**, with the evidence, so the
  deletion stays discoverable and cannot be silently re-introduced.

What shipped in each round is in [`../CHANGELOG.md`](../CHANGELOG.md); what is
still open is in the [`QUANT_REVIEW_2026-09.md`](QUANT_REVIEW_2026-09.md)
register and the census dispositions.

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
| `G_SIB_BUILD.md` | Rounds 1–2 log, closed: every verified item is merged and its "still missing" list was superseded by the [`QUANT_REVIEW_2026-09.md`](QUANT_REVIEW_2026-09.md) register |
| `EXECUTIVE_REVIEW_REMEDIATION.md` | Rounds 1–4 finding-by-finding log, closed: every item merged. Still-governing reasoning now lives in the standing-decisions list above and the reachability census |
| `data_connectors.md` | Decision record folded into the census `REMOVED` register and the point-in-time tests; the doc added no fact neither holds |
| `FIFTH_ROUND_RESPONSE.md` | Last-mile response log, closed: wiring merged, rejections and queued preconditions live in census dispositions |

Outside `docs/`: `configs/timescaledb/timescale_setup.sql` was deleted as a
drifted second copy of the migration DDL (it lacked the three baseline tables;
migration error messages now state the manual step), and
`configs/scenario_library.json` was deleted with zero references from any code,
test, workflow or doc.

Their content survives in git history, and every still-true fact was carried
forward before deletion.
