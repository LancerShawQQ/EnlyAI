"""标题生成模块

根据口播文案生成吸睛标题，支持多平台风格。

平台风格：
- douyin: 情绪钩子、悬念、数字
- kuaishou: 接地气、生活化
- bilibili: 信息量、专业感
- wechat_video: 价值导向、实用
"""
from __future__ import annotations

import re
from typing import Optional

from ..core.base_module import BaseModule, JobContext, ModuleResult
from ..core.llm_client import LLMClient, get_llm_client


# 各平台标题提示词
PLATFORM_PROMPTS = {
    "douyin": """请为以下口播文案生成 5 个抖音风格的吸睛标题。

要求：
- 15-25 字，带情绪钩子或悬念
- 可用数字、反问、对比等手法
- 避免标题党但要有吸引力
- 每行一个标题，不要编号

文案：
{script}""",
    "bilibili": """请为以下口播文案生成 5 个 B 站风格的标题。

要求：
- 20-30 字，信息量充足
- 体现专业感和干货属性
- 可用「|」「-」等分隔符
- 每行一个标题，不要编号

文案：
{script}""",
    "kuaishou": """请为以下口播文案生成 5 个快手风格的标题。

要求：
- 15-20 字，接地气、生活化
- 像朋友聊天一样自然
- 每行一个标题，不要编号

文案：
{script}""",
    "wechat_video": """请为以下口播文案生成 5 个视频号风格的标题。

要求：
- 18-25 字，价值导向
- 突出实用性和收获感
- 每行一个标题，不要编号

文案：
{script}""",
}

DEFAULT_PROMPT = """请为以下口播文案生成 5 个短视频标题。

要求：
- 15-25 字，有吸引力
- 每行一个标题，不要编号

文案：
{script}"""


class TitleGenerator(BaseModule):
    """标题生成模块"""

    name = "title"
    requires_gpu = False

    def __init__(self, config=None, llm_client: LLMClient | None = None):
        super().__init__(config)
        self.llm = llm_client or get_llm_client()

    def run(self, ctx: JobContext) -> ModuleResult:
        """根据文案生成标题"""
        script = ctx.script_text or ctx.input_script
        if not script:
            return ModuleResult(success=False, error="无文案，无法生成标题")

        platform = ctx.metadata.get("platform", "douyin")

        try:
            titles = self.generate(script, platform)
            if not titles:
                return ModuleResult(success=False, error="未生成有效标题")

            ctx.title = titles[0]  # 默认用第一个
            ctx.metadata["title_candidates"] = titles
            ctx.metadata["title_platform"] = platform

            return ModuleResult(
                success=True,
                data={
                    "titles": titles,
                    "selected": titles[0],
                    "platform": platform,
                    "mock": self.llm.is_mock,
                },
            )
        except Exception as e:
            return ModuleResult(success=False, error=str(e))

    def generate(self, script: str, platform: str = "douyin") -> list[str]:
        """生成标题列表"""
        prompt_template = PLATFORM_PROMPTS.get(platform, DEFAULT_PROMPT)
        user_prompt = prompt_template.format(script=script[:500])  # 截断避免超长

        messages = [
            {"role": "system", "content": "你是短视频标题专家，擅长生成高点击率标题。"},
            {"role": "user", "content": user_prompt},
        ]

        self.logger.info(
            f"生成标题 platform={platform} script_len={len(script)} mock={self.llm.is_mock}"
        )
        result = self.llm.chat(messages)
        titles = self._parse_titles(result)
        self.logger.info(f"生成 {len(titles)} 个标题")
        return titles

    def _parse_titles(self, text: str) -> list[str]:
        """解析 LLM 返回的标题（每行一个）"""
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        # 去除可能的编号前缀
        cleaned = []
        for line in lines:
            # 去除 "1." "1、" "1)" 等编号
            line = re.sub(r"^\d+[\.\、\)]\s*", "", line)
            # 去除引号
            line = line.strip("\"'""''「」【】")
            if line and len(line) <= 50:
                cleaned.append(line)
        return cleaned[:5]  # 最多 5 个
