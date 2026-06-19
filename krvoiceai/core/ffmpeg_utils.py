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
