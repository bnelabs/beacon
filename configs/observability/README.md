# BEACON Observability

Prometheus metrics, data-drift detection and Celery queue/worker health for the
BEACON systemic liquidity-risk platform.

```
configs/observability/
├── prometheus/
│   ├── prometheus.yml        # scrape config (backend /metrics + celery-exporter)
│   └── alert_rules.yml       # 25 alert rules
└── grafana/
    ├── provisioning/
    │   ├── datasources/prometheus.yml   # datasource uid: beacon-prometheus
    │   └── dashboards/dashboards.yml    # file provider -> /etc/grafana/dashboards
    └── dashboards/beacon-overview.json  # 16-panel overview (schemaVersion 39)
```

Python side: `backend/monitoring/` (`metrics.py`, `drift.py`, `celery_health.py`),
wired into the API by `backend/api/main.py` (`setup_metrics(app)`) and covered by
`backend/tests/test_observability.py`.

## Quick start

1. Merge the `prometheus`, `grafana` and `celery-exporter` services (and the
   `prometheus_data`/`grafana_data` named volumes) from the snippets below into
   `docker-compose.yml`.
2. `docker compose up -d prometheus grafana celery-exporter`
3. Prometheus → <http://localhost:9090>, Grafana → <http://localhost:3000>
   (default `admin` / `beacon`, override with `GRAFANA_ADMIN_USER` /
   `GRAFANA_ADMIN_PASSWORD`), dashboard **BEACON — Overview**.

No change to the existing `backend`, `celery-worker`, `redis` or `postgres`
services is required.

## How Celery worker metrics are exposed

**Decision: a dedicated exporter service** (`danihodovic/celery-exporter`,
scraped as the `celery-exporter` job at `celery-exporter:9808`). It subscribes to
the broker event stream, so it needs no change to the worker command line, no
worker-side HTTP endpoint and no shared multiprocess directory.

Rejected alternatives:

* **Pushgateway** — a Pushgateway cannot express *liveness*. The
  "zero live workers" alert needs `up`-style semantics; pushed metrics go stale
  but keep looking healthy, so a crashed training pool would never alert.
* **Worker-embedded HTTP** — requires modifying the worker image/command for
  every pool. Kept as an *optional* path only (see below), deliberately not a
  scrape target, so exactly one mechanism feeds Celery metrics to Prometheus.

The backend API process additionally publishes BEACON-native application metrics
at `/metrics` and samples Celery queue depth + worker liveness through the Celery
control API **at scrape time** (`beacon_celery_queue_depth`,
`beacon_celery_workers_online`). That sampling runs inside the API process — it
is not a worker-side endpoint, so it does not compete with the exporter choice.
Alert rules reference the exporter series first and fall back to the BEACON
gauges with `or`, so they work in either deployment shape.

Disable scrape-time sampling with `BEACON_CELERY_METRICS_AT_SCRAPE=0` on the
backend service.

### Optional: Celery multiprocess mode

`backend/monitoring/metrics.py` supports `PROMETHEUS_MULTIPROC_DIR`. Set it
**before the Python process starts** (the client reads it at import time) to a
shared, writable, empty directory, and expose an HTTP handler in the worker if
you prefer that over the exporter:

```yaml
celery-worker:
  environment:
    PROMETHEUS_MULTIPROC_DIR: /tmp/prometheus-multiproc
  command: >
    sh -c 'mkdir -p "$PROMETHEUS_MULTIPROC_DIR" &&
           celery -A backend.tasks.celery_app worker --loglevel=info --concurrency=2'
```

When it is set, `MultiProcessCollector` is registered on the module registry and
gauges use explicit `multiprocess_mode` (`max`, so a single high-PSI or
single-live-worker sample is not diluted). Do **not** set it for the API process.

