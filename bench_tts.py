#!/usr/bin/env python3
"""TTS (CosyVoice3) 性能基准测试

目标：RTF < 1（合成时间 < 音频时长，即快于实时）
测试内容：
1. 短文本（10字）合成
2. 中等文本（50字）合成
3. 长文本（200字）合成
4. 测量 RTF = 合成耗时 / 音频时长
"""
import time
import wave
import io
import sys
from pathlib import Path

import httpx

COSYVOICE_URL = "http://localhost:8012"
PROMPT_WAV = Path("./config/voices/anchor_female/sample.wav")
PROMPT_TEXT = "大家好，欢迎收看今天的节目。"


def get_wav_duration(wav_bytes: bytes) -> float:
    """从 WAV bytes 读取时长"""
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            n_frames = wf.getnframes()
            rate = wf.getframerate()
            return n_frames / rate if rate > 0 else 0.0
    except Exception as e:
        print(f"  [WARN] 读取音频时长失败: {e}")
        return 0.0


def benchmark_tts(text: str, label: str, warmup: bool = False) -> dict:
    """合成文本并测量 RTF"""
    if not PROMPT_WAV.exists():
        print(f"  [ERROR] prompt wav 不存在: {PROMPT_WAV}")
        return {}

    with open(PROMPT_WAV, "rb") as f:
        prompt_bytes = f.read()

    files = {"prompt_wav": ("sample.wav", prompt_bytes, "audio/wav")}
    data = {
        "tts_text": text,
        "prompt_text": PROMPT_TEXT,
        "stream": "false",
        "speed": "1.0",
    }

    t0 = time.time()
    try:
        with httpx.Client(timeout=180.0) as client:
            resp = client.post(
                f"{COSYVOICE_URL}/api/tts/synth",
                files=files,
                data=data,
            )
            elapsed = time.time() - t0
            if resp.status_code != 200:
                print(f"  [ERROR] HTTP {resp.status_code}: {resp.text[:200]}")
                return {}
            wav_bytes = resp.content
    except Exception as e:
        elapsed = time.time() - t0
        print(f"  [ERROR] 请求失败 ({elapsed:.2f}s): {e}")
        return {}

    audio_duration = get_wav_duration(wav_bytes)
    rtf = elapsed / audio_duration if audio_duration > 0 else float("inf")
    text_len = len(text)

    if not warmup:
        print(f"\n=== {label} ===")
        print(f"  文本长度: {text_len} 字符")
        print(f"  文本内容: {text[:60]}{'...' if text_len > 60 else ''}")
        print(f"  合成耗时: {elapsed:.2f}s")
        print(f"  音频时长: {audio_duration:.2f}s")
        print(f"  音频大小: {len(wav_bytes)/1024:.1f} KB")
        print(f"  RTF: {rtf:.3f}  {'✓ 达标 (<1)' if rtf < 1 else '✗ 未达标 (>=1)'}")
        print(f"  速度: {text_len/elapsed:.1f} 字/秒")

    return {
        "label": label,
        "text_len": text_len,
        "elapsed": elapsed,
        "audio_duration": audio_duration,
        "rtf": rtf,
        "wav_size": len(wav_bytes),
    }


if __name__ == "__main__":
    print(f"CosyVoice3: {COSYVOICE_URL}")
    print(f"Prompt: {PROMPT_WAV}")
    print(f"Prompt text: {PROMPT_TEXT}")

    # 检查服务健康
    try:
        r = httpx.get(f"{COSYVOICE_URL}/api/health", timeout=5.0)
        health = r.json()
        print(f"健康检查: {health}")
        if not health.get("model_loaded"):
            print("[ERROR] 模型未加载")
            sys.exit(1)
    except Exception as e:
        print(f"[ERROR] 健康检查失败: {e}")
        sys.exit(1)

    # 预热（首次合成包含模型预热开销）
    print("\n--- 预热合成（不计时）---")
    benchmark_tts("预热测试", "warmup", warmup=True)

    # 短文本（10字）
    short_text = "大家好，欢迎收看今天的节目。"
    r1 = benchmark_tts(short_text, "短文本 10字")

    # 中等文本（50字）
    medium_text = "今天给大家介绍一款非常实用的产品，它采用了最新的技术方案，能够有效解决日常生活中的痛点问题，价格也非常亲民，值得大家关注。"
    r2 = benchmark_tts(medium_text, "中等文本 50字")

    # 长文本（200字）
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
    r3 = benchmark_tts(long_text, "长文本 200字")

    # 汇总
    print("\n" + "=" * 60)
    print("TTS 基准测试汇总")
    print("=" * 60)
    print(f"{'场景':<20} {'文本':<8} {'耗时':<8} {'音频':<8} {'RTF':<8} {'达标':<6}")
    print("-" * 60)
    for r in [r1, r2, r3]:
        if r:
            ok = "✓" if r["rtf"] < 1 else "✗"
            print(f"{r['label']:<20} {r['text_len']:<8} {r['elapsed']:<8.2f} {r['audio_duration']:<8.2f} {r['rtf']:<8.3f} {ok:<6}")

    avg_rtf = sum(r["rtf"] for r in [r1, r2, r3] if r) / max(1, len([r for r in [r1, r2, r3] if r]))
    print(f"\n平均 RTF: {avg_rtf:.3f}  {'✓ 达标' if avg_rtf < 1 else '✗ 需优化'}")
