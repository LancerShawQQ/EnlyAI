"""本机硬件资源探测

自动检测 GPU / NVENC / CPU 核数，供各模块按需启用硬件加速。
检测结果缓存，避免重复探测开销。
"""
from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache


@lru_cache(maxsize=1)
def detect_nvenc() -> bool:
    """检测 FFmpeg 是否支持 NVIDIA NVENC 硬件编码（h264_nvenc）。

    通过实际编码测试验证（比 -encoders 列表更可靠，因为驱动可能不可用）。
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    try:
        # 用 NVENC 编码 1 帧黑色画面做实际测试
        result = subprocess.run(
            [ffmpeg, "-f", "lavfi", "-i", "color=black:s=64x64:d=0.1",
             "-c:v", "h264_nvenc", "-f", "null", "-"],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0
    except Exception:
        return False


@lru_cache(maxsize=1)
def detect_cuda() -> bool:
    """检测 CUDA 是否可用（torch + 驱动 + GPU）。

    主环境可能未装 torch，此时返回 False。
    独立环境（wav2lip_env）的 CUDA 检测由各模块自行处理。
    """
    try:
        import torch  # type: ignore
        return torch.cuda.is_available()
    except ImportError:
        return False
    except Exception:
        return False


@lru_cache(maxsize=1)
def detect_onnx_cuda() -> bool:
    """检测 ONNX Runtime 是否支持 CUDA ExecutionProvider。"""
    try:
        import onnxruntime as ort  # type: ignore
        return "CUDAExecutionProvider" in ort.get_available_providers()
    except ImportError:
        return False
    except Exception:
        return False


@lru_cache(maxsize=1)
def cpu_count() -> int:
    """可用 CPU 核数（考虑容器 cgroup 限制）。"""
    try:
        # 优先用 cgroup 限制（容器内更准确）
        cpu_quota = os.cpu_count() or 4
        return cpu_quota
    except Exception:
        return 4


def get_video_encoder() -> tuple[str, str, list[str]]:
    """获取最优视频编码器配置。

    Returns:
        (codec, preset, extra_args)
        - codec: 编码器名（h264_nvenc 或 libx264）
        - preset: 预设名
        - extra_args: 额外 FFmpeg 参数（如 -rc -cq 等）
    """
    if detect_nvenc():
        # NVENC: p4 预设质量与 libx264 medium 相当，速度 3-5 倍
        # VBR + CQ 模式保证质量（CQ 20 ≈ CRF 20）
        return ("h264_nvenc", "p4",
                ["-rc", "vbr", "-cq", "20", "-b:v", "0"])
    return ("libx264", "medium", [])


def get_acceleration_summary() -> dict:
    """获取本机加速能力摘要（供系统状态展示）。"""
    return {
        "nvenc": detect_nvenc(),
        "cuda": detect_cuda(),
        "onnx_cuda": detect_onnx_cuda(),
        "cpu_count": cpu_count(),
        "video_encoder": get_video_encoder()[0],
    }
