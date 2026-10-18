#!/bin/bash
set -e

echo "Pulling latest changes from git..."
git pull || true

echo "Pulling pre-built docker image..."
docker compose pull || true

echo "Stopping existing containers..."
docker compose down --remove-orphans || true

echo "Starting containers..."
docker compose up -d --remove-orphans

echo "Removing old Speedtest Logger images..."
IMAGE_REPO="${IMAGE_REPO:-ghcr.io/jsansop/speedtest-logger}"
IMAGE_LABEL="${IMAGE_LABEL:-org.opencontainers.image.source=https://github.com/JSansoP/speedtest-logger}"
CURRENT_IMAGE=$(docker image inspect --format '{{.Id}}' "$IMAGE_REPO:latest" 2>/dev/null || true)
if [ -n "$CURRENT_IMAGE" ]; then
    OLD_IMAGES=$(
        {
            docker images --no-trunc --quiet --filter "reference=$IMAGE_REPO"
            docker images --no-trunc --quiet --filter "label=$IMAGE_LABEL"
        } | sort -u | grep -vxF "$CURRENT_IMAGE" || true
    )
    for image in $OLD_IMAGES; do
        docker rmi -f "$image" || true
    done
else
    echo "No $IMAGE_REPO:latest image found, skipping."
fi

echo "Pruning dangling docker images..."
docker image prune -f

echo "Done! Speedtest Logger is running."

