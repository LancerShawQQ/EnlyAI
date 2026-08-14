"""CosyVoice 3 本地服务端

在独立 Python conda 环境中运行，为 EnlyAI 提供 Fun-CosyVoice3-0.5B-2512 TTS 服务。

为什么需要独立环境：
- CosyVoice 要求 torch==2.3.1 / torchaudio==2.3.1 / transformers==4.51.3
- EnlyAI 主环境（krvoiceai）用 torch 2.11+cu128（Blackwell sm_120 兼容）
- 两者 torch 版本冲突，必须独立 conda 环境 + HTTP 服务化（仿 MuseTalk 模式）

部署步骤：
1. conda create -n CosyVoice python=3.10 -y
2. conda activate CosyVoice
3. cd c:\\AI_projects\\koubo\\CosyVoice
4. pip install torch==2.3.1 torchaudio==2.3.1 --index-url https://download.pytorch.org/whl/cu121
5. pip install -r requirements.txt
6. pip install fastapi uvicorn python-multipart
7. python -c "from modelscope import snapshot_download; snapshot_download('iic/Fun-CosyVoice3-0.5B-2512', cache_dir='./pretrained_models')"
8. python cosyvoice_server.py --port 8012

硬件要求：
- 最低 4GB 显存（fp16 推理）
- 8GB 显存（RTX 5060）宽裕，可跑高质量模式
- 支持 CPU 推理（较慢，RTF~3-5）

API：
- GET  /api/health              健康检查 + GPU 信息 + 模型加载状态
- POST /api/tts/synth           零样本声音克隆（text + prompt_text + prompt_wav）
- POST /api/tts/instruct        指令控制合成（text + instruct_text + prompt_wav）
- POST /api/tts/cross_lingual   跨语言合成（text + prompt_wav）
- POST /api/tts/list_voices     列出可用预置音色（如有 SFT 模型）

返回：
- 音频以 WAV bytes 返回（Content-Type: audio/wav）
- 支持 stream=True 流式（返回 chunked int16 PCM）
"""
from __future__ import annotations

import argparse
import io
import os
import sys
import time
import tempfile
from pathlib import Path
from typing import Any

# 设置 modelscope 离线模式，避免 session 文件写入权限问题
os.environ.setdefault("MODELSCOPE_OFFLINE", "1")
# 将 modelscope 缓存目录指向项目内（避免 ~/.modelscope 权限问题）
os.environ.setdefault("MODELSCOPE_CACHE", str(Path(__file__).resolve().parent / "pretrained_models"))

# Patch pathlib.Path.write_text 以绕过 ~/.modelscope 权限问题
# modelscope_hub 尝试写 session 文件到 ~/.modelscope/credentials/session，
# 在某些 Windows 环境下该路径可能没有写权限，导致启动失败
_orig_write_text = Path.write_text
def _safe_write_text(self, data, encoding=None, errors=None, newline=None):
    try:
        return _orig_write_text(self, data, encoding=encoding, errors=errors, newline=newline)
    except (PermissionError, OSError):
        # 静默忽略权限错误（session 文件写入不是必需的）
        return 0
Path.write_text = _safe_write_text

import numpy as np
import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse, Response

# 将 CosyVoice 仓库根加入 sys.path（本脚本应放在 CosyVoice/ 根目录或通过 --repo_dir 指定）
ROOT_DIR = Path(__file__).resolve().parent
REPO_DIR = ROOT_DIR
# third_party/Matcha-TTS 也需加入
MATCHA_DIR = REPO_DIR / "third_party" / "Matcha-TTS"
for p in [str(REPO_DIR), str(MATCHA_DIR)]:
    if p not in sys.path:
        sys.path.insert(0, p)

app = FastAPI(title="CosyVoice3 TTS Server", version="1.0.0")

# 全局模型实例（懒加载）
_model = None
_model_dir: str = ""
_sample_rate: int = 24000
_fp16: bool = False


def get_gpu_info() -> dict:
    """获取 GPU 信息"""
    try:
        import torch
        if not torch.cuda.is_available():
            return {"available": False, "name": "CPU only", "vram_total_mb": 0}
        props = torch.cuda.get_device_properties(0)
        return {
            "available": True,
            "name": props.name,
            "vram_total_mb": int(props.total_memory / 1024 / 1024),
        }
    except Exception as e:
        return {"available": False, "name": f"检测失败: {e}", "vram_total_mb": 0}