## Environment variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `PROMETHEUS_MULTIPROC_DIR` | unset | Enable Celery prefork metric aggregation (see above). |
| `BEACON_CELERY_METRICS_AT_SCRAPE` | `1` | Refresh queue depth + worker health during `/metrics`. |
| `BEACON_CELERY_QUEUES` | discovered / `celery` | Comma-separated queue keys to `LLEN`. |
| `BEACON_EXPECTED_WORKER_POOLS` | `{"default": ["celery"]}` | JSON `{"pool": ["hostname-or-queue-or-task token", ...]}`. |
| `BEACON_EXPECTED_TRAINING_WORKERS` | `0` | Required training workers; `> 0` makes a dead training pool alert. |
| `BEACON_WORKER_HEALTH_TTL` | `10` | Seconds to cache the `inspect()` snapshot. |
| `BEACON_CELERY_INSPECT_TIMEOUT` | `1.0` | Celery control API timeout (seconds). |
| `BEACON_REDIS_SOCKET_TIMEOUT` / `BEACON_REDIS_CONNECT_TIMEOUT` | `0.5` | Redis timeouts used by `queue_depth`. |
| `GRAFANA_ADMIN_USER` / `GRAFANA_ADMIN_PASSWORD` | `admin` / `beacon` | Grafana admin credentials. |

## Metrics reference

Application metrics (backend API process, job `beacon-backend`):

| Metric | Type | Labels |
| --- | --- | --- |
| `beacon_http_requests_total` | counter | `method`, `route`, `status` |
| `beacon_http_request_duration_seconds` | histogram | `method`, `route` |
| `beacon_pipeline_jobs_started_total` | counter | `stage`, `job_type` |
| `beacon_pipeline_jobs_completed_total` | counter | `stage`, `job_type` |
| `beacon_pipeline_jobs_failed_total` | counter | `stage`, `job_type` |
| `beacon_pipeline_job_duration_seconds` | histogram | `stage`, `job_type` |
| `beacon_data_ingestion_attempts_total` | counter | `plugin`, `status` |
| `beacon_data_ingestion_failures_total` | counter | `plugin`, `error_code` |
| `beacon_data_ingestion_records_total` | counter | `plugin` |
| `beacon_celery_tasks_total` | counter | `task_name`, `status` |
| `beacon_celery_task_duration_seconds` | histogram | `task_name` |
| `beacon_celery_queue_depth` | gauge | `queue` |
| `beacon_celery_workers_online` | gauge | `pool` (`all`, per pool, `<pool>_expected`) |
| `beacon_celery_worker_tasks` | gauge | `state` (`active`/`reserved`/`scheduled`) |
| `beacon_model_inference_latency_seconds` | histogram | `model` |
| `beacon_model_inference_errors_total` | counter | `model`, `error_code` |
| `beacon_predictions_total` | counter | `region`, `risk_level` |
| `beacon_feature_drift_psi` | gauge | `feature` |

Celery worker metrics come from the exporter (`celery_queue_length`,
`celery_worker_up`, `celery_task_*`) — see the exporter's own documentation for
its full list.

### Python API

```python
from backend.monitoring.metrics import (
    pipeline_job_timer, record_ingestion_failure, record_ingestion_attempt,
    record_prediction, record_inference,
)

with pipeline_job_timer("training", "training"):   # started/completed/failed + duration
    run_training(...)

record_ingestion_attempt("fred", success=False, error_code="HTTP 500")
record_ingestion_failure(plugin_type="fred", error_code="HTTP 500")  # explicit
record_prediction(region="EUROPE", risk_level="high", count=3,
                  model="gnn-liquidity", duration_seconds=0.42)
```

Drift detection:

```python
from backend.monitoring.drift import detect_drift, FeatureDriftMonitor

report = detect_drift(reference_df, current_df)       # PSI + KS + JSD, JSON-able

monitor = FeatureDriftMonitor(buckets=10, name="gnn-v3").fit(reference_df)
monitor.save("configs/observability/drift/gnn-v3.json")   # persist reference
loaded = FeatureDriftMonitor.load("configs/observability/drift/gnn-v3.json")
report = loaded.score(current_df)     # PSI from frozen training bins + gauge
```

