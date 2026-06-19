"""GPT-SoVITS API 服务（云端 GPU 部署）

在云 GPU 上启动此服务，提供 TTS 声音克隆 API。
本地 KrVoiceAI 通过 GPURunner 调用此服务。

启动方式：
    python -m krvoiceai.api.tts_server --port 9880

依赖（云端安装）：
    pip install fastapi uvicorn gpt-sovits
"""
from __future__ import annotations

import argparse
import base64
import io
import os
import tempfile
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

app = FastAPI(title="KrVoiceAI TTS Server", version="1.0")

# GPT-SoVITS 模型实例（延迟加载）
_tts_model = None
_voices_dir = Path(os.environ.get("VOICES_DIR", "./config/voices"))


class SynthesizeRequest(BaseModel):
    text: str
    voice_id: str = "default"
    speed: float = 1.0


class RegisterVoiceRequest(BaseModel):
    voice_id: str
    sample_audio_base64: str


def _get_tts_model():
    """延迟加载 GPT-SoVITS 模型

    返回 None 表示未安装（使用占位实现）。
    """
    global _tts_model
    if _tts_model is None:
        try:
            # GPT-SoVITS 的加载方式（根据实际版本调整）
            from GPT_SoVITS.inference_webui import change_gpt_weights, change_sovits_weights, get_tts_wav
            _tts_model = {
                "get_tts_wav": get_tts_wav,
                "change_gpt_weights": change_gpt_weights,
                "change_sovits_weights": change_sovits_weights,
            }
        except ImportError:
            # GPT-SoVITS 未安装，返回 None 使用占位实现
            return None
    return _tts_model


@app.get("/health")
def health():
    return {"status": "ok", "service": "tts"}


@app.post("/api/tts/synthesize")
def synthesize(req: SynthesizeRequest):
    """文本转语音"""
    try:
        # 先查找音色参考音频（不依赖模型加载）
        voice_dir = _voices_dir / req.voice_id
        ref_audio = None
        for name in ("sample.wav", "sample.mp3", "ref.wav"):
            p = voice_dir / name
            if p.exists():
                ref_audio = p
                break

        if not ref_audio:
            raise HTTPException(
                status_code=404,
                detail=f"音色 {req.voice_id} 未注册",
            )

        model = _get_tts_model()

        if model is not None:
            # 真实 GPT-SoVITS 调用（实际接口根据版本调整）
            # result = model["get_tts_wav"](ref_audio, text=req.text, speed=req.speed)
            # audio_bytes = _wav_to_bytes(result)
            # return {"audio_base64": base64.b64encode(audio_bytes).decode(), ...}
            pass

        # 占位实现：生成静音 wav（实际部署时替换为 GPT-SoVITS 输出）
        import numpy as np
        import wave
        duration = max(0.5, len(req.text) / 4.5)
        sr = 32000
        # 极低幅度噪声，避免完全静音被某些解码器拒绝
        audio = (np.random.randn(int(duration * sr)) * 0.001 * 32767).astype(np.int16)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sr)
            wf.writeframes(audio.tobytes())
        audio_b64 = base64.b64encode(buf.getvalue()).decode()

        return {
            "audio_base64": audio_b64,
            "duration": duration,
            "sample_rate": sr,
            "voice_id": req.voice_id,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/tts/register_voice")
def register_voice(req: RegisterVoiceRequest):
    """注册音色"""
    try:
        voice_dir = _voices_dir / req.voice_id
        voice_dir.mkdir(parents=True, exist_ok=True)
        audio_bytes = base64.b64decode(req.sample_audio_base64)
        sample_path = voice_dir / "sample.wav"
        sample_path.write_bytes(audio_bytes)
        return {"success": True, "voice_id": req.voice_id}
    except Exception as e:
        return {"success": False, "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="KrVoiceAI TTS Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9880)
    args = parser.parse_args()

    import uvicorn
    print(f"TTS 服务启动: http://{args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
