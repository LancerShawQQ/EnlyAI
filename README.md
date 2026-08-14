# EnlyAI · 虚拟人口播智能体

对标旗博士的**本地可运行**口播视频自动化生成系统。从文案到成片到发布，全流程一键化，支持纯 CPU 声音克隆 + Wav2Lip 视频驱动数字人。

## ✨ 核心特性

- 🎙️ **本地声音克隆**：基于 MOSS-TTS-Nano（0.1B ONNX），5 秒样本零样本克隆，纯 CPU 实时合成，无需上传云端
- 🧑 **Wav2Lip 视频驱动数字人**：保留原视频头动/表情/眨眼，仅替换嘴形对齐 TTS 语音（视频驱动模式）
- ✨ **GFPGAN 人脸增强（可选）**：含嘴部保护遮罩，避免口形失真；可在 UI 一键开关
- 🎞️ **画中画时间线编辑器**：可视化时间线，支持 `cut`（全屏插播替换）和 `pip`（角窗画中画）两种模式
- 📝 **AI 文案工作流**：润色/仿写/生成 + 原创检测（simhash + 违禁词 + LLM 风控）
- 📤 **多平台发布**：抖音 / B站 / 快手 / 视频号，半自动打开创作者中心 + 生成发布清单
- 🖥️ **7 标签页 Gradio GUI**：一键生成 / 声音克隆 / 形象管理 / 画中画编辑器 / 多平台发布 / 设置 / 任务管理
- ⚡ **MX450 2GB GPU 可跑**：全部模块支持纯 CPU 运行，无需高端显卡

## 🎬 工作流程

```
文案输入 → [LLM 润色/仿写] → [原创检测] → [MOSS-TTS 声音克隆]
       → [Wav2Lip 唇形同步] → [字幕生成] → [画中画插播] → [视频合成]
       → [标题生成] → [封面生成] → [多平台发布清单]
```

## 🛠️ 技术栈

| 模块 | 技术方案 | 说明 |
|------|---------|------|
| **LLM 文案** | DeepSeek-V3 / Qwen2.5（agnes） | 文案润色、仿写、标题、风控 |
| **TTS 声音克隆** | **MOSS-TTS-Nano (ONNX)** | 0.1B 模型，纯 CPU，5s 样本零样本克隆 |
| **TTS 备选** | MiMo / GPT-SoVITS / edge-tts | 云端或无 GPU 降级方案 |
| **数字人** | **Wav2Lip（视频驱动）** | Python 3.8 venv + torch 1.13 CPU |
| **人脸增强** | **GFPGAN** | 嘴部保护遮罩，可开关 |
| **字幕** | faster-whisper + ASS | 词级时间戳，卡拉OK逐字高亮 |
| **画中画** | FFmpeg cut/pip | 全屏替换 / 角窗叠加 + 淡入淡出 |
| **UI** | **Gradio 6.x** | 7 标签页，26 个 API 端点 |
| **编排** | SQLite 状态机 | 断点续跑 + 指数退避重试 |

## 🚀 快速开始

### 方式一：一键启动（推荐新手）

```bash
# 1. 下载代码
git clone https://github.com/LancerShawQQ/EnlyAI.git
cd EnlyAI

# 2. 双击 启动.bat（或命令行运行）
启动.bat
```

脚本会**自动完成**：
- 检测/创建 Python 虚拟环境
- 安装所有 Python 依赖（含 Web 服务、本地增强模块）
- 安装 Playwright 浏览器内核（发布到抖音/快手需要）
- 检测 FFmpeg（缺失时给出下载提示）
- 启动 Web UI 并自动打开浏览器

**前置条件**（仅需手动安装一次）：
1. **Python 3.10+**：https://www.python.org/downloads/ （安装时勾选 "Add Python to PATH"）
2. **FFmpeg**：https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip
   - 解压后将 `bin` 目录加入系统 PATH
3. **Git**（用于克隆代码）：https://git-scm.com/

