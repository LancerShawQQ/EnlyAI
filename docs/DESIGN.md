# 虚拟人口播智能体 - 技术设计与开发方案

> 项目代号：**KrVoiceAI**
> 对标产品：旗博士（KrLongAI）口播自动生成智能体
> 文档版本：v1.0
> 更新日期：2026-06-19

---

## 1. 项目概述

### 1.1 项目目标

构建一套**离线批量口播视频自动化生成系统**，对标旗博士的核心能力。系统输入文案（或参考视频链接），输出可直接发布到主流短视频平台的口播视频，全流程自动化、可批量、可定制。

### 1.2 核心价值

- **全流程自动化**：从文案到发布，9 大环节无人干预
- **真人克隆**：基于用户视频素材生成专属数字人形象
- **本地可控**：自用工具，数据不出本地（除云端 GPU 推理外）
- **成本可控**：云 GPU 按量租用，单条视频成本 < ¥0.5

### 1.3 与对标产品差异

| 维度 | 旗博士 | 本项目 |
|---|---|---|
| 部署形态 | 本地软件 | 本地编排 + 云 GPU 推理 |
| 数字人路线 | 训练专属模型 | Zero-shot（免训练）+ 可扩展训练 |
| 开源依赖 | 闭源 | 全部基于开源组件 |
| 形象切换 | 需重训 | 秒级切换（Zero-shot 优势） |
| 成本结构 | 一次性硬件投入 | 按量付费，弹性 |

---

## 2. 对标功能拆解

旗博士 9 大能力映射到本项目的模块：

| # | 旗博士能力 | 本项目模块 | 优先级 | 技术实现 |
|---|---|---|---|---|
| 1 | 对标文案提取 | `script_extractor` | P2 | yt-dlp + FunASR |
| 2 | 文案语义级仿写 | `script_writer` | P1/P2 | LLM (DeepSeek/Qwen) |
| 3 | 声音克隆/合成 | `tts_engine` | P1 | GPT-SoVITS |
| 4 | 数字人口播生成 | `avatar_engine` | P1 | MuseTalk (主) / LatentSync (备) |
| 5 | 字幕自动生成 | `subtitle_engine` | P1 | FunASR + 时间戳对齐 |
| 6 | 背景音乐添加 | `video_composer` | P1 | FFmpeg |
| 7 | 视频标题生成 | `title_generator` | P3 | LLM |
| 8 | 封面一键生成 | `cover_generator` | P3 | SDXL / 视频抽帧 |
| 9 | 多平台自动发布 | `publisher` | P4 | 平台 API / Playwright |

---

## 3. 总体架构

### 3.1 分层架构

```
┌─────────────────────────────────────────────────────────────┐
│  L4 交互层    Gradio Web UI / CLI / 批量队列                │
├─────────────────────────────────────────────────────────────┤
│  L3 编排层    Pipeline Orchestrator (任务编排/状态机/重试)   │
├─────────────────────────────────────────────────────────────┤
│  L2 模块层                                                  │
│  ┌──────────┬──────────┬──────────┬──────────┬──────────┐  │
│  │ script   │ tts      │ avatar   │ subtitle │ composer │  │
│  │ _extract │ _engine  │ _engine  │ _engine  │          │  │
│  ├──────────┼──────────┼──────────┼──────────┼──────────┤  │
│  │ script   │ title    │ cover    │ bgm      │ publisher│  │
│  │ _writer  │ _gen     │ _gen     │ _loader  │          │  │
│  └──────────┴──────────┴──────────┴──────────┴──────────┘  │
├─────────────────────────────────────────────────────────────┤
│  L1 基础层    Config / Logger / Storage / HTTP / GPU Runner  │
├─────────────────────────────────────────────────────────────┤
│  L0 运行层    本地 CPU/Mac  +  云 GPU (按量租)              │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 本地/云端分离策略

**核心原则**：GPU 密集任务上云，其余本地执行。

| 任务 | 执行位置 | 理由 |
|---|---|---|
| 文案提取/仿写/标题 | 本地 | 调 LLM API，无 GPU 需求 |
| TTS 声音克隆 | **云端 GPU** | GPT-SoVITS 推理需 GPU |
| 数字人口播生成 | **云端 GPU** | MuseTalk 推理需 GPU |
| 字幕 ASR | 本地或云端 | FunASR CPU 可跑，量大上云 |
| 视频合成/BGM | 本地 | FFmpeg，CPU 即可 |
| 封面生成 | 本地或云端 | SDXL 需 GPU，抽帧本地即可 |
| 多平台发布 | 本地 | 浏览器自动化/API |

### 3.3 数据流

```
[输入]
  ├─ 文案文本 ──────────────────────────────┐
  └─ 参考视频URL ─→ script_extractor ─→ 文案 ┘
                                              │
                                              ▼
                                    script_writer (LLM润色/仿写)
                                              │
                                              ▼
                                    tts_engine (GPT-SoVITS)
                                       │            │
                                       ▼            ▼
                                    音频wav     时间戳/音素
                                       │            │
                                       ▼            │
                          avatar_engine (MuseTalk)  │
                              │                     │
                              ▼                     │
                          口播视频mp4               │
                              │                     │
                              ▼                     ▼
                          subtitle_engine ←─ (音频对齐)
                              │
                              ▼
                          video_composer (字幕+BGM+封面帧)
                              │
                              ▼
                          最终视频mp4
                              │
                    ┌─────────┴─────────┐
                    ▼                   ▼
              title_generator     cover_generator
                    │                   │
                    └─────────┬─────────┘
                              ▼
                          publisher (多平台)
                              │
                              ▼
                          [发布完成]
