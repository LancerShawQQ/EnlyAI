"""字幕生成模块

两种 provider：
- funasr: 调用 FunASR 服务（本地 HTTP API）进行语音识别 + 时间戳对齐
- mock:   优先复用 TTS 时间戳，否则按文本长度估算

输出：SRT 格式字幕文件
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import httpx

from ..core.audio_utils import estimate_speech_duration, split_text_to_segments
from ..core.base_module import BaseModule, JobContext, ModuleResult


def format_srt_time(seconds: float) -> str:
    """秒数转 SRT 时间格式 HH:MM:SS,mmm"""
    if seconds < 0:
        seconds = 0
    # 用 round 避免浮点精度问题（如 3661.999 -> 998）
    ms = round((seconds % 1) * 1000)
    if ms >= 1000:  # 四舍五入进位
        ms = 0
        seconds += 1
    s = int(seconds)
    h = s // 3600
    m = (s % 3600) // 60
    sec = s % 60
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def segments_to_srt(segments: list[dict]) -> str:
    """将分句时间戳列表转为 SRT 字符串"""
    lines: list[str] = []
    for i, seg in enumerate(segments, 1):
        start = format_srt_time(seg["start"])
        end = format_srt_time(seg["end"])
        text = seg["text"].strip()
        lines.append(str(i))
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")  # 空行分隔
    return "\n".join(lines).rstrip("\n") + "\n"


class SubtitleEngine(BaseModule):
    """字幕生成模块"""

    name = "subtitle"
    requires_gpu = False  # FunASR CPU 也可跑

    def __init__(self, config=None):
        super().__init__(config)
        self.provider = self.config.get("asr.provider", "mock")
        self.model = self.config.get("asr.model", "paraformer-zh")
        self.language = self.config.get("asr.language", "zh")
        self.max_chars = self.config.get("asr.subtitle.max_chars_per_line", 18)

    def setup(self) -> None:
        if self.provider == "funasr":
            # 检查 FunASR 是否可用（尝试 import）
            try:
                import funasr  # noqa: F401
                self._funasr_available = True
                self.logger.info("FunASR 本地可用")
            except ImportError:
                self._funasr_available = False
                self.logger.warning(
                    "FunASR 未安装，降级到 mock 模式（使用 TTS 时间戳）"
                )
                self.provider = "mock"
        else:
            self._funasr_available = False
        self.logger.info(f"字幕模块初始化 provider={self.provider}")
        super().setup()

    def run(self, ctx: JobContext) -> ModuleResult:
        """根据音频生成字幕"""
        if not ctx.audio_path or not ctx.audio_path.exists():
            return ModuleResult(success=False, error="无音频文件，无法生成字幕")

        output_path = ctx.work_dir / "subtitle.srt"

        try:
            if self.provider == "funasr" and self._funasr_available:
                segments = self._recognize_funasr(ctx)
            else:
                segments = self._generate_mock(ctx)

            srt_content = segments_to_srt(segments)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(srt_content, encoding="utf-8")

            ctx.subtitle_path = output_path
            ctx.metadata["subtitle_segments"] = segments

            return ModuleResult(
                success=True,
                data={
                    "subtitle_path": str(output_path),
                    "segment_count": len(segments),
                    "provider": self.provider,
                },
            )
        except Exception as e:
            return ModuleResult(success=False, error=str(e))

    def _recognize_funasr(self, ctx: JobContext) -> list[dict]:
        """使用 FunASR 识别音频并生成带时间戳的分句"""
        self.logger.info(f"FunASR 识别音频: {ctx.audio_path}")
        from funasr import AutoModel

        model = AutoModel(
            model=self.model,
            vad_model="fsmn-vad",
            punc_model="ct-punc",
            disable_update=True,
        )

        result = model.generate(
            input=str(ctx.audio_path),
            batch_size_s=300,
            sentence_timestamp=True,
        )

        segments: list[dict] = []
        for res in result:
            sentence_list = res.get("sentence_info", [])
            if sentence_list:
                for s in sentence_list:
                    text = s.get("text", "").strip()
                    if text:
                        # 长句切分
                        if len(text) > self.max_chars:
                            sub_segs = split_text_to_segments(text, self.max_chars)
                            total_dur = s.get("end", 0) - s.get("start", 0)
                            for j, sub in enumerate(sub_segs):
                                sub_start = s.get("start", 0) + j * total_dur / len(sub_segs)
                                sub_end = s.get("start", 0) + (j + 1) * total_dur / len(sub_segs)
                                segments.append({
                                    "text": sub,
                                    "start": round(sub_start / 1000, 3),
                                    "end": round(sub_end / 1000, 3),
                                })
                        else:
                            segments.append({
                                "text": text,
                                "start": round(s.get("start", 0) / 1000, 3),
                                "end": round(s.get("end", 0) / 1000, 3),
                            })
            else:
                # 无 sentence_info，用纯文本
                text = res.get("text", "").strip()
                if text:
                    segments.extend(self._split_text_by_duration(
                        text, ctx.audio_duration
                    ))

        self.logger.info(f"FunASR 识别完成，{len(segments)} 条字幕")
        return segments

    def _generate_mock(self, ctx: JobContext) -> list[dict]:
        """Mock 模式：优先复用 TTS 时间戳，否则按文本估算"""
        # 优先使用 TTS 模块生成的时间戳
        tts_ts = ctx.metadata.get("tts_timestamps")
        if tts_ts:
            self.logger.info(f"复用 TTS 时间戳生成字幕，{len(tts_ts)} 条")
            # 按最大字数切分过长的段
            segments: list[dict] = []
            for ts in tts_ts:
                text = ts["text"]
                if len(text) > self.max_chars:
                    sub_segs = split_text_to_segments(text, self.max_chars)
                    dur = ts["end"] - ts["start"]
                    for j, sub in enumerate(sub_segs):
                        s = ts["start"] + j * dur / len(sub_segs)
                        e = ts["start"] + (j + 1) * dur / len(sub_segs)
                        segments.append({
                            "text": sub,
                            "start": round(s, 3),
                            "end": round(e, 3),
                        })
                else:
                    segments.append(ts)
            return segments

        # 否则按文案文本估算
        text = ctx.script_text or ctx.input_script
        if not text:
            return [{
                "text": "（无文案）",
                "start": 0.0,
                "end": ctx.audio_duration,
            }]

        self.logger.info("按文本长度估算字幕时间戳")
        return self._split_text_by_duration(text, ctx.audio_duration)

    def _split_text_by_duration(
        self, text: str, total_duration: float
    ) -> list[dict]:
        """按文本切分并按字数比例分配时长"""
        segments = split_text_to_segments(text, self.max_chars)
        total_chars = sum(len(s) for s in segments) or 1
        result: list[dict] = []
        offset = 0.0
        for seg in segments:
            seg_dur = total_duration * len(seg) / total_chars
            result.append({
                "text": seg,
                "start": round(offset, 3),
                "end": round(offset + seg_dur, 3),
            })
            offset += seg_dur
        return result
