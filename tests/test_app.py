"""应用入口与全流程测试"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from krvoiceai.app import EnlyAI
from krvoiceai.core.audio_utils import generate_silent_wav
from krvoiceai.core.ffmpeg_utils import FFmpegRunner


@pytest.fixture
def app(isolated_config):
    """全 mock 模式的应用实例"""
    isolated_config.set("llm.provider", "mock")
    isolated_config.set("llm.api_key", "")
    isolated_config.set("tts.provider", "mock")
    isolated_config.set("avatar.provider", "mock")
    isolated_config.set("asr.provider", "mock")
    isolated_config.set("publisher.mode", "manual")
    isolated_config.set("publisher.publish_interval", 0)
    return EnlyAI()


def test_app_init(app):
    """应用可初始化"""
    assert app.orchestrator is not None
    health = app.health_check()
    assert health["ffmpeg"] is True
    assert "avatars_count" in health


def test_full_pipeline_9_modules(app):
    """全流程 9 模块端到端测试（核心验收用例）"""
    script = (
        "大家好，今天聊聊如何用AI提升工作效率。"
        "第一点，善用AI写作助手，文案效率翻倍。"
        "第二点，用AI做数据分析，告别手动制表。"
        "第三点，AI自动化流程，省下重复劳动时间。"
        "掌握这三点，你的效率至少提升3倍。"
        "觉得有用，点赞关注，下期见。"
    )

    result = app.submit_and_run(
        script=script,
        avatar_id="test",
        voice_id="test",
        script_mode="polish",
        platform="douyin",
        auto_publish=False,
    )

    assert result["success"] is True, f"任务失败: {result.get('error')}"
    assert result["status"] == "success"

    output = result["output"]
    # 验证所有产物
    assert output["final_video"], "无最终视频"
    assert Path(output["final_video"]).exists(), "最终视频文件不存在"
    assert output["script_text"], "无文案"
    assert output["audio_path"], "无音频"
    assert output["audio_duration"] > 0, "音频时长为0"
    assert output["raw_video"], "无口播视频"
    assert output["subtitle"], "无字幕"
    assert output["title"], "无标题"
    assert output["cover"], "无封面"

    # 验证最终视频可播放
    ff = FFmpegRunner()
    info = ff.probe_video_info(Path(output["final_video"]))
    assert info is not None
    assert info.duration > 5
    assert info.width == 1080
    assert info.height == 1920


def test_full_pipeline_with_reference_url(app):
    """带参考视频 URL 的全流程"""
    result = app.submit_and_run(
        script="",  # 留空，从 URL 提取
        reference_video_url="https://www.bilibili.com/video/BV1234",
        script_mode="rewrite",
        platform="bilibili",
    )
    assert result["success"] is True
    assert result["output"]["final_video"]


def test_full_pipeline_with_auto_publish(app):
    """自动发布流程"""
    result = app.submit_and_run(
        script="测试自动发布流程。",
        platform="douyin",
        auto_publish=True,
    )
    assert result["success"] is True
    # manual 模式下应生成发布清单
    job = app.get_job(result["job_id"])
    # publish 步骤应执行
    publish_step = [s for s in job["steps"] if s["step"] == "publish"][0]
    assert publish_step["status"] == "success"


def test_job_management(app):
    """任务管理：列表/查询/重跑"""
    r1 = app.submit_and_run(script="任务一测试。")
    r2 = app.submit_and_run(script="任务二测试。")

    jobs = app.list_jobs()
    assert len(jobs) >= 2

    job = app.get_job(r1["job_id"])
    assert job is not None
    assert job["status"] == "success"


def test_list_avatars_empty(app):
    """空形象列表"""
    avatars = app.list_avatars()
    assert isinstance(avatars, list)


def test_list_voices_empty(app):
    """空音色列表"""
    voices = app.list_voices()
    assert isinstance(voices, list)


def test_register_avatar_mock(app, job_work_dir):
    """注册形象（mock 模式）"""
    # 生成参考视频
    from PIL import Image
    ff = FFmpegRunner()
    img = job_work_dir / "ref.jpg"
    Image.new("RGB", (1080, 1920), (100, 120, 150)).save(str(img), "JPEG")
    audio = job_work_dir / "a.wav"
    generate_silent_wav(audio, 3.0)
    video = job_work_dir / "ref.mp4"
    ff.image_audio_to_video(img, audio, video, fps=25)

    ok = app.register_avatar("new_avatar", video)
    assert ok is True
    avatars = app.list_avatars()
    ids = [a["avatar_id"] for a in avatars]
    assert "new_avatar" in ids


def test_health_check(app):
    """健康检查"""
    health = app.health_check()
    assert health["ffmpeg"] is True
    assert "gpu_tts" in health
    assert "gpu_avatar" in health
    assert "llm_mock" in health


def test_gradio_ui_buildable(app):
    """Gradio UI 可构建（不启动）"""
    try:
        import gradio as gr
    except ImportError:
        pytest.skip("gradio 未安装")

    from krvoiceai.ui.gradio_app import _build_ui
    # 替换全局 app
    import krvoiceai.ui.gradio_app as gapp
    original = gapp._app
    gapp._app = app
    try:
        demo = _build_ui()
        assert demo is not None
    finally:
        gapp._app = original


def test_cli_importable():
    """CLI 可导入"""
    from krvoiceai.ui.cli import main
    assert callable(main)
