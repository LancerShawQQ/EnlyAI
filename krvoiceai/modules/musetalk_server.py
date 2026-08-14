"""MuseTalk 本地服务端

在独立 Python 3.10 conda 环境中运行，为 EnlyAI 提供 MuseTalk 数字人生成服务。

部署步骤：
1. conda create -n MuseTalk python==3.10 -y
2. conda activate MuseTalk
3. git clone https://github.com/TMElyralab/MuseTalk.git
4. cd MuseTalk
5. pip install torch==2.0.1 torchvision==0.15.2 --index-url https://download.pytorch.org/whl/cu118
6. pip install -r requirements.txt
7. pip install --no-cache-dir -U openmim && mim install mmengine "mmcv==2.0.1" "mmdet==3.1.0" "mmpose==1.1.0"
8. pip install fastapi uvicorn python-multipart
9. download_weights.bat  # 下载模型权重
10. 将本脚本复制到 MuseTalk 目录下
11. python musetalk_server.py --port 8010

硬件要求：
- 最低 4GB 显存（fp16 模式，官方 RTX 3050 Ti 实测）
- 2GB 显存（MX450）需额外优化，存在 OOM 风险
- 不支持纯 CPU 推理
- 推荐 8GB+ 系统内存

API：
- GET  /api/health          健康检查
- POST /api/avatar/generate 生成唇形同步视频
"""
from __future__ import annotations

import argparse
import copy
import glob
import os
import pickle
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import cv2
import numpy as np
import torch
import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse
from tqdm import tqdm

app = FastAPI(title="MuseTalk Avatar Server", version="1.0.0")

# 全局模型实例（懒加载）
_model = None
_preparation_func = None
_inference_func = None
_version = "v15"
_use_float16 = True


def get_gpu_info() -> dict:
    """获取 GPU 信息"""
    if not torch.cuda.is_available():
        return {"available": False, "name": "CPU only", "vram_total_mb": 0}
    props = torch.cuda.get_device_properties(0)
    return {
        "available": True,
        "name": props.name,
        "vram_total_mb": int(props.total_mem / 1024 / 1024),
    }


