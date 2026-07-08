"""TTS 声音克隆模块

五种 provider：
- moss_nano:  本地 MOSS-TTS-Nano ONNX（CPU 声音克隆，0.1B 模型，5s 样本零克隆）
- mimo:       调用小米 MiMo TTS API（OpenAI 兼容 chat/completions 端点）
- gpt_sovits: 调用云端 GPT-SoVITS API（声音克隆）
- edge_tts:   使用 edge-tts 标准音色（无克隆，CPU 可跑）
- mock:       生成静音 wav（保证流程可跑通）

输出：wav/mp3 音频文件 + 时长 + 分句时间戳
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
from pathlib import Path
from typing import Any

import httpx

from ..core.audio_utils import (
    estimate_speech_duration,
    generate_silent_wav,
    get_wav_duration,
    split_text_to_segments,
)
from ..core.base_module import BaseModule, JobContext, ModuleResult
from ..core.gpu_runner import GPURunner
from ..core.ffmpeg_utils import FFmpegRunner


# edge-tts 情感 -> rate/pitch 映射表（emotion 优先，覆盖 config 派生的 rate/pitch）
EMOTION_EDGE_MAP = {
    'neutral':  {'rate': '+0%',  'pitch': '+0Hz'},   # 中性：默认
    'calm':     {'rate': '-10%', 'pitch': '-2Hz'},   # 平静：稍慢稍低
    'excited':  {'rate': '+25%', 'pitch': '+5Hz'},   # 激昂：明显加快升高（+15%→+25%，让激昂风格更显著）
    'gentle':   {'rate': '-5%',  'pitch': '+1Hz'},   # 温柔：稍慢微升
    'serious':  {'rate': '-8%',  'pitch': '-3Hz'},   # 严肃：稍慢偏低
    'cheerful': {'rate': '+12%', 'pitch': '+3Hz'},   # 欢快：稍快微升（+8%→+12%，增强欢快感）
}


class TTSEngine(BaseModule):
    """TTS 声音克隆/合成模块"""

    name = "tts"
    requires_gpu = True  # 真实模式需要 GPU（moss_nano/edge_tts/mock 可纯 CPU 运行）

    # 纯 CPU 可跑的 provider（不需要云端 GPU）
    CPU_ONLY_PROVIDERS = {"moss_nano", "edge_tts", "mock"}

    def __init__(self, config=None, gpu_runner: GPURunner | None = None):
        super().__init__(config)
        self.provider = self.config.get("tts.provider", "mock")
        self.api_base = self.config.get("tts.api_base", "")
        self.api_key = self.config.get("tts.api_key", "")
        self.edge_voice = self.config.get("tts.edge_voice", "zh-CN-XiaoxiaoNeural")
        self.voices_dir = Path(self.config.get("tts.voices_dir", "./config/voices"))
        self.default_voice = self.config.get("tts.default_voice", "default")
        self.timeout = self.config.get("tts.timeout", 120)
        self.gpu = gpu_runner or GPURunner()
        # MOSS-TTS-Nano 运行时（懒加载，首次 moss_nano 合成时初始化）
        self._moss_runtime = None
        # FFmpeg 工具（用于音频后处理：静音消除/人声增强）
        self.ffmpeg = FFmpegRunner()

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

        # 从 audio 配置段读取语速/音量/音高/情感（UI 持久化到此）
        audio_cfg = self.config.get("audio", {}) or {}
        speed = audio_cfg.get("speed")
        volume = audio_cfg.get("volume")
        pitch = audio_cfg.get("pitch")
        emotion = audio_cfg.get("emotion")
        # 类型转换与边界保护
        try:
            speed = float(speed) if speed is not None else None
        except (TypeError, ValueError):
            speed = None
        try:
            volume = int(volume) if volume is not None else None
        except (TypeError, ValueError):
            volume = None
        try:
            pitch = int(pitch) if pitch is not None else None
        except (TypeError, ValueError):
            pitch = None

        try:
            start = time.time()
            if self.provider == "moss_nano":
                audio_path, duration, timestamps = self._synth_moss_nano(
                    text, voice_id, output_path, speed, volume, pitch, emotion
                )
            elif self.provider == "mimo":
                audio_path, duration, timestamps = self._synth_mimo(
                    text, voice_id, output_path, speed, volume, pitch, emotion
                )
            elif self.provider == "gpt_sovits":
                audio_path, duration, timestamps = self._synth_gpt_sovits(
                    text, voice_id, output_path, speed, volume, pitch, emotion
                )
            elif self.provider == "edge_tts":
                audio_path, duration, timestamps = self._synth_edge(
                    text, voice_id, output_path, speed, volume, pitch, emotion
                )
            else:
                audio_path, duration, timestamps = self._synth_mock(
                    text, voice_id, output_path, speed, volume, pitch, emotion
                )

            # 音频后处理：静音消除/人声增强
            remove_silence = bool(audio_cfg.get("remove_silence", False))
            voice_enhance = bool(audio_cfg.get("voice_enhance", False))
            pause_duration = float(audio_cfg.get("pause_duration", 0) or 0)

            if remove_silence or voice_enhance:
                try:
                    processed_path = ctx.work_dir / "tts_post_processed.wav"
                    self.ffmpeg.post_process_audio(
                        input_audio=audio_path,
                        output_audio=processed_path,
                        remove_silence=remove_silence,
                        pause_duration=pause_duration,
                        voice_enhance=voice_enhance,
                    )
                    # 重新计算时长
                    import subprocess as _sp
                    r = _sp.run(
                        [self.ffmpeg.ffprobe, "-v", "error", "-show_entries", "format=duration",
                         "-of", "csv=p=0", str(processed_path)],
                        capture_output=True, text=True,
                    )
                    if r.stdout.strip():
                        duration = float(r.stdout.strip())
                    audio_path = processed_path
                    self.logger.info(f"音频后处理完成: remove_silence={remove_silence}, voice_enhance={voice_enhance}, duration={duration:.2f}s")
                except Exception as e:
                    self.logger.warning(f"音频后处理失败，使用原始音频: {e}")
            elif pause_duration > 0:
                self.logger.info(
                    f"pause_duration={pause_duration}s 需 TTS provider 支持，"
                    f"当前仅记录到 metadata，不实际处理音频"
                )

            ctx.audio_path = audio_path
            ctx.audio_duration = duration
            ctx.metadata["tts_timestamps"] = timestamps
            ctx.metadata["tts_provider"] = self.provider
            emotion_applied = None
            if self.provider == "edge_tts" and emotion:
                emotion_applied = EMOTION_EDGE_MAP.get(emotion, EMOTION_EDGE_MAP['neutral'])
            ctx.metadata["tts_audio_opts"] = {
                "speed": speed, "volume": volume, "pitch": pitch, "emotion": emotion,
                "emotion_applied": emotion_applied,
                "remove_silence": remove_silence,
                "voice_enhance": voice_enhance,
                "pause_duration": pause_duration,
            }

            return ModuleResult(
                success=True,
                data={
                    "audio_path": str(audio_path),
                    "duration": duration,
                    "voice_id": voice_id,
                    "provider": self.provider,
                    "segments": len(timestamps),
                    "speed": speed,
                    "emotion": emotion,
                },
            )
        except Exception as e:
            return ModuleResult(success=False, error=str(e))

    def synthesize(
        self, text: str, voice_id: str, output_path: Path,
        speed: float | None = None, volume: int | None = None,
        pitch: int | None = None, emotion: str | None = None,
    ) -> tuple[Path, float, list[dict]]:
        """公共合成方法（provider 无关，供 UI 试听/预览使用，无需构造 JobContext）

        与 run() 的分发逻辑一致，但直接返回 (音频路径, 时长, 时间戳)，
        不依赖 ctx，也不走 run_single_module 的笨重前置步骤。

        Args:
            text: 要合成的文案
            voice_id: 音色 ID（default 或已注册音色）
            output_path: 输出 wav 路径
            speed: 语速倍率（0.5-2.0，1.0 为正常），None 时用引擎默认
            volume: 音量百分比（0-200，100 为正常），None 时用引擎默认
            pitch: 音高半音偏移（-12 到 +12，0 为正常），None 时用引擎默认
            emotion: 情感标签（neutral/calm/excited/gentle/serious/cheerful），
                     目前仅记录到 metadata，由支持情感的 provider 使用

        Returns:
            (audio_path: Path, duration: float, timestamps: list[dict])
        """
        if not text or not text.strip():
            raise ValueError("无文案可合成")
        audio_opts = {"speed": speed, "volume": volume, "pitch": pitch, "emotion": emotion}
        if self.provider == "moss_nano":
            return self._synth_moss_nano(text, voice_id, output_path, **audio_opts)
        elif self.provider == "mimo":
            return self._synth_mimo(text, voice_id, output_path, **audio_opts)
        elif self.provider == "gpt_sovits":
            return self._synth_gpt_sovits(text, voice_id, output_path, **audio_opts)
        elif self.provider == "edge_tts":
            return self._synth_edge(text, voice_id, output_path, **audio_opts)
        else:
            return self._synth_mock(text, voice_id, output_path, **audio_opts)

    def _get_moss_runtime(self):
        """懒加载 MOSS-TTS-Nano ONNX 运行时（仅依赖 onnxruntime + soundfile + sentencepiece）"""
        if self._moss_runtime is not None:
            return self._moss_runtime

        import sys
        from ..core.config import PROJECT_ROOT

        cfg = self.config.get("tts.moss_nano", {}) or {}

        # 路径解析策略：优先配置的绝对路径，其次相对 PROJECT_ROOT 解析，最后回退多个常见位置
        candidates = []
        raw_repo = cfg.get("repo_dir", "../../MOSS-TTS-Nano")
        if Path(raw_repo).is_absolute():
            candidates.append(Path(raw_repo))
        else:
            # 相对 PROJECT_ROOT（EnlyAI 目录）
            candidates.append((PROJECT_ROOT / raw_repo).resolve())
            candidates.append((PROJECT_ROOT / "../MOSS-TTS-Nano").resolve())
            candidates.append(Path(raw_repo).resolve())

        repo_dir = next((c for c in candidates if c.exists()), None)
        if repo_dir is None:
            raise RuntimeError(
                f"MOSS-TTS-Nano 仓库不存在，已尝试: {[str(c) for c in candidates]}。"
                f"请在设置中配置正确路径（tts.moss_nano.repo_dir）或克隆仓库"
            )

        # 把仓库根加入 sys.path 以便 import onnx_tts_runtime
        repo_str = str(repo_dir)
        if repo_str not in sys.path:
            sys.path.insert(0, repo_str)

        from onnx_tts_runtime import OnnxTtsRuntime  # type: ignore

        # model_dir 解析：优先绝对路径 > 相对 repo_dir > 相对 PROJECT_ROOT > repo_dir/models
        raw_model = cfg.get("model_dir")
        model_candidates = []
        if raw_model:
            if Path(raw_model).is_absolute():
                model_candidates.append(Path(raw_model))
            else:
                model_candidates.append((repo_dir / raw_model).resolve())
                model_candidates.append((PROJECT_ROOT / raw_model).resolve())
                # raw_model 可能就是相对 repo 的（如 ../../MOSS-TTS-Nano/models），尝试 ../前缀剥离
                if raw_model.startswith("../"):
                    model_candidates.append((repo_dir.parent / raw_model[3:]).resolve())
        model_candidates.append((repo_dir / "models").resolve())
        model_dir_path = next((c for c in model_candidates if c.exists()), model_candidates[-1])
        model_dir = str(model_dir_path.resolve())
        self._moss_runtime = OnnxTtsRuntime(
            model_dir=model_dir,
            thread_count=int(cfg.get("cpu_threads", 4)),
            execution_provider=cfg.get("execution_provider", "cpu"),
        )
        self.logger.info(
            f"MOSS-TTS-Nano 运行时已加载 repo={repo_dir} model_dir={model_dir}"
        )
        return self._moss_runtime

    def _synth_moss_nano(
        self, text: str, voice_id: str, output_path: Path,
        speed: float | None = None, volume: int | None = None,
        pitch: int | None = None, emotion: str | None = None,
    ) -> tuple[Path, float, list[dict]]:
        """使用本地 MOSS-TTS-Nano ONNX 合成（支持声音克隆）

        音色选择优先级：
        1. voice_id 对应目录下有 sample 音频 → 用该音频做零样本声音克隆
        2. voice_id 是 MOSS 内置音色（Junhao/Trump/Ava/Bella/Adam/Nathan）→ 用该内置音色
        3. 回退到 config 的 builtin_voice（默认 Junhao）
        """
        # emotion 暂不支持，仅 edge_tts 支持情感映射
        runtime = self._get_moss_runtime()
        cfg = self.config.get("tts.moss_nano", {}) or {}

        # MOSS 内置音色清单
        MOSS_BUILTIN_VOICES = {"Junhao", "Trump", "Ava", "Bella", "Adam", "Nathan"}
        config_builtin = cfg.get("builtin_voice", "Junhao")

        # 查找该音色的参考音频（用于声音克隆）
        prompt_audio_path = None
        # 决定使用哪个内置音色：用户选的如果是MOSS内置音色则用之，否则回退到config
        actual_builtin = config_builtin
        if voice_id and voice_id != "default":
            # 检查是否是 MOSS 内置音色
            if voice_id in MOSS_BUILTIN_VOICES:
                actual_builtin = voice_id
                self.logger.info(
                    f"MOSS 使用内置音色 voice={voice_id}"
                )
            # 检查是否有克隆样本
            voice_dir = self.voices_dir / voice_id
            if voice_dir.exists():
                for ext in (".wav", ".mp3", ".flac", ".m4a"):
                    candidates = list(voice_dir.glob(f"sample*{ext}")) + list(
                        voice_dir.glob(f"*{ext}")
                    )
                    if candidates:
                        prompt_audio_path = str(candidates[0].resolve())
                        self.logger.info(
                            f"MOSS 声音克隆 voice={voice_id} sample={prompt_audio_path}"
                        )
                        break

        if prompt_audio_path is None and voice_id not in MOSS_BUILTIN_VOICES:
            self.logger.info(
                f"MOSS 未找到 {voice_id} 的克隆样本，回退到内置音色 {actual_builtin}"
            )

        self.logger.info(
            f"MOSS-TTS-Nano 合成 voice={voice_id} builtin={actual_builtin} "
            f"clone={'是' if prompt_audio_path else '否'} text_len={len(text)}"
        )

        result = runtime.synthesize(
            text=text,
            voice=actual_builtin,
            prompt_audio_path=prompt_audio_path,
            output_audio_path=str(output_path.resolve()),
            streaming=bool(cfg.get("realtime_streaming", True)),
            max_new_frames=int(cfg.get("max_new_frames", 375)),
            voice_clone_max_text_tokens=int(cfg.get("voice_clone_max_text_tokens", 75)),
            enable_wetext=bool(cfg.get("enable_wetext", False)),
            enable_normalize_tts_text=bool(cfg.get("enable_normalize_tts_text", True)),
        )

        audio_path = Path(result["audio_path"])
        # MOSS 输出 48kHz 立体声 wav；转 16kHz 单声道供 Wav2Lip 使用
        final_path = audio_path
        try:
            import subprocess
            mono_path = output_path.parent / f"{output_path.stem}_16k.wav"
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(audio_path),
                 "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                 str(mono_path)],
                capture_output=True, timeout=30,
            )
            if mono_path.exists():
                # 替换为 16k 单声道版本
                audio_path.unlink(missing_ok=True)
                mono_path.rename(output_path)
                final_path = output_path
        except Exception as e:
            self.logger.warning(f"MOSS 音频转 16k 失败，使用原始输出: {e}")
            if audio_path != output_path and audio_path.exists():
                audio_path.rename(output_path)
                final_path = output_path

        duration = get_wav_duration(final_path)

        # MOSS 不返回逐句时间戳，按分句估算（用于字幕对齐，后续 ASR 会校正）
        segments = split_text_to_segments(text)
        timestamps: list[dict] = []
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

        self.logger.info(
            f"MOSS-TTS-Nano 合成完成 duration={duration:.2f}s segments={len(segments)}"
        )
        return final_path, duration, timestamps

    def _synth_mimo(
        self, text: str, voice_id: str, output_path: Path,
        speed: float | None = None, volume: int | None = None,
        pitch: int | None = None, emotion: str | None = None,
    ) -> tuple[Path, float, list[dict]]:
        """调用小米 MiMo TTS API（OpenAI 兼容 chat/completions 端点）

        MiMo TTS 特点：
        - 端点：{api_base}/chat/completions
        - 文本放在 assistant 角色消息中
        - 音色和格式放在 audio 对象中
        - 返回 base64 编码音频在 choices[0].message.audio.data
        """
        # emotion 暂不支持，仅 edge_tts 支持情感映射
        self.logger.info(f"MiMo TTS 合成 voice={voice_id} text_len={len(text)}")

        # MiMo 单次合成有长度限制，分句合成
        segments = split_text_to_segments(text, max_chars=300)
        timestamps: list[dict] = []
        combined_audio = bytearray()
        offset = 0.0

        # 音色映射：voice_id -> mimo voice
        mimo_voice = voice_id if voice_id != "default" else "mimo_default"

        for seg in segments:
            payload = {
                "model": self.config.get("tts.mimo_model", "mimo-v2.5-tts"),
                "messages": [
                    {"role": "assistant", "content": seg}
                ],
                "audio": {
                    "format": "mp3",
                    "voice": mimo_voice,
                },
                "stream": False,
            }
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            url = f"{self.api_base.rstrip('/')}/chat/completions"

            r = httpx.post(url, json=payload, headers=headers, timeout=self.timeout)
            r.raise_for_status()
            data = r.json()

            choices = data.get("choices", [])
            if not choices:
                raise RuntimeError(f"MiMo TTS 返回无 choices: {data}")

            audio_info = choices[0].get("message", {}).get("audio", {})
            audio_b64 = audio_info.get("data")
            if not audio_b64:
                raise RuntimeError(f"MiMo TTS 返回无音频数据: {choices[0]}")

            audio_bytes = base64.b64decode(audio_b64)
            combined_audio.extend(audio_bytes)

            # 估算该段时长（MiMo 不返回时间戳）
            seg_duration = estimate_speech_duration(seg)
            timestamps.append({
                "text": seg,
                "start": round(offset, 3),
                "end": round(offset + seg_duration, 3),
            })
            offset += seg_duration

        # 保存为 mp3（MiMo 返回 mp3 格式）
        output_path.parent.mkdir(parents=True, exist_ok=True)
        mp3_path = output_path.with_suffix(".mp3")
        mp3_path.write_bytes(bytes(combined_audio))

        # 尝试用 ffmpeg 转 wav，失败则用 mp3
        try:
            import subprocess
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(mp3_path), "-acodec", "pcm_s16le",
                 "-ar", "16000", "-ac", "1", str(output_path)],
                capture_output=True, timeout=30,
            )
            if output_path.exists():
                mp3_path.unlink(missing_ok=True)
                final_path = output_path
            else:
                final_path = mp3_path
        except Exception:
            final_path = mp3_path

        duration = get_wav_duration(final_path) if final_path.suffix == ".wav" else offset

        self.logger.info(
            f"MiMo TTS 合成完成 duration={duration:.2f}s segments={len(segments)}"
        )
        return final_path, duration, timestamps

    def _synth_gpt_sovits(
        self, text: str, voice_id: str, output_path: Path,
        speed: float | None = None, volume: int | None = None,
        pitch: int | None = None, emotion: str | None = None,
    ) -> tuple[Path, float, list[dict]]:
        """调用 GPT-SoVITS 云端 API"""
        # emotion 暂不支持，仅 edge_tts 支持情感映射
        self.logger.info(f"GPT-SoVITS 合成 voice={voice_id} text_len={len(text)} speed={speed}")

        # 分句合成，便于时间戳对齐
        segments = split_text_to_segments(text)
        timestamps: list[dict] = []
        combined_audio = bytearray()
        sample_rate = 32000
        offset = 0.0
        # 语速：默认 1.0，支持外部传入精细控制
        tts_speed = speed if speed is not None else 1.0

        for seg in segments:
            payload = {
                "text": seg,
                "voice_id": voice_id,
                "speed": tts_speed,
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
        self, text: str, voice_id: str, output_path: Path,
        speed: float | None = None, volume: int | None = None,
        pitch: int | None = None, emotion: str | None = None,
    ) -> tuple[Path, float, list[dict]]:
        """使用 edge-tts 合成（标准音色，无克隆）

        支持语速/音量/音高精细控制（edge-tts 库原生能力）：
        - speed: 0.5-2.0 倍率 → edge-tts rate "±N%"
        - volume: 0-200 百分比 → edge-tts volume "±N%"
        - pitch: -12 到 +12 半音 → edge-tts pitch "±NHz"（每半音约 4Hz）
        """
        try:
            import edge_tts
        except ImportError as e:
            self.logger.warning("edge-tts 未安装，降级到 mock")
            return self._synth_mock(text, voice_id, output_path)

        # 构造 edge-tts 的 rate/volume/pitch 参数字符串
        kwargs: dict = {}
        if speed is not None and abs(speed - 1.0) > 0.01:
            rate_pct = int(round((speed - 1.0) * 100))
            kwargs["rate"] = f"{rate_pct:+d}%"
        if volume is not None and volume != 100:
            vol_pct = volume - 100
            kwargs["volume"] = f"{vol_pct:+d}%"
        if pitch is not None and pitch != 0:
            # 半音 → Hz 近似转换（每半音约 4Hz）
            pitch_hz = pitch * 4
            kwargs["pitch"] = f"{pitch_hz:+d}Hz"

        # 情感映射：emotion 优先，覆盖 config 派生的 rate/pitch（用户逐任务选择，更具体）
        emotion_map = EMOTION_EDGE_MAP.get(emotion or 'neutral', EMOTION_EDGE_MAP['neutral'])
        if emotion and emotion in EMOTION_EDGE_MAP:
            kwargs["rate"] = emotion_map["rate"]
            kwargs["pitch"] = emotion_map["pitch"]

        # 关键修复：edge_tts 必须使用用户选择的 voice_id，而非配置中的 edge_voice
        # voice_id 来自前端音色卡片选择（如 zh-CN-YunxiNeural 男声）
        # 仅当 voice_id 为空/default 时，才回退到 config 的 edge_voice
        actual_voice = voice_id if voice_id and voice_id not in ("default", "", "None") else self.edge_voice

        self.logger.info(
            f"edge-tts 合成 voice={actual_voice} (请求voice_id={voice_id}, "
            f"edge_voice={self.edge_voice}) "
            f"speed={speed} volume={volume} pitch={pitch} emotion={emotion} "
            f"kwargs={kwargs}"
        )

        # edge-tts 总是输出 MP3 流，先保存到临时 mp3 再用 ffmpeg 转 wav
        # （pcm_s16le 16kHz mono，符合下游 Wav2Lip 对音频格式的要求）
        output_path.parent.mkdir(parents=True, exist_ok=True)
        mp3_path = output_path.with_suffix(".mp3")

        async def _synth():
            # edge-tts 首字吞音修复：在文本前加一个逗号停顿，让合成器"热身"
            # 避免开头2个字被吞掉（edge-tts 已知问题）
            warmup_text = f"，{text}" if not text.startswith(("，", ",", "。", ".")) else text
            communicate = edge_tts.Communicate(warmup_text, actual_voice, **kwargs)
            await communicate.save(str(mp3_path))

        asyncio.run(_synth())

        # 用 ffmpeg 将 mp3 转为 wav（与 MiMo 分支保持一致）
        final_path = mp3_path
        try:
            import subprocess
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(mp3_path), "-acodec", "pcm_s16le",
                 "-ar", "16000", "-ac", "1", str(output_path)],
                capture_output=True, timeout=30,
            )
            if output_path.exists():
                mp3_path.unlink(missing_ok=True)
                final_path = output_path
        except Exception as e:
            self.logger.warning(f"edge-tts ffmpeg 转 wav 失败，使用 mp3: {e}")

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

        duration = get_wav_duration(final_path) if final_path.suffix == ".wav" else offset
        self.logger.info(
            f"edge-tts 合成完成 duration={duration:.2f}s segments={len(segments)}"
        )
        return final_path, duration, timestamps

    def _synth_mock(
        self, text: str, voice_id: str, output_path: Path,
        speed: float | None = None, volume: int | None = None,
        pitch: int | None = None, emotion: str | None = None,
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
            # moss_nano / mimo / edge 模式：本地保存样本音频（moss_nano 用做零样本克隆参考）
            import shutil
            dest = voice_dir / f"sample{sample_audio.suffix or '.wav'}"
            shutil.copy2(sample_audio, dest)
            self.logger.info(f"本地音色注册成功: {voice_id} -> {dest}")
            # moss_nano: 若样本不是 wav/48k，尝试转为标准 wav（MOSS 内部会重采样，但保留原始更稳）
            if self.provider == "moss_nano":
                self.logger.info(
                    f"音色 {voice_id} 已注册，MOSS 将用 {dest.name} 作为零样本克隆参考"
                )
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
