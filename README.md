# EnlyAI · AI 口播与播客工作站

**全本地部署**的口播视频 / 语音播客一体化生成系统：文案 → 真人级配音 → 数字人口型 → 字幕 → 封面 → BGM → 成片，双击 `EnlyAI.exe` 一键启动与退出。声音、形象、文案模型全部本地运行，素材不出机器。

```
文案输入 → [Ollama Qwen3 润色/仿写] → [原创检测+风控]
        → [CosyVoice3 声音合成（31 音色/克隆/情绪指令）]
        → [LatentSync 扩散唇形同步 + GFPGAN 人脸增强]
        → [Fun-ASR 字幕对齐（卡拉OK逐字）] → [B-roll 台词锚点插播]
        → [封面（智能选帧避画中画）] → [BGM 混音] → 成片
```

## ✨ 核心能力

**🎙️ 声音：CosyVoice3 本地合成（31 个可选音色）**
- 6 个预置主播/解说音色 + 15 个真人克隆音色（中/英/日参考，均支持跨语言合成中文）+ 用户自助上传克隆
- instruct2 自然语言指令控制情绪/语速（"用开心明快的语气说…"）
- 全软件统一音色体系：口播视频、语音播客、音色面板共用一套音色列表，克隆音色自动路由到当前引擎

**🧑 数字人：LatentSync 1.5 扩散唇形 + GFPGAN 人脸增强**
- 音频驱动的扩散模型口型生成（CFG 2.5 标定，口型张合充分），同步固有延迟 < 1 帧
- GFPGAN 生成式人脸修复：嘴部清晰度 P50 +57% / P90 +83%（修复模糊与口内阴影）
- 非 25fps 参考素材自动归一化（消除慢放）；GPU 分时复用（8GB 显存跑全链路）

**📝 字幕：Fun-ASR-Nano 真实对齐的卡拉OK**
- sherpa-onnx 识别 + silero VAD 分段，句级时间戳跟随真实语音节奏
- ASS 卡拉OK逐字高亮、抖音爆款/经典金等 5 种样式预设

**🎞️ 画中画（B-roll）：台词锚点定位**
- 在文案句卡上插入素材，后端按 ASR 真实字幕时间重新定位（前端估算误差可达数秒）
- cut 全屏插播 / pip 角窗画中画两种模式

**🎵 BGM：14 首真实曲库 + 一键试听**
- 按曲目描述定制合成（钢琴/电子/古筝/史诗/爵士…），`scripts/make_bgm.py` 可重新生成
- UI 试听按钮即点即播

**🖥️ 全生命周期管理**
- 双击 exe：自动拉起 Ollama / CosyVoice / LatentSync，浏览器自动打开
- 关闭窗口或 UI「退出」按钮：Windows Job Object + 进程看门狗双重保证，显存/端口零残留
- 服务监管器：conda 环境自动探测、幂等拉起、失败冷却、`GET /api/services` 状态查询

## 🛠️ 技术栈

| 模块 | 方案 | 说明 |
|------|------|------|
| LLM 文案 | Ollama + Qwen3-8B（本地） | 润色/仿写/标题/风控，DeepSeek 云端可选 |
| TTS | **Fun-CosyVoice3-0.5B**（独立 conda 服务 :8012） | 零样本克隆 + instruct2 情绪，fp16 GPU |
| 数字人 | **LatentSync 1.5**（独立 conda 服务 :8011） | 256 分辨率扩散口型，15 步 / CFG 2.5 |
| 人脸增强 | **GFPGAN v1.4**（LatentSync 服务内置） | 生成式修复，默认开启 |
| ASR 字幕 | sherpa-onnx **Fun-ASR-Nano** + silero VAD | 纯 CPU，句级真实时间戳 |
| Web UI | FastAPI + 原生前端（Apple 玻璃态） | 口播向导/播客/音色/形象/设置/系统状态 |
| 编排 | SQLite 状态机 | 断点续跑、分级超时、GPU 分时 |
| 退出保障 | Job Object + 父进程看门狗 | 关窗即全停，无残留 |

## 🚀 快速开始

### 双击 EnlyAI.exe（推荐，全自动）

双击项目根目录的 `EnlyAI.exe`：Web UI 启动并自动打开浏览器，缺失的依赖服务（Ollama / CosyVoice / LatentSync）自动拉起。CosyVoice 冷加载约 50 秒，期间点「生成」会提示稍候。

**退出**：关闭窗口（内核级 Job Object 保证 Web 与全部服务一并终止）或侧边栏「退出 EnlyAI」按钮；手动另开的服务窗口不受影响。

### 命令行

```bash
git clone https://github.com/LancerShawQQ/EnlyAI.git
cd EnlyAI
启动.bat          # 首次运行：创建 .venv + 安装依赖 + 启动 Web
python -m krvoiceai.web.server --port 8000   # 或直接启动
```

### 环境要求（本地全链路）

