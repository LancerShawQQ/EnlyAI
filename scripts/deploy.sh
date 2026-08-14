#!/usr/bin/env bash
set -euo pipefail

# ── EnlyAI Deployment Script for Alibaba Cloud ECS ──
#
# Usage:
#   ./scripts/deploy.sh                    # Build locally and deploy
#   ./scripts/deploy.sh --pull             # Pull from ACR and deploy
#   ./scripts/deploy.sh --port 9000        # Custom port
#
# Prerequisites:
#   - Docker and Docker Compose installed
#   - .env.local configured with all API keys
#   - (For --pull) ACR login configured

REGISTRY="registry.cn-hangzhou.aliyuncs.com"
IMAGE_NAME="enlyai/enlyai-classroom"
PORT="${ENLYAI_PORT:-8000}"
PULL_ONLY=false

while [[ $# -gt 0 ]]; do
  case "$1" in
    --pull)    PULL_ONLY=true; shift ;;
    --port)    PORT="$2"; shift 2 ;;
    --help|-h)
      echo "Usage: $0 [--pull] [--port PORT]"
      echo "  --pull   Pull pre-built image from ACR instead of building locally"
      echo "  --port   Override port (default: 8000)"
      exit 0
      ;;
    *) echo "Unknown option: $1"; exit 1 ;;
  esac
done

export ENLYAI_PORT="$PORT"

echo "=== EnlyAI Deployment ==="
echo "Port: $PORT"
echo "Mode: $([ "$PULL_ONLY" = true ] && echo 'Pull from ACR' || echo 'Local build')"
echo ""

if [ "$PULL_ONLY" = true ]; then
  echo "Pulling latest image..."
  docker pull "$REGISTRY/$IMAGE_NAME:latest"
  export DOCKER_IMAGE="$REGISTRY/$IMAGE_NAME:latest"
else
  echo "Building Docker image..."
  docker compose build
fi

echo "Stopping old container..."
docker compose down || true

echo "Starting new container..."
docker compose up -d

echo "Waiting for health check..."
timeout 120 bash -c '
  until docker inspect --format="{{.State.Health.Status}}" enlyai-enlyai-1 2>/dev/null | grep -q healthy; do
    sleep 3
    echo "  Still waiting..."
  done
' && echo "Health check passed!" || echo "WARNING: Health check timed out (container may still be starting)"

echo ""
echo "=== Deployment Complete ==="
docker compose ps
echo ""
echo "App running at: http://localhost:$PORT"
