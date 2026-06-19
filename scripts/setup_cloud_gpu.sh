#!/usr/bin/env bash
# 云 GPU 环境一键安装脚本
#
# 用途：在租用的云 GPU 实例上执行，安装 KrVoiceAI 云端推理所需依赖
# 适用：Ubuntu 22.04 + NVIDIA GPU（CUDA 12.1+）
#
# 使用方式：
#   bash scripts/setup_cloud_gpu.sh
#
# 安装内容：
#   1. 系统依赖（ffmpeg, git, build-essential）
#   2. Python 3.10 + venv
#   3. PyTorch (CUDA 12.1)
#   4. GPT-SoVITS（TTS 声音克隆）
#   5. MuseTalk（数字人口型同步）
#   6. FunASR（ASR，可选）
#   7. KrVoiceAI API 服务

set -euo pipefail

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# 工作目录
WORKSPACE_DIR="${WORKSPACE_DIR:-$HOME/krvoiceai}"
VENV_DIR="${VENV_DIR:-$WORKSPACE_DIR/.venv}"
MODELS_DIR="${MODELS_DIR:-$WORKSPACE_DATA/models}"

# 检查 GPU
if ! command -v nvidia-smi &> /dev/null; then
    warn "未检测到 nvidia-smi，将跳过 GPU 相关步骤"
    GPU_AVAILABLE=0
else
    log "检测到 GPU："
    nvidia-smi --query-gpu=name,memory.total --format=csv
    GPU_AVAILABLE=1
fi

# 1. 安装系统依赖
log "安装系统依赖..."
sudo apt-get update -qq
sudo apt-get install -y -qq \
    build-essential \
    git \
    ffmpeg \
    libsndfile1 \
    libgl1 \
    libglib2.0-0 \
    wget \
    curl \
    python3.10 \
    python3.10-venv \
    python3-pip

# 2. 创建工作目录
log "创建工作目录..."
mkdir -p "$WORKSPACE_DIR" "$MODELS_DIR"

# 3. 创建虚拟环境
if [ ! -d "$VENV_DIR" ]; then
    log "创建 Python 虚拟环境..."
    python3.10 -m venv "$VENV_DIR"
fi

# 激活虚拟环境
source "$VENV_DIR/bin/activate"
log "已激活虚拟环境: $VENV_DIR"

# 升级 pip
pip install --upgrade pip wheel setuptools

# 4. 安装 PyTorch
if [ "$GPU_AVAILABLE" = "1" ]; then
    log "安装 PyTorch (CUDA 12.1)..."
    pip install torch==2.3.0 torchvision==0.18.0 torchaudio==2.3.0 \
        --index-url https://download.pytorch.org/whl/cu121
else
    warn "无 GPU，安装 CPU 版 PyTorch..."
    pip install torch==2.3.0 torchvision==0.18.0 torchaudio==2.3.0 \
        --index-url https://download.pytorch.org/whl/cpu
fi

# 5. 安装 KrVoiceAI API 依赖
log "安装 KrVoiceAI API 依赖..."
pip install fastapi==0.111.0 uvicorn[standard]==0.30.1 \
    pydantic==2.7.1 httpx==0.27.0 loguru==0.7.2 \
    Pillow==10.3.0 numpy==1.26.4 soundfile==0.12.1

# 6. 安装 GPT-SoVITS
if [ ! -d "$WORKSPACE_DIR/GPT-SoVITS" ]; then
    log "克隆 GPT-SoVITS..."
    cd "$WORKSPACE_DIR"
    git clone https://github.com/RVC-Boss/GPT-SoVITS.git
    cd GPT-SoVITS
    pip install -r requirements.txt
    pip install -r requirements.txt  # 二次确保
else
    log "GPT-SoVITS 已存在，跳过克隆"
fi

# 7. 安装 MuseTalk
if [ ! -d "$WORKSPACE_DIR/MuseTalk" ]; then
    log "克隆 MuseTalk..."
    cd "$WORKSPACE_DIR"
    git clone https://github.com/TMElyralab/MuseTalk.git
    cd MuseTalk
    pip install -r requirements.txt
else
    log "MuseTalk 已存在，跳过克隆"
fi

# 8. 安装 FunASR（可选，用于云端 ASR）
log "安装 FunASR..."
pip install funasr==1.0.27 modelscope==1.11.0

# 9. 下载预训练模型
log "下载预训练模型..."
if [ -f "$WORKSPACE_DIR/scripts/download_models.sh" ]; then
    bash "$WORKSPACE_DIR/scripts/download_models.sh"
else
    warn "未找到 download_models.sh，跳过模型下载"
fi

# 10. 配置环境变量
log "生成环境配置..."
cat > "$WORKSPACE_DIR/.env.cloud" <<EOF
# 云端 GPU 环境变量
VOICES_DIR=$WORKSPACE_DIR/config/voices
AVATARS_DIR=$WORKSPACE_DIR/config/avatars
MODELS_DIR=$MODELS_DIR
PYTHONPATH=$WORKSPACE_DIR
EOF

log "安装完成！"
echo ""
echo "=========================================="
echo " 下一步："
echo " 1. cd $WORKSPACE_DIR"
echo " 2. source .venv/bin/activate"
echo " 3. 启动 TTS 服务: python -m krvoiceai.api.tts_server --port 9880"
echo " 4. 启动数字人服务: python -m krvoiceai.api.avatar_server --port 8010"
echo " 5. 本地 KrVoiceAI 配置 gpu_runner.tts_endpoint 和 avatar_endpoint 指向本机"
echo "=========================================="
