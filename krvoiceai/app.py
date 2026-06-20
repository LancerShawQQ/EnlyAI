"""KrVoiceAI 核心应用入口

统一封装所有功能，供 CLI / Gradio / API 调用。
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Optional

from .core.base_module import BaseModule, JobContext, ModuleResult
from .core.config import get_config
from .core.ffmpeg_utils import FFmpegRunner
from .core.gpu_runner import GPURunner
from .core.llm_client import LLMClient
from .core.logger import get_logger, setup_logging
from .core.settings_manager import get_settings_manager
from .core.storage import Storage
from .modules.avatar_engine import AvatarEngine
from .modules.broll_engine import BRollEngine
from .modules.cover_generator import CoverGenerator
from .modules.publisher import Publisher
from .modules.script_extractor import ScriptExtractor
from .modules.script_writer import ScriptWriter
from .modules.subtitle_engine import SubtitleEngine
from .modules.title_generator import TitleGenerator
from .modules.tts_engine import TTSEngine
from .modules.video_composer import VideoComposer
from .pipeline.orchestrator import PipelineOrchestrator, StepDef
from .pipeline.state import JobStatus, JobStore, PIPELINE_STEPS, StepStatus


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

        # 注册设置变更监听器：用户在 UI 修改配置后热重建组件
        get_settings_manager().add_listener(self._on_settings_changed)

        self.logger.info(
            f"KrVoiceAI 初始化完成 "
            f"gpu_available={self.gpu.is_gpu_available()} "
            f"llm_mock={self.llm.is_mock}"
        )

    def _on_settings_changed(self, change: dict) -> None:
        """配置变更回调：重建受影响的组件"""
        try:
            # 重新加载配置
            self.config = get_config(reload=True)
            # 重建 LLM 客户端
            if "llm" in change or "_reset_all" in change:
                self.llm = LLMClient()
                self.logger.info("LLM 客户端已热重建")
            # 重建各模块（它们在 __init__ 读取配置，且 ScriptWriter/Title 持有 LLM 引用）
            # 任何配置变更都重建模块，确保引用一致
            if any(k in change for k in ("llm", "tts", "avatar", "asr", "composer",
                                          "cover", "publisher", "pipeline")) or "_reset_all" in change:
                self._register_all_modules()
                self.logger.info("模块已按新配置热重建")
        except Exception as e:
            self.logger.error(f"配置热更新失败: {e}")

    def _register_all_modules(self) -> None:
        """注册所有模块到编排器"""
        ff = self.ffmpeg
        gpu = self.gpu
        llm = self.llm

        # 同时保存到 self.modules 供单模块执行使用
        self.modules: dict[str, BaseModule] = {
            "script_extract": ScriptExtractor(ffmpeg=ff),
            "script_write": ScriptWriter(llm_client=llm),
            "tts": TTSEngine(gpu_runner=gpu),
            "avatar": AvatarEngine(gpu_runner=gpu, ffmpeg=ff),
            "subtitle": SubtitleEngine(),
            "broll": BRollEngine(ffmpeg=ff),
            "compose": VideoComposer(ffmpeg=ff),
            "title": TitleGenerator(llm_client=llm),
            "cover": CoverGenerator(ffmpeg=ff),
            "publish": Publisher(),
        }

        for name, module in self.modules.items():
            self.orchestrator.register_step(StepDef(
                name=name,
                module=module,
                skip_when=self._make_skip_condition(name),
                optional=name in ("title", "cover", "publish", "script_extract", "broll"),
            ))

    def _make_skip_condition(self, step_name: str):
        """为各步骤生成跳过条件"""
        def skip_no_ref_url(ctx):
            return step_name == "script_extract" and not ctx.reference_video_url
        def skip_publish_disabled(ctx):
            return step_name == "publish" and not ctx.metadata.get("auto_publish")
        def skip_no_broll(ctx):
            return step_name == "broll" and not ctx.broll_clips
        if step_name == "script_extract":
            return skip_no_ref_url
        if step_name == "publish":
            return skip_publish_disabled
        if step_name == "broll":
            return skip_no_broll
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
        broll_clips: Optional[list] = None,
        progress_callback: Optional[Callable[[str, str, dict], None]] = None,
    ) -> dict:
        """提交并运行任务，返回结果

        Args:
            broll_clips: B-roll 画中画/插播片段列表（可选）
            progress_callback: 可选的进度回调函数 (step_name, status, data)

        Returns:
            包含 job_id/success/elapsed/stages/video_path/subtitle_path/title/cover_path 等
            用户友好字段的结果字典
        """
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
            broll_clips=broll_clips,
        )
        import time as _time
        t0 = _time.time()
        success = self.orchestrator.run_job(job_id, progress_callback=progress_callback)
        elapsed = _time.time() - t0
        job = self.orchestrator.get_status(job_id)
        output = job.get("output", {}) or {}

        # 构建 stages 列表（保留执行顺序与耗时）
        stages = []
        for s in job.get("steps", []):
            stages.append({
                "step": s.get("step"),
                "status": s.get("status"),
                "elapsed": s.get("duration", 0) or 0,
                "result": s.get("result"),
                "error": s.get("error"),
            })

        return {
            "job_id": job_id,
            "success": success,
            "status": job["status"],
            "elapsed": round(elapsed, 2),
            "error": job.get("error"),
            # 用户友好的顶层输出字段
            "video_path": output.get("final_video"),
            "audio_path": output.get("audio_path"),
            "audio_duration": output.get("audio_duration"),
            "subtitle_path": output.get("subtitle"),
            "title": output.get("title"),
            "cover_path": output.get("cover"),
            "script_text": output.get("script_text"),
            # 完整阶段执行详情
            "stages": stages,
            # 原始输出（向后兼容）
            "output": output,
            "steps": {s["step"]: {"status": s["status"], "result": s.get("result")}
                      for s in job.get("steps", [])},
        }

    def run_single_module(
        self,
        module_name: str,
        script: str = "",
        reference_video_url: Optional[str] = None,
        avatar_id: str = "default",
        voice_id: str = "default",
        script_mode: str = "polish",
        platform: str = "douyin",
        metadata: Optional[dict] = None,
        broll_clips: Optional[list] = None,
    ) -> dict:
        """单独执行某个模块（用于 UI 单步调试）

        会自动执行该模块之前的所有依赖步骤以准备上下文。

        Returns:
            {"success": bool, "module": str, "result": dict, "error": str}
        """
        if module_name not in self.modules:
            return {"success": False, "error": f"未知模块: {module_name}"}

        meta = {"platform": platform, "auto_publish": False, "script_mode": script_mode}
        if metadata:
            meta.update(metadata)

        # 创建临时任务上下文
        job_id = self.orchestrator.submit_job(
            script=script,
            reference_video_url=reference_video_url,
            avatar_id=avatar_id,
            voice_id=voice_id,
            script_mode=script_mode,
            metadata=meta,
            broll_clips=broll_clips,
        )
        job = self.job_store.get_job(job_id)
        ctx = self.orchestrator._build_context(job_id, job["input"])

        # 执行目标模块之前的所有模块（准备上下文）
        target_idx = PIPELINE_STEPS.index(module_name)
        for step_name in PIPELINE_STEPS[:target_idx]:
            step_def = self.orchestrator._steps.get(step_name)
            if step_def is None:
                continue
            if step_def.skip_when and step_def.skip_when(ctx):
                continue
            result = step_def.module.execute(ctx)
            if not result.success and not step_def.optional:
                return {
                    "success": False,
                    "module": module_name,
                    "error": f"前置步骤 {step_name} 失败: {result.error}",
                }

        # 执行目标模块
        module = self.modules[module_name]
        result = module.execute(ctx)
        return {
            "success": result.success,
            "module": module_name,
            "result": result.data,
            "error": result.error,
            "duration": result.duration,
            "context": self._context_to_dict(ctx),
        }

    def _context_to_dict(self, ctx: JobContext) -> dict:
        """将上下文转为可序列化的 dict"""
        return {
            "job_id": ctx.job_id,
            "script_text": ctx.script_text,
            "audio_path": str(ctx.audio_path) if ctx.audio_path else None,
            "audio_duration": ctx.audio_duration,
            "raw_video_path": str(ctx.raw_video_path) if ctx.raw_video_path else None,
            "subtitle_path": str(ctx.subtitle_path) if ctx.subtitle_path else None,
            "cover_path": str(ctx.cover_path) if ctx.cover_path else None,
            "title": ctx.title,
            "final_video": str(ctx.final_video) if ctx.final_video else None,
        }

    def get_job(self, job_id: str) -> Optional[dict]:
        return self.orchestrator.get_status(job_id)

    def list_jobs(self, limit: int = 50) -> list[dict]:
        return self.orchestrator.list_jobs(limit)

    def rerun_job(self, job_id: str) -> bool:
        """重跑任务（断点续跑）"""
        return self.orchestrator.run_job(job_id)

    def delete_job(self, job_id: str) -> bool:
        """删除任务"""
        return self.job_store.delete_job(job_id)

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
        """列出所有可用音色（含已注册音色 + 当前 provider 默认音色）"""
        voices_dir = Path(self.config.get("tts.voices_dir", "./config/voices"))
        result = []
        seen_ids = set()

        # 1. 当前 provider 的默认音色（确保用户始终能看到可选音色）
        provider = self.config.get("tts.provider", "mock")
        default_voice = self.config.get("tts.default_voice", "default")
        if default_voice and default_voice not in seen_ids:
            result.append({
                "voice_id": default_voice,
                "type": "provider_default",
                "provider": provider,
            })
            seen_ids.add(default_voice)

        # 2. 已注册的自定义音色（用户上传的音色样本）
        if voices_dir.exists():
            for d in sorted(voices_dir.iterdir()):
                if not d.is_dir():
                    continue
                if d.name in seen_ids:
                    continue
                info = {"voice_id": d.name, "type": "custom", "provider": provider}
                for ext in (".wav", ".mp3", ".flac"):
                    samples = list(d.glob(f"*{ext}"))
                    if samples:
                        info["sample"] = str(samples[0])
                        break
                result.append(info)
                seen_ids.add(d.name)
        return result

    def register_avatar(self, avatar_id: str, reference_video: Path) -> bool:
        """注册数字人形象"""
        avatar = AvatarEngine()
        avatar.setup()  # 触发 GPU 不可用时的 mock 降级
        return avatar.register_avatar(avatar_id, Path(reference_video))

    def register_voice(self, voice_id: str, sample_audio: Path) -> bool:
        """注册音色"""
        tts = TTSEngine()
        tts.setup()  # 触发 GPU 不可用时的 mock 降级
        return tts.register_voice(voice_id, Path(sample_audio))

    # ============ 健康检查 ============

    def health_check(self) -> dict:
        """系统健康检查"""
        ffmpeg_ok = self.ffmpeg.available()
        gpu_tts_ok = self.gpu.health_check_tts()
        gpu_avatar_ok = self.gpu.health_check_avatar()
        # 综合状态：ffmpeg 必须可用；LLM/TTS/Avatar 允许 mock 降级
        overall_ok = ffmpeg_ok
        return {
            "status": "ok" if overall_ok else "degraded",
            "version": self.config.get("project.version", "unknown"),
            "ffmpeg": ffmpeg_ok,
            "gpu_tts": gpu_tts_ok,
            "gpu_avatar": gpu_avatar_ok,
            "llm_mock": self.llm.is_mock,
            "avatars_count": len(self.list_avatars()),
            "voices_count": len(self.list_voices()),
        }

    # ============ 文案 AI 处理 ============

    def process_script(
        self,
        script: str,
        action: str = "polish",
        style: Optional[str] = None,
        topic: Optional[str] = None,
    ) -> dict:
        """AI 文案处理（独立于流水线，供文案工作台调用）

        Args:
            script: 原始文案（generate 模式下可为空）
            action: polish/rewrite/expand/shorten/style/generate
            style: 风格转换时的目标风格（幽默/严肃/活泼/专业/口语化/煽情）
            topic: generate 模式下的主题

        Returns:
            {"success": bool, "script": str, "action": str, "error": str}
        """
        # 构造 prompt
        sys_prompt = (
            "你是一位资深的短视频口播文案创作者，擅长创作高完播率、高互动的口播内容。"
            "文案要求：口语化、短句为主、段落分明、150-400字、不要 emoji 和结构标签。"
        )

        action_map = {
            "polish": "请润色以下口播文案，使其更口语化、更有感染力，保留原意和核心信息。直接输出文案，不要解释。\n\n原始文案：\n{input}",
            "rewrite": "请对以下口播文案进行语义级仿写：保留核心观点和信息结构，替换表达方式避免雷同。直接输出文案，不要解释。\n\n原始文案：\n{input}",
            "expand": "请将以下口播文案扩写为更详细、更丰富的版本，增加具体案例、细节描写和情感渲染，但保持原主题。目标字数 300-500 字。直接输出文案，不要解释。\n\n原始文案：\n{input}",
            "shorten": "请将以下口播文案精简压缩，去除冗余，保留核心信息，使其更紧凑有力。目标字数 100-200 字。直接输出文案，不要解释。\n\n原始文案：\n{input}",
            "style": "请将以下口播文案转换为【{style}】风格，保持核心信息不变，调整用词、语气和表达方式以符合目标风格。直接输出文案，不要解释。\n\n原始文案：\n{input}",
            "generate": "请根据以下主题/要点，创作一段口播文案。要求开场有钩子、中间有价值点、结尾有行动号召。直接输出文案，不要解释。\n\n主题/要求：\n{input}",
        }

        if action not in action_map:
            return {"success": False, "error": f"不支持的操作: {action}"}

        if action == "generate":
            input_text = topic or script or "短视频运营技巧"
        elif action == "style":
            if not style:
                return {"success": False, "error": "style 模式需要指定 style 参数"}
            input_text = script
        else:
            if not script:
                return {"success": False, "error": "文案不能为空"}
            input_text = script

        user_prompt = action_map[action].format(input=input_text, style=style or "")

        try:
            messages = [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user_prompt},
            ]
            result = self.llm.chat(messages)
            # 后处理
            lines = [line.strip() for line in result.splitlines()]
            cleaned = []
            prev_empty = False
            for line in lines:
                if not line:
                    if not prev_empty:
                        cleaned.append("")
                    prev_empty = True
                else:
                    cleaned.append(line)
                    prev_empty = False
            while cleaned and not cleaned[0]:
                cleaned.pop(0)
            while cleaned and not cleaned[-1]:
                cleaned.pop()
            result = "\n".join(cleaned)

            return {
                "success": True,
                "script": result,
                "action": action,
                "style": style,
                "char_count": len(result),
                "mock": self.llm.is_mock,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "action": action}
