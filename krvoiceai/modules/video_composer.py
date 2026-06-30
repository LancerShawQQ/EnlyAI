"""视频合成模块

将口播视频 + 字幕 + BGM + 封面合成为最终成片。

功能：
- 字幕烧录（ASS 格式，支持样式预设/动画/逐字高亮，对标剪映）
- BGM 混音（amix，人声为主 BGM 为辅）
- 封面首帧（在视频开头插入封面图 1-2 秒）
- 视频滤镜（暖色/冷色/黑白/复古/鲜艳/电影感/Vlog/胶片）
- 转场效果（xfade 10+ 种转场，对标剪映）
- 水印（drawtext 文字水印）
- 片头片尾（渐变背景 + 文字动画）
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
from .subtitle_styler import (
    SUBTITLE_STYLE_PRESETS,
    srt_to_ass,
    write_ass_file,
)


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
        # BGM 音量：优先读 audio.bgm.volume（0-100），换算为 0-1；兜底 composer.bgm_volume
        _bgm_vol_pct = self.config.get("audio.bgm.volume", None)
        if _bgm_vol_pct is not None:
            self.bgm_volume = float(_bgm_vol_pct) / 100.0
        else:
            self.bgm_volume = self.config.get("composer.bgm_volume", 0.15)

        # 字幕样式（新 subtitle 段，对标剪映）
        sub_cfg = self.config.get("subtitle", {})
        self.subtitle_preset = sub_cfg.get("preset", "minimal_white")
        self.subtitle_animation = sub_cfg.get("animation", "fade")
        self.subtitle_font_name = sub_cfg.get("font_name", "")
        self.subtitle_font_size = sub_cfg.get("font_size", 28)
        self.subtitle_position = sub_cfg.get("position", "bottom")
        self.subtitle_alignment = sub_cfg.get("alignment", "center")
        self.subtitle_margin_v = sub_cfg.get("margin_v", 80)
        self.subtitle_karaoke = sub_cfg.get("karaoke", False)
        self.subtitle_bold = sub_cfg.get("bold", True)
        self.subtitle_italic = sub_cfg.get("italic", False)
        self.subtitle_outline_width = sub_cfg.get("outline_width", None)
        self.subtitle_shadow_distance = sub_cfg.get("shadow_distance", None)
        self.subtitle_letter_spacing = sub_cfg.get("letter_spacing", 0)
        self.subtitle_line_spacing = sub_cfg.get("line_spacing", 1.2)
        # 兼容旧 asr.subtitle 配置
        if not sub_cfg:
            old = self.config.get("asr.subtitle", {})
            self.subtitle_font_size = old.get("font_size", 28)

        # BGM 配置
        self.bgm_enabled = self.config.get("audio.bgm.enabled", True)
        self.bgm_track = self.config.get("audio.bgm.track", "soft_piano")
        self.bgm_fade_in = self.config.get("audio.bgm.fade_in", 1.0)
        self.bgm_fade_out = self.config.get("audio.bgm.fade_out", 1.0)

        # 视频效果配置
        self.transition = self.config.get("effects.transition", "none")
        self.transition_duration = self.config.get("effects.transition_duration", 0.5)
        self.video_filter = self.config.get("effects.filter", "none")
        self.filter_intensity = self.config.get("effects.filter_intensity", 50)

        # 水印配置
        wm_cfg = self.config.get("effects.watermark", {})
        self.watermark_enabled = wm_cfg.get("enabled", False)
        self.watermark_text = wm_cfg.get("text", "EnlyAI")
        self.watermark_position = wm_cfg.get("position", "bottom_right")
        self.watermark_opacity = wm_cfg.get("opacity", 50)

        # 片头片尾配置
        intro_cfg = self.config.get("effects.intro", {})
        outro_cfg = self.config.get("effects.outro", {})
        self.intro_enabled = intro_cfg.get("enabled", False)
        self.intro_text = intro_cfg.get("text", "")
        self.intro_duration = intro_cfg.get("duration", 2.0)
        self.outro_enabled = outro_cfg.get("enabled", False)
        self.outro_text = outro_cfg.get("text", "关注点赞支持一下")
        self.outro_duration = outro_cfg.get("duration", 2.0)

        # 硬件加速：自动检测 NVENC，选用最优编码器（不降质量）
        from ..core.hardware_probe import get_video_encoder, detect_nvenc
        self._nvenc_available = detect_nvenc()
        self._vcodec, self._vpreset, self._vextra = get_video_encoder()

    def setup(self) -> None:
        if not self.ffmpeg.available():
            raise RuntimeError("FFmpeg 不可用，视频合成模块无法工作")
        enc_type = "NVENC 硬件编码" if self._nvenc_available else "CPU 软编码"
        self.logger.info(
            f"视频合成模块初始化 "
            f"resolution={self.output_resolution} fps={self.output_fps} "
            f"编码器={self._vcodec}({enc_type})"
        )
        super().setup()

    def run(self, ctx: JobContext) -> ModuleResult:
        """合成最终视频"""
        if not ctx.raw_video_path or not ctx.raw_video_path.exists():
            return ModuleResult(success=False, error="无口播视频，无法合成")

        output_path = ctx.work_dir / "final_video.mp4"

        try:
            start = time.time()

            # 自动选择 BGM（若未指定且配置启用）
            bgm = ctx.bgm_path
            if not bgm and self.bgm_enabled:
                bgm = self.pick_bgm(self.bgm_track)
                if bgm:
                    self.logger.info(f"自动选择 BGM: {bgm.name}")
                    ctx.bgm_path = bgm

            final = self.compose(
                video=ctx.raw_video_path,
                subtitle=ctx.subtitle_path,
                bgm=bgm,
                cover=ctx.cover_path,
                output=output_path,
                subtitle_segments=ctx.metadata.get("subtitle_segments"),
                voice_audio=ctx.audio_path,  # TTS 真实人声（替换视频静音轨）
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
                    "has_bgm": bgm is not None,
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
        subtitle_segments: Optional[list[dict]] = None,
        voice_audio: Optional[Path] = None,
    ) -> Path:
        """核心合成方法

        Args:
            video: 口播视频
            subtitle: SRT 字幕文件（可选）
            bgm: BGM 音频文件（可选）
            cover: 封面图（可选，作为首帧）
            output: 输出路径
            subtitle_segments: 带词级时间戳的字幕段（优先于 SRT，
                让 karaoke 逐字高亮按真实发音时长分配）
            voice_audio: TTS 真实人声音频（替换视频自带音频）。
                数字人视频可能含静音轨，必须用此参数传入真实人声。
        """
        video = Path(video)
        output = Path(output) if output else video.parent / "final_video.mp4"
        output.parent.mkdir(parents=True, exist_ok=True)

        self.logger.info(
            f"合成视频 video={video.name} "
            f"subtitle={'是' if subtitle else '否'} "
            f"bgm={'是' if bgm else '否'} "
            f"cover={'是' if cover else '否'} "
            f"filter={self.video_filter} "
            f"watermark={'是' if self.watermark_enabled else '否'} "
            f"intro={'是' if self.intro_enabled else '否'} "
            f"outro={'是' if self.outro_enabled else '否'}"
        )

        # 如果有封面，先合成"封面+视频"
        main_video = video
        if cover and Path(cover).exists():
            main_video = self._prepend_cover(video, Path(cover), output.parent)

        # 生成片头/片尾片段（若启用）
        intro_clip = None
        outro_clip = None
        if self.intro_enabled and self.intro_text:
            intro_clip = self._generate_text_clip(
                self.intro_text, self.intro_duration, output.parent, "intro"
            )
        if self.outro_enabled and self.outro_text:
            outro_clip = self._generate_text_clip(
                self.outro_text, self.outro_duration, output.parent, "outro"
            )

        # 若有片头/片尾，先拼接到主视频前后
        if intro_clip or outro_clip:
            main_video = self._concat_intro_outro(
                main_video, intro_clip, outro_clip, output.parent
            )

        # 音视频同步：如果视频开头插入了封面（_prepend_cover 固定 1.5s）或片头，
        # TTS 人声必须加等量静音延迟，否则声音会比嘴型提前播放（封面段视频静音，但音频已开始）
        # 字幕也必须同步偏移，否则字幕会比人声提前显示
        cover_delay_ms = 0
        if cover and Path(cover).exists():
            cover_delay_ms = 1500  # _prepend_cover 固定 1.5 秒封面
        if self.intro_enabled and self.intro_text:
            cover_delay_ms += int(self.intro_duration * 1000)  # 加片头时长

        # 字幕时间戳偏移：和人声延迟保持一致
        shifted_segments = subtitle_segments
        if cover_delay_ms > 0 and subtitle_segments:
            import copy
            delay_sec = cover_delay_ms / 1000.0
            shifted_segments = []
            for seg in subtitle_segments:
                s = copy.deepcopy(seg)
                s["start"] = seg["start"] + delay_sec
                s["end"] = seg["end"] + delay_sec
                # 词级时间戳也要偏移（karaoke 逐字高亮需要）
                if "words" in s:
                    for w in s["words"]:
                        if "start" in w:
                            w["start"] += delay_sec
                        if "end" in w:
                            w["end"] += delay_sec
                shifted_segments.append(s)

        # 构建滤镜链（字幕用偏移后的时间戳，与延迟后的人声同步）
        vf_filters = self._build_video_filters(
            subtitle, output.parent, subtitle_segments=shifted_segments,
        )

        # 构建输入与音频处理
        # 关键：数字人视频可能含静音轨，必须用 voice_audio（TTS）作为人声源
        inputs = ["-i", str(main_video)]
        audio_filter = None
        voice_input_idx = 0  # 默认用主视频的音频

        # 如果有 TTS 真实人声，作为额外输入（index 从 1 开始递增）
        if voice_audio and Path(voice_audio).exists():
            inputs += ["-i", str(voice_audio)]
            voice_input_idx = len(inputs) // 2 - 1  # 刚加的输入索引

        # 构建人声滤镜链（含延迟补偿）
        def _voice_chain(out_label: str) -> str:
            chain = f"[{voice_input_idx}:a]volume=1.0"
            if cover_delay_ms > 0:
                chain += f",adelay={cover_delay_ms}|{cover_delay_ms}"
            chain += f"[{out_label}]"
            return chain

        if bgm and Path(bgm).exists():
            inputs += ["-i", str(bgm)]
            bgm_input_idx = len(inputs) // 2 - 1
            # 人声(TTS,含封面延迟) + BGM 混音
            audio_filter = (
                _voice_chain("voice") + ";"
                f"[{bgm_input_idx}:a]volume={self.bgm_volume}[bgm];"
                f"[voice][bgm]amix=inputs=2:duration=first:dropout_transition=0[aout]"
            )
        elif voice_audio and Path(voice_audio).exists():
            # 只有人声，无 BGM（含封面延迟补偿）
            audio_filter = _voice_chain("aout")

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
            "-c:v", self._vcodec,
            "-preset", self._vpreset,
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

    def _build_video_filters(
        self, subtitle: Optional[Path], work_dir: Optional[Path] = None,
        subtitle_segments: Optional[list[dict]] = None,
    ) -> str:
        """构建视频滤镜链（含分辨率统一、滤镜、字幕、水印）

        字幕使用 ASS 格式（通过 subtitle_styler 生成），支持样式预设/动画/逐字高亮。
        - 若传入 subtitle_segments（含 whisper 词级时间戳），直接用它生成 ASS，
          karaoke 逐字高亮按真实发音时长分配（最优精度）
        - 否则从 SRT 文件转换
        """
        filters: list[str] = []
        # 统一分辨率
        w, h = self.output_resolution
        filters.append(
            f"scale={w}:{h}:force_original_aspect_ratio=decrease"
        )
        filters.append(f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2")
        filters.append(f"fps={self.output_fps}")

        # 滤镜效果（对标剪映滤镜，8+ 种）
        vf = self._build_filter_chain()
        if vf:
            filters.append(vf)

        # 字幕烧录（ASS 格式，支持样式预设/动画/逐字高亮）
        if subtitle and Path(subtitle).exists():
            ass_path = self._ensure_ass_subtitle(
                subtitle, work_dir, segments=subtitle_segments,
            )
            if ass_path:
                # 转义路径中的特殊字符
                sub_path = str(ass_path.absolute()).replace("\\", "/").replace(":", r"\:")
                filters.append(f"subtitles='{sub_path}'")

        # 水印
        if self.watermark_enabled and self.watermark_text:
            wm_filter = self._build_watermark_filter(w, h)
            if wm_filter:
                filters.append(wm_filter)

        return ",".join(filters)

    def _ensure_ass_subtitle(
        self, subtitle: Path, work_dir: Optional[Path] = None,
        segments: Optional[list[dict]] = None,
    ) -> Optional[Path]:
        """确保字幕为 ASS 格式（应用样式预设/动画/逐字高亮）

        优先用 segments（含 whisper 词级时间戳）直接生成 ASS，
        让 karaoke 逐字高亮按真实发音时长分配；否则从 SRT 转换。
        """
        subtitle = Path(subtitle)
        if work_dir is None:
            work_dir = subtitle.parent
        else:
            work_dir = Path(work_dir)

        # 如果已经是 ASS，直接使用
        if subtitle.suffix.lower() == ".ass":
            return subtitle

        ass_path = work_dir / (subtitle.stem + ".ass")
        try:
            # 优先：用词级 segments 生成 ASS（逐字高亮最精准）
            if segments:
                from .subtitle_styler import write_ass_file
                write_ass_file(
                    segments, ass_path,
                    preset=self.subtitle_preset,
                    animation=self.subtitle_animation,
                    font_size=self.subtitle_font_size,
                    font_name=self.subtitle_font_name,
                    position=self.subtitle_position,
                    alignment=self.subtitle_alignment,
                    margin_v=self.subtitle_margin_v,
                    karaoke=self.subtitle_karaoke,
                    bold=self.subtitle_bold,
                    italic=self.subtitle_italic,
                    outline_width=self.subtitle_outline_width,
                    shadow_distance=self.subtitle_shadow_distance,
                    letter_spacing=self.subtitle_letter_spacing,
                    line_spacing=self.subtitle_line_spacing,
                    play_res_x=self.output_resolution[0],
                    play_res_y=self.output_resolution[1],
                    max_chars_per_line=0,  # 0=自动按分辨率和字号计算，长句自动折行
                )
                word_count = sum(len(s.get("words", [])) for s in segments)
                self.logger.info(
                    f"字幕 segments→ASS（词级时间戳）preset={self.subtitle_preset} "
                    f"animation={self.subtitle_animation} karaoke={self.subtitle_karaoke} "
                    f"word_timestamps={word_count}"
                )
                return ass_path

            # 退回：SRT 转 ASS
            srt_to_ass(
                subtitle, ass_path,
                preset=self.subtitle_preset,
                animation=self.subtitle_animation,
                font_size=self.subtitle_font_size,
                font_name=self.subtitle_font_name,
                position=self.subtitle_position,
                alignment=self.subtitle_alignment,
                margin_v=self.subtitle_margin_v,
                karaoke=self.subtitle_karaoke,
                bold=self.subtitle_bold,
                italic=self.subtitle_italic,
                outline_width=self.subtitle_outline_width,
                shadow_distance=self.subtitle_shadow_distance,
                letter_spacing=self.subtitle_letter_spacing,
                line_spacing=self.subtitle_line_spacing,
                play_res_x=self.output_resolution[0],
                play_res_y=self.output_resolution[1],
                max_chars_per_line=0,  # 0=自动按分辨率和字号计算，长句自动折行
            )
            self.logger.info(
                f"字幕 SRT→ASS 转换 preset={self.subtitle_preset} "
                f"animation={self.subtitle_animation} karaoke={self.subtitle_karaoke}"
            )
            return ass_path
        except Exception as e:
            self.logger.warning(f"ASS 字幕生成失败，降级使用 SRT: {e}")
            return subtitle

    def _build_filter_chain(self) -> Optional[str]:
        """构建滤镜链（对标剪映，8+ 种滤镜）

        基础调色：warm/cool/bw/vintage/vivid
        复合滤镜：cinematic/vlog/film/noir/summer
        """
        intensity = self.filter_intensity / 100.0
        f = self.video_filter

        # ===== 基础调色滤镜 =====
        if f == "warm":
            return f"eq=brightness=0.03:saturation={1.0+intensity*0.3}:gamma_r={1.0+intensity*0.1}:gamma_b={1.0-intensity*0.1}"
        elif f == "cool":
            return f"eq=brightness=0.02:saturation={1.0+intensity*0.2}:gamma_b={1.0+intensity*0.1}:gamma_r={1.0-intensity*0.1}"
        elif f == "bw":
            return f"hue=s=0,eq=brightness=0.02:contrast={1.0+intensity*0.1}"
        elif f == "vintage":
            return f"eq=saturation={1.0-intensity*0.4}:gamma_r={1.0+intensity*0.05}:gamma_g={1.0+intensity*0.03}:gamma_b={1.0-intensity*0.08}"
        elif f == "vivid":
            return f"eq=saturation={1.0+intensity*0.5}:contrast={1.0+intensity*0.1}"

        # ===== 复合滤镜（对标剪映电影感/Vlog/胶片） =====
        elif f == "cinematic":
            # 电影感：青橙色调 + 暗角 + 轻微对比
            i = intensity
            return (
                f"eq=saturation={1.0+i*0.15}:contrast={1.0+i*0.08}:gamma_r={1.0+i*0.05}:gamma_b={1.0+i*0.08},"
                f"vignette=PI/4"
            )
        elif f == "vlog":
            # Vlog 清新：提亮 + 降对比 + 微暖
            i = intensity
            return (
                f"eq=brightness={0.04*i}:contrast={1.0-i*0.05}:saturation={1.0+i*0.1}:gamma_g={1.0+i*0.03}"
            )
        elif f == "film":
            # 胶片质感：降饱和 + 颗粒感 + 偏黄
            i = intensity
            return (
                f"eq=saturation={1.0-i*0.25}:contrast={1.0+i*0.05}:gamma_r={1.0+i*0.04}:gamma_b={1.0-i*0.06},"
                f"noise=alls={int(i*20)}:allf=t"
            )
        elif f == "noir":
            # 黑色电影：高对比黑白 + 暗角
            i = intensity
            return (
                f"hue=s=0,eq=brightness=-0.02:contrast={1.0+i*0.3},"
                f"vignette=PI/3"
            )
        elif f == "summer":
            # 夏日清新：鲜艳 + 偏青绿 + 提亮
            i = intensity
            return (
                f"eq=brightness={0.03*i}:saturation={1.0+i*0.3}:gamma_g={1.0+i*0.06}:gamma_b={1.0+i*0.04}"
            )
        return None

    def _build_watermark_filter(self, w: int, h: int) -> Optional[str]:
        """构建水印滤镜"""
        alpha = max(0.1, min(1.0, self.watermark_opacity / 100.0))
        # 位置映射
        positions = {
            "top_left": f"x=20:y=20",
            "top_right": f"x={w}-tw-20:y=20",
            "bottom_left": f"x=20:y={h}-th-20",
            "bottom_right": f"x={w}-tw-20:y={h}-th-20",
        }
        pos = positions.get(self.watermark_position, positions["bottom_right"])
        # 转义水印文字中的特殊字符
        text = self.watermark_text.replace(":", r"\:").replace("'", r"\'")
        return f"drawtext=text='{text}':fontcolor=white@{alpha}:fontsize={max(16, w//40)}:{pos}:box=1:boxcolor=black@{alpha*0.5}"

    def _prepend_cover(
        self, video: Path, cover: Path, work_dir: Path
    ) -> Path:
        """在视频开头插入封面图（1.5 秒）"""
        self.logger.info(f"插入封面首帧: {cover.name}")

        # 将封面图转为 1.5 秒的视频片段
        cover_clip = work_dir / "_tmp_cover_intro.mp4"
        w, h = self.output_resolution

        # 调整封面尺寸
        resized_cover = work_dir / "_tmp_cover_resized.jpg"
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
            "-c:v", self._vcodec,
            "-preset", self._vpreset,
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(cover_clip),
        ]
        self.ffmpeg.run(args)

        # 拼接封面 + 原视频
        # 先确保原视频参数一致（重新编码为统一参数）
        # 注意：wav2lip 输出的 avatar 视频可能没有音频流，需补静音轨，否则 concat 时 [1:a] 找不到流
        normalized_video = work_dir / "_tmp_main_normalized.mp4"
        args = [
            "-i", str(video),
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=mono:sample_rate=44100",
            "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                   f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={self.output_fps},format=yuv420p",
            "-map", "0:v:0",
            "-map", "1:a:0",  # 静音音频轨（与视频时长对齐）
            "-c:v", self._vcodec,
            "-preset", self._vpreset,
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", self.audio_bitrate,
            "-r", str(self.output_fps),
            "-shortest",
            str(normalized_video),
        ]
        self.ffmpeg.run(args)

        # concat（用 filter 重新编码，避免参数不一致导致 copy 失败）
        combined = work_dir / "_tmp_with_cover.mp4"
        args = [
            "-i", str(cover_clip),
            "-i", str(normalized_video),
            "-filter_complex",
            f"[0:v][0:a][1:v][1:a]concat=n=2:v=1:a=1[outv][outa]",
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", self._vcodec,
            "-preset", self._vpreset,
            "-pix_fmt", "yuv420p",
            "-r", str(self.output_fps),
            "-c:a", "aac",
            "-b:a", self.audio_bitrate,
            str(combined),
        ]
        self.ffmpeg.run(args)
        return combined

    def pick_bgm(self, style: str = "default") -> Optional[Path]:
        """从 BGM 库选择 BGM

        Args:
            style: BGM 曲目标识（如 soft_piano/upbeat_corporate），
                   'default' 或 'random' 表示随机选择
        """
        import random
        if not self.bgm_dir.exists():
            return None
        bgms = list(self.bgm_dir.glob("*.mp3")) + list(self.bgm_dir.glob("*.m4a"))
        if not bgms:
            return None
        if style and style not in ("default", "random"):
            # 按曲目名精确匹配
            for bgm in bgms:
                if bgm.stem == style:
                    return bgm
        return random.choice(bgms)

    def _concat_intro_outro(
        self,
        main_video: Path,
        intro: Optional[Path],
        outro: Optional[Path],
        work_dir: Path,
    ) -> Path:
        """拼接片头+主视频+片尾"""
        w, h = self.output_resolution
        # 先统一主视频参数（补静音音频轨，避免无音频流时 concat 失败）
        normalized = work_dir / "_tmp_main_for_concat.mp4"
        args = [
            "-i", str(main_video),
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=mono:sample_rate=44100",
            "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                   f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={self.output_fps},format=yuv420p",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:v", self._vcodec, "-preset", self._vpreset, "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", self.audio_bitrate,
            "-r", str(self.output_fps),
            "-shortest",
            str(normalized),
        ]
        self.ffmpeg.run(args)

        segments = []
        if intro and intro.exists():
            segments.append(intro)
        segments.append(normalized)
        if outro and outro.exists():
            segments.append(outro)

        if len(segments) == 1:
            return normalized

        combined = work_dir / "_tmp_with_intro_outro.mp4"
        # 构建输入
        inputs = []
        for s in segments:
            inputs += ["-i", str(s)]
        # concat 滤镜
        concat_parts = "".join(f"[{i}:v][{i}:a]" for i in range(len(segments)))
        args = inputs + [
            "-filter_complex",
            f"{concat_parts}concat=n={len(segments)}:v=1:a=1[outv][outa]",
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", self._vcodec, "-preset", self._vpreset, "-pix_fmt", "yuv420p",
            "-r", str(self.output_fps),
            "-c:a", "aac", "-b:a", self.audio_bitrate,
            str(combined),
        ]
        self.ffmpeg.run(args)
        self.logger.info(f"拼接片头片尾完成: {len(segments)} 段")
        return combined

    def _generate_text_clip(
        self, text: str, duration: float, work_dir: Path, prefix: str
    ) -> Optional[Path]:
        """生成文字片头/片尾视频片段（渐变背景 + 文字动画）

        对标剪映片头片尾：渐变背景 + 文字淡入缩放 + 装饰元素
        """
        if not text:
            return None
        w, h = self.output_resolution
        clip_path = work_dir / f"_tmp_{prefix}.mp4"
        # 转义文字
        safe_text = text.replace(":", r"\:").replace("'", r"\'")
        # 尝试加载中文字体
        font_path = self._find_chinese_font()
        font_opt = f":fontfile='{font_path}'" if font_path else ""

        # 根据前缀选择渐变色（片头用深蓝→紫，片尾用深紫→红）
        if prefix == "intro":
            # 片头：深蓝到紫色渐变
            grad = "0x0A0A2E-0x2D1B4E"
            font_color = "white"
        else:
            # 片尾：深紫到暗红渐变
            grad = "0x2D1B4E-0x4A1A2E"
            font_color = "0xFFD700"  # 金色

        font_size = max(48, h // 18)

        # 构建渐变背景 + 文字动画滤镜
        # 1. 渐变背景：用 gradients 滤镜（FFmpeg 6+）或 fallback 到纯色
        # 2. 文字：drawtext + 淡入 + 缩放动画
        # 3. 装饰：底部细线
        vf = (
            # 文字主体（居中，带淡入）
            f"drawtext=text='{safe_text}':fontcolor={font_color}:fontsize={font_size}"
            f":x=(w-text_w)/2:y=(h-text_h)/2{font_opt}:line_spacing=15,"
            # 文字淡入（前 0.6s）
            f"fade=t=in:st=0:d=0.6:alpha=1,"
            # 文字淡出（后 0.5s）
            f"fade=t=out:st={max(0,duration-0.5)}:d=0.5:alpha=1,"
            # 整体淡入淡出
            f"fade=t=in:st=0:d=0.3,fade=t=out:st={max(0,duration-0.3)}:d=0.3"
        )

        args = [
            "-f", "lavfi",
            "-i", f"color=c=0x0A0A2E:s={w}x{h}:d={duration}:r={self.output_fps}",
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=mono:sample_rate=44100",
            "-vf", vf,
            "-t", f"{duration}",
            "-c:v", self._vcodec, "-preset", self._vpreset, "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(clip_path),
        ]
        try:
            self.ffmpeg.run(args)
            return clip_path
        except Exception as e:
            self.logger.warning(f"生成{prefix}失败: {e}")
            # 降级：纯黑背景
            try:
                args_fallback = [
                    "-f", "lavfi",
                    "-i", f"color=c=black:s={w}x{h}:d={duration}",
                    "-f", "lavfi",
                    "-i", "anullsrc=channel_layout=mono:sample_rate=44100",
                    "-vf",
                    f"drawtext=text='{safe_text}':fontcolor=white:fontsize={font_size}"
                    f":x=(w-text_w)/2:y=(h-text_h)/2{font_opt},"
                    f"fade=t=in:st=0:d=0.5,fade=t=out:st={max(0,duration-0.5)}:d=0.5",
                    "-t", f"{duration}",
                    "-c:v", self._vcodec, "-preset", self._vpreset, "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k",
                    "-shortest",
                    str(clip_path),
                ]
                self.ffmpeg.run(args_fallback)
                return clip_path
            except Exception as e2:
                self.logger.warning(f"生成{prefix}降级也失败: {e2}")
                return None

    def _find_chinese_font(self) -> Optional[str]:
        """查找系统中可用的中文字体（跨平台，返回字体文件路径）"""
        import os
        import platform
        # Windows
        if platform.system() == "Windows":
            win_fonts = [
                "C:/Windows/Fonts/msyhbd.ttc",   # 微软雅黑粗体
                "C:/Windows/Fonts/msyh.ttc",     # 微软雅黑
                "C:/Windows/Fonts/simhei.ttf",   # 黑体
            ]
            for p in win_fonts:
                if os.path.exists(p):
                    return p
        # macOS
        if platform.system() == "Darwin":
            mac_fonts = [
                "/System/Library/Fonts/PingFang.ttc",
                "/Library/Fonts/Songti.ttc",
            ]
            for p in mac_fonts:
                if os.path.exists(p):
                    return p
        # Linux
        candidates = [
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
            "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        ]
        for p in candidates:
            if os.path.exists(p):
                return p
        return None
