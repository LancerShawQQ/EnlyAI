"""模块基类与数据载体定义"""
from __future__ import annotations

import abc
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from .config import Config, get_config
from .logger import get_logger


class ModuleStatus(str, Enum):
    IDLE = "idle"
    READY = "ready"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"


@dataclass
class ModuleResult:
    """模块执行结果"""
    success: bool
    data: dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    duration: float = 0.0


@dataclass
class JobContext:
    """任务上下文，贯穿整个流水线"""
    job_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    work_dir: Path = field(default_factory=lambda: Path("./workspace_data/jobs/default"))

    # 输入
    input_script: str = ""                # 原始文案
    reference_video_url: Optional[str] = None  # 参考视频 URL（可选）
    avatar_id: str = "default"
    voice_id: str = "default"

    # 中间产物
    script_text: str = ""                 # 处理后文案
    audio_path: Optional[Path] = None     # TTS 合成音频
    audio_duration: float = 0.0
    raw_video_path: Optional[Path] = None # 数字人口播视频
    subtitle_path: Optional[Path] = None  # 字幕文件
    bgm_path: Optional[Path] = None       # BGM
    cover_path: Optional[Path] = None     # 封面
    title: Optional[str] = None           # 标题

    # B-roll 画中画片段（用户在时间轴编辑器中插入的视频/图片片段）
    # 每个片段: {path, start, end, mode(pip/cut), position, scale, volume, transition}
    broll_clips: list = field(default_factory=list)
    broll_video_path: Optional[Path] = None  # 叠加 B-roll 后的视频

    # 最终产物
    final_video: Optional[Path] = None

    # 元数据
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def touch(self) -> None:
        self.updated_at = time.time()

    def ensure_work_dir(self) -> None:
        self.work_dir.mkdir(parents=True, exist_ok=True)


class BaseModule(abc.ABC):
    """所有模块的基类"""

    name: str = "base"
    requires_gpu: bool = False

    def __init__(self, config: Config | None = None):
        self.config = config or get_config()
        self.logger = get_logger().bind(module=self.name)
        self.status: ModuleStatus = ModuleStatus.IDLE

    def setup(self) -> None:
        """初始化模块（子类可覆盖）"""
        self.status = ModuleStatus.READY

    @abc.abstractmethod
    def run(self, ctx: JobContext) -> ModuleResult:
        """执行模块逻辑"""
        ...

    def health_check(self) -> bool:
        """健康检查，默认 True"""
        return True

    def cleanup(self) -> None:
        """清理资源"""
        pass

    def execute(self, ctx: JobContext) -> ModuleResult:
        """带状态管理与计时的执行入口"""
        if self.status == ModuleStatus.IDLE:
            self.setup()
        self.status = ModuleStatus.RUNNING
        self.logger.info(f"模块 {self.name} 开始执行, job={ctx.job_id}")
        start = time.time()
        try:
            result = self.run(ctx)
            result.duration = time.time() - start
            if result.success:
                self.status = ModuleStatus.SUCCESS
                self.logger.info(
                    f"模块 {self.name} 执行成功, 耗时 {result.duration:.2f}s"
                )
            else:
                self.status = ModuleStatus.FAILED
                self.logger.warning(
                    f"模块 {self.name} 执行失败: {result.error}, "
                    f"耗时 {result.duration:.2f}s"
                )
            ctx.touch()
            return result
        except Exception as e:
            duration = time.time() - start
            self.status = ModuleStatus.FAILED
            self.logger.exception(f"模块 {self.name} 执行异常: {e}")
            return ModuleResult(
                success=False,
                error=f"{type(e).__name__}: {e}",
                duration=duration,
            )
