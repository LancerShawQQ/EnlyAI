"""语音博客生成模块

支持多角色播客音频生成，功能包括：
- 剧本解析（角色名: 台词 格式）
- AI 剧本改写（文章→口语化播客剧本）
- 多角色音色分配（自动/手动）
- 逐段 TTS 合成 + 合并
- SRT 字幕 + JSON 时间戳生成

复用：TTSEngine（moss_nano/edge_tts 等）、LLMClient（剧本改写）
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Optional

from ..core.base_module import BaseModule, JobContext, ModuleResult
from ..core.config import get_config
from ..core.llm_client import LLMClient, get_llm_client
from .tts_engine import TTSEngine


# MOSS 内置音色清单（与 tts_engine.py 同步）
MOSS_BUILTIN_VOICES = {
    # 中文音色
    "Junhao", "Zhiming", "Weiguo", "Xiaoyu", "Yuewen", "Lingyu",
    # 英文音色
    "Trump", "Ava", "Bella", "Adam", "Nathan",
    # 日文音色
    "Soyo", "Saki", "Mortis", "Umiri", "Mei", "Anon", "Arisa",
}

# 音色池分组（按语言+性别）
# 优先使用 edge-tts 音色（合成快约3-5秒），MOSS 作为补充
# edge-tts 中文男声
ZH_MALE_VOICES_EDGE = ["zh-CN-YunxiNeural", "zh-CN-YunjianNeural", "zh-CN-YunyangNeural",
                        "zh-CN-YunzeNeural", "zh-CN-YunfengNeural", "zh-CN-YunhaoNeural",
                        "zh-CN-YunxiaNeural"]
# edge-tts 中文女声
ZH_FEMALE_VOICES_EDGE = ["zh-CN-XiaoxiaoNeural", "zh-CN-XiaoyiNeural", "zh-CN-XiaohanNeural",
                          "zh-CN-XiaomengNeural", "zh-CN-XiaoruiNeural", "zh-CN-XiaomoNeural",
                          "zh-CN-XiaoshuangNeural", "zh-CN-XiaoxuanNeural", "zh-CN-XiaoyanNeural",
                          "zh-CN-XiaozhenNeural"]
# MOSS 中文男声（补充）
ZH_MALE_VOICES = ["Junhao", "Zhiming", "Weiguo"]
# MOSS 中文女声（补充）
ZH_FEMALE_VOICES = ["Xiaoyu", "Yuewen", "Lingyu"]
EN_MALE_VOICES = ["Adam", "Trump", "Nathan"]
EN_FEMALE_VOICES = ["Ava", "Bella"]
JA_FEMALE_VOICES = ["Soyo", "Saki", "Umiri", "Mei", "Anon", "Arisa"]
JA_MALE_VOICES = ["Mortis"]

# 停顿常量（秒）
ROLE_SWITCH_PAUSE = 0.4
SAME_ROLE_PAUSE = 0.12
LEAD_IN_SILENCE = 0.10


# ============ 剧本改写提示词 ============

# 共享的剧本格式规范
_SCRIPT_FORMAT_RULES = """剧本格式（严格遵守）：
- 每行一句，格式为 `角色名: 台词`
- 使用中文冒号或英文冒号均可
- 以 # 开头的行为注释（可标注角色性别，如 `# 张三（男）`）
- 空行会被跳过
- 不要使用 emoji 或特殊符号
- 开头先用注释行声明所有角色及性别，再开始对话"""

# 改写模式：忠实保留原始内容，只做措辞口语化调整 + 适度语气词
PODCAST_REWRITE_SYSTEM = """你是一位口语化改写专家，任务是把书面素材忠实转写为多人对话播客剧本。

最高原则——标准普通话 + 忠实保留内容：
1. **标准普通话**：所有台词必须是标准、清晰的普通话。禁止使用方言词（如"咋""啥""嘞""俺""咱""中""得劲"等）、禁止吞音/连读的文字表示（如把"这样"写成"酱"、"你知道吗"写成"你知道嘛"）。发音必须能让 TTS 引擎正确朗读
2. **忠实保留**：必须覆盖原文的所有核心观点、事实信息、数据、案例，不得遗漏或篡改内容含义
3. **只调整措辞**：只允许把书面语措辞替换为口语化措辞——"综上所述"→"所以"、"具有重要意义"→"很重要"、"在...过程中"→"在...的时候"。不要重新组织段落结构，不要改变论述顺序
4. **适度语气词**：可以加入自然的语气词和叹词增强拟人感——"嗯""呢""啊""吧""哦""对""是的"。但要克制，每句最多1个语气词，不要每句都加，避免做作
5. **自然接话**：角色间可以有简短的自然接话（"对""是的""这个说得好"），但接话内容不得添加原文没有的信息
6. **禁止行为**：禁止添加原文没有的观点/故事/案例/比喻，禁止编造角色间的质疑或对立，禁止改变原文的结论

""" + _SCRIPT_FORMAT_RULES

# 生成模式：围绕主题自由创作（仅用于"只给一个主题"的场景）
PODCAST_GENERATE_SYSTEM = """你是一位顶级的播客制作人和对话设计师，擅长将任何素材转化为令人沉浸的多人对话播客剧本。

