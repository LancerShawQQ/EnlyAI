@echo off
REM ============================================================
REM LatentSync 1.5 独立环境一键安装脚本（Windows，Blackwell GPU 兼容）
REM
REM 用途：为 EnlyAI 搭建 LatentSync 唇形同步本地推理服务环境
REM       LatentSync 是字节跳动开源的潜在扩散模型 LipSync（Apache 2.0），
REM       质量优于 Wav2Lip / MuseTalk，8GB 显存可跑 256x256 分辨率。
REM 位置：在项目父目录下创建 LatentSync 仓库与 conda 环境 LatentSync
REM
REM 前置：需安装 conda（Anaconda / Miniconda）与 git
REM 用法：scripts\setup_latentsync_env.bat
REM
REM Blackwell sm_120 兼容说明：
REM   RTX 50 系列等 Blackwell 架构需 PyTorch 2.7+cu128（含 sm_120 kernel），
REM   旧版 cu118/cu121 会报 "no kernel image is available for execution on the device"。
REM ============================================================
setlocal

REM BASE = 脚本所在目录的上两级（即项目父目录，与 LatentSync 仓库同级）
set "BASE=%~dp0\..\.."
cd /d "%BASE%"

echo ============================================================
echo  LatentSync 1.5 独立环境安装（Blackwell GPU 唇形同步）
echo  基础目录: %BASE%
echo ============================================================

REM 0. 检查 conda 是否可用
echo [0/6] 检查 conda ...
where conda >nul 2>nul
if errorlevel 1 (
    echo [错误] 未找到 conda，请先安装 Anaconda 或 Miniconda 并加入 PATH
    goto :error
)

REM 1. 创建 conda 环境 LatentSync（Python 3.10）
echo [1/6] 创建 conda 环境 LatentSync (python=3.10) ...
conda env list | findstr /C:"LatentSync" >nul 2>nul
if errorlevel 1 (
    conda create -n LatentSync python=3.10 -y || goto :error
) else (
    echo  环境 LatentSync 已存在，跳过创建
)

REM 2. 激活环境
echo [2/6] 激活 LatentSync 环境 ...
call conda activate LatentSync || goto :error

REM 3. 克隆 LatentSync 仓库
echo [3/6] 克隆 LatentSync 仓库 ...
if not exist "LatentSync\latentsync" (
    git clone https://github.com/bytedance/LatentSync.git || goto :error
) else (
    echo  LatentSync 仓库已存在，跳过克隆
)
cd /d "%BASE%\LatentSync"

REM 4. 安装 PyTorch 2.7+cu128（Blackwell sm_120 兼容）+ 依赖
echo [4/6] 安装 PyTorch 2.7+cu128（Blackwell 兼容）+ 依赖 ...
pip install torch==2.7.0 torchvision==0.22.0 --index-url https://download.pytorch.org/whl/cu128 || goto :error
pip install -r requirements.txt || goto :error
pip install fastapi uvicorn python-multipart || goto :error

REM 5. 下载模型权重（从 hf-mirror，国内加速）
echo [5/6] 下载 LatentSync 1.5 模型权重（从 hf-mirror） ...
set "HF_ENDPOINT=https://hf-mirror.com"
if not exist "checkpoints\latentsync_unet.pt" (
    python -c "import os; os.environ['HF_ENDPOINT']='https://hf-mirror.com'; from huggingface_hub import hf_hub_download; p=hf_hub_download(repo_id='ByteDance/LatentSync-1.5', filename='latentsync_unet.pt', local_dir='checkpoints'); print('latentsync_unet:', p)" || goto :error
) else (
    echo  latentsync_unet.pt 已存在，跳过
)
if not exist "checkpoints\whisper\tiny.pt" (
    python -c "import os; os.makedirs('checkpoints/whisper', exist_ok=True); os.environ['HF_ENDPOINT']='https://hf-mirror.com'; from huggingface_hub import hf_hub_download; p=hf_hub_download(repo_id='ByteDance/LatentSync-1.5', filename='whisper/tiny.pt', local_dir='checkpoints'); print('whisper tiny:', p)" || goto :error
) else (
    echo  whisper/tiny.pt 已存在，跳过
)

REM 6. 复制服务端脚本到 LatentSync 仓库根目录
echo [6/6] 部署 latentsync_server.py 到 LatentSync 仓库 ...
if not exist "latentsync_server.py" (
    copy /Y "%BASE%\krvoiceai\modules\latentsync_server.py" "latentsync_server.py" || goto :error
    echo  已复制 latentsync_server.py
) else (
    echo  latentsync_server.py 已存在，跳过（如需更新请手动覆盖）
)

REM 验证
echo.
echo === 环境自检 ===
python -c "import torch; print('torch', torch.__version__, 'cuda', torch.cuda.is_available(), 'cap', torch.cuda.get_device_capability(0) if torch.cuda.is_available() else 'N/A')" || goto :error
dir /b checkpoints\latentsync_unet.pt || goto :error
dir /b checkpoints\whisper\tiny.pt || goto :error

echo.
echo ============================================================
echo  LatentSync 1.5 环境安装完成！
echo.
echo  目录结构:
echo    conda 环境:    LatentSync (python=3.10, torch 2.7+cu128)
echo    仓库目录:      %BASE%\LatentSync\
echo    模型权重:       checkpoints\latentsync_unet.pt
echo                   checkpoints\whisper\tiny.pt
echo    服务端脚本:     latentsync_server.py
echo.
echo  启动服务（在 LatentSync 仓库目录下执行）:
echo    conda activate LatentSync
echo    cd %BASE%\LatentSync
echo    python latentsync_server.py --port 8011
echo.
echo  Blackwell 8GB 显存建议:
echo    python latentsync_server.py --port 8011 --resolution 256 --inference_steps 25
echo.
echo  EnlyAI 配置: avatar.provider: latentsync
echo               avatar.latentsync.server_url: http://localhost:8011
echo ============================================================
exit /b 0

:error
echo.
echo [错误] 安装失败，请检查上方输出
exit /b 1
