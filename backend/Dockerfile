# syntax=docker/dockerfile:1.7
# GPU-enabled image for Linux with an NVIDIA GPU (verified on an RTX 3090).
#
# Why this is not based on an nvidia/cuda image
# --------------------------------------------
# torch's own wheels bundle the CUDA runtime: the ``nvidia-*-cu13`` distributions
# are declared dependencies, so ``uv pip install torch`` already brings cuBLAS,
# cuDNN, NCCL and the rest. An ``nvidia/cuda:*`` base therefore contributes a
# second, differently-versioned copy of the same libraries -- the previous base
# was CUDA 12.6 while the torch wheel is built for 13.0 -- and costs several GB
# that are never loaded. The NVIDIA *driver* is injected by the container runtime
# (``--gpus all``, or the compose ``deploy.resources.reservations.devices``
# block), not by the base image, so basing on plain python loses nothing.
#
# Which torch lands here is a decision, not an accident
# ----------------------------------------------------
# PyPI's plain ``torch==2.14.0`` Linux wheel happens to be the CUDA 13.0 build
# today, but nothing pins that. TORCH_INDEX_URL states it explicitly and the build
# asserts a CUDA-enabled torch is actually present, so a silent switch back to a
# CPU wheel fails the build instead of failing at the first forward pass.
#
# Python 3.12 is required by the pinned scientific stack (scipy 1.18,
# scikit-learn 1.9 and matplotlib 3.11 all require >= 3.11/3.12).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /uvx /bin/

WORKDIR /app

RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

#: Wheel index for torch. ``cu130`` here; the CPU image uses ``cpu``.
ARG TORCH_INDEX_URL=https://download.pytorch.org/whl/cu130

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# torch first, from its explicit index; requirements.txt then finds it satisfied
# (PEP 440 ignores the local label for a specifier without one) rather than
# replacing it with a PyPI wheel.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --system --index-url "$TORCH_INDEX_URL" torch==2.14.0 \
 && uv pip install --system -r requirements.txt \
 && python -c "import torch; print('torch', torch.__version__, 'cuda', torch.version.cuda); assert torch.version.cuda is not None, 'GPU image must ship a CUDA torch'"

# Same layout as the CPU image, so ``backend.api.main`` resolves identically and
# docker-compose can use one command for both.
COPY . backend/

RUN mkdir -p /app/data /app/results /app/logs /app/saved_models

RUN groupadd -r beacon && useradd -r -g beacon -u 1000 -m -d /home/beacon beacon

RUN mkdir -p /home/beacon/.cache/py-yfinance && \
    chown -R beacon:beacon /home/beacon

RUN chown -R beacon:beacon /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
# Which GPU the process sees. A baked-in ENV silently defeated the
# `count: all` device reservation in docker-compose.gpu.yml, so this is a
# build ARG with the same default: override at build time
# (docker build --build-arg CUDA_VISIBLE_DEVICES=all, or via .env through
# docker-compose.gpu.yml) or at runtime (compose `environment:`).
ARG CUDA_VISIBLE_DEVICES=0
ENV CUDA_VISIBLE_DEVICES=${CUDA_VISIBLE_DEVICES}
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONIOENCODING=utf-8

USER beacon

EXPOSE 3456

COPY backend/entrypoint.sh /app/backend/entrypoint.sh
RUN chmod +x /app/backend/entrypoint.sh

ENTRYPOINT ["/app/backend/entrypoint.sh"]
CMD ["uvicorn", "backend.api.main:app", "--host", "0.0.0.0", "--port", "3456"]
