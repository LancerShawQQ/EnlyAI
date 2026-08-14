"""并发批处理执行器测试

设计原则：用 mock 掉耗时的 app.submit_and_run，只验证并发框架本身的行为
（并发数控制、错误隔离、顺序保持、进度回调、GPU 串行约束），
不重复跑完整的 ffmpeg 流水线（那由 test_pipeline_e2e / test_acceptance_e2e 覆盖）。
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from krvoiceai.pipeline.parallel_runner import BatchResult, ParallelRunner


def _make_app_mock(concurrency_cfg=1, gpu_enabled=False):
    """构造一个轻量 app mock（不实例化 EnlyAI，避免初始化开销）"""
    app = MagicMock()
    app.config = MagicMock()
    app.config.get = lambda key, default=None: {
        "pipeline.concurrency": concurrency_cfg,
        "pipeline.gpu_enabled": gpu_enabled,
    }.get(key, default)
    # 默认 submit_and_run 返回成功
    def fake_submit(**kwargs):
        time.sleep(0.05)  # 模拟一点耗时，让并发有意义
        return {"success": True, "job_id": f"job_{time.time()}", "elapsed": 0.05}
    app.submit_and_run = fake_submit
    return app


# ============ 基础功能 ============

def test_batch_serial_single_worker():
    """单 worker 串行执行"""
    app = _make_app_mock(concurrency_cfg=1)
    runner = ParallelRunner(app, max_workers=1)
    assert runner.max_workers == 1

    jobs = [{"script": "A"}, {"script": "B"}]
    results = runner.run_batch(jobs)

    assert len(results) == 2
    assert all(r.success for r in results)
    assert results[0].index == 0
    assert results[1].index == 1


def test_batch_concurrent_multi_worker():
    """多 worker 并发执行，顺序保持"""
    app = _make_app_mock(concurrency_cfg=1)
    runner = ParallelRunner(app, max_workers=3)
    assert runner.max_workers == 3

    jobs = [{"script": f"job_{i}"} for i in range(5)]
    results = runner.run_batch(jobs)

    assert len(results) == 5
    assert all(r.success for r in results)
    # 结果按输入序号排列
    assert [r.index for r in results] == [0, 1, 2, 3, 4]


def test_batch_empty_jobs():
    """空任务列表"""
    app = _make_app_mock()
    runner = ParallelRunner(app, max_workers=2)
    assert runner.run_batch([]) == []


def test_batch_concurrency_reads_config():
    """max_workers=None 时从配置读取"""
    app = _make_app_mock(concurrency_cfg=3)
    runner = ParallelRunner(app)  # 不传 max_workers
    assert runner.max_workers == 3


# ============ GPU 串行约束 ============

def test_batch_gpu_forces_serial():
    """GPU 模式下强制串行（max_workers 降为 1）"""
    app = _make_app_mock(concurrency_cfg=4, gpu_enabled=True)
    runner = ParallelRunner(app, max_workers=4)
    assert runner.max_workers == 1


# ============ 错误隔离 ============

def test_batch_error_isolation():
    """单个 job 失败不影响其他 job"""
    app = _make_app_mock()
    call_count = [0]
    original = app.submit_and_run

    def flaky(**kwargs):
        call_count[0] += 1
        if call_count[0] == 2:  # 第二个调用抛异常
            raise RuntimeError("模拟失败")
        return original(**kwargs)

    app.submit_and_run = flaky
    runner = ParallelRunner(app, max_workers=2)
    jobs = [{"script": "A"}, {"script": "B"}, {"script": "C"}]
    results = runner.run_batch(jobs)

    assert len(results) == 3
    failed = [r for r in results if not r.success]
    assert len(failed) == 1
    assert "模拟失败" in (failed[0].error or "")


def test_batch_submit_returns_failure_isolated():
    """submit_and_run 返回 success=False 也被正确隔离"""
    app = _make_app_mock()
    call_count = [0]
    original = app.submit_and_run

    def mixed(**kwargs):
        call_count[0] += 1
        if call_count[0] % 2 == 0:
            return {"success": False, "error": "风控拦截", "elapsed": 0.01}
        return original(**kwargs)

    app.submit_and_run = mixed
    runner = ParallelRunner(app, max_workers=1)
    results = runner.run_batch([{"script": "x"}, {"script": "y"}, {"script": "z"}])

    successes = [r for r in results if r.success]
    failures = [r for r in results if not r.success]
    assert len(successes) == 2
    assert len(failures) == 1
    assert failures[0].error == "风控拦截"


# ============ 汇总报告 ============

def test_batch_summary():
    """汇总报告"""
    app = _make_app_mock()
    runner = ParallelRunner(app, max_workers=1)
    results = runner.run_batch([{"script": "A"}, {"script": "B"}])
    summary = runner.run_batch_summary(results)

    assert summary["total"] == 2
    assert summary["success"] == 2
    assert summary["failed"] == 0
    assert summary["success_rate"] == 1.0
    assert summary["total_elapsed"] > 0
    assert summary["errors"] == []


# ============ 进度回调 ============

def test_batch_progress_callback():
    """进度回调被正确触发"""
    app = _make_app_mock()
    events = []
    runner = ParallelRunner(app, max_workers=1)
    runner.run_batch(
        [{"script": "A"}],
        progress_callback=lambda i, s, d: events.append((i, s)),
    )
    statuses = [e[1] for e in events]
    assert "started" in statuses
    assert "success" in statuses


# ============ 并发加速验证（证明多线程确实更快）============

def test_batch_concurrent_is_faster():
    """多 worker 并发应比串行更快（验证并发真正生效）"""
    app_slow = _make_app_mock()
    # 每个 job sleep 0.3s
    def slow(**kwargs):
        time.sleep(0.3)
        return {"success": True, "job_id": "x", "elapsed": 0.3}
    app_slow.submit_and_run = slow

    jobs = [{"script": f"j{i}"} for i in range(4)]

    # 串行
    t0 = time.time()
    ParallelRunner(app_slow, max_workers=1).run_batch(jobs)
    serial_time = time.time() - t0

    # 并发（4 worker）
    t0 = time.time()
    ParallelRunner(app_slow, max_workers=4).run_batch(jobs)
    parallel_time = time.time() - t0

    # 并发应明显快于串行（至少快 2 倍，留容差）
    assert parallel_time < serial_time * 0.6, (
        f"并发未生效: serial={serial_time:.2f}s parallel={parallel_time:.2f}s"
    )