你的创作理念：
1. **真实感优先**：像好朋友围坐聊天，不是念稿子。用"你想想看""说白了""我有个感受"这类自然过渡
2. **角色有温度**：每个角色有独特说话习惯——主持人活跃有掌控感、专家用大白话讲专业事、嘉宾敢说真话带情绪
3. **节奏感**：短句为主（15-50字），偶尔来个稍长的（60-80字）展开观点。角色间有接话、打断、追问、感叹
4. **口语化润色**：把书面语翻译成人话——"综上所述"→"所以你看"、"具有重要意义"→"这事挺关键的"
5. **内容有干货**：保留核心信息点，但用比喻、故事、类比包装，让听众秒懂
6. **互动自然**：角色之间要有真实的化学反应——有人抛梗、有人接话、有人质疑、有人总结
7. **避免AI味**：不要用"首先其次最后""值得一提""不可否认"等模板化表达，用"先说一个事""还有一点特别逗""我跟你讲"代替

""" + _SCRIPT_FORMAT_RULES

PODCAST_REWRITE_PROMPT = """请将以下内容改写成一段约{duration}分钟的多人对话播客剧本。

重要：这是"措辞口语化"任务，不是"创作"任务。你只做两件事：①把书面语措辞换成口语措辞 ②适度加入语气词。不要改写内容、不要重新组织结构、不要添加信息。

内容素材：
{content}

改写要求：
- {role_count} 个角色参与对话（{role_desc}）
- 风格：{style}
- 总台词数约 {line_count} 行
- 角色名用简短好记的中文名（如阿杰、小雅、老王）
- 开头用注释行声明所有角色及性别，格式 `# 角色名（男/女）`
- 所有台词必须使用标准普通话，禁止方言词和吞音表示
- 把原文内容分配给各角色转述，保持原文的论述顺序和逻辑
- 适度加入语气词（嗯、呢、啊、吧、哦）和自然接话（对、是的），但每句最多1个语气词
- 主持人开场直接点明原文主题，不要编造故事或反差
- 结尾可简短总结原文要点，不要编造原文未涉及的开放性问题

请直接输出剧本，不要任何解释说明。"""

PODCAST_GENERATE_PROMPT = """请围绕主题「{topic}」创作一段约{duration}分钟的深度对话播客剧本。

创作要求：
- {role_count} 个角色参与对话（{role_desc}）
- 风格：{style}
- 总台词数约 {line_count} 行
- 第一个发言的角色作为主持人，负责破冰开场和节奏引导
- 角色名用简短好记的中文名（如阿杰、小雅、老王）
- 开头用注释行声明所有角色及性别，格式 `# 角色名（男/女）`
- 主持人开场要抓人——用问题、故事或反差感开头，不要"大家好欢迎收听"这种套话
- 内容要有真正的洞察和观点碰撞，不要空话废话
- 对话中要有真实互动（"这个我深有体会""等等你说的这个让我想到...""我不太同意这个观点"）
- 适当用生活化的比喻和类比解释抽象概念
- 结尾要有收束感，主持人做个简短总结或抛个开放性问题

请直接输出剧本，不要任何解释说明。"""


# 丰富扩展模式：在保留原意基础上补充例子/类比/互动，让内容更饱满
PODCAST_EXPAND_SYSTEM = """你是一位擅长内容扩展的播客制作人，任务是把素材扩展为更丰富饱满的多人对话播客剧本。

核心原则——丰富但不跑题：
1. **标准普通话**：所有台词必须是标准、清晰的普通话，禁止方言词和吞音表示
2. **保留原意**：必须覆盖原文所有核心观点，不得遗漏或篡改
3. **适度扩展**：在原文观点基础上，可以补充相关的例子、类比、生活化比喻，让内容更易懂
4. **增加互动**：角色间可以有自然的追问、质疑、补充，让对话更有化学反应
5. **口语化**：用"你想想看""说白了""我举个例"等自然口语过渡
6. **禁止跑题**：扩展内容必须与原文主题相关，禁止编造无关的故事或观点

""" + _SCRIPT_FORMAT_RULES

PODCAST_EXPAND_PROMPT = """请将以下内容扩展为一段约{duration}分钟的多人对话播客剧本，在保留原意的基础上让内容更丰富饱满。

内容素材：
{content}

扩展要求：
- {role_count} 个角色参与对话（{role_desc}）
- 风格：{style}
- 总台词数约 {line_count} 行
- 角色名用简短好记的中文名
- 开头用注释行声明所有角色及性别
- 所有台词必须使用标准普通话
- 在原文观点基础上补充例子、类比、生活化比喻
- 角色间有自然追问、补充、感叹等互动
- 主持人开场点明主题，可加入引人入胜的提问
- 结尾总结要点并可抛出相关思考

请直接输出剧本，不要任何解释说明。"""

# 精简提炼模式：压缩冗余，保留核心观点
PODCAST_CONDENSE_SYSTEM = """你是一位擅长精简提炼的播客制作人，任务是把素材压缩为简洁有力的多人对话播客剧本。

核心原则——精简但不丢核心：
1. **标准普通话**：所有台词必须是标准、清晰的普通话，禁止方言词和吞音表示
2. **保留核心**：必须保留原文最重要的观点和关键数据，只删除冗余表述
3. **压缩冗余**：把长句缩为短句，重复观点合并，删去不重要的细节
4. **节奏紧凑**：对话节奏要快，每句控制在15-40字，信息密度高
5. **口语化**：用简短口语化表达，"综上所述"→"所以"、"具有重要意义"→"很关键"
6. **禁止添加**：不得添加原文没有的内容，只做减法不做加法

