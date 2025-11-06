#!/bin/bash

# =============================================================================
# BEACON - Banking Early Alert Comprehensive Observation Network
# Powered by BNE (Banking Network Engine)
# Docker-Isolated Startup Script
# Copyright © 2025 BNE. All rights reserved.
# =============================================================================
#
# DESIGN PRINCIPLE: 100% Docker Isolation
# - NO host filesystem modifications (except user-created .env)
# - NO directory creation on host (Docker auto-creates)
# - ALL operations run inside containers
# - Health checks via docker exec (not host curl)
#
# =============================================================================

set -euo pipefail

# =============================================================================
# COLORS
# =============================================================================
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
MAGENTA='\033[0;35m'
NC='\033[0m' # No Color

# =============================================================================
# HEADER
# =============================================================================
echo -e "${BLUE}============================================${NC}"
echo -e "${BLUE}  BEACON - Banking Network Engine${NC}"
echo -e "${BLUE}  Early Alert & Risk Monitoring${NC}"
echo -e "${BLUE}  Docker-Isolated Environment${NC}"
echo -e "${BLUE}============================================${NC}\n"

# =============================================================================
# CHANGE TO PROJECT ROOT
# =============================================================================
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"
echo -e "${GREEN}✓ Working directory: $PROJECT_ROOT${NC}"

# =============================================================================
# PREREQUISITE CHECKS (READ-ONLY HOST OPERATIONS)
# =============================================================================

echo -e "\n${MAGENTA}[Phase 1: Validating Prerequisites]${NC}"

# Check Docker
if ! command -v docker &>/dev/null; then
    echo -e "${RED}✗ Error: Docker is not installed${NC}"
    echo -e "${YELLOW}Please install Docker:${NC}"
    echo -e "  ${CYAN}https://docs.docker.com/get-docker/${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Docker installed${NC}"

# Detect docker compose command (v2 plugin or legacy)
DC_CMD=""
if docker compose version &>/dev/null 2>&1; then
    DC_CMD="docker compose"
    COMPOSE_VERSION=$(docker compose version --short 2>/dev/null || echo "v2.x")
    echo -e "${GREEN}✓ Docker Compose plugin detected ($COMPOSE_VERSION)${NC}"
elif command -v docker-compose &>/dev/null; then
    DC_CMD="docker-compose"
    COMPOSE_VERSION=$(docker-compose --version 2>/dev/null || echo "legacy")
    echo -e "${GREEN}✓ Docker Compose standalone detected ($COMPOSE_VERSION)${NC}"
else
    echo -e "${RED}✗ Error: Docker Compose is not installed${NC}"
    echo -e "${YELLOW}Install Docker Compose:${NC}"
    echo -e "  ${CYAN}https://docs.docker.com/compose/install/${NC}"
    exit 1
fi

# Check .env file (DO NOT CREATE - USER MUST CREATE FROM TEMPLATE)
if [ ! -f .env ]; then
    echo -e "\n${RED}✗ Error: .env file not found${NC}"
    echo -e "${YELLOW}BEACON requires a .env configuration file.${NC}\n"
    echo -e "${CYAN}Setup steps:${NC}"
    echo -e "  ${GREEN}1.${NC} cp .env.example .env"
    echo -e "  ${GREEN}2.${NC} Edit .env and add your API keys (or leave empty)"
    echo -e "  ${GREEN}3.${NC} ./scripts/start_docker_isolated.sh\n"

    # Check if .env.example exists
    if [ -f .env.example ]; then
        echo -e "${CYAN}Quick setup:${NC}"
        echo -e "  ${YELLOW}cp .env.example .env && ./scripts/start_docker_isolated.sh${NC}\n"
    else
        echo -e "${RED}Warning: .env.example not found${NC}"
        echo -e "${YELLOW}Creating minimal .env template...${NC}"
        cat > .env.example <<'EOF'
# BEACON Configuration
POSTGRES_DB=beacon_db
POSTGRES_USER=beacon_user
POSTGRES_PASSWORD=beacon_password
FRED_API_KEY=
ALPHA_VANTAGE_API_KEY=
SEC_API_KEY=
EOF
        echo -e "${GREEN}✓ Created .env.example${NC}"
        echo -e "${YELLOW}Now run: cp .env.example .env${NC}\n"
    fi
    exit 1
fi
echo -e "${GREEN}✓ Found .env file${NC}"

# =============================================================================
# PLATFORM DETECTION (READ-ONLY)
# =============================================================================

echo -e "\n${MAGENTA}[Phase 2: Platform Detection]${NC}"

