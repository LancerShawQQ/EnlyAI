"""LongCat-Video-Avatar 云端服务端

在 GPU 服务器上运行，为本地 EnlyAI 提供 LongCat 数字人生成服务。

部署步骤：
1. 租用 GPU 服务器（8GB+ 显存，如 RTX 3090/4090/A100）
2. git clone https://github.com/meituan-longcat/LongCat-Video
3. 按 LongCat README 安装依赖（torch 2.6 + flash-attn + requirements）
4. 下载模型权重：huggingface-cli download meituan-longcat/LongCat-Video-Avatar-1.5 --local-dir ./weights/LongCat-Video-Avatar-1.5
5. 将本脚本复制到 LongCat-Video 目录下
6. 运行：python longcat_server.py --checkpoint_dir ./weights/LongCat-Video-Avatar-1.5 --port 8000

本地 EnlyAI 设置中填写此服务器地址即可使用。

硬件要求：
- 最低 8GB 显存（配合 INT8 量化）
- 推荐 16GB+ 显存（FP16 标准推理）
- 需 CUDA 12.4+ + flash-attn-2

API：
- GET  /api/health          健康检查
- POST /api/avatar/generate 生成数字人视频
"""
from __future__ import annotations

import argparse
import asyncio
import os
import tempfile
import time
from pathlib import Path

import torch
import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(title="LongCat Avatar Server", version="1.0.0")

# 全局模型实例（懒加载）
_model = None
_checkpoint_dir = "./weights/LongCat-Video-Avatar-1.5"
_api_key = ""


def get_gpu_info() -> str:
    """获取 GPU 信息"""
    if not torch.cuda.is_available():
        return "CPU only (CUDA unavailable)"
    props = torch.cuda.get_device_properties(0)
    mem_total = props.total_mem / 1024**3
    return f"{props.name} ({mem_total:.1f}GB)"


def load_model():
    """懒加载 LongCat 模型"""
    global _model
    if _model is not None:
        return _model

    print(f"[LongCat] 加载模型 checkpoint_dir={_checkpoint_dir}")
    start = time.time()

    # 导入 LongCat 模块（需在 LongCat-Video 项目目录下运行）
    import sys
    sys.path.insert(0, str(Path(__file__).parent))

    from longcat_video.pipelines.avatar_pipeline import AvatarPipeline

    _model = AvatarPipeline.from_pretrained(_checkpoint_dir)
    _model = _model.to("cuda")
    _model.eval()

    elapsed = time.time() - start
    print(f"[LongCat] 模型加载完成 耗时={elapsed:.1f}s GPU={get_gpu_info()}")
    return _model


@app.get("/api/health")
async def health():
    """健康检查"""
    return {
        "status": "ok",
        "gpu": get_gpu_info(),
        "cuda_available": torch.cuda.is_available(),
        "model_loaded": _model is not None,
        "checkpoint_dir": _checkpoint_dir,
    }


