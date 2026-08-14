@echo off
REM ============================================================
REM Wav2Lip 独立环境一键安装脚本（Windows，CPU 推理）
REM
REM 用途：为 EnlyAI 搭建真实唇形同步（嘴会动）的本地推理环境
REM 位置：在 D:\cursor_project\koubo 下创建 wav2lip_env 和 Wav2Lip
REM
REM 前置：需安装 uv（https://github.com/astral-sh/uv）
REM 用法：scripts\setup_wav2lip_env.bat [gpu]
REM   无参数 = 安装 CPU 版 torch（默认，兼容性好）
REM   gpu    = 安装 GPU 版 torch（CUDA 11.7，需 NVIDIA 显卡）
REM ============================================================
setlocal

REM BASE = 脚本所在目录的上两级（即项目父目录，与 Wav2Lip/wav2lip_env 同级）
set "BASE=%~dp0\..\.."
cd /d "%BASE%"

echo ============================================================
echo  Wav2Lip 独立环境安装（CPU 唇形同步）
echo  基础目录: %BASE%
echo ============================================================

REM 1. 安装 Python 3.8（Wav2Lip 依赖老版本库）
echo [1/5] 安装 Python 3.8 ...
uv python install 3.8 || goto :error

REM 2. 创建独立 venv
echo [2/5] 创建 wav2lip_env 虚拟环境 ...
if not exist "wav2lip_env\Scripts\python.exe" (
    uv venv --python 3.8 wav2lip_env || goto :error
) else (
    echo  已存在，跳过
)

REM 3. 克隆 Wav2Lip 仓库
echo [3/5] 克隆 Wav2Lip 仓库 ...
if not exist "Wav2Lip\inference.py" (
    git clone https://github.com/Rudrabha/Wav2Lip.git || goto :error
) else (
    echo  已存在，跳过
)

REM 4. 安装依赖（兼容 CPU 的版本组合）
echo [4/5] 安装 Wav2Lip 依赖 ...
REM 检测是否安装 GPU 版 torch（通过参数 gpu 触发）
if "%1"=="gpu" (
    echo Installing GPU version of PyTorch (CUDA 11.7)...
    uv pip install --python "wav2lip_env\Scripts\python.exe" "torch==1.13.1+cu117" "torchvision==0.14.1+cu117" --index-url https://download.pytorch.org/whl/cu117 || goto :error
) else (
    echo Installing CPU version of PyTorch...
    uv pip install --python "wav2lip_env\Scripts\python.exe" "torch==1.13.1+cpu" "torchvision==0.14.1+cpu" --index-url https://download.pytorch.org/whl/cpu || goto :error
)
uv pip install --python "wav2lip_env\Scripts\python.exe" "librosa==0.9.2" "numba==0.56.4" "opencv-python==4.5.5.64" "tqdm==4.64.1" "scipy==1.9.3" "scikit-image==0.19.3" "imageio==2.22.4" "imageio-ffmpeg==0.4.7" "resampy==0.4.2" "soundfile==0.11.0" || goto :error

REM 5. 下载模型权重
echo [5/5] 下载模型权重（从 hf-mirror） ...
set "HF_ENDPOINT=https://hf-mirror.com"
wav2lip_env\Scripts\python.exe -c "import os; os.environ['HF_ENDPOINT']='https://hf-mirror.com'; from huggingface_hub import hf_hub_download; p=hf_hub_download(repo_id='rippertnt/wav2lip', filename='checkpoints/wav2lip_gan.pth', local_dir='Wav2Lip'); print('wav2lip_gan:', p)" || goto :error
wav2lip_env\Scripts\python.exe -c "import os; os.environ['HF_ENDPOINT']='https://hf-mirror.com'; from huggingface_hub import hf_hub_download; p=hf_hub_download(repo_id='camenduru/Wav2Lip', filename='face_detection/detection/sfd/s3fd.pth', local_dir='Wav2Lip'); print('s3fd:', p)" || goto :error

REM 验证
echo.
echo === 环境自检 ===
wav2lip_env\Scripts\python.exe -c "import torch, librosa, cv2, numpy; print('torch', torch.__version__, 'cuda', torch.cuda.is_available())" || goto :error
dir /b Wav2Lip\checkpoints\wav2lip_gan.pth || goto :error

echo.
echo ============================================================
echo  Wav2Lip 环境安装完成！
echo.
echo  目录结构:
echo    wav2lip_env\          Python 3.8 + torch (CPU 或 GPU，取决于安装参数)
echo    Wav2Lip\              推理脚本 + 模型
echo.
echo  EnlyAI 已配置 avatar.provider: wav2lip 自动使用此环境。
echo  CPU 推理耗时：1分钟视频约 20-60 分钟。
echo ============================================================
exit /b 0

:error
echo.
echo [错误] 安装失败，请检查上方输出
exit /b 1
