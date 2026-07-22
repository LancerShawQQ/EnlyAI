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
ZH_MALE_VOICES = ["Junhao", "Zhiming", "Weiguo"]
ZH_FEMALE_VOICES = ["Xiaoyu", "Yuewen", "Lingyu"]

# 停顿常量（秒）
ROLE_SWITCH_PAUSE = 0.4
SAME_ROLE_PAUSE = 0.12
LEAD_IN_SILENCE = 0.10


# ============ 剧本改写提示词 ============

PODCAST_REWRITE_SYSTEM = """你是一位资深的播客制作人，擅长将文章、资料改写成自然流畅的多人对话播客剧本。

你的剧本遵循以下原则：
1. 口语化表达，像朋友聊天，避免书面语和学术腔
2. 角色间有自然互动（回应、追问、补充、感叹）
3. 适当加入语气词（嗯、啊、对、没错、就是说）增加真实感
4. 复杂内容用比喻或举例简化
5. 每段台词控制在 20-80 字，避免过长独白
6. 角色性格鲜明（主持人引导/专家深度/嘉宾接地气）

剧本格式（严格遵守）：
- 每行一句，格式为 `角色名: 台词`
- 使用中文冒号或英文冒号均可
- 以 # 开头的行为注释（可标注角色性别，如 `# 张三（男）`）
- 空行会被跳过
- 不要使用 emoji 或特殊符号"""

PODCAST_REWRITE_PROMPT = """请将以下内容改写成一段{duration}分钟的多人播客剧本。

内容素材：
{content}

要求：
- {role_count} 个角色参与对话（{role_desc}）
- 风格：{style}
- 总台词数约 {line_count} 行
- 第一个发言的角色作为主持人，负责开场和引导
- 角色名用简短中文名（如张三、李四、小王）
- 在注释行标注每个角色的性别，如 `# 张三（男）`

请直接输出剧本，不要任何解释说明。"""

