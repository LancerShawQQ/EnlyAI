#!/usr/bin/env bash
# 下载预训练模型脚本
#
# 用途：下载 GPT-SoVITS / MuseTalk / FunASR 所需的预训练模型
# 适用：云端 GPU 实例（也可在本地下载后上传）
#
# 使用方式：
#   bash scripts/download_models.sh

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[INFO]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERROR]${NC} $*" >&2; }

# 模型存放根目录
MODELS_ROOT="${MODELS_ROOT:-$HOME/krvoiceai_models}"
mkdir -p "$MODELS_ROOT"

# ============================================
# 1. GPT-SoVITS 预训练模型
# ============================================
log "下载 GPT-SoVITS 预训练模型..."
GPT_SOVITS_DIR="$MODELS_ROOT/GPT-SoVITS"
mkdir -p "$GPT_SOVITS_DIR/GPT_weights" "$GPT_SOVITS_DIR/SoVITS_weights"

# 下载基础模型（s1bert25hz / s2G488k）
# 官方下载地址：https://huggingface.co/lj1995/GPT-SoVITS
if [ ! -f "$GPT_SOVITS_DIR/gsv-base/gsv-base.pth" ]; then
    log "下载 GPT-SoVITS base 模型（约 1GB）..."
    mkdir -p "$GPT_SOVITS_DIR/gsv-base"
    wget -q -O "$GPT_SOVITS_DIR/gsv-base/gsv-base.pth" \
        "https://huggingface.co/lj1995/GPT-SoVITS/resolve/main/gsv-base/gsv-base.pth" \
        || warn "GPT-SoVITS base 下载失败，请手动下载"
fi

# 下载 BERT 模型（中文）
if [ ! -d "$GPT_SOVITS_DIR/chinese-roberta-wwm-ext-large" ]; then
    log "下载 chinese-roberta-wwm-ext-large..."
    mkdir -p "$GPT_SOVITS_DIR/chinese-roberta-wwm-ext-large"
    cd "$GPT_SOVITS_DIR/chinese-roberta-wwm-ext-large"
    for f in config.json pytorch_model.bin tokenizer.json vocab.txt; do
        wget -q -O "$f" \
            "https://huggingface.co/hfl/chinese-roberta-wwm-ext-large/resolve/main/$f" \
            || warn "$f 下载失败"
    done
    cd -
fi

# ============================================
# 2. MuseTalk 预训练模型
# ============================================
log "下载 MuseTalk 预训练模型..."
MUSETALK_DIR="$MODELS_ROOT/MuseTalk"
mkdir -p "$MUSETALK_DIR"

# MuseTalk 模型（约 1.5GB）
# 官方下载地址：https://huggingface.co/TMElyralab/MuseTalk
if [ ! -f "$MUSETALK_DIR/musetalkV15.pt" ]; then
    log "下载 MuseTalk v1.5 模型..."
    wget -q -O "$MUSETALK_DIR/musetalkV15.pt" \
        "https://huggingface.co/TMElyralab/MuseTalk/resolve/main/models/musetalkV15.pt" \
        || warn "MuseTalk 模型下载失败，请手动下载"
fi

# 下载 SD VAE（用于 MuseTalk 后处理）
if [ ! -d "$MUSETALK_DIR/sd-vae-ft-mse" ]; then
    log "下载 sd-vae-ft-mse..."
    mkdir -p "$MUSETALK_DIR/sd-vae-ft-mse"
    cd "$MUSETALK_DIR/sd-vae-ft-mse"
    for f in config.json diffusion_pytorch_model.bin; do
        wget -q -O "$f" \
            "https://huggingface.co/stabilityai/sd-vae-ft-mse/resolve/main/$f" \
            || warn "$f 下载失败"
    done
    cd -
fi

# ============================================
# 3. FunASR 模型（paraformer-zh）
# ============================================
log "FunASR 模型将在首次调用时自动下载到 ModelScope 缓存目录"
log "如需预下载，请执行："
echo "  python -c \"from funasr import AutoModel; m = AutoModel(model='paraformer-zh', vad_model='fsmn-vad', punc_model='ct-punc')\""

# ============================================
# 4. Whisper 模型（备选 ASR）
# ============================================
log "Whisper 模型将在首次调用时自动下载"

# ============================================
# 5. 字体文件（用于字幕和封面）
# ============================================
log "下载思源黑体字体..."
FONTS_DIR="${FONTS_DIR:-$HOME/krvoiceai/config/fonts}"
mkdir -p "$FONTS_DIR"
if [ ! -f "$FONTS_DIR/SourceHanSansCN-Bold.otf" ]; then
    wget -q -O "$FONTS_DIR/SourceHanSansCN-Bold.otf" \
        "https://github.com/adobe-fonts/source-han-sans/raw/release/OTF/SimplifiedChinese/SourceHanSansSC-Bold.otf" \
        || warn "字体下载失败，将使用系统默认字体"
fi

log "模型下载完成！"
echo ""
echo "模型存放目录：$MODELS_ROOT"
echo "字体存放目录：$FONTS_DIR"
echo ""
echo "请设置环境变量："
echo "  export MODELS_DIR=$MODELS_ROOT"
echo "  export GPT_SOVITS_MODELS=$GPT_SOVITS_DIR"
echo "  export MUSETALK_MODELS=$MUSETALK_DIR"
