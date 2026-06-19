"""视频合成模块测试"""
from __future__ import annotations

from pathlib import Path

import pytest

from krvoiceai.core.audio_utils import generate_silent_wav
from krvoiceai.core.base_module import JobContext, ModuleStatus
from krvoiceai.core.ffmpeg_utils import FFmpegRunner
from krvoiceai.modules.video_composer import VideoComposer


@pytest.fixture
def composer(isolated_config):
    return VideoComposer()


@pytest.fixture
def ffmpeg_runner():
    return FFmpegRunner()


@pytest.fixture
def sample_video(job_work_dir, ffmpeg_runner):
    """生成测试用口播视频（图片+音频）"""
    from PIL import Image
    img = job_work_dir / "src.jpg"
    Image.new("RGB", (1080, 1920), (80, 100, 130)).save(str(img), "JPEG")
    audio = job_work_dir / "src.wav"
    generate_silent_wav(audio, 3.0)
    video = job_work_dir / "src.mp4"
    ffmpeg_runner.image_audio_to_video(img, audio, video, fps=25)
    return video


@pytest.fixture
def sample_subtitle(job_work_dir):
    """生成测试用 SRT 字幕"""
    srt = job_work_dir / "sub.srt"
    srt.write_text(
        "1\n00:00:00,000 --> 00:00:01,500\n第一句字幕\n\n"
        "2\n00:00:01,500 --> 00:00:03,000\n第二句字幕\n",
        encoding="utf-8",
    )
    return srt


@pytest.fixture
def sample_bgm(job_work_dir, ffmpeg_runner):
    """生成测试用 BGM（3 秒静音 mp3）"""
    bgm_wav = job_work_dir / "bgm.wav"
    generate_silent_wav(bgm_wav, 3.0)
    bgm_mp3 = job_work_dir / "bgm.mp3"
    ffmpeg_runner.run([
        "-i", str(bgm_wav),
        "-c:a", "libmp3lame",
        "-b:a", "128k",
        str(bgm_mp3),
    ])
    return bgm_mp3


@pytest.fixture
def sample_cover(job_work_dir):
    """生成测试用封面图"""
    from PIL import Image
    cover = job_work_dir / "cover.jpg"
    Image.new("RGB", (1080, 1920), (150, 80, 100)).save(str(cover), "JPEG")
    return cover


def test_compose_basic(composer, job_work_dir, sample_video):
    """基础合成（仅视频）"""
    ctx = JobContext(work_dir=job_work_dir, raw_video_path=sample_video)
    ctx.ensure_work_dir()
    result = composer.execute(ctx)

    assert result.success is True
    assert ctx.final_video.exists()
    assert composer.status == ModuleStatus.SUCCESS


def test_compose_with_subtitle(composer, job_work_dir, sample_video, sample_subtitle):
    """带字幕合成"""
    ctx = JobContext(
        work_dir=job_work_dir,
        raw_video_path=sample_video,
        subtitle_path=sample_subtitle,
    )
    ctx.ensure_work_dir()
    result = composer.execute(ctx)

    assert result.success is True
    assert ctx.final_video.exists()
    assert result.data["has_subtitle"] is True


def test_compose_with_bgm(composer, job_work_dir, sample_video, sample_bgm):
    """带 BGM 合成"""
    ctx = JobContext(
        work_dir=job_work_dir,
        raw_video_path=sample_video,
        bgm_path=sample_bgm,
    )
    ctx.ensure_work_dir()
    result = composer.execute(ctx)

    assert result.success is True
    assert ctx.final_video.exists()
    assert result.data["has_bgm"] is True


def test_compose_with_cover(composer, job_work_dir, sample_video, sample_cover):
    """带封面首帧合成"""
    ctx = JobContext(
        work_dir=job_work_dir,
        raw_video_path=sample_video,
        cover_path=sample_cover,
    )
    ctx.ensure_work_dir()
    result = composer.execute(ctx)

    assert result.success is True
    assert ctx.final_video.exists()
    assert result.data["has_cover"] is True
    # 封面 1.5s + 原视频 3s ≈ 4.5s
    ff = FFmpegRunner()
    info = ff.probe_video_info(ctx.final_video)
    assert info is not None
    assert 4.0 < info.duration < 5.0


def test_compose_all_elements(
    composer, job_work_dir, sample_video, sample_subtitle, sample_bgm, sample_cover
):
    """全部元素合成（字幕+BGM+封面）"""
    ctx = JobContext(
        work_dir=job_work_dir,
        raw_video_path=sample_video,
        subtitle_path=sample_subtitle,
        bgm_path=sample_bgm,
        cover_path=sample_cover,
    )
    ctx.ensure_work_dir()
    result = composer.execute(ctx)

    assert result.success is True
    assert ctx.final_video.exists()
    assert result.data["has_subtitle"] is True
    assert result.data["has_bgm"] is True
    assert result.data["has_cover"] is True


def test_compose_no_video(composer, job_work_dir):
    """无视频处理"""
    ctx = JobContext(work_dir=job_work_dir, raw_video_path=Path("/nonexistent.mp4"))
    ctx.ensure_work_dir()
    result = composer.execute(ctx)
    assert result.success is False
    assert "无口播视频" in result.error


def test_compose_output_resolution(composer, job_work_dir, sample_video):
    """输出分辨率符合配置"""
    ctx = JobContext(work_dir=job_work_dir, raw_video_path=sample_video)
    ctx.ensure_work_dir()
    composer.execute(ctx)

    ff = FFmpegRunner()
    info = ff.probe_video_info(ctx.final_video)
    assert info is not None
    assert info.width == composer.output_resolution[0]
    assert info.height == composer.output_resolution[1]


def test_compose_output_playable(composer, job_work_dir, sample_video):
    """输出是有效可播放视频"""
    ctx = JobContext(work_dir=job_work_dir, raw_video_path=sample_video)
    ctx.ensure_work_dir()
    composer.execute(ctx)

    ff = FFmpegRunner()
    info = ff.probe_video_info(ctx.final_video)
    assert info is not None
    assert info.duration > 2.5
    assert info.fps > 0
    # 文件大小应大于 0
    assert ctx.final_video.stat().st_size > 1000


def test_pick_bgm_empty(composer):
    """空 BGM 库"""
    result = composer.pick_bgm()
    # 测试环境 BGM 库可能为空
    assert result is None or result.exists()
