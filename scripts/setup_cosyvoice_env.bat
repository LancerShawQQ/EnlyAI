@echo off
REM ============================================================
REM CosyVoice3 独立环境一键安装脚本（Windows）
REM
REM 用途：为 EnlyAI 搭建 Fun-CosyVoice3-0.5B-2512 本地 TTS 服务
REM 位置：创建 conda 环境 CosyVoice，下载模型权重
REM
REM 前置：需安装 conda（Miniconda/Anaconda）
REM 用法：scripts\setup_cosyvoice_env.bat
REM ============================================================
setlocal

REM BASE = 脚本所在目录的上两级（项目根）
set "BASE=%~dp0\.."
cd /d "%BASE%"

echo ============================================================
echo  CosyVoice3 独立环境安装（Fun-CosyVoice3-0.5B-2512）
echo  项目根: %BASE%
echo ============================================================

REM 0. 检查 conda
where conda >nul 2>nul
if errorlevel 1 (
    echo [ERROR] 未找到 conda，请先安装 Miniconda 或 Anaconda
    goto :error
)

REM 1. 创建 conda 环境
echo [1/6] 创建 conda 环境 CosyVoice (python=3.10) ...
call conda env list | findstr /C:"CosyVoice" >nul
if errorlevel 1 (
    call conda create -n CosyVoice python=3.10 -y || goto :error
) else (
    echo  环境已存在，跳过
)

REM 2. 激活环境
echo [2/6] 激活 CosyVoice 环境 ...
call conda activate CosyVoice || goto :error

REM 3. 检查 CosyVoice 仓库
echo [3/6] 检查 CosyVoice 仓库 ...
if not exist "CosyVoice\cosyvoice\cli\cosyvoice.py" (
    echo [ERROR] CosyVoice 仓库未找到，请先 clone 到 %BASE%\CosyVoice
    echo  git clone https://github.com/FunAudioLLM/CosyVoice.git
    goto :error
) else (
    echo  CosyVoice 仓库已存在
)

REM 4. 安装 PyTorch 2.3.1 + CUDA 12.1
echo [4/6] 安装 PyTorch 2.3.1 + torchaudio (CUDA 12.1) ...
pip install torch==2.3.1 torchaudio==2.3.1 --index-url https://download.pytorch.org/whl/cu121 || goto :error

REM 5. 安装 CosyVoice 依赖
echo [5/6] 安装 CosyVoice 依赖 ...
cd CosyVoice
pip install -r requirements.txt || goto :error
pip install fastapi uvicorn python-multipart || goto :error
cd /d "%BASE%"

REM 6. 下载 Fun-CosyVoice3-0.5B-2512 模型
echo [6/6] 下载 Fun-CosyVoice3-0.5B-2512 模型（约 2GB）...
if not exist "CosyVoice\pretrained_models\Fun-CosyVoice3-0.5B-2512" (
    call conda run -n CosyVoice python -c "from modelscope import snapshot_download; p = snapshot_download('iic/Fun-CosyVoice3-0.5B-2512', cache_dir='./CosyVoice/pretrained_models'); print('模型已下载到:', p)" || goto :error
) else (
    echo  模型已存在，跳过
)

REM 完成
echo.
echo ============================================================
echo  CosyVoice3 环境安装完成！
echo ============================================================
echo.
echo  启动 TTS 服务：
echo    conda activate CosyVoice
echo    cd CosyVoice
echo    python ../krvoiceai/modules/cosyvoice_server.py --port 8012
echo.
echo  在 EnlyAI 设置中选择 TTS provider = cosyvoice
echo  服务地址: http://localhost:8012
echo.
echo  预生成参考音色样本（首次使用前执行）：
echo    conda run -n krvoiceai python scripts/pregenerate_cosyvoice_voices.py
echo.
goto :eof

:error
echo.
echo [ERROR] 安装失败，请检查上方错误信息
exit /b 1
