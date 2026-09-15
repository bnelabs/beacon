# Deploying BEACON on this host

This documents the stack as it runs on `ubuntuserver` (Ubuntu 24.04.4, i9-12900KF,
62 GB RAM, RTX 3090 24 GB), and records the reasoning behind the choices so they
can be revisited rather than reverse-engineered.

---

## 1. Docker Compose, not microk8s — and why

The question was "microk8s or Docker, whichever is best for this server". The
answer here is **Docker Engine + Compose v2**, on evidence rather than preference.

| Consideration | This host's reality | Consequence |
|---|---|---|
| Node count | **One.** Single RTX 3090, single machine. | Kubernetes schedules across nodes. There is nothing to schedule across. |
| HA / self-healing | No second machine exists to fail over to. | A control plane adds availability machinery with nothing to make available. |
| Artefacts already written | `docker-compose.yml` (5 services), `.gpu.yml` / `.cpu.yml` overlays, 3 Dockerfiles — all already tuned (healthchecks, `depends_on: service_healthy`, BuildKit cache mounts). | microk8s would require rewriting all of it into manifests for zero functional gain. |
| Idle cost | 62 GB RAM, 24 threads. | microk8s control plane (API server, etcd, kubelet, CNI) is roughly 1.5–2 GB resident before a single workload. Pure overhead on a single-node box. |
| Prerequisite | `snapd` is installed but **inactive**. | microk8s installs via snap and would need snapd enabled and running permanently. |
| GPU passthrough | `nvidia-container-toolkit` 1.20.0, verified working (**RTX 3090 visible inside a container**). | `deploy.resources.reservations.devices` in the compose overlay is already correct and tested. |

**When to revisit:** if a second machine is added, if workloads need to be packed
across heterogeneous nodes, or if the frontend/backend need independent rollout
and rollback. At that point microk8s (or k3s, which is lighter) becomes the right
call and the compose files are the migration source, not a dead end.

---

## 2. What is installed

```bash
docker --version          # 29.8.0
docker compose version    # v5.5.1
nvidia-container-toolkit  # 1.20.0
```

Docker was installed from Docker's official apt repository (not the distro
package) and the NVIDIA runtime was registered with:

```bash
nvidia-ctk runtime configure --runtime=docker
systemctl restart docker
```

`komedi` was added to the `docker` group — **log out and back in** for that to
take effect in your own shell. Until then, prefix commands with `sudo`.

Verified GPU passthrough:

```bash
docker run --rm --gpus all nvidia/cuda:12.6.3-base-ubuntu24.04 nvidia-smi -L
# GPU 0: NVIDIA GeForce RTX 3090 (UUID: GPU-...)
```

---

## 3. Model weights: none ship, none are fetched

The Toto 2.0 foundation-encoder stack was **removed** in the 2026-09 hygiene
round (see the REMOVED register in `backend/tests/test_reachability.py`): it
was implemented and tested but never constructed by a production path, while
every image paid gigabytes for it. There is therefore **no weights folder to
mount and no `BEACON_MODEL_DIR` to set** in current deployments. Older
 revisions of this document described `/home/komedi/models/beacon/toto/`;
that path was one developer's machine and is not part of this platform.

If a foundation encoder returns, it returns together with the engine path
that embeds nodes with it -- and this section returns with it.


## 4. Reaching the stack from other machines

The host is `192.168.68.57` on `wlo1` (Wi-Fi). All published ports bind `0.0.0.0`,
so anything on `192.168.68.0/22` can reach them:

| Service | URL | Notes |
|---|---|---|
| **Frontend (use this)** | `http://192.168.68.57:9876` | nginx serves the SPA and proxies `/api/` to the backend |
| Backend API | `http://192.168.68.57:3456` | FastAPI; `/docs` for OpenAPI |

**The frontend now calls its own origin.** Previously the bundle was built with
`VITE_API_BASE_URL=http://localhost:3456`, which is resolved by *the browser* — so
from another machine it called that machine's own `localhost` and silently failed.
The build arg is now empty and the code defaults to a relative base, so nginx
proxies `/api/` and the UI works from anywhere that can reach the host. Only set
`VITE_API_BASE_URL` if the API genuinely lives on a different origin.

Verify from another device:

