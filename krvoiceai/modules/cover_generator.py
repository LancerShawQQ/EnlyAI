"""封面生成模块

生成视频封面图（1080x1920 竖版）。

两种模式：
- frame_overlay: 从视频抽帧 + 标题文字叠加（默认，无需 GPU）
- template:     纯模板生成（纯色背景 + 标题文字）

输出：JPEG 封面图
"""
from __future__ import annotations

import random
import subprocess
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..core.base_module import BaseModule, JobContext, ModuleResult
from ..core.ffmpeg_utils import FFmpegRunner


class CoverGenerator(BaseModule):
    """封面生成模块"""

    name = "cover"
    requires_gpu = False

    def __init__(self, config=None, ffmpeg: FFmpegRunner | None = None):
        super().__init__(config)
        self.mode = self.config.get("cover.mode", "frame_overlay")
        self.templates_dir = Path(self.config.get("cover.templates_dir", "./config/cover_templates"))
        self.font_path = self.config.get("cover.font_path", "")
        self.title_max_chars = self.config.get("cover.title_max_chars", 20)
        res = self.config.get("avatar.output_resolution", [1080, 1920])
        self.resolution = tuple(res) if isinstance(res, list) else (1080, 1920)
        self.ffmpeg = ffmpeg or FFmpegRunner()

    def run(self, ctx: JobContext) -> ModuleResult:
        """生成封面"""
        title = ctx.title or ctx.metadata.get("title_candidates", ["口播视频"])[0]
        if not title:
            title = "口播视频"

        output_path = ctx.work_dir / "cover.jpg"

        try:
            if self.mode == "frame_overlay" and ctx.raw_video_path and ctx.raw_video_path.exists():
                cover = self._generate_from_frame(ctx.raw_video_path, title, output_path)
            else:
                cover = self._generate_template(title, output_path)

            ctx.cover_path = cover
            return ModuleResult(
                success=True,
                data={
                    "cover_path": str(cover),
                    "title": title,
                    "mode": self.mode,
                },
            )
        except Exception as e:
            return ModuleResult(success=False, error=str(e))

    def generate(self, video_path: Path | None, title: str,
                 output: Path) -> Path:
        """直接调用接口"""
        if video_path and Path(video_path).exists() and self.mode == "frame_overlay":
            return self._generate_from_frame(Path(video_path), title, output)
        return self._generate_template(title, output)

    def _generate_from_frame(
        self, video: Path, title: str, output: Path
    ) -> Path:
        """从视频抽帧 + 标题叠加"""
        self.logger.info(f"从视频抽帧生成封面: {video.name}")

        # 抽取视频中段的一帧（表情通常较自然）
        info = self.ffmpeg.probe_video_info(video)
        duration = info.duration if info else 5.0
        # 取 30%-60% 之间的随机位置
        seek_time = duration * random.uniform(0.3, 0.6)

        frame_path = output.parent / "cover_frame.jpg"
        subprocess.run(
            [
                self.ffmpeg.ffmpeg, "-y",
                "-ss", str(seek_time),
                "-i", str(video),
                "-frames:v", "1",
                "-q:v", "2",
                str(frame_path),
            ],
            capture_output=True, check=True,
        )

        # 加载帧并叠加标题
        img = Image.open(str(frame_path)).convert("RGB")
        img = self._resize_cover(img)
        img = self._overlay_title(img, title)
        img.save(str(output), "JPEG", quality=92)
        return output

    def _generate_template(self, title: str, output: Path) -> Path:
        """纯模板生成封面"""
        self.logger.info("生成模板封面")
        w, h = self.resolution
        # 渐变背景
        img = Image.new("RGB", (w, h), color=(30, 40, 60))
        draw = ImageDraw.Draw(img)

        # 绘制简单渐变
        for y in range(h):
            ratio = y / h
            r = int(30 + ratio * 40)
            g = int(40 + ratio * 30)
            b = int(60 + ratio * 60)
            draw.line([(0, y), (w, y)], fill=(r, g, b))

        img = self._overlay_title(img, title, dark_bg=True)
        img.save(str(output), "JPEG", quality=92)
        return output

    def _resize_cover(self, img: Image.Image) -> Image.Image:
        """调整到目标尺寸（cover 模式：填满）"""
        w, h = self.resolution
        src_w, src_h = img.size
        src_ratio = src_w / src_h
        dst_ratio = w / h
        if src_ratio > dst_ratio:
            # 宽了，按高裁
            new_w = int(src_h * dst_ratio)
            left = (src_w - new_w) // 2
            img = img.crop((left, 0, left + new_w, src_h))
        else:
            new_h = int(src_w / dst_ratio)
            top = (src_h - new_h) // 2
            img = img.crop((0, top, src_w, top + new_h))
        return img.resize((w, h), Image.LANCZOS)

    def _overlay_title(
        self, img: Image.Image, title: str, dark_bg: bool = False
    ) -> Image.Image:
        """在图片上叠加标题文字"""
        draw = ImageDraw.Draw(img)
        w, h = self.resolution

        # 加载字体
        font_size = 90
        font = self._load_font(font_size)

        # 标题过长则换行
        title = title[:self.title_max_chars]
        lines = self._wrap_text(title, font, w - 120)

        # 计算文字总高度
        line_heights = []
        for line in lines:
            try:
                bbox = draw.textbbox((0, 0), line, font=font)
                line_heights.append(bbox[3] - bbox[1])
            except Exception:
                line_heights.append(font_size)
        total_h = sum(line_heights) + 20 * (len(lines) - 1)

        # 文字位置：下方 1/3 处
        y = h - total_h - 250

        # 半透明底条（增强可读性）—— 用 paste 方式，避免尺寸不匹配
        overlay = Image.new("RGBA", (w, total_h + 80), (0, 0, 0, 140))
        img_rgba = img.convert("RGBA")
        # 把底条 paste 到对应位置
        img_rgba.paste(overlay, (0, h - total_h - 270), overlay)
        img = img_rgba.convert("RGB")
        draw = ImageDraw.Draw(img)

        # 重新计算 y
        y = h - total_h - 230

        # 绘制文字（带描边）
        for i, line in enumerate(lines):
            try:
                bbox = draw.textbbox((0, 0), line, font=font)
                tw = bbox[2] - bbox[0]
            except Exception:
                tw = len(line) * font_size
            x = (w - tw) // 2
            # 描边
            for dx, dy in [(-2, 0), (2, 0), (0, -2), (0, 2)]:
                draw.text((x + dx, y + dy), line, fill=(0, 0, 0), font=font)
            # 主文字
            draw.text((x, y), line, fill=(255, 255, 255), font=font)
            y += line_heights[i] + 20

        # 底部品牌标识
        footer_font = self._load_font(36)
        footer = "KrVoiceAI"
        try:
            bbox = draw.textbbox((0, 0), footer, font=footer_font)
            fw = bbox[2] - bbox[0]
        except Exception:
            fw = 200
        draw.text(
            ((w - fw) // 2, h - 80), footer,
            fill=(200, 210, 230), font=footer_font,
        )

        return img

    def _wrap_text(self, text: str, font, max_width: int) -> list[str]:
        """文字换行"""
        draw = ImageDraw.Draw(Image.new("RGB", (10, 10)))
        lines = []
        current = ""
        for ch in text:
            test = current + ch
            try:
                bbox = draw.textbbox((0, 0), test, font=font)
                tw = bbox[2] - bbox[0]
            except Exception:
                tw = len(test) * 50
            if tw > max_width and current:
                lines.append(current)
                current = ch
            else:
                current = test
        if current:
            lines.append(current)
        return lines if lines else [text]

    def _load_font(self, size: int) -> ImageFont.ImageFont:
        """加载字体"""
        if self.font_path and Path(self.font_path).exists():
            try:
                return ImageFont.truetype(self.font_path, size)
            except Exception:
                pass
        # 尝试系统字体
        for candidate in [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
        ]:
            if Path(candidate).exists():
                try:
                    return ImageFont.truetype(candidate, size)
                except Exception:
                    continue
        return ImageFont.load_default()
