# KrVoiceAI · 虚拟人口播智能体

对标旗博士的离线批量口播视频自动化生成系统。从文案到成片到发布，全流程自动化。

## 核心能力（9 大模块）

对标旗博士 9 大能力，全流程打通：

| # | 模块 | 功能 | 对标旗博士 |
|---|------|------|-----------|
| 1 | ScriptExtractor | 文案提取（从参考视频） | ✅ |
| 2 | ScriptWriter | 文案仿写/生成 | ✅ |
| 3 | TTSEngine | 声音克隆 TTS | ✅ |
| 4 | AvatarEngine | 数字人口播生成 | ✅ |
| 5 | SubtitleEngine | 自动字幕 | ✅ |
| 6 | VideoComposer | 视频合成（字幕+BGM+封面） | ✅ |
| 7 | TitleGenerator | 标题生成（多平台） | ✅ |
| 8 | CoverGenerator | 封面生成 | ✅ |
| 9 | Publisher | 多平台发布 | ✅ |

## 技术栈

- **LLM**：DeepSeek-V3 / Qwen2.5（文案、标题）
- **TTS**：GPT-SoVITS（声音克隆），edge-tts（降级）
- **数字人**：MuseTalk（口型同步），LatentSync/EchoMimic V2（备选）
- **ASR**：FunASR paraformer-zh（字幕、文案提取）
- **媒体**：FFmpeg + Pillow
- **UI**：Gradio + CLI
- **编排**：SQLite 状态机 + 断点续跑 + 指数退避重试

## 快速开始

### 1. 安装

```bash
cd /workspace
pip install -e ".[dev,tts]"
```

### 2. 配置

编辑 `config/default.yaml`，或通过环境变量配置：

```bash
# LLM API Key（必填，否则用 mock）
export KRVOICEAI_LLM_API_KEY=sk-xxx

# 云端 GPU 服务（可选，不填用 mock 模式）
export KRVOICEAI_GPU_RUNNER_TTS_ENDPOINT=http://<gpu-ip>:9880
export KRVOICEAI_GPU_RUNNER_AVATAR_ENDPOINT=http://<gpu-ip>:8010
```

### 3. 启动

```bash
# 启动 Gradio UI
python -m krvoiceai.ui.cli serve

# 或 CLI 直接生成
python -m krvoiceai.ui.cli run \
    --script "今天分享一个 AI 小技巧" \
    --platform douyin
```

访问 http://localhost:7860

### 4. 测试

```bash
pytest tests/ -q
```

## 部署模式

| 模式 | 适用 | 说明 |
|------|------|------|
| Mock 模式 | 开发测试 | 所有 GPU 模块用 mock，CPU 即可跑通全流程 |
| 本地 + 云 GPU | 生产推荐 | 本地跑 CPU 任务，云 GPU 跑 TTS/数字人 |
| 全 Docker | 快速部署 | docker-compose 一键启动 |

详见 [部署指南](docs/DEPLOYMENT.md)。

## 项目结构

```
krvoiceai/
├── krvoiceai/
│   ├── core/           # 基础设施（config/logger/ffmpeg/gpu_runner）
│   ├── modules/        # 9 大业务模块
│   ├── pipeline/       # 编排（orchestrator/state/factory）
│   ├── api/            # 云端 GPU 服务（tts_server/avatar_server）
│   ├── ui/             # CLI + Gradio
│   └── app.py          # 主入口
├── config/             # 配置文件
├── docker/             # Docker 文件
├── scripts/            # 部署脚本
├── tests/              # 测试（104 个用例）
└── docs/               # 文档
```

## 文档

- [技术设计文档](docs/DESIGN.md) - 完整架构设计、模块接口、开发路线
- [部署指南](docs/DEPLOYMENT.md) - 三种部署模式详解

## 开发路线

- [x] P0：项目脚手架 + 配置 + 日志 + 基础设施
- [x] P1：核心六模块（文案/TTS/数字人/字幕/合成/编排）
- [x] P2：文案提取（ScriptExtractor）
- [x] P3：标题 + 封面生成
- [x] P4：多平台发布器
- [x] P5：App + CLI + Gradio UI
- [x] P6：部署文档 + 云 GPU 镜像脚本 + 最终交付

## 测试覆盖

104 个测试用例，覆盖所有模块：

```
tests/test_app.py            11 个（含端到端 9 模块验收）
tests/test_avatar_engine.py   9 个
tests/test_pipeline_e2e.py    6 个（含断点续跑）
tests/test_publisher.py       8 个
tests/test_scaffold.py       11 个
tests/test_script_extractor.py 10 个
tests/test_script_writer.py  10 个
tests/test_subtitle_engine.py 9 个
tests/test_title_cover.py    12 个
tests/test_tts_engine.py      9 个
tests/test_video_composer.py  9 个
```

## License

MIT
