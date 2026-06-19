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
