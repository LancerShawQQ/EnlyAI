"""为已注册的克隆音色 Lancer 补生成试听样本

由于 Lancer 在预生成机制实现前就已注册，没有预生成样本。
此脚本一次性补生成，之后试听即可即时返回。
"""
import sys
import shutil
import time
from pathlib import Path

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from krvoiceai.app import EnlyAI

SAMPLE_TEXT = "大家好，欢迎收听本期播客，今天我们来聊一个有趣的话题。"
VOICE_ID = "Lancer"
SAMPLES_DIR = project_root / "config" / "voices" / "samples"

def main():
    SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    sample_path = SAMPLES_DIR / f"{VOICE_ID}.wav"

    print(f"为克隆音色 {VOICE_ID} 补生成试听样本...")
    print(f"样本路径: {sample_path}")
    print("=" * 60)

    app = EnlyAI()
    engine = app.modules.get("tts")
    if engine is None:
        print("ERROR: TTS 引擎未初始化")
        sys.exit(1)

    tmp_path = project_root / "workspace_data" / "tmp" / f"voice_sample_{VOICE_ID}.wav"
    tmp_path.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    try:
        audio_path, duration, _ = engine.synthesize(
            SAMPLE_TEXT, VOICE_ID, tmp_path,
        )
        shutil.copy2(str(audio_path), str(sample_path))
        elapsed = time.time() - t0
        size = sample_path.stat().st_size
        print(f"完成！耗时 {elapsed:.1f}s, 大小 {size/1024:.0f}KB, 音频时长 {duration:.1f}s")
        print(f"样本已保存到: {sample_path}")
        print(f"\n现在前端试听 {VOICE_ID} 即可即时返回（<1秒）")
    except Exception as e:
        print(f"失败: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
