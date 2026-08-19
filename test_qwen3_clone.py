"""Qwen3-TTS 声音克隆实测脚本

用 Junhao.wav（MOSS 预生成样本）作为参考音频，
克隆该音色合成一段新文案，验证声音克隆效果。
"""
import os
import sys
import time

# 离线模式：模型已通过 ModelScope 下载到本地
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from krvoiceai.core.config import get_config, PROJECT_ROOT
from krvoiceai.modules.tts_engine import TTSEngine


def main():
    print("=" * 60)
    print("Qwen3-TTS 声音克隆实测")
    print("=" * 60)

    # 参考音频配置
    ref_audio_rel = "config/voices/samples/Junhao.wav"
    ref_text = "你好，这是音色试听"
    clone_text = "大家好，欢迎收听今天的节目。我是你们的主持人，今天要和大家聊一个非常有意思的话题。"

    # 设置配置
    cfg = get_config(reload=True)
    cfg.set("tts.provider", "qwen3_tts_clone")
    cfg.set("tts.qwen3_tts_clone.ref_audio", ref_audio_rel)
    cfg.set("tts.qwen3_tts_clone.ref_text", ref_text)
    cfg.set("tts.qwen3_tts_clone.language", "Chinese")

    print(f"\n参考音频: {ref_audio_rel}")
    print(f"参考文本: {ref_text}")
    print(f"克隆目标文本: {clone_text}")
    print(f"\n开始克隆合成（首次需加载 Base 模型，请耐心等待）...")

    engine = TTSEngine(config=cfg)
    engine.setup()

    output_path = PROJECT_ROOT / "workspace_data" / "qwen3_clone_demo" / "clone_output.wav"
    output_path.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    try:
        audio_path, duration, timestamps = engine.synthesize(
            text=clone_text,
            voice_id="cloned_junhao",
            output_path=output_path,
        )
        elapsed = time.time() - t0

        print("\n" + "=" * 60)
        print("声音克隆成功！")
        print("=" * 60)
        print(f"音频文件: {audio_path}")
        print(f"总时长: {duration:.2f} 秒")
        print(f"合成耗时: {elapsed:.2f} 秒")
        print(f"实时率(RTF): {elapsed / duration:.2f}（<1.0 表示快于实时）")

        print(f"\n分句时间戳:")
        for ts in timestamps:
            print(f"  [{ts['start']:.1f}-{ts['end']:.1f}s] {ts['text']}")

    except Exception as e:
        elapsed = time.time() - t0
        print(f"\n克隆失败（耗时 {elapsed:.1f}s）: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
