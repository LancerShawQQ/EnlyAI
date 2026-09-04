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
            self.bgm_volume = self.config.get("composer.bgm_volume", 0.22)

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
        # 双行字幕开关：False 时不折行（单行长字幕），True 由 styler 自动折行
        self.subtitle_dual_line = sub_cfg.get("dual_line", True)
        self.subtitle_bold = sub_cfg.get("bold", True)
        self.subtitle_italic = sub_cfg.get("italic", False)
        self.subtitle_outline_width = sub_cfg.get("outline_width", None)
        self.subtitle_shadow_distance = sub_cfg.get("shadow_distance", None)
        self.subtitle_letter_spacing = sub_cfg.get("letter_spacing", 0)
        self.subtitle_line_spacing = sub_cfg.get("line_spacing", 1.2)
        # 颜色覆盖（apply_template 写入的 primary_color/outline_color/shadow_color）
        # 优先级：配置 > 预设默认值；为空时传 None 让 subtitle_styler 使用预设
        self.subtitle_primary_color = sub_cfg.get("primary_color", None) or None
        self.subtitle_outline_color = sub_cfg.get("outline_color", None) or None
        self.subtitle_shadow_color = sub_cfg.get("shadow_color", None) or None
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
        # 空字符串视为 "none"（避免 xfade 收到空 transition 值报错）
        _transition = self.config.get("effects.transition", "none")
        self.transition = _transition if _transition else "none"
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

        # Scene 配置（数字人位置/大小/Logo）
        scene_cfg = self.config.get("scene", {}) or {}
        self.scene_position = scene_cfg.get("position", "center")
        self.scene_scale = float(scene_cfg.get("scale", 1.0))
        # 背景颜色（用于 pad 填充，替代硬编码 black）
        # 支持 #RRGGBB 格式，转为 0xRRGGBB 给 ffmpeg
        self.scene_bg_color = scene_cfg.get("background_color", "#000000")
        self.show_logo = bool(scene_cfg.get("show_logo", False))
        self.logo_position = scene_cfg.get("logo_position", "top_right")
        self.logo_image = scene_cfg.get("logo_image", "")

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
                    # 检查 BGM 文件有效性（Git LFS 指针文件只有 ~132 字节）
                    if bgm.stat().st_size < 1024:
                        self.logger.warning(
                            f"BGM 文件无效或为 Git LFS 指针（{bgm.name}, {bgm.stat().st_size} bytes），跳过 BGM"
                        )
                        bgm = None
                    else:
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
        # lead_delay_ms：正片内容在成片中的实际起点（毫秒）。
        # 人声 adelay 与字幕偏移都必须用它，而不是名义封面时长——
        # xfade 转场会让正片提前 transition_duration 秒出现，用名义值会让人声比嘴型晚
        #
        # 封面停留可配（composer.cover_hold_seconds）：
        # 0 = 抖音式立即进主体——封面不进成片，只作应用内 poster 预览图
        #     与发布时的平台封面；正片从 0s 开始
        # >0 = 传统封面停留：封面段 hold 秒 + 转场进正片（旧行为）
        cover_hold_s = min(max(float(self.config.get(
            "composer.cover_hold_seconds", 0.0)), 0.0), 3.0)
        main_video = video
        lead_delay_ms = 0
        if cover and Path(cover).exists() and cover_hold_s > 0.05:
            main_video, cover_lead_ms = self._prepend_cover(
                video, Path(cover), output.parent, hold_seconds=cover_hold_s,
            )
            lead_delay_ms += cover_lead_ms

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
            main_video, intro_lead_ms = self._concat_intro_outro(
                main_video, intro_clip, outro_clip, output.parent
            )
            lead_delay_ms += intro_lead_ms

        # 音视频同步：正片实际起点 = lead_delay_ms + 开口起手静默。
        # 人声/口型/字幕三方必须用同一偏移量，任何一方单独偏移都会导致
        # "嘴动没声"或"字幕先于声音"的错位。
        # 开口起手可配（composer.speech_lead_seconds，默认 0.25s）：
        # 抖音式成片 0.2-0.4s 内开口最自然；旧硬编码 1s 观感是"等太久"
        SPEECH_LEAD_S = min(max(float(self.config.get(
            "composer.speech_lead_seconds", 0.25)), 0.0), 2.0)
        speech_delay_ms = lead_delay_ms + int(SPEECH_LEAD_S * 1000)
        self.logger.info(
            f"成片时序: 封面停留={cover_hold_s}s 正片起点={lead_delay_ms}ms "
            f"开口延迟={speech_delay_ms}ms（人声/口型/字幕共用同一偏移）"
        )

        # 字幕时间戳偏移：和人声延迟保持一致（cover + 开场留白）
        shifted_segments = subtitle_segments
        if speech_delay_ms > 0 and subtitle_segments:
            import copy
            delay_sec = speech_delay_ms / 1000.0
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
        # 视频时间轴同步：
        # 1) 开场：正片首帧定格 1s（人物可见但静止），口型与声音同时从
        #    speech_delay 处开始——不加这个，口型比声音早 1s（嘴动没声）
        # 2) 收尾：末帧定格 2.5s > 开场留白+收尾余韵，防 -shortest 截断音频
        if voice_audio and Path(voice_audio).exists() and speech_delay_ms > 0:
            pad = (vf_filters + "," if vf_filters else "")
            vf_filters = pad + \
                f"tpad=start_duration={SPEECH_LEAD_S}:start_mode=clone," + \
                "tpad=stop_mode=clone:stop_duration=2.5"

        # 构建输入与音频处理
        # 音轨策略：始终使用原始 TTS 24kHz 音轨（voice_audio）作为人声源——
        # avatar_output 内嵌音轨经 LatentSync 内部 16kHz 重采样（带宽损失一档），
        # 而原始 TTS 音轨与唇形在同一时间轴上（LatentSync 就是用它驱动的），
        # 替换只提升音质、不影响同步。
        inputs = ["-i", str(main_video)]
        audio_filter = None

        have_voice = bool(voice_audio and Path(voice_audio).exists())
        voice_input_idx = 0
        if have_voice:
            inputs += ["-i", str(voice_audio)]
            voice_input_idx = len(inputs) // 2 - 1

        # 构建人声滤镜链（含封面延迟补偿 + 开场/收尾呼吸感）
        # 商用成片节奏：封面 1s → 正片画面 1s 静默 → 开口 → 最后一句后 1s 余韵再结束
        TAIL_PAD_S = 0.5
        def _voice_chain(out_label: str) -> str:
            # 不剥前置静音！avatar 按完整音频驱动口型（前置静音期间口型闭合），
            # compose 必须用同一时间轴——剥掉静音会导致声音比口型早 N 秒
            chain = f"[{voice_input_idx}:a]volume=1.0"
            if speech_delay_ms > 0:
                chain += f",adelay={speech_delay_ms}|{speech_delay_ms}"
                # 人声淡入 80ms：防"咔"声但不吞字
                fade_start = speech_delay_ms / 1000.0
                chain += f",afade=t=in:st={fade_start:.3f}:d=0.08"
                # 结尾余韵：说完最后一句不戛然而止
                chain += f",apad=pad_dur={TAIL_PAD_S}"
            chain += f"[{out_label}]"
            return chain

        if bgm and Path(bgm).exists():
            inputs += ["-i", str(bgm)]
            bgm_input_idx = len(inputs) // 2 - 1
            # BGM 滤镜链：音量 + 淡入 + 淡出（afade）
            bgm_chain = f"[{bgm_input_idx}:a]volume={self.bgm_volume}"
            if self.bgm_fade_in > 0:
                bgm_chain += f",afade=t=in:st=0:d={self.bgm_fade_in}"
            if self.bgm_fade_out > 0:
                # 获取视频时长以计算淡出起始时间
                bgm_info = self.ffmpeg.probe_video_info(Path(main_video))
                bgm_dur = bgm_info.duration if bgm_info else 0
                if bgm_dur > self.bgm_fade_out:
                    fade_out_st = bgm_dur - self.bgm_fade_out
                    bgm_chain += f",afade=t=out:st={fade_out_st:.2f}:d={self.bgm_fade_out}"
            bgm_chain += "[bgm]"
            # 人声(TTS,含封面延迟) + BGM 混音（sidechain ducking：人声说话时自动压低 BGM）
            # amix 后加 loudnorm 做最终响度归一化 -16 LUFS（社媒标准 -14~-16）
            # dropout_transition=0 避免某一路静音时另一路音量突增
            # 注意：FFmpeg filter_complex 中一个 label 只能被消费一次——
            # [voice] 需 asplit 分成两路（sidechain 用一路、amix 用另一路），
            # 直接重复引用会导致人声丢失（只出 BGM）
            audio_filter = (
                _voice_chain("voice") + ";"
                + bgm_chain + ";"
                f"[voice]asplit=2[voice_sc][voice_mix];"
                f"[bgm][voice_sc]sidechaincompress=threshold=0.03:ratio=8:"
                f"attack=200:release=1000[bgm_ducked];"
                f"[voice_mix][bgm_ducked]amix=inputs=2:duration=first:dropout_transition=0,"
                f"loudnorm=I=-16:TP=-1.5:LRA=11[aout]"
            )
        elif have_voice:
            # 只有人声无 BGM：用原始 24kHz TTS 轨（含封面延迟补偿）
            audio_filter = _voice_chain("aout")
        else:
            # 无 voice_audio（异常兜底）：使用 avatar_output 自带音轨
            audio_filter = None

        # Logo 叠加输入（scene 配置）：在音频输入之后追加，索引动态计算
        # Logo overlay 需要多输入，必须走 -filter_complex 路径
        logo_input_idx = -1
        logo_overlay_chain = None
        if self.show_logo and self.logo_image and Path(self.logo_image).exists():
            inputs += ["-i", str(self.logo_image)]
            logo_input_idx = len(inputs) // 2 - 1
            lx, ly = self._get_logo_overlay_pos(self.logo_position)
            # logo 链：确保 png 透明通道（rgba），再 overlay 到主视频
            logo_overlay_chain = (
                f"[{logo_input_idx}:v]format=rgba[logo];"
                f"[vbase][logo]overlay={lx}:{ly}[vout]"
            )
            self.logger.info(
                f"Logo 叠加启用 image={self.logo_image} "
                f"position={self.logo_position} overlay={lx}:{ly}"
            )

        # 构建命令
        args = list(inputs)
        use_logo_filter_complex = logo_input_idx >= 0 and logo_overlay_chain

        if use_logo_filter_complex:
            # Logo 叠加：多输入 overlay 必须用 -filter_complex
            # 视频链：[0:v]<vf_filters>[vbase]; logo overlay -> [vout]
            video_chain = (
                f"[0:v]{vf_filters}[vbase]"
                if vf_filters
                else "[0:v]null[vbase]"
            )
            filter_complex = video_chain + ";" + logo_overlay_chain
            if audio_filter:
                filter_complex += ";" + audio_filter
            args += ["-filter_complex", filter_complex]
            args += ["-map", "[vout]"]
            if audio_filter:
                args += ["-map", "[aout]"]
        else:
            # 原有逻辑（无 Logo，保持不变）
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
            *self._vextra,
            # 码率控制：无论硬编（QSV/NVENC）还是软编（libx264）都加 maxrate 限制
            # 修复 QSV 模式下无码率控制导致 final_video bitrate 仅 575kbps 的问题
            *(["-crf", "18"] if self._vcodec == "libx264" else []),
            "-maxrate", self.video_bitrate,
            "-bufsize", self.video_bitrate,
            "-pix_fmt", "yuv420p",
            "-r", str(self.output_fps),
            # 色彩空间标准化：源素材可能带 yuvj420p/bt470bg 全范围标记
            # （JPEG 遗留），部分平台转码异常；统一为 bt709 limited range
            "-colorspace", "bt709",
            "-color_primaries", "bt709",
            "-color_trc", "bt709",
            "-color_range", "tv",
            "-c:a", "aac",
            "-ar", "48000",  # 统一 48kHz（此前 24k→16k→96k 链路混乱）
            "-b:a", self.audio_bitrate,
            "-movflags", "+faststart",
            "-shortest",
            str(output),
        ]

        self.ffmpeg.run(args)
        self.logger.info(f"视频合成完成: {output}")

        # 清理中间产物（_tmp_* 文件对用户无价值，占磁盘且暴露内部实现）
        for tmp in output.parent.glob("_tmp_*"):
            try:
                tmp.unlink()
                self.logger.debug(f"已清理中间文件: {tmp.name}")
            except OSError:
                pass

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
        # 根据 scene_scale 调整（仅当 scale != 1.0 时改变行为）
        # scale=1.0 时保持原有铺满逻辑，避免影响现有行为
        if abs(self.scene_scale - 1.0) > 0.01:
            # 缩放后用 pad 填充（黑边），position 影响偏移
            # scale<1.0 数字人缩小露出黑边；scale>1.0 放大裁切
            scaled_w = int(w * self.scene_scale)
            scaled_h = int(h * self.scene_scale)
            if self.scene_position == "left":
                x_offset, y_offset = "0", "(oh-ih)/2"
            elif self.scene_position == "right":
                x_offset, y_offset = "(ow-iw)", "(oh-ih)/2"
            else:  # center
                x_offset, y_offset = "(ow-iw)/2", "(oh-ih)/2"
            filters.append(
                f"scale={scaled_w}:{scaled_h}:force_original_aspect_ratio=decrease:flags=lanczos"
            )
            # pad 颜色：使用 scene.background_color（如模板配置的彩色背景），替代硬编码 black
            # #RRGGBB → 0xRRGGBB
            _bg_hex = (self.scene_bg_color or "#000000").lstrip("#")
            filters.append(f"pad={w}:{h}:{x_offset}:{y_offset}:0x{_bg_hex}")
        else:
            # scale=1.0 时保持原有铺满逻辑
            filters.append(
                f"scale={w}:{h}:force_original_aspect_ratio=decrease:flags=lanczos"
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
                    max_chars_per_line=(0 if self.subtitle_dual_line else 9999),  # dual_line=False 时 9999=不折行；True 0=自动按分辨率折行
                    primary_color=self.subtitle_primary_color,
                    outline_color=self.subtitle_outline_color,
                    shadow_color=self.subtitle_shadow_color,
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
                max_chars_per_line=(0 if self.subtitle_dual_line else 9999),  # dual_line=False 时 9999=不折行；True 0=自动按分辨率折行
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

    def _get_logo_overlay_pos(self, position: str) -> tuple:
        """返回 Logo overlay 的 x, y 坐标表达式

        坐标用 overlay 滤镜的内置变量：W/w 为主视频/overlay 宽，H/h 为主视频/overlay 高。
        兼容连字符(top-right)与下划线(top_right)两种命名（前端发送连字符）。
        """
        # 统一为下划线
        pos = (position or "").replace("-", "_")
        positions = {
            "top_left": ("20", "20"),
            "top_right": ("W-w-20", "20"),
            "bottom_left": ("20", "H-h-20"),
            "bottom_right": ("W-w-20", "H-h-20"),
        }
        return positions.get(pos, positions["top_right"])

    def _prepend_cover(
        self, video: Path, cover: Path, work_dir: Path,
        hold_seconds: float = 1.0,
    ) -> tuple[Path, int]:
        """在视频开头插入封面图（hold_seconds 秒，可配）

        Returns:
            (拼接后视频路径, 正片实际起点毫秒数)。
            xfade 转场与封面重叠 transition_duration 秒，正片提前出现，
            人声/字幕延迟必须按返回值而不是名义时长。
        """
        self.logger.info(f"插入封面首帧: {cover.name} 停留 {hold_seconds}s")

        # 将封面图转为视频片段
        cover_clip = work_dir / "_tmp_cover_intro.mp4"
        w, h = self.output_resolution
        cover_duration = min(max(float(hold_seconds), 0.2), 3.0)

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
            "-t", str(cover_duration),
            "-vf", f"scale={w}:{h},fps={self.output_fps},format=yuv420p",
            "-c:v", self._vcodec,
            "-preset", self._vpreset,
            *self._vextra,
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
            *self._vextra,
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", self.audio_bitrate,
            "-r", str(self.output_fps),
            "-shortest",
            str(normalized_video),
        ]
        self.ffmpeg.run(args)

        # 拼接封面 + 原视频
        # 封面→正片固定用 fade：slide 类转场在首帧暴露未初始化的 YUV 边缘
        # （RGB 下显示为绿色竖线，恰好是视频缩略图帧），fade 无此问题且观感更专业
        combined = work_dir / "_tmp_with_cover.mp4"
        if self.transition != "none":
            # xfade 转场拼接（封面→主视频），正片起点 = 封面时长 - 转场重叠
            try:
                combined = self._xfade_concat(
                    [cover_clip, normalized_video], work_dir, "_tmp_with_cover.mp4",
                    transition="fade",
                )
                lead_ms = int((cover_duration - self.transition_duration) * 1000)
            except Exception as e:
                self.logger.warning(f"xfade 转场失败，回退 concat: {e}")
                combined = self._plain_concat(
                    [cover_clip, normalized_video], work_dir, "_tmp_with_cover.mp4"
                )
                lead_ms = int(cover_duration * 1000)
        else:
            combined = self._plain_concat(
                [cover_clip, normalized_video], work_dir, "_tmp_with_cover.mp4"
            )
            lead_ms = int(cover_duration * 1000)
        return combined, lead_ms

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
            "-c:v", self._vcodec, "-preset", self._vpreset, *self._vextra, "-pix_fmt", "yuv420p",
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
            return normalized, 0

        combined = work_dir / "_tmp_with_intro_outro.mp4"
        if self.transition != "none" and len(segments) >= 2:
            # xfade 转场拼接（片头→主视频→片尾）
            # 片头与主视频转场重叠 transition_duration 秒 → 正片起点相应提前
            try:
                combined = self._xfade_concat(
                    segments, work_dir, "_tmp_with_intro_outro.mp4"
                )
                intro_lead_ms = (
                    int(self.intro_duration * 1000 - self.transition_duration * 1000)
                    if intro else 0
                )
            except Exception as e:
                self.logger.warning(f"xfade 转场失败，回退 concat: {e}")
                combined = self._plain_concat(
                    segments, work_dir, "_tmp_with_intro_outro.mp4"
                )
                intro_lead_ms = int(self.intro_duration * 1000) if intro else 0
        else:
            combined = self._plain_concat(
                segments, work_dir, "_tmp_with_intro_outro.mp4"
            )
            intro_lead_ms = int(self.intro_duration * 1000) if intro else 0
        self.logger.info(f"拼接片头片尾完成: {len(segments)} 段")
        return combined, intro_lead_ms

    def _plain_concat(
        self, segments: list[Path], work_dir: Path, output_name: str
    ) -> Path:
        """普通 concat 拼接（无转场）

        所有 segments 必须已包含音频流（静音轨亦可）。
        """
        output = work_dir / output_name
        inputs: list[str] = []
        for s in segments:
            inputs += ["-i", str(s)]
        concat_parts = "".join(f"[{i}:v][{i}:a]" for i in range(len(segments)))
        args = inputs + [
            "-filter_complex",
            f"{concat_parts}concat=n={len(segments)}:v=1:a=1[outv][outa]",
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", self._vcodec, "-preset", self._vpreset,
            *self._vextra, "-pix_fmt", "yuv420p",
            "-r", str(self.output_fps),
            "-c:a", "aac", "-b:a", self.audio_bitrate,
            str(output),
        ]
        self.ffmpeg.run(args)
        return output

    # slide/wipe 类方向性转场会在画面边缘暴露未初始化像素（YUV 零值 = RGB 绿色竖线）
    _DIRECTIONAL_TRANSITIONS = {
        "slideleft", "slideright", "slideup", "slidedown",
        "smoothleft", "smoothright", "smoothup", "smoothdown",
        "wipeleft", "wiperight", "wipeup", "wipedown",
        "squeezeh", "squeezev", "hlwind", "hrwind", "vslidestr",
    }
    _EDGE_PAD = 16  # 方向性转场的边缘保护带（像素）

    def _xfade_concat(
        self, segments: list[Path], work_dir: Path, output_name: str,
        transition: Optional[str] = None,
    ) -> Path:
        """使用 xfade 转场拼接多段视频

        视频用 xfade 链式转场，音频用 concat（xfade 不支持音频转场）。
        所有 segments 必须已包含音频流（静音轨亦可）。

        Args:
            segments: 视频片段列表（至少 2 段）
            work_dir: 临时文件目录
            output_name: 输出文件名
            transition: 覆盖转场类型（None 用 self.transition）。
                方向性转场自动加 pad/crop 保护带，避免边缘绿色伪影。
        """
        td = self.transition_duration
        transition = transition or self.transition

        # 方向性转场：输入先加黑色保护带、输出再裁掉，
        # 转场过程中未覆盖区域显示黑色而非未初始化的绿色像素
        guard = transition in self._DIRECTIONAL_TRANSITIONS
        pad_px = self._EDGE_PAD if guard else 0

        # 探测每段时长（探测失败则中止 xfade——duration=0 会把 offset 算成 0，
        # 封面不再推后正片，而音频延迟仍按封面时长施加，音视频整体错位 1 秒）
        durations: list[float] = []
        for seg in segments:
            info = self.ffmpeg.probe_video_info(Path(seg))
            if not info or info.duration <= 0:
                raise RuntimeError(
                    f"无法探测分段时长: {seg}（xfade offset 依赖它，中止转场走 concat 回退）"
                )
            durations.append(info.duration)

        # 构建 xfade 滤镜链
        # offset 计算示例（3段，时长 d0/d1/d2，转场时长 td）：
        #   第1次 xfade: [0:v][1:v] offset=d0-td → 产出时长 d0+d1-td
        #   第2次 xfade: [v01][2:v] offset=d0+d1-td-td → 产出时长 d0+d1+d2-2*td
        inputs: list[str] = []
        for seg in segments:
            inputs += ["-i", str(seg)]

        filter_parts: list[str] = []
        # 方向性转场的保护带：每个输入 pad 后进入 xfade，最终统一裁回原尺寸
        if guard:
            for i in range(len(segments)):
                filter_parts.append(
                    f"[{i}:v]pad=iw+{pad_px*2}:ih+{pad_px*2}:"
                    f"{pad_px}:{pad_px}:black[p{i}]"
                )
        prev_label = "p0" if guard else "0:v"
        cum_duration = durations[0]
        for i in range(1, len(segments)):
            offset = max(0, cum_duration - td)
            is_last = i == len(segments) - 1
            # 最后一节：方向性转场先输出中间标签，再裁掉保护带得 [vxout]
            out_label = ("vxraw" if (is_last and guard) else
                         "vxout" if is_last else f"vx{i:02d}")
            next_input = f"p{i}" if guard else f"{i}:v"
            filter_parts.append(
                f"[{prev_label}][{next_input}]xfade=transition={transition}"
                f":duration={td}:offset={offset:.3f}[{out_label}]"
            )
            prev_label = out_label
            cum_duration = cum_duration + durations[i] - td

        # 裁掉保护带，恢复原始分辨率
        if guard:
            filter_parts.append(
                f"[vxraw]crop=iw-{pad_px*2}:ih-{pad_px*2}:{pad_px}:{pad_px}[vxout]"
            )

        # 音频 concat（xfade 不支持音频转场，音频用 concat 保持简单）
        audio_concat = "".join(f"[{i}:a]" for i in range(len(segments)))
        filter_parts.append(
            f"{audio_concat}concat=n={len(segments)}:v=0:a=1[aout]"
        )

        filter_complex = ";".join(filter_parts)
        output = work_dir / output_name
        args = inputs + [
            "-filter_complex", filter_complex,
            "-map", "[vxout]", "-map", "[aout]",
            "-c:v", self._vcodec, "-preset", self._vpreset,
            *self._vextra, "-pix_fmt", "yuv420p",
            "-r", str(self.output_fps),
            "-c:a", "aac", "-b:a", self.audio_bitrate,
            str(output),
        ]
        self.ffmpeg.run(args)
        self.logger.info(
            f"xfade 转场拼接完成: {len(segments)} 段, "
            f"transition={transition}, duration={td}s"
        )
        return output

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
        # 注意：Windows 路径中的冒号（C:）需转义为 \:，否则被 FFmpeg 当作参数分隔符
        font_path = self._find_chinese_font()
        if font_path:
            escaped_font = font_path.replace(":", "\\:")
            font_opt = f":fontfile='{escaped_font}'"
        else:
            font_opt = ""

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
            "-c:v", self._vcodec, "-preset", self._vpreset, *self._vextra, "-pix_fmt", "yuv420p",
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
                    "-c:v", self._vcodec, "-preset", self._vpreset, *self._vextra, "-pix_fmt", "yuv420p",
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
