#!/bin/bash

# BEACON - Banking Early Alert Comprehensive Observation Network
# Powered by BNE (Banking Network Engine)
# Advanced startup script with rebuild options and auto-setup
# Copyright © 2025 BNE. All rights reserved.

set -euo pipefail

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}  BEACON - Banking Network Engine${NC}"
echo -e "${BLUE}  Early Alert & Risk Monitoring${NC}"
echo -e "${BLUE}============================================${NC}\n"

# CRITICAL: Change to project root directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo -e "${GREEN}✓ Working directory: $PROJECT_ROOT${NC}"

# Check if Docker is installed
if ! command -v docker &>/dev/null; then
    echo -e "${RED}Error: Docker is not installed${NC}"
    echo "Please install Docker from: https://docs.docker.com/get-docker/"
    exit 1
fi

# Detect docker compose command (v2 plugin or legacy)
DC_CMD=""
if docker compose version &>/dev/null 2>&1; then
    DC_CMD="docker compose"
elif command -v docker-compose &>/dev/null; then
    DC_CMD="docker-compose"
else
    echo -e "${RED}Error: Docker Compose is not installed${NC}"
    echo "Please install Docker Compose plugin or legacy docker-compose."
    exit 1
fi
echo -e "${GREEN}✓ Using compose command: ${DC_CMD}${NC}"

# Detect platform and configure compose files
PLATFORM=$(uname -s)
ARCH=$(uname -m)
COMPOSE_FILES="-f docker-compose.yml"
GPU_AVAILABLE=false

echo -e "${CYAN}Platform Detection:${NC}"
echo -e "  OS: ${PLATFORM}"
echo -e "  Architecture: ${ARCH}"

# Detect Apple Silicon (macOS ARM)
if [[ "$PLATFORM" == "Darwin" ]]; then
    if [[ "$ARCH" == "arm64" ]]; then
        echo -e "${GREEN}✓ Detected: macOS Apple Silicon (M1/M2/M3)${NC}"
        echo -e "${CYAN}  Using CPU-only configuration (no CUDA support on macOS)${NC}"
        COMPOSE_FILES="-f docker-compose.yml -f docker-compose.cpu.yml"
        GPU_AVAILABLE=false
    else
        echo -e "${GREEN}✓ Detected: macOS Intel${NC}"
        echo -e "${CYAN}  Using CPU-only configuration${NC}"
        COMPOSE_FILES="-f docker-compose.yml -f docker-compose.cpu.yml"
        GPU_AVAILABLE=false
    fi
# Check for NVIDIA GPU on Linux
elif [[ "$PLATFORM" == "Linux" ]]; then
    if command -v nvidia-smi &>/dev/null; then
        echo -e "${GREEN}✓ NVIDIA GPU detected${NC}"
        if docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q nvidia; then
            echo -e "${GREEN}✓ NVIDIA Docker runtime configured${NC}"
            echo -e "${CYAN}  Using GPU-accelerated configuration${NC}"
            COMPOSE_FILES="-f docker-compose.yml -f docker-compose.gpu.yml"
            GPU_AVAILABLE=true
        else
            echo -e "${YELLOW}⚠ NVIDIA Docker runtime not configured${NC}"
            echo -e "${YELLOW}  Falling back to CPU-only configuration${NC}"
            echo -e "${YELLOW}  To enable GPU: Install nvidia-container-toolkit${NC}"
            COMPOSE_FILES="-f docker-compose.yml -f docker-compose.cpu.yml"
            GPU_AVAILABLE=false
        fi
    else
        echo -e "${YELLOW}⚠ No NVIDIA GPU detected${NC}"
        echo -e "${CYAN}  Using CPU-only configuration${NC}"
        COMPOSE_FILES="-f docker-compose.yml -f docker-compose.cpu.yml"
        GPU_AVAILABLE=false
    fi
else
    echo -e "${YELLOW}⚠ Unknown platform: ${PLATFORM}${NC}"
    echo -e "${CYAN}  Using CPU-only configuration${NC}"
    COMPOSE_FILES="-f docker-compose.yml -f docker-compose.cpu.yml"
    GPU_AVAILABLE=false
fi
echo ""

# Create necessary directories in PROJECT ROOT
echo -e "${BLUE}Creating data directories...${NC}"
mkdir -p data logs models results configs
echo -e "${GREEN}✓ Created: data/ logs/ models/ results/ configs/${NC}"

# Check for .env file in PROJECT ROOT
if [ ! -f .env ]; then
    echo -e "${YELLOW}⚠ No .env file found. Creating default .env file...${NC}"
    cat > .env <<'EOF'
# BEACON - Banking Early Alert Comprehensive Observation Network
# Powered by BNE (Banking Network Engine)
# Copyright © 2025 BNE. All rights reserved.

