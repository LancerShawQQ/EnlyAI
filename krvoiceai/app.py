"""KrVoiceAI 核心应用入口

统一封装所有功能，供 CLI / Gradio / API 调用。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .core.config import get_config
from .core.ffmpeg_utils import FFmpegRunner
from .core.gpu_runner import GPURunner
from .core.llm_client import LLMClient
from .core.logger import get_logger, setup_logging
from .core.storage import Storage
from .modules.avatar_engine import AvatarEngine
from .modules.cover_generator import CoverGenerator
from .modules.publisher import Publisher
from .modules.script_extractor import ScriptExtractor
from .modules.script_writer import ScriptWriter
from .modules.subtitle_engine import SubtitleEngine
from .modules.title_generator import TitleGenerator
from .modules.tts_engine import TTSEngine
from .modules.video_composer import VideoComposer
from .pipeline.orchestrator import PipelineOrchestrator, StepDef
from .pipeline.state import JobStore, JobStatus


class KrVoiceAI:
    """KrVoiceAI 应用主入口"""

    def __init__(self, config=None):
        self.config = config or get_config()
        setup_logging()
        self.logger = get_logger().bind(component="app")

        # 基础组件
        self.storage = Storage()
        self.job_store = JobStore()
        self.gpu = GPURunner()
        self.ffmpeg = FFmpegRunner()
        self.llm = LLMClient()

        # 构建编排器
        self.orchestrator = PipelineOrchestrator(
            job_store=self.job_store, storage=self.storage,
        )
        self._register_all_modules()

        self.logger.info(
            f"KrVoiceAI 初始化完成 "
            f"gpu_available={self.gpu.is_gpu_available()} "
            f"llm_mock={self.llm.is_mock}"
        )

    def _register_all_modules(self) -> None:
        """注册所有模块到编排器"""
        ff = self.ffmpeg
        gpu = self.gpu
        llm = self.llm

        modules = {
            "script_extract": ScriptExtractor(ffmpeg=ff),
            "script_write": ScriptWriter(llm_client=llm),
            "tts": TTSEngine(gpu_runner=gpu),
            "avatar": AvatarEngine(gpu_runner=gpu, ffmpeg=ff),
            "subtitle": SubtitleEngine(),
            "compose": VideoComposer(ffmpeg=ff),
            "title": TitleGenerator(llm_client=llm),
            "cover": CoverGenerator(ffmpeg=ff),
            "publish": Publisher(),
        }

        for name, module in modules.items():
            self.orchestrator.register_step(StepDef(
                name=name,
                module=module,
                skip_when=self._make_skip_condition(name),
                optional=name in ("title", "cover", "publish", "script_extract"),
            ))

    def _make_skip_condition(self, step_name: str):
        """为各步骤生成跳过条件"""
        def skip_no_ref_url(ctx):
            return step_name == "script_extract" and not ctx.reference_video_url
        def skip_publish_disabled(ctx):
            return step_name == "publish" and not ctx.metadata.get("auto_publish")
        if step_name == "script_extract":
            return skip_no_ref_url
        if step_name == "publish":
            return skip_publish_disabled
        return None

    # ============ 任务管理 ============

    def submit_and_run(
        self,
        script: str = "",
        reference_video_url: Optional[str] = None,
        avatar_id: str = "default",
        voice_id: str = "default",
        script_mode: str = "polish",
        platform: str = "douyin",
        auto_publish: bool = False,
        metadata: Optional[dict] = None,
    ) -> dict:
        """提交并运行任务，返回结果"""
        meta = {"platform": platform, "auto_publish": auto_publish}
        if metadata:
            meta.update(metadata)

        job_id = self.orchestrator.submit_job(
            script=script,
            reference_video_url=reference_video_url,
            avatar_id=avatar_id,
            voice_id=voice_id,
            script_mode=script_mode,
            metadata=meta,
        )
        success = self.orchestrator.run_job(job_id)
        job = self.orchestrator.get_status(job_id)
        return {
            "job_id": job_id,
            "success": success,
            "status": job["status"],
            "output": job.get("output", {}),
            "error": job.get("error"),
        }

    def get_job(self, job_id: str) -> Optional[dict]:
        return self.orchestrator.get_status(job_id)

    def list_jobs(self, limit: int = 50) -> list[dict]:
        return self.orchestrator.list_jobs(limit)

    def rerun_job(self, job_id: str) -> bool:
        """重跑任务（断点续跑）"""
        return self.orchestrator.run_job(job_id)

    # ============ 形象/音色管理 ============

    def list_avatars(self) -> list[dict]:
        """列出所有已注册的数字人形象"""
        avatars_dir = Path(self.config.get("avatar.avatars_dir", "./config/avatars"))
        result = []
        if not avatars_dir.exists():
            return result
        for d in sorted(avatars_dir.iterdir()):
            if not d.is_dir():
                continue
            info = {"avatar_id": d.name}
            meta_file = d / "meta.json"
            if meta_file.exists():
                try:
                    info["meta"] = json.loads(meta_file.read_text(encoding="utf-8"))
                except Exception:
                    pass
            # 检查参考图
            for name in ("reference.jpg", "reference.png", "placeholder.jpg"):
                if (d / name).exists():
                    info["reference_image"] = str(d / name)
                    break
            result.append(info)
        return result

    def list_voices(self) -> list[dict]:
        """列出所有已注册的音色"""
        voices_dir = Path(self.config.get("tts.voices_dir", "./config/voices"))
        result = []
        if not voices_dir.exists():
            return result
        for d in sorted(voices_dir.iterdir()):
            if not d.is_dir():
                continue
            info = {"voice_id": d.name}
            for ext in (".wav", ".mp3", ".flac"):
                samples = list(d.glob(f"*{ext}"))
                if samples:
                    info["sample"] = str(samples[0])
                    break
            result.append(info)
        return result

    def register_avatar(self, avatar_id: str, reference_video: Path) -> bool:
        """注册数字人形象"""
        avatar = AvatarEngine()
        return avatar.register_avatar(avatar_id, Path(reference_video))

    def register_voice(self, voice_id: str, sample_audio: Path) -> bool:
        """注册音色"""
        tts = TTSEngine()
        return tts.register_voice(voice_id, Path(sample_audio))

    # ============ 健康检查 ============

    def health_check(self) -> dict:
        """系统健康检查"""
        return {
            "ffmpeg": self.ffmpeg.available(),
            "gpu_tts": self.gpu.health_check_tts(),
            "gpu_avatar": self.gpu.health_check_avatar(),
            "llm_mock": self.llm.is_mock,
            "avatars_count": len(self.list_avatars()),
            "voices_count": len(self.list_voices()),
        }
