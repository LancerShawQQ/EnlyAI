"""统一的路径管理

集中管理项目中所有路径常量，避免散落在各模块中的硬编码路径。
所有路径基于项目根目录（PROJECT_ROOT）锚定，不依赖 CWD。
"""
from __future__ import annotations

from pathlib import Path

# 项目根目录（krvoiceai 包的上级目录）
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# === 配置目录 ===
CONFIG_DIR = PROJECT_ROOT / "config"
VOICES_DIR = CONFIG_DIR / "voices"
AVATARS_DIR = CONFIG_DIR / "avatars"
BGM_DIR = CONFIG_DIR / "bgm"
COVER_TEMPLATES_DIR = CONFIG_DIR / "cover_templates"
BROLL_ASSETS_DIR = CONFIG_DIR / "broll_assets"
COOKIES_DIR = CONFIG_DIR / "cookies"
SCENE_TEMPLATES_DIR = CONFIG_DIR / "presets"

# === 工作数据目录 ===
WORKSPACE_DIR = PROJECT_ROOT / "workspace_data"
TMP_DIR = WORKSPACE_DIR / "tmp"
JOBS_DIR = WORKSPACE_DIR / "jobs"
LOGS_DIR = WORKSPACE_DIR / "logs"
MODELS_DIR = WORKSPACE_DIR / "models"
PODCASTS_DIR = WORKSPACE_DIR / "podcasts"
TTS_CACHE_DIR = WORKSPACE_DIR / "tts_cache"

# === 音色样本目录 ===
VOICE_SAMPLES_DIR = VOICES_DIR / "samples"

# === 第三方依赖路径（与项目同级的上级目录）===
PARENT_DIR = PROJECT_ROOT.parent
WAV2LIP_DIR = PARENT_DIR / "Wav2Lip"
WAV2LIP_ENV_PYTHON = PARENT_DIR / "wav2lip_env" / "Scripts" / "python.exe"
WAV2LIP_CHECKPOINT = WAV2LIP_DIR / "checkpoints" / "wav2lip_gan.pth"
MOSS_TTS_DIR = PARENT_DIR / "MOSS-TTS-Nano"
LATENTSYNC_DIR = PARENT_DIR / "LatentSync"


def ensure_dirs() -> None:
    """确保关键工作目录存在"""
    for d in (WORKSPACE_DIR, TMP_DIR, JOBS_DIR, LOGS_DIR, VOICE_SAMPLES_DIR, TTS_CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)
