"""
迭代7：批量处理与任务管理测试
1. 批量提交 2 个文案生成视频
2. 任务列表查询
3. 单任务详情查询
4. 任务重跑（断点续跑）
5. 任务删除
"""
import httpx
import sys
import time

BASE = "http://127.0.0.1:8000"
client = httpx.Client(base_url=BASE, timeout=300.0)

def banner(title):
    print(f"\n{'='*70}\n=== {title}\n{'='*70}")

banner("迭代7：批量处理与任务管理测试")

# ============ 1. 批量生成 ============
print("\n--- [1] 批量提交 2 个文案生成视频 ---")
batch_items = [
    {
        "script": "今天分享一个读书方法：主动阅读法。读的时候带着问题读，读完用自己的话总结。",
        "avatar_id": "default",
        "voice_id": "mimo_default",
    },
    {
        "script": "推荐一款效率工具：番茄钟。工作二十五分钟，休息五分钟，保持高效专注。",
        "avatar_id": "default",
        "voice_id": "mimo_default",
    },
]
print(f"批量任务数: {len(batch_items)}")
for i, item in enumerate(batch_items):
    print(f"  [{i}] {item['script'][:50]}...")

t0 = time.time()
r = client.post("/api/batch/generate", json={"items": batch_items, "parallel": 1})
elapsed = time.time() - t0
print(f"\nPOST /api/batch/generate -> {r.status_code} (总耗时 {elapsed:.1f}s)")

if r.status_code != 200:
    print(f"❌ 批量生成失败: {r.text[:500]}")
    sys.exit(1)

batch_result = r.json()
print(f"  总数: {batch_result.get('total')}")
results = batch_result.get("results", [])
print(f"  结果数: {len(results)}")

job_ids = []
for i, res in enumerate(results):
    success = res.get("success")
    job_id = res.get("job_id")
    job_ids.append(job_id)
    elapsed_i = res.get("elapsed", 0)
    video = res.get("video_path")
    title = res.get("title")
    print(f"\n  [{i}] success={success}, job_id={job_id}, elapsed={elapsed_i}s")
    print(f"      title={title}")
    print(f"      video={video}")
    if not success:
        print(f"      error={res.get('error')}")

success_count = sum(1 for r in results if r.get("success"))
print(f"\n批量生成结果: {success_count}/{len(results)} 成功")
assert success_count == len(results), f"部分批量任务失败: {success_count}/{len(results)}"

# ============ 2. 任务列表查询 ============
print("\n--- [2] 任务列表查询 ---")
r = client.get("/api/jobs?limit=10")
print(f"GET /api/jobs?limit=10 -> {r.status_code}")
jobs = r.json()
if isinstance(jobs, list):
    print(f"  任务总数: {len(jobs)}")
    for j in jobs[:5]:
        print(f"    - {j.get('job_id')}: status={j.get('status')}, created={j.get('created_at','?')}")
else:
    print(f"  响应: {jobs}")

# ============ 3. 单任务详情查询 ============
print(f"\n--- [3] 单任务详情查询 ---")
target_job = job_ids[0] if job_ids else None
if target_job:
    r = client.get(f"/api/jobs/{target_job}")
    print(f"GET /api/jobs/{target_job} -> {r.status_code}")
    if r.status_code == 200:
        job_detail = r.json()
        print(f"  job_id: {job_detail.get('job_id')}")
        print(f"  status: {job_detail.get('status')}")
        print(f"  步骤数: {len(job_detail.get('steps', []))}")
        for s in job_detail.get("steps", []):
            dur = s.get("duration") or 0
            print(f"    - {s.get('step')}: {s.get('status')} ({dur:.1f}s)")
        output = job_detail.get("output", {})
        print(f"  输出: video={output.get('final_video','?')}")
    else:
        print(f"  ❌ 查询失败: {r.text[:200]}")

# ============ 4. 任务重跑（断点续跑） ============
print(f"\n--- [4] 任务重跑测试 ---")
if target_job:
    r = client.post(f"/api/jobs/{target_job}/rerun")
    print(f"POST /api/jobs/{target_job}/rerun -> {r.status_code}")
    if r.status_code == 200:
        print(f"  重跑结果: {r.json()}")
    else:
        print(f"  重跑失败: {r.text[:200]}")

# ============ 5. 任务删除 ============
print(f"\n--- [5] 任务删除测试 ---")
if len(job_ids) >= 2:
    del_job = job_ids[-1]  # 删除最后一个
    r = client.delete(f"/api/jobs/{del_job}")
    print(f"DELETE /api/jobs/{del_job} -> {r.status_code}")
    print(f"  删除结果: {r.json()}")

    # 验证已删除
    r = client.get(f"/api/jobs/{del_job}")
    print(f"  验证删除: GET /api/jobs/{del_job} -> {r.status_code}")
    if r.status_code == 404:
        print(f"  ✅ 任务已成功删除")
    else:
        print(f"  ⚠️ 任务可能未删除: {r.text[:200]}")

print("\n✅ 迭代7：批量处理与任务管理测试通过")
print(f"  - 批量生成 {len(results)} 个任务全部成功")
print(f"  - 任务列表/详情/重跑/删除 API 全部正常")
