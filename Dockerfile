# --- Stage 1: Builder ---
FROM python:3.11 AS builder

# Install system dependencies including build-essential (which contains gcc/g++)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# --- Stage 2: Runtime ---
FROM python:3.11-slim

WORKDIR /app

# Set environment variables for better container logging
ENV PYTHONUNBUFFERED=1

# Copy runtime dependencies from the builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Copy application code and configuration files
COPY src ./src
COPY configs ./configs
COPY .env .env
COPY README.md .

# Determine the correct entry point based on environment details
CMD ["python", "src/liquidity_monitor/main.py"]
