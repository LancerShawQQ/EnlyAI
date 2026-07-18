"""字幕生成模块

四种 provider：
- whisper_local: 使用 faster-whisper（CPU int8）识别，提供词级时间戳（本地推荐）
- mimo:   调用小米 MiMo ASR API（OpenAI 兼容 chat/completions 端点）
- funasr: 调用 FunASR 服务（本地 HTTP API）进行语音识别 + 时间戳对齐
- mock:   优先复用 TTS 时间戳，否则按文本长度估算

输出：SRT 格式字幕文件（segment 可携带 words 词级时间戳，供 ASS 卡拉OK逐字高亮使用）
"""
from __future__ import annotations

import base64
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
        # MiMo ASR 配置
        self.mimo_api_base = self.config.get("asr.api_base", "")
        self.mimo_api_key = self.config.get("asr.api_key", "")
        self.mimo_model = self.config.get("asr.mimo_model", "mimo-v2.5-asr")
        self.timeout = self.config.get("asr.timeout", 120)
        # faster-whisper 本地配置
        self.whisper_cfg = self.config.get("asr.whisper", {}) or {}
        self._whisper_available = False

    def setup(self) -> None:
        if self.provider == "whisper_local":
            # 检查 faster-whisper 是否可用
            try:
                import faster_whisper  # noqa: F401
                self._whisper_available = True
                self.logger.info(
                    f"faster-whisper 本地可用 model_size={self.whisper_cfg.get('model_size','small')} "
                    f"device={self.whisper_cfg.get('device','cpu')}"
                )
            except ImportError:
                self._whisper_available = False
                self.logger.warning(
                    "faster-whisper 未安装，降级到 mock 模式（词级时间戳不可用）。"
                    "安装方法：pip install -e \".[local]\""
                )
                self.provider = "mock"
        elif self.provider == "mimo":
            if not self.mimo_api_key or not self.mimo_api_base:
                self.logger.warning(
                    "MiMo ASR 未配置 api_key/api_base，降级到 mock 模式"
                )
                self.provider = "mock"
            else:
                self.logger.info(f"MiMo ASR 模式 model={self.mimo_model}")
        elif self.provider == "funasr":
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
            if self.provider == "whisper_local" and self._whisper_available:
                segments = self._recognize_whisper(ctx)
            elif self.provider == "mimo":
                segments = self._recognize_mimo(ctx)
            elif self.provider == "funasr" and self._funasr_available:
                segments = self._recognize_funasr(ctx)
            else:
                segments = self._generate_mock(ctx)

            # 用 TTS 时间戳补全 ASR 可能丢失的开头内容
            # 场景：whisper VAD 过滤了前几秒音频，导致开头字幕缺失
            segments = self._fill_missing_head_with_tts(segments, ctx)

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

    def _recognize_whisper(self, ctx: JobContext) -> list[dict]:
        """使用 faster-whisper 识别音频，提供词级时间戳（本地 CPU int8）

        faster-whisper 优势：
        - 词级时间戳（word_timestamps=True），驱动 ASS 卡拉OK逐字高亮
        - CPU int8 量化，MX450 2GB 显存也能跑
        - 内置 VAD 静音过滤，字幕对齐更精准

        输出 segment 结构（携带 words 字段）：
            {"text": "...", "start": 0.0, "end": 2.5,
             "words": [{"text": "字", "start": 0.0, "end": 0.2}, ...]}
        """
        from faster_whisper import WhisperModel

        model_size = self.whisper_cfg.get("model_size", "small")
        device = self.whisper_cfg.get("device", "cpu")
        compute_type = self.whisper_cfg.get("compute_type", "int8")
        beam_size = int(self.whisper_cfg.get("beam_size", 5))
        vad_filter = bool(self.whisper_cfg.get("vad_filter", True))
        download_root = self.whisper_cfg.get("download_root") or None

        self.logger.info(
            f"faster-whisper 识别: {ctx.audio_path.name} "
            f"model={model_size} device={device} compute={compute_type}"
        )

        model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            download_root=download_root,
        )

        segments_iter, info = model.transcribe(
            str(ctx.audio_path),
            language=self.language,
            beam_size=beam_size,
            vad_filter=vad_filter,
            word_timestamps=True,
        )

        segments: list[dict] = []
        for seg in segments_iter:
            text = (seg.text or "").strip()
            if not text:
                continue
            words = []
            for w in (seg.words or []):
                wt = (w.word or "").strip()
                if not wt or w.start is None or w.end is None:
                    continue
                words.append({
                    "text": wt,
                    "start": round(float(w.start), 3),
                    "end": round(float(w.end), 3),
                })

            seg_start = round(float(seg.start), 3)
            seg_end = round(float(seg.end), 3)

            # 长句切分（保留 words，让每个子段仍可驱动逐字高亮）
            if len(text) > self.max_chars:
                sub_segs = split_text_to_segments(text, self.max_chars)
                # 把 words 按时间比例分配到子段
                sub_segments = self._split_segment_with_words(
                    sub_segs, seg_start, seg_end, words
                )
                segments.extend(sub_segments)
            else:
                segments.append({
                    "text": text, "start": seg_start, "end": seg_end,
                    "words": words,
                })

        self.logger.info(
            f"faster-whisper 识别完成: {len(segments)} 条字幕（均带词级时间戳）"
        )

        # 兜底：识别为空时降级
        if not segments:
            self.logger.warning("faster-whisper 识别为空，降级到 mock")
            return self._generate_mock(ctx)
        return segments

    def _split_segment_with_words(
        self, sub_texts: list[str], start: float, end: float,
        words: list[dict],
    ) -> list[dict]:
        """将一个长句的 words 按子段文本长度比例分配时间，保留逐字精度"""
        total_dur = end - start
        if not words:
            # 无词级时间戳，按字数均分
            total_chars = sum(len(s) for s in sub_texts) or 1
            result = []
            offset = start
            for s in sub_texts:
                d = total_dur * len(s) / total_chars
                result.append({
                    "text": s, "start": round(offset, 3),
                    "end": round(offset + d, 3), "words": [],
                })
                offset += d
            return result

        # 有词级时间戳：把 words 按子段字符数大致切分
        # 简化策略：按每个子段的字数比例从 words 中分配
        result = []
        word_idx = 0
        total_chars = sum(len(s) for s in sub_texts) or 1
        for s in sub_texts:
            n_take = max(1, round(len(words) * len(s) / total_chars))
            chunk = words[word_idx:word_idx + n_take]
            word_idx += n_take
            if chunk:
                cs = chunk[0]["start"]
                ce = chunk[-1]["end"]
            else:
                cs, ce = start, end
            result.append({
                "text": s, "start": round(cs, 3),
                "end": round(ce, 3), "words": chunk,
            })
        # 把剩余的 words 并入最后一段
        if word_idx < len(words) and result:
            result[-1]["words"].extend(words[word_idx:])
            result[-1]["end"] = words[-1]["end"]
        return result

    def _recognize_mimo(self, ctx: JobContext) -> list[dict]:
        """使用小米 MiMo ASR 识别音频

        MiMo ASR 特点：
        - 端点：{api_base}/chat/completions
        - 音频以 data URL 格式传入（data:audio/mp3;base64,...）
        - 不接受 text 部分（网关注入）
        - 返回识别文本在 choices[0].message.content
        - 不返回时间戳，需按文本长度估算
        """
        self.logger.info(f"MiMo ASR 识别音频: {ctx.audio_path}")

        # 读取音频并转 base64 data URL
        audio_path = ctx.audio_path
        audio_bytes = audio_path.read_bytes()
        # 判断格式
        ext = audio_path.suffix.lower().lstrip(".")
        mime = "audio/wav" if ext == "wav" else "audio/mp3"
        audio_b64 = base64.b64encode(audio_bytes).decode()
        data_url = f"data:{mime};base64,{audio_b64}"

        payload = {
            "model": self.mimo_model,
            "messages": [
                {"role": "user", "content": [
                    {"type": "input_audio", "input_audio": {"data": data_url, "format": ext or "mp3"}}
                ]}
            ],
            "stream": False,
        }
        headers = {
            "Authorization": f"Bearer {self.mimo_api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self.mimo_api_base.rstrip('/')}/chat/completions"

        r = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()

        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            self.logger.warning("MiMo ASR 返回空内容，降级到 mock")
            return self._generate_mock(ctx)

        self.logger.info(f"MiMo ASR 识别结果: {content[:100]}...")

        # MiMo ASR 不返回时间戳，按文本长度估算
        return self._split_text_by_duration(content, ctx.audio_duration)

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

    def _fill_missing_head_with_tts(
        self, segments: list[dict], ctx: JobContext
    ) -> list[dict]:
        """用 TTS 时间戳补全 ASR 可能丢失的开头内容

        场景：whisper VAD 过滤了开头几秒音频，导致前几句字幕缺失。
        策略（双重判断）：
        1. 文本内容匹配：如果 TTS 文本开头有 ASR 第一段没有的内容，补全缺失部分
        2. 时间差判断：如果 ASR 第一段 start 比 TTS 第一段 start 晚超过 1 秒，
           说明 ASR 可能丢失了开头内容，用 TTS 时间戳补全
        """
        import re

        tts_ts = ctx.metadata.get("tts_timestamps")
        if not tts_ts or not segments:
            return segments

        tts_first_start = tts_ts[0].get("start", 0)
        asr_first_start = segments[0].get("start", 0)
        asr_first_text = (segments[0].get("text") or "").strip()
        tts_first_text = (tts_ts[0].get("text") or "").strip()

        # 去除标点后比较，避免标点差异导致匹配失败
        _punct_chars = r"，。！？、,\.!?;；:：""''\"' "
        _strip_punct = lambda s: re.sub(f"[{re.escape(_punct_chars)}]", "", s)
        asr_clean = _strip_punct(asr_first_text)
        tts_clean = _strip_punct(tts_first_text)

        # 策略1：文本内容匹配 - TTS 文本开头有 ASR 没有的内容
        # 例如 TTS="大家好，今天给大家分享..." ASR="今天给大家分享..."
        # 说明 ASR 丢失了"大家好，"
        missing_text = ""
        if asr_clean and tts_clean and asr_clean in tts_clean:
            idx = tts_clean.index(asr_clean)
            if idx > 0:
                # 从 TTS 原始文本中提取缺失部分（保留标点）
                # 通过逐字符匹配原始文本，提取前 idx 个非标点字符对应的原始文本
                missing_chars = []
                clean_count = 0
                for ch in tts_first_text:
                    if ch in _punct_chars:
                        missing_chars.append(ch)
                    else:
                        if clean_count < idx:
                            missing_chars.append(ch)
                            clean_count += 1
                        else:
                            break
                missing_text = "".join(missing_chars).strip()

        # 策略2：时间差判断 - ASR 第一段比 TTS 晚超过 1 秒
        # 且文本不完全匹配（完全匹配说明 ASR 已识别完整内容，只是时间偏移）
        time_gap = asr_first_start - tts_first_start
        use_time_gap = time_gap >= 1.0 and asr_clean != tts_clean

        # 两种策略都不触发，无需补全
        if not missing_text and not use_time_gap:
            return segments

        # 补全丢失内容
        missing_segments: list[dict] = []

        if missing_text:
            # 策略1：文本匹配发现缺失内容，单独作为一条字幕
            # 时间从 TTS 第一段开始到 ASR 第一段开始
            missing_end = asr_first_start if asr_first_start > tts_first_start else tts_ts[0].get("end", 0)
            if len(missing_text) > self.max_chars:
                sub_segs = split_text_to_segments(missing_text, self.max_chars)
                dur = missing_end - tts_first_start
                for j, sub in enumerate(sub_segs):
                    s = tts_first_start + j * dur / len(sub_segs)
                    e = tts_first_start + (j + 1) * dur / len(sub_segs)
                    missing_segments.append({
                        "text": sub,
                        "start": round(s, 3),
                        "end": round(e, 3),
                    })
            else:
                missing_segments.append({
                    "text": missing_text,
                    "start": round(tts_first_start, 3),
                    "end": round(missing_end, 3),
                })
            self.logger.info(
                f"ASR 丢失开头文本 \"{missing_text}\"，"
                f"用 TTS 时间戳补全 {len(missing_segments)} 条字幕"
            )
        else:
            # 策略2：时间差补全，补充 ASR 第一段之前的 TTS 段
            for ts in tts_ts:
                ts_start = ts.get("start", 0)
                ts_end = ts.get("end", 0)
                if ts_start >= asr_first_start:
                    break
                effective_end = min(ts_end, asr_first_start)
                text = ts["text"]
                if len(text) > self.max_chars:
                    sub_segs = split_text_to_segments(text, self.max_chars)
                    dur = effective_end - ts_start
                    for j, sub in enumerate(sub_segs):
                        s = ts_start + j * dur / len(sub_segs)
                        e = ts_start + (j + 1) * dur / len(sub_segs)
                        missing_segments.append({
                            "text": sub,
                            "start": round(s, 3),
                            "end": round(e, 3),
                        })
                else:
                    missing_segments.append({
                        "text": text,
                        "start": round(ts_start, 3),
                        "end": round(effective_end, 3),
                    })
            if missing_segments:
                self.logger.info(
                    f"ASR 丢失开头 {time_gap:.1f}s，"
                    f"用 TTS 时间戳补全 {len(missing_segments)} 条字幕"
                )

        return missing_segments + segments if missing_segments else segments

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
