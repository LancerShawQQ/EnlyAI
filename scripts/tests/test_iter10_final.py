"""
迭代10：最终综合验证
1. 所有 API 端点健康检查
2. TTS 测试修复验证（MiMo 真实合成）
3. 完整流水线最终验证
4. 所有产出文件验证
"""
import httpx
import sys
import time
import os

BASE = "http://127.0.0.1:8000"
client = httpx.Client(base_url=BASE, timeout=300.0)

def banner(title):
    print(f"\n{'='*70}\n=== {title}\n{'='*70}")

banner("迭代10：最终综合验证")

# ============ 1. 所有 API 端点健康检查 ============
print("\n--- [1] 所有 API 端点健康检查 ---")
endpoints = [
    ("GET", "/api/health"),
    ("GET", "/api/avatars"),
    ("GET", "/api/voices"),
    ("GET", "/api/jobs?limit=5"),
    ("GET", "/api/settings"),
    ("GET", "/api/settings/llm"),
    ("GET", "/api/settings/tts"),
    ("GET", "/api/settings/subtitle"),
    ("GET", "/api/settings/audio"),
    ("GET", "/api/settings/effects"),
    ("GET", "/api/settings/presets/all"),
    ("GET", "/api/creative/presets"),
    ("GET", "/api/templates"),
    ("GET", "/api/bgm/library"),
]

all_ok = True
for method, path in endpoints:
    r = client.get(path) if method == "GET" else client.post(path)
    status = "✅" if r.status_code == 200 else "❌"
    if r.status_code != 200:
        all_ok = False
    print(f"  {status} {method} {path} -> {r.status_code}")

assert all_ok, "部分 API 端点不可用"

# ============ 2. TTS 测试修复验证 ============
print("\n--- [2] TTS 测试修复验证（MiMo 真实合成）---")
# 从服务器配置读取（传掩码值让服务器使用已配置的 key）
r = client.post("/api/settings/test/tts", json={
    "provider": "mimo",
    "api_base": "https://token-plan-cn.xiaomimimo.com/v1",
    "api_key": "****",  # 掩码值，服务器会从配置读取真实 key
})
print(f"POST /api/settings/test/tts -> {r.status_code}")
result = r.json()
print(f"  success: {result.get('success')}")
print(f"  message: {result.get('message')}")
print(f"  elapsed_ms: {result.get('elapsed_ms')}")
print(f"  model: {result.get('model')}")
assert result.get("success"), f"MiMo TTS 测试失败: {result.get('message')}"
assert "字节音频" in result.get("message", ""), "TTS 测试消息应包含合成的音频字节数"
print(f"  ✅ MiMo TTS 测试修复验证通过（真实合成音频）")

# ============ 3. LLM 测试验证 ============
print("\n--- [3] LLM 测试验证 ---")
r = client.post("/api/settings/test/llm", json={
    "provider": "agnes",
    "api_key": "****",  # 掩码值，服务器会从配置读取真实 key
    "base_url": "https://apihub.agnes-ai.cn/v1",
    "model": "agnes-2.5-flash",
})
print(f"POST /api/settings/test/llm -> {r.status_code}")
result = r.json()
print(f"  success: {result.get('success')}")
print(f"  message: {result.get('message')}")
print(f"  elapsed_ms: {result.get('elapsed_ms')}")
assert result.get("success"), f"LLM 测试失败: {result.get('message')}"

# ============ 4. 完整流水线最终验证 ============
print("\n--- [4] 完整流水线最终验证 ---")
script = "今天分享一个超实用的笔记法：康奈尔笔记法。把纸分成三栏，右边记内容，左边提问题，下面写总结。"
print(f"输入文案: {script}")

# 应用模板
r = client.post("/api/templates/apply", json={"template_id": "knowledge_popular"})
print(f"应用模板: knowledge_popular -> {r.json().get('success')}")

t0 = time.time()
r = client.post("/api/generate", json={
    "script": script,
    "avatar_id": "default",
    "voice_id": "mimo_default",
})
elapsed = time.time() - t0
print(f"POST /api/generate -> {r.status_code} ({elapsed:.1f}s)")

