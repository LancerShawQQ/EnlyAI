"""本机硬件资源探测

自动检测 GPU / NVENC / CPU 核数，供各模块按需启用硬件加速。
检测结果缓存，避免重复探测开销。
"""
from __future__ import annotations

import os
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path


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
def detect_amf() -> bool:
    """检测 FFmpeg 是否支持 AMD AMF 硬件编码（h264_amf）。

    通过实际编码测试验证（比 -encoders 列表更可靠，因为驱动可能不可用）。
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    try:
        result = subprocess.run(
            [ffmpeg, "-f", "lavfi", "-i", "color=black:s=64x64:d=0.1",
             "-c:v", "h264_amf", "-f", "null", "-"],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0
    except Exception:
        return False


@lru_cache(maxsize=1)
def detect_qsv() -> bool:
    """检测 FFmpeg 是否支持 Intel QSV 硬件编码（h264_qsv）。

    通过实际编码测试验证（比 -encoders 列表更可靠，因为驱动可能不可用）。
    """
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False
    try:
        result = subprocess.run(
            [ffmpeg, "-f", "lavfi", "-i", "color=black:s=64x64:d=0.1",
             "-c:v", "h264_qsv", "-f", "null", "-"],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0
    except Exception:
        return False


@lru_cache(maxsize=1)
def detect_cuda() -> bool:
    """检测 CUDA 是否可用（主环境或 wav2lip_env 独立环境）。

    检测顺序：
    1. 主环境 torch.cuda.is_available()
    2. wav2lip_env 独立环境的 torch.cuda.is_available()
    3. nvidia-smi 命令（检测 GPU 驱动是否存在）
    任一成功即返回 True，全部失败返回 False。
    """
    # 方案1：检测主环境 torch
    try:
        import torch  # type: ignore
        if torch.cuda.is_available():
            return True
    except ImportError:
        pass
    except Exception:
        pass

    # 方案2：检测 wav2lip_env 独立环境的 torch
    try:
        env_python = _find_wav2lip_env_python()
        if env_python:
            r = subprocess.run(
                [str(env_python), "-c",
                 "import torch; print(torch.cuda.is_available())"],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode == 0 and "True" in r.stdout:
                return True
    except Exception:
        pass

    # 方案3：检测 nvidia-smi（GPU 驱动存在性）
    try:
        nvidia_smi = shutil.which("nvidia-smi")
        if nvidia_smi:
            r = subprocess.run(
                [nvidia_smi, "--query-gpu=name", "--format=csv,noheader"],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode == 0 and r.stdout.strip():
                return True
    except Exception:
        pass

    return False


def _find_wav2lip_env_python() -> Path | None:
    """查找 wav2lip_env 独立环境的 python 可执行文件路径。

    查找顺序：配置 avatar.wav2lip.env_python → 项目根上级 wav2lip_env → 用户主目录 .wav2lip_env
    """
    # 1. 从配置读取 env_python
    try:
        from .config import PROJECT_ROOT  # type: ignore
        try:
            from .config import get_config  # type: ignore
            cfg_env = get_config().get("avatar.wav2lip.env_python", "")
        except Exception:
            cfg_env = ""
        if cfg_env:
            p = Path(cfg_env)
            if not p.is_absolute():
                p = (Path(PROJECT_ROOT) / p).resolve()
            if p.exists():
                return p
        # 2. 项目根上级的 wav2lip_env（setup_wav2lip_env.bat 默认位置）
        for exe in ("Scripts/python.exe", "bin/python"):
            candidate = Path(PROJECT_ROOT).parent / "wav2lip_env" / exe
            if candidate.exists():
                return candidate
    except Exception:
        pass
    # 3. 用户主目录
    try:
        for exe in ("Scripts/python.exe", "bin/python"):
            candidate = Path.home() / ".wav2lip_env" / exe
            if candidate.exists():
                return candidate
    except Exception:
        pass
    return None


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

    优先级：NVENC > QSV > AMF > libx264

    Returns:
        (codec, preset, extra_args)
        - codec: 编码器名（h264_nvenc/h264_qsv/h264_amf 或 libx264）
        - preset: 预设名
        - extra_args: 额外 FFmpeg 参数（如 -rc -cq 等）
    """
    if detect_nvenc():
        # NVENC: p4 预设质量与 libx264 medium 相当，速度 3-5 倍
        # VBR + CQ 模式保证质量（CQ 20 ≈ CRF 20）
        return ("h264_nvenc", "p4",
                ["-rc", "vbr", "-cq", "20", "-b:v", "0"])
    if detect_qsv():
        # QSV: veryfast 预设，关闭 look_ahead 降低延迟
        return ("h264_qsv", "veryfast", ["-look_ahead", "0"])
    if detect_amf():
        # AMF: speed 预设
        return ("h264_amf", "speed", ["-quality", "speed"])
    return ("libx264", "medium", [])


def get_acceleration_summary() -> dict:
    """获取本机加速能力摘要（供系统状态展示）。"""
    return {
        "nvenc": detect_nvenc(),
        "qsv": detect_qsv(),
        "amf": detect_amf(),
        "cuda": detect_cuda(),
        "onnx_cuda": detect_onnx_cuda(),
        "cpu_count": cpu_count(),
        "video_encoder": get_video_encoder()[0],
    }
