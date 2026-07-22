"""EnlyAI 核心应用入口

统一封装所有功能，供 CLI / Gradio / API 调用。
"""
from __future__ import annotations

import atexit
import json
import shutil
import threading
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
from .modules.originality_checker import OriginalityChecker
from .modules.podcast_engine import PodcastEngine
from .modules.publisher import Publisher
from .modules.script_extractor import ScriptExtractor
from .modules.script_writer import ScriptWriter
from .modules.subtitle_engine import SubtitleEngine
from .modules.title_generator import TitleGenerator
from .modules.tts_engine import TTSEngine
from .modules.video_composer import VideoComposer
from .pipeline.orchestrator import PipelineOrchestrator, StepDef
from .pipeline.state import JobStatus, JobStore, PIPELINE_STEPS, StepStatus


# 文案爆款模板库（对标万兴播爆/即梦AI灵感社区）
SCRIPT_TEMPLATES = [
    {
        "id": "viral_hook",
        "name": "爆款钩子型",
        "icon": "flame",
        "category": "通用",
        "desc": "强钩子开场+痛点共鸣+解决方案+CTA",
        "structure": "开场钩子（反差/数字/痛点，3秒内抓住注意力）→ 痛点共鸣（描述用户困境）→ 价值方案（3个核心要点）→ 行动号召",
        "example": "90%的人不知道这个技巧...",
    },
    {
        "id": "story_case",
        "name": "故事案例型",
        "icon": "book-open",
        "category": "通用",
        "desc": "真实案例+转折反转+经验总结+引导",
        "structure": "故事开场（真实案例引入）→ 冲突转折（遇到什么问题）→ 解决过程（怎么做）→ 经验总结+CTA",
        "example": "上周有个客户跟我说...",
    },
    {
        "id": "knowledge",
        "name": "知识科普型",
        "icon": "graduation-cap",
        "category": "教培",
        "desc": "提出问题+原理解释+实操步骤+总结",
        "structure": "提问开场（引发好奇）→ 原理解释（为什么）→ 实操步骤（怎么做，3步）→ 总结要点+关注引导",
        "example": "为什么你发的视频没人看？",
    },
    {
        "id": "contrast",
        "name": "对比反差型",
        "icon": "git-compare",
        "category": "通用",
        "desc": "错误做法VS正确做法+原理解析+建议",
        "structure": "错误做法展示（引发共鸣）→ 正确做法对比 → 原理解析 → 实操建议+CTA",
        "example": "别再用老方法了，正确做法是这样的...",
    },
    {
        "id": "news_hot",
        "name": "热点解读型",
        "icon": "trending-up",
        "category": "资讯",
        "desc": "热点事件+深度解读+个人观点+互动",
        "structure": "热点事件引入（蹭流量）→ 深度解读（为什么发生/影响）→ 个人观点（有态度）→ 互动引导",
        "example": "今天这个事上了热搜...",
    },
    {
        "id": "product_sell",
        "name": "种草带货型",
        "icon": "shopping-bag",
        "category": "电商",
        "desc": "痛点引入+产品展示+使用场景+促单",
        "structure": "痛点引入（用户困境）→ 产品展示（解决什么问题）→ 使用场景（怎么用）→ 限时优惠+促单",
        "example": "你是不是也遇到过这个问题？",
    },
]


