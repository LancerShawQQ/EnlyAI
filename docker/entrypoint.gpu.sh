#!/usr/bin/env bash
# 云端 GPU 容器入口脚本
# 同时启动 TTS 和数字人服务

set -e

echo "=========================================="
echo " KrVoiceAI 云端 GPU 服务"
echo "=========================================="

# 启动 TTS 服务（后台）
echo "[1/2] 启动 TTS 服务 (端口 9880)..."
python -m krvoiceai.api.tts_server --host 0.0.0.0 --port 9880 &
TTS_PID=$!

# 等待 TTS 启动
sleep 3

# 启动数字人服务（前台）
echo "[2/2] 启动数字人服务 (端口 8010)..."
python -m krvoiceai.api.avatar_server --host 0.0.0.0 --port 8010 &
AVATAR_PID=$!

# 捕获信号优雅退出
trap "echo '收到退出信号，停止服务...'; kill $TTS_PID $AVATAR_PID 2>/dev/null; exit 0" SIGINT SIGTERM

# 等待任一进程退出
wait -n $TTS_PID $AVATAR_PID
EXIT_CODE=$?

echo "服务已停止，退出码: $EXIT_CODE"
exit $EXIT_CODE
