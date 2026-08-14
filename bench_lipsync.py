#!/usr/bin/env python3
"""LipSync (LatentSync) 性能基准测试

目标：评估 LatentSync 1.5 在 RTX 5060 8GB 上的端到端延迟和 RTF

LatentSync 是扩散模型 LipSync（非实时），目标为"可接受离线生成延迟"：
- fast 模式（128/10）：RTF < 2（接近实时，适合短平快场景）
- high_quality 模式（256/25）：RTF < 8（高质量，适合精品内容）
- 输出视频：25fps，256x256，正常解码

对比 MuseTalk（30fps，RTF~1）和 Wav2Lip（RTF~0.5）：
- LatentSync 唇形质量更高（扩散模型 vs GAN）
- 速度较慢，但 8GB 显存可跑
- 适合"质量优先"的离线生成场景
"""
import sys
import time
import json
import wave
import subprocess
from pathlib import Path

import httpx

# 配置
LATENTSYNC_URL = "http://localhost:8011"
AVATAR_VIDEO = Path("./config/avatars/e2e_anchor/reference_video.mp4")
AVATAR_IMAGE = Path("./config/presets/avatars/anchor_female_pro.jpg")
# 选用较长的 TTS 输出音频（5.96s）作为测试素材
AUDIO_FILE = Path("./workspace_data/e2e_test/tts_cosyvoice.wav")
AUDIO_FILE_SHORT = Path("./config/voices/anchor_female/sample.wav")

# 测试配置矩阵（不同 inference_steps 和 resolution）
TEST_CONFIGS = [
    {"label": "fast(128/10)", "inference_steps": 10, "resolution": 128},
    {"label": "balanced(256/20)", "inference_steps": 20, "resolution": 256},
    {"label": "high_quality(256/25)", "inference_steps": 25, "resolution": 256},
]


def get_wav_duration(path: Path) -> float:
    """读取 WAV 文件时长（不依赖 ffprobe）"""
    try:
        with wave.open(str(path), "rb") as wf:
            return wf.getnframes() / wf.getframerate()
    except Exception as e:
        print(f"  [WARN] 读取 WAV 时长失败: {e}")
        return 0.0


def get_video_info(path: Path) -> dict:
    """通过 ffprobe 获取视频信息"""
    info = {"duration": 0.0, "fps": 0.0, "width": 0, "height": 0}
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=width,height,r_frame_rate,duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        data = json.loads(result.stdout)
        stream = data.get("streams", [{}])[0]
        info["width"] = int(stream.get("width", 0))
        info["height"] = int(stream.get("height", 0))
        fps_str = stream.get("r_frame_rate", "0/1")
        num, den = fps_str.split("/")
        info["fps"] = float(num) / float(den) if float(den) != 0 else 0.0
        info["duration"] = float(stream.get("duration", 0))
    except Exception as e:
        print(f"  [WARN] ffprobe 获取视频信息失败: {e}")
    return info


def benchmark_lipsync(cfg: dict, audio_path: Path, label_suffix: str = "") -> dict:
    """执行单次 LipSync 基准测试"""
    label = f"{cfg['label']}{label_suffix}"
    print(f"\n=== {label} ===")
    print(f"  steps={cfg['inference_steps']} res={cfg['resolution']}")

    if not AVATAR_VIDEO.exists() or not audio_path.exists():
        print(f"  [SKIP] 缺少测试素材 video={AVATAR_VIDEO.exists()} audio={audio_path.exists()}")
        return {}

    audio_dur = get_wav_duration(audio_path)
    print(f"  音频时长: {audio_dur:.2f}s")

    files = {
        "audio": (audio_path.name, open(audio_path, "rb"), "audio/wav"),
        "video": (AVATAR_VIDEO.name, open(AVATAR_VIDEO, "rb"), "video/mp4"),
    }
    data = {
        "inference_steps": str(cfg["inference_steps"]),
        "resolution": str(cfg["resolution"]),
        "seed": "-1",
    }

    output_path = Path(f"./workspace_data/bench/lipsync_{label}.mp4")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        t0 = time.time()
        with httpx.Client(timeout=900.0) as client:
            resp = client.post(
                f"{LATENTSYNC_URL}/api/avatar/generate",
                files=files, data=data,
                headers={"Accept": "video/mp4"},
            )
        elapsed = time.time() - t0

        if resp.status_code != 200:
            print(f"  [ERROR] HTTP {resp.status_code}: {resp.text[:300]}")
            return {}
        video_bytes = resp.content
        output_path.write_bytes(video_bytes)
        print(f"  处理耗时: {elapsed:.2f}s")
        print(f"  输出大小: {len(video_bytes)/1024:.1f} KB")

        # 分析输出视频
        vinfo = get_video_info(output_path)
        rtf = elapsed / audio_dur if audio_dur > 0 else float("inf")
        video_rtf = elapsed / vinfo["duration"] if vinfo["duration"] > 0 else float("inf")

        print(f"  输出视频: {vinfo['width']}x{vinfo['height']} @ {vinfo['fps']:.1f}fps  时长={vinfo['duration']:.2f}s")
        print(f"  RTF(处理/音频): {rtf:.3f}")
        print(f"  RTF(处理/视频): {video_rtf:.3f}")

        # 达标判定：fast 模式 RTF<2，high_quality 模式 RTF<8
        if cfg["inference_steps"] <= 10 and cfg["resolution"] <= 128:
            ok = "✓" if rtf < 2 else "✗"
            print(f"  达标判定 (fast, RTF<2): {ok}")
        elif cfg["inference_steps"] >= 25:
            ok = "✓" if rtf < 8 else "✗"
            print(f"  达标判定 (high_quality, RTF<8): {ok}")
        else:
            ok = "✓" if rtf < 5 else "✗"
            print(f"  达标判定 (balanced, RTF<5): {ok}")

        return {
            "label": label,
            "steps": cfg["inference_steps"],
            "resolution": cfg["resolution"],
            "audio_duration": audio_dur,
            "elapsed": elapsed,
            "rtf": rtf,
            "output_size": len(video_bytes),
            "video_width": vinfo["width"],
            "video_height": vinfo["height"],
            "video_fps": vinfo["fps"],
            "video_duration": vinfo["duration"],
        }
    except Exception as e:
        print(f"  [ERROR] 请求失败: {e}")
        return {}
    finally:
        for _, fobj, _ in files.values():
            fobj.close()


