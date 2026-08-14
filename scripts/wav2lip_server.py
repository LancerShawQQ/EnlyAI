"""Wav2Lip 唇形同步服务（常驻进程，模型加载一次复用）

将 Wav2Lip 推理从"每次启动子进程"改为"常驻 HTTP 服务"，节省每次 ~19.5 分钟的
模型加载 + CUDA 上下文初始化固定开销。

启动方式：
    wav2lip_env/Scripts/python.exe wav2lip_server.py \\
        --port 8011 \\
        --checkpoint_path checkpoints/wav2lip_gan.pth \\
        --face_det_batch_size 2 \\
        --wav2lip_batch_size 2

接口：
    GET  /health    健康检查（启动期间 ready=false，加载完成后 ready=true）
    POST /generate  生成唇形同步视频（串行处理，PyTorch 非线程安全）
    POST /shutdown  优雅关闭

注意：
    - 必须用 wav2lip_env 的 Python 3.8 解释器运行
    - 工作目录必须是 Wav2Lip 根目录（与 inference.py 一致，依赖相对路径）
    - PyTorch 模型非线程安全，并发请求用 threading.Lock 串行化
"""
from __future__ import annotations

import argparse
import os
import platform
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, List, Optional, Tuple

import numpy as np
import scipy
import cv2
import torch

# Wav2Lip 自有模块（必须在 Wav2Lip 根目录运行）
import audio
import face_detection
from models import Wav2Lip

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import uvicorn


# ============================================================================
# 全局状态
# ============================================================================

class ServerState:
    """服务全局状态（单例）"""

    def __init__(self):
        self.ready: bool = False
        self.loading: bool = False
        self.loading_progress: str = ""
        self.device: str = "cpu"
        self.model: Optional[torch.nn.Module] = None
        self.face_detector: Optional[Any] = None
        self.checkpoint_path: str = ""
        self.face_det_batch_size: int = 2
        self.wav2lip_batch_size: int = 2
        self.img_size: int = 96
        # 串行锁：PyTorch 模型非线程安全，并发请求必须排队
        self.inference_lock = threading.Lock()
        self.start_time: float = time.time()
        self.request_count: int = 0
        self.last_error: Optional[str] = None


state = ServerState()


# ============================================================================
# 模型加载（复用 inference.py 的 load_model 逻辑）
# ============================================================================

def _load_checkpoint(checkpoint_path: str, device: str):
    """加载 checkpoint"""
    if device == "cuda":
        return torch.load(checkpoint_path)
    else:
        return torch.load(
            checkpoint_path,
            map_location=lambda storage, loc: storage,
        )


def load_model(path: str, device: str) -> torch.nn.Module:
    """加载 Wav2Lip 模型"""
    print(f"[wav2lip_server] Load checkpoint from: {path}")
    checkpoint = _load_checkpoint(path, device)
    s = checkpoint["state_dict"]
    new_s = {}
    for k, v in s.items():
        new_s[k.replace("module.", "")] = v
    model = Wav2Lip()
    model.load_state_dict(new_s)
    model = model.to(device)
    print(f"[wav2lip_server] Model loaded on {device}")
    return model.eval()


def init_face_detector(device: str):
    """初始化人脸检测器（S3FD）"""
    print(f"[wav2lip_server] Initializing face detector on {device}...")
    detector = face_detection.FaceAlignment(
        face_detection.LandmarksType._2D,
        flip_input=False,
        device=device,
    )
    print(f"[wav2lip_server] Face detector ready")
    return detector


# ============================================================================
# 推理核心逻辑（复用 inference.py，但复用常驻模型/检测器）
# ============================================================================

def get_smoothened_boxes(boxes, T):
    """居中窗口平滑：以当前帧为中心取前后 T//2 帧"""
    new_boxes = boxes.copy()
    half = T // 2
    for i in range(len(boxes)):
        start = max(0, i - half)
        end = min(len(boxes), i + half + 1)
        window = new_boxes[start:end]
        boxes[i] = np.mean(window, axis=0)
    return boxes


