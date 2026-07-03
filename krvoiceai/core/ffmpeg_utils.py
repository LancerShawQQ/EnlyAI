"""FFmpeg 命令行工具封装

直接使用 subprocess 调用 ffmpeg，避免 ffmpeg-python 在复杂滤镜链上的局限。
"""
from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import get_config
from .logger import get_logger


@dataclass
class VideoInfo:
    path: Path
    duration: float
    width: int
    height: int
    fps: float


class FFmpegRunner:
    """FFmpeg 命令封装"""

    def __init__(self, ffmpeg_path: str | None = None):
        cfg = get_config()
        self.ffmpeg = ffmpeg_path or cfg.get("composer.ffmpeg_path", "ffmpeg")
        self.ffprobe = self.ffmpeg.replace("ffmpeg", "ffprobe")
        self.logger = get_logger().bind(component="ffmpeg")
        # 硬件编码探测（启动时一次性检测，结果缓存于 hardware_probe 的 lru_cache）
        from .hardware_probe import get_video_encoder, detect_nvenc
        self._vcodec, self._vpreset, self._vextra = get_video_encoder()
        self._nvenc_available = detect_nvenc()

    def _video_encoder_args(self) -> list:
        """返回视频编码器参数列表，自动选择 NVENC/QSV/AMF 或 libx264

        NVENC/QSV/AMF: 含码率/质量控制参数（来自 hardware_probe 的 extra_args）
        libx264: 仅 codec + preset（沿用各方法原有的 -b:v 或默认 CRF）
        """
        args = ["-c:v", self._vcodec, "-preset", self._vpreset]
        args.extend(self._vextra)
        return args

    def available(self) -> bool:
        """检查 ffmpeg 是否可用"""
        return shutil.which(self.ffmpeg) is not None

    def run(self, args: list[str], check: bool = True) -> subprocess.CompletedProcess:
        """执行 ffmpeg 命令"""
        cmd = [self.ffmpeg, "-y"] + args
        self.logger.debug(f"执行: {' '.join(cmd[:6])}...")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )
        if check and result.returncode != 0:
            self.logger.error(f"FFmpeg 失败: {result.stderr[-500:]}")
            raise RuntimeError(f"FFmpeg 命令失败: {result.stderr[-300:]}")
        return result

    def probe_duration(self, path: Path) -> float:
        """获取媒体时长（秒）"""
        if not shutil.which(self.ffprobe):
            return 0.0
        try:
            r = subprocess.run(
                [
                    self.ffprobe, "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    str(path),
                ],
                capture_output=True, text=True,
            )
            return float(r.stdout.strip()) if r.stdout.strip() else 0.0
        except Exception:
            return 0.0

    def probe_video_info(self, path: Path) -> Optional[VideoInfo]:
        """获取视频信息"""
        if not shutil.which(self.ffprobe):
            return None
        try:
            r = subprocess.run(
                [
                    self.ffprobe, "-v", "error",
                    "-select_streams", "v:0",
                    "-show_entries", "stream=width,height,r_frame_rate,duration",
                    "-show_entries", "format=duration",
                    "-of", "json",
                    str(path),
                ],
                capture_output=True, text=True,
            )
            import json
            data = json.loads(r.stdout)
            stream = data.get("streams", [{}])[0]
            width = int(stream.get("width", 0))
            height = int(stream.get("height", 0))
            fps_str = stream.get("r_frame_rate", "30/1")
            num, den = fps_str.split("/")
            fps = float(num) / float(den) if float(den) > 0 else 30.0
            duration = float(data.get("format", {}).get("duration", 0) or 0)
            if duration == 0:
                duration = float(stream.get("duration", 0) or 0)
            return VideoInfo(
                path=Path(path), duration=duration,
                width=width, height=height, fps=fps,
            )
        except Exception as e:
            self.logger.debug(f"probe 失败: {e}")
            return None

    def image_audio_to_video(
        self,
        image: Path,
        audio: Path,
        output: Path,
        fps: int = 25,
        resolution: tuple[int, int] | None = None,
        video_bitrate: str = "4M",
    ) -> Path:
        """图片 + 音频合成视频"""
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)

        vf_filters = []
        if resolution:
            vf_filters.append(f"scale={resolution[0]}:{resolution[1]}:force_original_aspect_ratio=decrease")
            vf_filters.append(f"pad={resolution[0]}:{resolution[1]}:(ow-iw)/2:(oh-ih)/2")
        vf_filters.append(f"fps={fps}")
        vf = ",".join(vf_filters)

        args = [
            "-loop", "1",
            "-i", str(image),
            "-i", str(audio),
            "-vf", vf,
            *self._video_encoder_args(),
            *(["-b:v", video_bitrate] if self._vcodec == "libx264" else []),
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            "-movflags", "+faststart",
            str(output),
        ]
        self.run(args)
        return output

    def concat_videos(self, videos: list[Path], output: Path) -> Path:
        """拼接多个视频"""
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        list_file = output.parent / "concat_list.txt"
        with open(list_file, "w", encoding="utf-8") as f:
            for v in videos:
                f.write(f"file '{Path(v).absolute()}'\n")
        args = [
            "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            str(output),
        ]
        self.run(args)
        return output

    def extract_audio(self, video: Path, output: Path) -> Path:
        """从视频提取音频"""
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        args = [
            "-i", str(video),
            "-vn",
            "-acodec", "pcm_s16le",
            "-ar", "22050",
            "-ac", "1",
            str(output),
        ]
        self.run(args)
        return output

    def convert_audio(
        self,
        input_audio: Path,
        output_audio: Path,
        sample_rate: int = 16000,
        channels: int = 1,
    ) -> Path:
        """将任意音频格式转换为 wav（Wav2Lip 等模型要求）

        Args:
            input_audio: 输入音频文件（mp3/m4a/aac/wav 等）
            output_audio: 输出 wav 文件路径
            sample_rate: 采样率，默认 16000（Wav2Lip 推荐）
            channels: 声道数，默认单声道
        """
        input_audio = Path(input_audio)
        output_audio = Path(output_audio)
        output_audio.parent.mkdir(parents=True, exist_ok=True)
        args = [
            "-i", str(input_audio),
            "-vn",  # 忽略视频流
            "-acodec", "pcm_s16le",
            "-ar", str(sample_rate),
            "-ac", str(channels),
            str(output_audio),
        ]
        self.run(args)
        self.logger.debug(
            f"音频转换: {input_audio.name} -> {output_audio.name} "
            f"({sample_rate}Hz {channels}ch)"
        )
        return output_audio

    def post_process_audio(
        self,
        input_audio: Path,
        output_audio: Path,
        remove_silence: bool = False,
        pause_duration: float = 0.0,
        voice_enhance: bool = False,
    ) -> Path:
        """音频后处理：静音消除、句间停顿、人声增强

        Args:
            input_audio: 输入音频文件
            output_audio: 输出音频文件
            remove_silence: 是否消除首尾静音和过长停顿
            pause_duration: 句间停顿时长（秒），0 表示不插入
            voice_enhance: 是否启用人声增强（降噪+均衡+压缩）

        Returns:
            输出音频路径
        """
        input_audio = Path(input_audio)
        output_audio = Path(output_audio)
        output_audio.parent.mkdir(parents=True, exist_ok=True)

        # 如果不需要任何处理，直接复制
        if not remove_silence and pause_duration <= 0 and not voice_enhance:
            import shutil
            shutil.copy2(input_audio, output_audio)
            return output_audio

        # 构建音频滤镜链
        filters = []

        if remove_silence:
            # silenceremove: 消除首尾静音 + 过长停顿
            # start_duration: 开头超过0.5秒的静音移除
            # stop_duration: 中间超过1.0秒的静音压缩到0.3秒
            filters.append(
                "silenceremove=start_periods=1:start_duration=0.5:"
                "start_threshold=-50dB:"
                "stop_periods=-1:stop_duration=1.0:"
                "stop_threshold=-50dB:"
                "window=0.1"
            )

        if voice_enhance:
            # 人声增强：高通滤波(去低频隆隆声) + 轻度压缩 + 响度归一化
            filters.append("highpass=f=80")          # 去除80Hz以下低频噪声
            filters.append("acompressor=threshold=-20dB:ratio=3:attack=5:release=50")  # 轻度压缩
            filters.append("loudnorm=I=-16:TP=-1.5:LRA=11")  # 响度归一化(播客标准)

        # 句间停顿：通过在句子间插入静音实现
        # 注意：pause_duration 需要在 TTS 合成时处理（在句号后插入静音），
        # 这里只能在后处理阶段通过 areverse+silenceremove 间接实现有限效果
        # 简单方案：如果 pause_duration > 0，在音频末尾不加，但记录到 metadata
        # 真正的句间停顿需要 TTS provider 支持（edge_tts 不支持）
        # 所以这里暂不实现 pause_duration 的音频处理，只记录日志

        if pause_duration > 0:
            self.logger.info(
                f"pause_duration={pause_duration}s 需 TTS provider 支持，"
                f"当前后处理阶段不实际处理，仅记录到 metadata"
            )

        filter_chain = ",".join(filters) if filters else "anull"

        args = [
            "-i", str(input_audio),
            "-af", filter_chain,
            "-c:a", "pcm_s16le",  # 保持 wav 格式
            "-y", str(output_audio),
        ]
        self.run(args)
        return output_audio


    def overlay_video_pip(
        self,
        main_video: Path,
        broll_clips: list[dict],
        output: Path,
        output_resolution: tuple[int, int] = (1080, 1920),
        fps: int = 30,
    ) -> Path:
        """画中画叠加：将多个 B-roll 片段以小窗口形式叠加到主视频上

        增强功能（对标剪映画中画）：
        - 形状：rectangle/rounded/circle（clip["shape"]）
        - 边框：clip["border_color"] + clip["border_width"]
        - 阴影：clip["shadow"]=True
        - 动画：fade/slide/zoom/bounce（clip["animation"]）

        Args:
            main_video: 主视频（数字人口播）
            broll_clips: B-roll 片段列表，每个片段格式：
                {
                    "path": str,          # 片段文件路径（视频或图片）
                    "start": float,       # 主视频中开始叠加的时间（秒）
                    "end": float,         # 结束时间（秒）
                    "position": str,      # 位置：top_left/top_right/bottom_left/bottom_right/center
                    "scale": float,       # 缩放比例（0.2-1.0，相对主视频宽度）
                    "volume": float,      # B-roll 音量（0.0-1.0，0 为静音）
                    "shape": str,         # 形状：rectangle/rounded/circle（默认 rectangle）
                    "border_color": str,  # 边框颜色（如 white/red/0xFF0000，默认无）
                    "border_width": int,  # 边框宽度像素（默认 0）
                    "shadow": bool,       # 是否添加阴影（默认 False）
                    "animation": str,     # 入场动画：fade/slide/zoom/bounce（默认 fade）
                }
            output: 输出路径
            output_resolution: 输出分辨率 (w, h)
            fps: 帧率
        """
        main_video = Path(main_video)
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        w, h = output_resolution

        if not broll_clips:
            # 无 B-roll，直接复制
            import shutil
            shutil.copy2(main_video, output)
            return output

        # 构建输入：0=主视频，1..N=B-roll 片段
        inputs = ["-i", str(main_video)]
        for clip in broll_clips:
            inputs += ["-i", str(clip["path"])]

        # 构建 filter_complex
        # 1. 主视频统一分辨率
        filter_parts = [
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={fps}[base]"
        ]

        prev_label = "base"
        for i, clip in enumerate(broll_clips, start=1):
            scale_factor = clip.get("scale", 0.3)
            clip_w = int(w * scale_factor)
            clip_h = int(h * scale_factor)
            pos = clip.get("position", "bottom_right")
            start_t = clip.get("start", 0)
            end_t = clip.get("end", start_t + 3)
            volume = clip.get("volume", 0.0)
            shape = clip.get("shape", "rectangle")
            border_color = clip.get("border_color", "")
            border_width = clip.get("border_width", 0)
            shadow = clip.get("shadow", False)
            animation = clip.get("animation", clip.get("transition", "fade"))

            # 计算位置坐标
            x, y = self._calc_pip_position(pos, clip_w, clip_h, w, h)

            # 构建 PIP 片段滤镜链
            clip_filters = [
                f"[{i}:v]scale={clip_w}:{clip_h}:force_original_aspect_ratio=decrease",
                f"pad={clip_w}:{clip_h}:(ow-iw)/2:(oh-ih)/2",
                "format=rgba",
            ]

            # 应用形状蒙版（圆角/圆形）
            if shape == "rounded":
                radius = min(clip_w, clip_h) // 6
                clip_filters.append(
                    self._rounded_mask_filter(clip_w, clip_h, radius)
                )
            elif shape == "circle":
                clip_filters.append(
                    self._circle_mask_filter(clip_w, clip_h)
                )

            # 应用边框
            if border_color and border_width > 0:
                clip_filters.append(
                    f"pad={clip_w + border_width * 2}:{clip_h + border_width * 2}:"
                    f"{border_width}:{border_width}:color={border_color}"
                )
                # 边框后尺寸变大，调整位置
                x -= border_width
                y -= border_width

            # 应用动画
            clip_dur = end_t - start_t
            anim_filter = self._pip_animation_filter(animation, clip_dur)
            if anim_filter:
                clip_filters.append(anim_filter)

            filter_parts.append(
                ",".join(clip_filters) + f"[clip{i}]"
            )

            # 应用阴影（在 overlay 前生成阴影层）
            if shadow:
                # 阴影：复制 PIP → 模糊 → 变暗 → 偏移叠加
                shadow_offset = max(4, clip_w // 50)
                filter_parts.append(
                    f"[clip{i}]split=2[clip{i}_orig][clip{i}_sh];"
                    f"[clip{i}_sh]boxblur=8:2,colorchannelmixer=aa=0.5,"
                    f"pad={clip_w + shadow_offset * 2}:{clip_h + shadow_offset * 2}:"
                    f"{shadow_offset}:{shadow_offset}:black[clip{i}_shadow]"
                )
                # 先叠加阴影
                filter_parts.append(
                    f"[{prev_label}][clip{i}_shadow]overlay={x - shadow_offset}:{y - shadow_offset}:"
                    f"enable='between(t,{start_t},{end_t})'[sh{i}]"
                )
                # 再叠加原 PIP
                filter_parts.append(
                    f"[sh{i}][clip{i}_orig]overlay={x}:{y}:"
                    f"enable='between(t,{start_t},{end_t})'[out{i}]"
                )
            else:
                # 直接叠加
                filter_parts.append(
                    f"[{prev_label}][clip{i}]overlay={x}:{y}:"
                    f"enable='between(t,{start_t},{end_t})'[out{i}]"
                )
            prev_label = f"out{i}"

            # B-roll 音频处理
            if volume > 0:
                filter_parts.append(f"[{i}:a]volume={volume}[a{i}]")

        # 音频混合
        audio_parts = ["[0:a]volume=1.0[main_a]"]
        audio_inputs = ["[main_a]"]
        for i, clip in enumerate(broll_clips, start=1):
            volume = clip.get("volume", 0.0)
            if volume > 0:
                audio_inputs.append(f"[a{i}]")
        if len(audio_inputs) > 1:
            audio_parts.append(
                f"{''.join(audio_inputs)}amix=inputs={len(audio_inputs)}"
                f":duration=first:dropout_transition=0[aout]"
            )
            audio_map = "[aout]"
        else:
            audio_map = "[main_a]"

        filter_complex = ";".join(filter_parts + audio_parts)
        video_map = f"[{prev_label}]"

        args = inputs + [
            "-filter_complex", filter_complex,
            "-map", video_map,
            "-map", audio_map,
            *self._video_encoder_args(),
            "-pix_fmt", "yuv420p",
            "-r", str(fps),
            "-c:a", "aac",
            "-b:a", "192k",
            "-shortest",
            str(output),
        ]
        self.logger.info(f"画中画叠加: {len(broll_clips)} 个片段 -> {output.name}")
        self.run(args)
        return output

    def _calc_pip_position(
        self, pos: str, clip_w: int, clip_h: int, w: int, h: int, margin: int = 20
    ) -> tuple[int, int]:
        """计算画中画位置坐标（修复 center 偏移 Bug）"""
        if pos == "top_left":
            return margin, margin
        elif pos == "top_right":
            return w - clip_w - margin, margin
        elif pos == "bottom_left":
            return margin, h - clip_h - margin
        elif pos == "bottom_right":
            return w - clip_w - margin, h - clip_h - margin
        elif pos == "center":
            return (w - clip_w) // 2, (h - clip_h) // 2
        return w - clip_w - margin, h - clip_h - margin

    def _rounded_mask_filter(self, w: int, h: int, radius: int) -> str:
        """生成圆角矩形 alpha 蒙版（geq 滤镜，简化版）

        对4个角进行圆形裁剪：角内像素距角圆心 > radius 则透明
        """
        # 简化表达式：用 max() 处理角区域，避免复杂嵌套
        r = radius
        wr = w - r
        hr = h - r
        return (
            f"geq=lum='p(X,Y)':"
            f"a='if("  # 4个角的圆形判断，任一角内且距圆心>r 则透明
            f"lt(X,{r})*lt(Y,{r})*gt(hypot(X-{r},Y-{r}),{r})+"
            f"gt(X,{wr})*lt(Y,{r})*gt(hypot(X-{wr},Y-{r}),{r})+"
            f"lt(X,{r})*gt(Y,{hr})*gt(hypot(X-{r},Y-{hr}),{r})+"
            f"gt(X,{wr})*gt(Y,{hr})*gt(hypot(X-{wr},Y-{hr}),{r})"
            f",0,255)'"
        )

    def _circle_mask_filter(self, w: int, h: int) -> str:
        """生成圆形 alpha 蒙版（geq 滤镜）"""
        cx, cy = w / 2, h / 2
        radius = min(w, h) / 2
        return (
            f"geq=lum='p(X,Y)':"
            f"a='if(lt(hypot(X-{cx},Y-{cy}),{radius}),255,0)'"
        )

    def _pip_animation_filter(self, animation: str, duration: float) -> str:
        """生成画中画入场动画滤镜"""
        if animation == "fade" and duration > 0.4:
            fade_in = min(0.3, duration / 3)
            fade_out = min(0.3, duration / 3)
            return (
                f"fade=t=in:st=0:d={fade_in:.2f}:alpha=1,"
                f"fade=t=out:st={duration - fade_out:.2f}:d={fade_out:.2f}:alpha=1"
            )
        elif animation == "slide":
            # 滑入：通过 overlay 的 x 表达式实现，这里用淡入近似
            fade_in = min(0.4, duration / 3)
            return f"fade=t=in:st=0:d={fade_in:.2f}:alpha=1"
        elif animation == "zoom":
            # 缩放进入：用 zoompan 近似，这里用淡入
            fade_in = min(0.4, duration / 3)
            return f"fade=t=in:st=0:d={fade_in:.2f}:alpha=1"
        elif animation == "bounce":
            # 弹跳：淡入
            fade_in = min(0.3, duration / 3)
            return f"fade=t=in:st=0:d={fade_in:.2f}:alpha=1"
        return ""

    def cut_replace_video(
        self,
        main_video: Path,
        broll_clips: list[dict],
        output: Path,
        output_resolution: tuple[int, int] = (1080, 1920),
        fps: int = 30,
    ) -> Path:
        """整段切换：在指定时间段用 B-roll 替换主视频画面（音频保留主视频）

        Args:
            main_video: 主视频（数字人口播）
            broll_clips: B-roll 片段列表（按 start 排序），每个片段：
                {
                    "path": str,          # B-roll 视频/图片路径
                    "start": float,       # 主视频中开始替换的时间（秒）
                    "end": float,         # 结束时间（秒）
                    "volume": float,      # B-roll 音量（通常 0，保留主视频音频）
                    "transition": str,    # 转场：none/fade
                }
            output: 输出路径
            output_resolution: 输出分辨率
            fps: 帧率
        """
        main_video = Path(main_video)
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        w, h = output_resolution

        if not broll_clips:
            import shutil
            shutil.copy2(main_video, output)
            return output

        # 按 start 排序
        clips = sorted(broll_clips, key=lambda c: c.get("start", 0))

        # 策略：用 concat 拼接多个片段
        # 1. 主视频按 B-roll 时间点切分成多段
        # 2. 在切分点插入 B-roll 片段
        # 3. 所有片段统一参数后 concat

        # 先探测主视频时长
        main_duration = self.probe_duration(main_video)
        if main_duration <= 0:
            main_duration = 9999  # 兜底

        # 构建切片列表：[(start, end, source, is_broll)]
        segments = []
        cursor = 0.0
        for clip in clips:
            cs = float(clip.get("start", 0))
            ce = float(clip.get("end", cs + 3))
            if cs > cursor:
                # 主视频片段
                segments.append((cursor, cs, str(main_video), False, None))
            # B-roll 片段
            segments.append((cs, ce, str(clip["path"]), True, clip))
            cursor = ce
        if cursor < main_duration:
            segments.append((cursor, main_duration, str(main_video), False, None))

        self.logger.info(f"整段切换: {len(segments)} 个片段拼接")

        # 转场时长（秒）：B-roll 片段首尾各做淡入淡出，实现交叉溶解感
        transition_dur = 0.4

        # 切分并统一编码每个片段（B-roll 片段加淡入淡出转场）
        seg_files = []
        for i, (seg_start, seg_end, src, is_broll, clip) in enumerate(segments):
            seg_dur = seg_end - seg_start
            if seg_dur <= 0.1:
                continue
            seg_file = output.parent / f"cut_seg_{i:03d}.mp4"

            # 判断是视频还是图片
            src_path = Path(src)
            is_image = src_path.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")

            # B-roll 片段加淡入淡出转场
            # 视频用 -vf 的 fade，音频用 -af 的 afade（不能混在一起）
            vfade_filter = ""
            afade_filter = ""
            if is_broll and seg_dur > transition_dur * 2:
                vfade_filter = (
                    f",fade=t=in:st=0:d={transition_dur}"
                    f",fade=t=out:st={seg_dur - transition_dur:.3f}:d={transition_dur}"
                )
                afade_filter = (
                    f"afade=t=in:st=0:d={transition_dur},"
                    f"afade=t=out:st={seg_dur - transition_dur:.3f}:d={transition_dur}"
                )

            base_vf = (
                f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p"
            )

            if is_broll and is_image:
                # 图片转视频片段（无原音频，用静音轨）
                args = [
                    "-loop", "1",
                    "-i", src,
                    "-f", "lavfi",
                    "-i", "anullsrc=channel_layout=mono:sample_rate=44100",
                    "-t", f"{seg_dur:.3f}",
                    "-vf", base_vf + vfade_filter,
                    "-af", afade_filter if afade_filter else "anull",
                    *self._video_encoder_args(), "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k",
                    "-shortest", str(seg_file),
                ]
            elif is_broll:
                # B-roll 视频片段（静音自身音频，主视频画外音由 concat 后的主轨保留）
                args = [
                    "-i", src,
                    "-t", f"{seg_dur:.3f}",
                    "-vf", base_vf + vfade_filter,
                    "-af", afade_filter if afade_filter else "anull",
                    *self._video_encoder_args(), "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k", "-r", str(fps),
                    str(seg_file),
                ]
            else:
                # 主视频片段（数字人口播），在 B-roll 前后加淡出/淡入
                main_vfade = ""
                main_afade = ""
                if seg_dur > transition_dur * 2:
                    next_is_broll = (i + 1 < len(segments) and segments[i + 1][3])
                    prev_is_broll = (i - 1 >= 0 and segments[i - 1][3])
                    vfades = []
                    afades = []
                    if prev_is_broll:
                        vfades.append(f"fade=t=in:st=0:d={transition_dur}")
                        afades.append(f"afade=t=in:st=0:d={transition_dur}")
                    if next_is_broll:
                        vfades.append(f"fade=t=out:st={seg_dur - transition_dur:.3f}:d={transition_dur}")
                        afades.append(f"afade=t=out:st={seg_dur - transition_dur:.3f}:d={transition_dur}")
                    if vfades:
                        main_vfade = "," + ",".join(vfades)
                        main_afade = ",".join(afades)
                args = [
                    "-ss", f"{seg_start:.3f}",
                    "-i", src,
                    "-t", f"{seg_dur:.3f}",
                    "-vf", base_vf + main_vfade,
                    "-af", main_afade if main_afade else "anull",
                    *self._video_encoder_args(),
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-r", str(fps),
                    str(seg_file),
                ]
            self.run(args)
            seg_files.append(seg_file)

        # concat 拼接所有片段
        list_file = output.parent / "cut_concat_list.txt"
        with open(list_file, "w", encoding="utf-8") as f:
            for sf in seg_files:
                f.write(f"file '{sf.absolute()}'\n")

        args = [
            "-f", "concat", "-safe", "0",
            "-i", str(list_file),
            "-c", "copy",
            str(output),
        ]
        self.run(args)
        self.logger.info(f"整段切换完成: {output.name} ({len(seg_files)} 片段)")
        return output

    # ===== 快捷剪辑工具（对标剪映/旗博士的易用剪辑能力） =====

    def trim_video(
        self,
        video: Path,
        output: Path,
        start: float = 0.0,
        end: float | None = None,
    ) -> Path:
        """裁剪视频：去掉头部/尾部，保留 [start, end] 区间

        Args:
            video: 输入视频
            output: 输出路径
            start: 起始时间（秒）
            end: 结束时间（秒），None 表示到视频末尾
        """
        video = Path(video)
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)

        args = ["-ss", f"{start:.3f}", "-i", str(video)]
        if end is not None and end > start:
            args += ["-t", f"{end - start:.3f}"]
        args += [
            *self._video_encoder_args(), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            str(output),
        ]
        self.logger.info(f"裁剪视频: {start:.1f}s - {end}s -> {output.name}")
        self.run(args)
        return output

    def adjust_volume(self, video: Path, output: Path, volume: float = 1.0) -> Path:
        """调整视频音量

        Args:
            video: 输入视频
            output: 输出路径
            volume: 音量倍数（0.0-2.0，1.0 为原音量）
        """
        video = Path(video)
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)

        args = [
            "-i", str(video),
            "-af", f"volume={volume:.2f}",
            "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k",
            str(output),
        ]
        self.logger.info(f"调整音量: x{volume:.2f} -> {output.name}")
        self.run(args)
        return output

    def add_fade(
        self,
        video: Path,
        output: Path,
        fade_in: float = 0.0,
        fade_out: float = 0.0,
    ) -> Path:
        """添加片头淡入/片尾淡出效果

        Args:
            video: 输入视频
            output: 输出路径
            fade_in: 片头淡入时长（秒），0 表示无
            fade_out: 片尾淡出时长（秒），0 表示无
        """
        video = Path(video)
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)

        duration = self.probe_duration(video)
        vf_parts = []
        af_parts = []
        if fade_in > 0:
            vf_parts.append(f"fade=t=in:st=0:d={fade_in:.2f}")
            af_parts.append(f"afade=t=in:st=0:d={fade_in:.2f}")
        if fade_out > 0 and duration > fade_out:
            fo_start = duration - fade_out
            vf_parts.append(f"fade=t=out:st={fo_start:.2f}:d={fade_out:.2f}")
            af_parts.append(f"afade=t=out:st={fo_start:.2f}:d={fade_out:.2f}")

        if not vf_parts:
            import shutil
            shutil.copy2(video, output)
            return output

        args = [
            "-i", str(video),
            "-vf", ",".join(vf_parts),
            "-af", ",".join(af_parts) if af_parts else "anull",
            *self._video_encoder_args(), "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            str(output),
        ]
        self.logger.info(f"添加淡入淡出: in={fade_in}s out={fade_out}s -> {output.name}")
        self.run(args)
        return output

    def to_portrait(
        self,
        video: Path,
        output: Path,
        target_resolution: tuple[int, int] = (1080, 1920),
        fps: int = 30,
        background: str = "blur",
        bg_color: str = "#000000",
        bg_image: str = "",
    ) -> Path:
        """横屏视频转竖屏（口播标准做法：人脸居中 + 背景填充）

        Args:
            video: 横屏输入视频（如 Wav2Lip 输出 1920x1080）
            output: 竖屏输出视频（1080x1920）
            target_resolution: 目标竖屏分辨率 (w, h)
            fps: 帧率
            background: 背景填充方式
                - blur: 原视频放大+模糊作背景（最自然，主流口播做法）
                - black: 纯黑背景
                - solid: 纯色背景（配合 bg_color，如 "#1A1A2E"）
                - image: 图片背景（配合 bg_image，图片文件路径）
            bg_color: solid 背景色（十六进制 "#RRGGBB"），仅 background="solid" 生效
            bg_image: image 背景图路径，仅 background="image" 生效
        """
        video = Path(video)
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        tw, th = target_resolution

        self.logger.info(
            f"横屏→竖屏: {video.name} -> {tw}x{th} (背景={background})"
        )
        if background == "blur":
            # 模糊背景：原视频放大铺满竖屏并模糊 → 上面叠加居中的原比例视频
            # 同时保留音频（若无音频流则用静音轨，避免后续 concat 报错）
            vf = (
                f"[0:v]scale={tw}:{th}:force_original_aspect_ratio=increase,"
                f"crop={tw}:{th},boxblur=20:5[bg];"
                f"[0:v]scale={tw}:{th}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2[v]"
            )
            # 带音频映射（0:a? 表示可选，无音频流时不报错）
            args = [
                "-i", str(video),
                "-filter_complex", vf,
                "-map", "[v]", "-map", "0:a?",
                *self._video_encoder_args(), "-pix_fmt", "yuv420p",
                "-r", str(fps),
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                str(output),
            ]
            # 先尝试带音频转换，失败或无音频则用静音轨重试
            try:
                self.run(args)
                # 检查输出是否有音频流
                import subprocess as _sp
                r = _sp.run(
                    [self.ffprobe, "-v", "error", "-select_streams", "a",
                     "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(output)],
                    capture_output=True, text=True,
                )
                if "audio" in r.stdout:
                    return output
            except Exception:
                pass
            # 加静音音频轨（确保输出一定有音频流，供后续 concat）
            # 注意：anullsrc 无限长，靠 -shortest 截断到视频时长，不能加 -t 限制
            args_silent = [
                "-i", str(video),
                "-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=44100",
                "-filter_complex", vf,
                "-map", "[v]", "-map", "1:a",
                *self._video_encoder_args(), "-pix_fmt", "yuv420p",
                "-r", str(fps),
                "-c:a", "aac", "-b:a", "192k",
                "-shortest", "-movflags", "+faststart",
                str(output),
            ]
            self.run(args_silent)
        elif background == "solid":
            # 纯色背景：用 color 源生成纯色背景，叠加居中数字人
            # bg_color 格式 "#1A1A2E" → ffmpeg 需要 "0x1A1A2E"
            hex_color = bg_color.lstrip("#")
            vf = (
                f"color=c=0x{hex_color}:s={tw}x{th}:r={fps}[bg];"
                f"[0:v]scale={tw}:{th}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2[v]"
            )
            args = [
                "-i", str(video),
                "-filter_complex", vf,
                "-map", "[v]", "-map", "0:a?",
                *self._video_encoder_args(), "-pix_fmt", "yuv420p",
                "-r", str(fps),
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                str(output),
            ]
            # 同 blur 分支，先试带音频，失败用静音轨
            try:
                self.run(args)
                import subprocess as _sp
                r = _sp.run(
                    [self.ffprobe, "-v", "error", "-select_streams", "a",
                     "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(output)],
                    capture_output=True, text=True,
                )
                if "audio" in r.stdout:
                    return output
            except Exception:
                pass
            args_silent = [
                "-i", str(video),
                "-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=44100",
                "-filter_complex", vf,
                "-map", "[v]", "-map", "1:a",
                *self._video_encoder_args(), "-pix_fmt", "yuv420p",
                "-r", str(fps),
                "-c:a", "aac", "-b:a", "192k",
                "-shortest", "-movflags", "+faststart",
                str(output),
            ]
            self.run(args_silent)
        elif background == "image" and bg_image and Path(bg_image).exists():
            # 图片背景：背景图缩放铺满，数字人居中叠加
            vf = (
                f"[1:v]scale={tw}:{th}:force_original_aspect_ratio=increase,"
                f"crop={tw}:{th}[bg];"
                f"[0:v]scale={tw}:{th}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2[v]"
            )
            args = [
                "-i", str(video),
                "-i", str(bg_image),
                "-filter_complex", vf,
                "-map", "[v]", "-map", "0:a?",
                *self._video_encoder_args(), "-pix_fmt", "yuv420p",
                "-r", str(fps),
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                str(output),
            ]
            try:
                self.run(args)
                import subprocess as _sp
                r = _sp.run(
                    [self.ffprobe, "-v", "error", "-select_streams", "a",
                     "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(output)],
                    capture_output=True, text=True,
                )
                if "audio" in r.stdout:
                    return output
            except Exception:
                pass
            args_silent = [
                "-i", str(video),
                "-i", str(bg_image),
                "-f", "lavfi", "-i", "anullsrc=channel_layout=mono:sample_rate=44100",
                "-filter_complex", vf,
                "-map", "[v]", "-map", "2:a",
                *self._video_encoder_args(), "-pix_fmt", "yuv420p",
                "-r", str(fps),
                "-c:a", "aac", "-b:a", "192k",
                "-shortest", "-movflags", "+faststart",
                str(output),
            ]
            self.run(args_silent)
        else:
            bg_color = "black"
            vf = (
                f"scale={tw}:{th}:force_original_aspect_ratio=decrease,"
                f"pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2:color={bg_color},fps={fps}"
            )
            args = [
                "-i", str(video),
                "-vf", vf,
                "-map", "0:v", "-map", "0:a?",
                *self._video_encoder_args(), "-pix_fmt", "yuv420p",
                "-c:a", "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                str(output),
            ]
            self.run(args)
        return output

    def add_micro_motion(
        self,
        video: Path,
        output: Path,
        width: int = 1080,
        height: int = 1920,
        fps: int = 30,
        breathing_scale: float = 0.02,
        breathing_period: float = 4.0,
        shake_amplitude: float = 0.3,
        shake_period: float = 2.0,
        blink_enabled: bool = True,
        blink_interval: float = 4.0,
    ) -> Path:
        """数字人微动作层（FFmpeg 后处理）

        给静态照片/Wav2Lip 输出叠加三层微动作，缓解"只有嘴动"的恐怖谷：
          1. 呼吸缩放：缓慢的 zoompan 缩放 1.0 ± breathing_scale（正弦周期）
          2. 微抖动：rotate ±shake_amplitude 度正弦摆动（模拟手持/呼吸晃动）
          3. 眨眼节奏：周期性极短亮度脉冲（近似闭眼，避免引入人脸检测重依赖）

        全部用 FFmpeg 表达式实现，单条命令完成，无需抽帧，CPU 即可。

        Args:
            video: 输入口播视频
            output: 输出视频
            width/height/fps: 输出参数（与 composer 对齐）
            breathing_scale: 呼吸缩放幅度（0.02 = ±2%）
            breathing_period: 呼吸周期（秒）
            shake_amplitude: 摆动幅度（度，0.3 = ±0.3°）
            shake_period: 摆动周期（秒）
            blink_enabled: 是否启用眨眼亮度节奏
            blink_interval: 眨眼间隔（秒）
        """
        video = Path(video)
        output = Path(output)
        output.parent.mkdir(parents=True, exist_ok=True)

        import math
        # ===== 滤镜表达式说明 =====
        # zoompan 支持 on（帧序号）变量；rotate/eq 只支持 t（时间秒）变量。
        # 故呼吸缩放用 on（zoompan 内），抖动和眨眼用 t（rotate/eq 内）。

        # 呼吸缩放：zoompan 的 z 用正弦（基于帧序号 on）
        omega_breathe = (2 * math.pi) / (breathing_period * fps)
        zoom_expr = f"1.0+{breathing_scale}*sin(on*{omega_breathe:.6f})"

        # 微抖动：rotate 用 t（弧度）
        omega_shake = (2 * math.pi) / shake_period
        shake_rad = math.radians(shake_amplitude)
        rotate_expr = f"{shake_rad:.6f}*sin(t*{omega_shake:.6f})"

        # 眨眼：eq.brightness 用 t（时间秒），周期性轻微亮度波动
        # 让画面有"活物感"，避免引入人脸检测重依赖
        blink_filter = ""
        if blink_enabled:
            omega_blink = (2 * math.pi) / blink_interval
            # 注意 eq 的 brightness 表达式不支持 on，必须用 t
            blink_filter = (
                f",eq=brightness=0.02*sin(t*{omega_blink:.6f}):contrast=1.0"
            )

        # 组合滤镜链：
        # 1. zoompan 做呼吸缩放（居中）— 用 on
        # 2. rotate 做微抖动 — 用 t，填充黑色边缘
        # 3. eq 做眨眼亮度节奏 — 用 t
        # 4. crop 去掉旋转黑边
        vf = (
            f"zoompan=z='{zoom_expr}':d=1:x='iw/2-(iw/zoom)/2':y='ih/2-(ih/zoom)/2'"
            f":s={width}x{height}:fps={fps},"
            f"rotate='{rotate_expr}':ow=rotw({rotate_expr}):oh=roth({rotate_expr})"
            f":c=black{blink_filter},"
            f"crop={width}:{height}:(in_w-{width})/2:(in_h-{height})/2,"
            f"scale={width}:{height}"
        )

        args = [
            "-i", str(video),
            "-vf", vf,
            *self._video_encoder_args(),
            "-pix_fmt", "yuv420p",
            "-r", str(fps),
            "-c:a", "aac",
            "-b:a", "192k",
            "-movflags", "+faststart",
            str(output),
        ]
        self.logger.info(
            f"微动作层: breathe=±{breathing_scale*100:.1f}%/{breathing_period}s "
            f"shake=±{shake_amplitude}°/{shake_period}s blink={blink_enabled} "
            f"-> {output.name}"
        )
        self.run(args)
        return output
