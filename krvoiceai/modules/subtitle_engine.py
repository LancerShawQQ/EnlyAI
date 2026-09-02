"""字幕生成模块

五种 provider：
- whisper_local: 使用 faster-whisper（CPU int8）识别，提供词级时间戳（本地推荐）
- mimo:   调用小米 MiMo ASR API（OpenAI 兼容 chat/completions 端点）
- funasr: 调用 FunASR 服务（本地 HTTP API）进行语音识别 + 时间戳对齐
- sherpa_funasr: 使用 sherpa-onnx 调用 Fun-ASR-Nano ONNX 模型（paraformer + VAD + 热词）
- mock:   优先复用 TTS 时间戳，否则按文本长度估算

输出：SRT 格式字幕文件（segment 可携带 words 词级时间戳，供 ASS 卡拉OK逐字高亮使用）
"""
from __future__ import annotations

import base64
import time
from pathlib import Path
from typing import Any, Optional

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
        # sherpa-onnx Fun-ASR-Nano 配置（provider=sherpa_funasr 时使用）
        self.sherpa_cfg = self.config.get("asr.sherpa_funasr", {}) or {}
        self._sherpa_available = False

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
        elif self.provider == "sherpa_funasr":
            # 检查 sherpa-onnx 是否可用 + 模型目录是否存在
            try:
                import sherpa_onnx  # noqa: F401
                from ..core.config import PROJECT_ROOT
                model_dir_raw = self.sherpa_cfg.get("model_dir", "")
                model_dir = Path(model_dir_raw) if model_dir_raw else None
                if model_dir and not model_dir.is_absolute():
                    model_dir = PROJECT_ROOT / model_dir
                if model_dir and model_dir.exists():
                    self._sherpa_available = True
                    self.logger.info(
                        f"sherpa-onnx Fun-ASR-Nano 可用 model_dir={model_dir} "
                        f"threads={self.sherpa_cfg.get('num_threads', 4)}"
                    )
                else:
                    self._sherpa_available = False
                    self.logger.warning(
                        f"sherpa_funasr 模型目录不存在: {model_dir or '(未配置)'}，"
                        f"降级到 mock 模式"
                    )
                    self.provider = "mock"
            except ImportError:
                self._sherpa_available = False
                self.logger.warning(
                    "sherpa-onnx 未安装，降级到 mock 模式。"
                    "安装方法：conda activate krvoiceai && pip install sherpa-onnx>=1.13"
                )
                self.provider = "mock"
        else:
            self._funasr_available = False
            self._sherpa_available = False
        self.logger.info(f"字幕模块初始化 provider={self.provider}")
        super().setup()

    def run(self, ctx: JobContext) -> ModuleResult:
        """根据音频生成字幕

        优先级（消灭 ASR 错字——报告实测品牌名「英里」被转写为「英理」）：
        1. TTS 时间戳 + 源文案直出（文字零误差，时间戳来自合成端）
        2. ASR 识别（TTS 时间戳不可用时兜底）
        3. mock 估算
        """
        if not ctx.audio_path or not ctx.audio_path.exists():
            return ModuleResult(success=False, error="无音频文件，无法生成字幕")

        output_path = ctx.work_dir / "subtitle.srt"

        try:
            segments = self._from_tts_timestamps(ctx)
            used = "tts_direct"

            if segments is None:
                if self.provider == "whisper_local" and self._whisper_available:
                    segments = self._recognize_whisper(ctx)
                elif self.provider == "mimo":
                    segments = self._recognize_mimo(ctx)
                elif self.provider == "funasr" and self._funasr_available:
                    segments = self._recognize_funasr(ctx)
                elif self.provider == "sherpa_funasr" and self._sherpa_available:
                    segments = self._recognize_sherpa_funasr(ctx)
                else:
                    segments = self._generate_mock(ctx)
                used = self.provider

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
                    "provider": used,
                },
            )
        except Exception as e:
            return ModuleResult(success=False, error=str(e))

    def _from_tts_timestamps(self, ctx: JobContext) -> Optional[list[dict]]:
        """用 TTS 合成端的时间戳 + 源文案直接构建字幕段

        优势：文字零误差（不做语音识别），时间来自合成端分句（比 ASR 更准）。
        返回 None 表示 TTS 时间戳不可用（如外部音频导入场景），走 ASR 兜底。
        """
        tts_ts = ctx.metadata.get("tts_timestamps") or []
        if not tts_ts:
            return None
        # 校验时间戳覆盖了音频主体（至少覆盖 60%）
        total = ctx.audio_duration or 0
        covered = sum(ts.get("end", 0) - ts.get("start", 0) for ts in tts_ts)
        if total > 0 and covered / total < 0.5:
            return None

        # 源文案原文（保留换行/标点结构）。TTS 合成前常把多行文案拼成整段，
        # 行间无标点时（"今天分享三个\n小妙招"→"今天分享三个小妙招"），
        # 按字数硬切会把"三个|小妙招"这类词组切断——r7 P0 实测 8 段全部
        # 切在词中间。切分基准必须回到原文的换行/标点边界。
        import re as _re
        script = (ctx.script_text or "").strip()

        # 匹配用归一化：去空白 + 去中英文标点（TTS 分段拼接常丢标点，
        # 只去空白会让子串匹配直接失败——r8 P1 层2根因）
        _strip_re = _re.compile(
            r"[\s\u3000，。！？!?；;、,\.：:·—…\"'‘’“”「」『』（）()\[\]【】<>《》]+"
        )
        # 归一化索引映射：norm_map[i] = (归一化字符, 原文下标)，
        # 子串定位后能把归一化位置映射回原文区间（保留 \n/标点）
        norm_map: list[tuple[str, int]] = [
            (ch, i) for i, ch in enumerate(script) if not _strip_re.match(ch)
        ]
        norm_str = "".join(c for c, _ in norm_map)
        # 单调游标：TTS 段按时间有序，后段从上次匹配位置之后搜索，
        # 防止重复短语错配到更早位置
        norm_cursor = 0

        segments: list[dict] = []

        # 连续恢复块：相邻 TTS 段各自恢复的原文区间合并为完整原文跨度，
        # 再按源文标点/换行统一重切。TTS 段边界本身可能切在源文行中间
        # （r8 场景D实测），直接用作字幕边界仍会切断词组；块内时间按
        # 归一化字数（不含标点）比例分配——标点不占语音时长。
        run: dict | None = None  # {"s": span_start, "e": span_end, "t0": start, "t1": end}

        def _flush_run():
            nonlocal run
            if not run:
                return
            span_text = script[run["s"]:run["e"] + 1]
            dur = max(run["t1"] - run["t0"], 0.001)

            def _ncount(s: str) -> int:
                n = len(_strip_re.sub("", s))
                return n if n > 0 else 1

            sub_segs = (
                split_text_to_segments(span_text, self.max_chars)
                if len(span_text) > self.max_chars else [span_text]
            )
            total_chars = sum(_ncount(s) for s in sub_segs)
            cursor = run["t0"]
            for sub in sub_segs:
                share = dur * _ncount(sub) / max(total_chars, 1)
                segments.append({
                    "text": sub,
                    "start": round(cursor, 3),
                    "end": round(cursor + share, 3),
                })
                cursor += share
            run = None

        for ts in tts_ts:
            text = (ts.get("text") or "").strip()
            if not text:
                continue
            start, end = float(ts.get("start", 0)), float(ts.get("end", 0))

            # 恢复源文区间（保留 \n/标点）；失败（TTS 改写/增删字符）→
            # 结束当前块，该段退回 TTS 文本按自身标点切分
            text_match = _strip_re.sub("", text)
            pos = norm_str.find(text_match, norm_cursor) if text_match else -1
            if pos >= 0:
                src_start = norm_map[pos][1]
                src_end = norm_map[pos + len(text_match) - 1][1]
                # 把匹配区间两侧紧邻的标点/空白并入跨度（句尾句号等
                # 属于该句的一部分，归一化定位会漏掉）
                while src_start > 0 and _strip_re.match(script[src_start - 1]):
                    src_start -= 1
                while src_end + 1 < len(script) and _strip_re.match(script[src_end + 1]):
                    src_end += 1
                norm_cursor = pos + len(text_match)
                if run is not None:
                    # 块内跨度取整体原文区间（覆盖段间被跳过的标点/空白）
                    run["s"] = min(run["s"], src_start)
                    run["e"] = max(run["e"], src_end)
                    run["t0"] = min(run["t0"], start)
                    run["t1"] = max(run["t1"], end)
                else:
                    run = {"s": src_start, "e": src_end, "t0": start, "t1": end}
            else:
                _flush_run()
                sub_segs = (
                    split_text_to_segments(text, self.max_chars)
                    if len(text) > self.max_chars else [text]
                )
                dur = max(end - start, 0.001)
                total_chars = sum(len(s) for s in sub_segs) or 1
                cursor = start
                for sub in sub_segs:
                    share = dur * len(sub) / total_chars
                    segments.append({
                        "text": sub,
                        "start": round(cursor, 3),
                        "end": round(cursor + share, 3),
                    })
                    cursor += share
        _flush_run()

        segments.sort(key=lambda s: s["start"])
        self.logger.info(
            f"TTS 时间戳直出字幕: {len(segments)} 段"
            f"（零 ASR 错字，按原文标点/换行切分）"
        )
        return segments if segments else None

    @staticmethod
    def _recover_script_slice(script: str, text_match: str) -> Optional[str]:
        """从源文案中恢复与 TTS 归一化文本对应的原文片段（保留换行与标点）

        归一化 = 去空白+去标点；用归一化索引映射做子串定位后映射回原文区间。
        匹配失败（TTS 改写/增删字符）返回 None（调用方退回 TTS 文本）。

        历史缺陷（r8 P1）：早期双指针要求从原文首字符起连续匹配，
        多段场景（段文本不在原文开头）与 TTS 丢标点场景全部静默失效。
        """
        import re as _re
        strip_re = _re.compile(
            r"[\s\u3000，。！？!?；;、,\.：:·—…\"'‘’“”「」『』（）()\[\]【】<>《》]+"
        )
        norm_map = [(ch, i) for i, ch in enumerate(script) if not strip_re.match(ch)]
        norm = "".join(c for c, _ in norm_map)
        pos = norm.find(text_match)
        if pos < 0 or pos + len(text_match) > len(norm_map):
            return None
        start = norm_map[pos][1]
        end = norm_map[pos + len(text_match) - 1][1]
        return script[start:end + 1]

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

    def _recognize_sherpa_funasr(self, ctx: JobContext) -> list[dict]:
        """使用 sherpa-onnx 调用 Fun-ASR-Nano (Qwen3-0.6B LLM-based) ONNX 模型识别音频

        Fun-ASR-Nano 模型结构（非 paraformer）：
          - encoder_adaptor.int8.onnx (227MB)
          - llm.int8.onnx (573MB)
          - embedding.int8.onnx (148MB)
          - Qwen3-0.6B/ (tokenizer 目录，含 tokenizer.json/merges.txt/vocab.json)

        支持中文（含7方言+26口音）、英文、日文、歌词、说唱语音识别。
        使用 from_funasr_nano API（非 from_paraformer）。

        sherpa-onnx 优势：
        - 纯 ONNX 推理，无需 PyTorch 依赖（CPU 即可跑，RTF~0.19，5倍实时速度）
        - VAD 分段（silero_vad）后逐段识别，长音频更稳
        - 支持热词（hotwords 配置）
        - 加载耗时约 4.4s，推理极快

        输出 segment 结构（携带 words 字段）：
            {"text": "...", "start": 0.0, "end": 2.5,
             "words": [{"text": "字", "start": 0.0, "end": 0.2}, ...]}
        """
        import sherpa_onnx
        import numpy as np
        from ..core.config import PROJECT_ROOT

        # 解析模型目录（相对路径基于 PROJECT_ROOT）
        model_dir_raw = self.sherpa_cfg.get("model_dir", "")
        model_dir = Path(model_dir_raw) if model_dir_raw else None
        if model_dir and not model_dir.is_absolute():
            model_dir = PROJECT_ROOT / model_dir
        if not model_dir or not model_dir.exists():
            self.logger.warning(
                f"sherpa_funasr 模型目录不存在: {model_dir or '(未配置)'}，降级到 mock"
            )
            return self._generate_mock(ctx)

        # Fun-ASR-Nano 模型文件结构（Qwen3-0.6B LLM-based）
        encoder_adaptor = model_dir / "encoder_adaptor.int8.onnx"
        if not encoder_adaptor.exists():
            encoder_adaptor = model_dir / "encoder_adaptor.onnx"
        llm_onnx = model_dir / "llm.int8.onnx"
        if not llm_onnx.exists():
            llm_onnx = model_dir / "llm.onnx"
        embedding_onnx = model_dir / "embedding.int8.onnx"
        if not embedding_onnx.exists():
            embedding_onnx = model_dir / "embedding.onnx"
        tokenizer_dir = model_dir / "Qwen3-0.6B"

        if not (encoder_adaptor.exists() and llm_onnx.exists()
                and embedding_onnx.exists() and tokenizer_dir.exists()):
            self.logger.warning(
                f"sherpa_funasr Fun-ASR-Nano 模型文件缺失: "
                f"encoder_adaptor={'存在' if encoder_adaptor.exists() else '缺失'} "
                f"llm={'存在' if llm_onnx.exists() else '缺失'} "
                f"embedding={'存在' if embedding_onnx.exists() else '缺失'} "
                f"tokenizer={'存在' if tokenizer_dir.exists() else '缺失'}，降级到 mock"
            )
            return self._generate_mock(ctx)

        num_threads = int(self.sherpa_cfg.get("num_threads", 4))
        use_vad = bool(self.sherpa_cfg.get("use_vad", True))
        vad_silero_raw = self.sherpa_cfg.get("vad_silero_model", "")
        vad_silero_model = Path(vad_silero_raw) if vad_silero_raw else None
        if vad_silero_model and not vad_silero_model.is_absolute():
            vad_silero_model = PROJECT_ROOT / vad_silero_model

        self.logger.info(
            f"sherpa-onnx Fun-ASR-Nano (Qwen3-0.6B) 识别: {ctx.audio_path.name} "
            f"model_dir={model_dir.name} threads={num_threads} vad={use_vad}"
        )

        # 构建识别器（from_funasr_nano API）
        try:
            recognizer = sherpa_onnx.OfflineRecognizer.from_funasr_nano(
                encoder_adaptor=str(encoder_adaptor),
                llm=str(llm_onnx),
                embedding=str(embedding_onnx),
                tokenizer=str(tokenizer_dir),
                num_threads=num_threads,
                provider="cpu",
                system_prompt="You are a helpful assistant.",
                user_prompt="语音转写:",
                max_new_tokens=512,
                temperature=1e-6,
                top_p=0.8,
                seed=42,
                language="",
                itn=True,
            )
        except Exception as e:
            self.logger.warning(
                f"sherpa_funasr 识别器构建失败: {e}，降级到 mock"
            )
            return self._generate_mock(ctx)

        # 读取音频为 float32 样本
        samples, sample_rate = self._load_audio_for_sherpa(ctx.audio_path)
        if samples is None or len(samples) == 0:
            self.logger.warning("sherpa_funasr 读取音频失败，降级到 mock")
            return self._generate_mock(ctx)

        # VAD 分段（若配置且模型存在）
        vad_available = (
            use_vad and vad_silero_model is not None and vad_silero_model.exists()
        )
        if vad_available:
            vad_segments = self._vad_segment_sherpa(
                sherpa_onnx, str(vad_silero_model), samples, sample_rate
            )
            self.logger.info(
                f"sherpa_funasr VAD 切分: {len(vad_segments)} 段 "
                f"(silero_vad={vad_silero_model.name})"
            )
            if not vad_segments:
                # VAD 切分为空（全静音或极短），整段识别兜底
                self.logger.warning("sherpa_funasr VAD 切分为空，整段识别兜底")
                vad_segments = [{
                    "start": 0.0,
                    "end": ctx.audio_duration,
                    "samples": samples,
                }]
        else:
            if use_vad:
                reason = (
                    "VAD 模型路径未配置" if vad_silero_model is None
                    else f"VAD 模型不存在: {vad_silero_model}"
                )
                self.logger.warning(f"sherpa_funasr {reason}，整段识别")
            # 整段识别
            vad_segments = [{
                "start": 0.0,
                "end": ctx.audio_duration,
                "samples": samples,
            }]

        # 长段二次切分：连续语音 VAD 切不开时整段可达数十秒，
        # Fun-ASR-Nano (Qwen3-0.6B) 对超长段会输出空文本（实测 39.8s 全空、8s 正常），
        # 按 ≤15s 硬切保证识别成功率
        MAX_ASR_SEG_S = 15.0
        split_segments = []
        for vs in vad_segments:
            seg_dur = float(vs["end"]) - float(vs["start"])
            if seg_dur <= MAX_ASR_SEG_S + 1.0:
                split_segments.append(vs)
                continue
            n = max(2, int(seg_dur / MAX_ASR_SEG_S) + 1)
            step = seg_dur / n
            total_samples = len(vs["samples"])
            for k in range(n):
                a = int(k * step / seg_dur * total_samples)
                b = int(min((k + 1) * step, seg_dur) / seg_dur * total_samples)
                split_segments.append({
                    "start": float(vs["start"]) + k * step,
                    "end": float(vs["start"]) + min((k + 1) * step, seg_dur),
                    "samples": vs["samples"][a:b],
                })
        if len(split_segments) != len(vad_segments):
            self.logger.info(
                f"sherpa_funasr 长段切分: {len(vad_segments)} 段 → {len(split_segments)} 段（>{MAX_ASR_SEG_S}s 强制切分）"
            )
        vad_segments = split_segments

        # 逐段识别
        segments: list[dict] = []
        for vs in vad_segments:
            seg_start = float(vs["start"])
            seg_end = float(vs["end"])
            seg_samples = vs["samples"]

            stream = recognizer.create_stream()
            stream.accept_waveform(sample_rate, seg_samples)
            recognizer.decode_stream(stream)

            text = (stream.result.text or "").strip()
            # Fun-ASR-Nano (Qwen3-0.6B) 输出可能含模型前缀，如：
            # "language Chinese<asr_text>实际文本" 或 "language English<asr_text>actual text"
            # 需清理前缀，只保留实际转写内容
            if "<asr_text>" in text:
                text = text.split("<asr_text>", 1)[1].strip()
            if not text:
                continue

            # 词级时间戳：尝试从 stream.result.tokens 提取（如模型支持）
            words = self._extract_sherpa_words(stream)

            # 长句切分（保留 words，让每个子段仍可驱动逐字高亮）
            if len(text) > self.max_chars:
                sub_segs = split_text_to_segments(text, self.max_chars)
                sub_segments = self._split_segment_with_words(
                    sub_segs, seg_start, seg_end, words
                )
                segments.extend(sub_segments)
            else:
                segments.append({
                    "text": text, "start": round(seg_start, 3),
                    "end": round(seg_end, 3), "words": words,
                })

        self.logger.info(f"sherpa_funasr 识别完成: {len(segments)} 条字幕")

        # 兜底：识别为空时降级
        if not segments:
            self.logger.warning("sherpa_funasr 识别为空，降级到 mock")
            return self._generate_mock(ctx)
        return segments

    def _load_audio_for_sherpa(self, audio_path: Path) -> tuple[Any, int]:
        """读取音频为 float32 样本

        sherpa-onnx accept_waveform 支持任意采样率（内部重采样），
        但要求单声道 float32。优先 WAV，ffmpeg 兜底转换。

        返回: (samples: np.ndarray[float32], sample_rate: int)
        失败返回: (None, 0)
        """
        import wave
        import numpy as np

        # 优先用 sherpa-onnx 内置 read_wave（仅支持 WAV）
        try:
            import sherpa_onnx
            samples, sample_rate = sherpa_onnx.read_wave(str(audio_path))
            return np.array(samples, dtype=np.float32), int(sample_rate)
        except Exception:
            pass

        # 用 wave 模块读 WAV
        try:
            with wave.open(str(audio_path), "rb") as f:
                sample_rate = f.getframerate()
                n_channels = f.getnchannels()
                sample_width = f.getsampwidth()
                frames = f.readframes(f.getnframes())

            if sample_width == 2:
                samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            elif sample_width == 4:
                samples = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
            elif sample_width == 1:
                samples = np.frombuffer(frames, dtype=np.uint8).astype(np.float32)
                samples = (samples - 128) / 128.0
            else:
                raise ValueError(f"不支持的 sample_width: {sample_width}")

            # 立体声转单声道
            if n_channels == 2:
                samples = samples.reshape(-1, 2).mean(axis=1)

            return samples, int(sample_rate)
        except Exception as e:
            self.logger.warning(
                f"读取 WAV 失败（{audio_path.name}）: {e}，尝试用 ffmpeg 转换"
            )

        # ffmpeg 兜底：转 16kHz mono PCM WAV 后读取
        import os
        import tempfile
        import subprocess
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(audio_path),
                 "-ac", "1", "-ar", "16000", "-f", "wav", tmp_path],
                check=True, capture_output=True,
            )
            with wave.open(tmp_path, "rb") as f:
                sample_rate = f.getframerate()
                frames = f.readframes(f.getnframes())
            samples = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
            return samples, int(sample_rate)
        except Exception as e:
            self.logger.error(f"ffmpeg 转换音频失败: {e}")
            return None, 0
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    def _vad_segment_sherpa(
        self, sherpa_onnx, vad_model_path: str,
        samples, sample_rate: int,
    ) -> list[dict]:
        """用 silero VAD 切分音频为多段

        返回: [{"start": float, "end": float, "samples": np.ndarray}]
        """
        import numpy as np

        # silero VAD 要求 16000Hz，如果输入不是则重采样
        vad_sr = 16000
        if sample_rate != vad_sr:
            try:
                import librosa
                samples = librosa.resample(samples, orig_sr=sample_rate, target_sr=vad_sr)
            except Exception:
                # 无 librosa 时用简单的线性重采样
                ratio = vad_sr / sample_rate
                n_new = int(len(samples) * ratio)
                indices = np.linspace(0, len(samples) - 1, n_new)
                samples = np.interp(indices, np.arange(len(samples)), samples).astype(np.float32)
            orig_sr = sample_rate
            sample_rate = vad_sr

        vad_config = sherpa_onnx.VadModelConfig()
        vad_config.silero_vad.model = vad_model_path
        vad_config.silero_vad.threshold = 0.5
        # sherpa-onnx 1.13+ 属性名无 _ms 后缀（兼容新旧版本）
        if hasattr(vad_config.silero_vad, "min_silence_duration"):
            vad_config.silero_vad.min_silence_duration = 500
        elif hasattr(vad_config.silero_vad, "min_silence_duration_ms"):
            vad_config.silero_vad.min_silence_duration_ms = 500
        vad_config.sample_rate = sample_rate
        vad_config.provider = "cpu"

        # 环形缓冲必须 ≥ 音频总长：固定 30s 时超长音频前段被覆盖
        # （实测 40.5s 音频只吐出一个 start=end=29.67 的零长度残段，
        #  导致识别器收到 0 样本、字幕降级为估算时间戳）
        buffer_seconds = max(30, int(len(samples) / sample_rate) + 5)
        vad = sherpa_onnx.VoiceActivityDetector(
            vad_config, buffer_size_in_seconds=buffer_seconds
        )

        # 小块喂入（100ms，官方推荐）：一次喂 30s 大块会导致 VAD 内部
        # 丢弃前段音频（实测 40.5s 音频只识别出尾部 10.8s）
        chunk_size = int(sample_rate * 0.1)
        total = len(samples)
        for i in range(0, total, chunk_size):
            chunk = samples[i:i + chunk_size]
            # sherpa-onnx 1.13+ 的 accept_waveform 只接受 samples（采样率在 config 中设）
            try:
                vad.accept_waveform(chunk)
            except TypeError:
                # 旧版 API 接受 (sample_rate, samples)
                vad.accept_waveform(sample_rate, chunk)
        vad.flush()  # 刷新尾部剩余

        segments: list[dict] = []
        while not vad.empty():
            seg = vad.front
            # 注意顺序：1.12.x 的 SpeechSegment.samples 是底层缓冲视图，
            # pop() 之后内容会被清空——必须先拷贝再 pop（曾因此产出 0 样本空段）
            if hasattr(seg, "samples"):
                seg_samples = np.array(seg.samples, dtype=np.float32).copy()
                seg_start_sec = (
                    float(seg.start) / sample_rate if hasattr(seg, "start") else 0.0
                )
            elif isinstance(seg, (list, np.ndarray)):
                seg_samples = np.array(seg, dtype=np.float32)
                seg_start_sec = 0.0
            else:
                vad.pop()
                continue
            vad.pop()

            seg_end_sec = seg_start_sec + len(seg_samples) / sample_rate
            segments.append({
                "start": seg_start_sec,
                "end": seg_end_sec,
                "samples": seg_samples,
            })

        return segments

    def _extract_sherpa_words(self, stream) -> list[dict]:
        """从 sherpa-onnx 识别结果中提取词级时间戳（如模型支持）

        paraformer offline 模型通常不返回 token 级时间戳，
        此方法尝试提取，无时间戳则返回空列表（由 _split_segment_with_words 兜底）。
        """
        words: list[dict] = []
        try:
            tokens = getattr(stream.result, "tokens", None) or []
            if not tokens:
                return words
            # 仅当 token 携带 .start/.end 属性时才提取（真正的词级时间戳）
            has_timestamps = any(
                hasattr(tok, "start") and hasattr(tok, "end") for tok in tokens
            )
            if not has_timestamps:
                return words  # 返回空，让 _split_segment_with_words 按字数均分
            for tok in tokens:
                tok_text = ""
                if hasattr(tok, "text"):
                    tok_text = (tok.text or "").strip()
                if not tok_text:
                    continue
                tok_start = float(getattr(tok, "start", 0.0))
                tok_end = float(getattr(tok, "end", tok_start))
                words.append({
                    "text": tok_text,
                    "start": round(tok_start, 3),
                    "end": round(tok_end, 3),
                })
        except Exception as e:
            self.logger.debug(f"sherpa_funasr 词级时间戳提取失败（忽略）: {e}")
            return []
        return words

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
                    # 按字数比例分配时长（等分会让短句拖长、长句赶拍，
                    # 卡拉OK逐字进度与语音脱节）
                    total_chars = sum(len(s) for s in sub_segs)
                    cursor = ts["start"]
                    for sub in sub_segs:
                        share = dur * len(sub) / max(total_chars, 1)
                        segments.append({
                            "text": sub,
                            "start": round(cursor, 3),
                            "end": round(cursor + share, 3),
                        })
                        cursor += share
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
