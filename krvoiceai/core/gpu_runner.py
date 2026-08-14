"""GPU 任务调度器

负责与云端 GPU 服务通信，调度 TTS 和数字人生成任务。
本地无 GPU 时，通过此模块调用云端 API。
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from .config import get_config
from .logger import get_logger


class GPURunner:
    """云端 GPU 服务客户端"""

    def __init__(self):
        self.config = get_config()
        self.logger = get_logger().bind(component="gpu_runner")
        self.tts_endpoint = self.config.get("gpu_runner.tts_endpoint")
        self.avatar_endpoint = self.config.get("gpu_runner.avatar_endpoint")
        self.health_timeout = self.config.get("gpu_runner.health_check_timeout", 10)

    def health_check_tts(self) -> bool:
        """检查 TTS 服务健康"""
        return self._health_check(self.tts_endpoint)

    def health_check_avatar(self) -> bool:
        """检查数字人服务健康"""
        return self._health_check(self.avatar_endpoint)

    def _health_check(self, endpoint: str) -> bool:
        if not endpoint:
            return False
        try:
            r = httpx.get(
                f"{endpoint}/health",
                timeout=self.health_timeout,
            )
            return r.status_code == 200
        except Exception as e:
            self.logger.debug(f"健康检查失败 {endpoint}: {e}")
            return False

    def is_gpu_available(self) -> bool:
        """GPU 是否可用（任一服务在线即可）"""
        return self.health_check_tts() or self.health_check_avatar()

    def call_tts(self, payload: dict[str, Any], timeout: float = 120) -> dict:
        """调用 TTS 服务"""
        return self._post(f"{self.tts_endpoint}/api/tts/synthesize", payload, timeout)

    def call_tts_register(self, payload: dict[str, Any], timeout: float = 300) -> dict:
        """注册音色"""
        return self._post(
            f"{self.tts_endpoint}/api/tts/register_voice", payload, timeout
        )

    def call_avatar(self, payload: dict[str, Any], timeout: float = 300) -> dict:
        """调用数字人生成"""
        return self._post(
            f"{self.avatar_endpoint}/api/avatar/generate", payload, timeout
        )

    def call_avatar_register(
        self, payload: dict[str, Any], timeout: float = 600
    ) -> dict:
        """注册数字人形象"""
        return self._post(
            f"{self.avatar_endpoint}/api/avatar/register", payload, timeout
        )

    def _post(self, url: str, payload: dict, timeout: float) -> dict:
        self.logger.debug(f"POST {url} payload={list(payload.keys())}")
        start = time.time()
        r = httpx.post(url, json=payload, timeout=timeout)
        r.raise_for_status()
        data = r.json()
        self.logger.debug(f"GPU 调用完成, 耗时 {time.time()-start:.2f}s")
        return data
