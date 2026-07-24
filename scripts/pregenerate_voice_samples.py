"""预生成内置音色试听样本

为 MOSS-TTS-Nano 的 18 个内置音色 + edge-tts 的 17 个中文音色生成试听音频，
保存到 config/voices/samples/{voice_id}.wav。

运行后，前端点击试听按钮时直接返回预生成文件（<1秒），
无需每次实时合成（MOSS 约80秒，edge-tts 约3-5秒）。

用法：
  cd KrVoiceAI
  python scripts/pregenerate_voice_samples.py
  python scripts/pregenerate_voice_samples.py --force  # 强制重新生成
  python scripts/pregenerate_voice_samples.py --edge   # 仅生成 edge-tts 音色
  python scripts/pregenerate_voice_samples.py --moss   # 仅生成 MOSS 音色
"""
import sys
import shutil
from pathlib import Path

# 确保项目根目录在 sys.path 中
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from krvoiceai.app import EnlyAI

# 试听文本（自然口语化，避免太短导致"着急"感）
SAMPLE_TEXT_ZH = "大家好，欢迎收听本期播客，今天我们来聊一个有趣的话题。"
SAMPLE_TEXT_EN = "Hello everyone, welcome to our podcast. Today we'll talk about an interesting topic."
SAMPLE_TEXT_JA = "皆さんこんにちは、今回のポッドキャストへようこそ。今日は面白い話題をお話ししましょう。"

# MOSS 18 个音色及其对应语言
MOSS_VOICES = {
    # 中文（6个）
    "Junhao":  SAMPLE_TEXT_ZH,
    "Zhiming": SAMPLE_TEXT_ZH,
    "Weiguo":  SAMPLE_TEXT_ZH,
    "Xiaoyu":  SAMPLE_TEXT_ZH,
    "Yuewen":  SAMPLE_TEXT_ZH,
    "Lingyu":  SAMPLE_TEXT_ZH,
    # 英文（5个）
    "Trump":   SAMPLE_TEXT_EN,
    "Ava":     SAMPLE_TEXT_EN,
    "Bella":   SAMPLE_TEXT_EN,
    "Adam":    SAMPLE_TEXT_EN,
    "Nathan":  SAMPLE_TEXT_EN,
    # 日文（7个）
    "Soyo":    SAMPLE_TEXT_JA,
    "Saki":    SAMPLE_TEXT_JA,
    "Mortis":  SAMPLE_TEXT_JA,
    "Umiri":   SAMPLE_TEXT_JA,
    "Mei":     SAMPLE_TEXT_JA,
    "Anon":    SAMPLE_TEXT_JA,
    "Arisa":   SAMPLE_TEXT_JA,
}

# edge-tts 7 个实测可用中文音色（与 tts_engine.py EDGE_SUPPORTED_VOICES 同步）
EDGE_VOICES = {
    "zh-CN-XiaoxiaoNeural":   SAMPLE_TEXT_ZH,
    "zh-CN-YunxiNeural":      SAMPLE_TEXT_ZH,
    "zh-CN-YunjianNeural":    SAMPLE_TEXT_ZH,
    "zh-CN-XiaoyiNeural":     SAMPLE_TEXT_ZH,
    "zh-CN-YunyangNeural":    SAMPLE_TEXT_ZH,
    "zh-CN-XiaoxuanNeural":   SAMPLE_TEXT_ZH,
    "zh-CN-YunxiaNeural":     SAMPLE_TEXT_ZH,
}
SAMPLES_DIR = project_root / "config" / "voices" / "samples"


def main():
    force = "--force" in sys.argv or "-f" in sys.argv
    only_edge = "--edge" in sys.argv
    only_moss = "--moss" in sys.argv

    # 确定要生成的音色集合
    voices_to_gen = {}
    if only_edge:
        voices_to_gen.update(EDGE_VOICES)
    elif only_moss:
        voices_to_gen.update(MOSS_VOICES)
    else:
        voices_to_gen.update(MOSS_VOICES)
        voices_to_gen.update(EDGE_VOICES)

    all_voices = list(voices_to_gen.keys())
    print("=" * 60)
    print(f"预生成音色试听样本（共 {len(all_voices)} 个：MOSS {len(MOSS_VOICES)} + edge-tts {len(EDGE_VOICES)}）")
    print(f"样本目录: {SAMPLES_DIR}")
    print(f"强制重新生成: {force}")
    if only_edge:
        print("模式: 仅 edge-tts 音色")
    elif only_moss:
        print("模式: 仅 MOSS 音色")
    print("=" * 60)

    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

    # 检查已存在的样本
    existing = [v for v in all_voices if (SAMPLES_DIR / f"{v}.wav").exists()]
    if len(existing) == len(all_voices) and not force:
        print(f"\n所有 {len(all_voices)} 个音色样本已存在，无需重新生成。")
        print("使用 --force 可强制重新生成。")
        for v in all_voices:
            size = (SAMPLES_DIR / f"{v}.wav").stat().st_size
            print(f"  {v}.wav  ({size/1024:.0f} KB)")
        return

    to_generate = all_voices if force else [v for v in all_voices if not (SAMPLES_DIR / f"{v}.wav").exists()]
    print(f"\n需生成 {len(to_generate)} 个样本...")

    # 初始化 KrVoiceAI 应用
    print("\n初始化 TTS 引擎...")
    app = EnlyAI()
    engine = app.modules.get("tts")
    if engine is None:
        print("ERROR: TTS 引擎未初始化")
        sys.exit(1)

    import time
    for voice_id in to_generate:
        sample_text = voices_to_gen[voice_id]
        sample_path = SAMPLES_DIR / f"{voice_id}.wav"
        if sample_path.exists() and not force:
            print(f"  [跳过] {voice_id} 已存在")
            continue

        # edge-tts 音色需要切换 provider
        is_edge = voice_id.startswith("zh-")
        provider_tag = "edge_tts" if is_edge else "moss_nano"
        print(f"  [生成] {voice_id} ({provider_tag})...", end=" ", flush=True)
        t0 = time.time()
        try:
            tmp_path = project_root / "workspace_data" / "tmp" / f"voice_sample_{voice_id}.wav"
            tmp_path.parent.mkdir(parents=True, exist_ok=True)

            if is_edge:
                # edge-tts 音色：临时切换 provider 合成
                import copy
                from krvoiceai.core.config import Config
                raw_data = copy.deepcopy(app.config._data)
                raw_data.setdefault("tts", {})["provider"] = "edge_tts"
                edge_engine = engine.__class__(config=Config(raw_data))
                edge_engine.setup()
                audio_path, duration, _ = edge_engine.synthesize(
                    sample_text, voice_id, tmp_path,
                )
            else:
                # MOSS 音色：用默认引擎（provider=moss_nano）
                audio_path, duration, _ = engine.synthesize(
                    sample_text, voice_id, tmp_path,
                )

            # 复制到样本目录
            shutil.copy2(str(audio_path), str(sample_path))
            elapsed = time.time() - t0
            size = sample_path.stat().st_size
            print(f"完成 ({elapsed:.1f}s, {size/1024:.0f} KB, {duration:.1f}s)")
        except Exception as e:
            print(f"失败: {e}")

    # 汇总
    print("\n" + "=" * 60)
    print("生成完成！")
    for v in all_voices:
        p = SAMPLES_DIR / f"{v}.wav"
        if p.exists():
            print(f"  {v}.wav  ({p.stat().st_size/1024:.0f} KB)")
        else:
            print(f"  {v}.wav  [缺失]")
    print("=" * 60)


if __name__ == "__main__":
    main()