**首次运行可选**（按需启用对应功能）：
- **本地声音克隆**：运行 `scripts\setup_moss_tts.bat`（下载 MOSS-TTS-Nano 模型约500MB）
- **真实唇形同步**：运行 `scripts\setup_wav2lip_env.bat`（下载 Wav2Lip 模型约200MB）
- **LLM 文案**：在 Web UI「设置」页面填入 DeepSeek API Key

> 未安装上述可选组件时，系统自动降级到 edge-tts（微软免费在线TTS）+ mock 数字人，仍可生成完整视频。

### 方式二：手动安装（开发者）

```bash
# 主环境（Python 3.12）
cd EnlyAI
pip install -e ".[local]"
pip install fastapi uvicorn bilibili-api-python
python -m playwright install chromium

# Wav2Lip 环境（Python 3.8，独立 venv）
# 运行 scripts\setup_wav2lip_env.bat 自动安装
```

### 启动服务

**Web UI（推荐，现代化界面）**

```bash
python -m krvoiceai.web.server --port 8000
```

访问 http://localhost:8000

**Gradio UI（备用，精简界面）**

```bash
python -m krvoiceai.ui.cli serve --port 7860
```

### 配置

所有配置在 Web UI「设置」标签页热修改，或编辑 `config/user_config.yaml`：

```yaml
# LLM 文案（填入 DeepSeek API Key 即可）
llm:
  provider: agnes
  api_key: 你的key

# TTS（默认 moss_nano 本地克隆，未安装时自动降级 edge-tts）
tts:
  provider: moss_nano

# 数字人（默认 wav2lip，未安装时用 mock）
avatar:
  provider: wav2lip
```

## 📋 GUI 标签页说明

| 标签页 | 功能 |
|--------|------|
| 🎬 **一键生成** | 输入文案 → 全流程自动产出视频，含实时进度、成片预览、发布按钮 |
| 🎙️ **声音克隆** | 上传 5-30s 人声样本注册音色，可试听克隆效果 |
| 🧑 **形象管理** | 上传正脸口播视频注册 Wav2Lip 形象 |
| 🎞️ **画中画编辑器** | 时间线可视化，添加/删除插播片段（cut 全屏 / pip 角窗） |
| 📤 **多平台发布** | 生成发布清单，一键打开抖音/B站/快手/视频号创作者中心 |
| ⚙️ **设置** | TTS 引擎 / GFPGAN 开关 / Wav2Lip 路径 / 字幕 / LLM / 发布模式，热生效 |
| 📋 **任务管理** | 历史任务、断点续跑、删除 |

## 📦 使用流程示例

1. **注册形象**：在「形象管理」上传你的口播视频 → 注册为 `anchor_wang`
2. **克隆声音**：在「声音克隆」上传你的声音样本 → 注册为 `voice_wang`，试听效果
3. **编辑画中画**（可选）：在「画中画编辑器」添加插播片段
4. **一键生成**：在「一键生成」输入文案，选择形象和音色 → 点击生成
5. **发布**：生成完成后点击「发布到抖音」，浏览器自动打开创作者中心

## 📂 项目结构

