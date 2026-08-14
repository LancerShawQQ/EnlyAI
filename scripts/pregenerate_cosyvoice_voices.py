"""预生成 CosyVoice3 参考音色样本

为每个预置音色生成参考音频（sample.wav + ref_text.txt），
用户在 UI 试听后选择音色，CosyVoice 服务端用这些样本做零样本声音克隆。

生成方式：使用 edge-tts（微软神经语音，免费）生成高质量参考音频。
用户可后续替换为自己的录音（放入 config/voices/{voice_id}/sample.wav 即可）。

用法：
    conda run -n krvoiceai python scripts/pregenerate_cosyvoice_voices.py
    conda run -n krvoiceai python scripts/pregenerate_cosyvoice_voices.py --force  # 重新生成

输出：
    config/voices/anchor_female/sample.wav + ref_text.txt
    config/voices/anchor_male/sample.wav + ref_text.txt
    ...
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 预置音色定义（与 krvoiceai/modules/tts_engine.py 中 COSYVOICE_PRESET_VOICES 保持一致）
# 自包含定义，避免导入 tts_engine 触发 loguru 等重依赖
PRESET_VOICES = {
    "anchor_female": {
        "ref_text": "大家好，欢迎收看今天的节目。",
        "edge_voice": "zh-CN-XiaoxiaoNeural",    # 晓晓，标准女主播
    },
    "anchor_male": {
        "ref_text": "大家好，欢迎收看今天的节目。",
        "edge_voice": "zh-CN-YunjianNeural",        # 云健，沉稳男主播
    },
    "narrator_female": {
        "ref_text": "在这个美好的日子里，让我们一起探索。",
        "edge_voice": "zh-CN-XiaoyiNeural",     # 晓伊，温暖女声
    },
    "narrator_male": {
        "ref_text": "在这个美好的日子里，让我们一起探索。",
        "edge_voice": "zh-CN-YunxiNeural",        # 云希，磁性男声
    },
    "seller_energetic": {
        "ref_text": "家人们，今天给大家带来一个超级划算的好物！",
        "edge_voice": "zh-CN-XiaoxuanNeural",  # 晓萱，活力女声
    },
    "english_female": {
        "ref_text": "Hello, welcome to today's program.",
        "edge_voice": "en-US-JennyNeural",       # Jenny, natural female
    },
    "english_male": {
        "ref_text": "Hello, welcome to today's program.",
        "edge_voice": "en-US-GuyNeural",           # Guy, natural male
    },
}


async def generate_voice_sample(
    voice_id: str,
    edge_voice: str,
    ref_text: str,
    output_dir: Path,
) -> bool:
    """用 edge-tts 生成单个参考音色样本

    Args:
        voice_id: 音色 ID（目录名）
        edge_voice: edge-tts 语音名称
        ref_text: 参考文本（与音频内容一致）
        output_dir: 输出根目录（config/voices）

    Returns:
        True 成功，False 失败
    """
    import edge_tts

    voice_dir = output_dir / voice_id
    voice_dir.mkdir(parents=True, exist_ok=True)

    sample_path = voice_dir / "sample.wav"
    ref_text_path = voice_dir / "ref_text.txt"

    # 已存在则跳过（除非 --force）
    if sample_path.exists() and "--force" not in sys.argv:
        print(f"  [跳过] {voice_id} 已有 sample.wav（用 --force 重新生成）")
        return True

    print(f"  [生成] {voice_id} edge_voice={edge_voice} text='{ref_text[:30]}...'")

    try:
        communicate = edge_tts.Communicate(ref_text, edge_voice)
        # edge-tts 输出 mp3，先存 mp3 再用 soundfile 转 wav
        mp3_path = voice_dir / "sample.mp3"
        await communicate.save(str(mp3_path))

        # mp3 → wav（16kHz mono，CosyVoice 要求 16kHz 参考音频）
        try:
            import soundfile as sf
            import librosa
            data, sr = librosa.load(str(mp3_path), sr=16000, mono=True)
            sf.write(str(sample_path), data, sr, subtype="PCM_16")
            mp3_path.unlink()  # 删除临时 mp3
        except ImportError:
            # 无 librosa，直接用 mp3（CosyVoice 也能处理 mp3）
            print(f"    [警告] librosa 未安装，保留 mp3 格式")
            sample_path = mp3_path

        # 写 ref_text.txt
        ref_text_path.write_text(ref_text, encoding="utf-8")

        print(f"    [完成] {sample_path.name} ({sample_path.stat().st_size // 1024} KB)")
        return True

    except Exception as e:
        print(f"    [失败] {voice_id}: {e}")
        return False


async def main():
    print("=" * 60)
    print("CosyVoice3 参考音色样本预生成")
    print("=" * 60)

    voices_dir = PROJECT_ROOT / "config" / "voices"
    voices_dir.mkdir(parents=True, exist_ok=True)
    print(f"输出目录: {voices_dir}")
    print(f"音色数量: {len(PRESET_VOICES)}")
    print()

    # 检查 edge-tts 是否可用
    try:
        import edge_tts  # noqa: F401
    except ImportError:
        print("[ERROR] edge-tts 未安装，请运行: pip install edge-tts")
        sys.exit(1)

    success_count = 0
    fail_count = 0

    for voice_id, voice_info in PRESET_VOICES.items():
        edge_voice = voice_info.get("edge_voice")
        if not edge_voice:
            print(f"  [跳过] {voice_id} 无对应的 edge-tts 语音映射")
            continue

        ref_text = voice_info.get("ref_text", "大家好，欢迎收看今天的节目。")
        ok = await generate_voice_sample(voice_id, edge_voice, ref_text, voices_dir)
        if ok:
            success_count += 1
        else:
            fail_count += 1

    print()
    print("=" * 60)
    print(f"预生成完成: 成功 {success_count} 个, 失败 {fail_count} 个")
    print("=" * 60)
    print()
    print("参考音色样本已保存到 config/voices/")
    print("用户可在 UI 设置中选择 TTS provider=cosyvoice 后试听这些音色")
    print("如需自定义音色，将你的录音（3-10s 清晰人声）放入")
    print("config/voices/{自定义音色名}/sample.wav + ref_text.txt")
    print()
    print("下一步：启动 CosyVoice 服务")
    print("  conda activate CosyVoice")
    print("  cd CosyVoice")
    print("  python ../krvoiceai/modules/cosyvoice_server.py --port 8012")


if __name__ == "__main__":
    asyncio.run(main())
