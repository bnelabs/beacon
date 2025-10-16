#!/bin/bash
# Stop script for Liquidity Monitor

echo "Stopping Liquidity Monitor..."
docker-compose stop

echo ""
echo "Liquidity Monitor has been stopped."
echo ""
echo "To start again: ./start.sh"
echo "To remove all containers: docker-compose down"
echo "To remove all data: docker-compose down -v"
