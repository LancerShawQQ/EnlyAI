"""存储与路径管理"""
from __future__ import annotations

import shutil
from pathlib import Path

from .config import get_config


class Storage:
    """统一管理任务工作目录与产物路径"""

    def __init__(self, work_root: str | Path | None = None):
        cfg = get_config()
        self.work_root = Path(work_root or cfg.get("project.work_root"))
        self.temp_root = Path(cfg.get("project.temp_root"))
        self.work_root.mkdir(parents=True, exist_ok=True)
        self.temp_root.mkdir(parents=True, exist_ok=True)

    def job_dir(self, job_id: str) -> Path:
        """获取任务工作目录"""
        d = self.work_root / "jobs" / job_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def temp_file(self, name: str) -> Path:
        """获取临时文件路径"""
        return self.temp_root / name

    def cleanup_job(self, job_id: str, keep_final: bool = True) -> None:
        """清理任务目录"""
        d = self.work_root / "jobs" / job_id
        if not d.exists():
            return
        if keep_final:
            # 保留 final 目录
            final_dir = self.work_root / "final" / job_id
            final_dir.mkdir(parents=True, exist_ok=True)
            for f in d.glob("final_*"):
                shutil.copy2(f, final_dir / f.name)
        shutil.rmtree(d, ignore_errors=True)

    def list_jobs(self) -> list[str]:
        """列出所有任务 ID"""
        jobs_dir = self.work_root / "jobs"
        if not jobs_dir.exists():
            return []
        return sorted([d.name for d in jobs_dir.iterdir() if d.is_dir()])
