"""TTS 模块测试"""
from __future__ import annotations

import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from krvoiceai.core.base_module import JobContext, ModuleStatus
from krvoiceai.core.gpu_runner import GPURunner
from krvoiceai.modules.tts_engine import TTSEngine


@pytest.fixture
def mock_gpu():
    gpu = MagicMock(spec=GPURunner)
    gpu.health_check_tts.return_value = False
    return gpu


@pytest.fixture
def tts_mock(isolated_config, mock_gpu):
    """Mock 模式 TTS"""
    isolated_config.set("tts.provider", "mock")
    return TTSEngine(gpu_runner=mock_gpu)


def test_mock_synth_basic(tts_mock, job_work_dir):
    """Mock 模式基础合成"""
    ctx = JobContext(
        work_dir=job_work_dir,
        script_text="大家好，今天聊聊AI技术。这个话题很重要。",
        voice_id="default",
    )
    ctx.ensure_work_dir()
    result = tts_mock.execute(ctx)

    assert result.success is True
    assert ctx.audio_path.exists()
    assert ctx.audio_duration > 0
    assert result.data["provider"] == "mock"
    assert len(ctx.metadata["tts_timestamps"]) > 0
    assert tts_mock.status == ModuleStatus.SUCCESS


def test_mock_synth_produces_valid_wav(tts_mock, job_work_dir):
    """Mock 生成的是有效 wav 文件"""
    ctx = JobContext(
        work_dir=job_work_dir,
        script_text="测试音频生成",
    )
    ctx.ensure_work_dir()
    tts_mock.execute(ctx)

    with wave.open(str(ctx.audio_path), "rb") as wf:
        assert wf.getnchannels() >= 1
        assert wf.getframerate() > 0
        assert wf.getnframes() > 0


def test_mock_synth_empty_text(tts_mock, job_work_dir):
    """空文案处理"""
    ctx = JobContext(work_dir=job_work_dir, script_text="")
    ctx.ensure_work_dir()
    result = tts_mock.execute(ctx)
    assert result.success is False
    assert "无文案" in result.error


def test_mock_timestamps_monotonic(tts_mock, job_work_dir):
    """时间戳单调递增"""
    ctx = JobContext(
        work_dir=job_work_dir,
        script_text="第一句。第二句。第三句。最后一句。",
    )
    ctx.ensure_work_dir()
    tts_mock.execute(ctx)
    ts = ctx.metadata["tts_timestamps"]
    for i in range(1, len(ts)):
        assert ts[i]["start"] >= ts[i-1]["end"] - 0.01


def test_gpt_sovits_unavailable_falls_back(isolated_config, mock_gpu):
    """GPT-SoVITS 不可用时降级到 mock"""
    isolated_config.set("tts.provider", "gpt_sovits")
    mock_gpu.health_check_tts.return_value = False
    tts = TTSEngine(gpu_runner=mock_gpu)
    tts.setup()
    assert tts.provider == "mock"


def test_gpt_sovits_synth_success(isolated_config, job_work_dir):
    """GPT-SoVITS 真实调用（mock GPU 响应）"""
    import base64
    from krvoiceai.core.audio_utils import generate_silent_wav

    isolated_config.set("tts.provider", "gpt_sovits")

    # 准备一段假音频
    tmp_wav = job_work_dir / "seg.wav"
    generate_silent_wav(tmp_wav, 1.0)
    audio_b64 = base64.b64encode(tmp_wav.read_bytes()).decode()

    gpu = MagicMock(spec=GPURunner)
    gpu.health_check_tts.return_value = True
    gpu.call_tts.return_value = {
        "audio_base64": audio_b64,
        "duration": 1.0,
        "sample_rate": 32000,
    }

    tts = TTSEngine(gpu_runner=gpu)
    tts.setup()
    assert tts.provider == "gpt_sovits"

    ctx = JobContext(
        work_dir=job_work_dir,
        script_text="测试GPT-SoVITS合成。",
        voice_id="alice",
    )
    ctx.ensure_work_dir()
    result = tts.execute(ctx)
    assert result.success is True
    assert ctx.audio_path.exists()
    assert gpu.call_tts.called
    assert result.data["provider"] == "gpt_sovits"


def test_gpt_sovits_no_audio_data(isolated_config, job_work_dir):
    """GPT-SoVITS 返回无音频数据"""
    isolated_config.set("tts.provider", "gpt_sovits")
    gpu = MagicMock(spec=GPURunner)
    gpu.health_check_tts.return_value = True
    gpu.call_tts.return_value = {"error": "voice not found"}

    tts = TTSEngine(gpu_runner=gpu)
    tts.setup()
    ctx = JobContext(work_dir=job_work_dir, script_text="测试")
    ctx.ensure_work_dir()
    result = tts.execute(ctx)
    assert result.success is False
    assert "无音频" in result.error


def test_register_voice_mock(tts_mock, tmp_path):
    """Mock 模式注册音色：本地保存样本音频"""
    from krvoiceai.core.audio_utils import generate_silent_wav
    sample = tmp_path / "sample.wav"
    generate_silent_wav(sample, duration=2.0)
    ok = tts_mock.register_voice("alice", sample)
    assert ok is True


def test_duration_estimation_reasonable(tts_mock, job_work_dir):
    """时长估算合理（中文约 4-5 字/秒）"""
    text = "一二三四五六七八九十" * 10  # 100 字
    ctx = JobContext(work_dir=job_work_dir, script_text=text)
    ctx.ensure_work_dir()
    tts_mock.execute(ctx)
    # 100 字应在 15-30 秒之间
    assert 10 < ctx.audio_duration < 40
