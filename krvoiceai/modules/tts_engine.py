"""TTS 声音克隆模块

三种 provider：
- gpt_sovits: 调用云端 GPT-SoVITS API（声音克隆）
- edge_tts:   使用 edge-tts 标准音色（无克隆，CPU 可跑）
- mock:       生成静音 wav（保证流程可跑通）

输出：wav 音频文件 + 时长 + 分句时间戳
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
from pathlib import Path
from typing import Any

from ..core.audio_utils import (
    estimate_speech_duration,
    generate_silent_wav,
    get_wav_duration,
    split_text_to_segments,
)
from ..core.base_module import BaseModule, JobContext, ModuleResult
from ..core.gpu_runner import GPURunner


class TTSEngine(BaseModule):
    """TTS 声音克隆/合成模块"""

    name = "tts"
    requires_gpu = True  # 真实模式需要 GPU

    def __init__(self, config=None, gpu_runner: GPURunner | None = None):
        super().__init__(config)
        self.provider = self.config.get("tts.provider", "mock")
        self.api_base = self.config.get("tts.api_base", "")
        self.edge_voice = self.config.get("tts.edge_voice", "zh-CN-XiaoxiaoNeural")
        self.voices_dir = Path(self.config.get("tts.voices_dir", "./config/voices"))
        self.default_voice = self.config.get("tts.default_voice", "default")
        self.gpu = gpu_runner or GPURunner()

    def setup(self) -> None:
        # 判断真实可用性
        if self.provider == "gpt_sovits":
            available = self.gpu.health_check_tts()
            if not available:
                self.logger.warning(
                    "GPT-SoVITS 服务不可用，降级到 mock 模式"
                )
                self.provider = "mock"
        self.logger.info(f"TTS 模块初始化 provider={self.provider}")
        super().setup()

    def run(self, ctx: JobContext) -> ModuleResult:
        """根据 ctx.script_text 合成音频"""
        text = ctx.script_text or ctx.input_script
        if not text:
            return ModuleResult(success=False, error="无文案可合成")

        voice_id = ctx.voice_id or self.default_voice
        output_path = ctx.work_dir / "tts_output.wav"

        try:
            start = time.time()
            if self.provider == "gpt_sovits":
                audio_path, duration, timestamps = self._synth_gpt_sovits(
                    text, voice_id, output_path
                )
            elif self.provider == "edge_tts":
                audio_path, duration, timestamps = self._synth_edge(
                    text, voice_id, output_path
                )
            else:
                audio_path, duration, timestamps = self._synth_mock(
                    text, voice_id, output_path
                )

            ctx.audio_path = audio_path
            ctx.audio_duration = duration
            ctx.metadata["tts_timestamps"] = timestamps
            ctx.metadata["tts_provider"] = self.provider

            return ModuleResult(
                success=True,
                data={
                    "audio_path": str(audio_path),
                    "duration": duration,
                    "voice_id": voice_id,
                    "provider": self.provider,
                    "segments": len(timestamps),
                },
            )
        except Exception as e:
            return ModuleResult(success=False, error=str(e))

    def _synth_gpt_sovits(
        self, text: str, voice_id: str, output_path: Path
    ) -> tuple[Path, float, list[dict]]:
        """调用 GPT-SoVITS 云端 API"""
        self.logger.info(f"GPT-SoVITS 合成 voice={voice_id} text_len={len(text)}")

        # 分句合成，便于时间戳对齐
        segments = split_text_to_segments(text)
        timestamps: list[dict] = []
        combined_audio = bytearray()
        sample_rate = 32000
        offset = 0.0

        for seg in segments:
            payload = {
                "text": seg,
                "voice_id": voice_id,
                "speed": 1.0,
            }
            resp = self.gpu.call_tts(payload)
            # 假设返回 base64 编码的 wav
            audio_b64 = resp.get("audio_base64") or resp.get("data", {}).get("audio_base64")
            if not audio_b64:
                raise RuntimeError(f"GPT-SoVITS 返回无音频数据: {resp}")
            audio_bytes = base64.b64decode(audio_b64)
            combined_audio.extend(audio_bytes)
            seg_duration = resp.get("duration", estimate_speech_duration(seg))
            timestamps.append({
                "text": seg,
                "start": round(offset, 3),
                "end": round(offset + seg_duration, 3),
            })
            offset += seg_duration
            if "sample_rate" in resp:
                sample_rate = resp["sample_rate"]

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(bytes(combined_audio))
        duration = get_wav_duration(output_path) if output_path.exists() else offset

        self.logger.info(
            f"GPT-SoVITS 合成完成 duration={duration:.2f}s segments={len(segments)}"
        )
        return output_path, duration, timestamps

    def _synth_edge(
        self, text: str, voice_id: str, output_path: Path
    ) -> tuple[Path, float, list[dict]]:
        """使用 edge-tts 合成（标准音色，无克隆）"""
        try:
            import edge_tts
        except ImportError as e:
            self.logger.warning("edge-tts 未安装，降级到 mock")
            return self._synth_mock(text, voice_id, output_path)

        self.logger.info(f"edge-tts 合成 voice={self.edge_voice}")

        async def _synth():
            communicate = edge_tts.Communicate(text, self.edge_voice)
            await communicate.save(str(output_path))

        asyncio.run(_synth())

        # edge-tts 不直接返回时间戳，按分句估算
        segments = split_text_to_segments(text)
        timestamps = []
        offset = 0.0
        for seg in segments:
            seg_dur = estimate_speech_duration(seg)
            timestamps.append({
                "text": seg,
                "start": round(offset, 3),
                "end": round(offset + seg_dur, 3),
            })
            offset += seg_dur

        duration = get_wav_duration(output_path) if output_path.exists() else offset
        return output_path, duration, timestamps

    def _synth_mock(
        self, text: str, voice_id: str, output_path: Path
    ) -> tuple[Path, float, list[dict]]:
        """Mock 模式：生成静音 wav，时长按文本估算"""
        duration = estimate_speech_duration(text)
        self.logger.info(
            f"Mock TTS 生成静音音频 voice={voice_id} "
            f"duration={duration:.2f}s text_len={len(text)}"
        )
        info = generate_silent_wav(output_path, duration)

        # 生成分句时间戳
        segments = split_text_to_segments(text)
        timestamps = []
        offset = 0.0
        total_chars = sum(len(s) for s in segments) or 1
        for seg in segments:
            seg_dur = duration * len(seg) / total_chars
            timestamps.append({
                "text": seg,
                "start": round(offset, 3),
                "end": round(offset + seg_dur, 3),
            })
            offset += seg_dur

        return info.path, info.duration, timestamps

    def register_voice(self, voice_id: str, sample_audio: Path) -> bool:
        """注册音色"""
        sample_audio = Path(sample_audio)
        voices_dir = Path(self.config.get("tts.voices_dir", "./config/voices"))
        voice_dir = voices_dir / voice_id
        voice_dir.mkdir(parents=True, exist_ok=True)

        if self.provider != "gpt_sovits":
            # Mock/edge 模式：本地保存样本音频
            import shutil
            dest = voice_dir / f"sample{sample_audio.suffix or '.wav'}"
            shutil.copy2(sample_audio, dest)
            self.logger.info(f"本地音色注册成功: {voice_id} -> {dest}")
            return True

        try:
            with open(sample_audio, "rb") as f:
                audio_b64 = base64.b64encode(f.read()).decode()
            resp = self.gpu.call_tts_register({
                "voice_id": voice_id,
                "sample_audio_base64": audio_b64,
            })
            # 云端注册成功后也本地保存一份
            if resp.get("success"):
                import shutil
                dest = voice_dir / f"sample{sample_audio.suffix or '.wav'}"
                shutil.copy2(sample_audio, dest)
            return resp.get("success", False)
        except Exception as e:
            self.logger.error(f"音色注册失败: {e}")
            return False