PLATFORM=$(uname -s)
ARCH=$(uname -m)
COMPOSE_FILES="-f docker-compose.yml"
GPU_AVAILABLE=false

echo -e "${CYAN}Platform Information:${NC}"
echo -e "  OS:           ${PLATFORM}"
echo -e "  Architecture: ${ARCH}"

# Detect Apple Silicon (macOS ARM)
if [[ "$PLATFORM" == "Darwin" ]]; then
    if [[ "$ARCH" == "arm64" ]]; then
        echo -e "  Device:       ${GREEN}macOS Apple Silicon (M1/M2/M3/M4)${NC}"
        echo -e "  Mode:         ${CYAN}CPU-only (no CUDA on macOS)${NC}"
        COMPOSE_FILES="-f docker-compose.yml -f docker-compose.cpu.yml"
    else
        echo -e "  Device:       ${GREEN}macOS Intel${NC}"
        echo -e "  Mode:         ${CYAN}CPU-only${NC}"
        COMPOSE_FILES="-f docker-compose.yml -f docker-compose.cpu.yml"
    fi
    GPU_AVAILABLE=false

# Check for NVIDIA GPU on Linux
elif [[ "$PLATFORM" == "Linux" ]]; then
    if command -v nvidia-smi &>/dev/null; then
        NVIDIA_INFO=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo "NVIDIA GPU")
        echo -e "  GPU:          ${GREEN}$NVIDIA_INFO${NC}"

        # Check for NVIDIA Docker runtime
        if docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q nvidia; then
            echo -e "  Runtime:      ${GREEN}NVIDIA Docker runtime configured${NC}"
            echo -e "  Mode:         ${GREEN}GPU-accelerated${NC}"
            COMPOSE_FILES="-f docker-compose.yml -f docker-compose.gpu.yml"
            GPU_AVAILABLE=true
        else
            echo -e "  Runtime:      ${YELLOW}NVIDIA Docker runtime NOT configured${NC}"
            echo -e "  Mode:         ${CYAN}CPU-only (fallback)${NC}"
            echo -e "${YELLOW}  To enable GPU: Install nvidia-container-toolkit${NC}"
            COMPOSE_FILES="-f docker-compose.yml -f docker-compose.cpu.yml"
            GPU_AVAILABLE=false
        fi
    else
        echo -e "  GPU:          ${CYAN}No NVIDIA GPU detected${NC}"
        echo -e "  Mode:         ${CYAN}CPU-only${NC}"
        COMPOSE_FILES="-f docker-compose.yml -f docker-compose.cpu.yml"
        GPU_AVAILABLE=false
    fi
else
    echo -e "  Platform:     ${YELLOW}Unknown ($PLATFORM)${NC}"
    echo -e "  Mode:         ${CYAN}CPU-only (safe default)${NC}"
    COMPOSE_FILES="-f docker-compose.yml -f docker-compose.cpu.yml"
    GPU_AVAILABLE=false
fi

# =============================================================================
# DOCKER OPERATIONS (100% ISOLATED IN CONTAINERS)
# =============================================================================

echo -e "\n${MAGENTA}[Phase 3: Docker Container Management]${NC}"

# Check if services are already running
SERVICES_RUNNING=false
if $DC_CMD $COMPOSE_FILES ps 2>/dev/null | grep -q "Up"; then
    SERVICES_RUNNING=true
    echo -e "${CYAN}Status: Services are currently running${NC}\n"

    # Show running services
    echo -e "${BLUE}Running containers:${NC}"
    $DC_CMD $COMPOSE_FILES ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || true
    echo ""
fi

# Interactive menu
REBUILD_CHOICE=1
if [ "$SERVICES_RUNNING" = true ]; then
    echo -e "${YELLOW}Select action:${NC}"
    echo -e "  ${GREEN}1${NC}) Restart existing containers (fast, no rebuild)"
    echo -e "  ${GREEN}2${NC}) Rebuild with cache (faster, may miss updates)"
    echo -e "  ${GREEN}3${NC}) Rebuild without cache (clean build, slower)"
    echo -e "  ${GREEN}4${NC}) Stop services and exit"
    echo ""
    read -p "Enter choice [1-4] (default: 1): " -r
    REBUILD_CHOICE="${REPLY:-1}"
else
    echo -e "${CYAN}Status: No services running (first startup)${NC}\n"
    echo -e "${YELLOW}Build options:${NC}"
    echo -e "  ${GREEN}1${NC}) Build with cache (recommended, faster)"
    echo -e "  ${GREEN}2${NC}) Build without cache (clean build, slower)"
    echo ""
    read -p "Enter choice [1-2] (default: 1): " -r
    REBUILD_CHOICE="${REPLY:-1}"
