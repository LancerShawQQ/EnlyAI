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
            "-c:v", "libx264",
            "-preset", "medium",
            "-b:v", video_bitrate,
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
            "-c:v", "libx264",
            "-preset", "medium",
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

        # 切分并统一编码每个片段
        seg_files = []
        for i, (seg_start, seg_end, src, is_broll, clip) in enumerate(segments):
            seg_dur = seg_end - seg_start
            if seg_dur <= 0.1:
                continue
            seg_file = output.parent / f"cut_seg_{i:03d}.mp4"

            # 判断是视频还是图片
            src_path = Path(src)
            is_image = src_path.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")

            if is_broll and is_image:
                # 图片转视频片段
                args = [
                    "-loop", "1",
                    "-i", src,
                    "-f", "lavfi",
                    "-i", "anullsrc=channel_layout=mono:sample_rate=44100",
                    "-t", f"{seg_dur:.3f}",
                    "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                           f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p",
                    "-c:v", "libx264",
                    "-preset", "medium",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-shortest",
                    str(seg_file),
                ]
            elif is_broll:
                # B-roll 视频片段，截取指定时长
                args = [
                    "-i", src,
                    "-t", f"{seg_dur:.3f}",
                    "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                           f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p",
                    "-c:v", "libx264",
                    "-preset", "medium",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac",
                    "-b:a", "192k",
                    "-r", str(fps),
                    str(seg_file),
                ]
            else:
                # 主视频片段，截取指定时间段
                args = [
                    "-ss", f"{seg_start:.3f}",
                    "-i", src,
                    "-t", f"{seg_dur:.3f}",
                    "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
                           f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,fps={fps},format=yuv420p",
                    "-c:v", "libx264",
                    "-preset", "medium",
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
            "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p",
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
            "-c:v", "libx264", "-preset", "medium", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k",
            str(output),
        ]
        self.logger.info(f"添加淡入淡出: in={fade_in}s out={fade_out}s -> {output.name}")
        self.run(args)
        return output
