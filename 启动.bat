@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

REM ============================================================
REM EnlyAI 一键启动脚本（Windows）
REM
REM 新用户使用：双击此文件即可，脚本会：
REM   1. 检测/创建虚拟环境
REM   2. 自动安装 Python 依赖
REM   3. 检测 FFmpeg（缺失时给出下载提示）
REM   4. 启动 Web UI 并自动打开浏览器
REM
REM 用法：
REM   启动.bat              默认 8000 端口
REM   启动.bat 9000         指定端口
REM ============================================================

set "PORT=8000"
if not "%~1"=="" set "PORT=%~1"

cd /d "%~dp0"

echo ============================================================
echo   EnlyAI 虚拟人口播智能体
echo   一键启动脚本
echo ============================================================
echo.

REM ===== 第1步：检测 Python =====
echo [1/5] 检测 Python 环境...
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.10+
    echo        下载地址：https://www.python.org/downloads/
    echo        安装时请勾选 "Add Python to PATH"
    pause
    exit /b 1
)
for /f "tokens=2" %%v in ('python --version 2^>^&1') do set "PYVER=%%v"
echo   Python: %PYVER%  OK
echo.

REM ===== 第2步：检测/创建虚拟环境 =====
echo [2/5] 检测虚拟环境...
if not exist ".venv\Scripts\python.exe" (
    echo   首次运行，创建虚拟环境...
    python -m venv .venv
    if errorlevel 1 (
        echo [错误] 创建虚拟环境失败
        pause
        exit /b 1
    )
    echo   虚拟环境已创建: .venv
) else (
    echo   虚拟环境已存在
)
echo.

REM ===== 第3步：安装/更新依赖 =====
echo [3/5] 检测依赖安装...
.venv\Scripts\python.exe -c "import krvoiceai, fastapi, uvicorn" >nul 2>&1
if errorlevel 1 (
    echo   首次运行，安装依赖（约2-5分钟，含本地增强模块）...
    .venv\Scripts\python.exe -m pip install --upgrade pip >nul
    .venv\Scripts\python.exe -m pip install -e ".[local]"
    if errorlevel 1 (
        echo   [警告] 完整安装失败，尝试基础安装...
        .venv\Scripts\python.exe -m pip install -e "."
    )
    REM playwright 浏览器内核（发布到抖音/快手需要）
    .venv\Scripts\python.exe -m playwright install chromium >nul 2>&1
    echo   依赖安装完成
) else (
    echo   依赖已就绪
)
echo.

REM ===== 第4步：检测 FFmpeg =====
echo [4/5] 检测 FFmpeg...
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo   [警告] 未检测到 FFmpeg
    echo   FFmpeg 是视频处理核心依赖，必须安装：
    echo     1. 下载：https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip
    echo     2. 解压到任意目录（如 C:\ffmpeg）
    echo     3. 将 C:\ffmpeg\bin 添加到系统 PATH 环境变量
    echo     4. 重启命令行后重新运行本脚本
    echo.
    set /p "cont=是否仍要启动？（字幕/BGM/合成功能将不可用）[y/N]: "
    if /i not "!cont!"=="y" exit /b 1
) else (
    echo   FFmpeg: OK
)
echo.

REM ===== 第5步：启动 Web UI =====
echo [5/5] 启动 Web UI...
echo.
echo ============================================================
echo   服务启动中...
echo   访问地址：http://localhost:%PORT%
echo   按 Ctrl+C 停止服务
echo ============================================================
echo.

REM 3秒后自动打开浏览器
start "" /b cmd /c "timeout /t 3 >nul && start http://localhost:%PORT%"

REM 启动 Web 服务
.venv\Scripts\python.exe -m krvoiceai.web.server
if errorlevel 1 (
    echo.
    echo [启动失败] 请检查上方错误信息
    echo 常见问题：
    echo   1. 端口被占用：换端口  启动.bat 9000
    echo   2. 依赖缺失：删除 .venv 文件夹后重新运行本脚本
    pause
)

endlocal
