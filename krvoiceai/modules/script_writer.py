"""文案生成模块

支持三种模式：
- polish: 润色已有文案，保留原意优化表达
- rewrite: 语义级仿写，保留结构替换表达（避免查重）
- generate: 根据主题/要点生成全新口播文案

口播文案结构：开场钩子 → 价值点 → CTA
"""
from __future__ import annotations

from typing import Any

from ..core.base_module import BaseModule, JobContext, ModuleResult
from ..core.llm_client import LLMClient, get_llm_client


# 口播文案系统提示词
SYSTEM_PROMPT = """你是一位资深的短视频口播文案创作者，擅长创作高完播率、高互动的口播内容。

你的文案遵循以下结构：
1. 开场钩子（前3秒）：用疑问、反差、数字或痛点抓住注意力
2. 价值主体：3-5个核心要点，每个要点简洁有力，口语化表达
3. 行动号召（CTA）：引导点赞、关注、收藏

写作要求：
- 口语化，像和朋友聊天，避免书面语
- 短句为主，每句不超过20字
- 适当使用语气词（啊、呢、吧）增加亲和力
- 段落间用换行分隔，便于配音停顿
- 总字数控制在150-400字（约1-2分钟口播）
- 不要使用 emoji 和特殊符号
- 不要标注"开场""主体"等结构标签，直接输出文案内容"""

POLISH_PROMPT = """请润色以下口播文案，使其更口语化、更有感染力，但保留原意和核心信息。

原始文案：
{input}

请直接输出润色后的文案，不要任何解释说明。"""

REWRITE_PROMPT = """请对以下口播文案进行语义级仿写，要求：
- 保留原文的核心观点和信息结构
- 替换表达方式、句式、用词，避免与原文雷同
- 保持口播风格，适合短视频配音
- 可以调整顺序、增删细节，但核心价值不变

原始文案：
{input}

请直接输出仿写后的文案，不要任何解释说明。"""

GENERATE_PROMPT = """请根据以下主题/要点，创作一段口播文案：

主题/要求：
{input}

请直接输出文案内容，不要任何解释说明。"""

# 爆款结构分析提示词
ANALYZE_PROMPT = """你是一位短视频爆款文案分析师，擅长拆解高完播率、高互动口播视频的结构密码。

请对以下口播文案进行深度爆款结构分析，按 JSON 格式输出分析报告：

待分析文案：
{input}

请严格按以下 JSON 结构输出（不要输出 JSON 以外的内容，不要用 markdown 代码块包裹）：
{{
  "hook_type": "开场钩子类型（疑问/反差/数字/痛点/悬念/故事/争议 之一）",
  "hook_analysis": "前3秒钩子为什么能/不能抓住注意力的分析（30-50字）",
  "emotion_curve": "情绪曲线描述（如：紧张→共鸣→希望→行动，20-30字）",
  "structure": [
    {{"part": "开场", "content": "原文对应片段", "effect": "作用分析（20字内）"}},
    {{"part": "主体", "content": "原文对应片段", "effect": "作用分析（20字内）"}},
    {{"part": "结尾", "content": "原文对应片段", "effect": "作用分析（20字内）"}}
  ],
  "highlights": ["亮点1", "亮点2", "亮点3"],
  "weaknesses": ["不足1", "不足2"],
  "viral_score": 75,
  "improvement": "改进建议（40-60字，针对不足给出具体优化方向）",
  "rewrite_direction": "仿写方向建议（20-30字，指明保持什么、替换什么）"
}}"""