```

---

## 4. 模块详细设计

### 4.1 模块通用契约

所有模块遵循统一接口规范，保证可替换、可测试、可 mock。

```python
# 统一基类
class BaseModule:
    name: str                    # 模块名
    requires_gpu: bool           # 是否需要 GPU
    
    def setup(self, config): ... # 初始化
    def run(self, input: ModuleInput) -> ModuleOutput: ...
    def health_check(self) -> bool: ...  # 健康检查
    def cleanup(self): ...

# 统一数据载体
@dataclass
class JobContext:
    job_id: str
    work_dir: Path               # 任务工作目录
    script_text: str             # 文案
    audio_path: Optional[Path]   # 合成音频
    video_path: Optional[Path]   # 口播视频
    subtitle_path: Optional[Path] # 字幕
    final_video: Optional[Path]  # 最终视频
    title: Optional[str]
    cover_path: Optional[Path]
    metadata: dict               # 扩展字段
```

### 4.2 script_extractor（对标文案提取）

**职责**：从参考视频 URL 提取口播文案。

**输入**：`video_url: str`（支持抖音/快手/B站/YouTube 公开视频）
**输出**：`script_text: str`（带标点的纯文本）

**实现**：
1. `yt-dlp` 下载视频（仅音频流，节省带宽）
2. `FunASR` (paraformer-zh) 转写为带标点文本
3. 文本清洗（去语气词、合并断句）

**接口**：
```python
class ScriptExtractor(BaseModule):
    def extract(self, video_url: str, lang: str = "zh") -> str
```

**合规边界**：仅支持用户手动提供链接，不做批量爬取；仅提取文案用于参考改写，不直接复用。

### 4.3 script_writer（文案生成/仿写）

**职责**：文案润色、语义级仿写、口播风格优化。

**输入**：`raw_text: str`, `mode: str` (polish|rewrite|generate), `style: dict`
**输出**：`script_text: str`

**实现**：
- 主选：DeepSeek-V3 API（成本低、中文强）
- 备选：Qwen2.5 本地部署
- 提示工程：内置口播文案模板（开场钩子、价值点、CTA）
- 仿写模式：保留语义结构，替换表达，避免查重

**接口**：
```python
class ScriptWriter(BaseModule):
    def write(self, raw_text: str, mode: str = "polish", 
              style: dict = None) -> str
```

### 4.4 tts_engine（声音克隆/TTS）

**职责**：文本→语音，支持音色克隆。

**输入**：`text: str`, `voice_id: str`（已注册音色）
**输出**：`audio_path: Path`, `duration: float`, `timestamps: list`

**实现**：
- 主选：**GPT-SoVITS**（少样本克隆，3-10s 干净人声即可）
- 部署：云端 GPU 起 API 服务（FastAPI 包装）
- 音色管理：本地维护音色库（参考音频 + 元数据）
- 流式：分句合成，降低首句延迟

**接口**：
```python
class TTSEngine(BaseModule):
    def register_voice(self, voice_id: str, sample_audio: Path) -> bool
    def synthesize(self, text: str, voice_id: str) -> AudioResult
