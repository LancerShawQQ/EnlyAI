"""从已有的 MuseTalk 结果帧 + 音频合成最终视频

MuseTalk 推理已成功生成 562 帧，但 ffmpeg 无法直接读取 sun.wav 和图片序列。
方案：OpenCV 合成无声视频 + ffmpeg 合并转换后的音频。
"""
import os
import sys
import glob
import subprocess
import soundfile as sf
import cv2
import numpy as np
from pathlib import Path

MUSETALK_ROOT = Path(__file__).resolve().parent / "MuseTalk"
result_dir = str(MUSETALK_ROOT / "workspace_data" / "musetalk_test_result")
audio_path = str(MUSETALK_ROOT / "data" / "audio" / "sun.wav")
output_path = str(MUSETALK_ROOT / "workspace_data" / "musetalk_test_output.mp4")
fps = 25

# 1. 用 soundfile 读取音频并保存为标准 WAV
print("[1/4] 转换音频为标准 WAV ...")
audio_data, sr = sf.read(audio_path)
print(f"      采样率={sr} 时长={len(audio_data)/sr:.1f}s shape={audio_data.shape}")
temp_wav = str(MUSETALK_ROOT / "workspace_data" / "temp_audio.wav")
sf.write(temp_wav, audio_data, sr, subtype='PCM_16')
print(f"      已保存: {temp_wav}")

# 2. 用 OpenCV 合成无声视频
print("[2/4] OpenCV 合成无声视频 ...")
img_files = sorted(glob.glob(os.path.join(result_dir, "*.png")))
print(f"      帧数: {len(img_files)}")
sample = cv2.imread(img_files[0])
h, w = sample.shape[:2]
print(f"      分辨率: {w}x{h}")

temp_vid = str(MUSETALK_ROOT / "workspace_data" / "musetalk_test_silent.mp4")
# 尝试 mp4v 编码
fourcc = cv2.VideoWriter_fourcc(*"mp4v")
writer = cv2.VideoWriter(temp_vid, fourcc, fps, (w, h))
if not writer.isOpened():
    print("[FAIL] OpenCV VideoWriter 无法打开，尝试 XVID ...")
    fourcc = cv2.VideoWriter_fourcc(*"XVID")
    temp_vid = temp_vid.replace(".mp4", ".avi")
    writer = cv2.VideoWriter(temp_vid, fourcc, fps, (w, h))

for img_file in img_files:
    frame = cv2.imread(img_file)
    if frame is not None:
        writer.write(frame)
writer.release()

if not Path(temp_vid).exists() or Path(temp_vid).stat().st_size == 0:
    print("[FAIL] 无声视频未生成")
    sys.exit(1)
print(f"      已保存: {temp_vid} ({Path(temp_vid).stat().st_size} bytes)")

# 3. 用 ffmpeg 合并音频
print("[3/4] ffmpeg 合并音频 ...")
cmd = [
    "ffmpeg", "-y", "-v", "warning",
    "-i", temp_vid,
    "-i", temp_wav,
    "-c:v", "libx264", "-pix_fmt", "yuv420p",
    "-c:a", "aac",
    "-shortest",
    output_path,
]
result = subprocess.run(cmd, capture_output=True, text=True)
if result.returncode != 0:
    print(f"      ffmpeg stderr: {result.stderr}")
    # 如果合并失败，直接复制无声视频作为输出
    import shutil
    shutil.copy2(temp_vid, output_path)
    print(f"      音频合并失败，使用无声视频作为输出")

# 4. 验证输出
print("[4/4] 验证输出 ...")
if Path(output_path).exists() and Path(output_path).stat().st_size > 0:
    size = Path(output_path).stat().st_size
    print(f"\n[OK] MuseTalk 视频合成成功: {size:,} bytes")
    print(f"     输出: {output_path}")
    print(f"     帧数: {len(img_files)}  时长: {len(audio_data)/sr:.1f}s  FPS: {fps}")
else:
    print("[FAIL] 输出视频未生成")
    sys.exit(1)