""" + _SCRIPT_FORMAT_RULES

PODCAST_CONDENSE_PROMPT = """请将以下内容精简提炼为一段约{duration}分钟的多人对话播客剧本，压缩冗余，保留核心观点。

内容素材：
{content}

精简要求：
- {role_count} 个角色参与对话（{role_desc}）
- 风格：{style}
- 总台词数约 {line_count} 行（比原文更精简）
- 角色名用简短好记的中文名
- 开头用注释行声明所有角色及性别
- 所有台词必须使用标准普通话
- 每句控制在15-40字，信息密度高
- 删去重复观点和不重要细节，合并相似论述
- 保留所有核心观点和关键数据
- 主持人开场简明扼要点明主题
- 结尾一句话总结核心要点

请直接输出剧本，不要任何解释说明。"""


# ============ 工具函数 ============

def parse_script(script_text: str) -> tuple[list[dict], dict[str, str]]:
    """解析播客剧本文本

    Returns:
        (lines, role_genders)
        lines: [{role, text, line}, ...]
        role_genders: {role: "male"/"female"}
    """
    lines = []
    role_genders: dict[str, str] = {}
    line_num = 0

    for raw_line in script_text.split("\n"):
        stripped = raw_line.strip()
        if not stripped:
            continue

        # 注释行：提取角色性别
        if stripped.startswith("#"):
            _extract_gender_from_comment(stripped, role_genders)
            continue

        # 解析 "角色名: 台词" 或 "角色名：台词"
        match = re.match(r"^([^:：]+)[：:]\s*(.+)", stripped)
        if not match:
            continue

        role = match.group(1).strip()
        text = match.group(2).strip()

        if not role or not text:
            continue

        lines.append({
            "role": role,
            "text": text,
            "line": line_num,
        })
        line_num += 1

    return lines, role_genders


def _extract_gender_from_comment(comment: str, role_genders: dict[str, str]) -> None:
    """从注释行提取角色性别"""
    # 匹配 "角色名（男）" / "角色名: 男" / "角色名（女）"
    patterns = [
        (r"([^\s（()【\[\:：]+)\s*[（(【\[]\s*(男|male)", "male"),
        (r"([^\s（()【\[\:：]+)\s*[：:]\s*(男|male)", "male"),
        (r"([^\s（()【\[\:：]+)\s*[（(【\[]\s*(女|female)", "female"),
        (r"([^\s（()【\[\:：]+)\s*[：:]\s*(女|female)", "female"),
    ]
    for pattern, gender in patterns:
        m = re.search(pattern, comment)
        if m:
            role_name = m.group(1).strip()
            if role_name and role_name not in role_genders:
                role_genders[role_name] = gender
            return


def auto_match_voices(
    roles: list[str],
    role_genders: dict[str, str],
    language: str = "zh",
) -> dict[str, str]:
    """自动为角色分配音色（优先 edge-tts，MOSS 补充）

    中文场景优先使用 edge-tts 音色（合成快约3-5秒），edge 池用完后用 MOSS 补充。
    英文/日文场景仍用 MOSS 音色（edge-tts 仅支持中文）。

    Returns:
        {role: voice_id}
    """
    if language == "zh":
        # 中文：edge-tts 优先 + MOSS 补充
        male_pool = list(ZH_MALE_VOICES_EDGE) + list(ZH_MALE_VOICES)
        female_pool = list(ZH_FEMALE_VOICES_EDGE) + list(ZH_FEMALE_VOICES)
    elif language == "ja":
        male_pool = list(JA_MALE_VOICES)
        female_pool = list(JA_FEMALE_VOICES)
    else:
        male_pool = list(EN_MALE_VOICES)
        female_pool = list(EN_FEMALE_VOICES)

    voice_map: dict[str, str] = {}
    male_idx = 0
    female_idx = 0

    for role in roles:
        gender = role_genders.get(role, "")
        if gender == "male":
            if male_idx < len(male_pool):
                voice_map[role] = male_pool[male_idx]
                male_idx += 1
            else:
                voice_map[role] = male_pool[0] if male_pool else "zh-CN-YunxiNeural"
        elif gender == "female":
            if female_idx < len(female_pool):
                voice_map[role] = female_pool[female_idx]
                female_idx += 1
            else:
                voice_map[role] = female_pool[0] if female_pool else "zh-CN-XiaoxiaoNeural"
        else:
            # 性别未知，交替分配
            if male_idx < len(male_pool):
                voice_map[role] = male_pool[male_idx]
                male_idx += 1
            elif female_idx < len(female_pool):
                voice_map[role] = female_pool[female_idx]
                female_idx += 1
            else:
                voice_map[role] = "zh-CN-XiaoxiaoNeural"

    return voice_map


def detect_language(text: str) -> str:
    """检测文本语言（按字符占比：中文/日文/英文）"""
    if not text:
        return "zh"
    # 日文假名检测（平假名 + 片假名）
    ja_count = sum(1 for c in text if "\u3040" <= c <= "\u30ff")
    # 中文字符检测
    zh_count = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    total = max(len(text), 1)
    if ja_count / total > 0.1:
        return "ja"
    if zh_count / total > 0.3:
        return "zh"
    return "en"


def format_srt_timestamp(seconds: float) -> str:
    """格式化为 SRT 时间戳 HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds % 1) * 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"


