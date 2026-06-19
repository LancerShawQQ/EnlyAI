"""核心闭环端到端测试

验证完整流程：文案 → TTS → 数字人 → 字幕 → 视频合成 → 最终视频
"""
from __future__ import annotations

from pathlib import Path

import pytest

from krvoiceai.core.base_module import JobContext
from krvoiceai.core.ffmpeg_utils import FFmpegRunner
from krvoiceai.core.gpu_runner import GPURunner
from krvoiceai.core.llm_client import LLMClient
from krvoiceai.modules.avatar_engine import AvatarEngine
from krvoiceai.modules.script_writer import ScriptWriter
from krvoiceai.modules.subtitle_engine import SubtitleEngine
from krvoiceai.modules.tts_engine import TTSEngine
from krvoiceai.modules.video_composer import VideoComposer
from krvoiceai.pipeline.orchestrator import PipelineOrchestrator
from krvoiceai.pipeline.state import JobStatus, JobStore


@pytest.fixture
def orchestrator(isolated_config, job_work_dir):
    """构建完整 mock 模式的编排器"""
    # 所有模块用 mock provider
    isolated_config.set("llm.provider", "mock")
    isolated_config.set("llm.api_key", "")
    isolated_config.set("tts.provider", "mock")
    isolated_config.set("avatar.provider", "mock")
    isolated_config.set("asr.provider", "mock")

    from krvoiceai.core.storage import Storage
    storage = Storage()
    store = JobStore()

    orch = PipelineOrchestrator(job_store=store, storage=storage)

    # 构建模块
    ff = FFmpegRunner()
    modules = {
        "script_write": ScriptWriter(llm_client=LLMClient()),
        "tts": TTSEngine(),
        "avatar": AvatarEngine(ffmpeg=ff),
        "subtitle": SubtitleEngine(),
        "compose": VideoComposer(ffmpeg=ff),
    }
    orch.register_core_pipeline(modules)
    return orch


def test_end_to_end_basic(orchestrator):
    """端到端基础流程：文案 → 最终视频"""
    script = (
        "大家好，今天聊聊AI数字人技术。"
        "这项技术正在改变内容创作的方式。"
        "首先，它能大幅提升生产效率。"
        "其次，成本远低于真人拍摄。"
        "最后，效果已经非常接近真人。"
        "如果你觉得有用，点赞关注，下期见。"
    )

    job_id = orchestrator.submit_job(
        script=script,
        avatar_id="test_avatar",
        voice_id="test_voice",
        script_mode="polish",
    )

    success = orchestrator.run_job(job_id)
    assert success is True

    job = orchestrator.get_status(job_id)
    assert job["status"] == JobStatus.SUCCESS.value

    # 验证最终产物
    output = job["output"]
    assert output["final_video"] is not None
    final_video = Path(output["final_video"])
    assert final_video.exists(), f"最终视频不存在: {final_video}"

    # 验证视频可播放
    ff = FFmpegRunner()
    info = ff.probe_video_info(final_video)
    assert info is not None
    assert info.duration > 5  # 至少几秒
    assert info.width == 1080
    assert info.height == 1920

    # 验证中间产物
    assert output["script_text"]  # 文案已生成
    assert output["audio_path"]   # 音频已生成
    assert output["audio_duration"] > 0
    assert output["raw_video"]    # 口播视频已生成
    assert output["subtitle"]     # 字幕已生成


def test_end_to_end_all_steps_success(orchestrator):
    """所有步骤都成功执行"""
    job_id = orchestrator.submit_job(script="测试完整流程。每一步都要成功。")
    orchestrator.run_job(job_id)

    job = orchestrator.get_status(job_id)
    # 核心闭环的 5 个步骤应全部成功（其他步骤未注册则跳过）
    core_steps = ["script_write", "tts", "avatar", "subtitle", "compose"]
    for step_name in core_steps:
        step = [s for s in job["steps"] if s["step"] == step_name][0]
        assert step["status"] == "success", (
            f"步骤 {step_name} 状态为 {step['status']}, 错误: {step['error']}"
        )


def test_end_to_end_with_generate_mode(orchestrator):
    """生成模式（从主题生成文案）"""
    job_id = orchestrator.submit_job(
        script="如何高效学习编程",
        script_mode="generate",
    )
    success = orchestrator.run_job(job_id)
    assert success is True

    job = orchestrator.get_status(job_id)
    assert job["output"]["script_text"]


def test_end_to_end_video_has_audio(orchestrator):
    """最终视频包含音频轨"""
    job_id = orchestrator.submit_job(script="测试音频轨。")
    orchestrator.run_job(job_id)

    job = orchestrator.get_status(job_id)
    final_video = Path(job["output"]["final_video"])

    # 用 ffprobe 检查音频流
    import subprocess, json
    r = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "a",
            "-show_entries", "stream=codec_type",
            "-of", "json",
            str(final_video),
        ],
        capture_output=True, text=True,
    )
    data = json.loads(r.stdout)
    assert len(data.get("streams", [])) > 0, "最终视频无音频流"


def test_resume_from_failure(orchestrator, monkeypatch):
    """断点续跑：模拟中途失败后重跑"""
    job_id = orchestrator.submit_job(script="测试断点续跑。")

    # 第一次运行：让 avatar 步骤失败
    original_avatar = orchestrator._steps["avatar"].module
    fail_count = [0]

    class FlakyAvatar:
        def __init__(self, real):
            self.real = real
            self.name = real.name

        def execute(self, ctx):
            if fail_count[0] < 1:
                fail_count[0] += 1
                from krvoiceai.core.base_module import ModuleResult
                return ModuleResult(success=False, error="模拟失败")
            return self.real.execute(ctx)

    orchestrator._steps["avatar"].module = FlakyAvatar(original_avatar)

    # 降低重试次数加速测试
    monkeypatch.setattr(orchestrator, "max_retries", 1)
    monkeypatch.setattr(orchestrator, "retry_backoff", 0)

    success = orchestrator.run_job(job_id)
    # 第一次因 avatar 失败且无重试，整体失败
    assert success is False

    # 恢复真实模块，重跑（断点续跑）
    orchestrator._steps["avatar"].module = original_avatar
    success = orchestrator.run_job(job_id)
    assert success is True

    job = orchestrator.get_status(job_id)
    assert job["status"] == JobStatus.SUCCESS.value


def test_job_listing(orchestrator):
    """任务列表"""
    id1 = orchestrator.submit_job(script="任务一")
    id2 = orchestrator.submit_job(script="任务二")
    jobs = orchestrator.list_jobs()
    assert len(jobs) >= 2
    job_ids = [j["job_id"] for j in jobs]
    assert id1 in job_ids
    assert id2 in job_ids
