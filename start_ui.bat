@echo off
REM KrVoiceAI UI 启动脚本（双击运行即可，浏览器自动打开）
REM 用法：双击此文件，或命令行运行 start_ui.bat [端口号]

setlocal
cd /d "%~dp0"

set PORT=7862
if not "%~1"=="" set PORT=%~1

echo ========================================
echo  KrVoiceAI 虚拟人口播智能体 - 启动中...
echo  访问地址: http://localhost:%PORT%
echo  按 Ctrl+C 停止服务
echo ========================================
echo.

REM 等待启动完成后再打开浏览器（由 Gradio inbrowser 处理）
python -m krvoiceai.ui.gradio_app --port %PORT% --host 127.0.0.1

echo.
echo 服务已停止。按任意键退出...
pause >nul