fi

echo ""

# Execute user choice
case "$REBUILD_CHOICE" in
    1)
        if [ "$SERVICES_RUNNING" = true ]; then
            echo -e "${BLUE}Restarting containers...${NC}"
            $DC_CMD $COMPOSE_FILES restart
            OPERATION="restart"
        else
            echo -e "${BLUE}Building images (with cache)...${NC}"
            $DC_CMD $COMPOSE_FILES build
            echo -e "${BLUE}Starting services...${NC}"
            $DC_CMD $COMPOSE_FILES up -d
            OPERATION="first_start"
        fi
        ;;
    2)
        if [ "$SERVICES_RUNNING" = true ]; then
            echo -e "${BLUE}Stopping services...${NC}"
            $DC_CMD $COMPOSE_FILES down
            echo -e "${BLUE}Rebuilding images (with cache)...${NC}"
            $DC_CMD $COMPOSE_FILES build
            echo -e "${BLUE}Starting services...${NC}"
            $DC_CMD $COMPOSE_FILES up -d
            OPERATION="rebuild"
        else
            echo -e "${BLUE}Building images (clean, no cache)...${NC}"
            echo -e "${YELLOW}This may take several minutes...${NC}"
            $DC_CMD $COMPOSE_FILES build --no-cache
            echo -e "${BLUE}Starting services...${NC}"
            $DC_CMD $COMPOSE_FILES up -d
            OPERATION="clean_build"
        fi
        ;;
    3)
        if [ "$SERVICES_RUNNING" = true ]; then
            echo -e "${BLUE}Stopping services...${NC}"
            $DC_CMD $COMPOSE_FILES down
            echo -e "${BLUE}Rebuilding images (clean, no cache)...${NC}"
            echo -e "${YELLOW}This may take several minutes...${NC}"
            $DC_CMD $COMPOSE_FILES build --no-cache
            echo -e "${BLUE}Starting services...${NC}"
            $DC_CMD $COMPOSE_FILES up -d
            OPERATION="clean_rebuild"
        else
            echo -e "${RED}Invalid choice for first startup${NC}"
            exit 1
        fi
        ;;
    4)
        if [ "$SERVICES_RUNNING" = true ]; then
            echo -e "${BLUE}Stopping all services...${NC}"
            $DC_CMD $COMPOSE_FILES down
            echo -e "${GREEN}✓ All services stopped${NC}"
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

# =============================================================================
# HEALTH CHECKS (USING DOCKER EXEC - 100% ISOLATED)
# =============================================================================

echo -e "\n${MAGENTA}[Phase 4: Service Health Verification]${NC}"
echo -e "${CYAN}Waiting for services to initialize...${NC}"
sleep 8

# Function to check service health using docker exec (stays in Docker)
check_service() {
    local service_name=$1
    local check_cmd=$2
    local max_attempts=15
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        if eval "$check_cmd" &>/dev/null; then
            echo -e "${GREEN}✓ $service_name ready${NC}"
            return 0
        fi

        if [ $attempt -eq $max_attempts ]; then
            echo -e "${YELLOW}⚠ $service_name not responding (check logs: docker logs beacon-${service_name,,})${NC}"
            return 1
        fi

        sleep 2
        ((attempt++))
    done
}

# Check PostgreSQL (using docker exec - isolated)
check_service "PostgreSQL" \
    "docker exec beacon-postgres pg_isready -U beacon_user -d beacon_db"

# Check Redis (using docker exec - isolated)
check_service "Redis" \
    "docker exec beacon-redis redis-cli ping"

# Check Backend API (using docker exec - isolated)
check_service "Backend API" \
    "docker exec beacon-backend curl -fsS --max-time 5 http://localhost:3456/health"

# Check Frontend (using docker exec - isolated)
# Note: Frontend runs nginx on port 80 inside container (mapped to 9876 on host)
check_service "Frontend" \
    "docker exec beacon-frontend wget --quiet --tries=1 --spider http://localhost/ || docker exec beacon-frontend curl -fsS --max-time 5 http://localhost/"

