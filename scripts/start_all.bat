@echo off
chcp 65001 >nul 2>&1
title EnlyAI 全本地服务启动器

REM ============================================================
REM EnlyAI 全本地服务一键启动脚本
REM 启动顺序：Ollama → CosyVoice → LatentSync → Web UI
REM 每个服务启动后进行健康检查，确保依赖就绪
REM ============================================================

set PROJECT_ROOT=%~dp0..
set CONDA_ENVS=C:\Users\%USERNAME%\miniconda3\envs
set PYTHON_MAIN=%CONDA_ENVS%\krvoiceai\python.exe
set PYTHON_COSYVOICE=%CONDA_ENVS%\CosyVoice\python.exe
set PYTHON_LATENTSYNC=%CONDA_ENVS%\LatentSync\python.exe

cd /d "%PROJECT_ROOT%"

echo ╔══════════════════════════════════════════════════════════╗
echo ║         EnlyAI 全本地服务一键启动器 v0.3.0               ║
echo ╚══════════════════════════════════════════════════════════╝
echo.

REM === 1. 检查 Ollama ===
echo [1/4] 检查 Ollama (LLM 服务)...
curl -s --max-time 3 http://localhost:11434/api/tags >nul 2>&1
if %ERRORLEVEL%==0 (
    echo   ✅ Ollama 已在运行
) else (
    echo   ⚠️  Ollama 未运行，尝试启动...
    start "" "ollama" serve
    timeout /t 5 /nobreak >nul
    curl -s --max-time 3 http://localhost:11434/api/tags >nul 2>&1
    if %ERRORLEVEL%==0 (
        echo   ✅ Ollama 启动成功
    ) else (
        echo   ❌ Ollama 启动失败，请手动运行: ollama serve
        echo   💡 拉取模型: ollama pull qwen3:8b
    )
)
echo.

REM === 2. 检查 CosyVoice ===
echo [2/4] 检查 CosyVoice (TTS 服务 :8012)...
curl -s --max-time 3 http://localhost:8012/api/health >nul 2>&1
if %ERRORLEVEL%==0 (
    echo   ✅ CosyVoice 已在运行
) else (
    echo   启动 CosyVoice（模型加载约 50 秒，请耐心等待）...
    start "CosyVoice Server" /MIN cmd /c "cd /d "%PROJECT_ROOT%" && "%PYTHON_COSYVOICE%" CosyVoice\cosyvoice_server.py --port 8012 --fp16"
    REM 等待 CosyVoice 就绪（最多 90 秒）
    set /a wait_count=0
    :wait_cosyvoice
    timeout /t 5 /nobreak >nul
    set /a wait_count+=1
    curl -s --max-time 3 http://localhost:8012/api/health >nul 2>&1
    if %ERRORLEVEL%==0 (
        echo   ✅ CosyVoice 启动成功
        goto cosyvoice_done
    )
    if %wait_count% LSS 18 (
        echo   等待中... (%wait_count%0%%)
        goto wait_cosyvoice
    )
    echo   ❌ CosyVoice 启动超时（90秒），请检查日志
    :cosyvoice_done
)
echo.

REM === 3. 检查 LatentSync ===
echo [3/4] 检查 LatentSync (数字人服务 :8011)...
curl -s --max-time 3 http://localhost:8011/api/health >nul 2>&1
if %ERRORLEVEL%==0 (
    echo   ✅ LatentSync 已在运行
) else (
    echo   启动 LatentSync...
    set LATENTSYNC_DIR=%PROJECT_ROOT%\..\LatentSync
    if not exist "%LATENTSYNC_DIR%\latentsync_server.py" (
        set LATENTSYNC_DIR=C:\AI_projects\LatentSync
    )
    start "LatentSync Server" /MIN cmd /c "cd /d "%LATENTSYNC_DIR%" && "%PYTHON_LATENTSYNC%" latentsync_server.py --port 8011 --resolution 256 --inference_steps 15"
    timeout /t 10 /nobreak >nul
    curl -s --max-time 3 http://localhost:8011/api/health >nul 2>&1
    if %ERRORLEVEL%==0 (
        echo   ✅ LatentSync 启动成功（首次推理时加载模型，约 60 秒）
    ) else (
        echo   ❌ LatentSync 启动失败，请检查 %LATENTSYNC_DIR%
    )
)
echo.

REM === 4. 启动 Web UI ===
echo [4/4] 启动 Web UI (:8000)...
curl -s --max-time 3 http://localhost:8000/api/voices >nul 2>&1
if %ERRORLEVEL%==0 (
    echo   ✅ Web UI 已在运行
) else (
    echo   启动 Web UI...
    start "EnlyAI Web" cmd /c "cd /d "%PROJECT_ROOT%" && "%PYTHON_MAIN%" -m krvoiceai.web.server --port 8000"
    timeout /t 10 /nobreak >nul
    curl -s --max-time 3 http://localhost:8000/api/voices >nul 2>&1
    if %ERRORLEVEL%==0 (
        echo   ✅ Web UI 启动成功
    ) else (
        echo   ❌ Web UI 启动失败
    )
)
echo.

echo ╔══════════════════════════════════════════════════════════╗
echo ║  ✅ 全部服务启动完成！                                    ║
echo ║                                                          ║
echo ║  Web UI:       http://localhost:8000                     ║
echo ║  CosyVoice:    http://localhost:8012/api/health          ║
echo ║  LatentSync:   http://localhost:8011/api/health          ║
echo ║  Ollama:       http://localhost:11434                    ║
echo ║                                                          ║
echo ║  按 Ctrl+C 或关闭此窗口不会停止服务                      ║
echo ║  各服务在独立窗口运行，可单独关闭                        ║
echo ╚══════════════════════════════════════════════════════════╝

REM 自动打开浏览器
timeout /t 3 /nobreak >nul
start "" http://localhost:8000

pause

REM 清除 Python 缓存（避免代码更新后旧 .pyc 生效）
for /r "%PROJECT_ROOT%\krvoiceai" %%f in (*.pyc) do del "%%f" 2>nul
for /d %%d in (%PROJECT_ROOT%\krvoiceai\**\__pycache__) do rmdir /s /q "%%d" 2>nul
