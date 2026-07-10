"""预生成内置音色试听样本

为 MOSS-TTS-Nano 的 6 个内置音色生成试听音频，
保存到 config/voices/samples/{voice_id}.wav。

运行后，前端点击试听按钮时直接返回预生成文件（<1秒），
无需每次调用 MOSS-TTS-Nano 实时合成（30-60秒）。

用法：
  cd KrVoiceAI
  python scripts/pregenerate_voice_samples.py
"""
import sys
import shutil
from pathlib import Path

# 确保项目根目录在 sys.path 中
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from krvoiceai.app import EnlyAI

SAMPLE_TEXT = "你好，这是音色试听，欢迎体验 EnlyAI 智能语音合成。"
BUILTIN_VOICES = ["Junhao", "Trump", "Ava", "Bella", "Adam", "Nathan"]
SAMPLES_DIR = project_root / "config" / "voices" / "samples"


def main():
    print("=" * 60)
    print("预生成内置音色试听样本")
    print(f"样本目录: {SAMPLES_DIR}")
    print(f"试听文本: {SAMPLE_TEXT}")
    print("=" * 60)

    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)

    # 检查是否所有样本已存在
    existing = [v for v in BUILTIN_VOICES if (SAMPLES_DIR / f"{v}.wav").exists()]
    if len(existing) == len(BUILTIN_VOICES):
        print(f"\n所有 {len(BUILTIN_VOICES)} 个音色样本已存在，无需重新生成。")
        for v in BUILTIN_VOICES:
            size = (SAMPLES_DIR / f"{v}.wav").stat().st_size
            print(f"  {v}.wav  ({size/1024:.0f} KB)")
        return

    print(f"\n需生成 {len(BUILTIN_VOICES) - len(existing)} 个新样本...")

    # 初始化 KrVoiceAI 应用
    print("\n初始化 TTS 引擎...")
    app = EnlyAI()
    engine = app.modules.get("tts")
    if engine is None:
        print("ERROR: TTS 引擎未初始化")
        sys.exit(1)

    import time
    for voice_id in BUILTIN_VOICES:
        sample_path = SAMPLES_DIR / f"{voice_id}.wav"
        if sample_path.exists():
            print(f"  [跳过] {voice_id} 已存在")
            continue

        print(f"  [生成] {voice_id}...", end=" ", flush=True)
        t0 = time.time()
        try:
            tmp_path = project_root / "workspace_data" / "tmp" / f"voice_sample_{voice_id}.wav"
            tmp_path.parent.mkdir(parents=True, exist_ok=True)
            audio_path, duration, _ = engine.synthesize(
                SAMPLE_TEXT, voice_id, tmp_path,
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
    for v in BUILTIN_VOICES:
        p = SAMPLES_DIR / f"{v}.wav"
        if p.exists():
            print(f"  {v}.wav  ({p.stat().st_size/1024:.0f} KB)")
        else:
            print(f"  {v}.wav  [缺失]")
    print("=" * 60)


if __name__ == "__main__":
    main()
