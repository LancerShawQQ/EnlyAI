"""视频合成模块

将口播视频 + 字幕 + BGM + 封面合成为最终成片。

功能：
- 字幕烧录（subtitles 滤镜，自定义样式）
- BGM 混音（amix，人声为主 BGM 为辅）
- 封面首帧（在视频开头插入封面图 1-2 秒）
- 统一输出参数（分辨率/帧率/码率）

输出：最终视频 mp4（H.264 + AAC，兼容主流平台）
"""
from __future__ import annotations

import shlex
import subprocess
import time
from pathlib import Path
from typing import Optional

from PIL import Image

from ..core.base_module import BaseModule, JobContext, ModuleResult
from ..core.ffmpeg_utils import FFmpegRunner


class VideoComposer(BaseModule):
    """视频合成模块"""

    name = "compose"
    requires_gpu = False

    def __init__(self, config=None, ffmpeg: FFmpegRunner | None = None):
        super().__init__(config)
        self.ffmpeg = ffmpeg or FFmpegRunner()
        self.output_fps = self.config.get("composer.output_fps", 30)
        res = self.config.get("composer.output_resolution", [1080, 1920])
        self.output_resolution = tuple(res) if isinstance(res, list) else (1080, 1920)
        self.video_bitrate = self.config.get("composer.video_bitrate", "8M")
        self.audio_bitrate = self.config.get("composer.audio_bitrate", "192k")
        self.bgm_dir = Path(self.config.get("composer.bgm_dir", "./config/bgm"))
        self.bgm_volume = self.config.get("composer.bgm_volume", 0.15)

        # 字幕样式
        sub_cfg = self.config.get("asr.subtitle", {})
        self.subtitle_font_size = sub_cfg.get("font_size", 24)
        self.subtitle_font_color = sub_cfg.get("font_color", "&HFFFFFF")
        self.subtitle_outline_color = sub_cfg.get("outline_color", "&H000000")
        self.subtitle_outline_width = sub_cfg.get("outline_width", 2)

    def setup(self) -> None:
        if not self.ffmpeg.available():
            raise RuntimeError("FFmpeg 不可用，视频合成模块无法工作")
        self.logger.info(
            f"视频合成模块初始化 "
            f"resolution={self.output_resolution} fps={self.output_fps}"
        )
        super().setup()

    def run(self, ctx: JobContext) -> ModuleResult:
        """合成最终视频"""
        if not ctx.raw_video_path or not ctx.raw_video_path.exists():
            return ModuleResult(success=False, error="无口播视频，无法合成")

        output_path = ctx.work_dir / "final_video.mp4"

        try:
            start = time.time()
            final = self.compose(
                video=ctx.raw_video_path,
                subtitle=ctx.subtitle_path,
                bgm=ctx.bgm_path,
                cover=ctx.cover_path,
                output=output_path,
            )
            ctx.final_video = final

            info = self.ffmpeg.probe_video_info(final)
            duration = info.duration if info else 0

            return ModuleResult(
                success=True,
                data={
                    "final_video": str(final),
                    "duration": duration,
                    "size_mb": round(final.stat().st_size / 1024 / 1024, 2),
                    "has_subtitle": ctx.subtitle_path is not None,
                    "has_bgm": ctx.bgm_path is not None,
                    "has_cover": ctx.cover_path is not None,
                },
            )
        except Exception as e:
            return ModuleResult(success=False, error=str(e))

    def compose(
        self,
        video: Path,
        subtitle: Optional[Path] = None,
        bgm: Optional[Path] = None,
        cover: Optional[Path] = None,
        output: Optional[Path] = None,
    ) -> Path:
        """核心合成方法

        Args:
            video: 口播视频
            subtitle: SRT 字幕文件（可选）
            bgm: BGM 音频文件（可选）
            cover: 封面图（可选，作为首帧）
            output: 输出路径
        """
        video = Path(video)
        output = Path(output) if output else video.parent / "final_video.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)

        self.logger.info(
            f"合成视频 video={video.name} "
            f"subtitle={'是' if subtitle else '否'} "
            f"bgm={'是' if bgm else '否'} "
            f"cover={'是' if cover else '否'}"
        )

        # 如果有封面，先合成"封面+视频"
        main_video = video
        if cover and Path(cover).exists():
            main_video = self._prepend_cover(video, Path(cover), output.parent)

        # 构建滤镜链
        vf_filters = self._build_video_filters(subtitle)

        # 构建输入与音频处理
        inputs = ["-i", str(main_video)]
        audio_filter = None
        if bgm and Path(bgm).exists():
            inputs += ["-i", str(bgm)]
            # 人声 + BGM 混音
            audio_filter = (
                f"[0:a]volume=1.0[voice];"
                f"[1:a]volume={self.bgm_volume}[bgm];"
                f"[voice][bgm]amix=inputs=2:duration=first:dropout_transition=0[aout]"
            )

        # 构建命令
        args = list(inputs)

        if audio_filter:
            args += ["-filter_complex", audio_filter]
            if vf_filters:
                # 视频滤镜与音频滤镜共存
                args += ["-vf", vf_filters]
            args += ["-map", "0:v", "-map", "[aout]"]
        else:
            if vf_filters:
                args += ["-vf", vf_filters]

        args += [
            "-c:v", "libx264",
            "-preset", "medium",
            "-b:v", self.video_bitrate,
            "-pix_fmt", "yuv420p",
            "-r", str(self.output_fps),
            "-c:a", "aac",
            "-b:a", self.audio_bitrate,
            "-movflags", "+faststart",
            "-shortest",
            str(output),
        ]

        self.ffmpeg.run(args)
        self.logger.info(f"视频合成完成: {output}")
        return output

    def _build_video_filters(self, subtitle: Optional[Path]) -> str:
        """构建视频滤镜链"""
        filters: list[str] = []
        # 统一分辨率
        w, h = self.output_resolution
        filters.append(
            f"scale={w}:{h}:force_original_aspect_ratio=decrease"
        )
        filters.append(f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2")
        filters.append(f"fps={self.output_fps}")

        # 字幕烧录
        if subtitle and Path(subtitle).exists():
            # 转义路径中的特殊字符（Windows 反斜杠/冒号）
            sub_path = str(Path(subtitle).absolute()).replace("\\", "/").replace(":", r"\:")
            style = (
                f"FontSize={self.subtitle_font_size},"
                f"PrimaryColour={self.subtitle_font_color},"
                f"OutlineColour={self.subtitle_outline_color},"
                f"Outline={self.subtitle_outline_width},"
                f"Alignment=2,"  # 底部居中
                f"MarginV=80"     # 底部边距
            )
            filters.append(f"subtitles='{sub_path}':force_style='{style}'")

        return ",".join(filters)

    def _prepend_cover(
        self, video: Path, cover: Path, work_dir: Path
    ) -> Path:
        """在视频开头插入封面图（1.5 秒）"""
        self.logger.info(f"插入封面首帧: {cover.name}")

        # 将封面图转为 1.5 秒的视频片段
        cover_clip = work_dir / "cover_intro.mp4"
        w, h = self.output_resolution

        # 调整封面尺寸
        resized_cover = work_dir / "cover_resized.jpg"
        img = Image.open(str(cover)).convert("RGB")
        img = img.resize((w, h), Image.LANCZOS)
        img.save(str(resized_cover), "JPEG", quality=95)

        # 生成 1.5 秒封面视频（带静音音频轨，确保 concat 后有音频流）
        args = [
            "-loop", "1",
            "-i", str(resized_cover),
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=mono:sample_rate=44100",
            "-t", "1.5",
            "-vf", f"scale={w}:{h},fps={self.output_fps},format=yuv420p",
            "-c:v", "libx264",
            "-preset", "medium",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(cover_clip),
        ]
        self.ffmpeg.run(args)

        # 拼接封面 + 原视频
        # 先确保原视频参数一致（重新编码为统一参数）
        normalized_video = work_dir / "main_normalized.mp4"
        args = [
            "-i", str(video),
            "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                   f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={self.output_fps},format=yuv420p",
            "-c:v", "libx264",
            "-preset", "medium",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", self.audio_bitrate,
            "-r", str(self.output_fps),
            str(normalized_video),
        ]
        self.ffmpeg.run(args)

        # concat（用 filter 重新编码，避免参数不一致导致 copy 失败）
        combined = work_dir / "with_cover.mp4"
        args = [
            "-i", str(cover_clip),
            "-i", str(normalized_video),
            "-filter_complex",
            f"[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[outv][outa]",
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264",
            "-preset", "medium",
            "-pix_fmt", "yuv420p",
            "-r", str(self.output_fps),
            "-c:a", "aac",
            "-b:a", self.audio_bitrate,
            str(combined),
        ]
        self.ffmpeg.run(args)
        return combined

    def pick_bgm(self, style: str = "default") -> Optional[Path]:
        """从 BGM 库随机选择一首 BGM"""
        import random
        if not self.bgm_dir.exists():
            return None
        bgms = list(self.bgm_dir.glob("*.mp3")) + list(self.bgm_dir.glob("*.m4a"))
        if not bgms:
            return None
        return random.choice(bgms)
