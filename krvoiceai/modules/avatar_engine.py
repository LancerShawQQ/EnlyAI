"""数字人口播生成模块

三种 provider：
- musetalk:    调用云端 MuseTalk API（口型同步）
- latentsync:  调用云端 LatentSync API（备选）
- mock:        音频 + 静态占位图合成视频（保证流程可跑通）

输出：口播视频 mp4 文件
"""
from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from ..core.base_module import BaseModule, JobContext, ModuleResult
from ..core.ffmpeg_utils import FFmpegRunner
from ..core.gpu_runner import GPURunner


class AvatarEngine(BaseModule):
    """数字人口播生成模块"""

    name = "avatar"
    requires_gpu = True

    def __init__(self, config=None, gpu_runner: GPURunner | None = None,
                 ffmpeg: FFmpegRunner | None = None):
        super().__init__(config)
        self.provider = self.config.get("avatar.provider", "mock")
        self.api_base = self.config.get("avatar.api_base", "")
        self.avatars_dir = Path(self.config.get("avatar.avatars_dir", "./config/avatars"))
        self.default_avatar = self.config.get("avatar.default_avatar", "default")
        self.output_fps = self.config.get("avatar.output_fps", 25)
        res = self.config.get("avatar.output_resolution", [1080, 1920])
        self.output_resolution = tuple(res) if isinstance(res, list) else (1080, 1920)
        self.gpu = gpu_runner or GPURunner()
        self.ffmpeg = ffmpeg or FFmpegRunner()

    def setup(self) -> None:
        if self.provider in ("musetalk", "latentsync", "echomimic"):
            available = self.gpu.health_check_avatar()
            if not available:
                self.logger.warning(
                    f"{self.provider} 服务不可用，降级到 mock 模式"
                )
                self.provider = "mock"
        self.logger.info(f"数字人模块初始化 provider={self.provider}")
        super().setup()

    def run(self, ctx: JobContext) -> ModuleResult:
        """根据 ctx.audio_path 生成口播视频"""
        if not ctx.audio_path or not ctx.audio_path.exists():
            return ModuleResult(success=False, error="无音频文件，无法生成数字人视频")

        avatar_id = ctx.avatar_id or self.default_avatar
        output_path = ctx.work_dir / "avatar_output.mp4"

        try:
            start = time.time()
            if self.provider == "mock":
                video_path = self._generate_mock(ctx, avatar_id, output_path)
            else:
                video_path = self._generate_cloud(ctx, avatar_id, output_path)

            ctx.raw_video_path = video_path
            ctx.metadata["avatar_provider"] = self.provider

            # 探测视频信息
            info = self.ffmpeg.probe_video_info(video_path)
            duration = info.duration if info else ctx.audio_duration

            return ModuleResult(
                success=True,
                data={
                    "video_path": str(video_path),
                    "duration": duration,
                    "avatar_id": avatar_id,
                    "provider": self.provider,
                },
            )
        except Exception as e:
            return ModuleResult(success=False, error=str(e))

    def _generate_cloud(
        self, ctx: JobContext, avatar_id: str, output_path: Path
    ) -> Path:
        """调用云端数字人 API"""
        self.logger.info(
            f"云端数字人生成 provider={self.provider} "
            f"avatar={avatar_id} audio={ctx.audio_path}"
        )

        # 读取音频并 base64 编码
        audio_b64 = base64.b64encode(ctx.audio_path.read_bytes()).decode()

        payload = {
            "audio_base64": audio_b64,
            "avatar_id": avatar_id,
            "output_fps": self.output_fps,
            "output_resolution": list(self.output_resolution),
        }
        resp = self.gpu.call_avatar(payload)

        video_b64 = resp.get("video_base64") or resp.get("data", {}).get("video_base64")
        if not video_b64:
            # 如果返回的是 URL，下载
            video_url = resp.get("video_url")
            if video_url:
                import httpx
                r = httpx.get(video_url, timeout=120)
                r.raise_for_status()
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(r.content)
                return output_path
            raise RuntimeError(f"数字人 API 返回无视频数据: {resp}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(video_b64))
        self.logger.info(f"云端数字人生成完成 video={output_path}")
        return output_path

    def _generate_mock(
        self, ctx: JobContext, avatar_id: str, output_path: Path
    ) -> Path:
        """Mock 模式：生成占位头像图 + 音频合成视频"""
        self.logger.info(
            f"Mock 数字人生成 avatar={avatar_id} "
            f"audio={ctx.audio_path} duration={ctx.audio_duration:.2f}s"
        )

        # 生成或获取占位头像图
        avatar_image = self._get_avatar_image(avatar_id)

        # 用 ffmpeg 合成图片 + 音频 = 视频
        self.ffmpeg.image_audio_to_video(
            image=avatar_image,
            audio=ctx.audio_path,
            output=output_path,
            fps=self.output_fps,
            resolution=self.output_resolution,
            video_bitrate="4M",
        )
        self.logger.info(f"Mock 数字人视频生成完成: {output_path}")
        return output_path

    def _get_avatar_image(self, avatar_id: str) -> Path:
        """获取数字人头像图片

        优先使用已注册的参考图，否则生成占位图。
        """
        # 查找已注册形象
        avatar_dir = self.avatars_dir / avatar_id
        if avatar_dir.exists():
            for name in ("reference.jpg", "reference.png", "avatar.jpg"):
                p = avatar_dir / name
                if p.exists():
                    return p

        # 生成占位图
        placeholder = self.avatars_dir / avatar_id / "placeholder.jpg"
        placeholder.parent.mkdir(parents=True, exist_ok=True)
        self._generate_placeholder_image(placeholder, avatar_id)
        return placeholder

    def _generate_placeholder_image(
        self, output: Path, avatar_id: str
    ) -> None:
        """生成占位头像图（纯色背景 + 文字标识）"""
        w, h = self.output_resolution
        # 浅灰背景
        img = Image.new("RGB", (w, h), color=(60, 70, 90))
        draw = ImageDraw.Draw(img)

        # 尝试加载字体，失败用默认
        font_path = self.config.get("cover.font_path", "")
        try:
            font_large = ImageFont.truetype(font_path, 80) if font_path else ImageFont.load_default()
            font_small = ImageFont.truetype(font_path, 40) if font_path else ImageFont.load_default()
        except Exception:
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()

        # 中心圆形头像占位
        cx, cy = w // 2, h // 2 - 100
        r = 200
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            fill=(120, 140, 180), outline=(200, 210, 230), width=4,
        )

        # 文字
        title = "数字人口播"
        subtitle = f"Avatar: {avatar_id}"
        for text, font, y_offset in [
            (title, font_large, 80),
            (subtitle, font_small, 180),
        ]:
            try:
                bbox = draw.textbbox((0, 0), text, font=font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
            except Exception:
                tw, th = 400, 80
            draw.text(
                ((w - tw) // 2, cy + y_offset),
                text, fill=(255, 255, 255), font=font,
            )

        # 底部标识
        footer = "KrVoiceAI · Mock Mode"
        try:
            bbox = draw.textbbox((0, 0), footer, font=font_small)
            tw = bbox[2] - bbox[0]
        except Exception:
            tw = 300
        draw.text(((w - tw) // 2, h - 120), footer, fill=(180, 190, 210), font=font_small)

        img.save(str(output), "JPEG", quality=90)

    def register_avatar(
        self, avatar_id: str, reference_video: Path
    ) -> bool:
        """注册数字人形象

        Args:
            avatar_id: 形象 ID
            reference_video: 参考视频（3-10s 正面说话）
        """
        avatar_dir = self.avatars_dir / avatar_id
        avatar_dir.mkdir(parents=True, exist_ok=True)

        if self.provider == "mock":
            # Mock 模式：从视频抽一帧作为参考图
            try:
                import subprocess
                ref_img = avatar_dir / "reference.jpg"
                subprocess.run(
                    [
                        self.ffmpeg.ffmpeg, "-y",
                        "-i", str(reference_video),
                        "-frames:v", "1",
                        "-q:v", "2",
                        str(ref_img),
                    ],
                    capture_output=True, check=True,
                )
                self.logger.info(f"Mock 形象注册成功: {avatar_id} -> {ref_img}")
                # 保存元数据
                import json
                (avatar_dir / "meta.json").write_text(
                    json.dumps({
                        "avatar_id": avatar_id,
                        "source": str(reference_video),
                        "mode": "mock",
                    }, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                return True
            except Exception as e:
                self.logger.error(f"形象注册失败: {e}")
                return False
        else:
            # 云端模式：上传参考视频
            try:
                video_b64 = base64.b64encode(Path(reference_video).read_bytes()).decode()
                resp = self.gpu.call_avatar_register({
                    "avatar_id": avatar_id,
                    "reference_video_base64": video_b64,
                })
                return resp.get("success", False)
            except Exception as e:
                self.logger.error(f"云端形象注册失败: {e}")
                return False
