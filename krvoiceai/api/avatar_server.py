"""MuseTalk 数字人 API 服务（云端 GPU 部署）

在云 GPU 上启动此服务，提供数字人口播生成 API。
本地 KrVoiceAI 通过 GPURunner 调用此服务。

启动方式：
    python -m krvoiceai.api.avatar_server --port 8010

依赖（云端安装）：
    pip install fastapi uvicorn musetalk torch torchvision opencv-python
    参考 scripts/setup_cloud_gpu.sh 一键安装
"""
from __future__ import annotations

import argparse
import base64
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI(title="KrVoiceAI Avatar Server", version="1.0")

# MuseTalk 模型实例（延迟加载）
_avatar_model = None
_avatars_dir = Path(os.environ.get("AVATARS_DIR", "./config/avatars"))


class GenerateRequest(BaseModel):
    """数字人生成请求"""
    audio_base64: str
    avatar_id: str = "default"
    output_fps: int = 25
    output_resolution: list[int] = [1080, 1920]


class RegisterRequest(BaseModel):
    """数字人形象注册请求"""
    avatar_id: str
    reference_video_base64: str


def _get_avatar_model():
    """延迟加载 MuseTalk 模型

    返回 None 表示未安装（使用占位实现）。
    """
    global _avatar_model
    if _avatar_model is None:
        try:
            # MuseTalk 加载方式（根据实际版本调整）
            # 参考 https://github.com/TMElyralab/MuseTalk
            from musetalk.api import MuseTalkAPI
            _avatar_model = MuseTalkAPI(
                avatar_path=str(_avatars_dir),
            )
        except ImportError:
            # MuseTalk 未安装，返回 None 使用占位实现
            return None
    return _avatar_model


@app.get("/health")
def health():
    return {"status": "ok", "service": "avatar"}


@app.post("/api/avatar/generate")
def generate(req: GenerateRequest):
    """生成数字人口播视频

    Args:
        req: 包含音频 base64 和 avatar_id

    Returns:
        video_base64: 生成的视频（base64 编码）
        duration: 视频时长（秒）
    """
    try:
        # 先查找形象参考视频（不依赖模型加载）
        avatar_dir = _avatars_dir / req.avatar_id
        ref_video = None
        for name in ("reference.mp4", "ref.mp4", "avatar.mp4"):
            p = avatar_dir / name
            if p.exists():
                ref_video = p
                break

        if not ref_video:
            raise HTTPException(
                status_code=404,
                detail=f"形象 {req.avatar_id} 未注册",
            )

        model = _get_avatar_model()

        # 解码音频到临时文件
        audio_bytes = base64.b64decode(req.audio_base64)
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            audio_path = f.name

        try:
            output_path = tempfile.NamedTemporaryFile(
                suffix=".mp4", delete=False
            ).name

            if model is not None:
                # 真实 MuseTalk 调用（实际接口根据版本调整）
                # result_path = model.generate(
                #     audio_path=audio_path,
                #     avatar_id=req.avatar_id,
                #     fps=req.output_fps,
                # )
                # shutil.copy(result_path, output_path)
                pass

            # 占位实现：用 ffmpeg 把参考视频 + 音频合成视频
            # 实际部署时替换为 MuseTalk 推理输出
            import subprocess
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", str(ref_video),
                    "-i", audio_path,
                    "-c:v", "libx264",
                    "-c:a", "aac",
                    "-shortest",
                    output_path,
                ],
                capture_output=True, check=True,
            )

            video_bytes = Path(output_path).read_bytes()
            video_b64 = base64.b64encode(video_bytes).decode()

            # 探测时长
            duration = _probe_duration(output_path)

            return {
                "video_base64": video_b64,
                "duration": duration,
                "avatar_id": req.avatar_id,
            }
        finally:
            if os.path.exists(audio_path):
                os.unlink(audio_path)
            if os.path.exists(output_path):
                os.unlink(output_path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/avatar/register")
def register(req: RegisterRequest):
    """注册数字人形象

    将参考视频保存到 avatars_dir/<avatar_id>/reference.mp4
    """
    try:
        avatar_dir = _avatars_dir / req.avatar_id
        avatar_dir.mkdir(parents=True, exist_ok=True)
        video_bytes = base64.b64decode(req.reference_video_base64)
        ref_path = avatar_dir / "reference.mp4"
        ref_path.write_bytes(video_bytes)

        # 抽取首帧作为预览图
        try:
            import subprocess
            preview = avatar_dir / "reference.jpg"
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", str(ref_path),
                    "-frames:v", "1",
                    "-q:v", "2",
                    str(preview),
                ],
                capture_output=True, check=True,
            )
        except Exception:
            pass

        # 保存元数据
        import json
        (avatar_dir / "meta.json").write_text(
            json.dumps({
                "avatar_id": req.avatar_id,
                "source": "cloud_register",
                "mode": "musetalk",
                "registered_at": time.time(),
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        return {"success": True, "avatar_id": req.avatar_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


def _probe_duration(video_path: str) -> float:
    """探测视频时长"""
    try:
        import subprocess
        r = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                video_path,
            ],
            capture_output=True, text=True, check=True,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


def main():
    parser = argparse.ArgumentParser(description="KrVoiceAI Avatar Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8010)
    args = parser.parse_args()

    import uvicorn
    print(f"数字人服务启动: http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
