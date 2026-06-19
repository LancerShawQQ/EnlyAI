"""最终端到端验收测试

模拟完整的"本地 + 云端 GPU"工作流：
1. 启动云端 TTS / 数字人 API 服务（TestClient 模拟）
2. 本地 KrVoiceAI 通过 GPURunner 调用云端服务
3. 注册音色和形象
4. 跑通完整 9 模块 pipeline
5. 验证最终产物

这是对标旗博士 9 大能力的最终验收测试。
"""
from __future__ import annotations

import base64
import importlib
import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# 检查依赖
fastapi_available = False
try:
    from fastapi.testclient import TestClient
    fastapi_available = True
except ImportError:
    pass


pytestmark = pytest.mark.skipif(
    not fastapi_available,
    reason="fastapi/testclient 未安装",
)


@pytest.fixture
def cloud_env(tmp_path, monkeypatch):
    """搭建云端 GPU 服务环境（模拟）"""
    cloud_voices = tmp_path / "cloud_voices"
    cloud_avatars = tmp_path / "cloud_avatars"
    cloud_voices.mkdir()
    cloud_avatars.mkdir()

    monkeypatch.setenv("VOICES_DIR", str(cloud_voices))
    monkeypatch.setenv("AVATARS_DIR", str(cloud_avatars))

    # 启动 TTS 服务
    from krvoiceai.api import tts_server
    importlib.reload(tts_server)
    tts_server._tts_model = None
    tts_server._voices_dir = cloud_voices
    tts_client = TestClient(tts_server.app)

    # 启动数字人服务
    from krvoiceai.api import avatar_server
    importlib.reload(avatar_server)
    avatar_server._avatar_model = None
    avatar_server._avatars_dir = cloud_avatars
    avatar_client = TestClient(avatar_server.app)

    return {
        "tts_client": tts_client,
        "avatar_client": avatar_client,
        "cloud_voices": cloud_voices,
        "cloud_avatars": cloud_avatars,
    }


@pytest.fixture
def local_app_with_cloud(tmp_path, isolated_config, cloud_env, monkeypatch):
    """本地 KrVoiceAI 配置为调用云端服务（通过 mock GPURunner）"""
    from krvoiceai.app import KrVoiceAI
    from krvoiceai.core.gpu_runner import GPURunner

    tts_client = cloud_env["tts_client"]
    avatar_client = cloud_env["avatar_client"]

    # 创建 mock GPURunner，将 HTTP 调用转发到 TestClient
    class CloudGPURunner(GPURunner):
        def __init__(self):
            super().__init__()
            self.tts_endpoint = "mock://tts"
            self.avatar_endpoint = "mock://avatar"

        def health_check_tts(self):
            return True

        def health_check_avatar(self):
            return True

        def is_gpu_available(self):
            return True

        def call_tts(self, payload, timeout=120):
            r = tts_client.post("/api/tts/synthesize", json=payload)
            r.raise_for_status()
            return r.json()

        def call_tts_register(self, payload, timeout=300):
            r = tts_client.post("/api/tts/register_voice", json=payload)
            r.raise_for_status()
            return r.json()

        def call_avatar(self, payload, timeout=300):
            r = avatar_client.post("/api/avatar/generate", json=payload)
            r.raise_for_status()
            return r.json()

        def call_avatar_register(self, payload, timeout=600):
            r = avatar_client.post("/api/avatar/register", json=payload)
            r.raise_for_status()
            return r.json()

    # 配置使用云端 provider
    isolated_config.set("tts.provider", "gpt_sovits")
    isolated_config.set("avatar.provider", "musetalk")
    isolated_config.set("pipeline.gpu_enabled", True)
    isolated_config.set("llm.provider", "mock")
    isolated_config.set("asr.provider", "mock")
    isolated_config.set("publisher.mode", "manual")

    app = KrVoiceAI()

    # 替换 TTS 和 Avatar 模块的 gpu_runner，并强制使用云端 provider
    cloud_runner = CloudGPURunner()
    for step_def in app.orchestrator._steps.values():
        module = step_def.module
        if hasattr(module, "gpu"):
            module.gpu = cloud_runner
        if module.name == "tts":
            module.provider = "gpt_sovits"
        elif module.name == "avatar":
            module.provider = "musetalk"

    return app, cloud_env


def _make_wav_bytes(duration: float = 2.0) -> bytes:
    """生成测试用 wav"""
    from krvoiceai.core.audio_utils import generate_silent_wav
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = Path(f.name)
    try:
        generate_silent_wav(path, duration=duration, sample_rate=22050)
        return path.read_bytes()
    finally:
        path.unlink(missing_ok=True)


def _make_mp4_bytes() -> bytes:
    """生成测试用 mp4"""
    import subprocess
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        path = Path(f.name)
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "color=c=blue:s=320x240:d=2",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            path,
        ],
        capture_output=True, check=True,
    )
    data = path.read_bytes()
    path.unlink()
    return data


def _register_cloud_resources(cloud_env, voice_id: str, avatar_id: str):
    """注册音色和形象到云端"""
    audio_b64 = base64.b64encode(_make_wav_bytes()).decode()
    r = cloud_env["tts_client"].post("/api/tts/register_voice", json={
        "voice_id": voice_id,
        "sample_audio_base64": audio_b64,
    })
    assert r.status_code == 200

    video_b64 = base64.b64encode(_make_mp4_bytes()).decode()
    r = cloud_env["avatar_client"].post("/api/avatar/register", json={
        "avatar_id": avatar_id,
        "reference_video_base64": video_b64,
    })
    assert r.status_code == 200


