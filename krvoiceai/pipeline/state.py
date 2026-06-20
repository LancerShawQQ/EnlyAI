"""任务状态管理"""
from __future__ import annotations

import sqlite3
import json
import time
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from ..core.config import get_config


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class StepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


# 流水线步骤定义（顺序执行）
PIPELINE_STEPS = [
    "script_extract",   # 文案提取（可选）
    "script_write",     # 文案生成/润色
    "tts",              # 语音合成
    "avatar",           # 数字人生成
    "subtitle",         # 字幕生成
    "broll",            # B-roll 画中画/插播视频（可选）
    "compose",          # 视频合成
    "title",            # 标题生成
    "cover",            # 封面生成
    "publish",          # 发布
]


class JobStore:
    """基于 SQLite 的任务状态持久化"""

    def __init__(self, db_path: str | Path | None = None):
        cfg = get_config()
        self.db_path = Path(db_path or cfg.get("pipeline.db_path"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with self._conn() as c:
            c.executescript(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    input_json TEXT,
                    output_json TEXT,
                    error TEXT,
                    created_at REAL,
                    updated_at REAL
                );
                CREATE TABLE IF NOT EXISTS steps (
                    job_id TEXT NOT NULL,
                    step_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at REAL,
                    finished_at REAL,
                    duration REAL,
                    error TEXT,
                    result_json TEXT,
                    PRIMARY KEY (job_id, step_name)
                );
                """
            )

    def _conn(self) -> sqlite3.Connection:
        c = sqlite3.connect(self.db_path)
        c.row_factory = sqlite3.Row
        return c

    def create_job(self, job_id: str, input_data: dict) -> None:
        with self._conn() as c:
            c.execute(
                "INSERT INTO jobs (job_id, status, input_json, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    job_id,
                    JobStatus.PENDING.value,
                    json.dumps(input_data, ensure_ascii=False),
                    time.time(),
                    time.time(),
                ),
            )
            # 初始化所有步骤为 pending
            for step in PIPELINE_STEPS:
                c.execute(
                    "INSERT INTO steps (job_id, step_name, status) VALUES (?, ?, ?)",
                    (job_id, step, StepStatus.PENDING.value),
                )

    def update_job_status(self, job_id: str, status: JobStatus,
                          error: Optional[str] = None,
                          output: Optional[dict] = None) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE jobs SET status=?, error=?, output_json=?, updated_at=? "
                "WHERE job_id=?",
                (
                    status.value,
                    error,
                    json.dumps(output, ensure_ascii=False) if output else None,
                    time.time(),
                    job_id,
                ),
            )

    def update_step(self, job_id: str, step_name: str, status: StepStatus,
                    error: Optional[str] = None,
                    result: Optional[dict] = None,
                    duration: Optional[float] = None) -> None:
        now = time.time()
        with self._conn() as c:
            # 先查现有记录的 started_at
            row = c.execute(
                "SELECT started_at FROM steps WHERE job_id=? AND step_name=?",
                (job_id, step_name),
            ).fetchone()
            started_at = row["started_at"] if row and row["started_at"] else now

            c.execute(
                "UPDATE steps SET status=?, started_at=?, finished_at=?, "
                "duration=?, error=?, result_json=? "
                "WHERE job_id=? AND step_name=?",
                (
                    status.value,
                    started_at,
                    now if status in (StepStatus.SUCCESS, StepStatus.FAILED) else None,
                    duration,
                    error,
                    json.dumps(result, ensure_ascii=False) if result else None,
                    job_id,
                    step_name,
                ),
            )

    def get_job(self, job_id: str) -> Optional[dict[str, Any]]:
        with self._conn() as c:
            job = c.execute(
                "SELECT * FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if not job:
                return None
            steps = c.execute(
                "SELECT * FROM steps WHERE job_id=? ORDER BY rowid", (job_id,)
            ).fetchall()
            return {
                "job_id": job["job_id"],
                "status": job["status"],
                "input": json.loads(job["input_json"]) if job["input_json"] else {},
                "output": json.loads(job["output_json"]) if job["output_json"] else {},
                "error": job["error"],
                "created_at": job["created_at"],
                "updated_at": job["updated_at"],
                "steps": [
                    {
                        "step": s["step_name"],
                        "status": s["status"],
                        "duration": s["duration"],
                        "error": s["error"],
                        "result": json.loads(s["result_json"]) if s["result_json"] else None,
                    }
                    for s in steps
                ],
            }

    def list_jobs(self, limit: int = 50) -> list[dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT job_id, status, created_at, updated_at "
                "FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_job(self, job_id: str) -> bool:
        """删除任务及其步骤记录"""
        with self._conn() as c:
            c.execute("DELETE FROM steps WHERE job_id=?", (job_id,))
            cur = c.execute("DELETE FROM jobs WHERE job_id=?", (job_id,))
            return cur.rowcount > 0

    def get_next_pending_step(self, job_id: str) -> Optional[str]:
        """获取下一个待执行的步骤"""
        with self._conn() as c:
            for step in PIPELINE_STEPS:
                row = c.execute(
                    "SELECT status FROM steps WHERE job_id=? AND step_name=?",
                    (job_id, step),
                ).fetchone()
                if row and row["status"] == StepStatus.PENDING.value:
                    return step
        return None
