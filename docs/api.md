# BEACON API

Protocol-level notes for the BEACON HTTP API: the error envelope, the job and
pipeline lifecycle, the WebSocket handshake, and the two response contracts
(data-quality scores and notifications) that callers branch on.

**The endpoint list is not here.** It is generated, and it lives in
[`api-endpoints.md`](api-endpoints.md). This split is deliberate: the previous
hand-written inventory (`docs/api_v2.md`) drifted until seven of the fourteen
endpoints it documented did not exist, while continuing to read convincingly.
A generated inventory cannot do that.

## Where the schema actually lives

| Source | What it is |
|---|---|
| [`api-endpoints.md`](api-endpoints.md) | Every route and tag, generated from the app by [`scripts/generate_api_docs.py`](../scripts/generate_api_docs.py) |
| `GET /openapi.json` | The machine-readable schema FastAPI generates |
| `GET /docs` | Swagger UI, with full request/response field detail |

Field-level bodies are **not** reproduced in these documents. They are declared
by the Pydantic schemas under `backend/schemas/` and are authoritative at
runtime; copying them into Markdown is how `api_v2.md` went wrong.

## Base URLs

| Environment | Base URL |
|---|---|
| Docker (this host) | `http://192.168.68.57:3456` — API; `/docs` for Swagger |
| Docker (this host) | `http://192.168.68.57:9876` — UI; nginx proxies `/api/` to the backend |
| Local development | `http://localhost:3456` |

See [`deployment.md`](deployment.md) for how these are wired.

## Conventions

- **Two API generations coexist.** `/api/v1/*` is the original surface;
  `/api/v2/*` holds the read-only report and catalogue shapes used by the UI.
  v2 is not a replacement for v1 — it covers four endpoints
  (`datasources`, `datacatalog`, the two reports, plus the backtest report),
  all of which are `GET`.
- **Most collection routes are registered twice**, once bare and once with a
  trailing slash (`/api/v1/jobs` and `/api/v1/jobs/`). Both appear in the
  generated inventory. This is why the inventory holds 120 operations over 100
  distinct paths.
- **`untyped` in the inventory means what it says.** The handler returns a plain
  `dict` and declares no `response_model`, so no schema is enforced. That is a
  real property of the endpoint, recorded rather than papered over.
- **The model catalogue is mounted twice**, at `/api/v1/models` and
  `/api/models`, from the same router. Both are live.

## Error model

There are two distinct error shapes, and clients must handle both.

**1. Typed domain errors** — raised as a `BeaconError` subclass and rendered by
the app-level handler in `backend/api/main.py`:

```json
{
  "code": "DATA_QUALITY_FAILED",
  "message": "Attestation failed: missing_ratio 0.31 exceeds 0.10",
  "severity": "error",
  "context": {"job_id": 731, "policy": "default"},
  "cause": "QualityPolicyViolation: missing ratio"
}
```

Branch on `code`, never on `message` text or the HTTP status alone. `cause` is
present only when the error wrapped an underlying exception.

| `code` | HTTP | Exception |
|---|---|---|
| `PREDICTION_BLOCKED` | 409 | `PredictionBlockedError` |
| `DATA_QUALITY_FAILED` | 422 | `DataQualityError` |
| `DATA_SOURCE_RESTRICTED` | 451 | `RestrictedSourceError` |
| `DATA_INGESTION_FAILED` | 502 | `DataIngestionError` |
| `EMPTY_DATASET` | 502 | `EmptyDatasetError` |
| `SCHEMA_INVALID` | 502 | `SchemaValidationError` |
| `DATASET_MISSING` | 503 | `DatasetMissingError` |
| `DATA_SOURCE_UNAVAILABLE` | 503 | `DataSourceUnavailableError` |

**2. Plain FastAPI errors** — framework validation failures and ad-hoc
`HTTPException`s use the standard shape:

```json
{"detail": "Risk scores only available for prediction/backtest/training jobs"}
```

A 422 can therefore mean either `DATA_QUALITY_FAILED` (a policy rejection,
shape 1) or a request-body validation failure (shape 2). Discriminate on the
presence of `code`.

## Jobs and the pipeline

Two different long-running abstractions exist, and they are not the same thing.

- **`/api/v1/jobs`** — a generic background job record (`job_type`,
  `parameters`). Create with `POST`, poll with `GET /api/v1/jobs/{job_id}`,
  cancel with `DELETE`. `POST /api/v1/jobs/batch/cancel` cancels up to 50 at
  once and returns partial success with a per-job reason.
- **`/api/v1/pipeline`** — the DATA → ENGINE → RESULTS pipeline. Create with
  `POST /api/v1/pipeline`, poll status, then read stage-specific results from
  `/data`, `/engine`, `/results`. Downloads come from
  `GET /api/v1/pipeline/{job_id}/download/{format}`.

There is **no** `/api/v1/jobs/download`, `/api/v1/jobs/train`, or
`/api/v1/jobs/status/{id}`. Training and ingestion are job *types* submitted to
`POST /api/v1/jobs`, or pipeline runs.

## Prediction gating

A prediction or backtest is refused with `PREDICTION_BLOCKED` (409) unless the
DATA stage issued a data-quality attestation for that job. This is a deliberate
fail-closed gate, not a transient error — see the Data Governance section of
the [README](../README.md).

