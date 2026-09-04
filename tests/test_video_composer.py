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
    # 默认抖音式（cover_hold_seconds=0）：封面不进成片，时长≈原视频 3s
    # （历史区间 3.2-4.0 是封面停留 1s 时代的行为，见 test_compose_cover_hold_legacy）
    ff = FFmpegRunner()
    info = ff.probe_video_info(ctx.final_video)
    assert info is not None
    assert 2.5 < info.duration < 4.0


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


# ============ 封面停留可配（抖音式 hold=0）============

def _first_frame_color(video: Path):
    """提取成片第一帧的平均 RGB（用于断言首帧是封面还是正片）"""
    import subprocess, tempfile
    from PIL import Image
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as f:
        frame = Path(f.name)
    ff = FFmpegRunner()
    subprocess.run(
        [ff.ffmpeg, "-y", "-i", str(video), "-frames:v", "1", str(frame)],
        capture_output=True, check=True, timeout=30,
    )
    img = Image.open(str(frame)).convert("RGB").resize((16, 16))
    px = list(img.getdata())
    n = len(px)
    return tuple(sum(c[i] for c in px) // n for i in range(3))


def test_compose_cover_hold_zero_immediate(composer, job_work_dir, sample_video, sample_cover, isolated_config):
    """hold=0（默认，抖音式）：封面不进成片，第一帧就是正片画面"""
    isolated_config.set("composer.cover_hold_seconds", 0.0)
    isolated_config.set("composer.speech_lead_seconds", 0.25)
    ctx = JobContext(
        work_dir=job_work_dir,
        raw_video_path=sample_video,
        cover_path=sample_cover,
    )
    ctx.ensure_work_dir()
    result = composer.execute(ctx)
    assert result.success is True

    # 首帧应是正片颜色 (80,100,130) 而非封面颜色 (150,80,100)
    r, g, b = _first_frame_color(ctx.final_video)
    assert abs(g - 100) < abs(g - 80), f"首帧疑似封面: RGB=({r},{g},{b})"
    assert abs(b - 130) < abs(b - 100), f"首帧疑似封面: RGB=({r},{g},{b})"


def test_compose_cover_hold_legacy(composer, job_work_dir, sample_video, sample_cover, isolated_config):
    """hold>0（传统模式）：封面段进成片，第一帧是封面"""
    isolated_config.set("composer.cover_hold_seconds", 1.5)
    isolated_config.set("composer.speech_lead_seconds", 0.5)
    ctx = JobContext(
        work_dir=job_work_dir,
        raw_video_path=sample_video,
        cover_path=sample_cover,
    )
    ctx.ensure_work_dir()
    result = composer.execute(ctx)
    assert result.success is True

    r, g, b = _first_frame_color(ctx.final_video)
    assert abs(r - 150) < abs(r - 80), f"首帧疑似正片: RGB=({r},{g},{b})"