# API Keys (Optional - can be configured via GUI)
FRED_API_KEY=
ALPHA_VANTAGE_API_KEY=
SEC_API_KEY=

# Database Configuration
POSTGRES_DB=beacon_db
POSTGRES_USER=beacon_user
POSTGRES_PASSWORD=beacon_password
EOF
    chmod 600 .env || true
    echo -e "${GREEN}✓ Created .env file${NC}"
    echo -e "${YELLOW}  You can add API keys now or configure them later via the GUI${NC}"
else
    echo -e "${GREEN}✓ Found existing .env file${NC}"
fi
echo ""

# Check if services are already running
SERVICES_RUNNING=false
if $DC_CMD $COMPOSE_FILES ps | grep -q "Up"; then
    SERVICES_RUNNING=true
    echo -e "${CYAN}Services are currently running${NC}"
    echo ""
fi

# Ask user about rebuild
REBUILD_OPTION=""
NO_CACHE=""

if [ "$SERVICES_RUNNING" = true ]; then
    echo -e "${YELLOW}Do you want to rebuild the containers?${NC}"
    echo "  1) No, just restart existing containers (fast)"
    echo "  2) Yes, rebuild with cache (faster, may miss some updates)"
    echo "  3) Yes, rebuild without cache (slower, ensures fresh build)"
    echo "  4) Stop services and exit"
    echo ""
    read -p "Enter choice [1-4] (default: 1): " -r
    REBUILD_CHOICE="${REPLY:-1}"
else
    echo -e "${YELLOW}Initial setup detected. Build options:${NC}"
    echo "  1) Build with cache (faster, recommended for first run)"
    echo "  2) Build without cache (slower, ensures clean build)"
    echo ""
    read -p "Enter choice [1-2] (default: 1): " -r
    REBUILD_CHOICE="${REPLY:-1}"
fi

echo ""

case "$REBUILD_CHOICE" in
    1)
        if [ "$SERVICES_RUNNING" = true ]; then
            echo -e "${BLUE}Restarting existing containers...${NC}"
            $DC_CMD $COMPOSE_FILES restart
            REBUILD_OPTION="restart"
        else
            echo -e "${BLUE}Building with cache...${NC}"
            REBUILD_OPTION="build"
        fi
        ;;
    2)
        if [ "$SERVICES_RUNNING" = true ]; then
            echo -e "${BLUE}Stopping services...${NC}"
            $DC_CMD $COMPOSE_FILES down
            echo -e "${BLUE}Rebuilding with cache...${NC}"
            REBUILD_OPTION="build"
        else
            echo -e "${BLUE}Rebuilding without cache (clean build)...${NC}"
            REBUILD_OPTION="build"
            NO_CACHE="--no-cache"
        fi
        ;;
    3)
        if [ "$SERVICES_RUNNING" = true ]; then
            echo -e "${BLUE}Stopping services...${NC}"
            $DC_CMD $COMPOSE_FILES down
            echo -e "${BLUE}Rebuilding without cache (clean build)...${NC}"
            REBUILD_OPTION="build"
            NO_CACHE="--no-cache"
        else
            echo -e "${RED}Invalid choice${NC}"
            exit 1
        fi
        ;;
    4)
        if [ "$SERVICES_RUNNING" = true ]; then
            echo -e "${BLUE}Stopping services...${NC}"
            $DC_CMD $COMPOSE_FILES down
            echo -e "${GREEN}Services stopped${NC}"
            exit 0
        else
            echo -e "${RED}Invalid choice${NC}"
            exit 1
        fi
        ;;
    *)
        echo -e "${RED}Invalid choice. Exiting.${NC}"
        exit 1
        ;;
esac

echo ""

# Build if needed
if [ "$REBUILD_OPTION" = "build" ]; then
    echo -e "${BLUE}Building Docker images...${NC}"
    echo -e "${YELLOW}This may take several minutes${NC}\n"
    $DC_CMD $COMPOSE_FILES build $NO_CACHE
    echo ""
fi

# Start services
if [ "$REBUILD_OPTION" != "restart" ]; then
    echo -e "${BLUE}Starting services...${NC}\n"
    $DC_CMD $COMPOSE_FILES up -d
else
    echo -e "${GREEN}✓ Services restarted${NC}\n"
fi

# Function: wait_for_cmd
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
            echo -e "${YELLOW}⚠ Timeout waiting for ${description}${NC}"
            return 1
        fi
        sleep 2
    done
}

# Wait for services
echo -e "${BLUE}Waiting for services to be ready...${NC}"