def load_model(model_dir: str, fp16: bool = False):
    """懒加载 Fun-CosyVoice3-0.5B 模型

    Args:
        model_dir: 模型目录路径（含 config.yaml + 模型权重）
                   或 modelscope repo id（如 iic/Fun-CosyVoice3-0.5B-2512）
        fp16: 是否使用半精度推理（减少显存、加速推理）
    """
    global _model, _model_dir, _sample_rate, _fp16
    if _model is not None and _model_dir == model_dir:
        return _model

    print(f"[CosyVoice] 加载模型 model_dir={model_dir} fp16={fp16}")
    start = time.time()

    # 如果 model_dir 是本地目录，patch snapshot_download 跳过网络下载
    if os.path.isdir(model_dir):
        try:
            import modelscope
            _orig_sd = modelscope.snapshot_download
            def _local_sd(repo_id, *args, **kwargs):
                if os.path.isdir(repo_id):
                    print(f"[CosyVoice] snapshot_download 跳过网络下载，使用本地目录: {repo_id}")
                    return repo_id
                return _orig_sd(repo_id, *args, **kwargs)
            modelscope.snapshot_download = _local_sd
            # 同时 patch modelscope.hub 模块中的引用
            try:
                import modelscope.hub as _ms_hub
                _ms_hub.snapshot_download = _local_sd
            except Exception:
                pass
            print(f"[CosyVoice] 已 patch snapshot_download 以支持本地目录")
        except Exception as e:
            print(f"[CosyVoice] patch snapshot_download 失败（可忽略）: {e}")

    from cosyvoice.cli.cosyvoice import AutoModel
    # 直接 patch cosyvoice 模块中的 snapshot_download 引用
    # (cosyvoice.py 在 import 时已绑定 snapshot_download，需覆盖模块级引用)
    try:
        import cosyvoice.cli.cosyvoice as _cv_mod
        _cv_mod.snapshot_download = _local_sd
    except Exception:
        pass

    _model = AutoModel(model_dir=model_dir, fp16=fp16)
    _model_dir = model_dir
    _fp16 = fp16
    _sample_rate = getattr(_model, "sample_rate", 24000)

    elapsed = time.time() - start
    print(f"[CosyVoice] 模型加载完成 耗时={elapsed:.1f}s sample_rate={_sample_rate} fp16={fp16}")
    return _model


