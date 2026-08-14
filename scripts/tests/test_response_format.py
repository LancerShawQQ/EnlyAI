"""快速验证 submit_and_run 响应格式修复"""
import httpx, time, json

client = httpx.Client(base_url="http://127.0.0.1:8000", timeout=180.0)

# 健康检查
r = client.get("/api/health")
print(f"Health: {r.json().get('status')}")

# 简短文案快速生成
script = "大家好，今天分享一个高效学习的小技巧：费曼学习法。简单来说，就是用教别人的方式来学习。"
print(f"提交生成请求 ({len(script)} 字)...")

t0 = time.time()
r = client.post("/api/generate", json={"script": script, "avatar_id": "default", "voice_id": "mimo_default"})
elapsed = time.time() - t0
print(f"POST /api/generate -> {r.status_code} ({elapsed:.1f}s)")

result = r.json()
print(f"\n=== 响应字段验证 ===")
print(f"  success: {result.get('success')}")
print(f"  job_id: {result.get('job_id')}")
print(f"  elapsed: {result.get('elapsed')}s")
print(f"  video_path: {result.get('video_path')}")
print(f"  subtitle_path: {result.get('subtitle_path')}")
print(f"  title: {result.get('title')}")
print(f"  cover_path: {result.get('cover_path')}")
print(f"  audio_duration: {result.get('audio_duration')}s")
print(f"  stages count: {len(result.get('stages', []))}")
print(f"\n=== 阶段详情 ===")
for s in result.get("stages", []):
    print(f"  {s.get('step')}: {s.get('status')} ({s.get('elapsed', 0):.2f}s)")

# 验证所有关键字段都存在
assert result.get("video_path"), "video_path 缺失"
assert result.get("subtitle_path"), "subtitle_path 缺失"
assert result.get("title"), "title 缺失"
assert result.get("cover_path"), "cover_path 缺失"
assert result.get("elapsed"), "elapsed 缺失"
assert len(result.get("stages", [])) > 0, "stages 为空"
print("\n✅ 响应格式修复验证通过：所有用户友好字段均已正确返回")