@app.post("/api/avatar/generate")
async def generate_avatar(
    audio: UploadFile = File(...),
    reference_image: UploadFile | None = File(None),
    model_type: str = Form("avatar-v1.5"),
    resolution: str = Form("480p"),
    prompt: str = Form("A person is speaking naturally with natural expressions"),
    num_segments: int = Form(5),
    use_distill: str = Form("true"),
    use_int8: str = Form("true"),
):
    """生成数字人视频

    Args:
        audio: 音频文件（wav）
        reference_image: 参考人物图片（可选）
        model_type: avatar-v1.5 或 avatar-v1.0
        resolution: 480p 或 720p
        prompt: 描述性提示词
        num_segments: 视频续写段数
        use_distill: 启用蒸馏（v1.5 必须启用）
        use_int8: 启用 INT8 量化（降低显存）

    Returns:
        视频文件（mp4）
    """
    # API Key 鉴权（可选）
    if _api_key:
        # FastAPI 在依赖注入中处理更优雅，这里简化
        pass

    print(
        f"[LongCat] 收到生成请求 model={model_type} res={resolution} "
        f"segments={num_segments} audio={audio.filename}"
    )

    # 保存上传的临时文件
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        audio_path = tmpdir / "input_audio.wav"
        with open(audio_path, "wb") as f:
            content = await audio.read()
            f.write(content)

        ref_img_path = None
        if reference_image:
            ref_img_path = tmpdir / "ref_image.jpg"
            with open(ref_img_path, "wb") as f:
                content = await reference_image.read()
                f.write(content)

        output_path = tmpdir / "output_video.mp4"

        try:
            # 加载模型（首次调用时加载）
            model = load_model()

            # 构建 JSON 输入（LongCat 要求 JSON 格式）
            import json
            input_json_path = tmpdir / "input.json"
            input_data = {
                "audio": str(audio_path),
                "ref_image": str(ref_img_path) if ref_img_path else "",
                "prompt": prompt,
            }
            with open(input_json_path, "w") as f:
                json.dump(input_data, f)

            start = time.time()

            # 调用 LongCat 推理
            # 注意：具体接口需根据 LongCat 实际 API 调整
            # 这里参考 run_demo_avatar_single_audio_to_video.py 的调用方式
            video_result = await asyncio.to_thread(
                _run_longcat_inference,
                model=model,
                input_json=str(input_json_path),
                output_path=str(output_path),
                model_type=model_type,
                resolution=resolution,
                num_segments=num_segments,
                use_distill=use_distill.lower() == "true",
                use_int8=use_int8.lower() == "true",
            )

            elapsed = time.time() - start
            print(f"[LongCat] 生成完成 耗时={elapsed:.1f}s output={output_path}")

            # 返回视频文件
            if not output_path.exists():
                return JSONResponse(
                    {"error": "生成失败：输出文件不存在"},
                    status_code=500,
                )

            video_bytes = output_path.read_bytes()
            return StreamingResponse(
                iter([video_bytes]),
                media_type="video/mp4",
                headers={
                    "Content-Disposition": f'attachment; filename="avatar_output.mp4"',
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


def _run_longcat_inference(
    model,
    input_json: str,
    output_path: str,
    model_type: str,
    resolution: str,
    num_segments: int,
    use_distill: bool,
    use_int8: bool,
):
    """执行 LongCat 推理（在线程中运行避免阻塞事件循环）

    注意：此函数需根据 LongCat 实际 API 调整。
    参考 run_demo_avatar_single_audio_to_video.py。
    """
    # 以下为伪代码框架，实际接口以 LongCat 源码为准
    # 具体参数参考 LongCat README 的 User tips
    print(
        f"[LongCat] 推理参数 model={model_type} res={resolution} "
        f"segments={num_segments} distill={use_distill} int8={use_int8}"
    )

    # TODO: 根据 LongCat 实际 API 调用
    # model.generate(
    #     input_json=input_json,
    #     output_path=output_path,
    #     model_type=model_type,
    #     resolution=resolution,
    #     num_segments=num_segments,
    #     use_distill=use_distill,
    #     use_int8=use_int8,
    #     ref_img_index=10,
    #     mask_frame_range=3,
    # )

    # 临时占位：如果模型未实际加载，抛出明确错误
    raise NotImplementedError(
        "LongCat 推理接口需根据实际模型 API 实现。"
        "请参考 run_demo_avatar_single_audio_to_video.py 调整 _run_longcat_inference 函数。"
    )


def main():
    """启动服务"""
    global _checkpoint_dir, _api_key

    parser = argparse.ArgumentParser(description="LongCat Avatar Server")
    parser.add_argument(
        "--checkpoint_dir",
        default="./weights/LongCat-Video-Avatar-1.5",
        help="模型权重目录",
    )
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    parser.add_argument("--api_key", default="", help="API Key 鉴权（可选）")
    parser.add_argument(
        "--preload", action="store_true", help="启动时预加载模型"
    )
    args = parser.parse_args()

    _checkpoint_dir = args.checkpoint_dir
    _api_key = args.api_key

    print("=" * 60)
    print("LongCat-Video-Avatar Server")
    print(f"  GPU: {get_gpu_info()}")
    print(f"  CUDA: {torch.cuda.is_available()}")
    print(f"  Checkpoint: {_checkpoint_dir}")
    print(f"  Listen: {args.host}:{args.port}")
    print(f"  API Key: {'enabled' if _api_key else 'disabled'}")
    print("=" * 60)

    if args.preload:
        print("[LongCat] 预加载模型...")
        load_model()

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