```
你的项目目录/
├── EnlyAI/                    ← GitHub 克隆的仓库（项目根目录）
│   ├── krvoiceai/
│   │   ├── core/              # 基础设施（config/logger/ffmpeg/settings_manager）
│   │   ├── modules/           # 业务模块
│   │   │   ├── tts_engine.py      # TTS（含 moss_nano/mimo/gpt_sovits/edge_tts/mock）
│   │   │   ├── avatar_engine.py   # Wav2Lip 数字人 + GFPGAN 增强
│   │   │   ├── broll_engine.py    # 画中画（cut 全屏替换 / pip 角窗）
│   │   │   ├── video_composer.py  # 视频合成（字幕+BGM+画中画）
│   │   │   ├── publisher.py       # 多平台发布
│   │   │   └── ...
│   │   ├── pipeline/          # 编排（orchestrator/state/parallel_runner）
│   │   ├── web/               # Web UI（FastAPI + 现代化前端）
│   │   ├── ui/
│   │   │   └── gradio_app.py      # Gradio GUI（备用）
│   │   └── app.py             # 主入口
│   ├── config/                # default.yaml + user_config.yaml + .env
│   ├── scripts/               # 环境安装脚本
│   │   ├── setup_wav2lip_env.bat  # Wav2Lip 环境一键安装
│   │   ├── setup_moss_tts.bat     # MOSS-TTS-Nano 模型下载
│   │   ├── start_wav2lip_server.bat  # Wav2Lip 服务独立启动
│   │   └── wav2lip_server.py      # Wav2Lip 常驻服务脚本（自动复制到 Wav2Lip/）
│   ├── 启动.bat                # 一键启动 Web UI（端口 8000）
│   └── start_gradio.bat       # Gradio UI 备用启动（端口 7860）
├── MOSS-TTS-Nano/             ← setup_moss_tts.bat 自动创建（声音克隆模型，约 500MB）
├── wav2lip_env/               ← setup_wav2lip_env.bat 自动创建（Python 3.8 venv）
└── Wav2Lip/                   ← setup_wav2lip_env.bat 自动克隆（推理代码 + 模型权重）
```

> **注意**：`MOSS-TTS-Nano/`、`wav2lip_env/`、`Wav2Lip/` 三个目录位于项目根目录的**上一级**（与 `EnlyAI/` 同级），由安装脚本自动创建。这样设计是为了将大文件/第三方仓库与项目代码分离。

## ⚙️ 关键配置（config/default.yaml）

```yaml
tts:
  provider: moss_nano              # moss_nano / mimo / gpt_sovits / edge_tts / mock
  moss_nano:
    cpu_threads: 4
    builtin_voice: Junhao          # 无克隆样本时的内置音色
    repo_dir: ../MOSS-TTS-Nano
    model_dir: ../MOSS-TTS-Nano/models

avatar:
  provider: wav2lip
  wav2lip:
    env_python: ../wav2lip_env/Scripts/python.exe  # 相对于项目根目录
    checkpoint_path: ../Wav2Lip/checkpoints/wav2lip_gan.pth
  gfpgan:
    enabled: false                 # 默认关闭，避免跳帧；UI 可一键开启
    stride: 1                      # 1=逐帧最稳
```

> **路径说明**：配置中的 `../` 前缀表示相对于项目根目录（`EnlyAI/`）的上一级目录，即 `MOSS-TTS-Nano/`、`wav2lip_env/`、`Wav2Lip/` 所在位置。安装脚本会自动在正确位置创建这些目录。

## 🧪 已验证

- ✅ MOSS-TTS-Nano 本地声音克隆（CPU，5s 样本零样本克隆，75s 音频合成）
- ✅ Wav2Lip 视频驱动数字人（保留头动/表情，嘴形对齐）
- ✅ GFPGAN 人脸增强（嘴部保护，可开关）
- ✅ 画中画时间线编辑器（cut 全屏替换 + pip 角窗 + 淡入淡出）
- ✅ 多平台发布清单生成（抖音/B站/快手/视频号）
- ✅ Gradio GUI 7 标签页、26 个 API 端点全部通过验收
- ✅ 设置热生效（tts/avatar/subtitle/llm/publisher 五段配置）

## 📝 开发路线

- [x] P0-P6：核心九模块 + 编排 + CLI + 部署
- [x] **本地化**：Wav2Lip CPU 推理 + GFPGAN + faster-whisper 字幕
- [x] **声音克隆**：MOSS-TTS-Nano ONNX 集成（去 torch 依赖）
- [x] **GUI 重构**：7 标签页 + 画中画编辑器 + 设置热生效
- [x] **多平台发布**：半自动模式 + 发布清单
- [ ] PyInstaller 打包为单 exe

## License

MIT
