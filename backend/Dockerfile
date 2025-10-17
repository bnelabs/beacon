# Use NVIDIA CUDA base image for GPU support (updated to non-deprecated version)
FROM nvidia/cuda:12.6.0-cudnn-runtime-ubuntu22.04

# Set working directory
WORKDIR /app

# Install Python 3.10 and system dependencies
RUN apt-get update && apt-get install -y \
    python3.10 \
    python3.10-dev \
    python3-pip \
    build-essential \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Create symlinks for python commands
RUN ln -sf /usr/bin/python3.10 /usr/bin/python && \
    ln -sf /usr/bin/python3.10 /usr/bin/python3

# Upgrade pip
RUN python -m pip install --upgrade pip

# Copy requirements file first (for better Docker layer caching)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy backend application code
COPY . .

# Create necessary directories
RUN mkdir -p /app/data /app/results /app/logs /app/saved_models

# Create non-root user for security
RUN groupadd -r beacon && useradd -r -g beacon -u 1000 beacon

# Set ownership
RUN chown -R beacon:beacon /app

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV CUDA_VISIBLE_DEVICES=0

# Switch to non-root user
USER beacon

# Expose port
EXPOSE 3456

# Default command (can be overridden in docker-compose)
CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "3456"]
