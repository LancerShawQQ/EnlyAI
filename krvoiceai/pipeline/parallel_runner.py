"""并发批处理执行器

用于批量生成口播视频时并发执行多个 job。

设计要点：
- CPU 模块（文案/字幕/合成/查重）IO 密集 + 子进程调用，并发收益明显
- GPU 模块（TTS/数字人）仍串行：单 GPU 不能并行推理，否则 OOM
- 使用 ThreadPoolExecutor（而非多进程）：子进程(ffmpeg)天然绕过 GIL，
  且模块间通过 SQLite 共享状态，线程更简单
- 错误隔离：单个 job 失败不影响其他 job

用法：
    runner = ParallelRunner(app, max_workers=3)
    results = runner.run_batch([
        {"script": "文案1", "avatar_id": "alice"},
        {"script": "文案2", "avatar_id": "bob"},
    ])
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from ..core.logger import get_logger


@dataclass
class BatchResult:
    """单个 job 的批处理结果"""
    index: int                       # 在输入列表中的序号
    job_id: Optional[str] = None
    success: bool = False
    elapsed: float = 0.0
    error: Optional[str] = None
    result: dict = field(default_factory=dict)


class ParallelRunner:
    """并发批处理执行器"""

    def __init__(
        self,
        app,  # EnlyAI 实例（避免循环 import 用鸭子类型）
        max_workers: Optional[int] = None,
    ):
        """
        Args:
            app: EnlyAI 应用实例
            max_workers: 最大并发数。None 表示从配置读取 pipeline.concurrency，
                         默认 min(4, CPU 核数)。GPU 任务会强制串行（=1）。
        """
        self.app = app
        self.logger = get_logger().bind(component="parallel_runner")
        cfg = app.config
        if max_workers is None:
            max_workers = cfg.get("pipeline.concurrency", 1)
        # GPU 模式下强制串行（单 GPU 不能并发推理）
        gpu_enabled = cfg.get("pipeline.gpu_enabled", False)
        if gpu_enabled and max_workers > 1:
            self.logger.warning(
                f"GPU 模式启用，并发数从 {max_workers} 降为 1（单 GPU 不可并行推理）"
            )
            max_workers = 1
        self.max_workers = max(1, int(max_workers))
        self.logger.info(f"并发批处理初始化 max_workers={self.max_workers}")

    def run_batch(
        self,
        jobs: list[dict],
        progress_callback: Optional[Callable[[int, str, dict], None]] = None,
    ) -> list[BatchResult]:
        """并发执行多个 job

        Args:
            jobs: 任务参数列表，每个元素是传给 app.submit_and_run 的 kwargs
                  （不含 progress_callback，由本方法内部统一管理）
            progress_callback: 进度回调 (index, status, data)
                status: "started" / "success" / "failed"

        Returns:
            按输入顺序排列的 BatchResult 列表
        """
        if not jobs:
            return []

        results: dict[int, BatchResult] = {}
        total = len(jobs)

        # 单任务直接同步执行，避免线程开销
        if self.max_workers == 1 or total == 1:
            for i, job_kwargs in enumerate(jobs):
                if progress_callback:
                    progress_callback(i, "started", {"total": total})
                r = self._run_single(i, job_kwargs)
                results[i] = r
                if progress_callback:
                    progress_callback(
                        i,
                        "success" if r.success else "failed",
                        {"error": r.error},
                    )
            return [results[i] for i in range(total)]

        # 多任务并发
        self.logger.info(f"批量执行 {total} 个任务，并发={self.max_workers}")
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_to_index = {}
            for i, job_kwargs in enumerate(jobs):
                if progress_callback:
                    progress_callback(i, "started", {"total": total})
                fut = pool.submit(self._run_single, i, job_kwargs)
                future_to_index[fut] = i

            for fut in as_completed(future_to_index):
                i = future_to_index[fut]
                try:
                    r = fut.result()
                except Exception as e:
                    r = BatchResult(index=i, success=False, error=str(e))
                results[i] = r
                if progress_callback:
                    progress_callback(
                        i,
                        "success" if r.success else "failed",
                        {"error": r.error},
                    )
                done = sum(1 for x in results.values() if x.success or x.error)
                self.logger.info(
                    f"批处理进度: {done}/{total} "
                    f"(job#{i} {'成功' if r.success else '失败'})"
                )

        return [results[i] for i in range(total)]

    def _run_single(self, index: int, kwargs: dict) -> BatchResult:
        """执行单个 job（线程池 worker 调用）

        注意：EnlyAI 内部的 orchestrator / JobStore 每次调用都创建
        新的 SQLite 连接，线程安全。共享的 self.app 只用于读配置。
        """
        start = time.time()
        try:
            result = self.app.submit_and_run(**kwargs)
            return BatchResult(
                index=index,
                job_id=result.get("job_id"),
                success=bool(result.get("success")),
                elapsed=result.get("elapsed", time.time() - start),
                result=result,
                error=result.get("error"),
            )
        except Exception as e:
            self.logger.error(f"job#{index} 执行异常: {e}")
            return BatchResult(
                index=index,
                success=False,
                elapsed=time.time() - start,
                error=f"{type(e).__name__}: {e}",
            )

    def run_batch_summary(self, results: list[BatchResult]) -> dict:
        """生成批处理汇总报告"""
        total = len(results)
        success = sum(1 for r in results if r.success)
        failed = total - success
        total_elapsed = sum(r.elapsed for r in results)
        return {
            "total": total,
            "success": success,
            "failed": failed,
            "total_elapsed": round(total_elapsed, 2),
            "avg_elapsed": round(total_elapsed / total, 2) if total else 0,
            "success_rate": round(success / total, 4) if total else 0,
            "errors": [
                {"index": r.index, "error": r.error}
                for r in results if not r.success
            ],
        }
