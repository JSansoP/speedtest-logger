#!/bin/bash
set -e

echo "Pulling latest changes from git..."
git pull || true

echo "Pulling pre-built docker image..."
docker compose pull || true

echo "Stopping existing containers..."
docker compose down || true

echo "Starting containers..."
docker compose up -d

echo "Pruning old docker images..."
docker image prune -f

echo "Done! Speedtest Logger is running."

