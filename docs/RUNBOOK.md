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

## 5. Alert rules

Rules are created with `POST /api/v1/alert-rules` (there is no UI page yet)
and evaluated by the Celery beat task `evaluate_alert_rules` (every five
minutes); each rule declares its own `evaluation_frequency_minutes`, and a
breach lands as a high-priority notification once per
`evaluation_window_minutes` cooldown. A monitoring platform whose alerts
never fire is quieter than one with no alert feature — the silence reads as
health — so check the notifications, not just the job list.

**Write thresholds on the metric's own scale.** `quality_score` and
`completeness` are stored on the quality gate's 0–100 scale
(`QualityPolicy.min_quality_score = 70.0`), so a data-quality floor is
`quality_score lt 70` — never `quality_score lt 0.8`: every gate-scale score
is > 1.0, so a fraction floor can never breach; the rule reports "ok" for
every dataset the gate refuses. `success_rate` is the exception — it is a
genuine fraction (0–1), and its thresholds stay fractions (L-39).

## 6. What this platform will not do (operator expectations)

- It will not invent data: missing feeds raise typed errors; gaps stay gaps.
- It will not present uncalibrated model output as a risk probability;
  levels read `uncalibrated` until the calibration roadmap lands
  (`README.md` §Scoring and validation, known limitations).
- It will not clear a network it was not given: clearing and fire-sale runs
  require declared or uploaded balance sheets; maximum-entropy estimates
  (`network_estimation`) carry their prior-status caveat into every result.

## 7. Release procedure (maintainer)

The Semver release design (L-48) splits a release into two artifacts: the
**tag** is the machine anchor, the **GitHub Release** is the public artifact.

1. Merge the open cycle PRs, then `git checkout -b release/X.Y.Z` from
   `main` (the branch holds the `[Unreleased]` block the release will carry).
2. `python scripts/release.py patch --tag` (or `minor`/`major`) on the
   release branch: moves `[Unreleased]` to a dated `[X.Y.Z]` heading, bumps
   `VERSION`, syncs `frontend/package.json`, commits atomically, and tags
   the **release commit** `vX.Y.Z`. The changelog-history gate runs inside
   the cut and refuses a cut the changelog has not recorded (L-41). PR +
   merge.
3. Push the tag, then publish: `python scripts/release.py publish` creates
   the GitHub Release for the pushed tag — notes are the versioned
   changelog block verbatim (pre-release versions publish as GitHub
   pre-releases; re-running refreshes an existing release's notes).
4. Verify: `VERSION` and `frontend/package.json` agree, the `[X.Y.Z]`
   heading is dated, and the Releases page shows the new release — the
   versioning CI job fails while any release tag lacks its GitHub Release.
   Pushing the tag and publishing are maintainer acts, never CI's.