```bash
curl -sS http://192.168.68.57:9876/health      # healthy
curl -sS http://192.168.68.57:3456/api/v1/countries/ | head -c 200
```

If a device cannot connect, the host firewall is the first suspect:

```bash
sudo ufw status
```

---

## 5. Operating the stack

Six services, of which one is a one-shot:

| Service | Role | Lifetime |
|---|---|---|
| `postgres` | TimescaleDB (PostgreSQL 15 + extension) | long-running |
| `redis` | Celery broker, result backend, WebSocket relay | long-running |
| `migrate` | `alembic upgrade head`, exactly once | **exits 0** |
| `backend` | FastAPI on :3456 | long-running |
| `celery-worker` | the four job tasks | long-running |
| `celery-beat` | the clock: enqueues due per-source collections | long-running |
| `frontend` | nginx serving the SPA on :9876, proxying `/api/` | long-running |

`migrate`, `backend`, `celery-worker` and `celery-beat` are **one image**.
Only `backend` carries a `build:` block; the others declare the same `image:`
tag
(`${BEACON_BACKEND_IMAGE:-beacon-backend:latest}`) and no build of their own, so
the CUDA torch wheel is downloaded once rather than twice and the worker cannot
drift from the API it takes jobs from.

```bash
cd /path/to/beacon
cp .env.example .env      # then edit it

# Validate before building. Both are fast and need no daemon.
python scripts/validate_compose.py
sudo docker compose -f docker-compose.yml -f docker-compose.gpu.yml config --quiet

# Build once, then start. Do not pass --no-cache for a normal rebuild.
sudo docker compose -f docker-compose.yml -f docker-compose.gpu.yml build backend frontend
sudo docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --force-recreate

# The migration is the first thing to look at, because everything else waits on it.
sudo docker compose ps
sudo docker compose logs migrate
```

CPU-only hosts substitute `docker-compose.cpu.yml` for the GPU overlay.

### Boot order, and why it is enforced rather than hoped for

```
postgres healthy ──> migrate runs once ──> migrate exits 0 ──> backend + worker + beat start
                                                                      │
                                            backend healthy ──────────┴──> frontend starts
```

`backend`, `celery-worker` and `celery-beat` depend on `migrate` with
`condition: service_completed_successfully`, and `frontend` depends on `backend`
with `condition: service_healthy`. Both are deliberate:

* All three services set `BEACON_RUN_MIGRATIONS=0`, so the entrypoint's own
  `alembic upgrade head` is disabled everywhere. Two containers used to migrate
  concurrently on first boot; the retry loop in `entrypoint.sh` tolerated the
  race, but when the migration itself was broken both restart-looped — 64
  restarts observed on a real deployment — while `docker compose ps` reported
  `Up`, because both containers *were* up and neither had ever served a request.
* `frontend` previously used the short-form `depends_on: [backend]`, which means
  "started", not "working". That is what produced a healthy nginx in front of an
  API that was reset on every connection.

A migration failure now stops the stack with `migrate` exited non-zero and its
error in `docker compose logs migrate`, instead of presenting as a backend that
will not answer.

### Scheduled collections, and what "connected" means per feed

Collection used to be entirely manual: a button that stamped a time. The
`celery-beat` service now ticks every five minutes and asks
`backend.services.scheduling` which sources are due; each source's cadence is
its own `sync_interval_minutes` (null means manual-only -- the absence of a
schedule is a decision, not a default). Three behaviours are deliberate:

- **Backoff on failure.** The interval doubles per consecutive failure, capped
  at eight intervals, and one success restores the healthy cadence. A feed
  that is down is retried forever, gently.
- **Stable per-source jitter**, a hash of the source id, so sources sharing a
  cadence do not land on the same tick. Random jitter would make the next due
  date unreadable in the health payload.
- **One collection path.** The scheduler enqueues the same `data_collection`
  job a human does, and `POST /api/v1/data-sources/{id}/sync` ("Sync Now")
  enqueues it too -- 202 and a job, not a timestamp. An open collection for a
  source blocks a second enqueue, from beat or from a human.

The same tick evaluates **alert rules** on each rule's own frequency
(`evaluate_alert_rules`): a breached rule raises one notification per cooldown
window -- a monitoring platform whose alerts never fire is quieter, and
therefore worse, than one with no alert feature at all. Rules whose metric is
not measurable over their window are skipped visibly rather than guessed.