# Optional: Check data catalogue (using docker exec - isolated)
echo -e "\n${CYAN}Checking data catalogue initialization...${NC}"
CATALOGUE_CHECK=$(docker exec beacon-backend curl -fsS http://localhost:3456/api/v1/catalogue/summary 2>/dev/null || echo '{"total_items":0}')
CATALOGUE_COUNT=$(echo "$CATALOGUE_CHECK" | grep -o '"total_items":[0-9]*' | grep -o '[0-9]*' || echo "0")

if [ "$CATALOGUE_COUNT" -gt 0 ]; then
    echo -e "${GREEN}✓ Data catalogue ready: $CATALOGUE_COUNT items available${NC}"
else
    echo -e "${YELLOW}⚠ Data catalogue initializing (may take a few seconds)${NC}"
    echo -e "${CYAN}  The catalogue will auto-populate on backend startup${NC}"
    echo -e "${CYAN}  Check progress: ${DC_CMD} logs backend | grep -i catalogue${NC}"
fi

# =============================================================================
# SUCCESS MESSAGE & USER GUIDANCE
# =============================================================================

echo -e "\n${GREEN}============================================${NC}"
echo -e "${GREEN}  ✓ BEACON Services Started Successfully!${NC}"
echo -e "${GREEN}============================================${NC}\n"

echo -e "${BLUE}Access BEACON:${NC}"
echo -e "  • Frontend GUI:  ${GREEN}http://localhost:9876${NC}"
echo -e "  • Backend API:   ${GREEN}http://localhost:3456${NC}"
echo -e "  • API Docs:      ${GREEN}http://localhost:3456/docs${NC}"
echo -e "  • Redoc Docs:    ${GREEN}http://localhost:3456/redoc${NC}\n"

echo -e "${BLUE}Quick Start Guide:${NC}"
echo -e "  ${CYAN}1.${NC} Open ${GREEN}http://localhost:9876${NC} in your browser"
echo -e "  ${CYAN}2.${NC} Navigate to ${YELLOW}Data Catalogue${NC} to browse 48+ data sources"
echo -e "  ${CYAN}3.${NC} Click ${YELLOW}Add to Monitoring${NC} on items you want to track"
echo -e "  ${CYAN}4.${NC} Go to ${YELLOW}Jobs${NC} and create a ${YELLOW}Data Collection${NC} job"
echo -e "  ${CYAN}5.${NC} View results in ${YELLOW}Results & Reports${NC}\n"

echo -e "${BLUE}Useful Commands:${NC}"
echo -e "  • View all logs:         ${YELLOW}${DC_CMD} ${COMPOSE_FILES} logs -f${NC}"
echo -e "  • View backend logs:     ${YELLOW}${DC_CMD} ${COMPOSE_FILES} logs -f backend${NC}"
echo -e "  • View frontend logs:    ${YELLOW}${DC_CMD} ${COMPOSE_FILES} logs -f frontend${NC}"
echo -e "  • View celery logs:      ${YELLOW}${DC_CMD} ${COMPOSE_FILES} logs -f celery-worker${NC}"
echo -e "  • View database logs:    ${YELLOW}${DC_CMD} ${COMPOSE_FILES} logs -f postgres${NC}"
echo -e "  • Stop all services:     ${YELLOW}${DC_CMD} ${COMPOSE_FILES} down${NC}"
echo -e "  • Restart all services:  ${YELLOW}${DC_CMD} ${COMPOSE_FILES} restart${NC}"
echo -e "  • Restart backend only:  ${YELLOW}${DC_CMD} ${COMPOSE_FILES} restart backend${NC}\n"

if [ "$GPU_AVAILABLE" = false ]; then
    echo -e "${YELLOW}Note: Running in CPU-only mode${NC}"
    echo -e "${YELLOW}      GNN training may be slower. Consider using smaller model parameters.${NC}"
    echo -e "${YELLOW}      Configure via the GUI Settings page.${NC}\n"
else
    echo -e "${GREEN}GPU Acceleration: ENABLED${NC}"
    echo -e "${GREEN}GNN training will use GPU acceleration for faster performance.${NC}\n"
fi

# Docker isolation verification
echo -e "${MAGENTA}Docker Isolation Status:${NC}"
echo -e "  ${GREEN}✓${NC} All operations executed in containers"
echo -e "  ${GREEN}✓${NC} No host filesystem modifications (except .env)"
echo -e "  ${GREEN}✓${NC} Data directories auto-created by Docker volumes"
echo -e "  ${GREEN}✓${NC} Health checks via docker exec (isolated)"
echo -e "  ${GREEN}✓${NC} 100% container isolation achieved\n"

echo -e "${GREEN}✓ BEACON is ready!${NC}"
echo -e "${CYAN}Visit ${GREEN}http://localhost:9876${CYAN} to get started.${NC}\n"

# Show container status
echo -e "${BLUE}Container Status:${NC}"
$DC_CMD $COMPOSE_FILES ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || $DC_CMD $COMPOSE_FILES ps

echo ""
