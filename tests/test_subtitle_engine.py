"""字幕生成模块测试"""
from __future__ import annotations

from pathlib import Path

import pytest

from krvoiceai.core.audio_utils import generate_silent_wav
from krvoiceai.core.base_module import JobContext, ModuleStatus
from krvoiceai.modules.subtitle_engine import (
    SubtitleEngine,
    format_srt_time,
    segments_to_srt,
)


@pytest.fixture
def subtitle_mock(isolated_config):
    isolated_config.set("asr.provider", "mock")
    return SubtitleEngine()


@pytest.fixture
def audio_file(job_work_dir):
    p = job_work_dir / "audio.wav"
    generate_silent_wav(p, 5.0)
    return p


def test_format_srt_time():
    """SRT 时间格式化"""
    assert format_srt_time(0) == "00:00:00,000"
    assert format_srt_time(1.5) == "00:00:01,500"
    assert format_srt_time(65.25) == "00:01:05,250"
    assert format_srt_time(3661.999) == "01:01:01,999"
    assert format_srt_time(-1) == "00:00:00,000"


def test_segments_to_srt():
    """分句转 SRT"""
    segments = [
        {"text": "第一句", "start": 0.0, "end": 1.5},
        {"text": "第二句", "start": 1.5, "end": 3.0},
    ]
    srt = segments_to_srt(segments)
    assert "1" in srt
    assert "00:00:00,000 --> 00:00:01,500" in srt
    assert "第一句" in srt
    assert "第二句" in srt
    assert srt.endswith("\n")


def test_mock_with_tts_timestamps(subtitle_mock, job_work_dir, audio_file):
    """复用 TTS 时间戳"""
    ctx = JobContext(
        work_dir=job_work_dir,
        audio_path=audio_file,
        audio_duration=5.0,
        script_text="第一句。第二句。",
        metadata={
            "tts_timestamps": [
                {"text": "第一句。", "start": 0.0, "end": 2.0},
                {"text": "第二句。", "start": 2.0, "end": 4.0},
            ]
        },
    )
    ctx.ensure_work_dir()
    result = subtitle_mock.execute(ctx)

    assert result.success is True
    assert ctx.subtitle_path.exists()
    content = ctx.subtitle_path.read_text(encoding="utf-8")
    assert "第一句" in content
    assert "第二句" in content
    assert subtitle_mock.status == ModuleStatus.SUCCESS


def test_mock_without_tts_timestamps(subtitle_mock, job_work_dir, audio_file):
    """无 TTS 时间戳，按文本估算"""
    ctx = JobContext(
        work_dir=job_work_dir,
        audio_path=audio_file,
        audio_duration=5.0,
        script_text="这是第一句话。这是第二句话。这是第三句话。",
    )
    ctx.ensure_work_dir()
    result = subtitle_mock.execute(ctx)

    assert result.success is True
    content = ctx.subtitle_path.read_text(encoding="utf-8")
    assert "第一句话" in content
    assert "第三句话" in content
    # 时间戳应在 0-5 秒范围内
    assert "00:00:00,000" in content


def test_mock_long_text_split(subtitle_mock, job_work_dir, audio_file):
    """长文本自动切分"""
    long_text = "这是一段非常非常长的字幕文本需要被切分成多段才能显示在屏幕上不会超出限制。"
    ctx = JobContext(
        work_dir=job_work_dir,
        audio_path=audio_file,
        audio_duration=10.0,
        script_text=long_text,
    )
    ctx.ensure_work_dir()
    result = subtitle_mock.execute(ctx)
    assert result.success is True
    segments = ctx.metadata["subtitle_segments"]
    # 应被切分
    assert len(segments) > 1
    # 每段不超过 max_chars 太多
    for seg in segments:
        assert len(seg["text"]) <= 25


def test_no_audio(subtitle_mock, job_work_dir):
    """无音频处理"""
    ctx = JobContext(work_dir=job_work_dir, audio_path=Path("/nonexistent.wav"))
    ctx.ensure_work_dir()
    result = subtitle_mock.execute(ctx)
    assert result.success is False
    assert "无音频" in result.error


def test_funasr_unavailable_falls_back(isolated_config, job_work_dir, audio_file):
    """FunASR 不可用降级"""
    isolated_config.set("asr.provider", "funasr")
    # funasr 包未安装，应降级
    sub = SubtitleEngine()
    sub.setup()
    assert sub.provider == "mock"

    ctx = JobContext(
        work_dir=job_work_dir,
        audio_path=audio_file,
        audio_duration=3.0,
        script_text="测试降级。",
    )
    ctx.ensure_work_dir()
    result = sub.execute(ctx)
    assert result.success is True
    assert result.data["provider"] == "mock"


def test_timestamps_monotonic(subtitle_mock, job_work_dir, audio_file):
    """时间戳单调递增"""
    ctx = JobContext(
        work_dir=job_work_dir,
        audio_path=audio_file,
        audio_duration=6.0,
        script_text="一。二。三。四。五。六。",
    )
    ctx.ensure_work_dir()
    subtitle_mock.execute(ctx)
    segments = ctx.metadata["subtitle_segments"]
    for i in range(1, len(segments)):
        assert segments[i]["start"] >= segments[i-1]["end"] - 0.1


def test_empty_script_with_audio(subtitle_mock, job_work_dir, audio_file):
    """无文案但有音频"""
    ctx = JobContext(
        work_dir=job_work_dir,
        audio_path=audio_file,
        audio_duration=3.0,
        script_text="",
    )
    ctx.ensure_work_dir()
    result = subtitle_mock.execute(ctx)
    assert result.success is True
    # 应有占位字幕
    segments = ctx.metadata["subtitle_segments"]
    assert len(segments) >= 1
