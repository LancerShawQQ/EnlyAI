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
        from ..core.config import PROJECT_ROOT
        valid_clips = []
        for clip in ctx.broll_clips:
            # 兼容前端 asset_path 和后端 path 两种字段名
            clip_path_str = clip.get("path") or clip.get("asset_path") or ""
            if not clip_path_str:
                self.logger.warning(f"B-roll 片段缺少 path/asset_path 字段，跳过: {clip}")
                continue
            clip_path = Path(clip_path_str)
            # 相对路径基于项目根目录解析（前端传的是 config/broll_assets/xxx 相对路径）
            if not clip_path.is_absolute():
                clip_path = (PROJECT_ROOT / clip_path_str).resolve()
            if not clip_path.exists():
                self.logger.warning(f"B-roll 片段文件不存在，跳过: {clip_path}")
                continue
            # 统一字段名，供后续 FFmpeg 处理使用
            clip["path"] = str(clip_path)
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
            # mode 默认为 cut（整段画面替换，对标旗博士/剪映的 B-roll 插播）
            #   cut: 指定时间段全屏替换为 B-roll 画面，数字人被遮挡，保留画外音
            #   pip: 右上角小窗叠加（数字人仍全屏可见）
            pip_clips = [c for c in valid_clips if c.get("mode", "cut") == "pip"]
            cut_clips = [c for c in valid_clips if c.get("mode", "cut") == "cut"]

            self.logger.info(
                f"B-roll 处理: {len(cut_clips)} 个整段插播 + {len(pip_clips)} 个画中画小窗"
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

        # 校验 B-roll 片段：兼容 asset_path/path 字段名 + 解析相对路径
        from ..core.config import PROJECT_ROOT
        valid_clips = []
        for clip in broll_clips:
            clip_path_str = clip.get("path") or clip.get("asset_path") or ""
            if not clip_path_str:
                continue
            clip_path = Path(clip_path_str)
            if not clip_path.is_absolute():
                clip_path = (PROJECT_ROOT / clip_path_str).resolve()
            if not clip_path.exists():
                continue
            clip["path"] = str(clip_path)
            valid_clips.append(clip)
        if not valid_clips:
            import shutil
            shutil.copy2(video_path, output_path)
            return output_path

        pip_clips = [c for c in valid_clips if c.get("mode", "cut") == "pip"]
        cut_clips = [c for c in valid_clips if c.get("mode", "cut") == "cut"]

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

    # ============ B-roll 智能插入（对标剪映智能匹配素材） ============

    def suggest_broll_clips(
        self,
        script: str,
        subtitle_segments: list[dict],
        assets: list[dict],
        video_duration: float = 0.0,
        max_clips: int = 5,
    ) -> list[dict]:
        """基于文案语义 + 字幕时间戳 + 素材库，智能推荐 B-roll 插入点

        Args:
            script: 完整文案
            subtitle_segments: 字幕片段 [{"text":..., "start":..., "end":...}, ...]
            assets: 素材库 [{"filename":..., "path":..., "kind":"video|image"}, ...]
            video_duration: 视频总时长（秒），用于约束推荐时间点
            max_clips: 最多推荐数量

        Returns:
            推荐片段列表，每项与 broll_clips schema 一致，额外含 reason 字段
        """
        from ..core.llm_client import LLMClient

        if not assets:
            return []
        if not subtitle_segments:
            subtitle_segments = []

        # 末尾时间兜底
        if not video_duration and subtitle_segments:
            video_duration = subtitle_segments[-1].get("end", 0)

        # 构造素材清单（精简，避免 prompt 过长）
        asset_list = "\n".join(
            f'- {i+1}. "{a.get("filename", "")}" ({a.get("kind", "video")})'
            for i, a in enumerate(assets)
        )
        # 构造字幕清单（带时间戳）
        sub_list = "\n".join(
            f'- [{seg.get("start",0):.1f}-{seg.get("end",0):.1f}s] {seg.get("text","")}'
            for seg in subtitle_segments[:60]  # 限制长度避免 prompt 爆炸
        )

        prompt = f"""你是视频 B-roll 智能匹配助手。请根据以下信息推荐最多 {max_clips} 个 B-roll 插入点。

【文案】
{script[:1500]}

【字幕时间戳】
{sub_list}

【可用素材库】
{asset_list}

【视频总时长】{video_duration:.1f} 秒

【推荐规则】
1. 分析文案语义，找出适合插入 B-roll 的场景点（如提到产品、场景、数据、动作、地点时）
2. 从可用素材库中选择最匹配的素材（基于文件名语义推断）
3. 对齐到字幕时间戳确定插入时间点，start/end 必须在 [0, {video_duration:.1f}] 内
4. 模式选择：展示实景/产品用 cut（整段切换），补充信息/旁白用 pip（画中画小窗）
5. 每个推荐需给出合理理由

请返回严格的 JSON 数组（不要任何额外文字、不要 markdown 代码块），每个元素格式：
{{"path":"素材完整路径","start":数字,"end":数字,"mode":"cut或pip","position":"top_right","scale":0.35,"volume":0,"transition":"fade","reason":"推荐理由"}}

若无合适插入点，返回空数组 []。"""

        llm = LLMClient()
        if llm.is_mock:
            # Mock 模式降级：基于字幕间隙的规则推荐（轮流分配素材）
            self.logger.info("LLM 处于 mock 模式，B-roll 智能推荐降级为规则匹配")
            return self._suggest_broll_by_rules(
                subtitle_segments, assets, video_duration, max_clips
            )
        try:
            resp = llm.chat(
                messages=[
                    {"role": "system", "content": "你是专业的视频 B-roll 智能匹配助手，只返回 JSON。"},
                    {"role": "user", "content": prompt},
                ],
                temperature=0.3,
                max_tokens=1500,
            )
        except Exception as e:
            self.logger.warning(f"LLM 调用失败，降级为规则匹配: {e}")
            return self._suggest_broll_by_rules(
                subtitle_segments, assets, video_duration, max_clips
            )

        # 解析 JSON（兼容 markdown 包裹）
        import json as _json
        import re as _re
        text = resp.strip()
        # 去除可能的 ```json ... ``` 包裹
        m = _re.search(r"```(?:json)?\s*(.+?)```", text, _re.DOTALL)
        if m:
            text = m.group(1).strip()
        try:
            suggestions = _json.loads(text)
        except _json.JSONDecodeError:
            self.logger.warning(f"LLM 返回非 JSON，降级为规则匹配: {text[:200]}")
            return self._suggest_broll_by_rules(
                subtitle_segments, assets, video_duration, max_clips
            )

        if not isinstance(suggestions, list):
            # LLM 返回非列表，走规则降级
            self.logger.warning("LLM 返回非列表，降级为规则匹配")
            return self._suggest_broll_by_rules(
                subtitle_segments, assets, video_duration, max_clips
            )

        # LLM 返回空数组时，走规则降级（确保用户总能看到推荐，对标剪映总会有建议）
        if not suggestions:
            self.logger.info("LLM 返回空推荐，降级为规则匹配（基于字幕间隙）")
            return self._suggest_broll_by_rules(
                subtitle_segments, assets, video_duration, max_clips
            )

        # 校验并修正每个推荐
        valid_path_set = {a.get("path", "") for a in assets}
        valid_filename_set = {a.get("filename", "") for a in assets}
        path_by_filename = {a.get("filename", ""): a.get("path", "") for a in assets}

        result = []
        for s in suggestions[:max_clips]:
            if not isinstance(s, dict):
                continue
            # 路径校验：优先用 path，否则用 filename 反查
            path = s.get("path", "")
            if path not in valid_path_set:
                # 尝试当作 filename 处理
                path = path_by_filename.get(path, "")
            if not path:
                continue
            # 时间校验
            start = float(s.get("start", 0))
            end = float(s.get("end", start + 2))
            if video_duration > 0:
                start = max(0, min(start, video_duration - 0.5))
                end = max(start + 0.5, min(end, video_duration))
            if end <= start:
                continue
            mode = s.get("mode", "cut")
            if mode not in ("cut", "pip"):
                mode = "cut"
            clip = {
                "path": path,
                "filename": Path(path).name,
                "start": round(start, 2),
                "end": round(end, 2),
                "mode": mode,
                "position": s.get("position", "top_right"),
                "scale": float(s.get("scale", 0.35)) if mode == "pip" else 1.0,
                "volume": float(s.get("volume", 0)),
                "transition": s.get("transition", "fade"),
                "reason": s.get("reason", ""),
            }
            result.append(clip)

        self.logger.info(f"B-roll 智能推荐: 输入 {len(assets)} 素材，生成 {len(result)} 个推荐")
        return result

    def _suggest_broll_by_rules(
        self,
        subtitle_segments: list[dict],
        assets: list[dict],
        video_duration: float,
        max_clips: int,
    ) -> list[dict]:
        """规则降级推荐：基于字幕间隙轮流分配素材（LLM 不可用时使用）

        策略：找出字幕间隙（>0.8s 的停顿），在间隙处插入 B-roll；
        素材按顺序轮流分配，前两个用 cut，之后用 pip。
        """
        if not assets or not subtitle_segments:
            # 无字幕时，在视频前 1/3 和 2/3 处各插一个
            if not video_duration:
                return []
            positions = [video_duration * 0.25, video_duration * 0.6]
            result = []
            for i, t in enumerate(positions[:max_clips]):
                a = assets[i % len(assets)]
                result.append({
                    "path": a.get("path", ""),
                    "filename": Path(a.get("path", "")).name,
                    "start": round(t, 2),
                    "end": round(min(t + 2.5, video_duration), 2),
                    "mode": "cut" if i == 0 else "pip",
                    "position": "top_right",
                    "scale": 0.35,
                    "volume": 0.0,
                    "transition": "fade",
                    "reason": "规则推荐：视频关键时间点插入（LLM 不可用时的降级方案）",
                })
            return result

        # 找字幕间隙
        gaps = []
        for i in range(len(subtitle_segments) - 1):
            cur_end = float(subtitle_segments[i].get("end", 0))
            next_start = float(subtitle_segments[i + 1].get("start", 0))
            gap = next_start - cur_end
            if gap >= 0.8:
                gaps.append((cur_end, next_start, gap, subtitle_segments[i].get("text", "")))

        # 无明显间隙时，在每段字幕中段插入（用 pip 模式不遮挡数字人）
        if not gaps:
            gaps = []
            for seg in subtitle_segments[::3][:max_clips]:  # 每隔3段取一个
                mid = (float(seg.get("start", 0)) + float(seg.get("end", 0))) / 2
                gaps.append((mid, mid + 1.5, 1.5, seg.get("text", "")))

        result = []
        for i, (g_start, g_end, g_dur, seg_text) in enumerate(gaps[:max_clips]):
            a = assets[i % len(assets)]
            mode = "cut" if i < 2 else "pip"
            # cut 模式用整个间隙，pip 模式限制 2s
            if mode == "cut":
                start, end = g_start, g_end
            else:
                start, end = g_start, min(g_start + 2.0, g_end)
            result.append({
                "path": a.get("path", ""),
                "filename": Path(a.get("path", "")).name,
                "start": round(start, 2),
                "end": round(end, 2),
                "mode": mode,
                "position": "top_right",
                "scale": 0.35,
                "volume": 0.0,
                "transition": "fade",
                "reason": f"规则推荐：字幕间隙插入（停顿 {g_dur:.1f}s，前文：{seg_text[:20]}）",
            })

        self.logger.info(f"B-roll 规则推荐：找到 {len(gaps)} 个字幕间隙，生成 {len(result)} 个推荐")
        return result
