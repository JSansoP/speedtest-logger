#!/bin/bash

echo "Stopping and removing existing containers..."
# Bring down the docker containers (will not fail if they are not up)
docker compose down || true

echo "Pulling latest changes from git..."
# Pull the latest code from git
# git pull

echo "Building and starting containers..."
# Build and start the containers in detached mode
docker compose up -d --build

echo "Pruning old docker images..."
# Prune old dangling docker images
docker image prune -f

echo "Done!"