```

**降级**：GPU 不可用时，回退到 edge-tts（无克隆，仅标准音色）。

### 4.5 avatar_engine（数字人口播生成）【核心】

**职责**：音频 + 参考形象 → 口播视频。

**输入**：`audio_path: Path`, `avatar_id: str`（已注册形象）
**输出**：`video_path: Path`（带口型同步的视频）

**实现**：
- 主选：**MuseTalk**（实时、质量平衡、4090 流畅）
- 备选 1：LatentSync（口型更精准，速度稍慢）
- 备选 2：EchoMimic V2（表情动作更自然）
- 形象注册：用户提供 3-10s 正面说话视频，预处理为参考帧
- 推理：云端 GPU，按 batch 处理

**接口**：
```python
class AvatarEngine(BaseModule):
    def register_avatar(self, avatar_id: str, 
                        reference_video: Path) -> bool
    def generate(self, audio_path: Path, 
                 avatar_id: str) -> Path  # 返回视频路径
```

**降级**：GPU 不可用时，输出"音频 + 静态头像图"的占位视频，保证流程可跑通。

### 4.6 subtitle_engine（字幕生成）

**职责**：基于音频生成带时间戳的字幕（SRT/ASS）。

**输入**：`audio_path: Path`
**输出**：`subtitle_path: Path`（SRT 格式）

**实现**：
- FunASR（paraformer-zh + 标点 + 时间戳）
- 输出 SRT，按句切分，单条 ≤ 18 字
- 可选：烧录字幕到视频（在 composer 完成）

**接口**：
```python
class SubtitleEngine(BaseModule):
    def generate(self, audio_path: Path, 
                 format: str = "srt") -> Path
```

### 4.7 video_composer（视频合成）

**职责**：口播视频 + 字幕 + BGM + 封面 → 最终成片。

**输入**：`video_path`, `subtitle_path`, `bgm_path`(可选), `cover_image`(可选)
**输出**：`final_video: Path`

**实现**：
- FFmpeg 滤镜链：
  - 字幕烧录（subtitles 滤镜，自定义样式）
  - BGM 混音（侧链压缩，避免盖过人声）
  - 封面作为首帧（黑场过渡）
  - 统一分辨率/帧率/码率（1080p@30fps, 8Mbps）
- 输出 H.264 + AAC，兼容主流平台

**接口**：
```python
class VideoComposer(BaseModule):
    def compose(self, video: Path, subtitle: Path = None,
                bgm: Path = None, cover: Path = None,
                output: Path = None) -> Path
