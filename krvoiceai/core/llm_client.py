"""LLM 客户端

统一封装 DeepSeek / Qwen / OpenAI 等 OpenAI 兼容 API。
无 API key 时自动降级为 mock 模式，保证流程可跑通。
"""
from __future__ import annotations

import json
import time
from typing import Any

import httpx

from .config import get_config
from .logger import get_logger


class LLMClient:
    """OpenAI 兼容 LLM 客户端"""

    def __init__(self, provider: str | None = None):
        cfg = get_config()
        self.provider = provider or cfg.get("llm.provider", "mock")
        self.api_key = cfg.get("llm.api_key", "") or ""
        self.base_url = cfg.get("llm.base_url", "")
        self.model = cfg.get("llm.model", "")
        self.temperature = cfg.get("llm.temperature", 0.7)
        self.max_tokens = cfg.get("llm.max_tokens", 2000)
        self.timeout = cfg.get("llm.timeout", 60)
        self.logger = get_logger().bind(component="llm_client")

    @property
    def is_mock(self) -> bool:
        return self.provider == "mock" or not self.api_key

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """调用 chat completion，返回助手消息文本"""
        if self.is_mock:
            return self._mock_response(messages)

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature if temperature is not None else self.temperature,
            "max_tokens": max_tokens or self.max_tokens,
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        start = time.time()
        try:
            r = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"]
            self.logger.debug(
                f"LLM 调用成功 provider={self.provider} "
                f"model={self.model} 耗时={time.time()-start:.2f}s "
                f"tokens={data.get('usage', {})}"
            )
            return content.strip()
        except httpx.HTTPStatusError as e:
            self.logger.error(f"LLM HTTP 错误: {e.response.status_code} {e}")
            raise
        except Exception as e:
            self.logger.error(f"LLM 调用异常: {e}")
            raise

    def _mock_response(self, messages: list[dict[str, str]]) -> str:
        """Mock 模式：根据 system/user 提示返回模板化内容"""
        self.logger.info("LLM mock 模式：返回模板化内容")
        user_msg = ""
        for m in messages:
            if m["role"] == "user":
                user_msg = m["content"]
                break

        # 简单的模板化处理：保留输入要点，套用口播结构
        if not user_msg:
            return "大家好，今天和大家分享一个重要的话题。希望对您有帮助，记得点赞关注。"

        # 提取输入前 50 字作为主题
        topic = user_msg[:50].replace("\n", " ").strip()
        return (
            f"大家好，今天和大家聊聊{topic}。\n\n"
            f"这个话题其实很多人都在关注，但真正搞明白的人不多。"
            f"接下来我用最简单的方式给你讲清楚。\n\n"
            f"首先，核心要点就一句话：抓住本质，化繁为简。\n"
            f"其次，实操层面有三个关键步骤，循序渐进就能上手。\n"
            f"最后，避坑指南也很重要，少走弯路才能事半功倍。\n\n"
            f"如果你觉得有用，点赞收藏关注三连，我们下期见。"
        )


# 全局单例
_client: LLMClient | None = None


def get_llm_client() -> LLMClient:
    global _client
    if _client is None:
        _client = LLMClient()
    return _client
