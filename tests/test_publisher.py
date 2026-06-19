"""多平台发布模块测试"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from krvoiceai.core.audio_utils import generate_silent_wav
from krvoiceai.core.base_module import JobContext, ModuleStatus
from krvoiceai.core.ffmpeg_utils import FFmpegRunner
from krvoiceai.modules.publisher import Publisher


@pytest.fixture
def publisher(isolated_config):
    return Publisher()


@pytest.fixture
def final_video(job_work_dir):
    """生成测试用最终视频"""
    from PIL import Image
    ff = FFmpegRunner()
    img = job_work_dir / "f.jpg"
    Image.new("RGB", (1080, 1920), (80, 100, 130)).save(str(img), "JPEG")
    audio = job_work_dir / "a.wav"
    generate_silent_wav(audio, 2.0)
    video = job_work_dir / "final.mp4"
    ff.image_audio_to_video(img, audio, video, fps=25)
    return video


def test_manual_mode_generates_manifest(publisher, job_work_dir, final_video):
    """手动模式生成清单"""
    publisher.mode = "manual"
    ctx = JobContext(
        work_dir=job_work_dir,
        final_video=final_video,
        title="测试标题",
        metadata={"publish_platforms": ["bilibili", "douyin"]},
    )
    ctx.ensure_work_dir()
    result = publisher.execute(ctx)

    assert result.success is True
    assert result.data["mode"] == "manual"
    manifest = Path(result.data["manifest"])
    assert manifest.exists()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    assert len(data["targets"]) == 2
    assert data["targets"][0]["platform"] == "bilibili"


def test_semi_auto_mode(publisher, job_work_dir, final_video):
    """半自动模式"""
    publisher.mode = "semi_auto"
    ctx = JobContext(
        work_dir=job_work_dir,
        final_video=final_video,
        title="半自动测试",
        metadata={"publish_platforms": ["bilibili"]},
    )
    ctx.ensure_work_dir()
    result = publisher.execute(ctx)
    assert result.success is True
    assert "确认后" in result.data["message"]


def test_auto_mode_no_cookie_skips(publisher, job_work_dir, final_video):
    """自动模式无 Cookie 跳过"""
    publisher.mode = "auto"
    publisher.publish_interval = 0  # 加速测试
    ctx = JobContext(
        work_dir=job_work_dir,
        final_video=final_video,
        title="自动测试",
        metadata={"publish_platforms": ["bilibili"]},
    )
    ctx.ensure_work_dir()
    result = publisher.execute(ctx)
    # 无 cookie 应跳过，但流程不报错
    assert result.data["success_count"] == 0
    assert result.data["results"][0]["status"] == "skipped"


def test_no_video_fails(publisher, job_work_dir):
    """无视频处理"""
    ctx = JobContext(work_dir=job_work_dir, final_video=Path("/nonexistent.mp4"))
    ctx.ensure_work_dir()
    result = publisher.execute(ctx)
    assert result.success is False
    assert "无最终视频" in result.error


def test_default_platforms_from_config(publisher, job_work_dir, final_video):
    """从配置读取默认平台"""
    publisher.mode = "manual"
    publisher.platforms_cfg = {
        "bilibili": {"enabled": True},
        "douyin": {"enabled": False},
    }
    ctx = JobContext(
        work_dir=job_work_dir,
        final_video=final_video,
        title="配置测试",
    )
    ctx.ensure_work_dir()
    result = publisher.execute(ctx)
    assert result.success is True
    # 只应包含 enabled 的平台
    assert "bilibili" in result.data["platforms"]
    assert "douyin" not in result.data["platforms"]


def test_manifest_contains_all_fields(publisher, job_work_dir, final_video):
    """清单包含所有字段"""
    publisher.mode = "manual"
    cover = job_work_dir / "cover.jpg"
    from PIL import Image
    Image.new("RGB", (1080, 1920), (100, 100, 100)).save(str(cover), "JPEG")

    ctx = JobContext(
        work_dir=job_work_dir,
        final_video=final_video,
        cover_path=cover,
        title="完整字段测试",
        script_text="这是描述文本",
        metadata={"publish_platforms": ["bilibili"]},
    )
    ctx.ensure_work_dir()
    publisher.execute(ctx)

    manifest = Path(ctx.metadata["publish_manifest"])
    data = json.loads(manifest.read_text(encoding="utf-8"))
    target = data["targets"][0]
    assert target["title"] == "完整字段测试"
    assert target["video_path"]
    assert target["cover_path"]
    assert target["description"]
    assert target["status"] == "pending"


def test_execute_publish_method(publisher, job_work_dir, final_video):
    """execute_publish 方法"""
    publisher.mode = "manual"
    ctx = JobContext(
        work_dir=job_work_dir,
        final_video=final_video,
        title="执行测试",
        metadata={"publish_platforms": ["bilibili"]},
    )
    ctx.ensure_work_dir()
    publisher.execute(ctx)

    manifest = Path(ctx.metadata["publish_manifest"])
    # 调用 execute_publish（无 cookie 会跳过）
    publisher.publish_interval = 0
    results = publisher.execute_publish(manifest)
    assert "bilibili" in results
    assert results["bilibili"]["status"] in ("skipped", "success", "failed")


def test_unsupported_platform(publisher, job_work_dir, final_video):
    """不支持的平台"""
    publisher.mode = "auto"
    publisher.publish_interval = 0
    ctx = JobContext(
        work_dir=job_work_dir,
        final_video=final_video,
        title="不支持平台测试",
        metadata={"publish_platforms": ["unknown_platform"]},
    )
    ctx.ensure_work_dir()
    result = publisher.execute(ctx)
    assert result.data["results"][0]["status"] == "skipped"
