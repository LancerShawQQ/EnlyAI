"""模块工厂

统一构建各模块实例，根据配置自动选择 provider（真实/mock）。
"""
from __future__ import annotations

from typing import Optional

from ..core.config import get_config
from ..core.gpu_runner import GPURunner
from ..core.ffmpeg_utils import FFmpegRunner
from ..core.llm_client import LLMClient
from ..modules.script_writer import ScriptWriter
from ..modules.tts_engine import TTSEngine
from ..modules.avatar_engine import AvatarEngine
from ..modules.subtitle_engine import SubtitleEngine
from ..modules.video_composer import VideoComposer


def build_core_modules(
    config=None,
    gpu_runner: Optional[GPURunner] = None,
    ffmpeg: Optional[FFmpegRunner] = None,
    llm_client: Optional[LLMClient] = None,
) -> dict:
    """构建核心闭环所需的所有模块

    Returns:
        包含 script_write/tts/avatar/subtitle/compose 的模块字典
    """
    gpu = gpu_runner or GPURunner()
    ff = ffmpeg or FFmpegRunner()
    llm = llm_client or LLMClient()

    return {
        "script_write": ScriptWriter(config=config, llm_client=llm),
        "tts": TTSEngine(config=config, gpu_runner=gpu),
        "avatar": AvatarEngine(config=config, gpu_runner=gpu, ffmpeg=ff),
        "subtitle": SubtitleEngine(config=config),
        "compose": VideoComposer(config=config, ffmpeg=ff),
    }