`BEACON_ALLOW_UNVERIFIED_DATA` re-enables prediction without an attestation,
but only outside production: when `resolve_environment()` returns `production`
or `prod`, setting the variable raises `PredictionBlockedError` at resolver
construction, so the override cannot be smuggled into a production process.
Elsewhere it logs a warning. Either way the bypass is **not** recorded in the
API response — the log is the only trace.

## Data-quality score

`GET /api/v1/data-quality/stats` reports a composite score built by
`backend/modules/data/analyzer.py` from three weighted factors:

```
quality_score = 0.4 * validation_score
              + 0.3 * completeness            # 1 - null_count / total_count
              + 0.3 * cleaning_score          # 1 / (1 + fixed_issues / total_rows)
```

`validation_score` is 1.0 when validation found no critical errors and 0.0 when
it found any — it is a gate, not a graded measure. The three endpoints in this
group are `stats` (aggregate), `sources` (per-source freshness and score), and
`trends?days=N` (daily series, default 30).

Freshness buckets are fixed: **fresh** ≤7 days, **stale** 7–30 days,
**outdated** >30 days, **never_synced** for a source with no successful fetch.

## Notifications

`/api/v1/notifications` is a read-mostly feed with a mutation per interaction.

- **Types** (`notification_type`): `info`, `success`, `warning`, `error`, `alert`
- **Priorities** (`priority`): `low`, `medium`, `high`, `critical` — the last is
  `critical`, **not** `urgent`
- **Categories** (`category`): `model`, `data`, `job`, `system`, `risk`

List responses (`NotificationListResponse`) carry `notifications`, `total`, and
`unread_count`. Statistics (`NotificationStats`) carry `total`, `unread`,
`by_priority`, `by_category`, and `urgent`.

`GET /api/v1/notifications` filters on `unread_only`, `category`, `priority`,
`include_dismissed`, `include_archived`, `limit` (default 50) and `offset`. Note
that `total` is the length of the returned page, not the size of the full
result set — do not use it as a total count for pagination.

Backend code raises notifications through `NotificationService`
(`backend/services/notification_service.py`), which exposes
`create_job_notification`, `create_risk_alert`, and `create_data_quality_alert`.

## WebSocket: job updates

The endpoint is registered at **`/api/v1/jobs/ws`** under the *Jobs WebSocket*
tag. It does **not** appear in [`api-endpoints.md`](api-endpoints.md) because
OpenAPI has no representation for WebSocket routes — the generated inventory
reads the OpenAPI schema, so this is the one route it cannot show.

Handshake and keepalive, as implemented in `backend/api/routes/jobs_ws.py`:

| Direction | Message | Meaning |
|---|---|---|
| Server → Client | `{"type": "connected", "message": "Connected to job updates stream"}` | Sent immediately on accept |
| Client → Server | `"ping"` | Keepalive (the client is expected to send this) |
| Server → Client | `{"type": "pong"}` | Reply to `"ping"` |
| Server → Client | `{"type": "ping"}` | Server heartbeat, sent after 30 s of client silence |
| Server → Client | `{"type": "job_update", "job": {...}}` | Job status or progress changed |

### What is not wired

**No `job_update` is ever sent.** `broadcast_job_update()` exists and is
exported in `__all__`, but no code path in the repository calls it. The
connection establishes, the heartbeats work, and then nothing is pushed.

There is a second, independent defect on the client. The React hook
`frontend/src/hooks/useJobsWebSocket.js` dials a hard-coded port:

```js
const wsUrl = `${protocol}//${window.location.hostname}:8000/api/v1/jobs/ws`
```

The backend is published on **3456**, and nginx already proxies `/api/` from
**9876** with `Upgrade`/`Connection` headers. Port 8000 is exposed by nothing,
so in the Docker deployment the browser cannot reach the socket at all.

**Consequence.** The hook retries five times, then falls back to polling
`['jobs']` every 5 seconds. The Jobs page therefore does refresh — via polling,
not via the socket. The "Live updates active" badge never appears, because
`isConnected` is read from a ref during render and no state change triggers a
re-render when the socket opens.

Treat the WebSocket as **scaffolding, not a working feature**. Restoring it
requires both a same-origin URL (`${window.location.host}`) and a caller for
`broadcast_job_update()` on job state transitions. Documented here rather than
described as working, because the earlier
`REAL_TIME_JOBS_DOCUMENTATION.md` claimed live updates shipped, and a reader
would have had no way to tell that neither half was connected.

## Authentication

**There is none.** Every endpoint is unauthenticated, CORS is configured by
`ALLOWED_ORIGINS` (see `.env.example`), and there is no SSO. This is a known,
open gap for any deployment reachable beyond a trusted network, and it is
called out again in [`deployment.md`](deployment.md) and
[`EXECUTIVE_REVIEW_REMEDIATION.md`](EXECUTIVE_REVIEW_REMEDIATION.md).

## Regenerating the endpoint inventory

```bash
PYTHONPATH=. python scripts/generate_api_docs.py          # rewrite
PYTHONPATH=. python scripts/generate_api_docs.py --check  # fail if stale
```

`--check` exits non-zero when the committed file disagrees with the app, which
is the intended CI guard.
