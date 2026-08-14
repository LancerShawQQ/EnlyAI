#!/usr/bin/env python3
"""LLM (qwen3:8b via Ollama) 性能基准测试

目标：~50 tok/s
测试内容：
1. 非流式生成（测量端到端延迟）
2. 流式生成（测量真实 tok/s）
3. 不同 prompt 长度下的性能
"""
import json
import time
import sys
import urllib.request

OLLAMA_URL = "http://localhost:11434"
MODEL = "qwen3:8b"


def benchmark_non_stream(prompt: str, label: str):
    """非流式：测量端到端延迟和总 tok/s"""
    payload = json.dumps({
        "model": MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.7,
            "num_predict": 300,
            "num_ctx": 4096,
        },
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{OLLAMA_URL}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    elapsed = time.time() - t0

    eval_count = data.get("eval_count", 0)
    prompt_eval_count = data.get("prompt_eval_count", 0)
    eval_duration_ns = data.get("eval_duration", 0)
    load_duration_ns = data.get("load_duration", 0)
    prompt_eval_duration_ns = data.get("prompt_eval_duration", 0)

    # Ollama 返回的 duration 单位是纳秒
    eval_duration_s = eval_duration_ns / 1e9 if eval_duration_ns else 0
    tok_s = eval_count / eval_duration_s if eval_duration_s > 0 else 0

    print(f"\n=== {label} ===")
    print(f"  prompt 长度: {len(prompt)} 字符 / {prompt_eval_count} tokens")
    print(f"  生成 tokens: {eval_count}")
    print(f"  总耗时: {elapsed:.2f}s (load={load_duration_ns/1e9:.2f}s, prompt_eval={prompt_eval_duration_ns/1e9:.2f}s, gen={eval_duration_s:.2f}s)")
    print(f"  生成速度: {tok_s:.1f} tok/s")
    print(f"  生成文本前100字: {data.get('response', '')[:100]}")
    return tok_s


def benchmark_stream(prompt: str, label: str):
    """流式：测量真实 tok/s（首token延迟 + 持续速度）"""
    import httpx

    payload = {
        "model": MODEL,
        "prompt": prompt,
        "stream": True,
        "options": {
            "temperature": 0.7,
            "num_predict": 200,
            "num_ctx": 4096,
        },
    }

    t0 = time.time()
    t_first_token = None
    token_count = 0
    with httpx.stream(
        "POST", f"{OLLAMA_URL}/api/generate",
        json=payload, timeout=120.0,
    ) as resp:
        for line in resp.iter_lines():
            line = line.strip()
            if not line:
                continue
            try:
                chunk = json.loads(line)
            except json.JSONDecodeError:
                continue
            if chunk.get("response"):
                if t_first_token is None:
                    t_first_token = time.time()
                token_count += 1
            if chunk.get("done"):
                break
    t_end = time.time()

    ttft = (t_first_token - t0) if t_first_token else 0
    gen_elapsed = (t_end - t_first_token) if t_first_token else 0
    tok_s = token_count / gen_elapsed if gen_elapsed > 0 else 0

    print(f"\n=== {label} (stream) ===")
    print(f"  首 token 延迟 (TTFT): {ttft:.2f}s")
    print(f"  生成 tokens: {token_count}")
    print(f"  生成耗时: {gen_elapsed:.2f}s")
    print(f"  持续生成速度: {tok_s:.1f} tok/s")
    return tok_s


if __name__ == "__main__":
    print(f"模型: {MODEL}")
    print(f"Ollama: {OLLAMA_URL}")

    # 短 prompt（模拟口播文案生成）
    short_prompt = "请用50字介绍人工智能的发展趋势，语气轻松活泼。/no_think"
    benchmark_non_stream(short_prompt, "短 prompt 非流式")

    # 中等 prompt（模拟润色）
    medium_prompt = """请润色以下文案，使其更适合抖音口播风格，保留原意但更口语化、有感染力：

原文：人工智能技术正在快速发展，大语言模型的出现让机器能够理解和生成人类语言，这将深刻改变内容创作行业。

要求：80字以内，有钩子句，节奏感强。/no_think"""
    benchmark_non_stream(medium_prompt, "中 prompt 非流式")

    # 流式测试
    benchmark_stream(short_prompt, "短 prompt 流式")

    print("\n基准测试完成")
