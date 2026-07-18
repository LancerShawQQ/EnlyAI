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
import tempfile
import time
from pathlib import Path

import torch
import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

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
    """懒加载 MuseTalk 模型"""
    global _model, _preparation_func, _inference_func
    if _model is not None:
        return _model, _preparation_func, _inference_func

    print(f"[MuseTalk] 加载模型 version={_version} fp16={_use_float16}")
    start = time.time()

    # 导入 MuseTalk 模块（需在 MuseTalk 项目目录下运行）
    import sys
    sys.path.insert(0, str(Path(__file__).parent))

    from musetalk.utils.blending import get_image
    from musetalk.utils.preprocess import *
    from musetalk.utils.utils import *

    # 加载模型
    if _version == "v15":
        from musetalk.models.v15 import musetalk as musetalk_v15
        _model = musetalk_v15.MuseTalk()
        _inference_func = musetalk_v15.inference
        _preparation_func = musetalk_v15.prepare_materials
    else:
        from musetalk.models.v100 import musetalk as musetalk_v10
        _model = musetalk_v10.MuseTalk()
        _inference_func = musetalk_v10.inference
        _preparation_func = musetalk_v10.prepare_materials

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
            model, prep_func, infer_func = load_model()
            start = time.time()

            # 调用 MuseTalk 推理
            # 注意：具体接口需根据 MuseTalk 实际 API 调整
            video_bytes = await _run_musetalk_inference(
                model=model,
                prep_func=prep_func,
                infer_func=infer_func,
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
    prep_func,
    infer_func,
    audio_path: str,
    video_path: str,
    output_path: str,
    version: str,
    use_float16: bool,
    fps: int,
    bbox_shift: int,
):
    """执行 MuseTalk 推理

    注意：此函数需根据 MuseTalk 实际 API 调整。
    参考 MuseTalk 的 scripts/inference.py。
    """
    import asyncio

    def _sync_infer():
        """同步推理（在线程中运行避免阻塞事件循环）"""
        # TODO: 根据 MuseTalk 实际 API 调整
        # 以下为参考 scripts/inference.py 的伪代码框架
        #
        # # 1. 准备材料（加载模型权重、face解析器等）
        # materials = prep_func(model, ...)
        #
        # # 2. 从视频提取帧 + 人脸检测
        # frames = extract_frames(video_path, fps)
        # face_landmarks = detect_face_landmarks(frames)
        #
        # # 3. 音频特征提取（whisper）
        # audio_features = extract_audio_features(audio_path)
        #
        # # 4. 逐帧推理（唇形同步生成）
        # result_frames = []
        # for frame, landmark in zip(frames, face_landmarks):
        #     result = infer_func(model, frame, landmark, audio_features, ...)
        #     result_frames.append(result)
        #
        # # 5. 合成视频
        # frames_to_video(result_frames, audio_path, output_path, fps)
        # return Path(output_path).read_bytes()

        raise NotImplementedError(
            "MuseTalk 推理接口需根据实际模型 API 实现。"
            "请参考 MuseTalk 的 scripts/inference.py 调整 _run_musetalk_inference 函数。"
        )

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
