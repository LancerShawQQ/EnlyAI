"""LatentSync 1.5 本地服务端

在独立 Python 3.10 conda 环境中运行，为 EnlyAI 提供 LatentSync 唇形同步服务。
LatentSync 是字节跳动开源的音频驱动潜在扩散模型 LipSync（Apache 2.0），
基于 Stable Diffusion VAE + Whisper 音频特征 + 3D U-Net，端到端生成唇形同步视频，
质量优于 Wav2Lip / MuseTalk，适合高质量口播与无人直播。

部署步骤：
1. conda create -n LatentSync python=3.10 -y
2. conda activate LatentSync
3. git clone https://github.com/bytedance/LatentSync.git
4. cd LatentSync
5. pip install torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cu128
   （Blackwell sm_120 架构需 PyTorch 2.7+cu128，旧版 cu118/cu121 不支持 sm_120）
6. pip install -r requirements.txt
7. pip install fastapi uvicorn python-multipart
8. 下载模型权重到 checkpoints/ 目录：
   - checkpoints/latentsync_unet.pt   （U-Net 权重，HuggingFace: ByteDance/LatentSync-1.5）
   - checkpoints/whisper/tiny.pt      （Whisper tiny 音频编码器）
9. 将本脚本复制到 LatentSync 仓库根目录下（与 configs/ checkpoints/ 同级）
10. python latentsync_server.py --port 8011 --resolution 256

硬件要求（Blackwell sm_120 兼容）：
- 需 PyTorch 2.7+cu128（构建包含 sm_120 kernel）
- fp16 半精度推理
- 8GB 显存可跑 resolution=256（推荐 Blackwell 8GB 卡）
- 12GB+ 显存可跑 resolution=512（更高质量）

API：
- GET  /api/health          健康检查（GPU 信息 + 模型加载状态）
- POST /api/avatar/generate 生成唇形同步视频（audio + video -> video bytes）
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import torch
import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from omegaconf import OmegaConf

# 确保 HuggingFace 走国内镜像（VAE 模型 sd-vae-ft-mse 首次需下载）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")


# ── 将 imageio-ffmpeg 的 ffmpeg 二进制加入 PATH ──
# 原因：LatentSync 的 check_ffmpeg_installed() 和输出视频编码均依赖 ffmpeg CLI。
# LatentSync conda 环境装了 imageio-ffmpeg（含 ffmpeg 二进制），但未加入 PATH。
# 这里将其目录注入 PATH，使 shutil.which('ffmpeg') 能找到。
def _inject_ffmpeg_into_path():
    global _ffmpeg_exe
    try:
        import imageio_ffmpeg
        _ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        ffmpeg_dir = str(Path(_ffmpeg_exe).parent)
        # 将 ffmpeg 目录加入 PATH（prepend 优先级最高）
        os.environ["PATH"] = ffmpeg_dir + os.pathsep + os.environ.get("PATH", "")
        # 复制/重命名为 ffmpeg.exe（imageio-ffmpeg 的文件名可能不是标准名）
        import shutil
        standard_name = str(Path(_ffmpeg_exe).parent / ("ffmpeg.exe" if sys.platform == "win32" else "ffmpeg"))
        if _ffmpeg_exe != standard_name and not Path(standard_name).exists():
            try:
                shutil.copy2(_ffmpeg_exe, standard_name)
                _ffmpeg_exe = standard_name
            except Exception:
                pass
        which_ff = shutil.which("ffmpeg")
        if which_ff:
            _ffmpeg_exe = which_ff
        print(f"[LatentSync] ffmpeg PATH 注入完成: {_ffmpeg_exe}")
    except ImportError:
        print("[LatentSync] 警告：imageio-ffmpeg 未安装，ffmpeg CLI 可能不可用")
    except Exception as e:
        print(f"[LatentSync] 警告：ffmpeg PATH 注入失败: {e}")


_inject_ffmpeg_into_path()


# ── Patch whisper.load_audio 使用 soundfile 替代 ffmpeg ──
# 原因：TRAE 内置 ffmpeg 是最小化构建（--disable-everything），不支持 PCM WAV 解码。
# soundfile 直接读取音频文件，无需 ffmpeg，且支持 WAV/MP3/FLAC 等格式。
def _patch_whisper_audio_loader():
    """用 soundfile 替换 whisper.audio.load_audio，避免依赖完整 ffmpeg"""
    try:
        import soundfile as sf
        import librosa
        from latentsync.whisper.whisper import audio as whisper_audio

        SAMPLE_RATE = 16000

        def _load_audio_sf(file: str, sr: int = SAMPLE_RATE):
            """soundfile 版 load_audio，签名与原版兼容"""
            audio, orig_sr = sf.read(file, dtype="float32", always_2d=False)
            if audio.ndim > 1:
                audio = audio.mean(axis=1)
            if orig_sr != sr:
                audio = librosa.resample(audio, orig_sr=orig_sr, target_sr=sr)
            return audio.astype(np.float32)

        # 替换 whisper 的 load_audio
        whisper_audio.load_audio = _load_audio_sf
        print("[LatentSync] 已 patch whisper.load_audio -> soundfile 版本")
    except ImportError as e:
        print(f"[LatentSync] 警告：soundfile/librosa 未安装，将使用原版 ffmpeg 加载音频: {e}")
    except Exception as e:
        print(f"[LatentSync] 警告：patch whisper.load_audio 失败: {e}")


_patch_whisper_audio_loader()


# ── Patch read_video 使用 decord 直接读取，避免 ffmpeg 依赖 ──
# 原因：LatentSync 的 util.read_video 会在 CWD 创建 'temp' 目录用 ffmpeg 转换 fps，
# 但 TRAE 内置 ffmpeg 是最小化构建，且 CWD 可能不可写。
# 改为用 decord 直接读取原视频（decord 自带视频解码，不依赖 ffmpeg CLI）。
# 优化：根据音频时长预裁剪视频帧，减少不必要的解码 I/O 和内存占用。

# 模块级变量：当前请求的音频时长（秒），用于预裁剪视频
_current_audio_duration: float = 0.0
# ffmpeg 可执行文件路径（由 _inject_ffmpeg_into_path 设置）
_ffmpeg_exe: str = "ffmpeg"


def _patch_read_video_temp():
    """让 read_video 先用 ffmpeg 标准化视频（应用旋转+25fps），再用 decord 读取

    解决问题：
    1. 手机视频含 displaymatrix 旋转元数据（如小米 90°），decord/cv2 不会自动应用
       → ffmpeg 标准化时自动旋转到正确方向
    2. 颜色通道：ffmpeg 输出标准 yuv420p → decord 转 RGB，颜色正确
    3. 性能：标准化后预裁剪到音频时长，减少不必要的帧解码
    """
    try:
        from latentsync.utils import util as ls_util
        import tempfile

        def _read_video_safe(video_path: str, change_fps=True, use_decord=True):
            """用 ffmpeg 标准化（旋转+25fps）后用 decord 读取"""
            print(f"[LatentSync] read_video: {video_path}")

            # Step 1: 用 ffmpeg 标准化视频（自动应用旋转元数据 + 转 25fps + libx264）
            # 这与 LatentSync 原版 read_video 的 ffmpeg 步骤一致，确保旋转和颜色正确
            tmp_dir = tempfile.mkdtemp(prefix="latentsync_norm_")
            norm_path = os.path.join(tmp_dir, "normalized.mp4")

            # 按音频时长裁剪视频（减少标准化和后续处理的耗时）
            global _current_audio_duration
            duration_arg = []
            if _current_audio_duration > 0:
                duration_arg = ["-t", str(_current_audio_duration + 0.5)]
                print(f"[LatentSync] 预裁剪到 {_current_audio_duration:.1f}s + 0.5s 余量")

            ff_cmd = [
                _ffmpeg_exe, "-y", "-loglevel", "error", "-nostdin",
                "-i", str(video_path),
            ] + duration_arg + [
                "-r", "25",                    # 统一 25fps（LatentSync 标准）
                "-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2",  # 确保偶数尺寸
                "-c:v", "libx264", "-crf", "18",
                "-an",                         # 不需要音频
                norm_path,
            ]
            import subprocess
            result = subprocess.run(ff_cmd, capture_output=True, text=True, timeout=120)
            if result.returncode != 0 or not os.path.exists(norm_path):
                # ffmpeg 标准化失败，回退到 decord 直读
                print(f"[LatentSync] ffmpeg 标准化失败，回退 decord 直读: {result.stderr[-200:]}")
                from decord import VideoReader
                vr = VideoReader(video_path)
                video_frames = vr[:].asnumpy()
                vr.seek(0)
                return video_frames

            print(f"[LatentSync] ffmpeg 标准化完成（旋转校正 + 25fps）")

            # Step 2: 用 decord 读取标准化后的视频
            from decord import VideoReader
            vr = VideoReader(norm_path)
            video_frames = vr[:].asnumpy()
            vr.seek(0)

            # 清理临时文件
            try:
                os.unlink(norm_path)
                os.rmdir(tmp_dir)
            except Exception:
                pass

            print(f"[LatentSync] decord 读取完成: {len(video_frames)} 帧, shape={video_frames.shape}")
            return video_frames

        ls_util.read_video = _read_video_safe
        print("[LatentSync] 已 patch read_video -> ffmpeg 标准化 + decord 读取")
    except Exception as e:
        print(f"[LatentSync] 警告：patch read_video 失败: {e}")


_patch_read_video_temp()
# ──────────────────────────────────────────────────────────

app = FastAPI(title="LatentSync Avatar Server", version="1.5.0")

# 全局 pipeline 实例（懒加载，首次请求时构建；resolution 变更时重建）
_pipeline = None
_config = None
_resolution = 256
_inference_steps = 25


def get_gpu_info() -> dict:
    """获取 GPU 信息"""
    if not torch.cuda.is_available():
        return {"available": False, "name": "CPU only", "vram_total_mb": 0}
    props = torch.cuda.get_device_properties(0)
    return {
        "available": True,
        "name": props.name,
        "vram_total_mb": int(props.total_memory / 1024 / 1024),
    }


def _config_path_for_resolution(resolution: int) -> str:
    """根据分辨率选择 U-Net 配置文件

    256 → configs/unet/stage2.yaml（8GB 显存推荐）
    512 → configs/unet/stage2_512.yaml（需 12GB+ 显存）
    """
    if resolution >= 512:
        return "configs/unet/stage2_512.yaml"
    return "configs/unet/stage2.yaml"


def load_pipeline(resolution: int = _resolution):
    """懒加载 LatentSync LipsyncPipeline

    按真实 LatentSync 1.5 API 构建推理管线：
    1. 加载 U-Net 配置（OmegaConf）
    2. DDIMScheduler（从 configs/ 目录）
    3. Audio2Feature（Whisper tiny 音频编码器）
    4. AutoencoderKL VAE（stabilityai/sd-vae-ft-mse）
    5. UNet3DConditionModel（从配置 + checkpoint）
    6. LipsyncPipeline(vae, audio_encoder, unet, scheduler).to("cuda")

    Args:
        resolution: 处理分辨率（256 适配 8GB，512 需 12GB+）
    """
    global _pipeline, _config, _resolution, _inference_steps

    # 已加载且分辨率未变 → 直接返回缓存
    if _pipeline is not None and _resolution == resolution:
        return _pipeline

    print(f"[LatentSync] 加载 pipeline resolution={resolution}")
    start = time.time()

    # 确保 LatentSync 项目根在 sys.path（CWD 应为 LatentSync 根目录）
    latentsync_root = Path(__file__).resolve().parent
    if str(latentsync_root) not in sys.path:
        sys.path.insert(0, str(latentsync_root))

    # 加载 U-Net 配置
    config_path = _config_path_for_resolution(resolution)
    config = OmegaConf.load(config_path)
    print(f"[LatentSync] 配置: {config_path} resolution={config.data.resolution}")

    # fp16 半精度（Blackwell sm_120 支持）
    is_fp16_supported = torch.cuda.is_available() and torch.cuda.get_device_capability()[0] > 7
    dtype = torch.float16 if is_fp16_supported else torch.float32
    print(f"[LatentSync] dtype={dtype} fp16_supported={is_fp16_supported}")

    # 1. DDIMScheduler
    from diffusers import AutoencoderKL, DDIMScheduler
    scheduler = DDIMScheduler.from_pretrained("configs")

    # 2. Audio2Feature（Whisper 音频编码器）
    # cross_attention_dim=384 → whisper tiny, 768 → whisper small
    if config.model.cross_attention_dim == 768:
        whisper_model_path = "checkpoints/whisper/small.pt"
    elif config.model.cross_attention_dim == 384:
        whisper_model_path = "checkpoints/whisper/tiny.pt"
    else:
        raise NotImplementedError("cross_attention_dim must be 768 or 384")

    from latentsync.whisper.audio2feature import Audio2Feature
    audio_encoder = Audio2Feature(
        model_path=whisper_model_path,
        device="cuda",
        num_frames=config.data.num_frames,
        audio_feat_length=config.data.audio_feat_length,
    )

    # 3. VAE（首次从 HuggingFace 下载，后续走缓存）
    vae = AutoencoderKL.from_pretrained("stabilityai/sd-vae-ft-mse", torch_dtype=dtype)
    vae.config.scaling_factor = 0.18215
    vae.config.shift_factor = 0

    # 4. U-Net
    from latentsync.models.unet import UNet3DConditionModel
    unet, _ = UNet3DConditionModel.from_pretrained(
        OmegaConf.to_container(config.model),
        config.ckpt.resume_ckpt_path,
        device="cpu",
    )
    unet = unet.to(dtype=dtype)

    # 5. LipsyncPipeline
    from latentsync.pipelines.lipsync_pipeline import LipsyncPipeline
    pipeline = LipsyncPipeline(
        vae=vae,
        audio_encoder=audio_encoder,
        unet=unet,
        scheduler=scheduler,
    ).to("cuda")

    _pipeline = pipeline
    _config = config
    _resolution = resolution

    elapsed = time.time() - start
    gpu = get_gpu_info()
    vram_used = torch.cuda.memory_allocated() / 1024**3 if torch.cuda.is_available() else 0
    print(
        f"[LatentSync] pipeline 加载完成 耗时={elapsed:.1f}s "
        f"GPU={gpu['name']} VRAM_used={vram_used:.2f}GB"
    )
    return _pipeline


@app.get("/api/health")
async def health():
    """健康检查"""
    gpu = get_gpu_info()
    return {
        "status": "ok",
        "gpu": gpu.get("name", "unknown"),
        "cuda_available": torch.cuda.is_available(),
        "vram_total_mb": gpu.get("vram_total_mb", 0),
        "model_loaded": _pipeline is not None,
        "resolution": _resolution,
        "inference_steps": _inference_steps,
    }


@app.post("/api/avatar/generate")
async def generate_avatar(
    audio: UploadFile = File(...),
    video: UploadFile = File(...),
    inference_steps: int = Form(25),
    resolution: int = Form(256),
    guidance_scale: float = Form(1.5),
    seed: int = Form(-1),
):
    """生成唇形同步视频

    LatentSync 是"视频驱动"模式：保留原视频动作，只替换嘴型（与 MuseTalk/Wav2Lip 一致）。

    Args:
        audio: 音频文件（wav，建议 16000Hz）
        video: 原始数字人视频（mp4，需含清晰正脸）
        inference_steps: 扩散步数（25 平衡，50 最高质量，10 最快）
        resolution: 处理分辨率（256 适配 8GB 显存，512 需 12GB+）
        guidance_scale: 引导强度（1.0-3.0，1.5 默认）
        seed: 随机种子（-1 随机，>=0 可复现）

    Returns:
        视频文件（mp4）
    """
    print(
        f"[LatentSync] 收到生成请求 steps={inference_steps} "
        f"resolution={resolution} seed={seed} "
        f"audio={audio.filename} video={video.filename}"
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        audio_path = tmpdir / "input_audio.wav"
        with open(audio_path, "wb") as f:
            content = await audio.read()
            f.write(content)

        video_path = tmpdir / "input_video.mp4"
        with open(video_path, "wb") as f:
            content = await video.read()
            f.write(content)

        output_path = tmpdir / "output_video.mp4"
        temp_dir = str(tmpdir / "temp")

        # 读取音频时长，用于预裁剪视频（减少不必要的帧解码）
        global _current_audio_duration
        try:
            import soundfile as sf
            audio_data, audio_sr = sf.read(str(audio_path))
            _current_audio_duration = len(audio_data) / audio_sr
            print(f"[LatentSync] 音频时长: {_current_audio_duration:.2f}s ({audio_sr}Hz)")
        except Exception as e:
            _current_audio_duration = 0.0
            print(f"[LatentSync] 无法读取音频时长（跳过预裁剪）: {e}")

        try:
            # 按请求分辨率加载/重建 pipeline（分辨率未变时复用缓存）
            pipeline = load_pipeline(resolution=resolution)
            config = _config
            start = time.time()

            # 设置随机种子
            if seed >= 0:
                torch.manual_seed(seed)
                if torch.cuda.is_available():
                    torch.cuda.manual_seed_all(seed)
            else:
                torch.seed()

            # fp16 dtype
            is_fp16_supported = torch.cuda.is_available() and torch.cuda.get_device_capability()[0] > 7
            dtype = torch.float16 if is_fp16_supported else torch.float32

            # 同步推理（在独立线程中执行，避免阻塞事件循环）
            import asyncio

            def _sync_infer():
                pipeline(
                    video_path=str(video_path),
                    audio_path=str(audio_path),
                    video_out_path=str(output_path),
                    num_frames=config.data.num_frames,
                    num_inference_steps=inference_steps,
                    guidance_scale=guidance_scale,
                    weight_dtype=dtype,
                    width=config.data.resolution,
                    height=config.data.resolution,
                    mask_image_path=config.data.mask_image_path,
                    temp_dir=temp_dir,
                )

            await asyncio.to_thread(_sync_infer)

            elapsed = time.time() - start
            if not output_path.exists():
                return JSONResponse(
                    {"error": "生成失败：输出文件不存在"},
                    status_code=500,
                )

            video_bytes = output_path.read_bytes()
            print(
                f"[LatentSync] 生成完成 耗时={elapsed:.1f}s size={len(video_bytes)} bytes"
            )

            return StreamingResponse(
                iter([video_bytes]),
                media_type="video/mp4",
                headers={
                    "Content-Disposition": 'attachment; filename="latentsync_output.mp4"',
                    "Content-Length": str(len(video_bytes)),
                    "X-Generation-Time": f"{elapsed:.1f}s",
                },
            )

        except Exception as e:
            import traceback
            traceback.print_exc()
            return JSONResponse(
                {"error": f"生成失败: {str(e)}", "traceback": traceback.format_exc()},
                status_code=500,
            )


def main():
    """启动服务"""
    global _resolution, _inference_steps

    parser = argparse.ArgumentParser(description="LatentSync Avatar Server")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8011, help="监听端口")
    parser.add_argument("--inference_steps", type=int, default=25, help="扩散步数（25 平衡）")
    parser.add_argument(
        "--resolution", type=int, default=256, choices=[256, 512],
        help="处理分辨率（256 适配 8GB 显存，512 需 12GB+）",
    )
    parser.add_argument("--preload", action="store_true", help="启动时预加载 pipeline")
    args = parser.parse_args()

    _resolution = args.resolution
    _inference_steps = args.inference_steps

    gpu = get_gpu_info()

    print("=" * 60)
    print("LatentSync 1.5 Avatar Server")
    print(f"  GPU: {gpu.get('name', 'N/A')}")
    print(f"  CUDA: {torch.cuda.is_available()}")
    print(f"  VRAM: {gpu.get('vram_total_mb', 0)} MB")
    print(f"  Inference Steps: {_inference_steps}")
    print(f"  Resolution: {_resolution}")
    print(f"  Listen: {args.host}:{args.port}")
    print("=" * 60)

    # Blackwell sm_120 兼容性提示
    if torch.cuda.is_available():
        cap = torch.cuda.get_device_capability(0)
        if cap[0] >= 12:  # sm_120+ = Blackwell（RTX 50 系列等）
            cuda_ver = float(torch.version.cuda) if torch.version.cuda else 0.0
            if cuda_ver < 12.8:
                print(
                    f"[警告] 检测到 Blackwell 架构(sm_{cap[0]}{cap[1]})，"
                    f"当前 PyTorch CUDA={torch.version.cuda}。"
                    f"Blackwell 需 PyTorch 2.7+cu128，否则推理会报 "
                    f"'no kernel image is available'"
                )

    # 8GB 显存建议 resolution=256
    vram = gpu.get("vram_total_mb", 0)
    if 0 < vram < 10240 and _resolution == 512:
        print(
            f"[警告] 显存 {vram}MB 跑 resolution=512 可能 OOM，"
            f"建议 --resolution 256"
        )

    if args.preload:
        print("[LatentSync] 预加载 pipeline...")
        load_pipeline(resolution=_resolution)

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
