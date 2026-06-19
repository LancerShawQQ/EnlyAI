"""数字人口播生成模块测试"""
from __future__ import annotations

import base64
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from krvoiceai.core.audio_utils import generate_silent_wav
from krvoiceai.core.base_module import JobContext, ModuleStatus
from krvoiceai.core.ffmpeg_utils import FFmpegRunner
from krvoiceai.core.gpu_runner import GPURunner
from krvoiceai.modules.avatar_engine import AvatarEngine


@pytest.fixture
def mock_gpu():
    gpu = MagicMock(spec=GPURunner)
    gpu.health_check_avatar.return_value = False
    return gpu


@pytest.fixture
def avatar_mock(isolated_config, mock_gpu):
    isolated_config.set("avatar.provider", "mock")
    return AvatarEngine(gpu_runner=mock_gpu)


@pytest.fixture
def audio_file(job_work_dir):
    """生成测试用音频"""
    p = job_work_dir / "test_audio.wav"
    generate_silent_wav(p, 2.0)
    return p


def test_mock_generate_basic(avatar_mock, job_work_dir, audio_file):
    """Mock 模式基础生成"""
    ctx = JobContext(
        work_dir=job_work_dir,
        audio_path=audio_file,
        audio_duration=2.0,
        avatar_id="test_avatar",
    )
    ctx.ensure_work_dir()
    result = avatar_mock.execute(ctx)

    assert result.success is True
    assert ctx.raw_video_path.exists()
    assert result.data["provider"] == "mock"
    assert avatar_mock.status == ModuleStatus.SUCCESS


def test_mock_generate_valid_video(avatar_mock, job_work_dir, audio_file):
    """Mock 生成的是有效视频文件"""
    ctx = JobContext(
        work_dir=job_work_dir,
        audio_path=audio_file,
        audio_duration=2.0,
    )
    ctx.ensure_work_dir()
    avatar_mock.execute(ctx)

    ff = FFmpegRunner()
    info = ff.probe_video_info(ctx.raw_video_path)
    assert info is not None
    assert info.duration > 1.5  # 接近 2 秒
    assert info.width > 0
    assert info.height > 0


def test_mock_no_audio(avatar_mock, job_work_dir):
    """无音频文件处理"""
    ctx = JobContext(work_dir=job_work_dir, audio_path=Path("/nonexistent.wav"))
    ctx.ensure_work_dir()
    result = avatar_mock.execute(ctx)
    assert result.success is False
    assert "无音频" in result.error


def test_musetalk_unavailable_falls_back(isolated_config, mock_gpu):
    """MuseTalk 不可用时降级"""
    isolated_config.set("avatar.provider", "musetalk")
    mock_gpu.health_check_avatar.return_value = False
    av = AvatarEngine(gpu_runner=mock_gpu)
    av.setup()
    assert av.provider == "mock"


def test_cloud_generate_success(isolated_config, job_work_dir, audio_file):
    """云端生成成功（mock GPU 响应）"""
    isolated_config.set("avatar.provider", "musetalk")

    # 生成一段假视频数据（用 ffmpeg 生成 1 秒视频）
    ff = FFmpegRunner()
    fake_video = job_work_dir / "fake_avatar.mp4"
    placeholder_img = job_work_dir / "img.jpg"
    from PIL import Image
    Image.new("RGB", (1080, 1920), (50, 60, 80)).save(str(placeholder_img), "JPEG")
    ff.image_audio_to_video(placeholder_img, audio_file, fake_video, fps=25)
    video_b64 = base64.b64encode(fake_video.read_bytes()).decode()

    gpu = MagicMock(spec=GPURunner)
    gpu.health_check_avatar.return_value = True
    gpu.call_avatar.return_value = {"video_base64": video_b64}

    av = AvatarEngine(gpu_runner=gpu)
    av.setup()
    assert av.provider == "musetalk"

    ctx = JobContext(
        work_dir=job_work_dir,
        audio_path=audio_file,
        audio_duration=2.0,
        avatar_id="alice",
    )
    ctx.ensure_work_dir()
    result = av.execute(ctx)
    assert result.success is True
    assert ctx.raw_video_path.exists()
    assert gpu.call_avatar.called


def test_cloud_no_video_data(isolated_config, job_work_dir, audio_file):
    """云端返回无视频数据"""
    isolated_config.set("avatar.provider", "musetalk")
    gpu = MagicMock(spec=GPURunner)
    gpu.health_check_avatar.return_value = True
    gpu.call_avatar.return_value = {"error": "avatar not found"}

    av = AvatarEngine(gpu_runner=gpu)
    av.setup()
    ctx = JobContext(
        work_dir=job_work_dir,
        audio_path=audio_file,
        audio_duration=2.0,
    )
    ctx.ensure_work_dir()
    result = av.execute(ctx)
    assert result.success is False
    assert "无视频" in result.error


def test_register_avatar_mock(avatar_mock, job_work_dir, audio_file):
    """Mock 模式注册形象（用音频生成假视频再抽帧）"""
    # 先用音频+图片生成一个假视频作为参考
    ff = FFmpegRunner()
    fake_ref = job_work_dir / "ref.mp4"
    img = job_work_dir / "ref_img.jpg"
    from PIL import Image
    Image.new("RGB", (1080, 1920), (100, 120, 150)).save(str(img), "JPEG")
    ff.image_audio_to_video(img, audio_file, fake_ref, fps=25)

    ok = avatar_mock.register_avatar("new_avatar", fake_ref)
    assert ok is True
    ref_img = avatar_mock.avatars_dir / "new_avatar" / "reference.jpg"
    assert ref_img.exists()


def test_placeholder_image_generated(avatar_mock, job_work_dir, audio_file):
    """未注册形象时生成占位图"""
    ctx = JobContext(
        work_dir=job_work_dir,
        audio_path=audio_file,
        audio_duration=2.0,
        avatar_id="nonexistent_avatar_xyz",
    )
    ctx.ensure_work_dir()
    result = avatar_mock.execute(ctx)
    assert result.success is True
    # 占位图应被生成
    placeholder = avatar_mock.avatars_dir / "nonexistent_avatar_xyz" / "placeholder.jpg"
    assert placeholder.exists()


def test_video_resolution_matches_config(avatar_mock, job_work_dir, audio_file):
    """输出视频分辨率符合配置"""
    ctx = JobContext(
        work_dir=job_work_dir,
        audio_path=audio_file,
        audio_duration=2.0,
    )
    ctx.ensure_work_dir()
    avatar_mock.execute(ctx)

    ff = FFmpegRunner()
    info = ff.probe_video_info(ctx.raw_video_path)
    assert info is not None
    assert info.width == avatar_mock.output_resolution[0]
    assert info.height == avatar_mock.output_resolution[1]