class ScriptWriter(BaseModule):
    """文案生成/润色/仿写模块"""

    name = "script_write"
    requires_gpu = False

    def __init__(self, config=None, llm_client: LLMClient | None = None):
        super().__init__(config)
        self.llm = llm_client or get_llm_client()

    def setup(self) -> None:
        self.logger.info(
            f"文案模块初始化 provider={self.llm.provider} "
            f"mock={self.llm.is_mock}"
        )
        super().setup()

    def run(self, ctx: JobContext) -> ModuleResult:
        """根据 ctx.input_script 和 ctx.metadata['mode'] 生成文案"""
        mode = ctx.metadata.get("script_mode", "polish")
        raw = ctx.input_script or ctx.metadata.get("raw_script", "")

        if not raw:
            return ModuleResult(
                success=False,
                error="输入文案为空，无法处理",
            )

        try:
            result_text = self.write(raw, mode=mode)
            ctx.script_text = result_text
            return ModuleResult(
                success=True,
                data={
                    "script_text": result_text,
                    "mode": mode,
                    "char_count": len(result_text),
                    "mock": self.llm.is_mock,
                },
            )
        except Exception as e:
            return ModuleResult(success=False, error=str(e))

    def write(self, raw_text: str, mode: str = "polish") -> str:
        """核心方法：生成文案

        Args:
            raw_text: 原始文案/主题
            mode: polish | rewrite | generate

        Returns:
            处理后的文案文本
        """
        if mode not in ("polish", "rewrite", "generate"):
            raise ValueError(f"不支持的 mode: {mode}")

        templates = {
            "polish": POLISH_PROMPT,
            "rewrite": REWRITE_PROMPT,
            "generate": GENERATE_PROMPT,
        }
        user_prompt = templates[mode].format(input=raw_text)

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        self.logger.info(
            f"文案生成 mode={mode} input_len={len(raw_text)} mock={self.llm.is_mock}"
        )
        result = self.llm.chat(messages)
        result = self._postprocess(result)
        self.logger.info(f"文案生成完成 output_len={len(result)}")
        return result

    def analyze(self, text: str) -> dict:
        """爆款结构分析：拆解文案的钩子/情绪/结构/亮点，返回结构化报告

        Args:
            text: 待分析的口播文案

        Returns:
            分析报告 dict，含 hook_type/emotion_curve/structure/highlights/weaknesses/
            viral_score/improvement/rewrite_direction
        """
        import json

        user_prompt = ANALYZE_PROMPT.format(input=text)
        messages = [
            {"role": "system", "content": "你是短视频爆款文案分析专家。只输出JSON，不加任何解释。"},
            {"role": "user", "content": user_prompt},
        ]

        self.logger.info(f"爆款分析开始 input_len={len(text)} mock={self.llm.is_mock}")
        raw = self.llm.chat(messages, temperature=0.3)

        # 清理可能的 markdown 代码块包裹
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        raw = raw.strip()

        try:
            report = json.loads(raw)
        except json.JSONDecodeError:
            # JSON 解析失败时返回降级报告
            self.logger.warning(f"爆款分析 JSON 解析失败，返回降级报告")
            report = {
                "hook_type": "未知",
                "hook_analysis": "分析结果解析失败，请重试",
                "emotion_curve": "未知",
                "structure": [],
                "highlights": [],
                "weaknesses": [],
                "viral_score": 0,
                "improvement": "分析失败，请检查 LLM 返回格式",
                "rewrite_direction": "建议手动润色",
                "raw_response": raw[:500],
            }

        self.logger.info(f"爆款分析完成 score={report.get('viral_score')}")
        return report

    def _postprocess(self, text: str) -> str:
        """后处理：去除多余空行、首尾空白"""
        lines = [line.strip() for line in text.splitlines()]
        # 合并连续空行为单个空行
        cleaned: list[str] = []
        prev_empty = False
        for line in lines:
            if not line:
                if not prev_empty:
                    cleaned.append("")
                prev_empty = True
            else:
                cleaned.append(line)
                prev_empty = False
        # 去除首尾空行
        while cleaned and not cleaned[0]:
            cleaned.pop(0)
        while cleaned and not cleaned[-1]:
            cleaned.pop()
        return "\n".join(cleaned)
