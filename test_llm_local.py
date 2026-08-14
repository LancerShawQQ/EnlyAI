"""本地 LLM 验证脚本（Ollama + Qwen2.5-7B OpenAI 兼容端点）

验证：
1. Ollama 服务可达
2. qwen2.5:7b-instruct 模型已拉取
3. OpenAI 兼容 /v1/chat/completions 端点可生成文案
"""
from __future__ import annotations

import sys
import time
from openai import OpenAI

BASE_URL = "http://localhost:11434/v1"
MODEL = "qwen2.5:7b-instruct-q4_K_M"


def main() -> int:
    print(f"[1/3] 检查 Ollama 服务 {BASE_URL} ...")
    try:
        client = OpenAI(base_url=BASE_URL, api_key="ollama", timeout=10)
        models = client.models.list()
        model_ids = [m.id for m in models.data]
        print(f"      可用模型: {model_ids}")
        if MODEL not in model_ids:
            print(f"[FAIL] 模型 {MODEL} 未找到，请先 ollama pull {MODEL}")
            return 1
    except Exception as e:
        print(f"[FAIL] Ollama 服务不可达: {e}")
        return 1

    print(f"[2/3] 生成测试文案（模拟口播脚本）...")
    prompt = (
        "你是一个短视频口播文案写手。请用中文写一段关于'人工智能改变生活'的口播文案，"
        "时长约30秒，语气轻松活泼，开头要吸引人。只输出文案正文，不要解释。"
    )
    t0 = time.time()
    resp = client.chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
        max_tokens=500,
        timeout=120,
    )
    t1 = time.time()
    text = resp.choices[0].message.content.strip()
    print(f"      生成耗时: {t1-t0:.1f}s  tokens={resp.usage.total_tokens}")
    print(f"      文案预览: {text[:200]}")

    if len(text) < 20:
        print("[FAIL] 生成内容过短")
        return 1

    print(f"\n[3/3] 完整文案:")
    print("-" * 60)
    print(text)
    print("-" * 60)
    print(f"\n[OK] 本地 LLM 验证通过：模型={MODEL} 耗时={t1-t0:.1f}s "
          f"tokens={resp.usage.total_tokens}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
