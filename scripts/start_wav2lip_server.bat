@echo off
REM ============================================================
REM Wav2Lip 常驻服务启动脚本（独立运行模式，Windows）
REM
REM 用途：手动启动 wav2lip_server 用于调试或预加载
REM       主应用 EnlyAI 启动时会自动后台拉起此服务，此脚本仅供独立调试使用
REM
REM 前置：
REM   1. 已运行 scripts\setup_wav2lip_env.bat 创建 wav2lip_env
REM   2. 已下载 Wav2Lip\checkpoints\wav2lip_gan.pth
REM   3. wav2lip_env 已安装 fastapi 和 uvicorn
REM      （pip install fastapi uvicorn -i https://pypi.tuna.tsinghua.edu.cn/simple）
REM
REM 用法：scripts\start_wav2lip_server.bat
REM       启动后访问 http://127.0.0.1:8011/health 查看状态
REM       按 Ctrl+C 停止服务
REM ============================================================
setlocal

REM BASE = 脚本所在目录的上两级（即项目父目录，与 Wav2Lip/wav2lip_env 同级）
set "BASE=%~dp0\..\.."
set "WAV2LIP_ROOT=%BASE%\Wav2Lip"
set "PYTHON=%BASE%\wav2lip_env\Scripts\python.exe"

REM 参数检查
if not exist "%PYTHON%" (
    echo [ERROR] wav2lip_env Python 不存在: %PYTHON%
    echo 请先运行 scripts\setup_wav2lip_env.bat 创建独立 Python 环境
    exit /b 1
)

if not exist "%WAV2LIP_ROOT%\wav2lip_server.py" (
    echo [ERROR] wav2lip_server.py 不存在: %WAV2LIP_ROOT%\wav2lip_server.py
    exit /b 1
)

if not exist "%WAV2LIP_ROOT%\checkpoints\wav2lip_gan.pth" (
    echo [ERROR] checkpoint 不存在: %WAV2LIP_ROOT%\checkpoints\wav2lip_gan.pth
    echo 请从 hf-mirror 下载 wav2lip_gan.pth（参考 scripts\setup_wav2lip_env.bat）
    exit /b 1
)

cd /d "%WAV2LIP_ROOT%"

echo ============================================================
echo  Wav2Lip 常驻服务启动
echo  工作目录: %CD%
echo  Python:   %PYTHON%
echo  服务地址: http://127.0.0.1:8011
echo  健康检查: http://127.0.0.1:8011/health
echo  日志输出: 控制台（按 Ctrl+C 停止）
echo ============================================================
echo.

REM 检测 fastapi 是否安装
"%PYTHON%" -c "import fastapi, uvicorn" 2>nul
if errorlevel 1 (
    echo [WARN] 未检测到 fastapi/uvicorn，尝试自动安装...
    "%BASE%\wav2lip_env\Scripts\pip3.8.exe" install fastapi uvicorn -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo [ERROR] 依赖安装失败，请手动执行：
        echo   %BASE%\wav2lip_env\Scripts\pip3.8.exe install fastapi uvicorn
        exit /b 1
    )
)

REM 启动服务（默认 CPU 推理；如有 NVIDIA GPU 可加 --device cuda）
REM 参数说明：
REM   --port 8011                  服务端口
REM   --checkpoint_path            Wav2Lip 模型权重
REM   --face_det_batch_size 2      人脸检测批大小（2GB 显存用 2）
REM   --wav2lip_batch_size 2       Wav2Lip 推理批大小（2GB 显存用 2）
REM   --device auto                自动检测 GPU（不可用时回退 cpu）
"%PYTHON%" wav2lip_server.py ^
    --port 8011 ^
    --host 127.0.0.1 ^
    --checkpoint_path checkpoints/wav2lip_gan.pth ^
    --face_det_batch_size 2 ^
    --wav2lip_batch_size 2 ^
    --device auto

exit /b %ERRORLEVEL%
