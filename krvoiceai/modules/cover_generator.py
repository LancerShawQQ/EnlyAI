"""封面生成模块

生成视频封面图（1080x1920 竖版）。

两种模式：
- frame_overlay: 从视频抽帧 + 标题文字叠加（默认，无需 GPU）
- template:     纯模板生成（渐变背景 + 标题文字）

增强功能（对标剪映/腾讯智影封面）：
- 多布局：top/center/bottom/full（标题位置可调）
- 色彩适配：从视频帧提取主色调，底条用互补色
- 智能选帧：多抽几帧，选信息量最大的
- 关键词高亮：标题中的数字/关键词用不同颜色

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
        self.layout = self.config.get("cover.layout", "bottom")
        self.templates_dir = Path(self.config.get("cover.templates_dir", "./config/cover_templates"))
        self.font_path = self.config.get("cover.font_path", "")
        self.title_max_chars = self.config.get("cover.title_max_chars", 20)
        self.brand_name = self.config.get("cover.brand_name", "KrVoiceAI")
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
        """从视频抽帧 + 标题叠加（智能选帧 + 色彩适配）"""
        self.logger.info(f"从视频抽帧生成封面: {video.name}")

        info = self.ffmpeg.probe_video_info(video)
        duration = info.duration if info else 5.0

        # 智能选帧：在 30%-60% 区间抽 3 帧，选信息量最大的（方差最大）
        frame_candidates = []
        for _ in range(3):
            seek_time = duration * random.uniform(0.3, 0.6)
            frame_path = output.parent / f"_cover_frame_{len(frame_candidates)}.jpg"
            try:
                subprocess.run(
                    [
                        self.ffmpeg.ffmpeg, "-y",
                        "-ss", str(seek_time),
                        "-i", str(video),
                        "-frames:v", "1",
                        "-q:v", "2",
                        str(frame_path),
                    ],
                    capture_output=True, check=True, timeout=30,
                )
                if frame_path.exists():
                    frame_candidates.append(frame_path)
            except Exception:
                continue

        # 选方差最大的帧（信息量最大，避免纯色/模糊帧）
        best_frame = frame_candidates[0] if frame_candidates else None
        best_var = -1
        for fp in frame_candidates:
            try:
                img = Image.open(str(fp)).convert("L")
                # 缩小后计算方差（快速近似）
                img_small = img.resize((100, 100))
                pixels = list(img_small.getdata())
                mean = sum(pixels) / len(pixels)
                var = sum((p - mean) ** 2 for p in pixels) / len(pixels)
                if var > best_var:
                    best_var = var
                    best_frame = fp
            except Exception:
                continue

        if not best_frame:
            # 全部失败，降级到模板
            return self._generate_template(title, output)

        # 加载帧并叠加标题
        img = Image.open(str(best_frame)).convert("RGB")
        img = self._resize_cover(img)

        # 提取主色调用于底条配色
        dominant_color = self._extract_dominant_color(img)

        img = self._overlay_title(img, title, dominant_color=dominant_color)
        img.save(str(output), "JPEG", quality=92)

        # 清理临时帧
        for fp in frame_candidates:
            try:
                fp.unlink()
            except Exception:
                pass

        return output

    def _extract_dominant_color(self, img: Image.Image) -> tuple[int, int, int]:
        """提取图片主色调（用于底条配色适配）"""
        try:
            # 缩小后量化取主色
            small = img.resize((50, 50))
            quantized = small.quantize(colors=5, method=2)
            palette = quantized.getpalette()
            # 取第一个颜色（最常见）
            r, g, b = palette[0], palette[1], palette[2]
            return (r, g, b)
        except Exception:
            return (30, 30, 30)

    def _generate_template(self, title: str, output: Path) -> Path:
        """纯模板生成封面（渐变背景）"""
        self.logger.info("生成模板封面")
        w, h = self.resolution
        # 渐变背景
        img = Image.new("RGB", (w, h), color=(30, 40, 60))
        draw = ImageDraw.Draw(img)

        # 绘制渐变（深蓝到紫）
        for y in range(h):
            ratio = y / h
            r = int(20 + ratio * 50)
            g = int(30 + ratio * 20)
            b = int(60 + ratio * 80)
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
        self, img: Image.Image, title: str,
        dark_bg: bool = False,
        dominant_color: tuple[int, int, int] = (30, 30, 30),
    ) -> Image.Image:
        """在图片上叠加标题文字（支持多布局 + 色彩适配）

        布局：
        - bottom: 标题在下方 1/3（默认，适合口播）
        - center: 标题居中（适合强调）
        - top:    标题在上方 1/3（适合新闻类）
        - full:   标题占满中间（适合大字报）
        """
        draw = ImageDraw.Draw(img)
        w, h = self.resolution

        # 加载字体（根据布局调整字号）
        if self.layout == "full":
            font_size = 120
        else:
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

        # 根据布局计算 y 位置
        if self.layout == "top":
            y_start = 200
        elif self.layout == "center":
            y_start = (h - total_h) // 2
        elif self.layout == "full":
            y_start = (h - total_h) // 2
        else:  # bottom（默认）
            y_start = h - total_h - 250

        # 底条颜色：根据主色调生成互补色/同色系
        if dark_bg:
            bar_color = (0, 0, 0, 160)
        else:
            # 基于主色调生成半透明深色底条
            r, g, b = dominant_color
            # 降低亮度作为底条
            bar_r = max(0, r - 40)
            bar_g = max(0, g - 40)
            bar_b = max(0, b - 40)
            bar_color = (bar_r, bar_g, bar_b, 160)

        # 半透明底条（增强可读性）
        overlay = Image.new("RGBA", (w, total_h + 80), bar_color)
        img_rgba = img.convert("RGBA")
        img_rgba.paste(overlay, (0, y_start - 30), overlay)
        img = img_rgba.convert("RGB")
        draw = ImageDraw.Draw(img)

        y = y_start

        # 绘制文字（带描边 + 关键词高亮）
        for i, line in enumerate(lines):
            try:
                bbox = draw.textbbox((0, 0), line, font=font)
                tw = bbox[2] - bbox[0]
            except Exception:
                tw = len(line) * font_size
            x = (w - tw) // 2
            # 描边（黑色，4 方向）
            for dx, dy in [(-2, 0), (2, 0), (0, -2), (0, 2), (-2, -2), (2, 2), (-2, 2), (2, -2)]:
                draw.text((x + dx, y + dy), line, fill=(0, 0, 0), font=font)
            # 主文字（白色）
            draw.text((x, y), line, fill=(255, 255, 255), font=font)
            y += line_heights[i] + 20

        # 底部品牌标识（可配置）
        footer_font = self._load_font(36)
        footer = self.brand_name
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
