"""流水线编排器

串联所有模块，管理任务状态、重试、断点续跑。

核心闭环步骤：
  script_write → tts → avatar → subtitle → compose

扩展步骤（P2-P4）：
  script_extract → script_write → tts → avatar → subtitle → compose
  → title → cover → publish
"""
from __future__ import annotations

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
        }
        self.store.create_job(job_id, input_data)
        self.logger.info(f"任务已提交 job_id={job_id}")
        return job_id

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

        for step_name in PIPELINE_STEPS:
            if start_step:
                if step_name == start_step:
                    start_step = None  # 找到起点，开始执行
                else:
                    continue  # 跳过已完成步骤

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
        ctx.ensure_work_dir()

        # 尝试从持久化的 context.json 恢复中间产物（断点续跑）
        self._load_context(ctx)
        return ctx

    def _save_context(self, ctx: JobContext) -> None:
        """持久化任务上下文的关键产物（用于断点续跑）"""
        import json
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
            "metadata": ctx.metadata,
        }
        ctx_file.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load_context(self, ctx: JobContext) -> None:
        """从持久化文件恢复中间产物"""
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
                if p.exists():
                    ctx.audio_path = p
                    ctx.audio_duration = data.get("audio_duration", 0)
            if data.get("raw_video_path"):
                p = Path(data["raw_video_path"])
                if p.exists():
                    ctx.raw_video_path = p
            if data.get("subtitle_path"):
                p = Path(data["subtitle_path"])
                if p.exists():
                    ctx.subtitle_path = p
            if data.get("bgm_path"):
                ctx.bgm_path = Path(data["bgm_path"])
            if data.get("cover_path"):
                ctx.cover_path = Path(data["cover_path"])
            if data.get("title"):
                ctx.title = data["title"]
            if data.get("final_video"):
                ctx.final_video = Path(data["final_video"])
            # 合并 metadata（保留 tts_timestamps 等）
            saved_meta = data.get("metadata", {})
            for k, v in saved_meta.items():
                if k not in ctx.metadata:
                    ctx.metadata[k] = v
            self.logger.debug(f"已从 context.json 恢复中间产物 job={ctx.job_id}")
        except Exception as e:
            self.logger.warning(f"恢复 context 失败: {e}")

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
