"""Qwen3-TTS 多人播客效果验证脚本

验证内容：
1. Qwen3-TTS CustomVoice 模型加载（首次需下载约1-2GB）
2. 多角色音色分配（3角色：Uncle_Fu/Vivian/Dylan）
3. 多人播客合成（含停顿、时间戳、字幕）
"""
import os
import sys
import time

# 配置 HuggingFace 国内镜像（加速模型下载）
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'
# 离线模式：模型已通过 ModelScope 下载到本地，避免 HF 网络请求
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['TRANSFORMERS_OFFLINE'] = '1'

# 确保使用项目虚拟环境
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from krvoiceai.core.config import get_config
from krvoiceai.modules.podcast_engine import PodcastEngine


def main():
    print("=" * 60)
    print("Qwen3-TTS 多人播客效果验证")
    print("=" * 60)

    # 简短多人播客剧本（3角色，6句，便于快速验证）
    script = """# 阿福（男）
# 薇薇安（女）
# 迪伦（男）
阿福: 大家好，欢迎收听今天的科技播客，我是主持人阿福。
薇薇安: 嗨，我是薇薇安，今天要聊的话题特别有意思。
迪伦: 对，我们今天要聊聊人工智能语音技术的最新进展。
薇薇安: 最近开源社区出了不少好东西，比如那个 Qwen3-TTS。
阿福: 没错，0.6B 的小模型就能做到 9 种音色，还挺惊艳的。
迪伦: 而且还支持声音克隆，3 秒样本就够了。"""

    # 角色到 Qwen3-TTS 音色的映射
    voice_map = {
        "阿福": "Uncle_Fu",    # 成熟醇厚男声（主持人）
        "薇薇安": "Vivian",     # 明亮年轻女声
        "迪伦": "Dylan",        # 青春北京男声
    }

    print(f"\n剧本角色数: {len(voice_map)}")
    print(f"音色映射: {voice_map}")
    print(f"\n开始合成（首次需下载模型，请耐心等待）...")

    config = get_config()
    engine = PodcastEngine(config=config)
    engine.setup()

    output_dir = os.path.join(os.path.dirname(__file__), "workspace_data", "qwen3_podcast_demo")

    t0 = time.time()
    result = engine.generate(
        script_text=script,
        voice_map=voice_map,
        output_dir=output_dir,
        progress_callback=lambda cur, total, msg: print(f"  [{cur}/{total}] {msg}"),
    )
    elapsed = time.time() - t0

    print("\n" + "=" * 60)
    print("合成完成！")
    print("=" * 60)
    print(f"音频文件: {result['audio_path']}")
    print(f"字幕文件: {result['srt_path']}")
    print(f"总时长: {result['total_duration']:.2f} 秒")
    print(f"片段数: {result['segment_count']}")
    print(f"合成耗时: {elapsed:.2f} 秒")
    if result['total_duration'] > 0:
        print(f"实时率(RTF): {elapsed / result['total_duration']:.2f}（<1.0 表示快于实时）")

    # 打印分段时间戳
    print(f"\n分段时间戳:")
    for seg in result['segments']:
        print(f"  [{seg['start']:.1f}-{seg['end']:.1f}s] {seg['role']}({seg['voice_id']}): {seg['text'][:30]}...")


if __name__ == "__main__":
    main()
