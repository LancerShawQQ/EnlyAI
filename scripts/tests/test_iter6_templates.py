"""
迭代6：模板系统应用与还原测试
测试所有 6 个模板的应用、配置传播、重置还原
"""
import httpx
import sys
import time

BASE = "http://127.0.0.1:8000"
client = httpx.Client(base_url=BASE, timeout=60.0)

def banner(title):
    print(f"\n{'='*70}\n=== {title}\n{'='*70}")

def get_cfg(section):
    r = client.get(f"/api/settings/{section}")
    return r.json() if r.status_code == 200 else {}

def put_cfg(section, data):
    r = client.put(f"/api/settings/{section}", json={"section": section, "data": data})
    return r.json() if r.status_code == 200 else {}

def reset_cfg(section):
    r = client.delete(f"/api/settings/{section}")
    return r.json() if r.status_code == 200 else {}

banner("迭代6：模板系统应用与还原测试")

# ============ 1. 获取所有模板 ============
print("\n--- [1] 获取所有模板 ---")
r = client.get("/api/templates")
templates = r.json()
print(f"模板总数: {len(templates)}")
template_ids = list(templates.keys())
print(f"模板列表: {template_ids}")

# 记录初始配置（用于最终还原验证）
print("\n--- [2] 记录初始配置（应用模板前）---")
initial_subtitle = get_cfg("subtitle")
initial_audio = get_cfg("audio")
initial_effects = get_cfg("effects")
print(f"初始字幕: preset={initial_subtitle.get('preset')}, animation={initial_subtitle.get('animation')}")
print(f"初始音频: emotion={initial_audio.get('emotion')}, bgm.enabled={initial_audio.get('bgm',{}).get('enabled')}")
print(f"初始效果: filter={initial_effects.get('filter')}, transition={initial_effects.get('transition')}")

# ============ 3. 逐个应用每个模板并验证 ============
print("\n--- [3] 逐个应用每个模板并验证配置传播 ---")
template_expected = {
    "news_broadcast": {
        "subtitle_preset": "news_red",
        "emotion": "serious",
        "bgm_track": "news_serious",
    },
    "knowledge_popular": {
        "subtitle_preset": "tech_blue",
        "emotion": "cheerful",
        "bgm_track": "tech_electronic",
    },
    "emotional_story": {
        "subtitle_preset": "minimal_white",
        "emotion": "gentle",
        "bgm_track": "warm_acoustic",
    },
    "product_intro": {
        "subtitle_preset": "pop_pink",
        "emotion": "excited",
        "bgm_track": "upbeat_corporate",
    },
    "chinese_style": {
        "subtitle_preset": "classic_gold",
        "emotion": "calm",
        "bgm_track": "chinese_guzheng",
    },
    "tech_review": {
        "subtitle_preset": "dark_black",
        "emotion": "neutral",
        "bgm_track": "tech_electronic",
    },
}

all_passed = True
for tid in template_ids:
    print(f"\n  >>> 应用模板: {tid} ({templates[tid].get('label')})")
    r = client.post("/api/templates/apply", json={"template_id": tid})
    if r.status_code != 200 or not r.json().get("success"):
        print(f"  ❌ 应用失败: {r.text[:200]}")
        all_passed = False
        continue

    # 验证字幕预设
    sub = get_cfg("subtitle")
    audio = get_cfg("audio")
    effects = get_cfg("effects")
    expected = template_expected.get(tid, {})

    checks = []
    # 字幕预设
    exp_sub = expected.get("subtitle_preset")
    if exp_sub:
        ok = sub.get("preset") == exp_sub
        checks.append(("subtitle.preset", exp_sub, sub.get("preset"), ok))
    # 情感
    exp_emo = expected.get("emotion")
    if exp_emo:
        ok = audio.get("emotion") == exp_emo
        checks.append(("audio.emotion", exp_emo, audio.get("emotion"), ok))
    # BGM track
    exp_bgm = expected.get("bgm_track")
    if exp_bgm:
        ok = audio.get("bgm", {}).get("track") == exp_bgm
        checks.append(("audio.bgm.track", exp_bgm, audio.get("bgm", {}).get("track"), ok))
    # BGM enabled
    ok = audio.get("bgm", {}).get("enabled") == True
    checks.append(("audio.bgm.enabled", True, audio.get("bgm", {}).get("enabled"), ok))

    for field, exp, actual, ok in checks:
        status = "✅" if ok else "❌"
        print(f"    {status} {field}: 期望={exp}, 实际={actual}")
        if not ok:
            all_passed = False

    # 验证字幕颜色是否随预设变化
    print(f"    字幕颜色: primary={sub.get('primary_color')}, outline={sub.get('outline_color')}")

if not all_passed:
    print("\n❌ 部分模板验证失败")
    sys.exit(1)

# ============ 4. 重置所有创作配置段并验证还原 ============
print("\n--- [4] 重置所有创作配置段（subtitle/audio/effects）---")
for section in ["subtitle", "audio", "effects"]:
    r = reset_cfg(section)
    print(f"  重置 {section}: {r}")

# 验证重置后配置回到默认
print("\n--- [5] 验证重置后配置回到默认 ---")
reset_subtitle = get_cfg("subtitle")
reset_audio = get_cfg("audio")
reset_effects = get_cfg("effects")
print(f"  重置后字幕: preset={reset_subtitle.get('preset')}, animation={reset_subtitle.get('animation')}")
print(f"  重置后音频: emotion={reset_audio.get('emotion')}, bgm.enabled={reset_audio.get('bgm',{}).get('enabled')}")
print(f"  重置后效果: filter={reset_effects.get('filter')}, transition={reset_effects.get('transition')}")

# 读取 default.yaml 中的默认值进行对比
import yaml
with open("/workspace/config/default.yaml", "r") as f:
    defaults = yaml.safe_load(f)
default_subtitle = defaults.get("subtitle", {})
default_audio = defaults.get("audio", {})
default_effects = defaults.get("effects", {})
print(f"\n  默认字幕配置: preset={default_subtitle.get('preset')}, animation={default_subtitle.get('animation')}")
print(f"  默认音频配置: emotion={default_audio.get('emotion')}, bgm.enabled={default_audio.get('bgm',{}).get('enabled')}")
print(f"  默认效果配置: filter={default_effects.get('filter')}, transition={default_effects.get('transition')}")

assert reset_subtitle.get("preset") == default_subtitle.get("preset"), "字幕预设未还原到默认"
assert reset_audio.get("emotion") == default_audio.get("emotion"), "音频情感未还原到默认"
print("\n✅ 迭代6：模板系统应用与还原测试通过")
print(f"  - 6 个模板全部应用成功")
print(f"  - 字幕预设/情感/BGM 配置全部正确传播")
print(f"  - 重置后配置正确回到默认值")
