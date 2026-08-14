"""
迭代5：创作向导 6 步流程端到端测试（修正版）
模拟真实用户从模板选择 → 数字人 → 文案 → 语音 → 字幕效果 → 生成的完整点击流程
"""
import httpx
import json
import time
import sys

BASE = "http://127.0.0.1:8000"
client = httpx.Client(base_url=BASE, timeout=180.0)

def banner(title):
    print(f"\n{'='*70}\n=== {title}\n{'='*70}")

def step(n, title):
    print(f"\n--- [向导步骤 {n}] {title} ---")

def put_settings(section: str, data: dict) -> dict:
    """PUT /api/settings/{section} 需要 {section, data} body"""
    r = client.put(f"/api/settings/{section}", json={"section": section, "data": data})
    return r

# ============ 启动向导：健康检查 ============
banner("迭代5：创作向导 6 步流程端到端测试")
step(0, "健康检查")
r = client.get("/api/health")
print(f"GET /api/health -> {r.status_code}")
health = r.json()
print(f"  status={health.get('status')}, version={health.get('version')}, ffmpeg={health.get('ffmpeg')}")
print(f"  llm_mock={health.get('llm_mock')}, avatars={health.get('avatars_count')}, voices={health.get('voices_count')}")
assert r.status_code == 200, "健康检查失败"
assert health.get("status") == "ok", f"系统状态异常: {health.get('status')}"

# ============ 步骤1：模板选择 ============
step(1, "模板选择（用户浏览模板库）")
r = client.get("/api/templates")
print(f"GET /api/templates -> {r.status_code}")
templates = r.json()
print(f"  可用模板数: {len(templates)}")
for tid, t in templates.items():
    print(f"    - {tid}: {t.get('label')} (字幕={t.get('subtitle_preset')}, BGM={t.get('bgm_track')}, 情感={t.get('emotion')})")

# 用户选择"知识科普"模板（正确ID: knowledge_popular）
chosen_template = "knowledge_popular"
print(f"\n用户选择模板: {chosen_template}")
r = client.post("/api/templates/apply", json={"template_id": chosen_template})
print(f"POST /api/templates/apply -> {r.status_code}")
apply_result = r.json()
print(f"  应用结果: success={apply_result.get('success')}, message={apply_result.get('message')}")
assert apply_result.get("success"), f"模板应用失败: {apply_result}"

# 验证模板是否真的生效
r = client.get("/api/settings/subtitle")
sub_cfg = r.json()
print(f"  验证字幕配置: preset={sub_cfg.get('preset')}, animation={sub_cfg.get('animation')}")
assert sub_cfg.get("preset") == "tech_blue", f"模板字幕预设未生效: {sub_cfg.get('preset')}"

r = client.get("/api/settings/audio")
audio_cfg = r.json()
print(f"  验证音频配置: emotion={audio_cfg.get('emotion')}, bgm.enabled={audio_cfg.get('bgm',{}).get('enabled')}")
assert audio_cfg.get("emotion") == "cheerful", f"模板情感未生效: {audio_cfg.get('emotion')}"

r = client.get("/api/settings/effects")
effects_cfg = r.json()
print(f"  验证效果配置: filter={effects_cfg.get('filter')}, transition={effects_cfg.get('transition')}")

# ============ 步骤2：数字人选择 ============
step(2, "数字人选择（用户浏览数字人列表）")
r = client.get("/api/avatars")
print(f"GET /api/avatars -> {r.status_code}")
avatars = r.json()
print(f"  可用数字人数: {len(avatars)}")
for a in avatars:
    print(f"    - avatar_id={a.get('avatar_id')}, reference={a.get('reference_image','无')}")
assert len(avatars) > 0, "没有可用数字人"
chosen_avatar = avatars[0].get("avatar_id")
print(f"  用户选择数字人: {chosen_avatar}")

# ============ 步骤3：文案编辑（AI 润色） ============
step(3, "文案编辑（用户输入文案并使用 AI 润色）")
raw_script = "今天给大家介绍三个时间管理的小技巧，第一个是番茄工作法，第二个是优先级排序，第三个是时间块管理。"
print(f"用户原始文案: {raw_script}")