PODCAST_GENERATE_PROMPT = """请围绕主题「{topic}」创作一段{duration}分钟的多人播客剧本。

要求：
- {role_count} 个角色参与对话（{role_desc}）
- 风格：{style}
- 总台词数约 {line_count} 行
- 内容有深度、有观点碰撞，避免空话
- 第一个发言的角色作为主持人，负责开场和引导
- 角色名用简短中文名（如张三、李四、小王）
- 在注释行标注每个角色的性别，如 `# 张三（男）`

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
    """自动为角色分配音色

    Returns:
        {role: voice_id}
    """
    if language == "zh":
        male_pool = list(ZH_MALE_VOICES)
        female_pool = list(ZH_FEMALE_VOICES)
    else:
        male_pool = ["Adam", "Trump", "Nathan"]
        female_pool = ["Ava", "Bella"]

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
                voice_map[role] = male_pool[0] if male_pool else "Junhao"
        elif gender == "female":
            if female_idx < len(female_pool):
                voice_map[role] = female_pool[female_idx]
                female_idx += 1
            else:
                voice_map[role] = female_pool[0] if female_pool else "Xiaoyu"
        else:
            # 性别未知，交替分配
            if male_idx < len(male_pool):
                voice_map[role] = male_pool[male_idx]
                male_idx += 1
            elif female_idx < len(female_pool):
                voice_map[role] = female_pool[female_idx]
                female_idx += 1
            else:
                voice_map[role] = "Junhao"

    return voice_map


def detect_language(text: str) -> str:
    """检测文本语言（简单按中文字符占比）"""
    if not text:
        return "zh"
    cjk_count = sum(1 for c in text if "\u4e00" <= c <= "\u9fff")
    return "zh" if cjk_count / max(len(text), 1) > 0.3 else "en"


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

    @property
    def tts(self) -> TTSEngine:
        if self._tts is None:
            self._tts = TTSEngine(config=self.config)
        return self._tts

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
        mode: str = "rewrite",
        role_count: int = 3,
        style: str = "轻松对话",
        duration_minutes: int = 5,
        role_desc: str = "",
    ) -> str:
        """将文章/主题改写为播客剧本

        Args:
            content: 原始内容（文章文本或主题描述）
            mode: rewrite（改写已有内容）| generate（根据主题生成）
            role_count: 角色数量
            style: 剧本风格
            duration_minutes: 目标时长（分钟）
            role_desc: 角色描述（如"主持人、行业专家、普通用户"）

        Returns:
            播客剧本文本
        """
        line_count = estimate_line_count(duration_minutes)
        if not role_desc:
            role_desc = f"{role_count} 个不同视角的对话者"

        if mode == "generate":
            prompt = PODCAST_GENERATE_PROMPT.format(
                topic=content,
                duration=duration_minutes,
                role_count=role_count,
                role_desc=role_desc,
                style=style,
                line_count=line_count,
            )
        else:
            prompt = PODCAST_REWRITE_PROMPT.format(
                content=content[:3000],  # 限制长度避免超 token
                duration=duration_minutes,
                role_count=role_count,
                role_desc=role_desc,
                style=style,
                line_count=line_count,
            )

        messages = [
            {"role": "system", "content": PODCAST_REWRITE_SYSTEM},
            {"role": "user", "content": prompt},
        ]

        self.logger.info(
            f"剧本改写 mode={mode} role_count={role_count} "
            f"style={style} duration={duration_minutes}min mock={self.llm.is_mock}"
        )
        result = self.llm.chat(messages, temperature=0.8, max_tokens=4096)
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
            "Junhao": "君浩（男·中文）",
            "Zhiming": "志明（男·中文）",
            "Weiguo": "建国（男·中文）",
            "Xiaoyu": "小语（女·中文）",
            "Yuewen": "悦文（女·中文）",
            "Lingyu": "灵语（女·中文）",
            "Trump": "Trump（男·英文）",
            "Ava": "Ava（女·英文）",
            "Bella": "Bella（女·英文）",
            "Adam": "Adam（男·英文）",
            "Nathan": "Nathan（男·英文）",
        }
        return labels.get(voice_id, voice_id)

    def generate(
        self,
        script_text: str,
        voice_map: dict[str, str],
        output_dir: Path | str,
        progress_callback: Optional[callable] = None,
    ) -> dict[str, Any]:
        """生成播客音频（核心方法）

        Args:
            script_text: 播客剧本文本
            voice_map: {角色名: 音色ID}
            output_dir: 输出目录
            progress_callback: 进度回调 (current, total, message)

        Returns:
            {
                "audio_path": Path,
                "srt_path": Path,
                "timestamps_path": Path,
                "script_path": Path,
                "total_duration": float,
                "segment_count": int,
                "segments": list[dict],
            }
        """
        output_dir = Path(output_dir).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)
        segments_dir = output_dir / "segments"
        segments_dir.mkdir(exist_ok=True)

        # 解析剧本
        lines, _ = parse_script(script_text)
        if not lines:
            raise ValueError("剧本解析失败，未找到有效台词")

        self.logger.info(
            f"播客生成开始 lines={len(lines)} roles={list(voice_map.keys())} "
            f"output={output_dir}"
        )

        # 逐段合成
        segments: list[dict] = []
        cursor = 0.0  # 当前时间游标
        prev_role: Optional[str] = None

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

            # 进度回调
            if progress_callback:
                progress_callback(i + 1, len(lines), f"合成第 {i+1}/{len(lines)} 句：{role}")

            # TTS 合成
            seg_path = segments_dir / f"seg_{i:04d}_{role}.wav"
            try:
                audio_path, duration, _ = self.tts.synthesize(
                    text=text,
                    voice_id=voice_id,
                    output_path=seg_path,
                )
            except Exception as e:
                self.logger.error(f"第 {i} 句合成失败: {e}")
                # 用静音填充
                from ..core.audio_utils import generate_silent_wav
                duration = max(1.0, len(text) * 0.15)
                generate_silent_wav(seg_path, duration)
                audio_path = seg_path

            # 计算时间戳
            start = cursor + LEAD_IN_SILENCE
            end = start + duration
            cursor = end

            segments.append({
                "index": i,
                "role": role,
                "text": text,
                "audio_path": str(audio_path),
                "duration": round(duration, 2),
                "start": round(start, 2),
                "end": round(end, 2),
                "pause_before": pause_before,
                "lead_in": LEAD_IN_SILENCE,
                "voice_id": voice_id,
            })

            prev_role = role

        # 合并音频
        if progress_callback:
            progress_callback(len(lines), len(lines), "合并音频中...")

        merged_path = output_dir / "podcast.wav"
        self._merge_audio_files(
            [Path(s["audio_path"]) for s in segments],
            segments,
            merged_path,
        )

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
            f"segments={len(segments)} output={output_dir}"
        )

        return {
            "audio_path": str(merged_path),
            "srt_path": str(srt_path),
            "timestamps_path": str(timestamps_path),
            "script_path": str(script_path),
            "total_duration": round(total_duration, 2),
            "segment_count": len(segments),
            "segments": segments,
        }

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
