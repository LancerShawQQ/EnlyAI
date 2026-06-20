"""B-roll 画中画/插播视频模块

支持两种模式（对标剪映画中画 + HeyGen 场景切换）：
- pip:  画中画模式，B-roll 以小窗口叠加在数字人口播视频上（数字人仍可见）
- cut:  整段切换模式，在指定时间段用 B-roll 替换主画面（数字人暂离，音频保留）

用户通过时间轴编辑器插入 B-roll 片段，每个片段包含：
- path:      视频/图片文件路径
- start:     主视频中开始叠加/替换的时间（秒）
- end:       结束时间（秒）
- mode:      pip / cut
- position:  画中画位置（pip 模式）：top_left/top_right/bottom_left/bottom_right/center
- scale:     画中画缩放（pip 模式）：0.2-1.0
- volume:    B-roll 音量：0.0-1.0（cut 模式通常为 0，保留主视频音频）
- transition: 转场效果：none/fade

输出：叠加 B-roll 后的视频 mp4
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from ..core.base_module import BaseModule, JobContext, ModuleResult
from ..core.ffmpeg_utils import FFmpegRunner


class BRollEngine(BaseModule):
    """B-roll 画中画/插播视频模块"""

    name = "broll"
    requires_gpu = False

    def __init__(self, config=None, ffmpeg: FFmpegRunner | None = None):
        super().__init__(config)
        self.ffmpeg = ffmpeg or FFmpegRunner()
        self.output_fps = self.config.get("composer.output_fps", 30)
        res = self.config.get("composer.output_resolution", [1080, 1920])
        self.output_resolution = tuple(res) if isinstance(res, list) else (1080, 1920)

    def setup(self) -> None:
        if not self.ffmpeg.available():
            raise RuntimeError("FFmpeg 不可用，B-roll 模块无法工作")
        self.logger.info("B-roll 画中画模块初始化完成")
        super().setup()

    def run(self, ctx: JobContext) -> ModuleResult:
        """根据 ctx.broll_clips 将 B-roll 叠加到口播视频上"""
        # 无 B-roll 片段时跳过
        if not ctx.broll_clips:
            self.logger.info("无 B-roll 片段，跳过")
            return ModuleResult(
                success=True,
                data={"skipped": True, "reason": "no broll clips"},
            )

        if not ctx.raw_video_path or not ctx.raw_video_path.exists():
            return ModuleResult(success=False, error="无口播视频，无法叠加 B-roll")

        # 校验所有 B-roll 文件存在
        valid_clips = []
        for clip in ctx.broll_clips:
            clip_path = Path(clip.get("path", ""))
            if not clip_path.exists():
                self.logger.warning(f"B-roll 片段文件不存在，跳过: {clip_path}")
                continue
            valid_clips.append(clip)

        if not valid_clips:
            self.logger.info("无有效 B-roll 片段，跳过")
            return ModuleResult(
                success=True,
                data={"skipped": True, "reason": "no valid clips"},
            )

        output_path = ctx.work_dir / "broll_video.mp4"

        try:
            start = time.time()
            # 按 mode 分组处理
            pip_clips = [c for c in valid_clips if c.get("mode", "pip") == "pip"]
            cut_clips = [c for c in valid_clips if c.get("mode", "pip") == "cut"]

            self.logger.info(
                f"B-roll 处理: {len(pip_clips)} 个画中画 + {len(cut_clips)} 个整段切换"
            )

            current_video = ctx.raw_video_path

            # 先处理整段切换（改变视频结构）
            if cut_clips:
                cut_output = ctx.work_dir / "broll_cut.mp4"
                current_video = self.ffmpeg.cut_replace_video(
                    main_video=current_video,
                    broll_clips=cut_clips,
                    output=cut_output,
                    output_resolution=self.output_resolution,
                    fps=self.output_fps,
                )

            # 再处理画中画叠加（在切换后的视频上叠加小窗口）
            if pip_clips:
                pip_output = ctx.work_dir / "broll_pip.mp4"
                current_video = self.ffmpeg.overlay_video_pip(
                    main_video=current_video,
                    broll_clips=pip_clips,
                    output=pip_output,
                    output_resolution=self.output_resolution,
                    fps=self.output_fps,
                )

            # 最终输出
            if current_video != output_path:
                import shutil
                shutil.copy2(current_video, output_path)

            ctx.broll_video_path = output_path
            # 合成模块应使用叠加后的视频
            ctx.raw_video_path = output_path

            info = self.ffmpeg.probe_video_info(output_path)
            duration = info.duration if info else 0

            elapsed = time.time() - start
            self.logger.info(
                f"B-roll 叠加完成: {output_path.name} "
                f"({output_path.stat().st_size // 1024}KB, {elapsed:.1f}s)"
            )

            return ModuleResult(
                success=True,
                data={
                    "broll_video": str(output_path),
                    "duration": duration,
                    "pip_count": len(pip_clips),
                    "cut_count": len(cut_clips),
                    "elapsed": elapsed,
                },
            )
        except Exception as e:
            return ModuleResult(success=False, error=str(e))

    def apply_broll_to_existing_video(
        self,
        video_path: Path,
        broll_clips: list[dict],
        output_path: Path | None = None,
    ) -> Path:
        """对已有视频应用 B-roll（供 API 单独调用，不经过流水线）

        Args:
            video_path: 输入视频
            broll_clips: B-roll 片段列表
            output_path: 输出路径（默认与输入同目录）
        """
        video_path = Path(video_path)
        output_path = Path(output_path) if output_path else video_path.parent / "broll_output.mp4"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        valid_clips = [c for c in broll_clips if Path(c.get("path", "")).exists()]
        if not valid_clips:
            import shutil
            shutil.copy2(video_path, output_path)
            return output_path

        pip_clips = [c for c in valid_clips if c.get("mode", "pip") == "pip"]
        cut_clips = [c for c in valid_clips if c.get("mode", "pip") == "cut"]

        current = video_path
        if cut_clips:
            cut_out = output_path.parent / "broll_cut.mp4"
            current = self.ffmpeg.cut_replace_video(
                main_video=current,
                broll_clips=cut_clips,
                output=cut_out,
                output_resolution=self.output_resolution,
                fps=self.output_fps,
            )
        if pip_clips:
            pip_out = output_path.parent / "broll_pip.mp4"
            current = self.ffmpeg.overlay_video_pip(
                main_video=current,
                broll_clips=pip_clips,
                output=pip_out,
                output_resolution=self.output_resolution,
                fps=self.output_fps,
            )
        if current != output_path:
            import shutil
            shutil.copy2(current, output_path)
        return output_path
