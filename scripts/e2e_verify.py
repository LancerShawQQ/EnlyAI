"""端到端验证脚本：逐环节测试，定位问题

用法：.venv/Scripts/python.exe scripts/e2e_verify.py [环节名]
环节：config | llm | tts | extract | avatar_reg | tts_synth | subtitle | broll | full
不传环节名则跑全部。
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

# 确保用项目 venv
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

INPUT_DIR = Path(r"D:\cursor_project\koubo\input")
OUTPUT_DIR = Path(r"D:\cursor_project\koubo\output")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def hr(title: str):
    print(f"\n{'='*60}\n  {title}\n{'='*60}")


def step(name):
    print(f"\n>>> {name}")


# ============ 环节 1: 配置加载 ============
def test_config():
    hr("环节 1: 配置加载（验证 .env 注入）")
    from krvoiceai.core.config import Config
    cfg = Config.load()
    print(f"  llm.provider   = {cfg.get('llm.provider')}")
    print(f"  llm.model      = {cfg.get('llm.model')}")
    print(f"  llm.api_key    = {cfg.get('llm.api_key','')[:10]}...")
    print(f"  llm.base_url   = {cfg.get('llm.base_url')}")
    print(f"  tts.provider   = {cfg.get('tts.provider')}")
    print(f"  tts.api_base   = {cfg.get('tts.api_base')}")
    print(f"  tts.mimo_model = {cfg.get('tts.mimo_model')}")
    assert cfg.get("llm.api_key"), "LLM api_key 未注入"
    assert cfg.get("tts.api_key"), "TTS api_key 未注入"
    print("  [OK] 配置注入成功")


# ============ 环节 2: LLM 文案仿写 ============
def test_llm():
    hr("环节 2: LLM 文案仿写（agnes-2.0-flash）")
    from krvoiceai.core.llm_client import LLMClient
    llm = LLMClient()
    print(f"  provider={llm.provider} mock={llm.is_mock}")
    assert not llm.is_mock, "LLM 仍为 mock 模式，api_key 未生效"

    raw = "深圳是一座充满活力的城市，有很多美食和好玩的地方。"
    messages = [
        {"role": "system", "content": "你是短视频口播文案专家，输出150-300字口语化文案。"},
        {"role": "user", "content": f"请润色以下文案，使其更有感染力：\n{raw}"},
    ]
    t0 = time.time()
    result = llm.chat(messages)
    elapsed = time.time() - t0
    print(f"  耗时: {elapsed:.1f}s  字数: {len(result)}")
    print(f"  文案预览: {result[:150]}...")
    assert len(result) > 30, "文案过短，LLM 可能异常"
    print("  [OK] LLM 文案生成正常")


# ============ 环节 3: TTS MiMo 合成 ============
def test_tts():
    hr("环节 3: TTS MiMo 真实语音合成")
    from krvoiceai.modules.tts_engine import TTSEngine
    tts = TTSEngine()
    tts.setup()
    print(f"  provider={tts.provider}")
    assert tts.provider == "mimo", f"TTS 未切到 mimo，当前={tts.provider}"

    from krvoiceai.core.base_module import JobContext
    work = OUTPUT_DIR / "_tts_test"
    work.mkdir(parents=True, exist_ok=True)
    ctx = JobContext(
        work_dir=work,
        script_text="今天带大家探索深圳的美食，这家手工肠粉绝对让你惊喜。",
    )
    ctx.ensure_work_dir()
    t0 = time.time()
    result = tts.execute(ctx)
    elapsed = time.time() - t0
    print(f"  耗时: {elapsed:.1f}s  success={result.success}")
    if not result.success:
        print(f"  [FAIL] error={result.error}")
        return
    print(f"  音频: {ctx.audio_path}  时长: {ctx.audio_duration:.1f}s")
    assert ctx.audio_path.exists(), "音频文件未生成"
    assert ctx.audio_path.stat().st_size > 5000, "音频文件过小"
    print("  [OK] TTS MiMo 合成正常")


# ============ 环节 4: 文案提取 ============
def test_extract():
    hr("环节 4: 文案提取（从原始视频）")
    from krvoiceai.modules.script_extractor import ScriptExtractor
    ext = ScriptExtractor()
    ext.setup()
    print(f"  yt-dlp 可用: {ext._ytdlp_available}")
    print(f"  asr provider: {ext.asr_provider}")

    # 从本地原始视频提取（不依赖 yt-dlp 下载）
    src = INPUT_DIR / "原始视频.mp4"
    t0 = time.time()
    text = ext.extract(str(src))
    elapsed = time.time() - t0
    print(f"  耗时: {elapsed:.1f}s")
    print(f"  提取文案: {text[:200]}")
    if len(text) < 10:
        print("  [WARN] 提取文案过短（可能 ASR 未装走 mock）")
    else:
        print("  [OK] 文案提取正常")


# ============ 环节 5: 数字人形象注册 ============
def test_avatar_reg():
    hr("环节 5: 数字人形象注册（用原始视频）")
    from krvoiceai.modules.avatar_engine import AvatarEngine
    av = AvatarEngine()
    av.setup()
    print(f"  provider={av.provider}")

    src = INPUT_DIR / "原始视频.mp4"
    ok = av.register_avatar("e2e_anchor", src)
    print(f"  注册结果: {ok}")
    ref = av.avatars_dir / "e2e_anchor"
    if ref.exists():
        files = list(ref.iterdir())
        print(f"  形象目录文件: {[f.name for f in files]}")
    assert ok, "形象注册失败"
    print("  [OK] 形象注册成功")


# ============ 环节 6: 数字人口播生成（mock + 微动作）============
def test_avatar_gen():
    hr("环节 6: 数字人口播生成 + 微动作")
    from krvoiceai.core.config import get_config
    cfg = get_config()
    cfg.set("avatar.micro_motion.enabled", True)  # 启用微动作

    from krvoiceai.modules.avatar_engine import AvatarEngine
    from krvoiceai.core.base_module import JobContext
    from krvoiceai.core.audio_utils import generate_silent_wav

    av = AvatarEngine()
    av.setup()

    work = OUTPUT_DIR / "_avatar_test"
    work.mkdir(parents=True, exist_ok=True)
    # 用真实 TTS 音频（如果环节3生成过）或生成静音
    audio = work / "audio.wav"
    generate_silent_wav(audio, 3.0)

    ctx = JobContext(
        work_dir=work,
        audio_path=audio,
        audio_duration=3.0,
        avatar_id="e2e_anchor",
    )
    ctx.ensure_work_dir()
    result = av.execute(ctx)
    print(f"  success={result.success} provider={av.provider}")
    if not result.success:
        print(f"  [FAIL] {result.error}")
        return
    print(f"  视频: {ctx.raw_video_path}")
    print(f"  大小: {ctx.raw_video_path.stat().st_size//1024}KB")
    motion = work / "avatar_with_motion.mp4"
    print(f"  微动作产物存在: {motion.exists()}")
    print("  [OK] 数字人生成完成")


# ============ 环节 7: 字幕 ============
def test_subtitle():
    hr("环节 7: 字幕生成")
    from krvoiceai.modules.subtitle_engine import SubtitleEngine
    from krvoiceai.core.base_module import JobContext
    from krvoiceai.core.audio_utils import generate_silent_wav

    sub = SubtitleEngine()
    sub.setup()
    print(f"  provider={sub.provider}")

    work = OUTPUT_DIR / "_subtitle_test"
    work.mkdir(parents=True, exist_ok=True)
    audio = work / "audio.wav"
    generate_silent_wav(audio, 4.0)
    ctx = JobContext(
        work_dir=work, audio_path=audio, audio_duration=4.0,
        script_text="今天分享深圳美食探店。手工肠粉非常好吃。豆浆也很纯正。",
    )
    ctx.ensure_work_dir()
    result = sub.execute(ctx)
    print(f"  success={result.success}")
    if ctx.subtitle_path and ctx.subtitle_path.exists():
        print(f"  字幕内容预览:\n{ctx.subtitle_path.read_text(encoding='utf-8')[:300]}")
    print("  [OK] 字幕生成完成" if result.success else f"  [FAIL] {result.error}")


# ============ 环节 8: B-roll ============
def test_broll():
    hr("环节 8: B-roll 画中画叠加")
    from krvoiceai.core.config import get_config
    from krvoiceai.modules.broll_engine import BRollEngine
    from krvoiceai.core.base_module import JobContext
    from krvoiceai.core.audio_utils import generate_silent_wav
    from krvoiceai.core.ffmpeg_utils import FFmpegRunner

    ff = FFmpegRunner()
    # 先生成一个基础口播视频（图片+音频）
    work = OUTPUT_DIR / "_broll_test"
    work.mkdir(parents=True, exist_ok=True)
    audio = work / "audio.wav"
    generate_silent_wav(audio, 10.0)
    from PIL import Image
    img = work / "anchor.jpg"
    Image.new("RGB", (1080, 1920), (80, 100, 140)).save(str(img), "JPEG")
    base_video = work / "avatar.mp4"
    ff.image_audio_to_video(img, audio, base_video, fps=25, resolution=(1080, 1920))

    broll = BRollEngine(ffmpeg=ff)
    ctx = JobContext(
        work_dir=work, audio_path=audio, audio_duration=10.0,
        raw_video_path=base_video,
        broll_clips=[{
            "path": str(INPUT_DIR / "画中画视频.mp4"),
            "start": 2.0, "end": 6.0,
            "mode": "pip", "position": "bottom_right",
            "scale": 0.35, "volume": 0.0,
            "shape": "rounded", "animation": "fade",
        }],
    )
    ctx.ensure_work_dir()
    result = broll.execute(ctx)
    print(f"  success={result.success}")
    if result.success:
        print(f"  视频: {ctx.raw_video_path}")
        print(f"  大小: {ctx.raw_video_path.stat().st_size//1024}KB")
        print(f"  data: {result.data}")
    print("  [OK] B-roll 完成" if result.success else f"  [FAIL] {result.error}")


# ============ 环节 9: 全流程 ============
def test_full():
    hr("环节 9: 全流程（除发布外）")
    from krvoiceai.core.config import get_config
    cfg = get_config()
    # 启用微动作
    cfg.set("avatar.micro_motion.enabled", True)

    from krvoiceai.app import EnlyAI
    app = EnlyAI()

    # 读取抖音文案作为参考
    douyin_text = (INPUT_DIR / "douyin.txt").read_text(encoding="utf-8").strip()
    # 提取口播主题（去掉链接和元信息）
    import re
    topic = re.sub(r'https?://\S+', '', douyin_text)
    topic = re.sub(r'#.*', '', topic).strip()
    if len(topic) < 5:
        topic = "深圳美食探店，手工肠粉和豆浆"

    print(f"  参考主题: {topic[:80]}")

    result = app.submit_and_run(
        script=f"今天带大家去深圳探店，吃手工黑芝麻肠粉配豆浆，分享真实体验。{topic[:40]}",
        avatar_id="e2e_anchor",
        voice_id="default",
        script_mode="polish",
        platform="douyin",
        auto_publish=False,
        broll_clips=[{
            "path": str(INPUT_DIR / "画中画视频.mp4"),
            "start": 3.0, "end": 8.0,
            "mode": "pip", "position": "bottom_right",
            "scale": 0.35, "volume": 0.0,
            "shape": "rounded", "animation": "fade",
        }],
    )

    print(f"\n  任务状态: {result['status']}")
    print(f"  耗时: {result['elapsed']:.1f}s")
    if not result["success"]:
        print(f"  [FAIL] {result.get('error')}")
        # 打印各步骤状态
        for s in result.get("stages", []):
            print(f"    {s['step']}: {s['status']} {s.get('error','')}")
        return

    # 各步骤状态
    print("\n  各步骤:")
    for s in result.get("stages", []):
        print(f"    {s['step']:20s} {s['status']:8s} {s.get('elapsed',0):.1f}s")

    # 复制产物到 output
    final = Path(result["video_path"])
    dest = OUTPUT_DIR / f"final_{result['job_id']}.mp4"
    import shutil
    shutil.copy2(final, dest)
    print(f"\n  最终视频: {dest}")
    print(f"  大小: {dest.stat().st_size//1024}KB")
    print(f"  标题: {result.get('title')}")
    print(f"  封面: {result.get('cover_path')}")
    print("  [OK] 全流程完成")


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "all"
    funcs = {
        "config": test_config, "llm": test_llm, "tts": test_tts,
        "extract": test_extract, "avatar_reg": test_avatar_reg,
        "avatar_gen": test_avatar_gen, "subtitle": test_subtitle,
        "broll": test_broll, "full": test_full,
    }
    if target == "all":
        order = ["config", "llm", "tts", "extract", "avatar_reg",
                 "avatar_gen", "subtitle", "broll", "full"]
        for name in order:
            try:
                funcs[name]()
            except Exception as e:
                hr(f"[异常] {name}: {e}")
                import traceback
                traceback.print_exc()
    else:
        funcs[target]()