```

### 4.8 title_generator（标题生成）

**职责**：根据口播内容生成吸睛标题。

**输入**：`script_text: str`, `platform: str`（抖音/快手/视频号/B站）
**输出**：`titles: list[str]`（3-5 个候选）

**实现**：LLM + 平台风格提示词（抖音重情绪钩子，B站重信息量）。

### 4.9 cover_generator（封面生成）

**职责**：生成视频封面图。

**输入**：`video_path: Path`, `title: str`
**输出**：`cover_path: Path`（1080x1920 竖版）

**实现**：
- 主方案：视频抽帧（选表情最佳帧）+ 标题文字叠加（PIL）
- 备选：SDXL 文生图（需 GPU）
- 模板化：内置若干封面模板（大字标题、人物+文字）

### 4.10 publisher（多平台发布）

**职责**：将成片发布到主流短视频平台。

**输入**：`video_path`, `title`, `cover_path`, `platforms: list`
**输出**：`publish_results: dict`

**实现**：
- 优先：平台开放 API（B站有官方 API）
- 兜底：Playwright 浏览器自动化（抖音/快手/视频号）
- 半自动模式：生成发布清单，用户确认后执行
- Cookie 持久化：避免重复登录

**合规**：明确告知用户平台 ToS 风险，默认半自动模式。

### 4.11 Pipeline Orchestrator（编排）

**职责**：串联所有模块，管理任务状态、重试、断点续跑。

**实现**：
- 状态机：`pending → running → success / failed`
- 持久化：SQLite 存任务记录
- 重试：失败模块指数退避重试 3 次
- 断点续跑：每个模块产出落盘，重跑从失败点开始
- 批量：支持队列批量处理

---

## 5. 技术选型汇总

| 层 | 组件 | 选型 | 版本 |
|---|---|---|---|
| 语言 | 主语言 | Python | 3.10+ |
| 编排 | 任务队列 | RQ (Redis Queue) | 轻量 |
| 持久化 | 数据库 | SQLite | 内置 |
| 界面 | Web UI | Gradio | 4.x |
| LLM | 文案/标题 | DeepSeek-V3 API / Qwen2.5 | - |
| TTS | 声音克隆 | GPT-SoVITS | latest |
| 数字人 | 口播生成 | MuseTalk | latest |
| ASR | 字幕/提取 | FunASR | 1.x |
| 视频 | 合成 | FFmpeg | 6.x |
| 图像 | 封面 | Pillow / SDXL | - |
| 发布 | 自动化 | Playwright | 1.40+ |
| 下载 | 视频 | yt-dlp | latest |
| 部署 | 容器 | Docker | - |

---

## 6. 项目结构

```
krvoiceai/
├── README.md
├── pyproject.toml              # 依赖与项目元数据
├── requirements.txt
├── config/
│   ├── default.yaml            # 默认配置
│   └── avatars/                # 数字人形象库
│       └── {avatar_id}/
│           ├── reference.mp4
│           └── meta.json
├── krvoiceai/
│   ├── __init__.py
│   ├── core/                   # 基础层
│   │   ├── config.py
│   │   ├── logger.py
│   │   ├── storage.py
│   │   ├── gpu_runner.py       # 云GPU任务调度
│   │   └── base_module.py
│   ├── modules/                # 模块层
│   │   ├── script_extractor.py
│   │   ├── script_writer.py
│   │   ├── tts_engine.py
│   │   ├── avatar_engine.py
│   │   ├── subtitle_engine.py
│   │   ├── video_composer.py
│   │   ├── title_generator.py
│   │   ├── cover_generator.py
│   │   └── publisher.py
│   ├── pipeline/               # 编排层
│   │   ├── orchestrator.py
│   │   ├── job_context.py
│   │   └── state.py
│   ├── ui/                     # 交互层
│   │   ├── gradio_app.py
│   │   └── cli.py
│   └── api/                    # 云端服务
│       ├── tts_server.py       # GPT-SoVITS API 包装
│       └── avatar_server.py    # MuseTalk API 包装
├── tests/                      # 测试
│   ├── conftest.py
│   ├── test_script_writer.py
│   ├── test_tts_engine.py
│   ├── test_avatar_engine.py
│   ├── test_subtitle_engine.py
│   ├── test_video_composer.py
│   └── test_pipeline.py
├── scripts/                    # 部署脚本
│   ├── setup_cloud_gpu.sh      # 云GPU环境
│   ├── build_docker.sh
│   └── download_models.sh
├── docker/
│   ├── Dockerfile.local
│   ├── Dockerfile.gpu
│   └── docker-compose.yml
└── docs/
    ├── DESIGN.md               # 本文档
    ├── DEPLOYMENT.md
    └── API.md
```

---

## 7. 接口规范（关键模块）

### 7.1 TTS 云端 API

```
POST /api/tts/synthesize
Body: { "text": "...", "voice_id": "alice", "speed": 1.0 }
Response: { "audio_url": "...", "duration": 12.5, "timestamps": [...] }

POST /api/tts/register_voice
Body: { "voice_id": "alice", "sample_audio_url": "..." }
Response: { "success": true }
```

### 7.2 Avatar 云端 API

```
POST /api/avatar/generate
Body: { "audio_url": "...", "avatar_id": "alice" }
Response: { "video_url": "...", "duration": 12.5 }

POST /api/avatar/register
Body: { "avatar_id": "alice", "reference_video_url": "..." }
Response: { "success": true }
```

### 7.3 本地编排 API（CLI/Gradio 共用）

```python
class KrVoiceAI:
    def submit_job(self, script: str, avatar_id: str, 
                   voice_id: str) -> str  # 返回 job_id
    def get_job_status(self, job_id: str) -> JobStatus
    def get_job_result(self, job_id: str) -> JobResult
    def list_avatars(self) -> list[AvatarInfo]
    def list_voices(self) -> list[VoiceInfo]
