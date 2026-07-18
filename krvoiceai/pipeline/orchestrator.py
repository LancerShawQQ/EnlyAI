"""流水线编排器

串联所有模块，管理任务状态、重试、断点续跑。

核心闭环步骤：
  script_write → tts → avatar → subtitle → compose

扩展步骤（P2-P4）：
  script_extract → script_write → tts → avatar → subtitle → compose
  → title → cover → publish
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from ..core.base_module import BaseModule, JobContext, ModuleResult
from ..core.config import get_config
from ..core.logger import get_logger
from ..core.storage import Storage
from .state import (
    JobStatus,
    JobStore,
    StepStatus,
    PIPELINE_STEPS,
)


@dataclass
class StepDef:
    """步骤定义"""
    name: str
    module: BaseModule
    # 是否跳过该步骤的条件（返回 True 则跳过）
    skip_when: Optional[Callable[[JobContext], bool]] = None
    # 步骤是否可选（可选步骤失败不阻断流程）
    optional: bool = False


class PipelineOrchestrator:
    """流水线编排器"""

    def __init__(
        self,
        job_store: JobStore | None = None,
        storage: Storage | None = None,
    ):
        self.config = get_config()
        self.logger = get_logger().bind(component="orchestrator")
        self.store = job_store or JobStore()
        self.storage = storage or Storage()
        self.max_retries = self.config.get("pipeline.max_retries", 3)
        self.retry_backoff = self.config.get("pipeline.retry_backoff", 5)
        self._steps: dict[str, StepDef] = {}
        # 保护 _save_context 的文件写入，避免 avatar∥subtitle 并行时并发写 context.json
        self._save_context_lock = threading.Lock()

    def register_step(self, step: StepDef) -> None:
        """注册步骤"""
        self._steps[step.name] = step
        self.logger.debug(f"注册步骤: {step.name}")

    def register_core_pipeline(self, modules: dict[str, BaseModule]) -> None:
        """注册核心闭环步骤

        Args:
            modules: 包含 script_write/tts/avatar/subtitle/compose 的模块字典
        """
        step_order = ["script_write", "tts", "avatar", "subtitle", "compose"]
        for name in step_order:
            if name in modules:
                self.register_step(StepDef(
                    name=name,
                    module=modules[name],
                ))

    def submit_job(
        self,
        script: str = "",
        reference_video_url: Optional[str] = None,
        avatar_id: str = "default",
        voice_id: str = "default",
        script_mode: str = "polish",
        metadata: Optional[dict] = None,
        broll_clips: Optional[list] = None,
    ) -> str:
        """提交任务，返回 job_id"""
        job_id = self._gen_job_id()
        work_dir = self.storage.job_dir(job_id)

        input_data = {
            "script": script,
            "reference_video_url": reference_video_url,
            "avatar_id": avatar_id,
            "voice_id": voice_id,
            "script_mode": script_mode,
            "work_dir": str(work_dir),
            "metadata": metadata or {},
            "broll_clips": broll_clips or [],
        }
        self.store.create_job(job_id, input_data)
        self.logger.info(f"任务已提交 job_id={job_id}")
        return job_id

    def cleanup_stale_jobs(self) -> int:
        """清理服务重启前卡在 running/pending 状态的任务

        服务异常退出时，正在执行的任务（Wav2Lip 子进程等）会被杀死，
        但数据库中状态仍为 running/pending。这些任务无法自动恢复，
        需标记为 failed 并提示用户重跑。

        Returns:
            清理的任务数量
        """
        cleaned = 0
        try:
            jobs = self.store.list_jobs(limit=200)
            for job_summary in jobs:
                status = job_summary.get("status")
                if status in ("running", "pending"):
                    job_id = job_summary.get("job_id")
                    # 获取完整任务信息（含 steps）
                    job = self.store.get_job(job_id)
                    self.store.update_job_status(
                        job_id, JobStatus.FAILED,
                        error="服务重启导致任务中断，请点击\"重跑\"恢复（支持断点续跑）",
                    )
                    # 标记当前 running 步骤为 failed
                    if job and job.get("steps"):
                        for s in job["steps"]:
                            if s.get("status") == "running":
                                self.store.update_step(
                                    job_id, s["step"], StepStatus.FAILED,
                                    error="服务重启中断",
                                )
                                break
                    cleaned += 1
                    self.logger.warning(f"清理卡住任务: {job_id} (原状态={status})")
        except Exception as e:
            self.logger.error(f"cleanup_stale_jobs 异常: {e}")
        if cleaned:
            self.logger.info(f"共清理 {cleaned} 个卡住的任务")
        return cleaned

    def run_job(
        self, job_id: str,
        progress_callback: Optional[Callable[[str, str, dict], None]] = None,
    ) -> bool:
        """运行任务（支持断点续跑）

        Args:
            job_id: 任务 ID
            progress_callback: 进度回调 (step_name, status, data)

        Returns:
            True 表示任务成功完成
        """
        job = self.store.get_job(job_id)
        if not job:
            self.logger.error(f"任务不存在: {job_id}")
            return False

        self.store.update_job_status(job_id, JobStatus.RUNNING)
        ctx = self._build_context(job_id, job["input"])

        # 确定起始步骤（断点续跑）
        start_step = self._find_resume_point(job_id)
        self.logger.info(
            f"开始执行任务 job={job_id} 从步骤 {start_step or '开头'} 开始"
        )

        # 记录已通过并行方式执行过的步骤，避免 for 循环重复执行
        executed_steps: set[str] = set()

        for step_name in PIPELINE_STEPS:
            if start_step:
                if step_name == start_step:
                    start_step = None  # 找到起点，开始执行
                else:
                    continue  # 跳过已完成步骤

            # 跳过已通过并行方式执行的步骤
            if step_name in executed_steps:
                continue

            step_def = self._steps.get(step_name)
            if step_def is None:
                # 未注册的步骤跳过
                self.store.update_step(
                    job_id, step_name, StepStatus.SKIPPED,
                    result={"reason": "step not registered"},
                )
                if progress_callback:
                    progress_callback(step_name, "skipped", {})
                continue

            # 检查跳过条件
            if step_def.skip_when and step_def.skip_when(ctx):
                self.logger.info(f"步骤 {step_name} 被跳过")
                self.store.update_step(
                    job_id, step_name, StepStatus.SKIPPED,
                    result={"reason": "skip condition met"},
                )
                if progress_callback:
                    progress_callback(step_name, "skipped", {})
                continue

            # 并行优化：avatar 和 subtitle 都只依赖 tts 输出，无相互依赖
            # 并行执行可节省较短步骤（通常是 subtitle）的耗时
            if step_name == "avatar":
                subtitle_def = self._steps.get("subtitle")
                can_parallel_subtitle = (
                    subtitle_def is not None
                    and "subtitle" not in executed_steps
                    and not (subtitle_def.skip_when and subtitle_def.skip_when(ctx))
                )
                if can_parallel_subtitle:
                    self.logger.info("avatar 与 subtitle 无依赖，并行执行")
                    if progress_callback:
                        progress_callback("avatar", "running", {})
                        progress_callback("subtitle", "running", {})

                    avatar_ok, subtitle_ok = self._execute_parallel_pair(
                        job_id, step_def, subtitle_def, ctx, progress_callback,
                    )
                    executed_steps.add("avatar")
                    executed_steps.add("subtitle")

                    # avatar 非可选，失败则任务失败
                    if not avatar_ok:
                        self.store.update_job_status(
                            job_id, JobStatus.FAILED,
                            error="步骤 avatar 失败",
                        )
                        self.logger.error(f"任务失败 job={job_id} 于步骤 avatar")
                        return False
                    # subtitle 失败处理（与原顺序逻辑一致）
                    if not subtitle_ok and not subtitle_def.optional:
                        self.store.update_job_status(
                            job_id, JobStatus.FAILED,
                            error="步骤 subtitle 失败",
                        )
                        self.logger.error(f"任务失败 job={job_id} 于步骤 subtitle")
                        return False
                    continue

            # 通知开始
            if progress_callback:
                progress_callback(step_name, "running", {})

            # 执行步骤（带重试）
            success = self._execute_step_with_retry(
                job_id, step_def, ctx, progress_callback,
            )
            if not success:
                if step_def.optional:
                    self.logger.warning(
                        f"可选步骤 {step_name} 失败，继续执行后续步骤"
                    )
                    continue
                self.store.update_job_status(
                    job_id, JobStatus.FAILED,
                    error=f"步骤 {step_name} 失败",
                )
                self.logger.error(f"任务失败 job={job_id} 于步骤 {step_name}")
                return False

        # 全部完成
        output = self._build_output(ctx)
        self.store.update_job_status(
            job_id, JobStatus.SUCCESS, output=output,
        )
        self.logger.info(f"任务成功完成 job={job_id}")
        return True

    def _execute_parallel_pair(
        self, job_id: str, step_def_a: StepDef, step_def_b: StepDef,
        ctx: JobContext, progress_callback: Optional[Callable] = None,
    ) -> tuple[bool, bool]:
        """并行执行两个无依赖的步骤（avatar + subtitle）

        两个步骤都依赖 tts 输出，但相互独立。并行执行可节省较短步骤的耗时。
        线程安全保障：
        - JobStore 已启用 WAL + busy_timeout，支持并发写
        - _save_context 用 threading.Lock 保护，避免并发写 context.json
        - JobContext.metadata 的不同 key 并发写安全（CPython GIL 保护单个 dict 操作）
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        self.logger.info(
            f"并行执行步骤: {step_def_a.name} + {step_def_b.name}"
        )

        results: dict[str, bool] = {}
        with ThreadPoolExecutor(max_workers=2) as pool:
            future_to_name = {
                pool.submit(
                    self._execute_step_with_retry,
                    job_id, step_def_a, ctx, progress_callback,
                ): step_def_a.name,
                pool.submit(
                    self._execute_step_with_retry,
                    job_id, step_def_b, ctx, progress_callback,
                ): step_def_b.name,
            }
            for fut in as_completed(future_to_name):
                name = future_to_name[fut]
                try:
                    results[name] = fut.result()
                except Exception as e:
                    self.logger.error(f"并行步骤 {name} 异常: {e}")
                    results[name] = False

        return (
            results.get(step_def_a.name, False),
            results.get(step_def_b.name, False),
        )

    def _execute_step_with_retry(
        self, job_id: str, step_def: StepDef, ctx: JobContext,
        progress_callback: Optional[Callable] = None,
    ) -> bool:
        """带重试的步骤执行"""
        last_error = None
        for attempt in range(1, self.max_retries + 1):
            self.store.update_step(job_id, step_def.name, StepStatus.RUNNING)
            self.logger.info(
                f"执行步骤 {step_def.name} (尝试 {attempt}/{self.max_retries})"
            )
            start = time.time()
            result = step_def.module.execute(ctx)
            duration = time.time() - start

            if result.success:
                self.store.update_step(
                    job_id, step_def.name, StepStatus.SUCCESS,
                    result=result.data, duration=duration,
                )
                # 持久化中间产物，支持断点续跑
                self._save_context(ctx)
                if progress_callback:
                    progress_callback(step_def.name, "success", result.data)
                return True

            last_error = result.error
            self.logger.warning(
                f"步骤 {step_def.name} 第 {attempt} 次失败: {result.error}"
            )
            if progress_callback:
                progress_callback(step_def.name, "retry", {
                    "attempt": attempt, "error": result.error,
                })
            if attempt < self.max_retries:
                wait = self.retry_backoff * (2 ** (attempt - 1))
                self.logger.info(f"等待 {wait}s 后重试")
                time.sleep(wait)

        self.store.update_step(
            job_id, step_def.name, StepStatus.FAILED,
            error=last_error, duration=0,
        )
        if progress_callback:
            progress_callback(step_def.name, "failed", {"error": last_error})
        return False

    def _find_resume_point(self, job_id: str) -> Optional[str]:
        """找到断点续跑的起始步骤"""
        job = self.store.get_job(job_id)
        if not job:
            return None
        for step in job["steps"]:
            if step["status"] in (StepStatus.PENDING.value, StepStatus.FAILED.value):
                return step["step"]
        return None

    def _build_context(self, job_id: str, input_data: dict) -> JobContext:
        """从输入数据构建任务上下文（支持从中间产物恢复）"""
        work_dir = Path(input_data.get("work_dir") or
                        str(self.storage.job_dir(job_id)))
        ctx = JobContext(
            job_id=job_id,
            work_dir=work_dir,
            input_script=input_data.get("script", ""),
            reference_video_url=input_data.get("reference_video_url"),
            avatar_id=input_data.get("avatar_id", "default"),
            voice_id=input_data.get("voice_id", "default"),
            metadata=input_data.get("metadata", {}),
        )
        ctx.metadata["script_mode"] = input_data.get("script_mode", "polish")
        # B-roll 片段从输入数据传入
        if input_data.get("broll_clips"):
            ctx.broll_clips = input_data["broll_clips"]
        ctx.ensure_work_dir()

        # 尝试从持久化的 context.json 恢复中间产物（断点续跑）
        self._load_context(ctx)
        return ctx

    def _save_context(self, ctx: JobContext) -> None:
        """持久化任务上下文的关键产物（用于断点续跑）

        线程安全：avatar∥subtitle 并行执行时，两个线程都会调用此方法
        写同一个 context.json 文件，用锁保护避免文件损坏。
        """
        import json
        with self._save_context_lock:
            ctx_file = ctx.work_dir / "context.json"
            data = {
                "job_id": ctx.job_id,
                "script_text": ctx.script_text,
                "audio_path": str(ctx.audio_path) if ctx.audio_path else None,
                "audio_duration": ctx.audio_duration,
                "raw_video_path": str(ctx.raw_video_path) if ctx.raw_video_path else None,
                "subtitle_path": str(ctx.subtitle_path) if ctx.subtitle_path else None,
                "bgm_path": str(ctx.bgm_path) if ctx.bgm_path else None,
                "cover_path": str(ctx.cover_path) if ctx.cover_path else None,
                "title": ctx.title,
                "final_video": str(ctx.final_video) if ctx.final_video else None,
                "broll_clips": ctx.broll_clips,
                "broll_video_path": str(ctx.broll_video_path) if ctx.broll_video_path else None,
                "metadata": ctx.metadata,
            }
            ctx_file.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    def _load_context(self, ctx: JobContext) -> None:
        """从持久化文件恢复中间产物

        带完整性校验：损坏的音视频文件会被忽略（视为该步骤未完成），
        让 _find_resume_point 从该步骤重跑，避免用坏文件续跑。
        """
        import json
        ctx_file = ctx.work_dir / "context.json"
        if not ctx_file.exists():
            return
        try:
            data = json.loads(ctx_file.read_text(encoding="utf-8"))
            if data.get("script_text"):
                ctx.script_text = data["script_text"]
            if data.get("audio_path"):
                p = Path(data["audio_path"])
                if self._validate_artifact(p, "audio"):
                    ctx.audio_path = p
                    ctx.audio_duration = data.get("audio_duration", 0)
            if data.get("raw_video_path"):
                p = Path(data["raw_video_path"])
                if self._validate_artifact(p, "video"):
                    ctx.raw_video_path = p
            if data.get("subtitle_path"):
                p = Path(data["subtitle_path"])
                if self._validate_artifact(p, "subtitle"):
                    ctx.subtitle_path = p
            if data.get("bgm_path"):
                p = Path(data["bgm_path"])
                if self._validate_artifact(p, "audio"):
                    ctx.bgm_path = p
            if data.get("cover_path"):
                p = Path(data["cover_path"])
                if self._validate_artifact(p, "image"):
                    ctx.cover_path = p
            if data.get("title"):
                ctx.title = data["title"]
            if data.get("final_video"):
                p = Path(data["final_video"])
                if self._validate_artifact(p, "video"):
                    ctx.final_video = p
            if data.get("broll_clips"):
                ctx.broll_clips = data["broll_clips"]
            if data.get("broll_video_path"):
                p = Path(data["broll_video_path"])
                if self._validate_artifact(p, "video"):
                    ctx.broll_video_path = p
            # 合并 metadata（保留 tts_timestamps 等）
            saved_meta = data.get("metadata", {})
            for k, v in saved_meta.items():
                if k not in ctx.metadata:
                    ctx.metadata[k] = v
            self.logger.debug(f"已从 context.json 恢复中间产物 job={ctx.job_id}")
        except Exception as e:
            self.logger.warning(f"恢复 context 失败: {e}")

    def _validate_artifact(self, path: Path, kind: str) -> bool:
        """校验产物文件完整性

        Args:
            path: 文件路径
            kind: 类型 audio/video/image/subtitle

        Returns:
            True 表示文件可用；False 表示损坏/缺失，应重跑该步骤
        """
        if not path.exists():
            return False
        # 体积过小（<100B）几乎肯定是损坏的空文件
        try:
            if path.stat().st_size < 100:
                self.logger.warning(f"产物文件过小，视为损坏: {path} ({path.stat().st_size}B)")
                return False
        except OSError:
            return False

        if kind == "audio":
            # wav 用 wave 解析；其他格式用 ffprobe
            if path.suffix.lower() == ".wav":
                try:
                    from ..core.audio_utils import get_wav_duration
                    return get_wav_duration(path) > 0.1
                except Exception:
                    return False
            return self._probe_media_duration(path) > 0.1
        elif kind == "video":
            return self._probe_media_duration(path) > 0.1
        elif kind == "image":
            try:
                from PIL import Image
                with Image.open(path) as img:
                    return img.size[0] > 0 and img.size[1] > 0
            except Exception:
                return False
        elif kind == "subtitle":
            # 字幕：非空且含时间轴标记
            try:
                txt = path.read_text(encoding="utf-8")
                return bool(txt.strip())
            except Exception:
                return False
        return True

    def _probe_media_duration(self, path: Path) -> float:
        """用 ffprobe 探测音视频时长（无 ffprobe 返回 0 视为不可用）"""
        try:
            from ..core.ffmpeg_utils import FFmpegRunner
            ff = FFmpegRunner()
            return ff.probe_duration(path)
        except Exception:
            return 0.0

    def _build_output(self, ctx: JobContext) -> dict:
        """构建任务输出信息"""
        return {
            "final_video": str(ctx.final_video) if ctx.final_video else None,
            "script_text": ctx.script_text,
            "audio_path": str(ctx.audio_path) if ctx.audio_path else None,
            "audio_duration": ctx.audio_duration,
            "raw_video": str(ctx.raw_video_path) if ctx.raw_video_path else None,
            "subtitle": str(ctx.subtitle_path) if ctx.subtitle_path else None,
            "title": ctx.title,
            "cover": str(ctx.cover_path) if ctx.cover_path else None,
        }

    def get_status(self, job_id: str) -> Optional[dict]:
        """查询任务状态"""
        return self.store.get_job(job_id)

    def list_jobs(self, limit: int = 50) -> list[dict]:
        """列出任务"""
        return self.store.list_jobs(limit)

    def _gen_job_id(self) -> str:
        import uuid
        from datetime import datetime
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        short = uuid.uuid4().hex[:6]
        return f"job_{ts}_{short}"