def load_model():
    """懒加载 MuseTalk 模型（vae, unet, pe, whisper, audio_processor, face_parser）

    Blackwell sm_120 兼容实现：
    - 使用 load_all_model 加载 vae/unet/pe（真实入口，非原桩里的 v15.musetalk）
    - 加载 WhisperModel 做音频特征提取
    - 加载 AudioProcessor / FaceParsing
    - mmpose 已在 preprocessing.py 中替换为 face_alignment，无需 mmcv
    """
    global _model, _preparation_func, _inference_func
    if _model is not None:
        return _model, _preparation_func, _inference_func

    print(f"[MuseTalk] 加载模型 version={_version} fp16={_use_float16}")
    start = time.time()

    # 导入 MuseTalk 模块（需在 MuseTalk 项目目录下运行，CWD=models 父目录）
    import sys
    # 确保 MuseTalk 项目根在 sys.path（models/ 在 CWD 下，preprocessing 用相对路径 ./models/dwpose）
    musetalk_root = Path(__file__).resolve().parent
    # 若脚本被复制到 MuseTalk 根目录运行，CWD 即 MuseTalk 根；否则需调用方保证 CWD
    sys.path.insert(0, str(musetalk_root))

    from musetalk.utils.blending import get_image
    from musetalk.utils.face_parsing import FaceParsing
    from musetalk.utils.audio_processor import AudioProcessor
    from musetalk.utils.utils import get_file_type, get_video_fps, datagen, load_all_model
    from musetalk.utils.preprocessing import get_landmark_and_bbox, read_imgs, coord_placeholder
    from transformers import WhisperModel

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    # 加载 vae/unet/pe（v15 模型权重路径，需 download_weights.bat 预先下载）
    unet_model_path = os.path.join("models", "musetalkV15", "unet.pth")
    unet_config = os.path.join("models", "musetalkV15", "musetalk.json")
    vae, unet, pe = load_all_model(
        unet_model_path=unet_model_path,
        vae_type="sd-vae",
        unet_config=unet_config,
        device=device,
    )
    timesteps = torch.tensor([0], device=device)

    # fp16 半精度（降低显存，Blackwell 8GB 宽裕）
    if _use_float16:
        pe = pe.half()
        vae.vae = vae.vae.half()
        unet.model = unet.model.half()

    pe = pe.to(device)
    vae.vae = vae.vae.to(device)
    unet.model = unet.model.to(device)

    # Whisper 音频特征提取（与 MuseTalk 训练一致的 whisper_dir）
    whisper_dir = os.path.join("models", "whisper")
    audio_processor = AudioProcessor(feature_extractor_path=whisper_dir)
    weight_dtype = unet.model.dtype
    whisper = WhisperModel.from_pretrained(whisper_dir)
    whisper = whisper.to(device=device, dtype=weight_dtype).eval()
    whisper.requires_grad_(False)

    # 人脸解析器（v15 带左右脸颊宽度参数）
    if _version == "v15":
        fp = FaceParsing(left_cheek_width=80, right_cheek_width=80)
    else:
        fp = FaceParsing()

    # 把所有组件打包到 _model dict（_preparation_func/_inference_func 保留兼容字段但不再使用）
    _model = {
        "vae": vae, "unet": unet, "pe": pe, "whisper": whisper,
        "audio_processor": audio_processor, "fp": fp, "timesteps": timesteps,
        "device": device, "weight_dtype": weight_dtype,
        "get_image": get_image, "get_landmark_and_bbox": get_landmark_and_bbox,
        "read_imgs": read_imgs, "coord_placeholder": coord_placeholder,
        "get_file_type": get_file_type, "get_video_fps": get_video_fps,
        "datagen": datagen,
    }
    _preparation_func = None  # 不再使用
    _inference_func = None     # 不再使用，直接在 _run_musetalk_inference 内联

    elapsed = time.time() - start
    gpu = get_gpu_info()
    print(f"[MuseTalk] 模型加载完成 耗时={elapsed:.1f}s GPU={gpu['name']}")
    return _model, _preparation_func, _inference_func


@app.get("/api/health")
async def health():
    """健康检查"""
    gpu = get_gpu_info()
    return {
        "status": "ok",
        "gpu": gpu.get("name", "unknown"),
        "cuda_available": torch.cuda.is_available(),
        "vram_total_mb": gpu.get("vram_total_mb", 0),
        "model_loaded": _model is not None,
        "version": _version,
        "use_float16": _use_float16,
    }


