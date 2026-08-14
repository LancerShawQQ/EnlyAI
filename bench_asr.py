#!/usr/bin/env python3
"""ASR (Fun-ASR-Nano via sherpa-onnx) 性能基准测试

目标：CER 降低 75%（相比 mock/无ASR），RTF < 1
测试内容：
1. 使用已知文本的音频进行识别
2. 计算 CER (Character Error Rate)
3. 测量 RTF (处理时间 / 音频时长)
"""
import sys
import time
import wave
import numpy as np
from pathlib import Path

# 配置
MODEL_DIR = Path("./workspace_data/models/asr/funasr_nano/sherpa-onnx-funasr-nano-int8-2025-12-30")
VAD_MODEL = Path("./workspace_data/models/asr/silero_vad.onnx")
NUM_THREADS = 4

# 测试音频和对应文本
TEST_CASES = [
    {
        "audio": Path("./config/voices/anchor_female/sample.wav"),
        "expected": "大家好欢迎收看今天的节目",
    },
    {
        "audio": Path("./config/voices/anchor_male/sample.wav"),
        "expected": "大家好欢迎收看今天的节目",
    },
    {
        "audio": Path("./config/voices/narrator_female/sample.wav"),
        "expected": "在这个美好的日子里让我们一起探索",
    },
]


def read_wav(path: Path) -> tuple[np.ndarray, int]:
    """读取 WAV 文件返回 (samples, sample_rate)"""
    with wave.open(str(path), "rb") as wf:
        sr = wf.getframerate()
        n = wf.getnframes()
        raw = wf.readframes(n)
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    return samples, sr


def get_duration(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / wf.getframerate()


def cer(reference: str, hypothesis: str) -> float:
    """计算字符错误率 CER (使用编辑距离)"""
    ref = list(reference)
    hyp = list(hypothesis)
    n, m = len(ref), len(hyp)
    if n == 0:
        return 1.0 if m > 0 else 0.0
    # DP table
    dp = [[0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        dp[i][0] = i
    for j in range(m + 1):
        dp[0][j] = j
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    return dp[n][m] / n


def benchmark_asr():
    import sherpa_onnx

    # 检查模型文件
    encoder = MODEL_DIR / "encoder_adaptor.int8.onnx"
    llm = MODEL_DIR / "llm.int8.onnx"
    embedding = MODEL_DIR / "embedding.int8.onnx"
    tokenizer = MODEL_DIR / "Qwen3-0.6B"

    if not all(p.exists() for p in [encoder, llm, embedding, tokenizer]):
        print(f"[ERROR] 模型文件缺失:")
        print(f"  encoder: {encoder.exists()} ({encoder})")
        print(f"  llm: {llm.exists()} ({llm})")
        print(f"  embedding: {embedding.exists()} ({embedding})")
        print(f"  tokenizer: {tokenizer.exists()} ({tokenizer})")
        return

    print(f"模型目录: {MODEL_DIR}")
    print(f"VAD模型: {VAD_MODEL} (存在: {VAD_MODEL.exists()})")
    print(f"线程数: {NUM_THREADS}")

    # 构建识别器（funasr_nano 不支持 vad_model 参数，VAD 由 subtitle_engine 层处理）
    t0 = time.time()
    kwargs = dict(
        encoder_adaptor=str(encoder),
        llm=str(llm),
        embedding=str(embedding),
        tokenizer=str(tokenizer),
        num_threads=NUM_THREADS,
        decoding_method="greedy_search",
        provider="cpu",
    )

    recognizer = sherpa_onnx.OfflineRecognizer.from_funasr_nano(**kwargs)
    load_time = time.time() - t0
    print(f"模型加载耗时: {load_time:.2f}s\n")

    # 测试每个音频
    results = []
    for i, tc in enumerate(TEST_CASES):
        audio_path = tc["audio"]
        expected = tc["expected"]

        if not audio_path.exists():
            print(f"[SKIP] 音频不存在: {audio_path}")
            continue

        duration = get_duration(audio_path)
        samples, sr = read_wav(audio_path)

        # 识别
        t0 = time.time()
        stream = recognizer.create_stream()
        stream.accept_waveform(sr, samples)
        recognizer.decode_stream(stream)
        elapsed = time.time() - t0

        recognized = stream.result.text.strip()
        error_rate = cer(expected, recognized)
        rtf = elapsed / duration if duration > 0 else float("inf")

        print(f"=== 测试 {i+1}: {audio_path.name} ===")
        print(f"  音频时长: {duration:.2f}s")
        print(f"  识别耗时: {elapsed:.2f}s")
        print(f"  RTF: {rtf:.3f}  {'✓' if rtf < 1 else '✗'}")
        print(f"  期望文本: {expected}")
        print(f"  识别文本: {recognized}")
        print(f"  CER: {error_rate:.3f} ({error_rate*100:.1f}%)")
        print()

        results.append({
            "audio": audio_path.name,
            "duration": duration,
            "elapsed": elapsed,
            "rtf": rtf,
            "expected": expected,
            "recognized": recognized,
            "cer": error_rate,
        })

    # 汇总
    if results:
        print("=" * 60)
        print("ASR 基准测试汇总")
        print("=" * 60)
        print(f"{'音频':<25} {'时长':<8} {'耗时':<8} {'RTF':<8} {'CER':<8} {'达标':<6}")
        print("-" * 60)
        for r in results:
            ok = "✓" if r["rtf"] < 1 else "✗"
            print(f"{r['audio']:<25} {r['duration']:<8.2f} {r['elapsed']:<8.2f} {r['rtf']:<8.3f} {r['cer']:<8.3f} {ok:<6}")

        avg_rtf = sum(r["rtf"] for r in results) / len(results)
        avg_cer = sum(r["cer"] for r in results) / len(results)
        print(f"\n平均 RTF: {avg_rtf:.3f}  {'✓ 达标 (<1)' if avg_rtf < 1 else '✗ 未达标'}")
        print(f"平均 CER: {avg_cer:.3f} ({avg_cer*100:.1f}%)")
        print(f"准确率: {(1-avg_cer)*100:.1f}%")

        # CER 降低评估（相比 mock 模式 CER=1.0）
        mock_cer = 1.0
        improvement = (mock_cer - avg_cer) / mock_cer * 100
        print(f"\n相比 mock 模式 (CER=100%)，CER 降低: {improvement:.1f}%")
        print(f"目标: CER 降低 75%  {'✓ 达标' if improvement >= 75 else '✗ 未达标'}")


if __name__ == "__main__":
    print("Fun-ASR-Nano (Qwen3-0.6B) ASR 基准测试\n")
    benchmark_asr()