| 组件 | 要求 | 安装 |
|------|------|------|
| Python | 3.10+ | python.org（勾选 Add to PATH） |
| GPU | NVIDIA ≥8GB（LatentSync 必需；Blackwell 需 torch 2.7+cu128） | — |
| conda 环境 | `CosyVoice`、`LatentSync` | `scripts/setup_cosyvoice_env.bat` / `scripts/setup_latentsync_env.bat` |
| Ollama + Qwen3-8B | 本地 LLM | `ollama pull qwen3:8b` |
| sherpa-onnx | 词句对齐字幕 | `pip install sherpa-onnx`（模型已在 `workspace_data/models/asr/`） |

> 无 GPU 时自动降级：TTS→edge-tts、数字人→mock，流程仍可完整跑通。

## ⚙️ 关键配置（config/user_config.yaml，UI 设置中心可热改）

```yaml
llm:
  provider: ollama           # 本地 Qwen3；也可 deepseek（填 api_key）

tts:
  provider: cosyvoice        # 31 音色；音色列表见 Web「音色」页
  cosyvoice:
    server_url: http://localhost:8012

avatar:
  provider: latentsync
  latentsync:
    server_url: http://localhost:8011
    inference_steps: 15      # 扩散步数
    guidance_scale: 2.5      # 口型张合强度（实测标定，过高易牙形伪影）
    face_enhance: true       # GFPGAN 人脸增强（关掉省一半时长，清晰度回退）

services:                    # 服务自动拉起（留空自动探测 conda）
  auto_start: true
```

## 🎬 使用流程

1. **选音色**：向导第 2 步选 CosyVoice 音色（卡片 ▶ 试听），或「音色」页上传 5-30s 样本注册克隆音色
2. **选形象**：「形象」页上传正脸口播视频注册（建议 25fps、动作自然、表情丰富——成片表情来自素材）
3. **写文案**：直接输入 / LLM 润色 / 爆款模板生成；可对任意句子插入 B-roll 画中画
4. **生成**：一键触发全流程，实时进度 + 分级超时提示；2 分钟视频约 20 分钟（8GB GPU）
5. **发布**：成片页预览/打开目录，多平台发布清单半自动辅助

## 📂 项目结构

```
EnlyAI/
├── EnlyAI.exe                # 双击启动（launcher 打包）
├── krvoiceai/
│   ├── core/
│   │   ├── service_supervisor.py   # 依赖服务监管器（拉起/健康检查/退出清理）
│   │   └── ffmpeg_utils.py         # ffmpeg 封装（无 ffprobe 环境兜底）
│   ├── modules/
│   │   ├── tts_engine.py           # CosyVoice/MOSS/edge 多引擎 + 克隆解析
│   │   ├── avatar_engine.py        # LatentSync 客户端（动态超时/GPU 分时）
│   │   ├── subtitle_engine.py      # Fun-ASR 词句对齐 + 卡拉OK
│   │   ├── broll_engine.py         # 画中画（台词锚点重定位）
│   │   ├── video_composer.py       # 合成（封面/字幕/BGM/转场，音画同步）
│   │   ├── cover_generator.py      # 封面（智能选帧，避开画中画时段）
│   │   └── podcast_engine.py       # 语音播客（多角色/音色路由统一）
│   ├── pipeline/             # 编排（并行步骤/断点续跑/分级重试）
│   └── web/                  # FastAPI + 玻璃态前端
├── config/                   # default.yaml + user_config.yaml + 音色/BGM/模板资产
├── scripts/
│   ├── make_bgm.py           # BGM 曲库合成器（14 首，可重新生成）
│   ├── setup_cosyvoice_env.bat / setup_latentsync_env.bat
│   └── start_all.bat         # 手动分窗启动（备选）
├── CosyVoice/  LatentSync/   # 独立 conda 环境项目（setup 脚本创建）
└── workspace_data/           # 任务产物 / 日志 / ASR 模型
```

## 🧪 质量工程（实测数据）

- **音画同步**：端到端恒定 +1.00s（封面延迟），视频帧匹配与音频包络互相关双向验证 r=1.00；唇形固有滞后 +40ms（<1 帧）
- **口型质量**：guidance 2.5 使张合动态范围 +57%（对比官方默认 1.5）；GFPGAN 使嘴部清晰度 P50 +57% / P90 +83%
- **字幕对齐**：句起点 11/13 命中成片人声能量窗口（ASR 真实时间戳）
- **可靠性**：TTS 失败快速失败（绝不静默降级出无声片）、GPU 分时失效自动重试、服务冷启动超时自适应
- 测试：`tests/`（服务监管器 18 项、视频合成 9 项全绿）

## 📝 已知限制

- LatentSync 官方仅发布 whisper-tiny 特征权重（384 维），快速语流下逐音节贴合度有上限；512 分辨率权重（1.6）需 12GB+ 显存
- LLM/数字人/TTS 三方共享 8GB 显存，靠分时复用调度；生成期间避免同时运行其他大显存任务
- Windows「智能应用控制」开启时会拦截无签名 DLL（conda 环境）——遇到 `应用程序控制策略已阻止此文件` 时用签名版依赖替换（仓库内 openssl 已处理）

## License

MIT