# ============================================
# 验收测试 1：云端服务健康检查
# ============================================

def test_cloud_services_healthy(cloud_env):
    """云端 TTS 和数字人服务健康检查通过"""
    r = cloud_env["tts_client"].get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "tts"

    r = cloud_env["avatar_client"].get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "avatar"


# ============================================
# 验收测试 2：注册音色和形象到云端
# ============================================

def test_register_voice_and_avatar_to_cloud(cloud_env):
    """注册音色和形象到云端服务"""
    _register_cloud_resources(cloud_env, "acceptance_voice", "acceptance_avatar")

    # 验证文件存在
    assert (cloud_env["cloud_voices"] / "acceptance_voice" / "sample.wav").exists()
    assert (cloud_env["cloud_avatars"] / "acceptance_avatar" / "reference.mp4").exists()
    assert (cloud_env["cloud_avatars"] / "acceptance_avatar" / "meta.json").exists()


# ============================================
# 验收测试 3：完整 9 模块 pipeline（云端 GPU 模式）
# ============================================

def test_full_pipeline_with_cloud_gpu(local_app_with_cloud):
    """完整 9 模块 pipeline，TTS 和数字人调用云端服务

    这是最终验收测试：对标旗博士 9 大能力全流程打通。
    """
    app, cloud_env = local_app_with_cloud

    # 注册资源到云端
    _register_cloud_resources(cloud_env, "e2e_voice", "e2e_avatar")

    # 提交并运行任务
    result = app.submit_and_run(
        script="今天分享一个 AI 小技巧，用 GPT-SoVITS 克隆声音，三分钟搞定。",
        avatar_id="e2e_avatar",
        voice_id="e2e_voice",
        script_mode="polish",
        platform="douyin",
        auto_publish=False,
    )

    # 验证任务成功
    assert result["success"] is True, f"任务失败: {result.get('error')}"
    assert result["status"] == "success"

    # 验证 9 个步骤状态
    job = app.get_job(result["job_id"])
    steps = {s["step"]: s["status"] for s in job["steps"]}
    assert len(steps) == 9, f"应有 9 个步骤，实际 {len(steps)}"

    # 核心步骤必须成功
    for core_step in ["script_write", "tts", "avatar", "subtitle", "compose"]:
        assert steps[core_step] == "success", (
            f"核心步骤 {core_step} 状态: {steps[core_step]}"
        )

    # 验证最终产物
    output = result["output"]
    assert output["final_video"], "无最终视频"
    final_video = Path(output["final_video"])
    assert final_video.exists(), f"最终视频不存在: {final_video}"
    assert final_video.stat().st_size > 1000, "最终视频过小"

    # 验证视频是有效的 mp4
    with open(final_video, "rb") as f:
        header = f.read(8)
    assert header[4:8] == b'ftyp', f"视频不是有效的 mp4: {header}"

    # 验证其他产物
    assert output["script_text"], "无文案"
    assert output["audio_path"], "无音频"
    assert output["audio_duration"] > 0, "音频时长为0"
    assert output["raw_video"], "无口播视频"
    assert output["subtitle"], "无字幕"
    assert output["title"], "无标题"
    assert output["cover"], "无封面"


# ============================================
# 验收测试 4：断点续跑（云端模式）
# ============================================

def test_resume_with_cloud_gpu(local_app_with_cloud):
    """验证云端模式下断点续跑"""
    app, cloud_env = local_app_with_cloud

    _register_cloud_resources(cloud_env, "resume_voice", "resume_avatar")

    # 第一次运行
    result1 = app.submit_and_run(
        script="断点续跑测试文案。",
        avatar_id="resume_avatar",
        voice_id="resume_voice",
        platform="bilibili",
    )
    assert result1["success"] is True

    # 重新运行（应跳过已完成步骤）
    job_id = result1["job_id"]
    success = app.rerun_job(job_id)
    assert success is True

    # 验证所有步骤仍为成功（从 checkpoint 恢复）
    job = app.get_job(job_id)
    for s in job["steps"]:
        if s["status"] != "skipped":
            assert s["status"] == "success", (
                f"步骤 {s['step']} 状态: {s['status']}"
            )


# ============================================
# 验收测试 5：多平台支持
# ============================================

@pytest.mark.parametrize("platform", ["douyin", "bilibili", "kuaishou", "wechat_video"])
def test_multi_platform(local_app_with_cloud, platform):
    """验证多平台支持"""
    app, cloud_env = local_app_with_cloud

    _register_cloud_resources(
        cloud_env,
        f"plat_voice_{platform}",
        f"plat_avatar_{platform}",
    )

    result = app.submit_and_run(
        script=f"测试 {platform} 平台发布。",
        avatar_id=f"plat_avatar_{platform}",
        voice_id=f"plat_voice_{platform}",
        platform=platform,
        auto_publish=True,
    )

    assert result["success"] is True, f"平台 {platform} 失败: {result.get('error')}"

    # 验证发布步骤执行
    job = app.get_job(result["job_id"])
    publish_step = [s for s in job["steps"] if s["step"] == "publish"][0]
    assert publish_step["status"] == "success", (
        f"平台 {platform} 发布步骤状态: {publish_step['status']}"
    )
