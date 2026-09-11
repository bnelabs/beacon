# GPU-enabled Dockerfile for Linux with NVIDIA GPU
# For CPU-only systems, use Dockerfile.cpu instead
# Ubuntu 24.04 is used so the image ships Python 3.12 natively: the pinned
# scientific stack (scipy 1.18, scikit-learn 1.9, matplotlib 3.11) requires
# Python >= 3.12. CUDA stays on 12.6 to match the PyTorch build.
FROM nvidia/cuda:12.6.3-cudnn-runtime-ubuntu24.04

# uv installs the pinned stack far faster than pip; see Dockerfile.cpu.
COPY --from=ghcr.io/astral-sh/uv:0.12.13 /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Install Python 3.12 and system dependencies
RUN apt-get update && apt-get install -y \
    python3.12 \
    python3.12-dev \
    python3-pip \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create symlinks for python commands
RUN ln -sf /usr/bin/python3.12 /usr/bin/python && \
    ln -sf /usr/bin/python3.12 /usr/bin/python3

# Copy requirements file first (for better Docker layer caching)
COPY requirements.txt .
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy
RUN uv pip install --system --no-cache -r requirements.txt

# Copy backend application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/data /app/results /app/logs /app/saved_models

# Create non-root user for security
RUN groupadd -r beacon && useradd -r -g beacon -u 1000 -m -d /home/beacon beacon

# Create cache directories for yfinance
RUN mkdir -p /home/beacon/.cache/py-yfinance && \
    chown -R beacon:beacon /home/beacon

# Set ownership
RUN chown -R beacon:beacon /app

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV CUDA_VISIBLE_DEVICES=0
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONIOENCODING=utf-8

# Switch to non-root user
USER beacon

# Expose port
EXPOSE 3456

# Default command (can be overridden in docker-compose)
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "3456"]
