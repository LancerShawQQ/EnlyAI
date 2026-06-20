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

        # 位置映射（画中画小窗口的左上角坐标）
        pip_w = int(w * 0.3)  # 默认画中画宽度为主视频的 30%
        pip_h = int(h * 0.3)
        position_map = {
            "top_left": (20, 20),
            "top_right": (w - pip_w - 20, 20),
            "bottom_left": (20, h - pip_h - 20),
            "bottom_right": (w - pip_w - 20, h - pip_h - 20),
            "center": ((w - pip_w) // 2, (h - pip_h) // 2),
        }

        prev_label = "base"
        for i, clip in enumerate(broll_clips, start=1):
            scale_factor = clip.get("scale", 0.3)
            clip_w = int(w * scale_factor)
            clip_h = int(h * scale_factor)
            pos = clip.get("position", "bottom_right")
            x, y = position_map.get(pos, position_map["bottom_right"])
            # 根据缩放重新计算位置（保持边距）
            if "right" in pos:
                x = w - clip_w - 20
            if "bottom" in pos:
                y = h - clip_h - 20
            start_t = clip.get("start", 0)
            end_t = clip.get("end", start_t + 3)
            volume = clip.get("volume", 0.0)

            # 缩放 B-roll 片段（支持淡入淡出转场）
            transition = clip.get("transition", "none")
            clip_dur = end_t - start_t
            if transition == "fade" and clip_dur > 0.4:
                # 淡入前 0.3s，淡出后 0.3s
                fade_in_d = min(0.3, clip_dur / 3)
                fade_out_d = min(0.3, clip_dur / 3)
                filter_parts.append(
                    f"[{i}:v]scale={clip_w}:{clip_h}:force_original_aspect_ratio=decrease,"
                    f"pad={clip_w}:{clip_h}:(ow-iw)/2:(oh-ih)/2,"
                    f"fade=t=in:st=0:d={fade_in_d:.2f},"
                    f"fade=t=out:st={clip_dur - fade_out_d:.2f}:d={fade_out_d:.2f}[clip{i}]"
                )
            else:
                filter_parts.append(
                    f"[{i}:v]scale={clip_w}:{clip_h}:force_original_aspect_ratio=decrease,"
                    f"pad={clip_w}:{clip_h}:(ow-iw)/2:(oh-ih)/2[clip{i}]"
                )
            # 叠加到主视频（仅在 start-end 时间段显示）
            filter_parts.append(
                f"[{prev_label}][clip{i}]overlay={x}:{y}:"
                f"enable='between(t,{start_t},{end_t})'[out{i}]"
            )
            prev_label = f"out{i}"

            # B-roll 音频处理（混入主视频音频）
            if volume > 0:
                filter_parts.append(
                    f"[{i}:a]volume={volume}[a{i}]"
                )

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
