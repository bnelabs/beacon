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

## Data-source connectivity

Three endpoints turn "configured" into "connected":

| Endpoint | Meaning |
|---|---|
| `GET /api/v1/data-sources/health` | Per feed: cadence (`sync_interval_minutes`, null means manual-only), backoff factor, consecutive failures with the last reason, last start/duration/rows, next due date, `overdue`, `collection_running`. |
| `POST /api/v1/data-sources/{id}/sync` | **202** and a queued `data_collection` job scoped to the source's enabled catalogue items -- the same job the scheduler queues. **409** while a collection for that source is open or the source is disabled. |
| `POST /api/v1/data-sources/{id}/probe` | Runs the plugin's own `test_connection` against the live provider with the saved config; environment-held API keys are injected exactly as the collector injects them. Answers `{success, message, details}`. |

Celery beat ticks every five minutes and enqueues whichever scheduled sources
are due (interval, doubled per consecutive failure up to eight intervals, plus
a stable per-source jitter). `PUT /api/v1/data-sources/{id}` with
`sync_interval_minutes` sets or clears (`null`) the cadence. The operator view
of all of this is `docs/deployment.md` §5.

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

## Alerts that fire, and numbers that stay re-derivable

Alert rules (`/api/v1/alert-rules`) are evaluated by the beat tick on each
rule's own `evaluation_frequency_minutes`; a breach raises exactly one
notification per `evaluation_window_minutes` cooldown, typed `alert`, with
the measured value, the operator and the threshold in the message and in
`extra_data`. A rule whose metric has no measurement in its window is skipped
and says so in the tick summary -- silence is never ambiguous with health.

Indicator observations keep an append-only vintage log
(`indicator_vintage_log`): every write records the value as written and the
instant it was published here, so `TimeSeriesStore.observations_as_of(source,
indicator, as_of)` re-derives the series exactly as it stood at any past date.
Restatements update the latest-value store without rewriting history, which
is what keeps a backtest from "knowing" in May what was published in June.

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

### How `job_update` is delivered

Two processes are involved, which is the part that was originally missed. The
socket lives in the API process, but most progress is written by the **Celery
worker**. A process-local registry cannot see those writes, so delivery runs
over Redis — already a hard dependency as the Celery broker:

1. `JobService.update_job_status` is the single choke point through which every
   status and progress change passes, in both processes. After each commit it
   calls `job_events.publish_job_update`, which publishes to the Redis channel
   `beacon:job_updates`. `create_job` publishes too, and `cancel_job` needs its
   own call because it writes status directly rather than via that method.
2. The API process runs `job_events.relay_job_updates` as a background task
   started in the application lifespan. It subscribes to that channel and calls
   `manager.broadcast`, which writes to every socket attached to this process.

Publishing is **best-effort and never raises**, so a Redis outage cannot fail a
job. The subscriber reconnects on a backoff, and the client independently falls
back to polling after five failed socket connects — so degradation is gradual
rather than silent.

The client dials the socket **same-origin**
(`${protocol}//${window.location.host}/api/v1/jobs/ws`), which nginx proxies with
the `Upgrade`/`Connection` headers. It previously hard-coded port 8000, which
nothing listens on.

This is a bus, not a queue: messages are dropped when no subscriber is attached,
nothing is retried or replayed, and ordering between two publishers is not
enforced. That is acceptable precisely because the polling fallback exists.

## Authentication

**There is no user model.** If `BEACON_API_TOKEN` is set, every `/api/*` route
requires `Authorization: Bearer <token>` (the Swagger/openapi endpoints stay
open so the protocol remains browsable); the SPA prompts for the token once and
stores it in `localStorage`. If the variable is unset the API is open, which
is fine for a single-operator host and not fine beyond a trusted network —
`deployment.md` and `RUNBOOK.md` say the same, and neither pretends this is
multi-user auth: there is no SSO, no roles, no per-user state.
`GET /api/v1/system/status` reports the live posture as `auth.mode`
(`"none"` or `"bearer-gate"`, never the token itself) so the UI states what the
deployment actually enforces instead of guessing.

## Regenerating the endpoint inventory

```bash
PYTHONPATH=. python scripts/generate_api_docs.py          # rewrite
PYTHONPATH=. python scripts/generate_api_docs.py --check  # fail if stale
```

`--check` exits non-zero when the committed file disagrees with the app, which
is the intended CI guard.
