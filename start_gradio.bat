@echo off
REM ============================================================
REM EnlyAI Gradio UI 启动脚本（备用，端口 7862）
REM
REM 注意：这是 Gradio UI（备用），主入口是 启动.bat（Web UI，端口 8000）
REM       日常使用请双击 启动.bat，本脚本仅供 Gradio 调试/对比使用
REM
REM 用法：双击此文件，或命令行运行 start_gradio.bat [端口号]
REM ============================================================
setlocal
cd /d "%~dp0"

set PORT=7860
if not "%~1"=="" set PORT=%~1

echo ========================================
echo  EnlyAI Gradio UI（备用）- 启动中...
echo  访问地址: http://localhost:%PORT%
echo  按 Ctrl+C 停止服务
echo ========================================
echo.
echo [提示] 日常使用推荐 启动.bat（Web UI，端口 8000）
echo.

REM 等待启动完成后再打开浏览器（由 Gradio inbrowser 处理）
python -m krvoiceai.ui.gradio_app --port %PORT% --host 127.0.0.1

echo.
echo 服务已停止。按任意键退出...
pause >nul