PSI bands: `< 0.1` none, `0.1 – 0.25` moderate, `> 0.25` major.

`prometheus_client` is optional: without it every metric becomes a no-op shim,
`/metrics` reports that metrics are disabled, and the app boots normally.

## Runbooks

### Data ingestion failures

1. Open **BEACON — Overview → "Ingestion failures by error code"** to find the
   dominant `plugin` / `error_code` pair.
2. `error_code` is the plugin-supplied failure code (`HTTP 500`,
   `RATE_LIMITED`, `AUTH_FAILED`, `TIMEOUT`, …). Group by code to separate
   upstream outages from credential/quota problems.
3. Rate limits/quota → raise the plan or lower `priority`/frequency for that
   catalogue item. Auth → rotate the API key in `.env`
   (`FRED_API_KEY`, `ALPHA_VANTAGE_API_KEY`, `SEC_API_KEY`) and restart the
   backend. Schema drift in the upstream payload → update the plugin.
4. Silence with `BeaconDataIngestionFailureRateSpike` only while an upstream
   incident is tracked.

### Feature drift

1. Identify the feature on the **"Feature drift — PSI per feature"** panel.
2. `PSI > 0.25` (critical) means the live distribution no longer matches the
   training reference: check for an upstream data revision, a units/scale change,
   a new regime, or a broken feature computation before retraining.
3. Inspect `jensen_shannon_divergence` and `ks_pvalue` in the drift report. A high
   KS with low PSI means a shape shift that the binning did not capture.
4. Retrain or roll back. Only then re-fit `FeatureDriftMonitor` — re-fitting on
   drifted data silently hides the drift.

### Celery queues

1. Queue depth is visible on **"Celery queue depth"**; thresholds at 200
   (warning band), 1000 (high), 10000 (critical).
2. Depth high + workers alive → arrivals exceed capacity: scale
   `celery-worker` (`--concurrency`) or add a replica for the affected queue.
3. Depth high + zero workers → see *Celery workers*.
4. A single queue growing while others drain usually means tasks are routed to a
   queue with no consumer; check `task_routes`/`-Q` on the worker.

### Celery workers

1. **"Live Celery workers"** must be ≥ 1. Zero for 5 minutes fires
   `BeaconCeleryNoLiveWorkers` (critical) — all background work has stopped.
2. Inspect containers: `docker compose logs --tail=200 celery-worker`. The usual
   causes are OOM kills during GNN training (`worker_max_tasks_per_child=50`),
   broker auth errors, or a bad deploy.
3. A dead **training** pool while other workers are alive fires
   `BeaconCeleryTrainingPoolDead`. Set `BEACON_EXPECTED_TRAINING_WORKERS` to the
   pool size you require so this alert has a target, and declare pools with
   `BEACON_EXPECTED_WORKER_POOLS` for per-pool gauges.
4. `reserved` climbing with `active` flat means workers are prefetching but stuck
   — look for a hung task (a single `task_time_limit`-bound job).

### API

1. **"API request rate by status"** and **"API latency p50/p95/p99"** show the
   failure and latency shape. The 5xx ratio alert fires at 1% (warning) / 5%
   (critical); p95 > 2s (warning) and p99 > 10s (critical).
2. `BeaconBackendDown` means `/metrics` itself is unreachable — check the
   container and `docker compose logs backend`.
3. Per-route detail comes from `beacon_http_requests_total`: filter
   `status=~"5.."` and group by `route` in Prometheus to find the offender.

### Pipeline jobs

1. **"Pipeline job throughput"** (started vs completed) and **"Pipeline job
   failures by stage"** localise the failure to a stage/job type.
2. `BeaconPipelineJobFailureRateHigh` fires above 10% over 15 minutes; the
   per-stage rule fires above 25% for a specific `stage`/`job_type`.
