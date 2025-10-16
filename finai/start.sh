#!/bin/bash
# Startup script for Liquidity Monitor production system

set -e

echo "=========================================="
echo "Starting Liquidity Monitor v2.0"
echo "=========================================="
echo ""

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "ERROR: Docker is not installed."
    echo "Please install Docker Desktop from: https://www.docker.com/products/docker-desktop"
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "ERROR: Docker Compose is not installed."
    echo "Please install Docker Compose from: https://docs.docker.com/compose/install/"
    exit 1
fi

# Create required directories
echo "Creating required directories..."
mkdir -p data logs models results

# Check for .env file
if [ ! -f .env ]; then
    echo "WARNING: No .env file found. Creating template..."
    cat > .env << EOF
# API Keys (optional - only needed if using these data sources)
FRED_API_KEY=
SEC_API_KEY=

# Database (defaults are fine for local development)
DATABASE_URL=postgresql://liquidity:liquidity@postgres:5432/liquidity_monitor
REDIS_URL=redis://redis:6379/0
EOF
    echo "Created .env file. Please edit it to add your API keys if needed."
    echo ""
fi

# Build and start services
echo "Building Docker images (this may take a few minutes)..."
docker-compose build

echo ""
echo "Starting all services..."
docker-compose up -d

echo ""
echo "Waiting for services to be ready..."
sleep 10

# Check if services are running
if docker-compose ps | grep -q "Up"; then
    echo ""
    echo "=========================================="
    echo "✓ Liquidity Monitor is now running!"
    echo "=========================================="
    echo ""
    echo "Access the application:"
    echo "  - Dashboard:  http://localhost:3000"
    echo "  - API Docs:   http://localhost:8000/docs"
    echo "  - API:        http://localhost:8000"
    echo ""
    echo "Useful commands:"
    echo "  - View logs:  docker-compose logs -f"
    echo "  - Stop:       docker-compose stop"
    echo "  - Restart:    docker-compose restart"
    echo "  - Shutdown:   docker-compose down"
    echo ""
    echo "For first-time setup:"
    echo "  1. Open http://localhost:3000 in your browser"
    echo "  2. Go to 'Data Sources' and add Yahoo Finance (no key needed)"
    echo "  3. Go to 'Assets' and add stocks to monitor"
    echo "  4. Go to 'Jobs' and start a data collection job"
    echo ""
else
    echo ""
    echo "ERROR: Some services failed to start."
    echo "Check logs with: docker-compose logs"
    exit 1
fi
