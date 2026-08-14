@echo off
REM ============================================================
REM EnlyAI 本地环境一键安装脚本（Windows）
REM
REM 用法：
REM   scripts\setup_local.bat           完整安装（基础 + 本地增强）
REM   scripts\setup_local.bat basic     仅基础（含 mock + edge-tts）
REM   scripts\setup_local.bat local     基础 + 本地增强（whisper + jieba）
REM
REM 硬件适配：MX450 2GB 显存也能跑（全部 CPU）
REM ============================================================
setlocal EnableDelayedExpansion

set "MODE=%~1"
if "%MODE%"=="" set "MODE=local"

cd /d "%~dp0\.."
echo ============================================================
echo  EnlyAI 本地环境安装  [模式: %MODE%]
echo  Python: .venv\Scripts\python.exe
echo ============================================================

REM 1. 创建虚拟环境（若不存在）
if not exist ".venv\Scripts\python.exe" (
    echo [1/4] 创建虚拟环境...
    python -m venv .venv
    if errorlevel 1 (
        echo [错误] 创建 venv 失败，请检查系统 Python 是否可用
        exit /b 1
    )
) else (
    echo [1/4] 虚拟环境已存在，跳过
)

REM 2. 升级 pip
echo [2/4] 升级 pip / setuptools / wheel...
.venv\Scripts\python.exe -m pip install --upgrade pip setuptools wheel >nul

REM 3. 按模式安装
echo [3/4] 安装依赖（模式: %MODE%）...
if /i "%MODE%"=="basic" (
    .venv\Scripts\python.exe -m pip install -e ".[dev,tts]"
) else if /i "%MODE%"=="local" (
    .venv\Scripts\python.exe -m pip install -e ".[dev,tts,local]"
) else (
    echo [错误] 未知模式: %MODE%  (可选: basic / local)
    exit /b 1
)
if errorlevel 1 (
    echo [错误] 依赖安装失败
    exit /b 1
)

REM 4. 自检
echo [4/4] 自检...
echo.
echo --- Python 版本 ---
.venv\Scripts\python.exe --version

echo.
echo --- FFmpeg ---
where ffmpeg >nul 2>&1 && (for /f "delims=" %%i in ('ffmpeg -version 2^>nul ^| findstr /n "version" ^| findstr "^1:"') do echo %%i) || echo [警告] 未找到 ffmpeg，请确保 ffmpeg 在 PATH 中

echo.
echo --- 关键模块 import 自检 ---
.venv\Scripts\python.exe -c "import krvoiceai; print('krvoiceai        OK')"
.venv\Scripts\python.exe -c "import edge_tts; print('edge_tts         OK (TTS 降级可用)')" 2>nul || echo "edge_tts         未安装（可选）"
.venv\Scripts\python.exe -c "import faster_whisper; print('faster_whisper   OK (字幕精对齐可用)')" 2>nul || echo "faster_whisper   未安装（可选，仅 basic 模式）"
.venv\Scripts\python.exe -c "import jieba; print('jieba            OK (文案查重可用)')" 2>nul || echo "jieba            未安装（可选）"

echo.
echo --- GPU 检测 ---
.venv\Scripts\python.exe -c "import torch; print('torch CUDA:', torch.cuda.is_available(), '设备:', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'N/A')" 2>nul || echo "torch            未安装（本地无需，云端才装）"

echo.
echo ============================================================
echo  安装完成！
echo.
echo  下一步：
echo    1. 跑测试：       .venv\Scripts\python.exe -m pytest tests\ -q
echo    2. 启动 UI：       .venv\Scripts\python.exe -m krvoiceai.ui.cli serve
echo    3. 命令行生成：   .venv\Scripts\python.exe -m krvoiceai.ui.cli run --script "测试文案"
echo ============================================================
endlocal
