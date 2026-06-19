# KrVoiceAI 部署指南

本文档介绍 KrVoiceAI 的三种部署模式：本地 Mock 模式、本地 + 云端 GPU 模式、全 Docker 模式。

## 目录

- [部署架构](#部署架构)
- [模式一：本地 Mock 模式（开发/测试）](#模式一本地-mock-模式开发测试)
- [模式二：本地 + 云端 GPU 模式（推荐生产）](#模式二本地--云端-gpu-模式推荐生产)
- [模式三：全 Docker 模式](#模式三全-docker-模式)
- [配置详解](#配置详解)
- [服务接口](#服务接口)
- [故障排查](#故障排查)

---

## 部署架构

```
┌─────────────────────────────────────────────────────────┐
│  本地机器（CPU）                                          │
│  ┌───────────────────────────────────────────────────┐  │
│  │  KrVoiceAI App                                    │  │
│  │  ├── Gradio UI (7860)                             │  │
│  │  ├── CLI                                          │  │
│  │  ├── Pipeline Orchestrator                        │  │
│  │  └── 9 个模块（mock 模式或调用云端）              │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────┬───────────────────────────────────────┘
                  │ HTTP API
                  ▼
┌─────────────────────────────────────────────────────────┐
│  云端 GPU 实例                                            │
│  ┌──────────────────┐  ┌──────────────────┐            │
│  │ TTS Server (9880)│  │Avatar Server(8010)│            │
│  │ GPT-SoVITS       │  │ MuseTalk          │            │
│  └──────────────────┘  └──────────────────┘            │
└─────────────────────────────────────────────────────────┘
```

**核心思想**：CPU 任务（文案、字幕、合成、发布）在本地运行，GPU 任务（TTS、数字人）调用云端服务。本地无 GPU 时自动降级到 mock 模式。

---

## 模式一：本地 Mock 模式（开发/测试）

适用：开发、测试、无 GPU 环境。所有 GPU 模块使用 mock 实现。

### 1. 安装依赖

```bash
cd /workspace
pip install -e ".[dev,tts]"
```

### 2. 安装 FFmpeg

```bash
# Ubuntu
sudo apt-get install -y ffmpeg

# macOS
brew install ffmpeg
```

### 3. 启动服务

```bash
# 启动 Gradio UI
python -m krvoiceai.ui.cli serve --host 0.0.0.0 --port 7860

# 或使用 CLI 直接生成视频
python -m krvoiceai.ui.cli run --script "今天分享一个 AI 小技巧" --platform douyin
```

### 4. 验证

```bash
# 运行测试
pytest tests/ -q

# 健康检查
python -m krvoiceai.ui.cli health
```

---

## 模式二：本地 + 云端 GPU 模式（推荐生产）

适用：实际生产。本地运行 KrVoiceAI，云端 GPU 运行 TTS 和数字人推理。

### 步骤 1：租用云 GPU 实例

推荐平台：
- **AutoDL**（国内，便宜）：RTX 3090 / 4090，约 ¥1-3/小时
- **阿里云 GN7**：A10/V100，按量付费
- **腾讯云 GN7**：T4/V100，按量付费

要求：
- GPU 显存 ≥ 8GB（推荐 12GB+）
- CUDA 12.1+
- Python 3.10+
- 公网 IP（或端口转发）

### 步骤 2：云端环境一键安装

```bash
# SSH 到云 GPU 实例
ssh root@<gpu-ip>

# 克隆项目
git clone <your-repo-url> krvoiceai
cd krvoiceai

# 一键安装（约 15-30 分钟）
bash scripts/setup_cloud_gpu.sh
```

脚本会自动安装：
- 系统依赖（ffmpeg, build-essential）
- Python 3.10 虚拟环境
- PyTorch (CUDA 12.1)
- GPT-SoVITS
- MuseTalk
- FunASR
- 预训练模型

### 步骤 3：启动云端服务

```bash
cd ~/krvoiceai
source .venv/bin/activate

# 后台启动 TTS 服务
nohup python -m krvoiceai.api.tts_server --host 0.0.0.0 --port 9880 \
    > logs/tts.log 2>&1 &

# 后台启动数字人服务
nohup python -m krvoiceai.api.avatar_server --host 0.0.0.0 --port 8010 \
    > logs/avatar.log 2>&1 &

# 验证服务
curl http://localhost:9880/health
curl http://localhost:8010/health
```

### 步骤 4：配置本地 KrVoiceAI

编辑本地 `config/default.yaml`：

```yaml
gpu_runner:
  tts_endpoint: http://<gpu-ip>:9880
  avatar_endpoint: http://<gpu-ip>:8010

tts:
  provider: gpt_sovits

avatar:
  provider: musetalk
```

或通过环境变量：

```bash
export KRVOICEAI_GPU_RUNNER_TTS_ENDPOINT=http://<gpu-ip>:9880
export KRVOICEAI_GPU_RUNNER_AVATAR_ENDPOINT=http://<gpu-ip>:8010
export KRVOICEAI_TTS_PROVIDER=gpt_sovits
export KRVOICEAI_AVATAR_PROVIDER=musetalk
```

### 步骤 5：注册音色和形象

```bash
# 注册音色（上传 5-10s 干净人声样本）
python -m krvoiceai.ui.cli voice register --voice-id myvoice --audio /path/to/sample.wav

# 注册数字人形象（上传 3-10s 正面说话视频）
python -m krvoiceai.ui.cli avatar register --avatar-id myavatar --video /path/to/ref.mp4
```

### 步骤 6：生成视频

```bash
# CLI
python -m krvoiceai.ui.cli run \
    --script "今天分享一个 AI 小技巧" \
    --avatar myavatar \
    --voice myvoice \
    --platform douyin

# 或启动 Gradio UI
python -m krvoiceai.ui.cli serve
```

---

## 模式三：全 Docker 模式

适用：快速部署、环境隔离。

### 1. 构建镜像

```bash
# 构建本地镜像
bash scripts/build_docker.sh local

# 构建 GPU 镜像（需在 GPU 机器上）
bash scripts/build_docker.sh gpu
```

### 2. 启动服务

**本地服务：**

```bash
docker-compose up -d local
```

访问 http://localhost:7860

**云端 GPU 服务（在 GPU 机器上）：**

```bash
docker-compose --profile gpu up -d tts avatar
```

### 3. 查看日志

```bash
docker-compose logs -f local
docker-compose logs -f tts
docker-compose logs -f avatar
```

---

## 配置详解

所有配置项在 `config/default.yaml`，可通过环境变量覆盖（前缀 `KRVOICEAI_`，全大写，下划线分隔）。

### 关键配置项

| 配置路径 | 说明 | 默认值 |
|---------|------|--------|
| `llm.provider` | LLM 提供商 | deepseek |
| `llm.api_key` | LLM API Key（环境变量 `KRVOICEAI_LLM_API_KEY`） | "" |
| `tts.provider` | TTS 提供商 | gpt_sovits |
| `tts.api_base` | TTS 服务地址 | http://localhost:9880 |
| `avatar.provider` | 数字人提供商 | musetalk |
| `avatar.api_base` | 数字人服务地址 | http://localhost:8010 |
| `asr.provider` | ASR 提供商 | funasr |
| `publisher.mode` | 发布模式 | semi_auto |
| `pipeline.gpu_enabled` | 是否启用 GPU | false |
| `gpu_runner.tts_endpoint` | 云端 TTS 地址 | http://localhost:9880 |
| `gpu_runner.avatar_endpoint` | 云端数字人地址 | http://localhost:8010 |

### LLM 配置示例

```yaml
llm:
  provider: deepseek  # deepseek / qwen / openai / mock
  api_key: ""         # 环境变量 KRVOICEAI_LLM_API_KEY
  base_url: https://api.deepseek.com/v1
  model: deepseek-chat
  temperature: 0.7
  max_tokens: 2000
```

获取 DeepSeek API Key：https://platform.deepseek.com/

---

## 服务接口

### TTS 服务（端口 9880）

**健康检查：**
```
GET /health
```

**语音合成：**
```
POST /api/tts/synthesize
Content-Type: application/json

{
    "text": "要合成的文本",
    "voice_id": "default",
    "speed": 1.0
}
```

响应：
```json
{
    "audio_base64": "<base64 编码的 wav>",
    "duration": 5.2,
    "sample_rate": 32000,
    "voice_id": "default"
}
```

**注册音色：**
```
POST /api/tts/register_voice
{
    "voice_id": "myvoice",
    "sample_audio_base64": "<base64>"
}
```

### 数字人服务（端口 8010）

**健康检查：**
```
GET /health
```

**生成视频：**
```
POST /api/avatar/generate
{
    "audio_base64": "<base64>",
    "avatar_id": "default",
    "output_fps": 25,
    "output_resolution": [1080, 1920]
}
```

**注册形象：**
```
POST /api/avatar/register
{
    "avatar_id": "myavatar",
    "reference_video_base64": "<base64>"
}
```

---

## 故障排查

### 1. TTS 服务无响应

```bash
# 检查服务状态
curl http://<gpu-ip>:9880/health

# 查看日志
tail -f ~/krvoiceai/logs/tts.log

# 常见原因：
# - GPT-SoVITS 未安装：bash scripts/setup_cloud_gpu.sh
# - 显存不足：nvidia-smi 查看显存
# - 模型未下载：bash scripts/download_models.sh
```

### 2. 数字人服务报错

```bash
# 检查 MuseTalk 是否加载
python -c "from musetalk.api import MuseTalkAPI; print('OK')"

# 检查形象是否注册
ls ~/krvoiceai/config/avatars/

# 常见原因：
# - MuseTalk 未安装
# - 形象未注册：python -m krvoiceai.ui.cli avatar register
# - 参考视频格式不对：需 3-10s 正面说话，分辨率 ≥ 720p
```

### 3. 本地无法连接云端

```bash
# 检查网络
ping <gpu-ip>
curl http://<gpu-ip>:9880/health

# 常见原因：
# - 防火墙未开放端口：sudo ufw allow 9880/tcp
# - 云安全组未配置：在云控制台开放 9880/8010 端口
# - 服务未启动：ssh 到云端检查进程
```

### 4. FFmpeg 报错

```bash
# 检查 ffmpeg
ffmpeg -version

# 常见原因：
# - 未安装：sudo apt-get install ffmpeg
# - 版本过旧：升级到 4.4+
```

### 5. 字幕乱码

```bash
# 检查字体
ls config/fonts/

# 下载思源黑体
bash scripts/download_models.sh  # 包含字体下载
```

---

## 成本估算

### 云 GPU 成本（按量）

| 平台 | GPU | 价格（¥/小时） | 适用 |
|------|-----|---------------|------|
| AutoDL | RTX 3090 | 1.5-2.5 | 推荐，性价比高 |
| AutoDL | RTX 4090 | 2.5-3.5 | 高质量生成 |
| 阿里云 | A10 | 4-6 | 企业级 |
| 腾讯云 | T4 | 2-4 | 入门 |

### 单条视频成本

假设每条视频 60 秒：
- TTS 合成：约 5 秒 GPU 时间
- 数字人生成：约 30-60 秒 GPU 时间
- 总计：约 1 分钟 GPU 时间

按 RTX 3090 ¥2/小时计算：**单条视频 GPU 成本约 ¥0.03**

### 优化建议

1. **批量生成**：一次启动 GPU，批量处理多条视频，分摊启动成本
2. **闲时关机**：不生成时关闭云 GPU 实例
3. **使用 mock 模式开发**：开发调试用 mock，正式生成才启动 GPU
