"""LongCat-Video-Avatar 数字人引擎客户端

通过 HTTP API 调用云端 LongCat 服务，生成高质量唇形同步视频。
云端服务端脚本见 krvoiceai/modules/longcat_server.py。

架构：
    本地 EnlyAI  ──HTTP──→  云端 GPU 服务器（longcat_server.py）
                            ├─ LongCat-Video-Avatar 1.5 推理
                            └─ 返回视频文件

优势（对比 Wav2Lip）：
- Whisper-large-v3 音频编码器，唇形同步更精准
- 全身时序稳定，头部移动时不再丢同步
- DMD 蒸馏 8 步生成，效率提升 15 倍

要求：
- 云端需 8GB+ 显存 GPU（配合 INT8 量化）
- 本地仅需网络连接
"""
from __future__ import annotations

import time
from pathlib import Path

import httpx

from ..core.logger import get_logger


class LongCatAvatarClient:
    """LongCat 云端数字人客户端"""

    def __init__(
        self,
        server_url: str,
        api_key: str = "",
        timeout: int = 600,
        model_type: str = "avatar-v1.5",
        resolution: str = "480p",
    ):
        """初始化客户端

        Args:
            server_url: 云端服务地址，如 http://xxx.xxx.xxx.xxx:8000
            api_key: API 密钥（可选，服务端配置后启用）
            timeout: 请求超时秒数（默认 600s，LongCat 生成长视频可能较慢）
            model_type: 模型版本 avatar-v1.5（默认）或 avatar-v1.0
            resolution: 分辨率 480p 或 720p
        """
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.model_type = model_type
        self.resolution = resolution
        self.logger = get_logger().bind(component="longcat_client")

    def health_check(self) -> tuple[bool, str]:
        """检查云端服务连通性

        Returns:
            (ok, message)
        """
        try:
            headers = self._headers()
            r = httpx.get(
                f"{self.server_url}/api/health",
                headers=headers,
                timeout=15,
            )
            if r.status_code == 200:
                data = r.json()
                gpu_info = data.get("gpu", "unknown")
                model_loaded = data.get("model_loaded", False)
                msg = f"连通正常 GPU={gpu_info} 模型已加载={model_loaded}"
                return (True, msg)
            return (False, f"HTTP {r.status_code}: {r.text[:200]}")
        except httpx.ConnectError as e:
            return (False, f"无法连接到 {self.server_url}: {e}")
        except Exception as e:
            return (False, f"健康检查异常: {e}")

    def generate(
        self,
        audio_path: Path,
        reference_image: Path | None = None,
        prompt: str = "",
        num_segments: int = 5,
        progress_callback=None,
    ) -> bytes:
        """调用云端 LongCat 生成视频

        Args:
            audio_path: 音频文件路径（wav）
            reference_image: 参考人物图片（jpg/png），可选
            prompt: 描述性提示词（如"A young woman speaking"），越详细效果越好
            num_segments: 视频续写段数（每段约 10s），默认 5
            progress_callback: 进度回调函数 (progress: float) -> None

        Returns:
            视频文件 bytes（mp4）

        Raises:
            RuntimeError: 生成失败
        """
        if not audio_path.exists():
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")

        self.logger.info(
            f"调用 LongCat 云端生成 audio={audio_path.name} "
            f"ref_img={reference_image.name if reference_image else 'none'} "
            f"resolution={self.resolution} model={self.model_type}"
        )

        # 构建 multipart 表单
        files = {"audio": (audio_path.name, open(audio_path, "rb"), "audio/wav")}
        if reference_image and reference_image.exists():
            files["reference_image"] = (
                reference_image.name,
                open(reference_image, "rb"),
                "image/jpeg",
            )

        data = {
            "model_type": self.model_type,
            "resolution": self.resolution,
            "prompt": prompt or "A person is speaking naturally with natural expressions",
            "num_segments": str(num_segments),
            "use_distill": "true",
            "use_int8": "true",
        }

        try:
            start = time.time()
            headers = self._headers()
            # 移除 Content-Type，让 httpx 自动设置 multipart boundary
            headers.pop("Content-Type", None)

            with httpx.Client(timeout=self.timeout) as client:
                with client.stream(
                    "POST",
                    f"{self.server_url}/api/avatar/generate",
                    files=files,
                    data=data,
                    headers=headers,
                ) as resp:
                    if resp.status_code != 200:
                        body = resp.read().decode(errors="replace")
                        raise RuntimeError(
                            f"LongCat 生成失败 HTTP {resp.status_code}: {body[:500]}"
                        )

                    # 流式读取视频内容
                    chunks = []
                    total = 0
                    for chunk in resp.iter_bytes(chunk_size=65536):
                        chunks.append(chunk)
                        total += len(chunk)
                        if progress_callback:
                            progress_callback(total)

                    video_bytes = b"".join(chunks)

            elapsed = time.time() - start
            self.logger.info(
                f"LongCat 生成完成 size={len(video_bytes)} bytes 耗时={elapsed:.1f}s"
            )
            return video_bytes

        finally:
            for _, fobj, _ in files.values():
                fobj.close()

    def _headers(self) -> dict[str, str]:
        """构建请求头"""
        headers = {"Accept": "video/mp4"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers
