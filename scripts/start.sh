#!/bin/bash

# FinAI - Financial Liquidity Risk Monitoring System
# Startup script for Docker environment

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}================================${NC}"
echo -e "${BLUE}  FinAI - Liquidity Monitor${NC}"
echo -e "${BLUE}================================${NC}\n"

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo -e "${RED}Error: Docker is not installed${NC}"
    echo "Please install Docker from: https://docs.docker.com/get-docker/"
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null 2>&1; then
    echo -e "${RED}Error: Docker Compose is not installed${NC}"
    echo "Please install Docker Compose from: https://docs.docker.com/compose/install/"
    exit 1
fi

# Check if NVIDIA Docker runtime is available (for GPU support)
if command -v nvidia-smi &> /dev/null; then
    echo -e "${GREEN}✓ NVIDIA GPU detected${NC}"
    if docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi &> /dev/null; then
        echo -e "${GREEN}✓ NVIDIA Docker runtime configured${NC}"
        GPU_AVAILABLE=true
    else
        echo -e "${YELLOW}⚠ NVIDIA Docker runtime not configured${NC}"
        echo -e "${YELLOW}  GPU acceleration will not be available${NC}"
        echo -e "${YELLOW}  To enable GPU support, install nvidia-docker2${NC}"
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
    cat > .env << EOF
# API Keys (Optional - can be configured via GUI)
FRED_API_KEY=
ALPHA_VANTAGE_API_KEY=

# Database Configuration
POSTGRES_DB=finai_db
POSTGRES_USER=finai_user
POSTGRES_PASSWORD=finai_password
EOF
    echo -e "${GREEN}✓ Created .env file${NC}"
    echo -e "${YELLOW}  You can add API keys now or configure them later via the GUI${NC}"
fi

echo ""
echo -e "${BLUE}Building Docker images...${NC}"
echo -e "${YELLOW}This may take several minutes on first run${NC}\n"

# Build images
if [ "$GPU_AVAILABLE" = true ]; then
    docker-compose build
else
    echo -e "${YELLOW}Building without GPU support${NC}"
    # Remove GPU configuration from docker-compose temporarily
    docker-compose build
fi

echo ""
echo -e "${BLUE}Starting services...${NC}\n"

# Start services
if [ "$GPU_AVAILABLE" = true ]; then
    docker-compose up -d
else
    # Start without GPU requirements
    docker-compose up -d
fi

# Wait for services to be healthy
echo -e "${BLUE}Waiting for services to be ready...${NC}"
sleep 10

# Check service health
echo ""
echo -e "${BLUE}Checking service status...${NC}"

# Check PostgreSQL
if docker exec finai-postgres pg_isready -U finai_user &> /dev/null; then
    echo -e "${GREEN}✓ PostgreSQL is ready${NC}"
else
    echo -e "${RED}✗ PostgreSQL is not ready${NC}"
fi

# Check Redis
if docker exec finai-redis redis-cli ping &> /dev/null; then
    echo -e "${GREEN}✓ Redis is ready${NC}"
else
    echo -e "${RED}✗ Redis is not ready${NC}"
fi

# Check Backend
if curl -s http://localhost:3456/health &> /dev/null; then
    echo -e "${GREEN}✓ Backend API is ready${NC}"
else
    echo -e "${YELLOW}⚠ Backend API is starting...${NC}"
    echo -e "${YELLOW}  It may take a few more seconds${NC}"
fi

# Check Frontend
if curl -s http://localhost:6789 &> /dev/null; then
    echo -e "${GREEN}✓ Frontend is ready${NC}"
else
    echo -e "${YELLOW}⚠ Frontend is starting...${NC}"
    echo -e "${YELLOW}  It may take a minute to compile${NC}"
fi

echo ""
echo -e "${GREEN}================================${NC}"
echo -e "${GREEN}  Services are starting!${NC}"
echo -e "${GREEN}================================${NC}\n"

echo -e "${BLUE}Access the application:${NC}"
echo -e "  • Frontend GUI: ${GREEN}http://localhost:6789${NC}"
echo -e "  • Backend API:  ${GREEN}http://localhost:3456${NC}"
echo -e "  • API Docs:     ${GREEN}http://localhost:3456/docs${NC}\n"

echo -e "${BLUE}Useful commands:${NC}"
echo -e "  • View logs:           ${YELLOW}docker-compose logs -f${NC}"
echo -e "  • View backend logs:   ${YELLOW}docker-compose logs -f backend${NC}"
echo -e "  • View frontend logs:  ${YELLOW}docker-compose logs -f frontend${NC}"
echo -e "  • Stop services:       ${YELLOW}docker-compose down${NC}"
echo -e "  • Restart services:    ${YELLOW}docker-compose restart${NC}\n"

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

echo -e "${GREEN}System started successfully!${NC}"