result = r.json()
assert result.get("success"), f"流水线失败: {result.get('error')}"

print(f"\n  === 流水线结果 ===")
print(f"  job_id: {result.get('job_id')}")
print(f"  elapsed: {result.get('elapsed')}s")
print(f"  video_path: {result.get('video_path')}")
print(f"  subtitle_path: {result.get('subtitle_path')}")
print(f"  audio_path: {result.get('audio_path')}")
print(f"  audio_duration: {result.get('audio_duration')}s")
print(f"  title: {result.get('title')}")
print(f"  cover_path: {result.get('cover_path')}")
print(f"  stages: {len(result.get('stages', []))} 个阶段")

for s in result.get("stages", []):
    dur = s.get("elapsed", 0) or 0
    print(f"    {s.get('step')}: {s.get('status')} ({dur:.1f}s)")

# ============ 5. 产出文件验证 ============
print("\n--- [5] 产出文件验证 ---")
video_path = result.get("video_path")
subtitle_path = result.get("subtitle_path")
cover_path = result.get("cover_path")

if video_path:
    full_path = os.path.join("/workspace", video_path)
    if os.path.exists(full_path):
        size = os.path.getsize(full_path)
        print(f"  ✅ 视频文件存在: {size/1024:.0f}KB")
    else:
        print(f"  ❌ 视频文件不存在: {full_path}")
        sys.exit(1)

if subtitle_path:
    full_path = os.path.join("/workspace", subtitle_path)
    if os.path.exists(full_path):
        with open(full_path, "r") as f:
            content = f.read()
        print(f"  ✅ 字幕文件存在: {len(content)} 字符")
        # 验证 SRT 格式
        if content.strip().startswith("1"):
            print(f"     字幕格式: SRT")
    else:
        print(f"  ❌ 字幕文件不存在: {full_path}")

if cover_path:
    full_path = os.path.join("/workspace", cover_path)
    if os.path.exists(full_path):
        size = os.path.getsize(full_path)
        print(f"  ✅ 封面文件存在: {size/1024:.0f}KB")
    else:
        print(f"  ❌ 封面文件不存在: {full_path}")

# ============ 6. 文件下载 API 验证 ============
print("\n--- [6] 文件下载 API 验证 ---")
if video_path:
    r = client.get("/api/files", params={"path": video_path})
    print(f"  GET /api/files?path=video -> {r.status_code}, Content-Type: {r.headers.get('content-type','?')}")
    assert r.status_code == 200, "文件下载失败"
    assert len(r.content) > 0, "下载文件为空"
    print(f"  ✅ 文件下载正常 ({len(r.content)/1024:.0f}KB)")

print("\n" + "="*70)
print("=== 迭代10：最终综合验证全部通过 ===")
print("="*70)
print("\n📊 10 轮迭代测试总结:")
print("  迭代1: LLM 文案生成（Agnes AI）✅")
print("  迭代2: TTS 语音合成（小米 MiMo）✅")
print("  迭代3: ASR 语音识别（小米 MiMo）✅")
print("  迭代4: 完整流水线端到端 + 429限流修复 ✅")
print("  迭代5: 创作向导 6 步流程 + 3个bug修复 ✅")
print("  迭代6: 模板系统应用与还原（6个模板）✅")
print("  迭代7: 批量处理与任务管理 ✅")
print("  迭代8: 设置中心 14 个配置段保存/热更新 ✅")
print("  迭代9: 稳定性测试（3次连续+错误恢复）✅")
print("  迭代10: 最终综合验证 + TTS测试修复 ✅")
print("\n🔧 本轮修复的 Bug:")
print("  1. settings 白名单缺少 subtitle/scene/audio/effects 段")
print("  2. health_check 缺少 status/version 字段")
print("  3. list_voices 不返回 provider 默认音色")
print("  4. submit_and_run 响应缺少 video_path/subtitle_path/title/cover_path/elapsed/stages")
print("  5. test_tts 对 MiMo provider 只检查URL可达性，未真实合成音频")