def main():
    print("LatentSync 唇形同步基准测试\n")
    print(f"服务地址: {LATENTSYNC_URL}")
    print(f"参考视频: {AVATAR_VIDEO} (12.03s)")
    print(f"音频文件(长): {AUDIO_FILE}")
    print(f"音频文件(短): {AUDIO_FILE_SHORT}\n")

    # 健康检查
    try:
        r = httpx.get(f"{LATENTSYNC_URL}/api/health", timeout=10)
        health = r.json()
        print(f"健康检查: {health}\n")
        if not health.get("model_loaded"):
            print("[WARN] 模型未加载，首次请求将触发加载（耗时 30-60s）")
    except Exception as e:
        print(f"[ERROR] LatentSync 服务不可用: {e}")
        return

    # 测试 1：长音频 + 三种配置
    print("=" * 70)
    print(f"测试集 A: 长音频 ({get_wav_duration(AUDIO_FILE):.2f}s) + 三种配置")
    print("=" * 70)
    results = []
    for cfg in TEST_CONFIGS:
        r = benchmark_lipsync(cfg, AUDIO_FILE, "_long")
        if r:
            results.append(r)

    # 测试 2：短音频 + fast 模式（验证短音频场景）
    print("\n" + "=" * 70)
    print(f"测试集 B: 短音频 ({get_wav_duration(AUDIO_FILE_SHORT):.2f}s) + fast 模式")
    print("=" * 70)
    r = benchmark_lipsync(TEST_CONFIGS[0], AUDIO_FILE_SHORT, "_short")
    if r:
        results.append(r)

    # 汇总
    if results:
        print("\n" + "=" * 80)
        print("LatentSync 基准测试汇总")
        print("=" * 80)
        print(f"{'配置':<25} {'音频':<8} {'耗时':<8} {'RTF':<8} {'分辨率':<10} {'FPS':<6} {'达标':<6}")
        print("-" * 80)
        for r in results:
            if r["steps"] <= 10 and r["resolution"] <= 128:
                ok = "✓" if r["rtf"] < 2 else "✗"
            elif r["steps"] >= 25:
                ok = "✓" if r["rtf"] < 8 else "✗"
            else:
                ok = "✓" if r["rtf"] < 5 else "✗"
            res_str = f"{r['video_width']}x{r['video_height']}"
            print(f"{r['label']:<25} {r['audio_duration']:<8.2f} {r['elapsed']:<8.2f} {r['rtf']:<8.3f} {res_str:<10} {r['video_fps']:<6.1f} {ok:<6}")

        # 性能分析
        print("\n性能分析:")
        long_results = [r for r in results if r["label"].endswith("_long")]
        if long_results:
            print(f"  长音频 ({long_results[0]['audio_duration']:.1f}s) 性能:")
            for r in long_results:
                if r["steps"] <= 10:
                    mode = "fast"
                    target = 2
                elif r["steps"] >= 25:
                    mode = "high_quality"
                    target = 8
                else:
                    mode = "balanced"
                    target = 5
                ok = r["rtf"] < target
                print(f"    {mode}: RTF={r['rtf']:.2f} 耗时={r['elapsed']:.1f}s "
                      f"输出={r['video_width']}x{r['video_height']}@{r['video_fps']:.0f}fps "
                      f"目标 RTF<{target} {'✓' if ok else '✗'}")

        print("\n说明:")
        print("  - LatentSync 是扩散模型 LipSync，非实时设计，目标为'可接受离线生成延迟'")
        print("  - fast 模式（128/10）：追求速度，适合短平快场景，目标 RTF<2")
        print("  - high_quality 模式（256/25）：追求质量，适合精品内容，目标 RTF<8")
        print("  - 对比 MuseTalk（RTF~1）和 Wav2Lip（RTF~0.5），LatentSync 唇形质量更高")
        print("  - 8GB 显存可跑 256 分辨率，12GB+ 显存可跑 512 分辨率")


if __name__ == "__main__":
    main()
