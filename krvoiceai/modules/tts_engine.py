"""TTS 声音克隆模块

八种 provider：
- cosyvoice:        本地 CosyVoice3 服务（Fun-CosyVoice3-0.5B-2512，9 语言+18 方言+instruct+零样本克隆，Apache 2.0）
- moss_nano:        本地 MOSS-TTS-Nano ONNX（CPU 声音克隆，0.1B 模型，5s 样本零克隆）
- qwen3_tts:        本地 Qwen3-TTS（0.6B，9 预置音色 + 指令控制 + 3s 声音克隆，Apache 2.0）
- qwen3_tts_clone:  本地 Qwen3-TTS Base（0.6B，3 秒参考音频声音克隆，Apache 2.0）
- mimo:             调用小米 MiMo TTS API（OpenAI 兼容 chat/completions 端点）
- gpt_sovits:       调用云端 GPT-SoVITS API（声音克隆）
- edge_tts:         使用 edge-tts 标准音色（无克隆，CPU 可跑）
- mock:             生成静音 wav（保证流程可跑通）

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

# Qwen3-TTS 9 个预置音色（CustomVoice 0.6B 版）
# 注：voice_id 为模型内置 ID 不可改；label 使用中文别名便于用户识别
QWEN3_PRESET_VOICES = {
    "Vivian":    {"label": "薇薇（女·中文）",     "gender": "female", "language": "Chinese",  "description": "明亮年轻女声"},
    "Serena":    {"label": "诗韵（女·中文）",     "gender": "female", "language": "Chinese",  "description": "温暖柔和年轻女声"},
    "Uncle_Fu":  {"label": "傅叔（男·中文）",     "gender": "male",   "language": "Chinese",  "description": "成熟醇厚男声"},
    "Dylan":     {"label": "迪伦（男·北京）",     "gender": "male",   "language": "Chinese",  "description": "青春北京男声"},
    "Eric":      {"label": "毅行（男·四川）",     "gender": "male",   "language": "Chinese",  "description": "活泼成都男声"},
    "Ryan":      {"label": "Ryan（男·英文）",     "gender": "male",   "language": "English",  "description": "富有节奏感活力男声"},
    "Aiden":     {"label": "Aiden（男·英文）",    "gender": "male",   "language": "English",  "description": "阳光美式男声"},
    "Ono_Anna":  {"label": "Ono Anna（女·日文）", "gender": "female", "language": "Japanese", "description": "活泼日语女声"},
    "Sohee":     {"label": "Sohee（女·韩文）",    "gender": "female", "language": "Korean",   "description": "温暖韩语女声"},
}

# emotion → Qwen3-TTS 自然语言指令映射（instruct 控制语气风格）
EMOTION_QWEN3_INSTRUCT_MAP = {
    'neutral':  '',
    'calm':     '用平静舒缓的语气说',
    'excited':  '用非常激动兴奋的语气说',
    'gentle':   '用温柔轻柔的语气说',
    'serious':  '用严肃沉稳的语气说',
    'cheerful': '用开心欢快的语气说',
}

# CosyVoice3 预置参考音色（用于零样本克隆，每个音色对应 voices_dir 下的样本音频）
# 样本音频由 scripts/pregenerate_voice_samples.py 预生成，用户可在 UI 试听后选择
# voice_id 即目录名，目录内 sample.wav + ref_text.txt（参考音频+对应文本）
COSYVOICE_PRESET_VOICES = {
    "anchor_female": {
        "label": "女主播（女·中文）",
        "gender": "female",
        "language": "zh",
        "description": "标准女主播音色，清晰专业",
        "ref_text": "大家好，欢迎收看今天的节目。",
    },
    "anchor_male": {
        "label": "男主播（男·中文）",
        "gender": "male",
        "language": "zh",
        "description": "标准男主播音色，沉稳大气",
        "ref_text": "大家好，欢迎收看今天的节目。",
    },
    "narrator_female": {
        "label": "女解说（女·中文）",
        "gender": "female",
        "language": "zh",
        "description": "温暖女声解说，适合科普/情感",
        "ref_text": "在这个美好的日子里，让我们一起探索。",
    },
    "narrator_male": {
        "label": "男解说（男·中文）",
        "gender": "male",
        "language": "zh",
        "description": "磁性男声解说，适合纪录片",
        "ref_text": "在这个美好的日子里，让我们一起探索。",
    },
    "seller_energetic": {
        "label": "带货达人（女·中文）",
        "gender": "female",
        "language": "zh",
        "description": "活力女声，适合带货/种草",
        "ref_text": "家人们，今天给大家带来一个超级划算的好物！",
    },
    "english_female": {
        "label": "English Female",
        "gender": "female",
        "language": "en",
        "description": "Native English female voice",
        "ref_text": "Hello, welcome to today's program.",
    },
    "english_male": {
        "label": "English Male",
        "gender": "male",
        "language": "en",
        "description": "Native English male voice",
        "ref_text": "Hello, welcome to today's program.",
    },
}

# emotion → CosyVoice3 instruct 指令映射（自然语言控制语气/情绪/语速）
# neutral → 空 = 走零样本克隆（韵律直接继承参考音频，配合富表现力参考样本最自然）；
# 非 neutral → instruct2 文本指令控制情绪（指令越具体韵律越自然，加入语速/场景修饰）
EMOTION_COSYVOICE_INSTRUCT_MAP = {
    'neutral':  '',
    'calm':     '请用平静舒缓的语气说，语速稍慢，从容不迫，像在讲述一段故事',
    'excited':  '请用热情饱满的语气说，语速稍快，充满感染力，像在激动地分享好消息',
    'gentle':   '请用温柔轻柔的语气说，语速舒缓，柔和细腻，像在轻声安慰朋友',
    'serious':  '请用严肃沉稳的语气说，语速适中，庄重而有分量，像在播报重要新闻',
    'cheerful': '请用开心明快的语气说，语速适中偏快，轻松活泼，像在和朋友开心聊天',
}


class TTSEngine(BaseModule):
    """TTS 声音克隆/合成模块"""

    name = "tts"
    requires_gpu = True  # 真实模式需要 GPU（moss_nano/edge_tts/mock 可纯 CPU 运行）

    # 纯 CPU 可跑的 provider（不需要云端 GPU）
    # cosyvoice: HTTP 客户端调用独立服务，主进程不需要 GPU
    CPU_ONLY_PROVIDERS = {"cosyvoice", "moss_nano", "qwen3_tts", "qwen3_tts_clone", "edge_tts", "mock"}

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
        # Qwen3-TTS 模型缓存（懒加载，首次 qwen3_tts 合成时初始化）
        self._qwen3_tts_model = None
        self._qwen3_tts_variant = None  # "custom_voice" / "voice_clone"
        # Qwen3-TTS Base 模型缓存（声音克隆，懒加载，首次 qwen3_tts_clone 合成时初始化）
        self._qwen3_tts_base_model = None
        # FFmpeg 工具（用于音频后处理：静音消除/人声增强）
        self.ffmpeg = FFmpegRunner()

    # 类级共享 HTTP 客户端：流水线/播客/试听多个引擎实例复用同一组 keep-alive 连接
    _cosyvoice_client_instance: "httpx.Client | None" = None

    @classmethod
    def _cosyvoice_http_client(cls) -> "httpx.Client":
        """共享的 CosyVoice HTTP 客户端（keep-alive 连接复用，省去每段 TCP 握手）"""
        if cls._cosyvoice_client_instance is None:
            cls._cosyvoice_client_instance = httpx.Client(
                timeout=180.0,
                limits=httpx.Limits(max_keepalive_connections=4, keepalive_expiry=300.0),
            )
        return cls._cosyvoice_client_instance

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
            if self.provider == "cosyvoice":
                audio_path, duration, timestamps = self._synth_cosyvoice(
                    text, voice_id, output_path, speed, volume, pitch, emotion,
                    pause_duration=float(audio_cfg.get("pause_duration", 0.5) or 0),
                )
            elif self.provider == "moss_nano":
                audio_path, duration, timestamps = self._synth_moss_nano(
                    text, voice_id, output_path, speed, volume, pitch, emotion
                )
            elif self.provider == "qwen3_tts":
                audio_path, duration, timestamps = self._synth_qwen3_tts(
                    text, voice_id, output_path, speed, volume, pitch, emotion
                )
            elif self.provider == "qwen3_tts_clone":
                audio_path, duration, timestamps = self._synth_qwen3_tts_clone(
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
        self.logger.info(f"synthesize called provider={repr(self.provider)} voice_id={voice_id} text_len={len(text)}")
        if self.provider == "cosyvoice":
            self.logger.info("→ routing to _synth_cosyvoice")
            # 试听路径也应用句间停顿（与流水线一致的自然节奏）
            audio_opts["pause_duration"] = float(
                self.config.get("audio.pause_duration", 0.5) or 0
            )
            return self._synth_cosyvoice(text, voice_id, output_path, **audio_opts)
        elif self.provider == "moss_nano":
            return self._synth_moss_nano(text, voice_id, output_path, **audio_opts)
        elif self.provider == "qwen3_tts":
            return self._synth_qwen3_tts(text, voice_id, output_path, **audio_opts)
        elif self.provider == "qwen3_tts_clone":
            return self._synth_qwen3_tts_clone(text, voice_id, output_path, **audio_opts)
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

    def _get_qwen3_tts_model(self):
        """懒加载 Qwen3-TTS 模型（仅依赖 qwen_tts + torch + soundfile）

        加载 CustomVoice 0.6B 版本，支持 9 预置音色 + instruct 指令控制。
        CPU 模式用 float32，GPU 模式用 bfloat16。
        """
        if self._qwen3_tts_model is not None:
            return self._qwen3_tts_model

        cfg = self.config.get("tts.qwen3_tts", {}) or {}
        device = cfg.get("device", "cpu")

        try:
            import torch
            from qwen_tts import Qwen3TTSModel
        except ImportError as e:
            raise RuntimeError(
                f"Qwen3-TTS 依赖未安装: {e}。请运行 pip install qwen-tts torch soundfile"
            )

        model_id = cfg.get(
            "model_id",
            "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice",
        )
        # CPU 用 float32，GPU 用 bfloat16
        dtype = torch.float32 if device == "cpu" else torch.bfloat16

        self._qwen3_tts_model = Qwen3TTSModel.from_pretrained(
            model_id,
            device_map=device,
            dtype=dtype,
        )
        self.logger.info(
            f"Qwen3-TTS 模型已加载 model={model_id} device={device} dtype={dtype}"
        )
        return self._qwen3_tts_model

    def _synth_qwen3_tts(
        self, text: str, voice_id: str, output_path: Path,
        speed: float | None = None, volume: int | None = None,
        pitch: int | None = None, emotion: str | None = None,
    ) -> tuple[Path, float, list[dict]]:
        """使用本地 Qwen3-TTS 合成（0.6B CustomVoice，9 预置音色 + 指令控制）

        音色选择优先级：
        1. voice_id 在 9 预置音色中 → 用该音色 + 情绪指令
        2. 回退到配置的 default_speaker（默认 Vivian）

        情绪控制通过自然语言 instruct 实现（非 rate/pitch 参数）。
        长文本分句合成，逐句拼接。
        """
        try:
            import soundfile as sf
        except ImportError:
            self.logger.warning("soundfile 未安装，降级到 mock")
            return self._synth_mock(text, voice_id, output_path)

        try:
            import numpy as np
        except ImportError:
            self.logger.warning("numpy 未安装，降级到 mock")
            return self._synth_mock(text, voice_id, output_path)

        model = self._get_qwen3_tts_model()
        cfg = self.config.get("tts.qwen3_tts", {}) or {}

        # 确定音色
        actual_speaker = (
            voice_id if voice_id in QWEN3_PRESET_VOICES
            else cfg.get("default_speaker", "Vivian")
        )
        voice_info = QWEN3_PRESET_VOICES.get(actual_speaker, {})
        language = voice_info.get("language", "Chinese")

        # 情绪 → 自然语言指令
        instruct = EMOTION_QWEN3_INSTRUCT_MAP.get(emotion or 'neutral', '')

        self.logger.info(
            f"Qwen3-TTS 合成 speaker={actual_speaker} lang={language} "
            f"emotion={emotion} instruct='{instruct}' text_len={len(text)}"
        )

        # 分句合成（长文本稳定性）
        segments = split_text_to_segments(text)
        all_wavs: list = []
        sample_rate = 24000

        for seg in segments:
            if not seg.strip():
                continue
            kwargs: dict = {
                "text": seg,
                "language": language,
                "speaker": actual_speaker,
            }
            if instruct:
                kwargs["instruct"] = instruct
            wavs, sr = model.generate_custom_voice(**kwargs)
            all_wavs.extend(wavs)
            sample_rate = sr

        if not all_wavs:
            self.logger.warning("Qwen3-TTS 未生成音频，降级到 mock")
            return self._synth_mock(text, voice_id, output_path)

        # 合并音频
        combined = np.concatenate(all_wavs) if len(all_wavs) > 1 else all_wavs[0]

        # 保存 wav（16kHz mono，与 edge_tts/mimo 保持一致，适配下游 Wav2Lip）
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(output_path), combined, sample_rate)

        duration = len(combined) / sample_rate

        # 生成分句时间戳（按各句实际音频长度分配）
        timestamps = []
        offset = 0.0
        wav_idx = 0
        for seg in segments:
            if not seg.strip():
                continue
            if wav_idx < len(all_wavs):
                seg_dur = len(all_wavs[wav_idx]) / sample_rate
                wav_idx += 1
            else:
                seg_dur = estimate_speech_duration(seg)
            timestamps.append({
                "text": seg,
                "start": round(offset, 3),
                "end": round(offset + seg_dur, 3),
            })
            offset += seg_dur

        self.logger.info(
            f"Qwen3-TTS 合成完成 duration={duration:.2f}s segments={len(segments)} "
            f"speaker={actual_speaker} sr={sample_rate}"
        )
        return output_path, duration, timestamps

    def _get_qwen3_tts_base_model(self):
        """懒加载 Qwen3-TTS Base 模型（用于声音克隆，仅依赖 qwen_tts + torch + soundfile）

        加载 Base 0.6B 版本，支持 3 秒参考音频声音克隆。
        CPU 模式用 float32，GPU 模式用 bfloat16。
        """
        if self._qwen3_tts_base_model is not None:
            return self._qwen3_tts_base_model

        cfg = self.config.get("tts.qwen3_tts_clone", {}) or {}
        device = cfg.get("device", "cpu")

        try:
            import torch
            from qwen_tts import Qwen3TTSModel
        except ImportError as e:
            raise RuntimeError(
                f"Qwen3-TTS 依赖未安装: {e}。请运行 pip install qwen-tts torch soundfile"
            )

        model_id = cfg.get(
            "model_id",
            "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        )
        # CPU 用 float32，GPU 用 bfloat16
        dtype = torch.float32 if device == "cpu" else torch.bfloat16

        self._qwen3_tts_base_model = Qwen3TTSModel.from_pretrained(
            model_id,
            device_map=device,
            dtype=dtype,
        )
        self.logger.info(
            f"Qwen3-TTS Base 模型已加载 model={model_id} device={device} dtype={dtype}"
        )
        return self._qwen3_tts_base_model

    def _synth_qwen3_tts_clone(
        self, text: str, voice_id: str, output_path: Path,
        speed: float | None = None, volume: int | None = None,
        pitch: int | None = None, emotion: str | None = None,
    ) -> tuple[Path, float, list[dict]]:
        """使用 Qwen3-TTS Base 模型进行声音克隆合成（3 秒参考音频）

        需要在 config tts.qwen3_tts_clone 中配置 ref_audio 和 ref_text。
        voice_id 参数在此 provider 中不用于音色选择（音色由 ref_audio 决定），
        但会作为输出文件的标识。

        长文本分句合成，逐句拼接。
        """
        try:
            import soundfile as sf
        except ImportError:
            self.logger.warning("soundfile 未安装，降级到 mock")
            return self._synth_mock(text, voice_id, output_path)

        try:
            import numpy as np
        except ImportError:
            self.logger.warning("numpy 未安装，降级到 mock")
            return self._synth_mock(text, voice_id, output_path)

        cfg = self.config.get("tts.qwen3_tts_clone", {}) or {}
        ref_audio = cfg.get("ref_audio", "")
        ref_text = cfg.get("ref_text", "")
        language = cfg.get("language", "Chinese")

        if not ref_audio or not ref_text:
            self.logger.error(
                "Qwen3-TTS 声音克隆未配置 ref_audio/ref_text，降级到 mock"
            )
            return self._synth_mock(text, voice_id, output_path)

        ref_audio_path = Path(ref_audio)
        if not ref_audio_path.is_absolute():
            # 相对路径基于 PROJECT_ROOT 解析
            from ..core.config import PROJECT_ROOT
            ref_audio_path = PROJECT_ROOT / ref_audio_path
        if not ref_audio_path.exists():
            self.logger.error(f"参考音频不存在: {ref_audio_path}，降级到 mock")
            return self._synth_mock(text, voice_id, output_path)

        model = self._get_qwen3_tts_base_model()

        self.logger.info(
            f"Qwen3-TTS 克隆合成 ref_audio={ref_audio_path.name} "
            f"lang={language} text_len={len(text)}"
        )

        # 分句合成（长文本稳定性）
        segments = split_text_to_segments(text)
        all_wavs: list = []
        sample_rate = 24000

        for seg in segments:
            if not seg.strip():
                continue
            wavs, sr = model.generate_voice_clone(
                text=seg,
                language=language,
                ref_audio=str(ref_audio_path),
                ref_text=ref_text,
            )
            all_wavs.extend(wavs)
            sample_rate = sr

        if not all_wavs:
            self.logger.warning("Qwen3-TTS 克隆未生成音频，降级到 mock")
            return self._synth_mock(text, voice_id, output_path)

        # 合并音频
        combined = np.concatenate(all_wavs) if len(all_wavs) > 1 else all_wavs[0]

        # 保存 wav
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(output_path), combined, sample_rate)

        duration = len(combined) / sample_rate

        # 生成分句时间戳
        timestamps = []
        offset = 0.0
        wav_idx = 0
        for seg in segments:
            if not seg.strip():
                continue
            if wav_idx < len(all_wavs):
                seg_dur = len(all_wavs[wav_idx]) / sample_rate
                wav_idx += 1
            else:
                seg_dur = estimate_speech_duration(seg)
            timestamps.append({
                "text": seg,
                "start": round(offset, 3),
                "end": round(offset + seg_dur, 3),
            })
            offset += seg_dur

        self.logger.info(
            f"Qwen3-TTS 克隆合成完成 duration={duration:.2f}s segments={len(segments)} "
            f"sr={sample_rate}"
        )
        return output_path, duration, timestamps

    def _synth_cosyvoice(
        self, text: str, voice_id: str, output_path: Path,
        speed: float | None = None, volume: int | None = None,
        pitch: int | None = None, emotion: str | None = None,
        pause_duration: float | None = None,
    ) -> tuple[Path, float, list[dict]]:
        """使用本地 CosyVoice3 服务合成（HTTP 调用 cosyvoice_server.py）

        Fun-CosyVoice3-0.5B-2512 特性：
        - 零样本声音克隆（3-10s 参考音频）
        - instruct2 指令控制（情绪/方言/语速/音量）
        - 9 语言 + 18 中文方言
        - 150ms 低延迟流式

        音色选择优先级：
        1. voice_id 在 COSYVOICE_PRESET_VOICES 中 → 用预置参考音频
        2. voice_id 对应 voices_dir/{voice_id}/ 目录有样本 → 用该样本克隆
        3. 回退到配置的 default_voice 或第一个预置音色

        情绪控制通过 instruct2 自然语言指令实现。
        长文本分句合成，逐句调用，最后拼接。
        """
        cfg = self.config.get("tts.cosyvoice", {}) or {}
        server_url = (cfg.get("server_url") or "http://localhost:8012").rstrip("/")
        timeout = int(cfg.get("timeout", 180))
        use_instruct = bool(cfg.get("use_instruct", True))

        # 确定参考音频和文本
        prompt_audio_path, prompt_text = self._resolve_cosyvoice_voice(voice_id, cfg)
        if prompt_audio_path is None:
            self.logger.error(
                f"CosyVoice 未找到音色 {voice_id} 的参考音频，降级到 mock"
            )
            return self._synth_mock(text, voice_id, output_path)

        # 情绪 → instruct 指令
        instruct = EMOTION_COSYVOICE_INSTRUCT_MAP.get(emotion or 'neutral', '')

        self.logger.info(
            f"CosyVoice 合成 voice={voice_id} emotion={emotion} "
            f"instruct='{instruct}' text_len={len(text)} server={server_url}"
        )

        # 分句合成（长文本稳定性，CosyVoice 对超长文本容易重复/跳字）
        # 优化：增大分句长度到250字，尽量保持整段语义连贯，减少句间韵律断层
        # CosyVoice3 内部已有分句机制，250字以内单次调用更自然流畅
        segments = split_text_to_segments(text, max_chars=250)
        all_wavs: list[bytes] = []
        sample_rate = 24000

        self.logger.info(f"CosyVoice segments={len(segments)} seg_reps={[repr(s) for s in segments]}")

        for seg in segments:
            if not seg.strip():
                continue
            self.logger.info(f"CosyVoice calling API with seg={repr(seg)} prompt_text={repr(prompt_text)}")
            wav_bytes = self._call_cosyvoice_api(
                server_url, seg, prompt_audio_path, prompt_text,
                instruct=use_instruct and instruct,
                speed=speed or 1.0,
                timeout=timeout,
            )
            self.logger.info(f"CosyVoice seg wav_bytes={len(wav_bytes) if wav_bytes else 'None'}")
            if wav_bytes:
                all_wavs.append(wav_bytes)

        if not all_wavs:
            self.logger.warning("CosyVoice 未生成音频，降级到 mock")
            return self._synth_mock(text, voice_id, output_path)

        # 合并音频 bytes（WAV 格式，需解码后拼接再编码）
        try:
            import soundfile as sf
            import numpy as np
            import io as _io

            combined_audio = []
            for wb in all_wavs:
                data, sr = sf.read(_io.BytesIO(wb), dtype="float32")
                if data.ndim > 1:
                    data = data.mean(axis=1)  # stereo → mono
                combined_audio.append(data)
                sample_rate = sr

            combined, seg_durations = self._concat_tts_segments(
                combined_audio, sample_rate, segments,
                pause_duration=0.5 if pause_duration is None else float(pause_duration),
            )
        except Exception as e:
            self.logger.warning(f"音频合并失败，直接写第一段: {e}")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(all_wavs[0])
            duration = get_wav_duration(output_path)
            timestamps = self._build_timestamps_from_segments(segments, duration, sample_rate)
            return output_path, duration, timestamps

        # 保存 wav
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(output_path), combined, sample_rate)

        duration = len(combined) / sample_rate

        # 生成分句时间戳（含句间停顿的真实时长）
        timestamps = []
        offset = 0.0
        wav_idx = 0
        for seg in segments:
            if not seg.strip():
                continue
            if wav_idx < len(seg_durations):
                seg_dur = seg_durations[wav_idx]
                wav_idx += 1
            else:
                seg_dur = estimate_speech_duration(seg)
            timestamps.append({
                "text": seg,
                "start": round(offset, 3),
                "end": round(offset + seg_dur, 3),
            })
            offset += seg_dur

        self.logger.info(
            f"CosyVoice 合成完成 duration={duration:.2f}s segments={len(segments)} "
            f"sr={sample_rate}"
        )
        return output_path, duration, timestamps

    @staticmethod
    def _concat_tts_segments(
        seg_audios: list, sample_rate: int, segments: list[str],
        pause_duration: float = 0.5,
    ) -> tuple:
        """专业级 TTS 分段拼接：边缘淡化 + 句间停顿

        - 每段头部 20ms / 尾部 50ms 线性淡化：消除段边界的爆音与能量跳变
        - 句末为 。！？ 的段后插入 pause_duration 静音：自然呼吸感（此前该参数是假的）
        - 返回 (拼接音频, 每段真实时长列表含停顿)，供字幕时间戳精确对齐
        """
        import numpy as np

        fade_in_n = max(1, int(sample_rate * 0.020))
        fade_out_n = max(1, int(sample_rate * 0.050))
        pause_n = max(0, int(sample_rate * max(0.0, min(pause_duration, 3.0))))

        pieces = []
        seg_durations = []
        for idx, data in enumerate(seg_audios):
            if data is None or len(data) == 0:
                continue
            seg = data.copy()
            n = len(seg)
            # 头部淡入（段间衔接处；首段保留原始起音）
            if idx > 0 and n > fade_in_n:
                seg[:fade_in_n] *= np.linspace(0.0, 1.0, fade_in_n, dtype=np.float32)
            # 尾部淡出
            if n > fade_out_n:
                seg[-fade_out_n:] *= np.linspace(1.0, 0.0, fade_out_n, dtype=np.float32)
            pieces.append(seg)
            seg_durations.append(n / sample_rate)

            # 句间停顿：句末为句号/叹号/问号且非最后一段
            if pause_n > 0 and idx < len(seg_audios) - 1:
                seg_text = segments[idx].rstrip() if idx < len(segments) else ""
                if seg_text and seg_text[-1] in "。！？!?":
                    pieces.append(np.zeros(pause_n, dtype=np.float32))
                    seg_durations[-1] += pause_n / sample_rate

        if not pieces:
            import numpy as _np
            return _np.zeros(0, dtype=_np.float32), []
        if len(pieces) == 1:
            return pieces[0], seg_durations
        import numpy as _np
        return _np.concatenate(pieces), seg_durations

    def _resolve_cosyvoice_voice(
        self, voice_id: str, cfg: dict
    ) -> tuple[Path | None, str]:
        """解析 CosyVoice 音色，返回 (参考音频路径, 参考文本)

        优先级：
        1. voice_id 在 COSYVOICE_PRESET_VOICES → voices_dir/{voice_id}/sample.wav
        2. voice_id 对应目录有样本音频 → 用该样本
        3. 配置的 default_voice → 同上解析
        4. 回退到第一个预置音色
        """
        from ..core.config import PROJECT_ROOT

        voices_dir = Path(cfg.get("voices_dir", "./config/voices"))
        if not voices_dir.is_absolute():
            voices_dir = PROJECT_ROOT / voices_dir

        # 候选 voice_id 列表（依次尝试）
        candidates = [voice_id]
        default_voice = cfg.get("default_voice", "")
        if default_voice and default_voice != voice_id:
            candidates.append(default_voice)
        # 回退到第一个预置音色
        if COSYVOICE_PRESET_VOICES:
            first_preset = next(iter(COSYVOICE_PRESET_VOICES))
            if first_preset not in candidates:
                candidates.append(first_preset)

        for vid in candidates:
            if not vid or vid == "default":
                continue
            # 预置音色的 ref_text
            ref_text = COSYVOICE_PRESET_VOICES.get(vid, {}).get("ref_text", "")

            voice_dir = voices_dir / vid
            if voice_dir.exists():
                # 查找样本音频
                for ext in (".wav", ".mp3", ".flac", ".m4a"):
                    candidates_files = list(voice_dir.glob(f"sample*{ext}")) + list(
                        voice_dir.glob(f"*{ext}")
                    )
                    if candidates_files:
                        # 读取 ref_text.txt（如有）
                        ref_text_file = voice_dir / "ref_text.txt"
                        if ref_text_file.exists():
                            try:
                                ref_text = ref_text_file.read_text(encoding="utf-8").strip()
                            except Exception:
                                pass
                        self.logger.info(
                            f"CosyVoice 音色解析 voice={vid} sample={candidates_files[0].name}"
                        )
                        return candidates_files[0].resolve(), ref_text

        return None, ""

    def _call_cosyvoice_api(
        self, server_url: str, text: str, prompt_audio_path: Path,
        prompt_text: str, instruct: str = "", speed: float = 1.0, timeout: int = 180,
    ) -> bytes | None:
        """调用 CosyVoice 服务端 API 合成单段文本

        有 instruct 时走 /api/tts/instruct，否则走 /api/tts/synth（零样本克隆）

        Returns:
            WAV 音频 bytes，失败返回 None
        """
        endpoint = "/api/tts/instruct" if instruct else "/api/tts/synth"
        url = f"{server_url}{endpoint}"

        try:
            with open(prompt_audio_path, "rb") as f:
                files = {"prompt_wav": (prompt_audio_path.name, f, "audio/wav")}
                data = {"tts_text": text, "speed": str(speed)}
                if instruct:
                    data["instruct_text"] = instruct
                    data["stream"] = "false"
                else:
                    data["prompt_text"] = prompt_text
                    data["stream"] = "false"

                self.logger.info(
                    f"CosyVoice API request: url={url} "
                    f"text='{text[:30]}' prompt_text='{prompt_text[:30]}' "
                    f"instruct='{instruct}' file={prompt_audio_path.name} "
                    f"file_size={prompt_audio_path.stat().st_size}"
                )
                # 共享 Client（keep-alive 连接复用）：多段文本合成时省去每段 TCP 握手
                r = self._cosyvoice_http_client().post(
                    url, files=files, data=data, timeout=timeout
                )

            if r.status_code == 200:
                return r.content
            else:
                self.logger.warning(
                    f"CosyVoice API 返回 HTTP {r.status_code}: {r.text[:200]}"
                )
                return None
        except httpx.ConnectError:
            self.logger.error(
                f"无法连接 CosyVoice 服务 {server_url}，请确认 cosyvoice_server.py 已启动"
            )
            return None
        except Exception as e:
            self.logger.warning(f"CosyVoice API 调用异常: {e}")
            return None

    def _build_timestamps_from_segments(
        self, segments: list[str], duration: float, sample_rate: int
    ) -> list[dict]:
        """根据分句和总时长生成时间戳（兜底用）"""
        timestamps = []
        offset = 0.0
        for seg in segments:
            if not seg.strip():
                continue
            seg_dur = estimate_speech_duration(seg)
            timestamps.append({
                "text": seg,
                "start": round(offset, 3),
                "end": round(offset + seg_dur, 3),
            })
            offset += seg_dur
        return timestamps

    def _synth_moss_nano(
        self, text: str, voice_id: str, output_path: Path,
        speed: float | None = None, volume: int | None = None,
        pitch: int | None = None, emotion: str | None = None,
    ) -> tuple[Path, float, list[dict]]:
        """使用本地 MOSS-TTS-Nano ONNX 合成（支持声音克隆）

        音色选择优先级：
        1. voice_id 对应目录下有 sample 音频 → 用该音频做零样本声音克隆
        2. voice_id 是 MOSS 内置音色（Zhiming/Weiguo/Xiaoyu/Yuewen/Lingyu/Trump/Ava/Bella/Adam/Nathan）→ 用该内置音色
        3. 回退到 config 的 builtin_voice（默认 Zhiming）
        """
        # emotion 暂不支持，仅 edge_tts 支持情感映射
        runtime = self._get_moss_runtime()
        cfg = self.config.get("tts.moss_nano", {}) or {}

        # MOSS 内置音色清单（11 个：6 中文 + 5 英文，Junhao 保留兼容但 UI 不展示）
        MOSS_BUILTIN_VOICES = {
            # 中文音色（Junhao 已从音色列表移除，但 MOSS 模型仍支持，保留以便兼容旧配置）
            "Junhao", "Zhiming", "Weiguo", "Xiaoyu", "Yuewen", "Lingyu",
            # 英文音色
            "Trump", "Ava", "Bella", "Adam", "Nathan",
        }
        config_builtin = cfg.get("builtin_voice", "Zhiming")

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

        # v9: 移除 Junhao padded 参考音频特殊处理
        # 根因：padded 参考音频（300ms开头+500ms尾部静音）被 codec 重新编码后，
        #   模型学到"静音→说话→静音"模式，导致每个 chunk 都生成 700-1000ms 静音，
        #   静音占比高达 52%（正常 <25%）。改为使用 manifest 预编码（与 Xiaoyu 一致），
        #   开头急促问题通过后处理补静音解决（见下方 _ensure_leading_silence）。
        # v8 原方案：使用 padded 参考音频 → 导致大量内部静音/卡顿

        self.logger.info(
            f"MOSS-TTS-Nano 合成 voice={voice_id} builtin={actual_builtin} "
            f"clone={'是' if prompt_audio_path else '否'} text_len={len(text)}"
        )

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
            # v9.14: 固定 seed 默认值 9999，消除 fixed 模式下 rng 跨 synthesize 调用累积
            # 根因：fixed 模式每帧调用 self.rng.random()，若不传 seed，rng 状态跨句子累积
            # 导致播客中每轮对话发音随机波动（前2轮 RMS 偏高→口音明显，第3轮 RMS 偏低→听感标准）
            # 修复：默认 seed=9999，每次 synthesize 重置 rng → 3 轮变异系数从 12.2% 降至 3.4%
            seed=int(cfg.get("seed", 9999)),
            sample_mode=sample_mode_val,
            do_sample=do_sample_val,
        )

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

        # v9: 补齐开头静音（修复 Junhao 开头急促问题）
        # 根因：Junhao manifest 预编码参考音频 zh_1.wav 开头静音仅 60ms，
        #   模型学到的韵律导致输出开头静音不足（< 100ms），听起来急促。
        #   其他音色（Xiaoyu 200ms、Zhiming 200ms 开头静音）无此问题。
        # 修复：检测输出开头静音，不足 150ms 时补齐到 200ms。
        try:
            import soundfile as _sf2
            import numpy as _np2
            _data2, _sr2 = _sf2.read(str(result["audio_path"]), dtype="float32")
            if _data2.ndim == 1:
                _data2 = _data2.reshape(-1, 1)
            _win2 = int(_sr2 * 0.01)  # 10ms 窗口
            _silence_threshold2 = 0.01
            # 从开头向后找第一个非静音窗口
            _first_speech2 = len(_data2)
            for _i2 in range(0, len(_data2) - _win2, _win2):
                _w2 = _data2[_i2: _i2 + _win2]
                _rms2 = float(_np2.sqrt(_np2.mean(_w2 ** 2)))
                if _rms2 > _silence_threshold2:
                    _first_speech2 = _i2
                    break
            _leading_silence_ms2 = _first_speech2 / _sr2 * 1000
            if _leading_silence_ms2 < 150:
                # 补齐到 200ms 开头静音
                _pad_samples2 = int(_sr2 * 0.2) - _first_speech2
                if _pad_samples2 > 0:
                    _padding2 = _np2.zeros((_pad_samples2, _data2.shape[1]), dtype=_data2.dtype)
                    _padded2 = _np2.concatenate([_padding2, _data2], axis=0)
                    _sf2.write(str(result["audio_path"]), _padded2, _sr2, subtype="PCM_16")
                    self.logger.info(
                        f"v9: 补齐开头静音 {_leading_silence_ms2:.0f}ms → 200ms"
                    )
            elif _leading_silence_ms2 > 200:
                # v9.8: 截断过长的开头静音到 200ms
                # 根因：Junhao 音色在 fixed 模式下会生成 500ms+ 开头静音，
                #   导致用户听感"等很久才出声"。原 v9 逻辑只补齐 < 150ms，不截断 > 200ms。
                # 修复：保留前 200ms 静音 + 从语音起点开始的音频。
                _keep_samples2 = int(_sr2 * 0.2)
                _trimmed2 = _np2.concatenate([
                    _data2[:_keep_samples2],       # 保留 200ms 开头静音
                    _data2[_first_speech2:],        # 从语音起点开始的音频
                ], axis=0)
                _sf2.write(str(result["audio_path"]), _trimmed2, _sr2, subtype="PCM_16")
                self.logger.info(
                    f"v9.8: 截断开头静音 {_leading_silence_ms2:.0f}ms → 200ms"
                )
        except Exception as _e2:
            self.logger.warning(f"v9: 开头静音补齐失败: {_e2}")

        # v9.1: 压缩内部静音（修复 Junhao chunk 间静音过长问题）
        # 根因：Junhao 音色在 fixed 模式下，模型会在 chunk 边界生成 700-1000ms 静音，
        #   导致说话卡顿（静音占比 50%+，正常 <25%）。inter-chunk pause 仅 180ms，
        #   但模型在 chunk 内部也生成大量静音。
        # 修复：检测超过 300ms 的内部静音段，压缩到 200ms。保留首尾静音不变。
        try:
            import soundfile as _sf3
            import numpy as _np3
            _data3, _sr3 = _sf3.read(str(result["audio_path"]), dtype="float32")
            if _data3.ndim == 1:
                _data3 = _data3.reshape(-1, 1)
            _win3 = int(_sr3 * 0.01)  # 10ms 窗口
            _silence_threshold3 = 0.01
            _channels3 = _data3.shape[1]

            # 找到第一个和最后一个非静音窗口
            _first_speech3 = 0
            _last_speech3 = len(_data3)
            for _i3 in range(0, len(_data3) - _win3, _win3):
                _w3 = _data3[_i3: _i3 + _win3]
                _rms3 = float(_np3.sqrt(_np3.mean(_w3 ** 2)))
                if _rms3 > _silence_threshold3:
                    _first_speech3 = _i3
                    break
            for _i3 in range(len(_data3) - _win3, -1, -_win3):
                _w3 = _data3[_i3: _i3 + _win3]
                _rms3 = float(_np3.sqrt(_np3.mean(_w3 ** 2)))
                if _rms3 > _silence_threshold3:
                    _last_speech3 = _i3 + _win3
                    break

            # 只压缩语音范围内的内部静音
            if _last_speech3 > _first_speech3:
                _speech_range = _data3[_first_speech3:_last_speech3]
                # 标记每个窗口是否为静音
                _is_silence = []
                for _i3 in range(0, len(_speech_range) - _win3, _win3):
                    _w3 = _speech_range[_i3: _i3 + _win3]
                    _rms3 = float(_np3.sqrt(_np3.mean(_w3 ** 2)))
                    _is_silence.append(_rms3 < _silence_threshold3)

                # 找到连续静音段并压缩
                _compressed = []
                _sil_start3 = -1
                _total_compressed_ms = 0
                _max_silence_ms = 100  # v9.12: 超过此值才压缩（原 150ms，导致 Lancer 克隆 140ms 静音未被压缩，听感断续）
                _target_silence_ms = 120  # v9.10: 压缩到此值（原 150ms，中文播客听感仍卡顿）
                _target_silence_samples = int(_sr3 * _target_silence_ms / 1000)

                for _idx3, _sil in enumerate(_is_silence):
                    if _sil:
                        if _sil_start3 < 0:
                            _sil_start3 = _idx3
                    else:
                        if _sil_start3 >= 0:
                            _sil_dur_ms = (_idx3 - _sil_start3) * 10
                            if _sil_dur_ms >= _max_silence_ms:
                                # 压缩这段静音
                                _compressed.append(_np3.zeros((_target_silence_samples, _channels3), dtype=_data3.dtype))
                                _total_compressed_ms += _sil_dur_ms - _target_silence_ms
                            else:
                                # 保留原始静音
                                _sil_start_sample = _sil_start3 * _win3
                                _sil_end_sample = _idx3 * _win3
                                _compressed.append(_speech_range[_sil_start_sample:_sil_end_sample])
                            _sil_start3 = -1
                        # 保留非静音部分
                        _seg_start = _idx3 * _win3
                        _seg_end = (_idx3 + 1) * _win3
                        _compressed.append(_speech_range[_seg_start:_seg_end])

                # 处理末尾的静音段
                if _sil_start3 >= 0:
                    _sil_dur_ms = (len(_is_silence) - _sil_start3) * 10
                    if _sil_dur_ms >= _max_silence_ms:
                        _compressed.append(_np3.zeros((_target_silence_samples, _channels3), dtype=_data3.dtype))
                        _total_compressed_ms += _sil_dur_ms - _target_silence_ms
                    else:
                        _sil_start_sample = _sil_start3 * _win3
                        _compressed.append(_speech_range[_sil_start_sample:])

                if _total_compressed_ms > 0 and _compressed:
                    _result3 = _np3.concatenate([
                        _data3[:_first_speech3],  # 保留开头静音
                        _np3.concatenate(_compressed, axis=0),  # 压缩后的语音
                        _data3[_last_speech3:],  # 保留尾部静音
                    ], axis=0)
                else:
                    _result3 = _data3

                # v9.10: 优化淡入长度（80ms → 40ms）
                # v9.9 缺陷：80ms 淡入过长，覆盖到 292ms，导致 240-292ms 稳定语音被压制 40-86%
                #   实例：255ms 处原始 RMS=0.2384，压制后 0.0795（降低 67%），听感"闷"和"断续"
                # v9.10 修复：缩短到 40ms，只覆盖过渡区 212-252ms
                #   效果：220-235ms 过渡区被有效压制（84-97%），240ms 后完全保留语音（0% 压制）
                # v9.9 保留逻辑（prev 2ms / next 30ms / search 5ms）：
                #   1. prev 窗口 2ms，只检测紧邻检测点的静音
                #   2. next 窗口 30ms，避免在静音段提前触发
                #   3. 搜索窗口 5ms，RMS 更稳定
                _fade_ms_99 = 40  # v9.10: 80ms → 40ms（避免过度压制稳定语音）
                _fade_samples_99 = int(_sr3 * _fade_ms_99 / 1000)
                _detect_step_99 = int(_sr3 * 0.01)   # 10ms 检测步进（性能考虑）
                _prev_win_99 = int(_sr3 * 0.002)     # 2ms prev 窗口（修复 3880ms 漏检）
                _next_win_99 = int(_sr3 * 0.03)      # 30ms next 窗口（避免提前触发）
                _silence_rms_99 = 0.005  # 静音判定
                _speech_rms_99 = 0.015   # 语音判定
                _search_step_99 = int(_sr3 * 0.005)  # 5ms 步进定位过渡区起点
                _fade_applied_99 = 0
                _skip_until_99 = 0

                for _i99 in range(_prev_win_99, len(_result3) - _next_win_99 - _fade_samples_99, _detect_step_99):
                    if _i99 < _skip_until_99:
                        continue
                    _prev_frame_99 = _result3[_i99 - _prev_win_99:_i99]
                    _next_frame_99 = _result3[_i99:_i99 + _next_win_99]
                    if _prev_frame_99.shape[0] < _prev_win_99 or _next_frame_99.shape[0] < _next_win_99:
                        continue
                    _prev_rms_99 = float(_np3.sqrt(_np3.mean(_prev_frame_99 ** 2)))
                    _next_rms_99 = float(_np3.sqrt(_np3.mean(_next_frame_99 ** 2)))

                    if _prev_rms_99 < _silence_rms_99 and _next_rms_99 > _speech_rms_99:
                        # v9.13: 区分开头边界和内部边界，使用不同阈值
                        # v9.12 缺陷：对所有边界统一用阈值 5，导致 Xiaoyu 开头（ratio=8.6, 11.9）被误判为"突变"而应用淡入
                        #   实测数据：
                        #   - Xiaoyu 开头边界 ratio=8.6/11.9（平缓上升，不应淡入）
                        #   - Lancer 开头边界 ratio=544.3（真正突变，应淡入）
                        #   - 内部边界 ratio=3-15（需要区分，阈值 5 合适）
                        # v9.13 修复：开头边界（_fade_applied_99==0）使用阈值 20，内部边界保持阈值 5
                        #   依据：需要淡入的音色（Junhao/Lancer）开头 ratio 通常 >100，平缓音色（Xiaoyu）开头 ratio <15
                        _energy_ratio_99 = _next_rms_99 / max(_prev_rms_99, 0.0001)
                        _threshold_99 = 20.0 if _fade_applied_99 == 0 else 5.0
                        if _energy_ratio_99 < _threshold_99:
                            _skip_until_99 = _i99 + _next_win_99
                            _boundary_type_99 = "开头" if _fade_applied_99 == 0 else "内部"
                            self.logger.info(
                                f"v9.13: 跳过淡入（{_boundary_type_99}边界能量上升平缓 ratio={_energy_ratio_99:.1f}<{_threshold_99:.0f}）"
                                f" 检测点={_i99/_sr3*1000:.1f}ms prev_rms={_prev_rms_99:.4f} next_rms={_next_rms_99:.4f}"
                            )
                            continue
                        # v9.9: 从检测点开始按 5ms 步进找到过渡区起点（第一个 RMS > silence_rms 的点）
                        _fade_start_99 = _i99  # 默认从检测点开始
                        _search_end_99 = min(_i99 + _next_win_99, len(_result3) - _search_step_99)
                        for _j99 in range(_i99, _search_end_99, _search_step_99):
                            _probe_frame_99 = _result3[_j99:_j99 + _search_step_99]
                            if _probe_frame_99.shape[0] < _search_step_99:
                                break
                            _probe_rms_99 = float(_np3.sqrt(_np3.mean(_probe_frame_99 ** 2)))
                            if _probe_rms_99 > _silence_rms_99:
                                _fade_start_99 = _j99
                                break

                        # 从过渡区起点应用 80ms 平方淡入
                        _fade_end_99 = min(_fade_start_99 + _fade_samples_99, len(_result3))
                        _fade_len_99 = _fade_end_99 - _fade_start_99
                        if _fade_len_99 > 0:
                            _fade_region_99 = _result3[_fade_start_99:_fade_end_99].astype(_np3.float32, copy=True)
                            # v9.11: 使用三次方淡入（envelope = (t/T)³）
                            # v9.10 缺陷：平方淡入在早期压制不足，220ms 处只压制 67%，爆破音仍可闻
                            # v9.11 修复：三次方淡入在早期提供更强压制（envelope=0.19 vs 0.33），
                            #   后期快速恢复（envelope=0.56 vs 0.68），既消除爆破音又保留语音自然度
                            _fade_linear_99 = _np3.linspace(0, 1, _fade_len_99, dtype=_np3.float32)
                            _fade_envelope_99 = _fade_linear_99 ** 3  # v9.11: 三次方淡入
                            if _fade_region_99.ndim == 2:
                                _fade_envelope_99 = _fade_envelope_99.reshape(-1, 1)
                            _faded_region_99 = _fade_region_99 * _fade_envelope_99
                            _result3[_fade_start_99:_fade_end_99] = _faded_region_99
                            _fade_applied_99 += 1
                            _skip_until_99 = _fade_end_99
                            self.logger.info(
                                f"v9.13: 淡入 #{_fade_applied_99} 检测点={_i99/_sr3*1000:.1f}ms "
                                f"过渡区起点={_fade_start_99/_sr3*1000:.1f}ms "
                                f"淡入结束={_fade_end_99/_sr3*1000:.1f}ms "
                                f"prev_rms={_prev_rms_99:.4f} next_rms={_next_rms_99:.4f} ratio={_energy_ratio_99:.1f}"
                            )

                _sf3.write(str(result["audio_path"]), _result3, _sr3, subtype="PCM_16")
                self.logger.info(
                    f"v9.13: 压缩内部静音 {_total_compressed_ms}ms, 应用淡入 {_fade_applied_99} 处 "
                    f"(原时长={len(_data3)/_sr3:.2f}s → 新时长={len(_result3)/_sr3:.2f}s)"
                )
        except Exception as _e3:
            self.logger.warning(f"v9.13: 内部静音压缩/淡入失败: {_e3}")

        audio_path = Path(result["audio_path"])
        # 保留 MOSS 原始 48kHz 立体声输出：
        # - 数字人场景：Wav2Lip 服务端 audio.load_wav(path, 16000) 会自行重采样到 16kHz 单声道
        # - 播客场景：podcast_engine 会重采样到 24kHz；保留 48kHz 避免 16k→24k 上采样损失音质
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
        # 关键：系统 ffmpeg 可能是极简编译版（--disable-everything，无 mp3 解码器），
        #   必须用 imageio-ffmpeg 自带的完整版 ffmpeg，否则 mp3 转换静默失败
        final_path = mp3_path
        try:
            import subprocess
            import imageio_ffmpeg
            ffmpeg_cmd = imageio_ffmpeg.get_ffmpeg_exe()
            result = subprocess.run(
                [ffmpeg_cmd, "-y", "-i", str(mp3_path), "-acodec", "pcm_s16le",
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

    def analyze_reference_audio(self, sample_audio: Path) -> dict:
        """分析参考音频质量，返回结构化质量报告

        用于声音克隆前的质量检测，识别开头/尾部静音过长、语音占比低、
        内部静音段过多、信噪比低、时长不达标等问题。

        Returns:
            {
                "ok": bool,                     # 是否无明显质量问题
                "metrics": {...},               # 详细指标
                "warnings": [str, ...],         # 警告列表
                "suggestions": [str, ...],      # 录制改进建议
            }
        """
        import numpy as np
        import soundfile as sf

        sample_audio = Path(sample_audio)
        result: dict[str, Any] = {
            "ok": True,
            "metrics": {},
            "warnings": [],
            "suggestions": [],
        }

        if not sample_audio.exists():
            result["ok"] = False
            result["warnings"].append(f"音频文件不存在: {sample_audio}")
            return result

        try:
            data, sr = sf.read(str(sample_audio), dtype="float32")
        except Exception as e:
            result["ok"] = False
            result["warnings"].append(f"音频文件读取失败: {e}")
            return result

        # 立体声转单声道
        if data.ndim > 1:
            data = data.mean(axis=1)

        duration_ms = len(data) / sr * 1000
        rms = float(np.sqrt(np.mean(data ** 2)))
        peak = float(np.max(np.abs(data)))

        # 静音分析（10ms 窗口）
        win = int(sr * 0.01)
        n = len(data) // win
        threshold = 0.01
        first_speech = 0
        last_speech = len(data)

        for i in range(n):
            w = data[i * win:(i + 1) * win]
            r = float(np.sqrt(np.mean(w ** 2)))
            if r > threshold:
                if first_speech == 0:
                    first_speech = i * win
                last_speech = (i + 1) * win

        leading_silence_ms = first_speech / sr * 1000
        trailing_silence_ms = (len(data) - last_speech) / sr * 1000

        # 内部静音段（>=100ms 的连续静音，排除开头和尾部）
        internal_silences: list[tuple[int, int, int]] = []
        current_silence_start = None
        for i in range(n):
            w = data[i * win:(i + 1) * win]
            r = float(np.sqrt(np.mean(w ** 2)))
            if r <= threshold:
                if current_silence_start is None:
                    current_silence_start = i * 10
            else:
                if current_silence_start is not None:
                    silence_duration = i * 10 - current_silence_start
                    if silence_duration >= 100:
                        # 仅记录真正的内部静音（非开头/尾部）
                        if current_silence_start != 0 and i * 10 < duration_ms - 50:
                            internal_silences.append(
                                (current_silence_start, i * 10, silence_duration)
                            )
                    current_silence_start = None

        # 信噪比估计（粗略）：语音段 RMS / 静音段 RMS
        speech_mask = np.zeros(len(data), dtype=bool)
        for i in range(n):
            w = data[i * win:(i + 1) * win]
            if float(np.sqrt(np.mean(w ** 2))) > threshold:
                speech_mask[i * win:(i + 1) * win] = True
        speech_rms = float(np.sqrt(np.mean(data[speech_mask] ** 2))) if speech_mask.any() else 0.0
        silence_mask = ~speech_mask
        noise_rms = float(np.sqrt(np.mean(data[silence_mask] ** 2))) if silence_mask.any() else 0.001
        # 避免 log10(0) = -inf：当 speech_rms 为 0 时（纯静音音频），SNR = 0
        if speech_rms <= 1e-6:
            snr_db = 0.0
        else:
            snr_db = 20 * float(np.log10(speech_rms / max(noise_rms, 1e-6)))

        # 语音占比
        speech_ratio_pct = speech_mask.sum() / max(len(data), 1) * 100

        # 基频估计（限制 80-300Hz 人声范围）
        f0 = 0.0
        try:
            from scipy.signal import welch
            freqs, psd = welch(data, sr, nperseg=min(4096, len(data)))
            voice_mask = (freqs >= 80) & (freqs <= 300)
            voice_freqs = freqs[voice_mask]
            voice_psd = psd[voice_mask]
            if len(voice_freqs) > 0:
                f0_idx = int(np.argmax(voice_psd))
                f0 = float(voice_freqs[f0_idx])
        except Exception:
            # scipy 不可用时跳过基频检测
            pass

        metrics = {
            "duration_ms": round(duration_ms),
            "duration_s": round(duration_ms / 1000, 2),
            "sample_rate": sr,
            "rms": round(rms, 4),
            "peak": round(peak, 4),
            "leading_silence_ms": round(leading_silence_ms),
            "trailing_silence_ms": round(trailing_silence_ms),
            "internal_silence_count": len(internal_silences),
            "internal_silences": [
                {"start_ms": s, "end_ms": e, "duration_ms": d}
                for s, e, d in internal_silences
            ],
            "speech_ratio_pct": round(speech_ratio_pct, 1),
            "snr_db": round(snr_db, 1),
            "f0_hz": round(f0, 1),
            "speech_rms": round(speech_rms, 4),
            "noise_rms": round(noise_rms, 4),
        }
        result["metrics"] = metrics

        # 质量评估
        warnings: list[str] = []
        if leading_silence_ms > 500:
            warnings.append(
                f"开头静音过长（{leading_silence_ms:.0f}ms > 500ms），建议裁剪到 200ms 以内，"
                f"否则克隆音色首字发音不稳定"
            )
        if trailing_silence_ms > 500:
            warnings.append(
                f"尾部静音过长（{trailing_silence_ms:.0f}ms > 500ms），建议裁剪到 200ms 以内，"
                f"浪费参考音频有效时长"
            )
        if speech_ratio_pct < 60:
            warnings.append(
                f"语音占比过低（{speech_ratio_pct:.1f}% < 60%），静音太多，"
                f"模型学不到足够的韵律特征，克隆发音不标准"
            )
        if snr_db < 20:
            warnings.append(
                f"信噪比过低（{snr_db:.1f}dB < 20dB），有背景噪音，"
                f"会污染克隆音色，导致发音模糊或带杂音"
            )
        if duration_ms < 5000:
            warnings.append(
                f"时长过短（{duration_ms:.0f}ms < 5000ms），建议 10-30s，"
                f"参考音频太短模型学不到稳定音色"
            )
        if duration_ms > 30000:
            warnings.append(
                f"时长过长（{duration_ms:.0f}ms > 30000ms），建议 10-30s，"
                f"参考音频太长会稀释关键韵律特征"
            )
        if len(internal_silences) > 3:
            warnings.append(
                f"内部静音段过多（{len(internal_silences)}段 > 3段），"
                f"影响韵律学习，会导致克隆发音卡顿或节奏不自然"
            )

        # 录制改进建议（仅在有问题时才返回）
        if warnings:
            result["suggestions"] = [
                "在安静环境录制（关闭风扇、空调、电视等噪音源）",
                "使用高质量麦克风（推荐 USB 麦克风或手机原装麦克风）",
                "距离麦克风 15-20cm，避免喷麦（可加防喷罩）",
                "录制 10-20s 的连续语音，不要有长时间停顿",
                "朗读标准普通话内容（避免方言、口语化表达）",
                "语速自然，不要太快或太慢",
                "录制完成后裁剪开头/尾部静音到 200ms 以内",
                "确保音频格式为 WAV，采样率 >= 16kHz",
                "避免音频中有咳嗽、清嗓子等非语音声音",
                "推荐录制内容：自我介绍 + 一段短文朗读",
            ]

        result["warnings"] = warnings
        result["ok"] = len(warnings) == 0
        return result

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