wait_for_cmd "PostgreSQL" 60 docker exec beacon-postgres pg_isready -U beacon_user -d beacon_db || echo -e "${YELLOW}⚠ Postgres may not be ready (check logs)${NC}"
wait_for_cmd "Redis" 30 docker exec beacon-redis redis-cli ping || echo -e "${YELLOW}⚠ Redis may not be ready (check logs)${NC}"
wait_for_cmd "Backend API" 90 curl -fsS --max-time 5 http://localhost:3456/health || echo -e "${YELLOW}⚠ Backend API not responding (check logs)${NC}"
wait_for_cmd "Frontend" 90 curl -fsS --max-time 5 http://localhost:6789/ || echo -e "${YELLOW}⚠ Frontend not responding (check logs)${NC}"

echo ""

# Check and populate catalogue if needed
echo -e "${BLUE}Checking data catalogue...${NC}"
CATALOGUE_CHECK=$(curl -fsS http://localhost:3456/api/v1/catalogue/stats 2>/dev/null || echo '{"total":0}')
CATALOGUE_COUNT=$(echo "$CATALOGUE_CHECK" | grep -o '"total":[0-9]*' | grep -o '[0-9]*' || echo "0")

if [ "$CATALOGUE_COUNT" -eq 0 ]; then
    echo -e "${YELLOW}⚠ Data catalogue is empty (0 items)${NC}"
    echo -e "${CYAN}The catalogue will be auto-populated on first backend startup${NC}"
    echo -e "${CYAN}This includes 48 data sources: ECB, FRED, SEC, BIS, IMF, World Bank${NC}"
    echo ""
    echo -e "${BLUE}Waiting for catalogue auto-population...${NC}"
    sleep 10
    CATALOGUE_CHECK=$(curl -fsS http://localhost:3456/api/v1/catalogue/stats 2>/dev/null || echo '{"total":0}')
    CATALOGUE_COUNT=$(echo "$CATALOGUE_CHECK" | grep -o '"total":[0-9]*' | grep -o '[0-9]*' || echo "0")
    if [ "$CATALOGUE_COUNT" -gt 0 ]; then
        echo -e "${GREEN}✓ Catalogue populated: $CATALOGUE_COUNT items available${NC}"
    else
        echo -e "${YELLOW}⚠ Catalogue not yet populated. Check backend logs:${NC}"
        echo -e "${YELLOW}  ${DC_CMD} logs backend | grep -i catalogue${NC}"
    fi
else
    echo -e "${GREEN}✓ Catalogue ready: $CATALOGUE_COUNT items available${NC}"
fi

echo ""
echo -e "${GREEN}============================================${NC}"
echo -e "${GREEN}  BEACON Services Started!${NC}"
echo -e "${GREEN}============================================${NC}\n"

echo -e "${BLUE}Access the application:${NC}"
echo -e "  • Frontend GUI: ${GREEN}http://localhost:6789${NC}"
echo -e "  • Backend API:  ${GREEN}http://localhost:3456${NC}"
echo -e "  • API Docs:     ${GREEN}http://localhost:3456/docs${NC}\n"

echo -e "${BLUE}Quick Start Guide:${NC}"
echo -e "  1. Open ${GREEN}http://localhost:6789${NC} in your browser"
echo -e "  2. Navigate to ${CYAN}Data Catalogue${NC} to browse 48 data sources"
echo -e "  3. Click ${CYAN}Add to Monitoring${NC} on items you want to track"
echo -e "  4. Go to ${CYAN}Jobs${NC} and create a ${CYAN}Data Collection${NC} job"
echo -e "  5. View results in ${CYAN}Results & Reports${NC}\n"

echo -e "${BLUE}Useful commands (run from project root):${NC}"
echo -e "  • View all logs:         ${YELLOW}${DC_CMD} ${COMPOSE_FILES} logs -f${NC}"
echo -e "  • View backend logs:     ${YELLOW}${DC_CMD} ${COMPOSE_FILES} logs -f backend${NC}"
echo -e "  • View frontend logs:    ${YELLOW}${DC_CMD} ${COMPOSE_FILES} logs -f frontend${NC}"
echo -e "  • View celery logs:      ${YELLOW}${DC_CMD} ${COMPOSE_FILES} logs -f celery-worker${NC}"
echo -e "  • Stop services:         ${YELLOW}${DC_CMD} ${COMPOSE_FILES} down${NC}"
echo -e "  • Restart all:           ${YELLOW}${DC_CMD} ${COMPOSE_FILES} restart${NC}"
echo -e "  • Restart backend:       ${YELLOW}${DC_CMD} ${COMPOSE_FILES} restart backend${NC}"
echo -e "  • Restart frontend:      ${YELLOW}${DC_CMD} ${COMPOSE_FILES} restart frontend${NC}\n"

if [ "$GPU_AVAILABLE" = false ]; then
    echo -e "${YELLOW}Note: Running in CPU-only mode. Training may be slower.${NC}"
    echo -e "${YELLOW}      Consider using smaller model parameters via Configuration page.${NC}\n"
fi

echo -e "${GREEN}✓ BEACON is ready! Visit ${CYAN}http://localhost:6789${GREEN} to get started.${NC}"
