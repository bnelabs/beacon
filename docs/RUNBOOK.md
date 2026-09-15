# Runbook — operating BEACON

Written for the operator on call, not for the author. Every procedure here is
either exercised by `scripts/restore_drill.py` or by the CI suite; anything
that is a judgement call says so.

## 1. Start / stop / health

```bash
docker compose up -d                 # postgres+timescale, redis, backend, worker, frontend
docker compose logs -f backend       # entrypoint runs alembic before uvicorn
curl -fsS http://localhost:3456/health
curl -fsS http://localhost:9876/     # SPA (nginx proxies /api/)
```

The backend entrypoint (`backend/entrypoint.sh`) runs `alembic upgrade head`
with a retry loop before the API or worker starts; set
`BEACON_RUN_MIGRATIONS=0` only if migrations are managed externally. A first
boot with two containers racing is tolerated: the baseline migration is
inspector-guarded and the loser's retry is a no-op.

## 2. Configuration surface

| Variable | Effect | Default |
|---|---|---|
| `BEACON_API_TOKEN` | Enables the bearer-token gate on `/api/*` (docs endpoints stay open) | unset = single-operator, no auth |
| `BEACON_ENV` / `ENVIRONMENT` | `production` refuses the unverified-data override outright | unset |
| `BEACON_ALLOW_UNVERIFIED_DATA` | Predict without attestation (dev only; refused in production) | 0 |
| `BEACON_ALLOW_UNSAFE_CHECKPOINT_LOAD` | Load legacy non-weights-only checkpoints; logged as a security event | 0 |
| `BEACON_ALLOW_UNTRAINED_FALLBACK` | Score with an untrained model (smoke tests only) | 0 |
| `BEACON_CUSTOM_API_ALLOW_HTTP` | Permit http for custom-API sources | 0 (https only) |
| `BEACON_CUSTOM_API_HOST_ALLOWLIST` | Comma-separated exact hosts the custom-API plugin may fetch | unset = policy only |
| `BILATERAL_EXPOSURE_*` | Upload size/row/institution caps for exposure matrices | see `.env.example` |

All four `BEACON_ALLOW_*` overrides are **fail-closed by default** and each
emits a log line when used. If you see one in logs without having set it,
treat it as an incident.

## 3. Restore drill (run after every deployment change, and on a schedule)

```bash
PYTHONPATH=. python scripts/restore_drill.py                 # in-container checks
PYTHONPATH=. python scripts/restore_drill.py --data-dir /app/data   # + exposure manifests
```

The drill proves, against a temporary copy, the three recovery claims:
content-addressed snapshots restore exactly and mutated data does not verify;
the point-in-time store round-trips and refuses cut-offs before publication;
exposure manifests match their matrices. It exits non-zero on any failure and
never touches production state. A backup nobody has restored is a hypothesis.

## 4. Failure modes and first responses

| Symptom | First look | Then |
|---|---|---|
| Job stuck `running` | `docker compose logs worker` | Celery concurrency vs long training; restart worker, job state is in Postgres |
| `PredictionBlockedError` | missing attestation or missing checkpoint | run data collection → gate → training; do **not** set overrides in production |
| Risk map shows the demo network | banner says DEMO NETWORK | no exposure matrix stored; upload one (`POST /api/v1/network/...`) |
| Validation report `not_validated` | backtest ran without `event_definition` | re-run with a declared event definition (Jobs → Backtest & validate) |
| Custom-API source refused | `URL policy refusal` in the job failure | scheme/host policy; allowlist or https migration, never disable the policy wholesale |
| 401 across the UI | `BEACON_API_TOKEN` set | supply the token in the prompt the SPA shows; rotate if leaked |

## 5. What this platform will not do (operator expectations)

- It will not invent data: missing feeds raise typed errors; gaps stay gaps.
- It will not present uncalibrated model output as a risk probability;
  levels read `uncalibrated` until the calibration roadmap lands
  (`docs/QUANT_REVIEW_2026-09.md`, Phase 2).
- It will not clear a network it was not given: clearing and fire-sale runs
  require declared or uploaded balance sheets; maximum-entropy estimates
  (`network_estimation`) carry their prior-status caveat into every result.

## 6. Release procedure

1. Merge the open cycle PRs.
2. `python scripts/release.py minor` on a release branch (bumps `VERSION`,
   dates the changelog block, syncs `frontend/package.json`); PR + merge.
3. Tag the merge commit `vX.Y.Z` (annotated message: what the release
   carries). `scripts/check_versioning.py` guards drift in CI.
