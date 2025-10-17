#!/bin/bash

# FinAI - Financial Liquidity Risk Monitoring System
# Startup script for Docker environment
# Improved: robust docker-compose detection, retries for health checks, safer curl usage

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}  BEACON - Banking Network Engine${NC}"
echo -e "${BLUE}  Early Alert & Risk Monitoring${NC}"
echo -e "${BLUE}============================================${NC}\n"

# Check if Docker is installed
if ! command -v docker &>/dev/null; then
echo -e "${RED}Error: Docker is not installed${NC}"
echo "Please install Docker from: https://docs.docker.com/get-docker/"
exit 1
fi

# Detect docker-compose command (legacy or v2 subcommand)
DC_CMD=""
if command -v docker-compose &>/dev/null; then
DC_CMD="docker-compose"
elif docker compose version &>/dev/null 2>&1; then
DC_CMD="docker compose"
else
echo -e "${RED}Error: Docker Compose is not installed${NC}"
echo "Please install Docker Compose (either docker-compose or the 'docker compose' plugin)."
exit 1
fi
echo -e "${GREEN}Using compose command: ${DC_CMD}${NC}"

# Check if NVIDIA GPU runtime is available (for GPU support)
GPU_AVAILABLE=false
if command -v nvidia-smi &>/dev/null; then
echo -e "${GREEN}✓ NVIDIA GPU detected${NC}"
# Quick check for GPU accessibility via docker; prefer checking docker runtimes to avoid pulling large images
if docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q nvidia || docker run --rm --gpus all --entrypoint nvidia-smi nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi &>/dev/null; then
echo -e "${GREEN}✓ NVIDIA Docker runtime configured${NC}"
GPU_AVAILABLE=true
else
echo -e "${YELLOW}⚠ NVIDIA Docker runtime not configured${NC}"
echo -e "${YELLOW}  GPU acceleration will not be available${NC}"
echo -e "${YELLOW}  To enable GPU support, install and configure nvidia-docker2 / nvidia-container-toolkit${NC}"
GPU_AVAILABLE=false
fi
else
echo -e "${YELLOW}⚠ No NVIDIA GPU detected - using CPU only${NC}"
GPU_AVAILABLE=false
fi
echo ""

# Create necessary directories
echo -e "${BLUE}Creating data directories...${NC}"
mkdir -p data logs models results

# Check for .env file
if [ ! -f .env ]; then
echo -e "${YELLOW}⚠ No .env file found. Creating default .env file...${NC}"
cat > .env <<'EOF'
# API Keys (Optional - can be configured via GUI)
FRED_API_KEY=
ALPHA_VANTAGE_API_KEY=

# Database Configuration
POSTGRES_DB=finai_db
POSTGRES_USER=finai_user
POSTGRES_PASSWORD=finai_password
EOF
chmod 600 .env || true
echo -e "${GREEN}✓ Created .env file${NC}"
echo -e "${YELLOW}  You can add API keys now or configure them later via the GUI${NC}"
fi
echo ""
echo -e "${BLUE}Building Docker images...${NC}"
echo -e "${YELLOW}This may take several minutes on first run${NC}\n"

# Build images (use configured compose command)
$DC_CMD build
echo ""
echo -e "${BLUE}Starting services...${NC}\n"

# Start services
$DC_CMD up -d

# Function: wait_for_cmd <description> <max_seconds> <cmd...>
wait_for_cmd() {
description="$1"; shift
timeout="$1"; shift
cmd=( "$@" )

echo -e "${BLUE}Waiting up to ${timeout}s for ${description}...${NC}"
start_ts=$(date +%s)
while true; do
if "${cmd[@]}" &>/dev/null; then
echo -e "${GREEN}✓ ${description} ready${NC}"
return 0
fi
now=$(date +%s)
elapsed=$((now - start_ts))
if [ "$elapsed" -ge "$timeout" ]; then
echo -e "${RED}✗ Timeout waiting for ${description}${NC}"
return 1
fi
sleep 2
done
}

# Wait for containers to be up and healthy with retries
echo -e "${BLUE}Waiting for services to be ready...${NC}"

# Examples of checks. Adjust names/ports if your compose uses different service names.
wait_for_cmd "PostgreSQL container startup (pg_isready)" 60 docker exec finai-postgres pg_isready -U finai_user || echo -e "${YELLOW}Postgres may not be ready yet (check logs)${NC}"
wait_for_cmd "Redis container (redis-cli ping)" 30 docker exec finai-redis redis-cli ping || echo -e "${YELLOW}Redis may not be ready yet (check logs)${NC}"

# HTTP endpoint health checks — use curl --fail so non-2xx/3xx are treated as failures
wait_for_cmd "Backend API (http://localhost:3456/health)" 60 curl -fsS --max-time 5 http://localhost:3456/health || echo -e "${YELLOW}⚠ Backend API did not respond successfully to /health within timeout${NC}"
wait_for_cmd "Frontend (http://localhost:6789/)" 60 curl -fsS --max-time 5 http://localhost:6789/ || echo -e "${YELLOW}⚠ Frontend did not respond within timeout${NC}"

echo ""
echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}  Services are starting!${NC}"
echo -e "${GREEN}================================${NC}\n"

echo -e "${BLUE}Access the application:${NC}"
echo -e "  • Frontend GUI: ${GREEN}http://localhost:6789${NC}"
echo -e "  • Backend API:  ${GREEN}http://localhost:3456${NC}"
echo -e "  • API Docs:     ${GREEN}http://localhost:3456/docs${NC}\n"

echo -e "${BLUE}Useful commands:${NC}"
echo -e "  • View logs:           ${YELLOW}${DC_CMD} logs -f${NC}"
echo -e "  • View backend logs:   ${YELLOW}${DC_CMD} logs -f backend${NC}"
echo -e "  • View frontend logs:  ${YELLOW}${DC_CMD} logs -f frontend${NC}"
echo -e "  • Stop services:       ${YELLOW}${DC_CMD} down${NC}"
echo -e "  • Restart services:    ${YELLOW}${DC_CMD} restart${NC}\n"

if [ "$GPU_AVAILABLE" = false ]; then
echo -e "${YELLOW}Note: Running in CPU-only mode. Training may be slower.${NC}"
echo -e "${YELLOW}      Consider using smaller model parameters via the Configuration page.${NC}\n"
fi
echo -e "${BLUE}Getting Started:${NC}"
echo -e "  1. Open ${GREEN}http://localhost:6789${NC} in your browser"
echo -e "  2. Configure data sources (add API keys or upload CSV files)"
echo -e "  3. Add assets to monitor"
echo -e "  4. Start data collection job"
echo -e "  5. Train the model"
echo -e "  6. View predictions and analytics\n"
echo -e "${GREEN}System started (or is starting). Check logs for progress.${NC}"