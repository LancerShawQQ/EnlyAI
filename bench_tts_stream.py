#!/usr/bin/env python3
"""TTS 流式模式基准测试

流式模式：LLM 生成 token 与 token2wav 合成交叠执行，
可减少总耗时（特别是长文本）。
"""
import time
import wave
import io
from pathlib import Path
import httpx

COSYVOICE_URL = "http://localhost:8012"
PROMPT_WAV = Path("./config/voices/anchor_female/sample.wav")
PROMPT_TEXT = "大家好，欢迎收看今天的节目。"


def get_wav_duration(wav_bytes: bytes) -> float:
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            return wf.getnframes() / wf.getframerate() if wf.getframerate() > 0 else 0.0
    except Exception:
        return 0.0


def benchmark_stream(text: str, label: str):
    """流式合成：收集所有 chunk，测量总耗时和首 chunk 延迟"""
    with open(PROMPT_WAV, "rb") as f:
        prompt_bytes = f.read()

    files = {"prompt_wav": ("sample.wav", prompt_bytes, "audio/wav")}
    data = {
        "tts_text": text,
        "prompt_text": PROMPT_TEXT,
        "stream": "true",
        "speed": "1.0",
    }

    t0 = time.time()
    t_first_chunk = None
    chunks = []
    total_bytes = 0

    with httpx.Client(timeout=180.0) as client:
        with client.stream(
            "POST", f"{COSYVOICE_URL}/api/tts/synth",
            files=files, data=data,
        ) as resp:
            for chunk in resp.iter_bytes():
                if chunk:
                    if t_first_chunk is None:
                        t_first_chunk = time.time()
                    chunks.append(chunk)
                    total_bytes += len(chunk)

    t_end = time.time()
    wav_bytes = b"".join(chunks)
    audio_duration = get_wav_duration(wav_bytes)
    total_elapsed = t_end - t0
    ttfa = (t_first_chunk - t0) if t_first_chunk else 0
    rtf = total_elapsed / audio_duration if audio_duration > 0 else float("inf")

    print(f"\n=== {label} (stream) ===")
    print(f"  文本长度: {len(text)} 字符")
    print(f"  首 chunk 延迟 (TTFA): {ttfa:.2f}s")
    print(f"  总耗时: {total_elapsed:.2f}s")
    print(f"  音频时长: {audio_duration:.2f}s")
    print(f"  音频大小: {total_bytes/1024:.1f} KB")
    print(f"  RTF: {rtf:.3f}  {'✓ 达标 (<1)' if rtf < 1 else '✗ 未达标 (>=1)'}")
    return rtf, ttfa, total_elapsed, audio_duration


if __name__ == "__main__":
    print(f"CosyVoice3 流式基准测试: {COSYVOICE_URL}")

    # 预热
    print("\n--- 预热 ---")
    benchmark_stream("预热", "warmup")

    # 短文本
    short = "大家好，欢迎收看今天的节目。"
    benchmark_stream(short, "短文本 14字")

    # 中等文本
    medium = "今天给大家介绍一款非常实用的产品，它采用了最新的技术方案，能够有效解决日常生活中的痛点问题，价格也非常亲民，值得大家关注。"
    benchmark_stream(medium, "中等文本 61字")

    # 长文本
    long_text = (
        "人工智能技术正在以前所未有的速度改变着我们的生活。"
        "从智能手机到自动驾驶汽车，从医疗诊断到金融分析，"
        "AI的应用场景越来越广泛。特别是大语言模型的出现，"
        "让机器能够理解和生成人类语言，这为内容创作行业带来了革命性的变化。"
        "现在，即使是没有专业背景的普通人，也可以借助AI工具快速生成高质量的文案、"
        "视频脚本和营销内容。这不仅大大提高了工作效率，也降低了内容创作的门槛。"
        "未来，随着技术的进一步发展，我们相信AI将在更多领域发挥重要作用，"
        "为人类创造更加美好的生活体验。让我们一起拥抱这个充满机遇的时代吧！"
    )
    benchmark_stream(long_text, "长文本 245字")

    print("\n流式模式可显著降低首音频延迟(TTFA)，提升用户体验")
