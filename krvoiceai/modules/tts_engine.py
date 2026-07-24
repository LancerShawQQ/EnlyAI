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

        # MOSS 内置音色清单（18 个：6 中文 + 5 英文 + 7 日文）
        MOSS_BUILTIN_VOICES = {
            # 中文音色
            "Junhao", "Zhiming", "Weiguo", "Xiaoyu", "Yuewen", "Lingyu",
            # 英文音色
            "Trump", "Ava", "Bella", "Adam", "Nathan",
            # 日文音色
            "Soyo", "Saki", "Mortis", "Umiri", "Mei", "Anon", "Arisa",
        }
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

        # v8: 修复 Junhao 开头急促问题
        # 根因：Junhao 参考音频 zh_1.wav 开头静音仅 60ms（< 1 codec 帧），
        #   模型学到"急促起音"韵律，导致第一个字没说完就跳到下一个字。
        #   其他音色（Zhiming 200ms、Xiaoyu 270ms 开头静音）无此问题。
        # 修复：对 Junhao 音色，使用补了 240ms 静音前缀 + 200ms 后缀的参考音频，
        #   让模型学到"静音→起音"的自然过渡。幅度淡入无法解决韵律问题。
        if prompt_audio_path is None and actual_builtin == "Junhao":
            from ..core.config import PROJECT_ROOT
            junhao_padded = (PROJECT_ROOT / "../MOSS-TTS-Nano/assets/audio/zh_1_padded.wav").resolve()
            if junhao_padded.exists():
                prompt_audio_path = str(junhao_padded)
                self.logger.info(
                    f"v8: Junhao 使用补静音参考音频 (240ms前缀+200ms后缀): {junhao_padded.name}"
                )

        self.logger.info(
            f"MOSS-TTS-Nano 合成 voice={voice_id} builtin={actual_builtin} "
            f"clone={'是' if prompt_audio_path else '否'} text_len={len(text)}"
        )

        # v7: 采样参数调优（降低 AI 感，让语音更自然）
        # v6 修复：必须通过 synthesize() 的 sample_mode/do_sample 参数传递
        # v7 新增：voice_clone_max_text_tokens 从 75 调到 100（保持长句韵律连贯）
        # 注意：audio_top_k 不宜过低（<22 会导致模型无法选到 audio_end_token，
        #        生成满 30s max_new_frames 才停止），保持 manifest 默认 25
        gen_defaults = runtime.manifest["generation_defaults"]
        _orig_defaults = dict(gen_defaults)
        try:
            # 音频层参数通过 manifest 注入（synthesize 不覆盖这些字段）
            # v7: temperature=0.9 与 v6 一致（0.85 太低导致生成过长）
            if "audio_temperature" in gen_defaults:
                gen_defaults["audio_temperature"] = float(cfg.get("audio_temperature", 0.9))
            if "audio_top_p" in gen_defaults:
                gen_defaults["audio_top_p"] = float(cfg.get("audio_top_p", 0.90))
            if "audio_repetition_penalty" in gen_defaults:
                gen_defaults["audio_repetition_penalty"] = float(cfg.get("audio_repetition_penalty", 1.05))
            if "text_temperature" in gen_defaults:
                gen_defaults["text_temperature"] = float(cfg.get("text_temperature", 1.0))
        except (TypeError, ValueError):
            pass

        # v6: sample_mode 和 do_sample 必须通过参数传递（不能只改 manifest）
        # v8.2: 从 full 改回 fixed。full 模式会生成大量静音（85-95% 静音比例），
        #   fixed 模式稳定（静音比例 <25%），且补静音参考音频已解决开头急促问题
        # full = 完整随机性（最自然但会生成大量静音）
        # fixed = 固定随机性（最稳定，烘焙常数在 ONNX 图中）
        # greedy = 贪婪（最机械）
        sample_mode_val = str(cfg.get("sample_mode", "fixed"))
        if sample_mode_val not in ("full", "fixed", "greedy"):
            sample_mode_val = "fixed"
        do_sample_val = sample_mode_val != "greedy"

        result = runtime.synthesize(
            text=text,
            voice=actual_builtin,
            prompt_audio_path=prompt_audio_path,
            output_audio_path=str(output_path.resolve()),
            streaming=bool(cfg.get("realtime_streaming", True)),
            # v8.2: 恢复 375（fixed 模式不会生成大量静音，无需降低上限）
            max_new_frames=int(cfg.get("max_new_frames", 375)),
            # v7: 75 → 100，保持长句韵律连贯，减少分块断层
            voice_clone_max_text_tokens=int(cfg.get("voice_clone_max_text_tokens", 100)),
            enable_wetext=bool(cfg.get("enable_wetext", False)),
            enable_normalize_tts_text=bool(cfg.get("enable_normalize_tts_text", True)),
            seed=int(cfg["seed"]) if cfg.get("seed") else None,
            sample_mode=sample_mode_val,
            do_sample=do_sample_val,
        )

        # 恢复原始采样参数（避免影响后续合成）
        runtime.manifest["generation_defaults"] = _orig_defaults

        # v8.1: 截断尾部连续静音（>500ms）
        # full 模式有时会生成大量尾部静音，需要自动截断
        try:
            import soundfile as _sf
            import numpy as _np
            _data, _sr = _sf.read(str(result["audio_path"]), dtype="float32")
            if _data.ndim == 1:
                _data = _data.reshape(-1, 1)
            _win = int(_sr * 0.01)  # 10ms 窗口
            _n = len(_data) // _win
            _silence_threshold = 0.01
            # 从末尾向前找最后一个非静音窗口
            _last_speech = 0
            for _i in range(_n - 1, -1, -1):
                _w = _data[_i * _win: (_i + 1) * _win]
                _rms = float(_np.sqrt(_np.mean(_w ** 2)))
                if _rms > _silence_threshold:
                    _last_speech = (_i + 1) * _win
                    break
            _trailing_silence_ms = (len(_data) - _last_speech) / _sr * 1000
            if _trailing_silence_ms > 500:
                # 保留 200ms 尾部静音，截断其余部分
                _keep = _last_speech + int(_sr * 0.2)
                _trimmed = _data[:_keep]
                _sf.write(str(result["audio_path"]), _trimmed, _sr, subtype="PCM_16")
                self.logger.info(
                    f"v8.1: 截断尾部静音 {_trailing_silence_ms:.0f}ms → 保留 200ms"
                )
        except Exception as _e:
            self.logger.warning(f"v8.1: 尾部静音截断失败: {_e}")

        audio_path = Path(result["audio_path"])
        # MOSS 输出 48kHz 立体声 wav；转 16kHz 单声道供 Wav2Lip 使用
        # 关键：系统 ffmpeg 是极简编译版（--disable-everything，无音频编解码器），
        #   必须用 imageio-ffmpeg 自带的完整版 ffmpeg，否则转换静默失败
        final_path = audio_path
        try:
            import subprocess
            import imageio_ffmpeg
            ffmpeg_cmd = imageio_ffmpeg.get_ffmpeg_exe()
            mono_path = output_path.parent / f"{output_path.stem}_16k.wav"
            subprocess.run(
                [ffmpeg_cmd, "-y", "-i", str(audio_path),
                 "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
                 str(mono_path)],
                check=True, capture_output=True, timeout=30,
            )
            if mono_path.exists():
                # 替换为 16k 单声道版本
                audio_path.unlink(missing_ok=True)
                mono_path.rename(output_path)
                final_path = output_path
        except Exception as e:
            self.logger.warning(f"MOSS 音频转 16k 失败，使用原始输出: {e}")
            # 转换失败时确保原始音频落到 output_path（resolve 比较，避免绝对/相对路径误判）
            if audio_path.resolve() != output_path.resolve() and audio_path.exists():
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
        # Voice 兼容性校验：MiMo TTS 仅支持 mimo_default，其他音色自动降级
        # （模板 voice 字段可能写入 Ava/Junhao 等 MOSS 内置音色，切换到 mimo 时需降级）
        MIMO_SUPPORTED = {"default", "mimo_default", "", None}
        if voice_id not in MIMO_SUPPORTED:
            self.logger.warning(
                f"MiMo TTS 不支持音色 {voice_id}，降级到 mimo_default"
            )
            voice_id = "mimo_default"
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
        # Voice 兼容性校验：edge_tts 仅支持实测可用的 zh-CN-* Neural 音色
        # （模板 voice 字段可能写入 Ava/Junhao 等 MOSS 内置音色，切换到 edge_tts 时需降级）
        # 与 settings_manager.PROVIDER_PRESETS['tts']['edge_tts']['voices'] 保持同步
        EDGE_SUPPORTED_VOICES = {
            "zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural", "zh-CN-YunjianNeural",
            "zh-CN-XiaoyiNeural", "zh-CN-YunyangNeural", "zh-CN-XiaoxuanNeural",
            "zh-CN-YunxiaNeural",
        }
        if voice_id and voice_id not in ("default", "", "None") and voice_id not in EDGE_SUPPORTED_VOICES:
            self.logger.warning(
                f"edge_tts 不支持音色 {voice_id}，降级到 {self.edge_voice}"
            )
            voice_id = self.edge_voice
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

        # 带重试的合成（edge-tts 服务端偶发返回空音频/NoAudioReceived）
        MAX_RETRIES = 3
        last_error: Exception | None = None

        async def _synth_with_retry():
            """带重试的 edge-tts 合成，确保生成有效音频文件"""
            nonlocal last_error
            # edge-tts 首字吞音修复：在文本前加一个逗号停顿，让合成器"热身"
            warmup_text = f"，{text}" if not text.startswith(("，", ",", "。", ".")) else text
            for attempt in range(1, MAX_RETRIES + 1):
                mp3_path.unlink(missing_ok=True)  # 清理上次可能的空文件
                try:
                    communicate = edge_tts.Communicate(warmup_text, actual_voice, **kwargs)
                    await communicate.save(str(mp3_path))
                    # 检查文件大小（有效音频至少 1KB）
                    if mp3_path.exists() and mp3_path.stat().st_size > 1000:
                        self.logger.info(f"edge-tts 合成成功（尝试 {attempt}/{MAX_RETRIES}）"
                                         f" size={mp3_path.stat().st_size}")
                        return
                    self.logger.warning(
                        f"edge-tts 尝试 {attempt}/{MAX_RETRIES}: "
                        f"音频文件为空或过小 size={mp3_path.stat().st_size if mp3_path.exists() else 0}"
                    )
                except Exception as e:
                    last_error = e
                    self.logger.warning(f"edge-tts 尝试 {attempt}/{MAX_RETRIES}: {type(e).__name__}: {e}")
                await asyncio.sleep(1.5)
            # 重试耗尽，抛出最后一个异常
            raise last_error or RuntimeError(
                f"edge-tts 合成失败：重试 {MAX_RETRIES} 次后仍无音频输出 voice={actual_voice}"
            )

        asyncio.run(_synth_with_retry())

        # 用 ffmpeg 将 mp3 转为 wav（与 MiMo 分支保持一致）
        final_path = mp3_path
        try:
            import subprocess
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", str(mp3_path), "-acodec", "pcm_s16le",
                 "-ar", "16000", "-ac", "1", str(output_path)],
                capture_output=True, timeout=30,
            )
            if output_path.exists() and output_path.stat().st_size > 1000:
                mp3_path.unlink(missing_ok=True)
                final_path = output_path
                self.logger.info(f"edge-tts ffmpeg 转 wav 成功: {output_path.name} "
                                 f"size={output_path.stat().st_size}")
            else:
                self.logger.warning(
                    f"edge-tts ffmpeg 转 wav 后文件无效: "
                    f"exists={output_path.exists()} "
                    f"size={output_path.stat().st_size if output_path.exists() else 0} "
                    f"stderr={result.stderr.decode('utf-8', errors='replace')[:200]}"
                )
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
            # 关键：MOSS 用 soundfile 读取参考音频，soundfile 不支持 m4a/aac 等格式
            # 非 wav 格式必须转换为 wav，否则克隆时报 "Format not recognised"
            import shutil
            dest = voice_dir / "sample.wav"
            if sample_audio.suffix.lower() == ".wav":
                shutil.copy2(sample_audio, dest)
            else:
                # 非 wav（m4a/mp3/flac 等），用 imageio-ffmpeg 转换为标准 wav（48kHz 立体声 PCM_16）
                try:
                    import imageio_ffmpeg
                    import subprocess
                    ffmpeg_cmd = imageio_ffmpeg.get_ffmpeg_exe()
                    subprocess.run(
                        [ffmpeg_cmd, "-y", "-i", str(sample_audio),
                         "-acodec", "pcm_s16le", "-ar", "48000", "-ac", "2", str(dest)],
                        check=True, capture_output=True, timeout=30,
                    )
                    self.logger.info(f"音色样本已转 WAV: {sample_audio.name} -> {dest.name}")
                except Exception as e:
                    self.logger.warning(f"音色样本转 WAV 失败({e})，直接复制原文件")
                    dest = voice_dir / f"sample{sample_audio.suffix or '.wav'}"
                    shutil.copy2(sample_audio, dest)
            self.logger.info(f"本地音色注册成功: {voice_id} -> {dest}")
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