@app.post("/api/avatar/generate")
async def generate_avatar(
    audio: UploadFile = File(...),
    video: UploadFile = File(...),
    version: str = Form("v15"),
    use_float16: str = Form("true"),
    fps: int = Form(25),
    bbox_shift: int = Form(5),
):
    """生成唇形同步视频

    MuseTalk 是"视频驱动"模式：保留原视频动作，只替换嘴型。

    Args:
        audio: 音频文件（wav）
        video: 原始数字人视频（mp4）
        version: v15（推荐）或 v10
        use_float16: 启用 fp16（降低显存）
        fps: 输出帧率
        bbox_shift: 人脸裁剪框偏移

    Returns:
        视频文件（mp4）
    """
    print(
        f"[MuseTalk] 收到生成请求 version={version} fp16={use_float16} "
        f"fps={fps} audio={audio.filename} video={video.filename}"
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

        try:
            model, _, _ = load_model()
            start = time.time()

            # 调用 MuseTalk 推理（model 是包含 vae/unet/pe/whisper/... 的 dict）
            video_bytes = await _run_musetalk_inference(
                model=model,
                audio_path=str(audio_path),
                video_path=str(video_path),
                output_path=str(output_path),
                version=version,
                use_float16=use_float16.lower() == "true",
                fps=fps,
                bbox_shift=bbox_shift,
            )

            elapsed = time.time() - start
            print(f"[MuseTalk] 生成完成 耗时={elapsed:.1f}s size={len(video_bytes)} bytes")

            return StreamingResponse(
                iter([video_bytes]),
                media_type="video/mp4",
                headers={
                    "Content-Disposition": 'attachment; filename="musetalk_output.mp4"',
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


async def _run_musetalk_inference(
    model,
    audio_path: str,
    video_path: str,
    output_path: str,
    version: str,
    use_float16: bool,
    fps: int,
    bbox_shift: int,
):
    """执行 MuseTalk 推理（复刻 scripts/inference.py 流程）

    流程：
    1. ffmpeg 从视频提帧
    2. 音频特征提取（whisper chunks）
    3. 人脸 landmark + bbox（face_alignment 替代 mmpose）
    4. 逐帧 crop → 256x256 → VAE latent
    5. 批量推理：pe(whisper) → unet → vae.decode
    6. 贴回原帧 + face parsing 融合
    7. ffmpeg 合成视频 + 合并音频
    """
    import asyncio

    def _sync_infer():
        m = model
        vae, unet, pe = m["vae"], m["unet"], m["pe"]
        whisper = m["whisper"]
        audio_processor = m["audio_processor"]
        fp = m["fp"]
        timesteps = m["timesteps"]
        device = m["device"]
        weight_dtype = m["weight_dtype"]
        get_image = m["get_image"]
        get_landmark_and_bbox = m["get_landmark_and_bbox"]
        read_imgs = m["read_imgs"]
        coord_placeholder = m["coord_placeholder"]
        get_file_type = m["get_file_type"]
        get_video_fps = m["get_video_fps"]
        datagen = m["datagen"]

        # v15 用固定 bbox_shift=0，v10 用传入的 bbox_shift
        if version == "v15":
            bbox_shift = 0
        extra_margin = 5  # v15 默认下边距扩展

        # 1. 提帧
        tmp_frames_dir = output_path + "_frames"
        os.makedirs(tmp_frames_dir, exist_ok=True)
        if get_file_type(video_path) == "video":
            save_dir_full = output_path + "_src"
            os.makedirs(save_dir_full, exist_ok=True)
            cmd = f'ffmpeg -v fatal -i "{video_path}" -start_number 0 "{save_dir_full}/%08d.png"'
            os.system(cmd)
            input_img_list = sorted(glob.glob(os.path.join(save_dir_full, '*.[jpJP][pnPN]*[gG]')))
            fps = get_video_fps(video_path) or fps
        elif get_file_type(video_path) == "image":
            input_img_list = [video_path]
        else:
            raise ValueError(f"unsupported video_path: {video_path}")

        # 2. 音频特征
        whisper_input_features, librosa_length = audio_processor.get_audio_feature(audio_path)
        whisper_chunks = audio_processor.get_whisper_chunk(
            whisper_input_features, device, weight_dtype, whisper, librosa_length,
            fps=fps,
            audio_padding_length_left=2,
            audio_padding_length_right=2,
        )

        # 3. landmark + bbox
        coord_list, frame_list = get_landmark_and_bbox(input_img_list, bbox_shift)

        # 4. 逐帧 crop → 256x256 → VAE latent
        input_latent_list = []
        for bbox, frame in zip(coord_list, frame_list):
            if bbox == coord_placeholder:
                continue
            x1, y1, x2, y2 = bbox
            if version == "v15":
                y2 = y2 + extra_margin
                y2 = min(y2, frame.shape[0])
            crop_frame = frame[y1:y2, x1:x2]
            crop_frame = cv2.resize(crop_frame, (256, 256), interpolation=cv2.INTER_LANCZOS4)
            latents = vae.get_latents_for_unet(crop_frame)
            input_latent_list.append(latents)

        # 帧循环（首尾相接做平滑）
        frame_list_cycle = frame_list + frame_list[::-1]
        coord_list_cycle = coord_list + coord_list[::-1]
        input_latent_list_cycle = input_latent_list + input_latent_list[::-1]

        # 5. 批量推理
        video_num = len(whisper_chunks)
        batch_size = 8
        gen = datagen(
            whisper_chunks=whisper_chunks,
            vae_encode_latents=input_latent_list_cycle,
            batch_size=batch_size,
            delay_frame=0,
            device=device,
        )
        res_frame_list = []
        total = int(np.ceil(float(video_num) / batch_size))
        for whisper_batch, latent_batch in tqdm(gen, total=total, desc="MuseTalk infer"):
            audio_feature_batch = pe(whisper_batch)
            latent_batch = latent_batch.to(dtype=unet.model.dtype)
            pred_latents = unet.model(
                latent_batch, timesteps, encoder_hidden_states=audio_feature_batch
            ).sample
            recon = vae.decode_latents(pred_latents)
            for res_frame in recon:
                res_frame_list.append(res_frame)

        # 6. 贴回原帧 + face parsing 融合
        result_img_dir = output_path + "_result"
        os.makedirs(result_img_dir, exist_ok=True)
        for i, res_frame in enumerate(tqdm(res_frame_list, desc="MuseTalk blend")):
            bbox = coord_list_cycle[i % len(coord_list_cycle)]
            ori_frame = copy.deepcopy(frame_list_cycle[i % len(frame_list_cycle)])
            x1, y1, x2, y2 = bbox
            if version == "v15":
                y2 = y2 + extra_margin
                y2 = min(y2, ori_frame.shape[0])
            try:
                res_frame = cv2.resize(res_frame.astype(np.uint8), (x2 - x1, y2 - y1))
            except Exception:
                continue
            if version == "v15":
                combine_frame = get_image(ori_frame, res_frame, [x1, y1, x2, y2], mode="patch", fp=fp)
            else:
                combine_frame = get_image(ori_frame, res_frame, [x1, y1, x2, y2], fp=fp)
            cv2.imwrite(f"{result_img_dir}/{str(i).zfill(8)}.png", combine_frame)

        # 7. ffmpeg 合成视频 + 合并音频
        temp_vid = output_path + "_temp.mp4"
        cmd_img2video = (
            f'ffmpeg -y -v warning -r {fps} -f image2 -i "{result_img_dir}/%08d.png" '
            f'-vcodec libx264 -vf format=yuv420p -crf 18 "{temp_vid}"'
        )
        os.system(cmd_img2video)
        cmd_combine = f'ffmpeg -y -v warning -i "{audio_path}" -i "{temp_vid}" "{output_path}"'
        os.system(cmd_combine)

        # 清理临时目录
        shutil.rmtree(result_img_dir, ignore_errors=True)
        shutil.rmtree(tmp_frames_dir, ignore_errors=True)
        if os.path.exists(temp_vid):
            os.remove(temp_vid)
        if os.path.isdir(save_dir_full):
            shutil.rmtree(save_dir_full, ignore_errors=True)

        return Path(output_path).read_bytes()

    return await asyncio.to_thread(_sync_infer)


def main():
    """启动服务"""
    global _version, _use_float16

    parser = argparse.ArgumentParser(description="MuseTalk Avatar Server")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8010, help="监听端口")
    parser.add_argument("--version", default="v15", choices=["v15", "v10"], help="模型版本")
    parser.add_argument("--use_float16", action="store_true", default=True, help="启用 fp16")
    parser.add_argument("--preload", action="store_true", help="启动时预加载模型")
    args = parser.parse_args()

    _version = args.version
    _use_float16 = args.use_float16

    gpu = get_gpu_info()

    print("=" * 60)
    print("MuseTalk Avatar Server")
    print(f"  GPU: {gpu.get('name', 'N/A')}")
    print(f"  CUDA: {torch.cuda.is_available()}")
    print(f"  VRAM: {gpu.get('vram_total_mb', 0)} MB")
    print(f"  Version: {_version}")
    print(f"  FP16: {_use_float16}")
    print(f"  Listen: {args.host}:{args.port}")
    print("=" * 60)

    # 2GB 显存警告
    vram = gpu.get("vram_total_mb", 0)
    if vram > 0 and vram < 4096:
        print(f"[警告] 显存仅 {vram}MB，低于官方推荐 4GB，可能 OOM")
        print("[建议] 确保使用 --use_float16，关闭其他 GPU 程序")

    if args.preload:
        print("[MuseTalk] 预加载模型...")
        load_model()

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
