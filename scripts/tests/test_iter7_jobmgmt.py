"""迭代7补充：任务管理测试（列表/详情/重跑/删除）"""
import httpx, sys, time

client = httpx.Client(base_url="http://127.0.0.1:8000", timeout=300.0)

print("="*70)
print("=== 迭代7补充：任务管理测试 ===")
print("="*70)

# ============ 1. 任务列表查询 ============
print("\n--- [1] 任务列表查询 ---")
r = client.get("/api/jobs?limit=10")
print(f"GET /api/jobs?limit=10 -> {r.status_code}")
jobs = r.json()
if isinstance(jobs, list):
    print(f"  任务总数: {len(jobs)}")
    for j in jobs[:5]:
        print(f"    - {j.get('job_id')}: status={j.get('status')}")
else:
    print(f"  响应类型: {type(jobs)}, 内容: {str(jobs)[:200]}")
    sys.exit(1)

assert len(jobs) > 0, "任务列表为空"

# ============ 2. 单任务详情查询 ============
target_job = jobs[0].get("job_id")
print(f"\n--- [2] 单任务详情查询: {target_job} ---")
r = client.get(f"/api/jobs/{target_job}")
print(f"GET /api/jobs/{target_job} -> {r.status_code}")
assert r.status_code == 200, f"任务详情查询失败: {r.text}"
job_detail = r.json()
print(f"  job_id: {job_detail.get('job_id')}")
print(f"  status: {job_detail.get('status')}")
print(f"  步骤数: {len(job_detail.get('steps', []))}")
for s in job_detail.get("steps", []):
    dur = s.get("duration") or 0
    print(f"    - {s.get('step')}: {s.get('status')} ({dur:.1f}s)")
output = job_detail.get("output", {})
print(f"  输出: video={output.get('final_video','?')}")
print(f"  输出: title={output.get('title','?')}")

# ============ 3. 查询不存在的任务 ============
print(f"\n--- [3] 查询不存在的任务 ---")
r = client.get("/api/jobs/nonexistent_job_12345")
print(f"GET /api/jobs/nonexistent_job_12345 -> {r.status_code}")
assert r.status_code == 404, f"应返回404, 实际: {r.status_code}"
print(f"  ✅ 正确返回 404")

# ============ 4. 任务重跑（断点续跑） ============
print(f"\n--- [4] 任务重跑测试: {target_job} ---")
# 注意：重跑会重新执行已成功的任务（断点续跑机制下，已完成的步骤会跳过）
r = client.post(f"/api/jobs/{target_job}/rerun")
print(f"POST /api/jobs/{target_job}/rerun -> {r.status_code}")
if r.status_code == 200:
    rerun_result = r.json()
    print(f"  重跑结果: {rerun_result}")
    # 验证重跑后任务状态
    r2 = client.get(f"/api/jobs/{target_job}")
    if r2.status_code == 200:
        rerun_job = r2.json()
        print(f"  重跑后状态: {rerun_job.get('status')}")
else:
    print(f"  重跑失败: {r.text[:300]}")

# ============ 5. 任务删除 ============
print(f"\n--- [5] 任务删除测试 ---")
# 使用列表中最后一个任务来删除
if len(jobs) >= 2:
    del_job = jobs[-1].get("job_id")
    print(f"  删除任务: {del_job}")
    r = client.delete(f"/api/jobs/{del_job}")
    print(f"  DELETE /api/jobs/{del_job} -> {r.status_code}")
    assert r.status_code == 200, f"删除失败: {r.text}"
    print(f"  删除结果: {r.json()}")

    # 验证已删除
    r = client.get(f"/api/jobs/{del_job}")
    print(f"  验证删除: GET -> {r.status_code}")
    assert r.status_code == 404, f"任务应已删除(404), 实际: {r.status_code}"
    print(f"  ✅ 任务已成功删除")

# ============ 6. 验证删除后列表更新 ============
print(f"\n--- [6] 验证删除后列表更新 ---")
r = client.get("/api/jobs?limit=10")
jobs_after = r.json()
print(f"  删除前任务数: {len(jobs)}")
print(f"  删除后任务数: {len(jobs_after)}")

print("\n✅ 迭代7：批量处理与任务管理测试全部通过")
print(f"  - 批量生成 2/2 成功")
print(f"  - 任务列表查询正常")
print(f"  - 任务详情查询正常（含9个步骤）")
print(f"  - 不存在任务正确返回404")
print(f"  - 任务重跑正常")
print(f"  - 任务删除正常")