def _wav_to_bytes(wav_tensor, sample_rate: int) -> bytes:
    """将 torch tensor WAV 转为 WAV 文件 bytes（16-bit PCM）

    使用 soundfile 直接写入 BytesIO，避免 torchaudio 在 Windows 上的
    'Invalid file' 错误（torchaudio.save 对 file-like 对象支持不稳定）。
    """
    import torch
    import soundfile as sf
    import numpy as np

    # 确保是 1D (samples,) 或 2D (channel, samples)
    if wav_tensor.dim() == 1:
        wav_np = wav_tensor.cpu().numpy()
    else:
        # 2D: (channel, samples) -> transpose to (samples, channel)
        wav_np = wav_tensor.cpu().numpy().T

    # 归一化到 [-1, 1]
    max_val = np.abs(wav_np).max() if wav_np.size > 0 else 0
    if max_val > 1.0:
        wav_np = wav_np / max_val

    # 写入 WAV 到 BytesIO（16-bit PCM）
    buf = io.BytesIO()
    sf.write(buf, wav_np.astype(np.float32), sample_rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()


def _load_prompt_wav(file_bytes: bytes, tmp_dir: str = None) -> str:
    """保存上传的 prompt_wav 到临时文件，返回路径

    CosyVoice 的 load_wav 接受文件路径，不接受 file-like 对象。
    """
    if tmp_dir is None:
        tmp_dir = tempfile.gettempdir()
    tmp_path = os.path.join(tmp_dir, f"cosyvoice_prompt_{int(time.time()*1000)}.wav")
    with open(tmp_path, "wb") as f:
        f.write(file_bytes)
    return tmp_path


def _safe_unlink(path: str | None) -> None:
    """安全删除临时文件"""
    if path is None:
        return
    try:
        os.unlink(path)
    except Exception:
        pass


@app.get("/api/health")
async def health():
    """健康检查"""
    gpu = get_gpu_info()
    return {
        "status": "ok",
        "model_loaded": _model is not None,
        "model_dir": _model_dir,
        "gpu": gpu.get("name", "unknown"),
        "vram_total_mb": gpu.get("vram_total_mb", 0),
        "sample_rate": _sample_rate,
    }


@app.post("/api/unload")
async def unload_model():
    """卸载模型释放显存（GPU 分时复用：供 LatentSync 等其他 GPU 任务使用）"""
    global _model
    if _model is None:
        return {"status": "ok", "message": "model already unloaded"}
    del _model
    _model = None
    # 强制 GPU 内存回收
    import torch
    import gc
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    print("[CosyVoice] 模型已卸载，显存已释放")
    return {"status": "ok", "message": "model unloaded, VRAM released"}


@app.post("/api/load")
async def load_model_api():
    """重新加载模型（GPU 分时复用：LatentSync 完成后恢复 CosyVoice）"""
    global _model
    if _model is not None:
        return {"status": "ok", "message": "model already loaded"}
    try:
        load_model(_model_dir, fp16=_fp16)
        return {"status": "ok", "message": "model loaded"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/tts/synth")
async def inference_zero_shot(
    tts_text: str = Form(...),
    prompt_text: str = Form(""),
    prompt_wav: UploadFile = File(...),
    speed: float = Form(1.0),
    stream: bool = Form(False),
):
    """零样本声音克隆合成

    Args:
        tts_text: 要合成的文本
        prompt_text: 参考音频对应的文本（提升克隆精度，CosyVoice3 格式：
                     'You are a helpful assistant.<|endofprompt|>参考音频文本'）
        prompt_wav: 参考音频文件（3-10s 清晰人声，16kHz 优先）
        speed: 语速倍率（1.0 正常，CosyVoice3 通过 instruct 控制）
        stream: 是否流式返回

    Returns:
        WAV 音频 bytes（audio/wav）
    """
    prompt_path = None
    try:
        model = load_model(_model_dir)

        # 保存上传文件到临时路径 — 模型内部会调用 load_wav(path) 加载，
        # 所以必须传文件路径，不能预加载为 tensor（否则 torchaudio.load(tensor) 报错）
        prompt_bytes = await prompt_wav.read()
        prompt_path = _load_prompt_wav(prompt_bytes)

        # CosyVoice3 prompt_text 需要加系统前缀
        if prompt_text and "endofprompt" not in prompt_text:
            prompt_text = f"You are a helpful assistant.<|endofprompt|>{prompt_text}"
        elif not prompt_text:
            prompt_text = "You are a helpful assistant.<|endofprompt|>"

        print(f"[CosyVoice] zero_shot text_len={len(tts_text)} prompt_len={len(prompt_text)}")

        if stream:
            def gen():
                try:
                    for chunk in model.inference_zero_shot(
                        tts_text, prompt_text, prompt_path, stream=True, speed=speed
                    ):
                        yield _wav_to_bytes(chunk["tts_speech"], _sample_rate)
                finally:
                    _safe_unlink(prompt_path)
            return StreamingResponse(gen(), media_type="audio/wav")
        else:
            # 非流式：收集所有 chunk 合并为单个 WAV
            all_wavs = []
            for chunk in model.inference_zero_shot(
                tts_text, prompt_text, prompt_path, stream=False, speed=speed
            ):
                all_wavs.append(chunk["tts_speech"])

            if not all_wavs:
                return JSONResponse(
                    {"success": False, "error": "合成结果为空"}, status_code=500
                )

            import torch
            combined = torch.cat(all_wavs, dim=-1) if len(all_wavs) > 1 else all_wavs[0]
            wav_bytes = _wav_to_bytes(combined, _sample_rate)
            return Response(content=wav_bytes, media_type="audio/wav")

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(tb, flush=True)
        return JSONResponse(
            {"success": False, "error": str(e), "traceback": tb}, status_code=500
        )
    finally:
        _safe_unlink(prompt_path)


@app.post("/api/tts/instruct")
async def inference_instruct(
    tts_text: str = Form(...),
    instruct_text: str = Form(""),
    prompt_wav: UploadFile = File(...),
    speed: float = Form(1.0),
    stream: bool = Form(False),
):
    """指令控制合成（instruct2，支持情绪/方言/语速/音量控制）

    指令示例：
    - 'You are a helpful assistant. 请用四川话说。<|endofprompt|>'
    - 'You are a helpful assistant. 请用尽可能快地语速说。<|endofprompt|>'
    - 'You are a helpful assistant. 请用伤心的语气说。<|endofprompt|>'

    Args:
        tts_text: 要合成的文本
        instruct_text: 指令文本（CosyVoice3 格式，含系统前缀和 <|endofprompt|>）
        prompt_wav: 参考音频（定义音色）
        stream: 是否流式返回

    Returns:
        WAV 音频 bytes
    """
    prompt_path = None
    try:
        model = load_model(_model_dir)

        prompt_bytes = await prompt_wav.read()
        prompt_path = _load_prompt_wav(prompt_bytes)

        # instruct_text 需要系统前缀
        if instruct_text and "endofprompt" not in instruct_text:
            instruct_text = f"You are a helpful assistant. {instruct_text}<|endofprompt|>"
        elif not instruct_text:
            instruct_text = "You are a helpful assistant.<|endofprompt|>"

        print(f"[CosyVoice] instruct2 text_len={len(tts_text)} instruct='{instruct_text[:80]}'")

        if stream:
            def gen():
                try:
                    for chunk in model.inference_instruct2(
                        tts_text, instruct_text, prompt_path, stream=True, speed=speed
                    ):
                        yield _wav_to_bytes(chunk["tts_speech"], _sample_rate)
                finally:
                    _safe_unlink(prompt_path)
            return StreamingResponse(gen(), media_type="audio/wav")
        else:
            all_wavs = []
            for chunk in model.inference_instruct2(
                tts_text, instruct_text, prompt_path, stream=False, speed=speed
            ):
                all_wavs.append(chunk["tts_speech"])

            if not all_wavs:
                return JSONResponse(
                    {"success": False, "error": "合成结果为空"}, status_code=500
                )

            import torch
            combined = torch.cat(all_wavs, dim=-1) if len(all_wavs) > 1 else all_wavs[0]
            wav_bytes = _wav_to_bytes(combined, _sample_rate)
            return Response(content=wav_bytes, media_type="audio/wav")

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(tb, flush=True)
        return JSONResponse(
            {"success": False, "error": str(e), "traceback": tb}, status_code=500
        )
    finally:
        _safe_unlink(prompt_path)


@app.post("/api/tts/cross_lingual")
async def inference_cross_lingual(
    tts_text: str = Form(...),
    prompt_wav: UploadFile = File(...),
    stream: bool = Form(False),
):
    """跨语言合成（文本可含语言标签 <|zh|><|en|><|ja|><|yue|><|ko|>）

    Args:
        tts_text: 要合成的文本（可含语言标签）
        prompt_wav: 参考音频
        stream: 是否流式返回

    Returns:
        WAV 音频 bytes
    """
    prompt_path = None
    try:
        model = load_model(_model_dir)

        prompt_bytes = await prompt_wav.read()
        prompt_path = _load_prompt_wav(prompt_bytes)

        # CosyVoice3 cross_lingual 文本需要系统前缀
        if "endofprompt" not in tts_text:
            tts_text = f"You are a helpful assistant.<|endofprompt|>{tts_text}"

        print(f"[CosyVoice] cross_lingual text_len={len(tts_text)}")

        if stream:
            def gen():
                try:
                    for chunk in model.inference_cross_lingual(
                        tts_text, prompt_path, stream=True
                    ):
                        yield _wav_to_bytes(chunk["tts_speech"], _sample_rate)
                finally:
                    _safe_unlink(prompt_path)
            return StreamingResponse(gen(), media_type="audio/wav")
        else:
            all_wavs = []
            for chunk in model.inference_cross_lingual(
                tts_text, prompt_path, stream=False
            ):
                all_wavs.append(chunk["tts_speech"])

            if not all_wavs:
                return JSONResponse(
                    {"success": False, "error": "合成结果为空"}, status_code=500
                )

            import torch
            combined = torch.cat(all_wavs, dim=-1) if len(all_wavs) > 1 else all_wavs[0]
            wav_bytes = _wav_to_bytes(combined, _sample_rate)
            return Response(content=wav_bytes, media_type="audio/wav")

    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        print(tb, flush=True)
        return JSONResponse(
            {"success": False, "error": str(e), "traceback": tb}, status_code=500
        )
    finally:
        _safe_unlink(prompt_path)


@app.post("/api/tts/list_voices")
async def list_voices():
    """列出可用预置音色（仅 SFT 模型支持，CosyVoice3 Base 不支持）"""
    try:
        if _model is None:
            return {"success": False, "error": "模型未加载"}
        spks = _model.list_available_spks() if hasattr(_model, "list_available_spks") else []
        return {"success": True, "voices": list(spks) if spks else []}
    except Exception as e:
        return {"success": False, "error": str(e)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CosyVoice3 TTS Server")
    parser.add_argument("--port", type=int, default=8012, help="服务端口")
    parser.add_argument(
        "--model_dir",
        type=str,
        default=str(ROOT_DIR / "pretrained_models/models/FunAudioLLM--Fun-CosyVoice3-0.5B-2512/snapshots/master"),
        help="模型目录路径或 modelscope repo id",
    )
    parser.add_argument("--host", type=str, default="0.0.0.0", help="监听地址")
    parser.add_argument("--fp16", action="store_true", default=False, help="启用半精度推理（减少显存、加速）")
    args = parser.parse_args()

    # 预加载模型（避免首次请求超时）
    print(f"[CosyVoice] 预加载模型 model_dir={args.model_dir} fp16={args.fp16}")
    load_model(args.model_dir, fp16=args.fp16)

    print(f"[CosyVoice] 服务启动 host={args.host} port={args.port}")
    uvicorn.run(app, host=args.host, port=args.port)
