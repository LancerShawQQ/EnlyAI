#!/usr/bin/env bash
# Docker 镜像构建脚本
#
# 用途：构建 KrVoiceAI 的本地版和云端 GPU 版 Docker 镜像
#
# 使用方式：
#   bash scripts/build_docker.sh local    # 构建本地 CPU 版
#   bash scripts/build_docker.sh gpu      # 构建云端 GPU 版
#   bash scripts/build_docker.sh all      # 构建全部

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
NC='\033[0m'

log()  { echo -e "${GREEN}[INFO]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DOCKER_DIR="$PROJECT_ROOT/docker"

TARGET="${1:-all}"

build_local() {
    log "构建本地 CPU 镜像 krvoiceai:local..."
    docker build \
        -f "$DOCKER_DIR/Dockerfile.local" \
        -t krvoiceai:local \
        "$PROJECT_ROOT"
    log "本地镜像构建完成: krvoiceai:local"
}

build_gpu() {
    log "构建云端 GPU 镜像 krvoiceai:gpu..."
    docker build \
        -f "$DOCKER_DIR/Dockerfile.gpu" \
        -t krvoiceai:gpu \
        "$PROJECT_ROOT"
    log "GPU 镜像构建完成: krvoiceai:gpu"
}

case "$TARGET" in
    local)
        build_local
        ;;
    gpu)
        build_gpu
        ;;
    all)
        build_local
        build_gpu
        ;;
    *)
        err "未知目标: $TARGET"
        echo "用法: bash scripts/build_docker.sh [local|gpu|all]"
        exit 1
        ;;
esac

log "完成！"
echo ""
echo "可用镜像："
docker images | grep krvoiceai || true