def create_face_blend_mask(h, w):
    """创建聚焦嘴部区域的羽化融合遮罩（与 inference.py 一致）"""
    mask = np.zeros((h, w), dtype=np.float32)
    focus_start = int(h * 0.35)
    mask[focus_start:, :] = 1.0
    feather_h = max(1, int(h * 0.15))
    for i in range(max(0, focus_start - feather_h), focus_start):
        alpha = (i - (focus_start - feather_h)) / feather_h
        mask[i, :] = alpha
    edge_w = max(1, int(w * 0.12))
    for i in range(edge_w):
        alpha = i / edge_w
        mask[:, i] *= alpha
        mask[:, w - 1 - i] *= alpha
    return mask


def face_detect(images, detector, batch_size, pads):
    """人脸检测（复用常驻 detector）"""
    pady1, pady2, padx1, padx2 = pads
    while True:
        predictions = []
        try:
            for i in range(0, len(images), batch_size):
                batch = np.array(images[i:i + batch_size])
                predictions.extend(detector.get_detections_for_batch(batch))
        except RuntimeError:
            if batch_size == 1:
                raise RuntimeError(
                    "Image too big to run face detection on GPU. "
                    "Please use a larger --resize_factor argument"
                )
            batch_size //= 2
            print(f"[wav2lip_server] OOM, reducing face_det_batch to {batch_size}")
            continue
        break

    results = []
    for rect, image in zip(predictions, images):
        if rect is None:
            cv2.imwrite("temp/faulty_frame.jpg", image)
            raise ValueError(
                "Face not detected! Ensure the video contains a face in all frames."
            )
        y1 = max(0, rect[1] - pady1)
        y2 = min(image.shape[0], rect[3] + pady2)
        x1 = max(0, rect[0] - padx1)
        x2 = min(image.shape[1], rect[2] + padx2)
        results.append([x1, y1, x2, y2])

    boxes = np.array(results)
    boxes = get_smoothened_boxes(boxes, T=5)
    results = [
        [image[y1:y2, x1:x2], (y1, y2, x1, x2)]
        for image, (x1, y1, x2, y2) in zip(images, boxes)
    ]
    return results


