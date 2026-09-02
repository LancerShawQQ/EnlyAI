"""音频处理工具"""
from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np


@dataclass
class AudioInfo:
    """音频信息"""
    path: Path
    duration: float
    sample_rate: int
    channels: int
    sample_width: int  # bytes


def generate_silent_wav(
    output_path: Path,
    duration: float,
    sample_rate: int = 22050,
    channels: int = 1,
    sample_width: int = 2,
) -> AudioInfo:
    """生成指定时长的静音 wav 文件（含极低幅度噪声避免完全静音被某些解码器拒绝）"""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    n_samples = int(duration * sample_rate)
    # 极低幅度噪声（-60dB），避免完全静音
    noise = np.random.randn(n_samples) * 0.001
    # 转为 16-bit PCM
    audio = (noise * 32767).astype(np.int16)
    if channels > 1:
        audio = np.tile(audio.reshape(-1, 1), (1, channels))

    with wave.open(str(output_path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(audio.tobytes())

    return AudioInfo(
        path=output_path,
        duration=duration,
        sample_rate=sample_rate,
        channels=channels,
        sample_width=sample_width,
    )


def get_wav_duration(path: Path) -> float:
    """读取 wav 文件时长"""
    path = Path(path)
    with wave.open(str(path), "rb") as wf:
        n_frames = wf.getnframes()
        rate = wf.getframerate()
        return n_frames / rate if rate > 0 else 0.0


def estimate_speech_duration(text: str, chars_per_second: float = 4.5) -> float:
    """根据文本长度估算语音时长（中文约 4-5 字/秒）"""
    # 去除空白与标点后的有效字数
    effective = sum(1 for c in text if c.strip() and not c in "，。！？、；：""''（）()【】[] \n\t")
    if effective == 0:
        effective = len(text)
    return max(1.0, effective / chars_per_second)


# 虚词/连接词首字：硬切时优先让切点落在这些字之前（词首边界概率高，
# 避免"英|语"这类词中切断——中文无分词器下的轻量启发式）
_FUNC_WORD_STARTS = set("的了和与是在让给把对从被跟或而且然后因为所以但是如果也要就都还再并并且此外另外同时")

# 缓存:避免每行重复编译
_SPLIT_TAIL_RE = None


def _best_cjk_cut(text: str, target: int) -> int:
    """在 target 附近（±4 字）找一个"下一字是虚词首字"的切点，找不到退回 target"""
    for delta in range(0, 5):
        for pos in (target - delta, target + delta):
            if 6 <= pos < len(text) and text[pos] in _FUNC_WORD_STARTS:
                return pos
    return target


def split_text_to_segments(
    text: str, max_chars: int = 40, allow_overshoot: float = 0.0,
) -> list[str]:
    """将文案按句切分为段落，用于分句合成与时间戳对齐

    先按标点切分，再对超过 max_chars 的段按字数硬切分。

    Args:
        allow_overshoot: 无标点长串允许的超长比例（如 0.35 表示 max_chars=18
            时最多可整段保留 24 字）。字幕场景下"轻微超长"远好于把词切断；
            TTS 合成分段传 0（默认）保持精确上限。
    """
    import re
    global _SPLIT_TAIL_RE
    if _SPLIT_TAIL_RE is None:
        _SPLIT_TAIL_RE = re.compile(r'(?<=[，,、；;])')
    # 按标点切分
    sentences = re.split(r'(?<=[。！？!?\n])', text)
    segments: list[str] = []
    buf = ""
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if len(buf) + len(s) <= max_chars:
            buf += s
        else:
            if buf:
                segments.append(buf)
            buf = s
    if buf:
        segments.append(buf)

    # 无标点长串的可保留上限（轻微超长好于词中切断）
    hard_cap = int(max_chars * (1.0 + max(allow_overshoot, 0.0)))

    # 对超过 max_chars 的段按字数硬切分（尽量在逗号/顿号/分号处断开）
    final_segments: list[str] = []
    for seg in segments:
        if len(seg) <= max_chars:
            final_segments.append(seg)
        else:
            # 优先在逗号/顿号/分号处切分
            parts = _SPLIT_TAIL_RE.split(seg)
            cur = ""
            for p in parts:
                if not p:
                    continue
                if len(cur) + len(p) <= max_chars:
                    cur += p
                else:
                    if cur:
                        final_segments.append(cur)
                    # 无标点且在可容忍超长内：整段保留（"英语"不再被切断）
                    if max_chars < len(p) <= hard_cap:
                        final_segments.append(p)
                        cur = ""
                        continue
                    # 超过硬上限：在虚词边界附近切
                    while len(p) > max_chars:
                        if len(p) <= hard_cap:
                            final_segments.append(p)
                            p = ""
                            break
                        cut = _best_cjk_cut(p, max_chars)
                        final_segments.append(p[:cut])
                        p = p[cut:]
                    cur = p
            if cur:
                final_segments.append(cur)

    return final_segments if final_segments else [text]