# 调用 AI 润色
r = client.post("/api/script/process", json={
    "script": raw_script,
    "action": "polish",
    "style": "professional",
    "topic": "时间管理"
})
print(f"POST /api/script/process (polish) -> {r.status_code}")
if r.status_code == 200:
    script_result = r.json()
    polished = script_result.get("script") or script_result.get("text") or ""
    print(f"  AI 润色后文案 ({len(polished)} 字): {polished[:200]}...")
    final_script = polished if polished else raw_script
else:
    print(f"  润色失败: {r.text[:300]}")
    final_script = raw_script

# ============ 步骤4：语音配置 ============
step(4, "语音配置（用户选择音色）")
r = client.get("/api/voices")
print(f"GET /api/voices -> {r.status_code}")
voices = r.json()
print(f"  可用音色数: {len(voices)}")
for v in voices:
    print(f"    - voice_id={v.get('voice_id')}, type={v.get('type')}, provider={v.get('provider')}")
assert len(voices) > 0, "没有可用音色"

r = client.get("/api/settings/tts")
tts_cfg = r.json()
print(f"  当前 TTS 配置: provider={tts_cfg.get('provider')}, model={tts_cfg.get('mimo_model')}")
chosen_voice = voices[0].get("voice_id")
print(f"  用户选择音色: {chosen_voice}")

# ============ 步骤5：字幕/效果配置 ============
step(5, "字幕/效果配置（用户调整字幕样式与特效）")
r = client.get("/api/creative/presets")
print(f"GET /api/creative/presets -> {r.status_code}")
presets = r.json()
for category, items in presets.items():
    if isinstance(items, dict):
        print(f"  {category}: {list(items.keys())}")

# 用户调整字幕样式为"卡拉OK"
print("\n用户调整字幕动画为 karaoke（卡拉OK效果）")
r = put_settings("subtitle", {"animation": "karaoke", "karaoke": True})
print(f"PUT /api/settings/subtitle -> {r.status_code}")
assert r.status_code == 200, f"字幕配置保存失败: {r.text}"
print(f"  响应: success={r.json().get('success')}")

# 用户调整 BGM 音量
print("用户调整 BGM 音量为 0.4")
r = put_settings("audio", {"bgm": {"volume": 40}})
print(f"PUT /api/settings/audio -> {r.status_code}")
assert r.status_code == 200, f"音频配置保存失败: {r.text}"

# 用户设置转场效果
print("用户设置转场效果为 slide")
r = put_settings("effects", {"transition": "slide"})
print(f"PUT /api/settings/effects -> {r.status_code}")
assert r.status_code == 200, f"效果配置保存失败: {r.text}"

# ============ 步骤6：生成视频 ============
step(6, "生成视频（用户点击生成按钮）")
print(f"最终文案 ({len(final_script)} 字): {final_script[:150]}...")

generate_payload = {
    "script": final_script,
    "avatar_id": chosen_avatar,
    "voice_id": chosen_voice,
}
print(f"提交生成请求: avatar_id={chosen_avatar}, voice_id={chosen_voice}")

t0 = time.time()
r = client.post("/api/generate", json=generate_payload)
elapsed = time.time() - t0
print(f"POST /api/generate -> {r.status_code} (耗时 {elapsed:.1f}s)")

if r.status_code == 200:
    result = r.json()
    print(f"\n生成结果:")
    print(f"  success: {result.get('success')}")
    print(f"  job_id: {result.get('job_id')}")
    print(f"  耗时: {result.get('elapsed', elapsed):.1f}s")
    stages = result.get("stages", {})
    print(f"  阶段执行情况:")
    for stage_name, stage_data in stages.items():
        status = stage_data.get("status") if isinstance(stage_data, dict) else stage_data
        dur = stage_data.get("elapsed", 0) if isinstance(stage_data, dict) else 0
        print(f"    {stage_name}: {status} ({dur:.2f}s)")
    print(f"\n  视频路径: {result.get('video_path')}")
    print(f"  字幕路径: {result.get('subtitle_path')}")
    print(f"  标题: {result.get('title')}")
    print(f"  封面: {result.get('cover_path')}")
    if result.get("success"):
        print("\n✅ 迭代5：创作向导 6 步流程端到端测试通过")
    else:
        print(f"\n⚠️  流水线执行未完全成功: {result.get('error', '未知错误')}")
        sys.exit(1)
else:
    print(f"❌ 生成失败: {r.text[:500]}")
    sys.exit(1)