class EnlyAI:
    """EnlyAI 应用主入口"""

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

        # Wav2Lip 服务生命周期管理（provider=wav2lip 时后台拉起常驻服务）
        self._wav2lip_service = None
        self._wav2lip_thread: Optional[threading.Thread] = None
        self._start_wav2lip_service_in_background()
        atexit.register(self._shutdown_wav2lip_service)

        self.logger.info(
            f"EnlyAI 初始化完成 "
            f"gpu_available={self.gpu.is_gpu_available()} "
            f"llm_mock={self.llm.is_mock}"
        )

    def _start_wav2lip_service_in_background(self) -> None:
        """后台启动 Wav2Lip 常驻服务（仅 provider=wav2lip 时）

        将模型加载从"首次提交 job 时"提前到"应用启动时"，避免用户等待。
        后台线程执行，不阻塞主线程；失败时记录日志，不影响应用启动。
        首次调用 generate() 时会再次 ensure_running() 兜底。
        """
        provider = self.config.get("avatar.provider", "mock")
        if provider != "wav2lip":
            return

        def _start():
            try:
                from .core.wav2lip_service import Wav2LipService
                service = Wav2LipService.get_instance()
                self._wav2lip_service = service
                if service.is_healthy():
                    self.logger.info(
                        "wav2lip_server 已在运行（外部启动），复用，不接管生命周期"
                    )
                    return
                self.logger.info("后台启动 wav2lip_server（模型加载约 7-60s）...")
                ok = service.start()
                if ok:
                    status = service.get_status()
                    self.logger.info(
                        f"wav2lip_server 已就绪 device={status.get('device')} "
                        f"face_batch={status.get('face_det_batch')} "
                        f"wav2lip_batch={status.get('wav2lip_batch')}"
                    )
                else:
                    self.logger.warning(
                        "wav2lip_server 启动失败，首次调用 generate 时会重试"
                    )
            except Exception as e:
                self.logger.error(f"启动 wav2lip_server 异常: {e}")

        self._wav2lip_thread = threading.Thread(
            target=_start, daemon=True, name="wav2lip-service"
        )
        self._wav2lip_thread.start()

    def _shutdown_wav2lip_service(self) -> None:
        """停止 Wav2Lip 服务（进程退出时调用）"""
        if self._wav2lip_service is None:
            return
        try:
            self._wav2lip_service.stop()
            self.logger.info("wav2lip_server 已停止")
        except Exception as e:
            self.logger.error(f"停止 wav2lip_server 异常: {e}")

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
            # 注意：audio/effects/scene 段影响 video_composer 的 BGM/滤镜/水印/片头片尾，必须包含
            if any(k in change for k in ("llm", "tts", "avatar", "asr", "composer",
                                          "cover", "publisher", "pipeline", "originality",
                                          "audio", "effects", "scene", "subtitle")) or "_reset_all" in change:
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
            "originality_check": OriginalityChecker(llm_client=llm),
            "tts": TTSEngine(gpu_runner=gpu),
            "avatar": AvatarEngine(gpu_runner=gpu, ffmpeg=ff),
            "subtitle": SubtitleEngine(),
            "broll": BRollEngine(ffmpeg=ff),
            "compose": VideoComposer(ffmpeg=ff),
            "title": TitleGenerator(llm_client=llm),
            "cover": CoverGenerator(ffmpeg=ff),
            "publish": Publisher(),
            "podcast": PodcastEngine(config=self.config, tts_engine=TTSEngine(gpu_runner=gpu), llm_client=llm),
        }

        for name, module in self.modules.items():
            self.orchestrator.register_step(StepDef(
                name=name,
                module=module,
                skip_when=self._make_skip_condition(name),
                optional=name in ("title", "cover", "publish", "script_extract", "broll", "originality_check"),
            ))

    def _make_skip_condition(self, step_name: str):
        """为各步骤生成跳过条件"""
        def skip_no_ref_url(ctx):
            return step_name == "script_extract" and not ctx.reference_video_url
        def skip_publish_disabled(ctx):
            return step_name == "publish" and not ctx.metadata.get("auto_publish")
        def skip_no_broll(ctx):
            return step_name == "broll" and not ctx.broll_clips
        def skip_originality_disabled(ctx):
            return step_name == "originality_check" and not (
                self.config.get("originality.enabled", True)
            )
        if step_name == "script_extract":
            return skip_no_ref_url
        if step_name == "publish":
            return skip_publish_disabled
        if step_name == "broll":
            return skip_no_broll
        if step_name == "originality_check":
            return skip_originality_disabled
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
        # avatar_id 为 "default" 时，从配置读取 default_id（如 e2e_anchor）
        if avatar_id == "default":
            avatar_id = self.config.get("avatar.default_avatar", "default")
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

    def check_originality(self, text: str) -> dict:
        """轻量级原创检测（直接调 checker.run，不经过 run_single_module，不重复跑 script_write）

        避免 run_single_module 先执行 script_write（额外一次 LLM 调用，易触发限流）。

        Args:
            text: 待检测文案

        Returns:
            {"success": bool, "data": dict, "error": str|None}
            data 含：char_count, simhash, status；失败时含 duplicate/banned_words/llm_risk
        """
        if not text or not text.strip():
            return {"success": False, "data": {}, "error": "无文案可检测"}
        try:
            checker = self.modules.get("originality_check")
            if checker is None:
                return {"success": False, "data": {}, "error": "原创检测模块未初始化"}
            # 构造最小 JobContext，仅传 script_text
            from .core.base_module import JobContext
            ctx = JobContext(input_script=text, script_text=text)
            ctx.metadata["script_mode"] = "polish"
            result = checker.execute(ctx)
            return {
                "success": result.success,
                "data": result.data,
                "error": result.error,
            }
        except Exception as e:
            return {"success": False, "data": {}, "error": str(e)}

    def preview_tts(self, text: str, voice_id: str = "default",
                    speed: Optional[float] = None, volume: Optional[int] = None,
                    pitch: Optional[int] = None, emotion: Optional[str] = None) -> dict:
        """试听/预览合成（provider 无关，不经过流水线，供 UI 试听按钮调用）

        Args:
            text: 要试听的文案片段
            voice_id: 音色 ID（default 或已注册音色）
            speed: 语速倍率（0.5-2.0），None 用引擎默认
            volume: 音量百分比（0-200），None 用引擎默认
            pitch: 音高半音（-12 到 +12），None 用引擎默认
            emotion: 情感标签，None 用引擎默认

        Returns:
            {"success": bool, "audio_path": str|None, "duration": float, "error": str|None}
            音频落到 output/voice_preview_{ts}.wav，可直接交给 gradio.Audio 播放。
        """
        import time as _time
        if not text or not text.strip():
            return {"success": False, "audio_path": None, "duration": 0.0,
                    "error": "无文案可试听"}
        try:
            engine = self.modules.get("tts")
            if engine is None:
                return {"success": False, "audio_path": None, "duration": 0.0,
                        "error": "TTS 引擎未初始化"}
            persist = Path("workspace_data/tmp") / f"voice_preview_{int(_time.time())}.wav"
            persist.parent.mkdir(parents=True, exist_ok=True)
            audio_path, duration, _ = engine.synthesize(
                text, voice_id, persist,
                speed=speed, volume=volume, pitch=pitch, emotion=emotion,
            )
            # synthesize 可能输出到 persist，也可能输出到别处（如 moss 的 16k 转换）
            final = str(audio_path) if audio_path.exists() else str(persist)
            if Path(final) != persist and persist.exists():
                persist.unlink(missing_ok=True)
            return {"success": True, "audio_path": final,
                    "duration": round(float(duration), 2), "error": None}
        except Exception as e:
            return {"success": False, "audio_path": None, "duration": 0.0,
                    "error": str(e)}

    def get_job(self, job_id: str) -> Optional[dict]:
        return self.orchestrator.get_status(job_id)

    def list_jobs(self, limit: int = 50) -> list[dict]:
        return self.orchestrator.list_jobs(limit)

    def rerun_job(self, job_id: str) -> bool:
        """重跑任务（断点续跑）"""
        return self.orchestrator.run_job(job_id)

    # ============ 批量处理 ============

    def submit_and_run_batch(
        self,
        jobs: list[dict],
        max_workers: int | None = None,
        progress_callback: Any = None,
    ) -> dict:
        """批量并发执行多个任务

        Args:
            jobs: 任务参数列表，每个元素是 submit_and_run 的 kwargs 字典
            max_workers: 最大并发数（None 读配置 pipeline.concurrency；
                         GPU 模式自动降为 1）
            progress_callback: 进度回调 (index, status, data)

        Returns:
            {"results": [...], "summary": {...}}
        """
        from .pipeline.parallel_runner import ParallelRunner
        runner = ParallelRunner(self, max_workers=max_workers)
        results = runner.run_batch(jobs, progress_callback=progress_callback)
        summary = runner.run_batch_summary(results)
        return {
            "results": [
                {
                    "index": r.index,
                    "job_id": r.job_id,
                    "success": r.success,
                    "elapsed": r.elapsed,
                    "error": r.error,
                }
                for r in results
            ],
            "summary": summary,
        }

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
        """列出所有可用音色（根据当前 tts.provider 返回对应音色库）

        - edge_tts: 返回 avatar_voice_library.yaml 中的 10 个预制音色
        - moss_nano: 返回 MOSS 内置音色（Junhao/Trump/Ava/Bella/Adam/Nathan）+ 已注册克隆音色
        - 其他 provider: 返回默认音色 + 克隆音色
        """
        voices_dir = Path(self.config.get("tts.voices_dir", "./config/voices"))
        result = []
        seen_ids = set()
        provider = self.config.get("tts.provider", "edge_tts")

        if provider == "edge_tts":
            # edge_tts: 从 avatar_voice_library.yaml 加载 10 个预制音色
            preset_file = Path("./config/presets/avatar_voice_library.yaml")
            if preset_file.exists():
                try:
                    import yaml
                    with open(preset_file, "r", encoding="utf-8") as f:
                        data = yaml.safe_load(f) or {}
                    for vid, info in (data.get("voices", {}) or {}).items():
                        if vid in seen_ids:
                            continue
                        result.append({
                            "voice_id": vid,
                            "label": info.get("label", vid),
                            "gender": info.get("gender", ""),
                            "description": info.get("description", ""),
                            "type": "preset",
                            "provider": "edge_tts",
                            "supports_emotion": True,  # edge_tts 支持 emotion 映射
                        })
                        seen_ids.add(vid)
                except Exception:
                    pass
            # edge_tts 默认音色兜底
            default_voice = self.config.get("tts.edge_voice", "zh-CN-XiaoxiaoNeural")
            if default_voice and default_voice not in seen_ids:
                result.append({
                    "voice_id": default_voice,
                    "label": default_voice,
                    "type": "provider_default",
                    "provider": "edge_tts",
                    "supports_emotion": True,
                })
                seen_ids.add(default_voice)

        elif provider == "moss_nano":
            # MOSS-TTS-Nano: 内置 6 个音色（Junhao/Trump/Ava/Bella/Adam/Nathan）
            moss_builtin = {
                "Junhao":  {"label": "君浩（男·中文）",  "gender": "male",   "description": "沉稳男声，适合新闻播报"},
                "Trump":   {"label": "特朗普（男·英文）","gender": "male",   "description": "英文男声，适合外语内容"},
                "Ava":     {"label": "Ava（女·英文）",    "gender": "female", "description": "英文女声，自然流畅"},
                "Bella":   {"label": "Bella（女·中文）",  "gender": "female", "description": "温柔女声，适合情感内容"},
                "Adam":    {"label": "Adam（男·英文）",   "gender": "male",   "description": "英文男声，沉稳专业"},
                "Nathan":  {"label": "Nathan（男·英文）", "gender": "male",   "description": "英文男声，浑厚有力"},
            }
            builtin_voice = self.config.get("tts.moss_nano.builtin_voice", "Junhao")
            for vid, info in moss_builtin.items():
                if vid in seen_ids:
                    continue
                result.append({
                    "voice_id": vid,
                    "label": info["label"],
                    "gender": info["gender"],
                    "description": info["description"],
                    "type": "preset" if vid == builtin_voice else "preset",
                    "provider": "moss_nano",
                    "supports_emotion": False,  # MOSS NANO 暂不支持 emotion 映射
                })
                seen_ids.add(vid)

        else:
            # 其他 provider（mimo/gpt_sovits/mock）：返回默认音色
            default_voice = self.config.get("tts.default_voice", "zh-CN-XiaoxiaoNeural")
            if default_voice:
                result.append({
                    "voice_id": default_voice,
                    "label": default_voice,
                    "type": "provider_default",
                    "provider": provider,
                    "supports_emotion": False,
                })
                seen_ids.add(default_voice)

        # 已注册的自定义克隆音色（所有 provider 通用，moss_nano 用做零样本克隆参考）
        if voices_dir.exists():
            for d in sorted(voices_dir.iterdir()):
                if not d.is_dir():
                    continue
                if d.name in seen_ids:
                    continue
                # 排除预生成试听样本目录（不是音色）
                if d.name == "samples":
                    continue
                info = {
                    "voice_id": d.name,
                    "label": d.name + "（克隆）",
                    "type": "custom",
                    "provider": provider,
                    "supports_emotion": provider == "edge_tts",
                }
                for ext in (".wav", ".mp3", ".flac", ".m4a"):
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

    def delete_avatar(self, avatar_id: str) -> bool:
        """删除已注册的数字人形象（不允许删除 default 形象）"""
        if avatar_id == "default":
            return False
        avatars_dir = Path(self.config.get("avatar.avatars_dir", "./config/avatars"))
        target = avatars_dir / avatar_id
        if not target.exists() or not target.is_dir():
            return False
        # 安全检查：确保 target 在 avatars_dir 内（防止路径穿越）
        try:
            target.resolve().relative_to(avatars_dir.resolve())
        except ValueError:
            return False
        shutil.rmtree(target)
        self.logger.info(f"已删除形象: {avatar_id}")
        return True

    def delete_voice(self, voice_id: str) -> bool:
        """删除已注册的克隆音色（预制音色在 yaml 中，不在 voices_dir 目录，天然不会被误删）"""
        voices_dir = Path(self.config.get("tts.voices_dir", "./config/voices"))
        target = voices_dir / voice_id
        if not target.exists() or not target.is_dir():
            return False
        # 安全检查：确保 target 在 voices_dir 内
        try:
            target.resolve().relative_to(voices_dir.resolve())
        except ValueError:
            return False
        shutil.rmtree(target)
        self.logger.info(f"已删除音色: {voice_id}")
        return True

    # ============ 语音博客 ============

    def get_podcast_engine(self) -> PodcastEngine:
        """获取播客引擎实例（懒加载 TTS/LLM）"""
        engine = self.modules.get("podcast")
        if engine is None:
            engine = PodcastEngine(
                config=self.config,
                tts_engine=TTSEngine(gpu_runner=self.gpu, config=self.config),
                llm_client=self.llm,
            )
            self.modules["podcast"] = engine
        return engine

    def podcast_rewrite(
        self,
        content: str,
        mode: str = "rewrite",
        role_count: int = 3,
        style: str = "轻松对话",
        duration_minutes: int = 5,
        role_desc: str = "",
    ) -> str:
        """AI 将内容/主题改写为播客剧本"""
        engine = self.get_podcast_engine()
        return engine.rewrite_script(
            content=content,
            mode=mode,
            role_count=role_count,
            style=style,
            duration_minutes=duration_minutes,
            role_desc=role_desc,
        )

    def podcast_suggest_voices(self, script_text: str) -> dict:
        """根据剧本自动建议音色分配"""
        engine = self.get_podcast_engine()
        return engine.suggest_voice_map(script_text)

    def podcast_generate(
        self,
        script_text: str,
        voice_map: dict[str, str],
        output_name: str = "",
        progress_callback: Optional[Callable[[str, str, dict], None]] = None,
    ) -> dict:
        """生成播客音频（同步）

        Returns:
            含 audio_path/srt_path/timestamps_path/script_path/total_duration 等
        """
        engine = self.get_podcast_engine()

        # 输出目录：放在 workspace_data/podcasts 下，供 /api/files 访问（安全检查仅允许 workspace_data）
        output_root = Path(self.config.get("project.work_root", "./workspace_data")) / "podcasts"
        output_root.mkdir(parents=True, exist_ok=True)
        if not output_name:
            output_name = f"podcast_{time.strftime('%Y%m%d_%H%M%S')}"
        output_dir = output_root / output_name

        def _progress(current, total, message):
            if progress_callback:
                progress_callback("podcast", "running", {
                    "current": current,
                    "total": total,
                    "message": message,
                })

        result = engine.generate(
            script_text=script_text,
            voice_map=voice_map,
            output_dir=output_dir,
            progress_callback=_progress,
        )
        result["output_dir"] = str(output_dir)
        return result

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
        reference_url: Optional[str] = None,
        template_id: Optional[str] = None,
    ) -> dict:
        """AI 文案处理（独立于流水线，供文案工作台调用）

        Args:
            script: 原始文案（generate 模式下可为空）
            action: polish/rewrite/expand/shorten/style/generate/extract
            style: 风格转换时的目标风格（幽默/严肃/活泼/专业/口语化/煽情）
            topic: generate 模式下的主题
            reference_url: extract 模式下的参考视频链接
            template_id: generate 模式下可选，使用爆款模板库中的结构生成

        Returns:
            {"success": bool, "script": str, "action": str, "error": str}
        """
        # 文案提取：从参考视频/文章链接提取文案
        if action == "extract":
            if not reference_url:
                return {"success": False, "error": "请输入参考视频链接"}
            try:
                extractor = self.modules.get("script_extract")
                if not extractor:
                    return {"success": False, "error": "文案提取模块未初始化"}
                # 确保 setup() 已执行（检测 yt-dlp / ASR 配置）
                if extractor._ytdlp_available is None:
                    extractor.setup()
                text = extractor.extract(reference_url)
                # 判断是否为 mock：文章提取是真实的，视频提取在 mock 模式下才返回模板文案
                clean_url = extractor._extract_url_from_text(reference_url)
                is_video = extractor._is_video_url(clean_url) if clean_url else False
                is_mock = is_video and (extractor.asr_provider == "mock" or not extractor._ytdlp_available)
                return {
                    "success": True,
                    "script": text,
                    "action": "extract",
                    "char_count": len(text),
                    "mock": is_mock,
                    "degraded": getattr(extractor, "_last_extract_degraded", False),
                    "source_type": "video" if is_video else "article",
                }
            except Exception as e:
                return {"success": False, "error": str(e), "action": "extract"}

        # 爆款结构分析：拆解文案的钩子/情绪/结构/亮点
        if action == "analyze":
            if not script:
                return {"success": False, "error": "请输入待分析的文案"}
            try:
                writer = self.modules.get("script_write")
                if not writer:
                    return {"success": False, "error": "文案模块未初始化"}
                report = writer.analyze(script)
                return {
                    "success": True,
                    "action": "analyze",
                    "report": report,
                    "mock": self.llm.is_mock,
                }
            except Exception as e:
                return {"success": False, "error": str(e), "action": "analyze"}

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
            "smooth": "请对以下口播文案进行文本顺滑处理：去除'嗯'、'啊'、'那个'、'就是'、'然后'等口语冗余词和重复表达，修正语病，使语句更流畅自然，但保持口语化风格和原意不变。直接输出文案，不要解释。\n\n原始文案：\n{input}",
            "hook": "请为以下口播文案重新设计开场钩子（前3秒），用疑问、反差、数字或痛点抓住注意力，保持主体内容不变。直接输出完整文案，不要解释。\n\n原始文案：\n{input}",
        }

        if action not in action_map:
            return {"success": False, "error": f"不支持的操作: {action}"}

        if action == "generate":
            input_text = topic or script or "短视频运营技巧"
            # 模板生成：使用爆款模板的结构和示例指导 LLM 生成
            if template_id:
                tpl = next((t for t in SCRIPT_TEMPLATES if t["id"] == template_id), None)
                if not tpl:
                    return {"success": False, "error": f"未知模板: {template_id}", "action": action}
                user_prompt = (
                    f"请严格按以下爆款结构创作口播文案：\n"
                    f"【结构】{tpl['structure']}\n"
                    f"【参考示例】{tpl['example']}\n\n"
                    f"【主题/要求】{input_text}\n\n"
                    f"要求：严格遵循上述结构，开场钩子3秒内抓住注意力，"
                    f"口语化、短句为主、150-300字，直接输出文案，不要解释。"
                )
            else:
                user_prompt = action_map[action].format(input=input_text, style=style or "")
        elif action == "style":
            if not style:
                return {"success": False, "error": "style 模式需要指定 style 参数"}
            input_text = script
            user_prompt = action_map[action].format(input=input_text, style=style or "")
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
                "template_id": template_id,
                "char_count": len(result),
                "mock": self.llm.is_mock,
            }
        except Exception as e:
            return {"success": False, "error": str(e), "action": action}