def datagen(frames, mels, face_det_results, img_size, batch_size, static, box):
    """生成推理 batch（与 inference.py 一致）"""
    img_batch, mel_batch, frame_batch, coords_batch = [], [], [], []

    for i, m in enumerate(mels):
        idx = 0 if static else i % len(frames)
        frame_to_save = frames[idx].copy()
        face, coords = face_det_results[idx].copy()

        face = cv2.resize(face, (img_size, img_size))

        img_batch.append(face)
        mel_batch.append(m)
        frame_batch.append(frame_to_save)
        coords_batch.append(coords)

        if len(img_batch) >= batch_size:
            img_batch, mel_batch = np.asarray(img_batch), np.asarray(mel_batch)

            img_masked = img_batch.copy()
            img_masked[:, img_size // 2:] = 0

            img_batch = np.concatenate((img_masked, img_batch), axis=3) / 255.
            mel_batch = np.reshape(
                mel_batch,
                [len(mel_batch), mel_batch.shape[1], mel_batch.shape[2], 1],
            )

            yield img_batch, mel_batch, frame_batch, coords_batch
            img_batch, mel_batch, frame_batch, coords_batch = [], [], [], []

    if len(img_batch) > 0:
        img_batch, mel_batch = np.asarray(img_batch), np.asarray(mel_batch)

        img_masked = img_batch.copy()
        img_masked[:, img_size // 2:] = 0

        img_batch = np.concatenate((img_masked, img_batch), axis=3) / 255.
        mel_batch = np.reshape(
            mel_batch,
            [len(mel_batch), mel_batch.shape[1], mel_batch.shape[2], 1],
        )

        yield img_batch, mel_batch, frame_batch, coords_batch


def run_inference(
    face_path: str,
    audio_path: str,
    outfile_path: str,
    pads: List[int],
    resize_factor: int,
    nosmooth: bool,
    fps_override: float = 25.0,
) -> dict:
    """执行完整 Wav2Lip 推理流程

    与 inference.py main() 等价，但复用全局 model + face_detector。
    """
    start_time = time.time()
    state.request_count += 1
    request_id = state.request_count

    print(f"[wav2lip_server] #{request_id} start: face={Path(face_path).name} "
          f"audio={Path(audio_path).name} -> {Path(outfile_path).name}")

    # 1. 读取视频帧（或静态图片）
    if not os.path.isfile(face_path):
        raise FileNotFoundError(f"--face 路径不存在: {face_path}")

    is_static = False
    if face_path.split(".")[-1].lower() in ["jpg", "png", "jpeg"]:
        is_static = True
        full_frames = [cv2.imread(face_path)]
        fps = fps_override
    else:
        video_stream = cv2.VideoCapture(face_path)
        fps = video_stream.get(cv2.CAP_PROP_FPS)
        if not fps or fps <= 0:
            fps = fps_override
        print(f"[wav2lip_server] #{request_id} Reading video frames...")
        full_frames = []
        while True:
            still_reading, frame = video_stream.read()
            if not still_reading:
                video_stream.release()
                break
            if resize_factor > 1:
                frame = cv2.resize(
                    frame,
                    (frame.shape[1] // resize_factor, frame.shape[0] // resize_factor),
                )
            full_frames.append(frame)

    print(f"[wav2lip_server] #{request_id} frames={len(full_frames)} fps={fps}")

    # 2. 准备音频（Wav2Lip 需要 wav 格式）
    if not audio_path.endswith(".wav"):
        temp_wav = "temp/temp.wav"
        command = f'ffmpeg -y -i {audio_path} -strict -2 {temp_wav}'
        subprocess.call(command, shell=platform.system() != "Windows")
        audio_path = temp_wav

    wav = audio.load_wav(audio_path, 16000)
    mel = audio.melspectrogram(wav)

    if np.isnan(mel.reshape(-1)).sum() > 0:
        raise ValueError(
            "Mel contains nan! Using a TTS voice? "
            "Add a small epsilon noise to the wav file and try again"
        )

    # 3. 切分 mel chunk
    mel_step_size = 16
    mel_chunks = []
    mel_idx_multiplier = 80.0 / fps
    i = 0
    while True:
        start_idx = int(i * mel_idx_multiplier)
        if start_idx + mel_step_size > len(mel[0]):
            mel_chunks.append(mel[:, len(mel[0]) - mel_step_size:])
            break
        mel_chunks.append(mel[:, start_idx: start_idx + mel_step_size])
        i += 1

    print(f"[wav2lip_server] #{request_id} mel_chunks={len(mel_chunks)}")

    full_frames = full_frames[:len(mel_chunks)]

    # 4. 人脸检测
    if is_static:
        face_det_results = face_detect(
            [full_frames[0]], state.face_detector,
            state.face_det_batch_size, pads,
        )
    else:
        face_det_results = face_detect(
            full_frames, state.face_detector,
            state.face_det_batch_size, pads,
        )

    # 5. 推理循环
    batch_size = state.wav2lip_batch_size
    gen = datagen(
        full_frames.copy(), mel_chunks, face_det_results,
        state.img_size, batch_size, is_static, [-1, -1, -1, -1],
    )

    frame_h, frame_w = full_frames[0].shape[:-1]
    out = cv2.VideoWriter(
        "temp/result.avi",
        cv2.VideoWriter_fourcc(*"DIVX"),
        fps, (frame_w, frame_h),
    )

    total_batches = int(np.ceil(float(len(mel_chunks)) / batch_size))
    processed_batches = 0

    for img_batch, mel_batch, frames, coords in gen:
        img_batch = torch.FloatTensor(
            np.transpose(img_batch, (0, 3, 1, 2))
        ).to(state.device)
        mel_batch = torch.FloatTensor(
            np.transpose(mel_batch, (0, 3, 1, 2))
        ).to(state.device)

        with torch.no_grad():
            pred = state.model(mel_batch, img_batch)

        pred = pred.cpu().numpy().transpose(0, 2, 3, 1) * 255.

        for p, f, c in zip(pred, frames, coords):
            y1, y2, x1, x2 = c
            p = cv2.resize(p.astype(np.uint8), (x2 - x1, y2 - y1))

            # 羽化嘴部聚焦融合（与 inference.py 一致）
            box_h, box_w = y2 - y1, x2 - x1
            blend_mask = create_face_blend_mask(box_h, box_w)
            mask_3ch = np.stack([blend_mask] * 3, axis=-1)
            orig_region = f[y1:y2, x1:x2].astype(np.float32)
            gen_region = p.astype(np.float32)
            f[y1:y2, x1:x2] = (
                gen_region * mask_3ch + orig_region * (1.0 - mask_3ch)
            ).astype(np.uint8)
            out.write(f)

        processed_batches += 1
        if processed_batches % 10 == 0:
            print(f"[wav2lip_server] #{request_id} progress: "
                  f"{processed_batches}/{total_batches} batches")

    out.release()
    print(f"[wav2lip_server] #{request_id} inference done, muxing audio...")

    # 6. 合成音频
    command = 'ffmpeg -y -i {} -i {} -strict -2 -q:v 1 {}'.format(
        audio_path, "temp/result.avi", outfile_path
    )
    subprocess.call(command, shell=platform.system() != "Windows")

    if not os.path.isfile(outfile_path):
        raise RuntimeError(f"推理完成但输出文件不存在: {outfile_path}")

    duration = time.time() - start_time
    outfile_size = os.path.getsize(outfile_path) // 1024

    print(f"[wav2lip_server] #{request_id} done: {Path(outfile_path).name} "
          f"({outfile_size}KB) duration={duration:.1f}s")

    return {
        "success": True,
        "outfile": outfile_path,
        "duration": duration,
        "frames": len(full_frames),
        "size_kb": outfile_size,
    }


# ============================================================================
# FastAPI 服务
# ============================================================================

app = FastAPI(title="Wav2Lip Server", version="1.0")


class GenerateRequest(BaseModel):
    """生成请求"""
    face_path: str
    audio_path: str
    outfile_path: str
    pads: List[int] = [0, 10, 0, 0]
    resize_factor: int = 1
    nosmooth: bool = False
    fps: float = 25.0


@app.get("/health")
def health():
    """健康检查"""
    return JSONResponse({
        "ready": state.ready,
        "loading": state.loading,
        "progress": state.loading_progress,
        "device": state.device,
        "model": Path(state.checkpoint_path).name if state.checkpoint_path else "",
        "face_det_batch": state.face_det_batch_size,
        "wav2lip_batch": state.wav2lip_batch_size,
        "uptime": int(time.time() - state.start_time),
        "requests": state.request_count,
        "last_error": state.last_error,
    })


@app.post("/generate")
def generate(req: GenerateRequest):
    """生成唇形同步视频（串行处理）"""
    if not state.ready:
        raise HTTPException(
            status_code=503,
            detail=f"服务未就绪: ready={state.ready} loading={state.loading}",
        )

    # 串行化：PyTorch 模型非线程安全
    acquired = state.inference_lock.acquire(timeout=1800)  # 最长等 30 分钟
    if not acquired:
        raise HTTPException(
            status_code=503,
            detail="服务繁忙，上一个请求未完成（等待 30 分钟超时）",
        )

    try:
        # 验证输入文件存在
        if not os.path.isfile(req.face_path):
            raise HTTPException(
                status_code=400,
                detail=f"face_path 不存在: {req.face_path}",
            )
        if not os.path.isfile(req.audio_path):
            raise HTTPException(
                status_code=400,
                detail=f"audio_path 不存在: {req.audio_path}",
            )

        # 确保输出目录存在
        outfile_dir = os.path.dirname(req.outfile_path)
        if outfile_dir and not os.path.isdir(outfile_dir):
            os.makedirs(outfile_dir, exist_ok=True)

        # 确保 temp 目录存在
        os.makedirs("temp", exist_ok=True)

        result = run_inference(
            face_path=req.face_path,
            audio_path=req.audio_path,
            outfile_path=req.outfile_path,
            pads=req.pads,
            resize_factor=req.resize_factor,
            nosmooth=req.nosmooth,
            fps_override=req.fps,
        )
        return JSONResponse(result)

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        tb = traceback.format_exc()
        state.last_error = str(e)
        print(f"[wav2lip_server] ERROR: {e}\n{tb}")
        raise HTTPException(status_code=500, detail=f"推理失败: {e}")
    finally:
        state.inference_lock.release()


@app.post("/shutdown")
def shutdown():
    """优雅关闭"""
    print("[wav2lip_server] Shutdown requested")
    # 在另一个线程中延迟关闭，让响应能正常返回
    def _do_shutdown():
        time.sleep(1)
        os._exit(0)
    threading.Thread(target=_do_shutdown, daemon=True).start()
    return JSONResponse({"success": True, "message": "shutting down"})


# ============================================================================
# 启动逻辑
# ============================================================================

def detect_device() -> str:
    """检测推理设备"""
    if torch.cuda.is_available():
        gpu_name = torch.cuda.get_device_name(0)
        vram_gb = torch.cuda.get_device_properties(0).total_memory // (1024 ** 3)
        print(f"[wav2lip_server] CUDA detected: {gpu_name} ({vram_gb}GB)")
        return "cuda"
    else:
        print("[wav2lip_server] CUDA not available, using CPU")
        return "cpu"


def auto_select_batch_size(device: str, configured_face: int, configured_wav2lip: int) -> Tuple[int, int]:
    """根据 GPU 显存动态选择 batch_size（与 avatar_engine.py 逻辑一致）"""
    if device != "cuda":
        return configured_face, configured_wav2lip

    try:
        vram_gb = torch.cuda.get_device_properties(0).total_memory // (1024 ** 3)
    except Exception:
        vram_gb = 0

    if vram_gb >= 8:
        face_batch = max(configured_face, 8)
        wav2lip_batch = max(configured_wav2lip, 16)
    elif vram_gb >= 4:
        face_batch = max(configured_face, 4)
        wav2lip_batch = max(configured_wav2lip, 8)
    else:
        # 低显存 GPU（如 MX450 2GB）：用配置值
        face_batch = configured_face
        wav2lip_batch = configured_wav2lip

    print(f"[wav2lip_server] GPU VRAM={vram_gb}GB -> "
          f"face_det_batch={face_batch}, wav2lip_batch={wav2lip_batch}")
    return face_batch, wav2lip_batch


def load_models_background(checkpoint_path: str, device: str,
                           face_det_batch: int, wav2lip_batch: int):
    """后台加载模型（不阻塞 uvicorn 启动）"""
    def _load():
        try:
            state.loading = True
            state.loading_progress = "loading Wav2Lip model..."

            # 1. 加载模型
            state.model = load_model(checkpoint_path, device)
            state.checkpoint_path = checkpoint_path

            # 2. 初始化人脸检测器
            state.loading_progress = "initializing face detector..."
            state.face_detector = init_face_detector(device)

            # 3. 确定 batch_size
            state.face_det_batch_size, state.wav2lip_batch_size = (
                auto_select_batch_size(device, face_det_batch, wav2lip_batch)
            )

            state.device = device
            state.loading = False
            state.ready = True
            state.loading_progress = "ready"
            print(f"[wav2lip_server] Service ready on {device}, "
                  f"face_batch={state.face_det_batch_size}, "
                  f"wav2lip_batch={state.wav2lip_batch_size}")
        except Exception as e:
            import traceback
            tb = traceback.format_exc()
            state.loading = False
            state.loading_progress = f"load failed: {e}"
            state.last_error = str(e)
            print(f"[wav2lip_server] FATAL: model load failed: {e}\n{tb}")

    t = threading.Thread(target=_load, daemon=True)
    t.start()


def main():
    parser = argparse.ArgumentParser(description="Wav2Lip 唇形同步常驻服务")
    parser.add_argument("--port", type=int, default=8011,
                        help="服务端口（默认 8011）")
    parser.add_argument("--host", type=str, default="127.0.0.1",
                        help="监听地址（默认 127.0.0.1，仅本地访问）")
    parser.add_argument("--checkpoint_path", type=str, required=True,
                        help="Wav2Lip checkpoint 路径")
    parser.add_argument("--device", type=str, default="auto",
                        choices=["auto", "cuda", "cpu"],
                        help="推理设备（默认 auto）")
    parser.add_argument("--face_det_batch_size", type=int, default=2,
                        help="人脸检测 batch size（默认 2）")
    parser.add_argument("--wav2lip_batch_size", type=int, default=2,
                        help="Wav2Lip 推理 batch size（默认 2）")
    args = parser.parse_args()

    # 确保 temp 目录存在
    os.makedirs("temp", exist_ok=True)

    # 检测设备
    if args.device == "auto":
        device = detect_device()
    else:
        device = args.device

    print(f"[wav2lip_server] Starting on port={args.port} device={device}")
    print(f"[wav2lip_server] checkpoint={args.checkpoint_path}")

    # 后台加载模型（不阻塞 uvicorn 启动，客户端可通过 /health 查询就绪状态）
    load_models_background(
        checkpoint_path=args.checkpoint_path,
        device=device,
        face_det_batch=args.face_det_batch_size,
        wav2lip_batch=args.wav2lip_batch_size,
    )

    # 启动 HTTP 服务
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
