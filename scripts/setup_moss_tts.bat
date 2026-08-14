@echo off
REM ============================================================
REM MOSS-TTS-Nano 本地声音克隆环境一键安装脚本（Windows，CPU 推理）
REM
REM 用途：为 EnlyAI 搭建本地声音克隆（MOSS-TTS-Nano ONNX）环境
REM 位置：在项目父目录下创建 MOSS-TTS-Nano/
REM
REM 前置：
REM   1. 已运行 启动.bat 创建主 Python 虚拟环境（.venv）
REM   2. 已安装 Git
REM
REM 用法：scripts\setup_moss_tts.bat
REM ============================================================
setlocal

REM BASE = 脚本所在目录的上两级（即项目父目录，与 MOSS-TTS-Nano 同级）
set "BASE=%~dp0\..\.."
set "MOSS_ROOT=%BASE%\MOSS-TTS-Nano"
set "PYTHON=%~dp0\..\.venv\Scripts\python.exe"

cd /d "%BASE%"

echo ============================================================
echo  MOSS-TTS-Nano 本地声音克隆环境安装
echo  基础目录: %BASE%
echo  MOSS 目录: %MOSS_ROOT%
echo ============================================================

REM 参数检查
if not exist "%PYTHON%" (
    echo [ERROR] 主 Python 环境不存在: %PYTHON%
    echo 请先运行 启动.bat 创建主虚拟环境
    exit /b 1
)

REM 1. 克隆 MOSS-TTS-Nano 仓库
echo [1/4] 克隆 MOSS-TTS-Nano 仓库 ...
if not exist "MOSS-TTS-Nano\onnx_tts_runtime.py" (
    git clone https://github.com/OpenMOSS/MOSS-TTS-Nano.git || goto :error
) else (
    echo  已存在，跳过
)

REM 2. 安装 Python 依赖（onnxruntime + sentencepiece + soundfile + huggingface_hub）
echo [2/4] 安装 Python 依赖 ...
"%PYTHON%" -m pip install onnxruntime sentencepiece soundfile huggingface_hub -i https://pypi.tuna.tsinghua.edu.cn/simple || goto :error

REM 3. 下载 ONNX 模型（从 hf-mirror 镜像，约 500MB）
echo [3/4] 下载 ONNX 模型（约 500MB，使用国内镜像）...
set "HF_ENDPOINT=https://hf-mirror.com"
"%PYTHON%" -c "import os; os.environ['HF_ENDPOINT']='https://hf-mirror.com'; from huggingface_hub import snapshot_download; snapshot_download(repo_id='OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX', local_dir='MOSS-TTS-Nano/models/MOSS-TTS-Nano-100M-ONNX', allow_patterns=['*.onnx','*.data','*.json','tokenizer.model']); print('TTS model downloaded')" || goto :error
"%PYTHON%" -c "import os; os.environ['HF_ENDPOINT']='https://hf-mirror.com'; from huggingface_hub import snapshot_download; snapshot_download(repo_id='OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX', local_dir='MOSS-TTS-Nano/models/MOSS-Audio-Tokenizer-Nano-ONNX', allow_patterns=['*.onnx','*.data','*.json']); print('Audio Tokenizer model downloaded')" || goto :error

REM 4. 验证
echo [4/4] 环境自检 ...
"%PYTHON%" -c "import onnxruntime, sentencepiece, soundfile, numpy; print('onnxruntime', onnxruntime.__version__); print('numpy', numpy.__version__)" || goto :error
dir /b "MOSS-TTS-Nano\models\MOSS-TTS-Nano-100M-ONNX\moss_tts_prefill.onnx" || goto :error
dir /b "MOSS-TTS-Nano\models\MOSS-Audio-Tokenizer-Nano-ONNX\moss_audio_tokenizer_encode.onnx" || goto :error

echo.
echo ============================================================
echo  MOSS-TTS-Nano 环境安装完成！
echo.
echo  目录结构:
echo    MOSS-TTS-Nano\          仓库代码 + ONNX 模型
echo      models\MOSS-TTS-Nano-100M-ONNX\       TTS 模型（约 400MB）
echo      models\MOSS-Audio-Tokenizer-Nano-ONNX\  Audio Tokenizer（约 100MB）
echo.
echo  EnlyAI 已配置 tts.provider: moss_nano 自动使用此环境。
echo  纯 CPU 推理，1 分钟文案约 10-30 秒合成。
echo ============================================================
exit /b 0

:error
echo.
echo [错误] 安装失败，请检查上方输出
exit /b 1
