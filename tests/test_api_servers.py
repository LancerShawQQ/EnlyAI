"""API 服务测试

验证 TTS 和数字人 API 服务可正常启动、健康检查、注册、调用。
"""
from __future__ import annotations

import base64
import io
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# FastAPI TestClient 需要先安装 httpx
fastapi_test_available = False
try:
    from fastapi.testclient import TestClient
    fastapi_test_available = True
except ImportError:
    pass


pytestmark = pytest.mark.skipif(
    not fastapi_test_available,
    reason="fastapi/testclient 未安装",
)


@pytest.fixture
def tts_client(tmp_path, monkeypatch):
    """TTS 服务测试客户端"""
    voices_dir = tmp_path / "voices"
    voices_dir.mkdir()
    monkeypatch.setenv("VOICES_DIR", str(voices_dir))

    # 重新导入以应用环境变量
    import importlib
    from krvoiceai.api import tts_server
    importlib.reload(tts_server)
    tts_server._tts_model = None  # 重置模型缓存
    tts_server._voices_dir = voices_dir

    return TestClient(tts_server.app), voices_dir


@pytest.fixture
def avatar_client(tmp_path, monkeypatch):
    """数字人服务测试客户端"""
    avatars_dir = tmp_path / "avatars"
    avatars_dir.mkdir()
    monkeypatch.setenv("AVATARS_DIR", str(avatars_dir))

    import importlib
    from krvoiceai.api import avatar_server
    importlib.reload(avatar_server)
    avatar_server._avatar_model = None
    avatar_server._avatars_dir = avatars_dir

    return TestClient(avatar_server.app), avatars_dir


def _make_wav_bytes(duration: float = 1.0, sr: int = 22050) -> bytes:
    """生成测试用 wav 字节（使用项目已有的 audio_utils）"""
    from krvoiceai.core.audio_utils import generate_silent_wav
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        path = Path(f.name)
    try:
        generate_silent_wav(path, duration=duration, sample_rate=sr)
        return path.read_bytes()
    finally:
        if path.exists():
            path.unlink()


def _make_mp4_bytes() -> bytes:
    """生成最小测试 mp4 字节（用 ffmpeg）"""
    import subprocess
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        path = f.name
    subprocess.run(
        [
            "ffmpeg", "-y", "-f", "lavfi",
            "-i", "color=c=red:s=320x240:d=1",
            "-c:v", "libx264",
            path,
        ],
        capture_output=True, check=True,
    )
    data = Path(path).read_bytes()
    os.unlink(path)
    return data


# ============================================
# TTS 服务测试
# ============================================

def test_tts_health(tts_client):
    """TTS 健康检查"""
    client, _ = tts_client
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["service"] == "tts"


def test_tts_register_voice(tts_client):
    """注册音色"""
    client, voices_dir = tts_client
    audio_b64 = base64.b64encode(_make_wav_bytes()).decode()
    r = client.post("/api/tts/register_voice", json={
        "voice_id": "test_voice",
        "sample_audio_base64": audio_b64,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert (voices_dir / "test_voice" / "sample.wav").exists()


def test_tts_synthesize_not_registered(tts_client):
    """合成未注册音色应返回 404"""
    client, _ = tts_client
    r = client.post("/api/tts/synthesize", json={
        "text": "测试",
        "voice_id": "nonexistent",
    })
    assert r.status_code == 404


def test_tts_synthesize_success(tts_client):
    """合成成功（占位实现）"""
    client, voices_dir = tts_client
    # 先注册音色
    audio_b64 = base64.b64encode(_make_wav_bytes()).decode()
    client.post("/api/tts/register_voice", json={
        "voice_id": "v1",
        "sample_audio_base64": audio_b64,
    })
    # 合成
    r = client.post("/api/tts/synthesize", json={
        "text": "你好世界",
        "voice_id": "v1",
        "speed": 1.0,
    })
    assert r.status_code == 200
    data = r.json()
    assert "audio_base64" in data
    assert data["voice_id"] == "v1"
    assert data["duration"] > 0
    # 验证返回的音频可解码
    audio_bytes = base64.b64decode(data["audio_base64"])
    assert len(audio_bytes) > 0


# ============================================
# 数字人服务测试
# ============================================

def test_avatar_health(avatar_client):
    """数字人健康检查"""
    client, _ = avatar_client
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["service"] == "avatar"


def test_avatar_register(avatar_client):
    """注册形象"""
    client, avatars_dir = avatar_client
    video_b64 = base64.b64encode(_make_mp4_bytes()).decode()
    r = client.post("/api/avatar/register", json={
        "avatar_id": "test_avatar",
        "reference_video_base64": video_b64,
    })
    assert r.status_code == 200
    data = r.json()
    assert data["success"] is True
    assert (avatars_dir / "test_avatar" / "reference.mp4").exists()
    assert (avatars_dir / "test_avatar" / "meta.json").exists()


def test_avatar_generate_not_registered(avatar_client):
    """生成未注册形象应返回 404"""
    client, _ = avatar_client
    audio_b64 = base64.b64encode(_make_wav_bytes()).decode()
    r = client.post("/api/avatar/generate", json={
        "audio_base64": audio_b64,
        "avatar_id": "nonexistent",
    })
    assert r.status_code == 404


def test_avatar_generate_success(avatar_client):
    """生成数字人视频（占位实现：参考视频 + 音频合成）"""
    client, avatars_dir = avatar_client
    # 先注册形象
    video_b64 = base64.b64encode(_make_mp4_bytes()).decode()
    client.post("/api/avatar/register", json={
        "avatar_id": "a1",
        "reference_video_base64": video_b64,
    })
    # 生成
    audio_b64 = base64.b64encode(_make_wav_bytes(duration=0.5)).decode()
    r = client.post("/api/avatar/generate", json={
        "audio_base64": audio_b64,
        "avatar_id": "a1",
        "output_fps": 25,
        "output_resolution": [320, 240],
    })
    assert r.status_code == 200
    data = r.json()
    assert "video_base64" in data
    assert data["avatar_id"] == "a1"
    # 验证返回的视频可解码（mp4 文件以 ftyp box 开头）
    video_bytes = base64.b64decode(data["video_base64"])
    assert len(video_bytes) > 100
    # mp4 文件头：4 字节 box size + 'ftyp' 标识
    assert video_bytes[4:8] == b'ftyp'