def generate_srt(segments: list[dict], output_path: Path) -> None:
    """生成 SRT 字幕文件"""
    lines = []
    for i, seg in enumerate(segments, 1):
        start = format_srt_timestamp(seg["start"])
        end = format_srt_timestamp(seg["end"])
        role = seg.get("role", "")
        text = seg.get("text", "")
        lines.append(f"{i}")
        lines.append(f"{start} --> {end}")
        lines.append(f"[{role}] {text}")
        lines.append("")
    output_path.write_text("\n".join(lines), encoding="utf-8")


def generate_timestamps_json(segments: list[dict], total_duration: float, output_path: Path) -> None:
    """生成 JSON 时间戳文件"""
    data = {
        "total_duration": round(total_duration, 2),
        "segment_count": len(segments),
        "segments": segments,
    }
    output_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def estimate_line_count(duration_minutes: int) -> int:
    """根据目标时长估算台词行数"""
    # 平均每行 5-8 秒（含停顿）
    return int(duration_minutes * 60 / 6.5)


# ============ 主模块 ============

class PodcastEngine(BaseModule):
    """语音博客生成引擎

    提供独立的播客生成流水线，不依赖数字人/视频合成模块。
    复用 TTSEngine 进行语音合成，复用 LLMClient 进行剧本改写。
    """

    name = "podcast"
    requires_gpu = False

    def __init__(
        self,
        config=None,
        tts_engine: TTSEngine | None = None,
        llm_client: LLMClient | None = None,
    ):
        super().__init__(config)
        self._tts = tts_engine
        self._llm = llm_client
        # TTS 缓存目录（相同文本+音色组合复用音频）
        self._cache_dir = Path(self.config.get("project.work_root", "./workspace_data")) / "tts_cache"
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        # 按 provider 缓存的 TTSEngine 实例（避免每句都新建实例）
        self._tts_pool: dict[str, TTSEngine] = {}

    @property
    def tts(self) -> TTSEngine:
        """默认 TTS 引擎（向后兼容，返回配置的 provider 引擎）"""
        if self._tts is None:
            self._tts = TTSEngine(config=self.config)
        return self._tts

    def _detect_provider_by_voice(self, voice_id: str) -> str:
        """根据音色ID自动判断 TTS provider

        路由规则：
        - zh-CN-* 开头 → edge_tts
        - MOSS 内置名（Junhao/Trump/...）→ moss_nano
        - 克隆音色（config/voices/ 下有目录）→ moss_nano
        - 其他 → 回退到配置的默认 provider
        """
        if voice_id and voice_id.startswith("zh-"):
            return "edge_tts"
        if voice_id in MOSS_BUILTIN_VOICES:
            return "moss_nano"
        # 克隆音色：检查 config/voices/ 下是否有对应目录
        voices_dir = Path(self.config.get("tts.voices_dir", "./config/voices"))
        if (voices_dir / voice_id).exists():
            return "moss_nano"
        # 回退到配置的默认 provider
        return self.config.get("tts.provider", "moss_nano")

    def _get_tts_for_voice(self, voice_id: str) -> TTSEngine:
        """根据音色ID获取对应的 TTS 引擎实例（带缓存复用）

        不同音色可能需要不同的 provider，这里按 provider 缓存引擎实例，
        避免 MOSS 模型重复加载（首次加载约10秒）。
        """
        provider = self._detect_provider_by_voice(voice_id)
        if provider not in self._tts_pool:
            # 创建指定 provider 的引擎实例
            # 深拷贝配置并覆盖 provider，避免影响全局配置
            import copy
            from ..core.config import Config
            # Config 内部用 _data 存储原始字典
            raw_data = copy.deepcopy(self.config._data) if hasattr(self.config, '_data') else {}
            raw_data.setdefault("tts", {})["provider"] = provider
            new_config = Config(raw_data)
            self._tts_pool[provider] = TTSEngine(config=new_config)
            self._tts_pool[provider].setup()
            self.logger.info(f"已创建 {provider} TTS 引擎实例（音色路由）")
        return self._tts_pool[provider]

    @property
    def llm(self) -> LLMClient:
        if self._llm is None:
            self._llm = get_llm_client()
        return self._llm

    def setup(self) -> None:
        self.logger.info("语音博客引擎初始化")
        super().setup()

    def run(self, ctx: JobContext) -> ModuleResult:
        """流水线模式入口（兼容编排器调用）"""
        # 从 ctx.metadata 读取参数
        script_text = ctx.metadata.get("podcast_script", "")
        voice_map = ctx.metadata.get("podcast_voice_map", {})
        output_dir = ctx.work_dir

        if not script_text:
            return ModuleResult(success=False, error="剧本为空")

        try:
            result = self.generate(
                script_text=script_text,
                voice_map=voice_map,
                output_dir=output_dir,
            )
            ctx.audio_path = result["audio_path"]
            ctx.audio_duration = result["total_duration"]
            ctx.metadata["podcast_result"] = result
            return ModuleResult(success=True, data=result)
        except Exception as e:
            return ModuleResult(success=False, error=str(e))

    # ============ 核心 API ============

    def rewrite_script(
        self,
        content: str,
        mode: str = "polish",
        role_count: int = 3,
        style: str = "轻松对话",
        duration_minutes: int = 5,
        role_desc: str = "",
    ) -> str:
        """将文章/主题改写为播客剧本

        Args:
            content: 原始内容（文章文本或主题描述）
            mode: 改写模式：
                  polish（口语润色：内容不变+语气词）
                  expand（丰富扩展：补充细节）
                  condense（精简提炼：缩短）
                  generate（AI创作：主题生成）
            role_count: 角色数量（0 表示自动，由 AI 决定）
            style: 剧本风格
            duration_minutes: 目标时长（分钟）
            role_desc: 角色描述（如"主持人、行业专家、普通用户"）

        Returns:
            播客剧本文本
        """
        line_count = estimate_line_count(duration_minutes)
        # role_count=0 表示"自动"，让 AI 自行决定角色数
        role_count_text = "自动决定（2-5人）" if role_count == 0 else f"{role_count}"
        if not role_desc:
            role_desc = f"{role_count} 个不同视角的对话者" if role_count > 0 else "2-5 个不同视角的对话者"

        # 根据 mode 选择 prompt 模板
        if mode == "generate":
            prompt = PODCAST_GENERATE_PROMPT.format(
                topic=content,
                duration=duration_minutes,
                role_count=role_count_text,
                role_desc=role_desc,
                style=style,
                line_count=line_count,
            )
        elif mode == "expand":
            prompt = PODCAST_EXPAND_PROMPT.format(
                content=content[:3000],
                duration=duration_minutes,
                role_count=role_count_text,
                role_desc=role_desc,
                style=style,
                line_count=line_count,
            )
        elif mode == "condense":
            prompt = PODCAST_CONDENSE_PROMPT.format(
                content=content[:3000],
                duration=duration_minutes,
                role_count=role_count_text,
                role_desc=role_desc,
                style=style,
                line_count=line_count,
            )
        else:
            # polish（默认，等价于原 rewrite）
            prompt = PODCAST_REWRITE_PROMPT.format(
                content=content[:3000],
                duration=duration_minutes,
                role_count=role_count_text,
                role_desc=role_desc,
                style=style,
                line_count=line_count,
            )

        # 根据 mode 选择不同的 system prompt 和 temperature
        mode_configs = {
            "generate": (PODCAST_GENERATE_SYSTEM, 0.8),   # 创造性强
            "expand":   (PODCAST_EXPAND_SYSTEM, 0.6),     # 适度发散
            "condense": (PODCAST_CONDENSE_SYSTEM, 0.3),   # 精简低发散
            "polish":   (PODCAST_REWRITE_SYSTEM, 0.35),   # 忠实低发散
        }
        system_prompt, temperature = mode_configs.get(mode, mode_configs["polish"])

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]

        self.logger.info(
            f"剧本改写 mode={mode} role_count={role_count} "
            f"style={style} duration={duration_minutes}min temp={temperature} mock={self.llm.is_mock}"
        )
        result = self.llm.chat(messages, temperature=temperature, max_tokens=4096)
        result = result.strip()

        self.logger.info(f"剧本改写完成 output_len={len(result)}")
        return result

    def suggest_voice_map(
        self,
        script_text: str,
        role_genders: dict[str, str] | None = None,
    ) -> dict[str, dict]:
        """根据剧本自动建议音色分配

        Returns:
            {role: {"voice_id": str, "gender": str, "label": str}}
        """
        lines, parsed_genders = parse_script(script_text)
        genders = role_genders or parsed_genders

        # 提取角色列表（按首次出现顺序）
        roles = []
        seen = set()
        for line in lines:
            if line["role"] not in seen:
                roles.append(line["role"])
                seen.add(line["role"])

        # 检测语言
        all_text = " ".join(line["text"] for line in lines)
        language = detect_language(all_text)

        voice_map = auto_match_voices(roles, genders, language)

        # 构建详细信息
        result = {}
        for role in roles:
            voice_id = voice_map.get(role, "Junhao")
            gender = genders.get(role, "unknown")
            result[role] = {
                "voice_id": voice_id,
                "gender": gender,
                "label": self._get_voice_label(voice_id, gender),
            }
        return result

    def _get_voice_label(self, voice_id: str, gender: str) -> str:
        """获取音色的中文标签"""
        labels = {
            # 中文
            "Junhao": "君浩（男·中文）",
            "Zhiming": "志明（男·中文）",
            "Weiguo": "建国（男·中文）",
            "Xiaoyu": "小语（女·中文）",
            "Yuewen": "悦文（女·中文）",
            "Lingyu": "灵语（女·中文）",
            # 英文
            "Trump": "Trump（男·英文）",
            "Ava": "Ava（女·英文）",
            "Bella": "Bella（女·英文）",
            "Adam": "Adam（男·英文）",
            "Nathan": "Nathan（男·英文）",
            # 日文
            "Soyo": "Soyo（女·日文）",
            "Saki": "Saki（女·日文）",
            "Mortis": "Mortis（男·日文）",
            "Umiri": "Umiri（女·日文）",
            "Mei": "Mei（女·日文）",
            "Anon": "Anon（女·日文）",
            "Arisa": "Arisa（女·日文）",
        }
        return labels.get(voice_id, voice_id)

    def generate(
        self,
        script_text: str,
        voice_map: dict[str, str],
        output_dir: Path | str,
        progress_callback: Optional[callable] = None,
        bgm_track: str = "",
        bgm_volume: float = 0.15,
        output_format: str = "wav",
    ) -> dict[str, Any]:
        """生成播客音频（核心方法）

        Args:
            script_text: 播客剧本文本
            voice_map: {角色名: 音色ID}
            output_dir: 输出目录
            progress_callback: 进度回调 (current, total, message)
            bgm_track: BGM 曲目名（如 "soft_piano"），为空则不混入 BGM
            bgm_volume: BGM 音量（0-1），默认 0.15
            output_format: 输出音频格式 wav / mp3

        Returns:
            {
                "audio_path": Path,
                "srt_path": Path,
                "timestamps_path": Path,
                "script_path": Path,
                "total_duration": float,
                "segment_count": int,
                "segments": list[dict],
                "bgm_track": str,
                "bgm_volume": float,
            }
        """
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        # 解析剧本
        lines, _ = parse_script(script_text)
        if not lines:
            raise ValueError("剧本解析失败，未找到有效台词")

        self.logger.info(
            f"播客生成开始 lines={len(lines)} roles={list(voice_map.keys())} "
            f"output={output_dir}"
        )

        # 逐段合成（直接在内存中收集音频数据，不写单独的 segments 文件）
        import soundfile as sf
        import numpy as np
        import tempfile

        sample_rate = 24000
        segments: list[dict] = []
        all_audio_chunks: list[np.ndarray] = []  # 内存中收集所有音频片段
        cursor = 0.0  # 当前时间游标
        prev_role: Optional[str] = None

        # 预热 MOSS 运行时（避免首次合成时 60 秒模型加载导致 TTS 超时）
        # 根因：MOSS-TTS-Nano 首次加载需要约 60 秒，加上克隆合成时间，
        #        总计可能超过原 120 秒超时，导致克隆音色（如 Lancer）的台词被静音填充
        moss_voice_ids = {v for v in voice_map.values() if self._detect_provider_by_voice(v) == "moss_nano"}
        if moss_voice_ids:
            self.logger.info(f"预热 MOSS 运行时（{len(moss_voice_ids)} 个 MOSS 音色: {moss_voice_ids}）...")
            if progress_callback:
                progress_callback(0, len(lines), "正在加载 TTS 引擎...")
            try:
                first_moss_voice = next(iter(moss_voice_ids))
                moss_engine = self._get_tts_for_voice(first_moss_voice)
                # 触发 MOSS 模型加载（首次约 60 秨）
                if hasattr(moss_engine, '_get_moss_runtime'):
                    moss_engine._get_moss_runtime()
                self.logger.info("MOSS 运行时预热完成")
            except Exception as e:
                self.logger.warning(f"MOSS 运行时预热失败: {e}")

        for i, line in enumerate(lines):
            role = line["role"]
            text = line["text"]
            voice_id = voice_map.get(role, "Junhao")

            # 计算停顿
            if prev_role is None:
                pause_before = 0.0
            elif prev_role != role:
                pause_before = ROLE_SWITCH_PAUSE
            else:
                pause_before = SAME_ROLE_PAUSE

            # 添加停顿静音到内存
            if i > 0:
                pause_samples = int(sample_rate * pause_before)
                all_audio_chunks.append(np.zeros(pause_samples, dtype=np.float32))

            # 引导静音
            lead_in_samples = int(sample_rate * LEAD_IN_SILENCE)
            all_audio_chunks.append(np.zeros(lead_in_samples, dtype=np.float32))

            # 进度回调
            if progress_callback:
                progress_callback(i + 1, len(lines), f"合成第 {i+1}/{len(lines)} 句：{role}")

            # TTS 合成（带缓存 + 超时保护）
            cache_key = self._get_cache_key(text, voice_id)
            cache_path = self._cache_dir / f"{cache_key}.wav"
            seg_audio: np.ndarray | None = None
            duration = 0.0

            if cache_path.exists():
                # 缓存命中，直接读取到内存
                seg_audio, sr = sf.read(str(cache_path), dtype="float32")
                if seg_audio.ndim > 1:
                    seg_audio = seg_audio.mean(axis=1)
                if sr != sample_rate:
                    ratio = sample_rate / sr
                    new_len = int(len(seg_audio) * ratio)
                    indices = np.linspace(0, len(seg_audio) - 1, new_len)
                    seg_audio = np.interp(indices, np.arange(len(seg_audio)), seg_audio).astype(np.float32)
                duration = len(seg_audio) / sample_rate
                self.logger.info(f"第 {i} 句缓存命中: {role} voice={voice_id} duration={duration:.1f}s")
            else:
                # TTS 合成（直接同步调用）
                # 原线程池方案已移除：ThreadPoolExecutor 子线程中 ONNX 推理性能严重下降
                # （同步75秒完成的克隆合成，在线程池中>180秒仍未完成），且超时后 worker
                # 线程无法停止，残留线程干扰后续合成。同步调用经独立测试验证稳定可靠。
                tmp_path = Path(tempfile.mktemp(suffix=".wav", dir=str(self._cache_dir.parent / "tmp")))
                tmp_path.parent.mkdir(parents=True, exist_ok=True)
                try:
                    # 根据音色ID自动路由到对应 provider 的引擎
                    tts_engine = self._get_tts_for_voice(voice_id)
                    audio_path, duration, _ = tts_engine.synthesize(
                        text=text, voice_id=voice_id, output_path=tmp_path,
                    )

                    # 读取到内存
                    seg_audio, sr = sf.read(str(tmp_path), dtype="float32")
                    if seg_audio.ndim > 1:
                        seg_audio = seg_audio.mean(axis=1)
                    if sr != sample_rate:
                        ratio = sample_rate / sr
                        new_len = int(len(seg_audio) * ratio)
                        indices = np.linspace(0, len(seg_audio) - 1, new_len)
                        seg_audio = np.interp(indices, np.arange(len(seg_audio)), seg_audio).astype(np.float32)
                    duration = len(seg_audio) / sample_rate

                    # 写入缓存
                    import shutil
                    shutil.copy2(str(tmp_path), str(cache_path))

                    # 清理临时文件
                    tmp_path.unlink(missing_ok=True)

                except Exception as e:
                    self.logger.error(f"第 {i} 句合成失败: {e}")
                    # 用静音填充
                    duration = max(1.0, len(text) * 0.15)
                    seg_audio = np.zeros(int(sample_rate * duration), dtype=np.float32)

            # 添加到内存合并列表
            all_audio_chunks.append(seg_audio)

            # 计算时间戳
            start = cursor + LEAD_IN_SILENCE
            end = start + duration
            cursor = end

            segments.append({
                "index": i,
                "role": role,
                "text": text,
                "duration": round(duration, 2),
                "start": round(start, 2),
                "end": round(end, 2),
                "pause_before": pause_before,
                "lead_in": LEAD_IN_SILENCE,
                "voice_id": voice_id,
            })

            prev_role = role

        # 合并音频（直接从内存拼接，无需读取文件）
        if progress_callback:
            progress_callback(len(lines), len(lines), "合并音频中...")

        # 统一用临时 wav 文件做中间产物，最后转为目标格式并删除临时文件
        merged_audio = np.concatenate(all_audio_chunks) if all_audio_chunks else np.zeros(0, dtype=np.float32)
        # 先写到临时 wav（供 BGM 混音或格式转换用）
        tmp_wav = output_dir / "_tmp_voice.wav"
        sf.write(str(tmp_wav), merged_audio, sample_rate, subtype="PCM_16")

        # 混入 BGM（如有）→ 输出到临时混音 wav
        bgm_mixed_wav = tmp_wav  # 默认无 BGM，直接用原始 wav
        if bgm_track:
            if progress_callback:
                progress_callback(len(lines), len(lines), "混入背景音乐...")
            bgm_mixed_wav = output_dir / "_tmp_mixed.wav"
            mixed = self._mix_bgm(
                voice_path=tmp_wav,
                bgm_track=bgm_track,
                bgm_volume=bgm_volume,
                total_duration=cursor,
                output_path=bgm_mixed_wav,
            )
            if not mixed:
                # BGM 混音失败，回退使用纯语音
                self.logger.warning(f"BGM 混音失败，回退纯语音 bgm_track={bgm_track}")
                bgm_mixed_wav = tmp_wav
                bgm_track = ""  # 标记实际未混入
            # 删除原始纯语音临时文件
            tmp_wav.unlink(missing_ok=True)

        # 转换为最终输出格式
        output_format = (output_format or "wav").lower()
        if output_format not in ("wav", "mp3"):
            output_format = "wav"
        final_audio_path = output_dir / f"podcast.{output_format}"

        if output_format == "wav":
            # 直接重命名临时文件为最终文件
            bgm_mixed_wav.rename(final_audio_path)
        else:
            # mp3：用 soundfile 直接编码（不依赖 ffmpeg）
            if progress_callback:
                progress_callback(len(lines), len(lines), "转换为 MP3...")
            try:
                _data, _sr = sf.read(str(bgm_mixed_wav), dtype="float32")
                if _data.ndim > 1:
                    _data = _data.mean(axis=1)
                sf.write(str(final_audio_path), _data, _sr, format="MP3")
            except Exception as e:
                self.logger.warning(f"MP3 转换失败({e})，回退 WAV")
                final_audio_path = output_dir / "podcast.wav"
                bgm_mixed_wav.rename(final_audio_path)
            # 删除临时 wav
            bgm_mixed_wav.unlink(missing_ok=True)

        # 生成字幕
        srt_path = output_dir / "podcast.srt"
        generate_srt(segments, srt_path)

        # 生成时间戳 JSON
        timestamps_path = output_dir / "timestamps.json"
        generate_timestamps_json(segments, cursor, timestamps_path)

        # 保存剧本
        script_path = output_dir / "script.txt"
        script_path.write_text(script_text, encoding="utf-8")

        total_duration = cursor

        self.logger.info(
            f"播客生成完成 duration={total_duration:.1f}s "
            f"segments={len(segments)} bgm={bgm_track or 'none'} output={output_dir}"
        )

        return {
            "audio_path": str(final_audio_path),
            "srt_path": str(srt_path),
            "timestamps_path": str(timestamps_path),
            "script_path": str(script_path),
            "total_duration": round(total_duration, 2),
            "segment_count": len(segments),
            "segments": segments,
            "bgm_track": bgm_track,
            "bgm_volume": bgm_volume if bgm_track else 0.0,
        }

    def _get_cache_key(self, text: str, voice_id: str) -> str:
        """生成 TTS 缓存键（基于文本+音色的 hash）"""
        import hashlib
        content = f"{voice_id}|{text}"
        return hashlib.md5(content.encode("utf-8")).hexdigest()[:16]

    def _get_wav_duration(self, path: Path) -> float:
        """获取 WAV 文件时长（秒）"""
        import wave
        try:
            with wave.open(str(path), "rb") as wf:
                return wf.getnframes() / wf.getframerate()
        except Exception:
            return 0.0

    def _merge_audio_files(
        self,
        audio_paths: list[Path],
        segments: list[dict],
        output_path: Path,
    ) -> None:
        """合并音频片段（含停顿和引导静音）"""
        import soundfile as sf
        import numpy as np

        sample_rate = 24000
        all_audio: list[np.ndarray] = []

        for i, (audio_path, seg) in enumerate(zip(audio_paths, segments)):
            # 添加停顿静音
            if i > 0:
                pause_samples = int(sample_rate * seg["pause_before"])
                all_audio.append(np.zeros(pause_samples, dtype=np.float32))

            # 引导静音
            lead_in_samples = int(sample_rate * seg["lead_in"])
            all_audio.append(np.zeros(lead_in_samples, dtype=np.float32))

            # 读取音频
            data, sr = sf.read(str(audio_path), dtype="float32")
            if data.ndim > 1:
                data = data.mean(axis=1)
            if sr != sample_rate:
                # 简单重采样（避免引入额外依赖）
                ratio = sample_rate / sr
                new_len = int(len(data) * ratio)
                indices = np.linspace(0, len(data) - 1, new_len)
                data = np.interp(indices, np.arange(len(data)), data).astype(np.float32)
            all_audio.append(data)

        merged = np.concatenate(all_audio) if all_audio else np.zeros(0, dtype=np.float32)
        sf.write(str(output_path), merged, sample_rate, subtype="PCM_16")

    def _mix_bgm(
        self,
        voice_path: Path,
        bgm_track: str,
        bgm_volume: float,
        total_duration: float,
        output_path: Path,
    ) -> bool:
        """将 BGM 混入语音音频（使用 soundfile + numpy）

        BGM 会循环播放并截取到语音时长，按指定音量混入。
        语音为主（音量不变），BGM 为辅（按 bgm_volume 缩放）。

        Args:
            voice_path: 纯语音 WAV 文件路径
            bgm_track: BGM 曲目名（如 "soft_piano"）
            bgm_volume: BGM 音量（0-1）
            total_duration: 语音总时长（秒），用于截取 BGM
            output_path: 输出文件路径

        Returns:
            True 表示混音成功，False 表示失败（调用方应回退）
        """
        import soundfile as sf
        import numpy as np

        # 查找 BGM 文件
        bgm_dir = Path(self.config.get("composer.bgm_dir", "./config/bgm"))
        bgm_file: Path | None = None
        for ext in (".mp3", ".m4a", ".wav"):
            candidate = bgm_dir / f"{bgm_track}{ext}"
            if candidate.exists():
                bgm_file = candidate
                break
        if not bgm_file:
            self.logger.warning(f"BGM 文件未找到: {bgm_track} in {bgm_dir}")
            return False

        # 限制 BGM 音量到合理范围
        vol = max(0.0, min(1.0, float(bgm_volume)))
        sample_rate = 24000

        try:
            # 1. 读取语音音频
            voice_data, voice_sr = sf.read(str(voice_path), dtype="float32")
            if voice_data.ndim > 1:
                voice_data = voice_data.mean(axis=1)
            # 重采样到目标采样率（如有必要）
            if voice_sr != sample_rate:
                ratio = sample_rate / voice_sr
                new_len = int(len(voice_data) * ratio)
                indices = np.linspace(0, len(voice_data) - 1, new_len)
                voice_data = np.interp(indices, np.arange(len(voice_data)), voice_data).astype(np.float32)

            # 2. 读取 BGM 音频
            bgm_data, bgm_sr = sf.read(str(bgm_file), dtype="float32")
            # 转为单声道
            if bgm_data.ndim > 1:
                bgm_data = bgm_data.mean(axis=1)
            # 重采样到目标采样率
            if bgm_sr != sample_rate:
                ratio = sample_rate / bgm_sr
                new_len = int(len(bgm_data) * ratio)
                indices = np.linspace(0, len(bgm_data) - 1, new_len)
                bgm_data = np.interp(indices, np.arange(len(bgm_data)), bgm_data).astype(np.float32)

            # 3. 循环 BGM 到语音时长
            target_len = len(voice_data)
            if len(bgm_data) == 0:
                self.logger.warning(f"BGM 音频为空: {bgm_track}")
                return False
            if len(bgm_data) < target_len:
                # 循环拼接
                repeats = int(np.ceil(target_len / len(bgm_data)))
                bgm_data = np.tile(bgm_data, repeats)
            bgm_data = bgm_data[:target_len]

            # 4. 混音：语音 + BGM * vol
            # 注意：float32 音频范围是 [-1.0, 1.0]，直接相加可能超过 1.0 导致削波
            # 使用 soft clipping（tanh）防止削波
            mixed = voice_data + bgm_data * vol
            mixed = np.tanh(mixed).astype(np.float32)  # soft clip 防止削波

            # 5. 写入输出文件
            sf.write(str(output_path), mixed, sample_rate, subtype="PCM_16")

            self.logger.info(
                f"BGM 混音成功 track={bgm_track} volume={vol} "
                f"duration={total_duration:.1f}s output={output_path}"
            )
            return True
        except Exception as e:
            self.logger.error(f"BGM 混音异常: {e}", exc_info=True)
            return False