`GET /api/v1/data-sources/health` is the operator's view: cadence, backoff
factor, last start/duration/rows, next due date, and `overdue`. The Data
Sources page renders it per card (schedule selector, last run, next refresh,
failure streak with the reason), and the Data Quality page renders a
"Refresh Cadence" panel for scheduled feeds. `POST
/api/v1/data-sources/{id}/probe` runs the plugin's own `test_connection`
against the live provider with environment-held keys injected exactly as the
collector injects them, so a keyed feed probes the way it runs.

### "Up" is not "operational"

`docker compose ps` reports a container that is restarting as `Up` between
restarts. When the UI loads and every `/api/` call fails, check these in order:

```bash
sudo docker compose ps                       # migrate must show Exited (0)
sudo docker compose logs --tail=100 migrate  # the schema error, if any
sudo docker compose inspect backend --format '{{.RestartCount}} {{.State.Status}}'
curl -sS http://127.0.0.1:3456/health        # {"status":"healthy","database":"connected"}
```

A non-zero `RestartCount` on `backend` means it is crash-looping, whatever `ps`
says.

### GPU: two variables that are not interchangeable

```bash
sudo docker compose -f docker-compose.yml -f docker-compose.gpu.yml \
  exec backend python -c "import torch; print(torch.__version__, torch.version.cuda, torch.cuda.is_available(), torch.cuda.device_count())"
```

| Variable | Read by | Valid values |
|---|---|---|
| `NVIDIA_VISIBLE_DEVICES` | the NVIDIA **container runtime**, to decide which GPUs enter the container | `all`, `none`, or indices |
| `CUDA_VISIBLE_DEVICES` | **CUDA/PyTorch inside** the container | indices or UUIDs — **not `all`** |

Setting `CUDA_VISIBLE_DEVICES=all` does not mean "every GPU". torch parses it as a
device list, matches nothing, and reports `torch.cuda.is_available() == False` in
a container that can see the GPU perfectly well. The image used to bake `all` in
as its default and the GPU overlay passed `${CUDA_VISIBLE_DEVICES:-all}` to it,
which produced exactly that: an RTX 3090 visible to `nvidia-smi` inside the
container and invisible to torch. Both now default to `0`, and the container-level
`NVIDIA_VISIBLE_DEVICES` still defaults to `all`, so the reservation is unchanged.
Pin a subset from `.env` (`CUDA_VISIBLE_DEVICES=0,1`).

### Build context and .dockerignore

The backend build context is the **repository root**, not `./backend`, because
`alembic.ini` lives at the root and the entrypoint runs `alembic upgrade head`.
Alembic reads its config from `alembic.ini` relative to the working directory and
its `script_location = backend/alembic` is relative to that same directory, so
with `WORKDIR /app` both resolve — and neither did when the context was
`./backend`, because `alembic.ini` was never in the image.

That also broke the build outright: the Dockerfiles ended with
`COPY backend/entrypoint.sh`, which under a `./backend` context resolves to
`backend/backend/entrypoint.sh` and does not exist. `scripts/validate_compose.py`
now checks every `COPY` source against the build context on every CI run, since
the workflow that would have caught it (`docker-backend.yml`) is manual-only.

`.dockerignore` at the root keeps `.git`, `frontend/`, model weights, local
`data/`, `logs/` and caches out of that context. It is a deny list rather than
`*` plus negations on purpose: an allowlist that starts with `*` has to
re-include everything the build needs, and getting that wrong fails as a missing
file minutes into an image build.

### Reclaiming disk

Build cache grows without bound and is not shared between differently-tagged
builds. On a single host it reached 17.5 GB before the duplicate worker build was
removed.

```bash
sudo docker system df                  # what is being held, and how much is reclaimable
sudo docker builder prune              # dangling build cache only
sudo docker image prune -a             # images no container references
```

`docker compose down` preserves the database volume; `down -v` deletes it. The
second is a destructive reset and is never part of a normal rebuild.

### Backing up before a migration

```bash
sudo docker compose exec -T postgres pg_dump -U "${POSTGRES_USER:-beacon_user}" \
  "${POSTGRES_DB:-beacon_db}" > "beacon-$(date +%Y%m%d-%H%M%S).sql"
```