3. `BeaconPipelineJobStalled` (no starts for 30 minutes with a non-empty queue)
   is almost always a dispatch or routing problem, not a job bug.
4. Reproduce with `run_data_collection` / `run_training` / `run_prediction` /
   `run_backtest` directly against the same parameters.

### Inference latency

1. **"Model inference latency p95 / p99"** — the SLO breach alert fires at
   p95 > 2.5s for 10 minutes; p99 > 10s is critical.
2. Check GPU availability/utilisation first (`nvidia-smi` on the worker host),
   then batch size and input tensor sizes. A jump with unchanged inputs usually
   means CPU fallback because CUDA is unavailable.
3. `beacon_model_inference_errors_total` broken down by `error_code` separates
   `CUDA_OOM` (reduce batch size) from data/validation errors.

## Merge snippets

Services (into the existing `services:` block):

```yaml
  prometheus:
    image: prom/prometheus:v2.51.2
    container_name: beacon-prometheus
    command:
      - --config.file=/etc/prometheus/prometheus.yml
      - --storage.tsdb.path=/prometheus
      - --storage.tsdb.retention.time=15d
      - --web.enable-lifecycle
    volumes:
      - ./configs/observability/prometheus:/etc/prometheus:ro
      - prometheus_data:/prometheus
    ports:
      - "9090:9090"
    depends_on:
      backend:
        condition: service_started
      celery-exporter:
        condition: service_started
    healthcheck:
      test: ["CMD", "wget", "--spider", "-q", "http://localhost:9090/-/healthy"]
      interval: 30s
      timeout: 5s
      retries: 5
    networks:
      - beacon-network
    restart: unless-stopped

  grafana:
    image: grafana/grafana:10.4.2
    container_name: beacon-grafana
    environment:
      GF_SECURITY_ADMIN_USER: ${GRAFANA_ADMIN_USER:-admin}
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_ADMIN_PASSWORD:-beacon}
      GF_USERS_ALLOW_SIGN_UP: "false"
      GF_ANALYTICS_REPORTING_ENABLED: "false"
      GF_DASHBOARDS_DEFAULT_HOME_DASHBOARD_PATH: /etc/grafana/dashboards/beacon-overview.json
    volumes:
      - ./configs/observability/grafana/provisioning:/etc/grafana/provisioning:ro
      - ./configs/observability/grafana/dashboards:/etc/grafana/dashboards:ro
      - grafana_data:/var/lib/grafana
    ports:
      - "3000:3000"
    depends_on:
      prometheus:
        condition: service_started
    healthcheck:
      test: ["CMD-SHELL", "wget --spider -q http://localhost:3000/api/health || exit 1"]
      interval: 30s
      timeout: 5s
      retries: 5
    networks:
      - beacon-network
    restart: unless-stopped

  celery-exporter:
    image: danihodovic/celery-exporter:latest
    container_name: beacon-celery-exporter
    command:
      - --broker-url=redis://redis:6379/0
      - --port=9808
    environment:
      CELERY_BROKER_URL: redis://redis:6379/0
    ports:
      - "9808:9808"
    depends_on:
      redis:
        condition: service_healthy
    networks:
      - beacon-network
    restart: unless-stopped
```

Volumes (into the existing top-level `volumes:` block):

```yaml
volumes:
  prometheus_data:
  grafana_data:
```

Pin `danihodovic/celery-exporter` to a specific tag once you have validated one
in your environment (`:latest` is used here only to avoid inventing a tag that
may not exist).

## Verification

```bash
cd /home/komedi/Denemeler/beacon
PYTHONPATH=. python -m pytest backend/tests/test_observability.py -v -o addopts=""
python -m json.tool configs/observability/grafana/dashboards/beacon-overview.json > /dev/null
```

The tests pass with **and** without `prometheus_client` installed (the fallback
path is exercised in a subprocess), and without a live Redis broker or Celery
workers.
