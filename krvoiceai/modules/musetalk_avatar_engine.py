"""MuseTalk 数字人引擎客户端

通过 HTTP API 调用本地 MuseTalk 服务，生成高质量唇形同步视频。
MuseTalk 服务端脚本见 krvoiceai/modules/musetalk_server.py。

架构：
    本地 EnlyAI  ──HTTP──→  本地 MuseTalk 服务（独立 Python 3.10 环境）
                             ├─ MuseTalk 1.5 推理
                             └─ 返回视频文件

优势（对比 Wav2Lip）：
- 256×256 标准化人脸区域单步潜空间 inpainting
- 逐帧重新检测+对齐人脸，解决头部移动时唇形精度下降问题
- v1.5 加 GAN+感知+sync loss，唇形质量明显更好

要求：
- 需 NVIDIA GPU（官方最低 4GB，fp16 模式）
- 需独立 Python 3.10 conda 环境（因依赖 mmcv/mmdet/mmpose）
- 不支持纯 CPU 推理

部署：
1. conda create -n MuseTalk python==3.10
2. git clone https://github.com/TMElyralab/MuseTalk.git
3. 按 MuseTalk README 安装依赖 + 下载模型权重
4. 运行 musetalk_server.py 启动服务
5. 在 EnlyAI 设置中填写服务地址
"""
from __future__ import annotations

import time
from pathlib import Path

import httpx

from ..core.logger import get_logger


class MuseTalkAvatarClient:
    """MuseTalk 本地数字人客户端"""

    def __init__(
        self,
        server_url: str,
        api_key: str = "",
        timeout: int = 600,
        version: str = "v15",
        use_float16: bool = True,
        fps: int = 25,
    ):
        """初始化客户端

        Args:
            server_url: MuseTalk 服务地址，如 http://localhost:8010
            api_key: API 密钥（可选）
            timeout: 请求超时秒数（默认 600s）
            version: 模型版本 v15（推荐）或 v10
            use_float16: 启用 fp16 推理（降低显存，2GB 显存必须启用）
            fps: 输出视频帧率
        """
        self.server_url = server_url.rstrip("/")
        self.api_key = api_key
        self.timeout = timeout
        self.version = version
        self.use_float16 = use_float16
        self.fps = fps
        self.logger = get_logger().bind(component="musetalk_client")

    def health_check(self) -> tuple[bool, str]:
        """检查 MuseTalk 服务连通性

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
                vram_total = data.get("vram_total_mb", 0)
                model_loaded = data.get("model_loaded", False)
                msg = f"连通正常 GPU={gpu_info} 显存={vram_total_mb}MB 模型已加载={model_loaded}"
                return (True, msg)
            return (False, f"HTTP {r.status_code}: {r.text[:200]}")
        except httpx.ConnectError as e:
            return (False, f"无法连接到 {self.server_url}: {e}")
        except Exception as e:
            return (False, f"健康检查异常: {e}")

    def generate(
        self,
        audio_path: Path,
        video_path: Path,
        output_path: Path | None = None,
        bbox_shift: int = 5,
        progress_callback=None,
    ) -> bytes:
        """调用 MuseTalk 生成唇形同步视频

        MuseTalk 是"视频驱动"模式：保留原视频动作，只替换嘴型。
        这与我们 Wav2Lip 的使用方式一致，下游 B-roll/字幕无需适配。

        Args:
            audio_path: 音频文件路径（wav）
            video_path: 原始数字人视频路径（mp4，保留动作只换嘴型）
            output_path: 输出路径（可选，不传则只返回 bytes）
            bbox_shift: 人脸裁剪框偏移（正值下移，5 为默认）
            progress_callback: 进度回调

        Returns:
            视频文件 bytes（mp4）

        Raises:
            RuntimeError: 生成失败
        """
        if not audio_path.exists():
            raise FileNotFoundError(f"音频文件不存在: {audio_path}")
        if not video_path.exists():
            raise FileNotFoundError(f"视频文件不存在: {video_path}")

        self.logger.info(
            f"调用 MuseTalk 生成 audio={audio_path.name} "
            f"video={video_path.name} version={self.version} "
            f"fp16={self.use_float16} fps={self.fps}"
        )

        # 构建 multipart 表单
        files = {
            "audio": (audio_path.name, open(audio_path, "rb"), "audio/wav"),
            "video": (video_path.name, open(video_path, "rb"), "video/mp4"),
        }

        data = {
            "version": self.version,
            "use_float16": str(self.use_float16).lower(),
            "fps": str(self.fps),
            "bbox_shift": str(bbox_shift),
        }

        try:
            start = time.time()
            headers = self._headers()
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
                            f"MuseTalk 生成失败 HTTP {resp.status_code}: {body[:500]}"
                        )

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
                f"MuseTalk 生成完成 size={len(video_bytes)} bytes 耗时={elapsed:.1f}s"
            )

            # 可选写入文件
            if output_path:
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(video_bytes)

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