Migrations are guarded and idempotent, and `backend/tests/test_migrations_live.py`
runs all three histories against a real PostgreSQL in CI. That is a reason to
expect an upgrade to work, not a reason to skip the backup: `alembic stamp head`
is not a shortcut for a failed migration, and a downgrade of
`baseline_core_001` raises by design rather than guessing which tables it created.

### A note on the two Dockerfiles

Both install torch from an **explicit index**, because the default is a trap:

* PyPI's plain `torch==2.14.0` Linux wheel **is** the CUDA 13.0 build — its
  dependencies are `nvidia-*-cu13`. Installing `requirements.txt` alone therefore
  pulled ~3 GB of CUDA into the *CPU* image.
* `Dockerfile.cpu` uses `TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu`
  and asserts `torch.version.cuda is None`.
* `Dockerfile` uses `.../whl/cu130` and asserts a CUDA torch is present.
* The GPU image does not base on `nvidia/cuda:*`. torch's wheels bundle the CUDA
  runtime, so the base contributed a second, differently-versioned copy (the old
  base was CUDA 12.6 against a 13.0 torch). The *driver* is injected by the
  container runtime, so nothing is lost.

---

## 6. Secrets

`.env` was **tracked in git on `main`**. It has been untracked
(`git rm --cached .env`); the working file stays on disk so compose still reads
it, and that is where the values belong.

**What was actually exposed** — verified by walking every revision, rather than
inferred from a masked listing:

| Variable | Status in history |
|---|---|
| `FRED_API_KEY` | **A real key was committed in `19b004e`.** Rotate it. |
| `ALPHA_VANTAGE_API_KEY` | Empty in every revision. Never exposed. |
| `SEC_API_KEY` | Empty in every revision. Never exposed. |
| `POSTGRES_PASSWORD` / `_USER` / `_DB` | Present, but only the compose defaults (`beacon_user` / `beacon_password` / `beacon_db`) that are already public in `docker-compose.yml`. Not a secret, though a LAN deployment should still change it. |

**Untracking does not remove anything from history.** The `19b004e` blob is still
readable by anyone with the repository, so the FRED key must be rotated. The
other three need no action.

`.env.example` is the tracked template. Keep real values in `.env` (gitignored)
or in a secret manager.

---

## 7. Verifying a deployment

```bash
cd /home/komedi/Denemeler/beacon

# Unit + integration suite (offline; no network needed — the foundation-encoder
# tests run against the deterministic HashedFallbackEncoder, there is no
# real-weight mode any more)
PYTHONPATH=. /home/komedi/Denemeler/beacon-venv/bin/python -m pytest backend/tests -o addopts='' -q

/home/komedi/Denemeler/beacon-venv/bin/python -m ruff check backend --select E9,F63,F7,F82
```

Then at the container level:

```bash
docker compose ps                      # frontend must be (healthy), not merely Up

# No weights ship and none are fetched (section 3). The encoder that does exist
# is the deterministic fallback: it must construct inside the image with no
# network and no model tree.
docker compose exec backend python -c "
from backend.modules.engine.foundation_encoders import HashedFallbackEncoder
e = HashedFallbackEncoder(embed_dim=64)
print('encoder OK:', e.embed_dim, e.provenance.is_pretrained)"
```

### Rebuilding: one image, three services

`migrate`, `backend` and `celery-worker` run the same image, so
`docker compose build backend` updates all three. There is no second worker image
to remember to rebuild — which was the previous arrangement, and the reason a
worker could be left running the code from a prior release while the API ran the
new one. Because the worker is where job progress is produced, that drift showed
up as live updates looking half-broken in a way that was easy to misread as a
WebSocket problem.

```bash
docker compose build backend frontend
docker compose up -d --force-recreate
```

`--force-recreate` matters after a rebuild: without it compose leaves a running
container on the image it started with.

### The frontend healthcheck

`beacon-frontend` probes `http://127.0.0.1/health`, **not** `localhost`. nginx
listens on IPv4 only, while the image's `/etc/hosts` maps `localhost` to `::1`
first, so a `localhost` probe is refused and the container reports unhealthy for
its whole life while serving every real request correctly. If the frontend shows
`(unhealthy)`, check that probe first.