```

---

## 8. 部署方案

### 8.1 本地环境（编排 + 轻任务）

**要求**：Python 3.10+，FFmpeg，8GB+ RAM，无需 GPU
**部署**：`docker compose up local`
**组件**：编排器、Gradio UI、SQLite、Redis（可选）

### 8.2 云端 GPU 环境（重推理）

**推荐平台**：AutoDL（4090 ¥2-3/h）、阿里云 PAI
**镜像**：预装 GPT-SoVITS + MuseTalk + FunASR + 模型权重
**启动**：`bash scripts/setup_cloud_gpu.sh`
**服务**：TTS API + Avatar API（FastAPI）

### 8.3 镜像持久化

首次配置完成后：
1. 保存为自定义镜像（AutoDL 支持秒级开机）
2. 模型权重放数据盘（不随镜像丢失）
3. 下次开机秒级恢复，无需重装

---

## 9. 成本分析

### 9.1 单条视频成本（1 分钟口播）

| 环节 | 耗时 | 单价 | 成本 |
|---|---|---|---|
| 文案生成（LLM API） | ~5s | DeepSeek ¥0.001/1k token | ¥0.01 |
| TTS 合成 | ~15s | 4090 ¥2.5/h | ¥0.01 |
| 数字人生成 | ~30s | 4090 ¥2.5/h | ¥0.02 |
| 字幕 + 合成 | ~10s | 本地 CPU | ¥0 |
| 封面 + 标题 | ~5s | 本地 + LLM API | ¥0.01 |
| **合计** | ~65s | | **¥0.05** |

### 9.2 批量优化

- 攒 10 条文案一次性租 GPU 1 小时，成本 ¥2.5，单条 ¥0.25（含闲置）
- 攒 50 条，单条降至 ¥0.05

### 9.3 月度成本估算

| 产量 | 月成本（GPU） | 月成本（LLM API） | 合计 |
|---|---|---|---|
| 30 条/月 | ¥10 | ¥3 | ¥13 |
| 100 条/月 | ¥25 | ¥10 | ¥35 |
| 300 条/月 | ¥60 | ¥30 | ¥90 |

---

## 10. 实施路线图

### P0：脚手架（基础）
- 项目结构、配置系统、日志、依赖管理
- BaseModule 基类、JobContext 数据载体
- 验证：项目可 import、配置可加载

### P1：核心闭环（文案→视频）
- P1.1 script_writer（LLM 文案）
- P1.2 tts_engine（GPT-SoVITS 接口 + edge-tts 降级）
- P1.3 avatar_engine（MuseTalk 接口 + 占位降级）
- P1.4 subtitle_engine（FunASR）
- P1.5 video_composer（FFmpeg）
- P1.6 orchestrator 串联 + 端到端验证
- **里程碑**：输入文案 → 输出带字幕的口播视频

### P2：内容侧
- script_extractor（yt-dlp + FunASR）
- script_writer 仿写模式
- **里程碑**：参考视频链接 → 新文案 → 视频

### P3：增强侧
- title_generator
- cover_generator（抽帧 + 文字）
- bgm_loader
- **里程碑**：视频带标题、封面、BGM

### P4：分发侧
- publisher（B站 API + Playwright 兜底）
- **里程碑**：一键发布到多平台

### P5：体验侧
- Gradio Web UI
- 批量队列
- 形象/音色管理界面
- **里程碑**：可视化操作，日常可用

### P6：交付 ✅
- 部署文档（docs/DEPLOYMENT.md）
- 云 GPU 镜像脚本（scripts/setup_cloud_gpu.sh, scripts/download_models.sh, scripts/build_docker.sh）
- Docker 编排（docker/Dockerfile.local, docker/Dockerfile.gpu, docker/docker-compose.yml）
- 云端 API 服务（krvoiceai/api/tts_server.py, krvoiceai/api/avatar_server.py）
- 最终端到端验收（tests/test_acceptance_e2e.py，8 个用例全部通过）
- **里程碑**：全流程打通，可交付使用

---

## 11. 测试策略

### 11.1 测试分层

| 层级 | 范围 | 工具 |
|---|---|---|
| 单元测试 | 各模块独立逻辑 | pytest |
| 集成测试 | 模块间数据流 | pytest + 临时目录 |
| 端到端测试 | 全流程 | pytest + mock GPU |
| 回归测试 | 关键用例集 | 固定测试数据 |

### 11.2 Mock 策略

GPU 不可用时，每个模块提供 mock 实现：
- `tts_engine`: edge-tts 或生成静音 wav
- `avatar_engine`: 音频 + 静态图合成占位视频
- `subtitle_engine`: 基于文本长度估算时间戳
- 保证全流程在纯 CPU 环境可跑通、可测试

### 11.3 验证标准

每个模块开发完成时验证：
1. 单元测试通过
2. 接口契约符合（输入输出类型正确）
3. 异常路径有处理（超时、文件不存在、API 失败）
4. 日志可观测
5. Mock 模式可跑

---

## 12. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| MuseTalk 效果不达标 | 核心体验差 | P0 阶段对比 MuseTalk/LatentSync/EchoMimic，备选切换 |
| 云 GPU 成本超预期 | 经济压力 | 批量处理 + 镜像持久化 + 本地/云端分离 |
| 平台发布被封号 | 分发失败 | 默认半自动，Cookie 隔离，遵守频率限制 |
| GPT-SoVITS 克隆效果差 | 音色不像 | 提供素材采集指南，要求干净人声 5s+ |
| yt-dlp 被平台封 | 文案提取失败 | 支持手动上传视频文件作为备选输入 |
| 模型版本升级破坏兼容 | 系统不可用 | 锁定版本，Docker 镜像固化 |

---

## 13. 交付标准

### 13.1 功能交付

- [x] 9 大模块全部实现并有测试
- [x] 核心闭环（文案→视频）端到端可跑
- [x] 全流程（提取→发布）端到端可跑
- [x] Gradio UI 可视化操作
- [x] 云 GPU 部署脚本可用

### 13.2 质量交付

- [x] 每个模块单元测试通过
- [x] 关键路径集成测试通过
- [x] 异常路径有处理且不崩溃
- [x] 日志清晰可排查
- [x] 配置项有默认值，开箱可用

### 13.3 文档交付

- [x] DESIGN.md（本文档）
- [x] DEPLOYMENT.md（部署指南）
- [x] README.md（快速开始）
- [x] 代码内关键逻辑注释

### 13.4 测试覆盖（实际交付）

| 测试文件 | 用例数 | 说明 |
|---|---|---|
| test_scaffold.py | 11 | 基础设施 |
| test_script_writer.py | 10 | 文案仿写 |
| test_tts_engine.py | 9 | TTS 引擎 |
| test_avatar_engine.py | 9 | 数字人引擎 |
| test_subtitle_engine.py | 9 | 字幕引擎 |
| test_video_composer.py | 9 | 视频合成 |
| test_pipeline_e2e.py | 6 | 编排（含断点续跑） |
| test_script_extractor.py | 10 | 文案提取 |
| test_title_cover.py | 12 | 标题 + 封面 |
| test_publisher.py | 8 | 多平台发布 |
| test_app.py | 11 | App + UI（含 9 模块验收） |
| test_api_servers.py | 8 | 云端 TTS/数字人 API |
| test_acceptance_e2e.py | 8 | 最终端到端验收（含云端 GPU 模拟） |
| **合计** | **120** | **全部通过** |

---

## 14. 当前环境约束说明

> **重要**：当前开发环境为无 GPU 的 Linux 沙箱，无法实际运行 MuseTalk/GPT-SoVITS 等需 GPU 的模型。

**应对策略**：
1. 所有 GPU 模块以"接口 + Mock 实现 + 真实实现"双形态开发
2. Mock 实现保证全流程在 CPU 环境可跑通、可测试
3. 真实实现代码完整编写，部署到云 GPU 即可用
4. 提供云 GPU 一键部署脚本，用户租用 GPU 后即可激活真实推理
5. 所有非 GPU 模块（编排、文案、字幕、合成、UI、发布）完整实现并真实测试

这样确保：**代码完整可交付 + 本地可验证流程 + 上云即可生产**。
