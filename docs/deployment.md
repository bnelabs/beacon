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

```bash
cd /home/komedi/Denemeler/beacon

# GPU build + start
sudo docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build

# CPU-only (no GPU needed)
sudo docker compose -f docker-compose.yml -f docker-compose.cpu.yml up -d --build

sudo docker compose ps
sudo docker compose logs -f backend
sudo docker compose down          # add -v to drop the database volume
```

Confirm the containers can actually see the weights and the GPU:

```bash
sudo docker compose -f docker-compose.yml -f docker-compose.gpu.yml \
  exec backend python -c "import torch; print(torch.__version__, torch.cuda.is_available())"

sudo docker compose exec backend python -c \
  "from backend.modules.engine.foundation_encoders import local_model_path; print(local_model_path('Datadog/Toto-2.0-313m'))"
# /models/Toto-2.0-313m
```

### A note on the two backend images

Both now install torch from an **explicit index**, because the default is a trap:

* PyPI's plain `torch==2.14.0` Linux wheel **is** the CUDA 13.0 build — its
  dependencies are `nvidia-*-cu13`. Installing `requirements.txt` alone therefore
  pulled ~3 GB of CUDA into the *CPU* image.
* `Dockerfile.cpu` now uses `TORCH_INDEX_URL=https://download.pytorch.org/whl/cpu`
  and asserts `torch.version.cuda is None`.
* `Dockerfile` uses `.../whl/cu130` and asserts a CUDA torch is present.
* The GPU image no longer bases on `nvidia/cuda:*`. torch's wheels bundle the CUDA
  runtime, so the base contributed a second, differently-versioned copy (the old
  base was CUDA 12.6 against a 13.0 torch). The *driver* is injected by the
  container runtime, so nothing is lost. Both images now share the same code
  layout (`COPY . backend/`), which is what makes the compose command
  `backend.api.main:app` valid for both.

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

# Unit + integration suite (offline; no network needed)
PYTHONPATH=. /home/komedi/Denemeler/beacon-venv/bin/python -m pytest backend/tests -o addopts='' -q

# Real-weight encoder tests run only when the model tree is set
BEACON_MODEL_DIR=/home/komedi/models/beacon/toto \
  PYTHONPATH=. /home/komedi/Denemeler/beacon-venv/bin/python -m pytest \
  backend/tests/test_foundation_encoders.py -o addopts='' -q

/home/komedi/Denemeler/beacon-venv/bin/python -m ruff check backend --select E9,F63,F7,F82
```

Then at the container level:

```bash
docker compose ps                      # frontend must be (healthy), not merely Up

# The Toto encoder must load inside the image. Its Python package is declared in
# backend/requirements.txt; if that pin is ever dropped, construction raises
# ModuleNotFoundError rather than failing at first prediction.
docker compose exec backend python -c "
from backend.modules.engine.foundation_encoders import TotoEncoder
e = TotoEncoder(model_id='Datadog/Toto-2.0-313m', device='cpu')
print('encoder OK:', e.n_parameters(), e.embed_dim)"
```

### Rebuilding: `backend` and `celery-worker` are separate images

They are built from the same context (`./backend`) but are **distinct images**,
so `docker compose build backend` does not update the worker. Rebuilding only the
API leaves the worker on the previous code, and because the worker is where job
progress is produced, live updates then appear half-broken in a way that is easy
to misread. Rebuild everything, or name both:

```bash
docker compose build backend celery-worker frontend
docker compose up -d
```

### The frontend healthcheck

`beacon-frontend` probes `http://127.0.0.1/health`, **not** `localhost`. nginx
listens on IPv4 only, while the image's `/etc/hosts` maps `localhost` to `::1`
first, so a `localhost` probe is refused and the container reports unhealthy for
its whole life while serving every real request correctly. If the frontend shows
`(unhealthy)`, check that probe first.
