"""数字人口播生成模块

四种 provider：
- wav2lip:     本地 Wav2Lip 唇形同步（CPU 可跑，输入真人照片/视频+音频→嘴唇会动）
- musetalk:    调用云端 MuseTalk API（口型同步）
- latentsync:  调用云端 LatentSync API（备选）
- mock:        音频 + 静态占位图合成视频（保证流程可跑通）

输出：口播视频 mp4 文件
"""
from __future__ import annotations

import base64
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from ..core.base_module import BaseModule, JobContext, ModuleResult
from ..core.ffmpeg_utils import FFmpegRunner
from ..core.gpu_runner import GPURunner


class AvatarEngine(BaseModule):
    """数字人口播生成模块"""

    name = "avatar"
    requires_gpu = False  # wav2lip CPU 也可跑

    def __init__(self, config=None, gpu_runner: GPURunner | None = None,
                 ffmpeg: FFmpegRunner | None = None):
        super().__init__(config)
        self.provider = self.config.get("avatar.provider", "mock")
        self.api_base = self.config.get("avatar.api_base", "")
        self.avatars_dir = Path(self.config.get("avatar.avatars_dir", "./config/avatars"))
        self.default_avatar = self.config.get("avatar.default_avatar", "default")
        self.output_fps = self.config.get("avatar.output_fps", 25)
        res = self.config.get("avatar.output_resolution", [1080, 1920])
        self.output_resolution = tuple(res) if isinstance(res, list) else (1080, 1920)
        # Wav2Lip 配置
        self.wav2lip_config = self.config.get("avatar.wav2lip", {})
        self.wav2lip_checkpoint = self.wav2lip_config.get(
            "checkpoint_path", "./Wav2Lip/checkpoints/wav2lip_gan.pth"
        )
        self.wav2lip_env_python = self.wav2lip_config.get(
            "env_python", "../wav2lip_env/Scripts/python.exe"
        )
        self.wav2lip_inference_script = self.wav2lip_config.get(
            "inference_script", "../Wav2Lip/inference.py"
        )
        self.wav2lip_device = self.wav2lip_config.get("device", "auto")
        # 微动作配置
        self.micro_motion_cfg = self.config.get("avatar.micro_motion", {}) or {}
        # GFPGAN 人脸增强配置
        self.gfpgan_cfg = self.config.get("avatar.gfpgan", {}) or {}
        self.gpu = gpu_runner or GPURunner()
        self.ffmpeg = ffmpeg or FFmpegRunner()
        # Scene 配置（背景类型）
        scene_cfg = self.config.get("scene", {}) or {}
        self.scene_bg_type = scene_cfg.get("background_type", "transparent")
        self.scene_bg_color = scene_cfg.get("background_color", "#1A1A2E")
        self.scene_bg_image = scene_cfg.get("background_image", "")

    def setup(self) -> None:
        if self.provider == "wav2lip":
            # Wav2Lip 真实运行需要独立 Python3.8 环境（torch 1.13 等）
            # 不再静默降级到 mock —— 用户明确要求真实唇形同步
            ready, reason = self._check_wav2lip_env()
            if not ready:
                # 环境未就绪：保持 provider=wav2lip，run() 时会给出明确报错
                self.logger.warning(
                    f"Wav2Lip 环境未就绪: {reason}。"
                    f"请运行 scripts/setup_wav2lip_env.bat 安装，"
                    f"或将 avatar.provider 改为 mock 跳过真实唇形同步。"
                )
            else:
                self.logger.info(
                    f"数字人模块初始化 provider=wav2lip "
                    f"checkpoint={Path(self.wav2lip_checkpoint).name} "
                    f"env={Path(self.wav2lip_env_python).name}"
                )
        elif self.provider in ("musetalk", "latentsync", "echomimic"):
            available = self.gpu.health_check_avatar()
            if not available:
                self.logger.warning(
                    f"{self.provider} 云端服务不可用，将报错（不再静默降级 mock）"
                )
            else:
                self.logger.info(f"数字人模块初始化 provider={self.provider}")
        else:
            self.logger.info(f"数字人模块初始化 provider={self.provider}")
        super().setup()

    def _check_wav2lip_env(self) -> tuple[bool, str]:
        """检查 Wav2Lip 独立运行环境是否就绪

        不再静默降级。返回 (ready, reason)。
        ready=True 表示可真实推理；ready=False 时 reason 给出具体缺失项和指引。
        """
        from ..core.config import PROJECT_ROOT
        project_root = Path(PROJECT_ROOT)

        def _abs(p: str) -> Path:
            path = Path(p)
            return path if path.is_absolute() else (project_root / p).resolve()

        # 1. 独立 Python 环境存在
        env_python = _abs(self.wav2lip_env_python)
        if not env_python.exists():
            return False, (
                f"独立 Python 环境不存在: {env_python}。"
                f"请运行 scripts/setup_wav2lip_env.bat 创建 wav2lip_env。"
            )

        # 2. 推理脚本存在
        script = _abs(self.wav2lip_inference_script)
        if not script.exists():
            return False, f"Wav2Lip 推理脚本不存在: {script}"

        # 3. 模型权重存在
        ckpt = _abs(self.wav2lip_checkpoint)
        if not ckpt.exists():
            return False, (
                f"模型权重不存在: {ckpt}。"
                f"请从 hf-mirror 下载 wav2lip_gan.pth。"
            )

        # 4. 依赖（torch/librosa）能在独立环境 import
        try:
            result = subprocess.run(
                [str(env_python), "-c",
                 "import torch, librosa, cv2, numpy, scipy; "
                 "print('deps ok', torch.__version__)"],
                capture_output=True, text=True, timeout=120,
            )
            if result.returncode != 0:
                return False, (
                    f"wav2lip_env 依赖缺失: {result.stderr[-200:]}。"
                    f"请在该环境执行 pip install torch librosa opencv-python scipy。"
                )
        except Exception as e:
            return False, f"检测 wav2lip_env 依赖异常: {e}"

        return True, "ok"

    def _check_wav2lip_deps(self) -> bool:
        """[已废弃] 检查主环境依赖 —— 改用 _check_wav2lip_env 检测独立环境

        保留仅为向后兼容。Wav2Lip 现在用独立 Python 3.8 环境，主环境无需这些依赖。
        """
        return False

    def run(self, ctx: JobContext) -> ModuleResult:
        """根据 ctx.audio_path 生成口播视频"""
        if not ctx.audio_path or not ctx.audio_path.exists():
            return ModuleResult(success=False, error="无音频文件，无法生成数字人视频")

        avatar_id = ctx.avatar_id or self.default_avatar
        output_path = ctx.work_dir / "avatar_output.mp4"

        try:
            start = time.time()
            if self.provider == "wav2lip":
                # 真实 Wav2Lip：环境未就绪必须报错（不静默降级）
                ready, reason = self._check_wav2lip_env()
                if not ready:
                    return ModuleResult(
                        success=False,
                        error=f"Wav2Lip 环境未就绪: {reason}",
                    )
                video_path = self._generate_wav2lip(ctx, avatar_id, output_path)
            elif self.provider == "mock":
                video_path = self._generate_mock(ctx, avatar_id, output_path)
            else:
                video_path = self._generate_cloud(ctx, avatar_id, output_path)

            # 微动作后处理（可选，缓解静态照片/低质量数字人的恐怖谷）
            if self.micro_motion_cfg.get("enabled", False):
                video_path = self._apply_micro_motion(video_path, ctx)

            ctx.raw_video_path = video_path
            ctx.metadata["avatar_provider"] = self.provider

            # 探测视频信息
            info = self.ffmpeg.probe_video_info(video_path)
            duration = info.duration if info else ctx.audio_duration

            elapsed = time.time() - start
            self.logger.info(f"数字人生成完成 provider={self.provider} 耗时={elapsed:.1f}s")

            return ModuleResult(
                success=True,
                data={
                    "video_path": str(video_path),
                    "duration": duration,
                    "avatar_id": avatar_id,
                    "provider": self.provider,
                    "elapsed": elapsed,
                },
            )
        except Exception as e:
            return ModuleResult(success=False, error=str(e))

    def _generate_wav2lip(
        self, ctx: JobContext, avatar_id: str, output_path: Path
    ) -> Path:
        """使用 Wav2Lip 生成唇形同步视频

        输入：真人照片或视频 + 音频
        输出：嘴唇会动的视频
        """
        self.logger.info(
            f"Wav2Lip 唇形同步 avatar={avatar_id} audio={ctx.audio_path.name} "
            f"duration={ctx.audio_duration:.1f}s"
        )

        # 获取参考人脸（照片或视频）
        face_path = self._get_avatar_reference(avatar_id)
        if not face_path:
            raise RuntimeError(
                f"数字人 {avatar_id} 无参考照片/视频，请先上传真人照片或视频注册形象"
            )

        self.logger.info(f"参考人脸: {face_path}")

        # 准备音频（Wav2Lip 需要 wav 格式）
        audio_path = ctx.audio_path
        if audio_path.suffix.lower() != ".wav":
            wav_path = ctx.work_dir / "wav2lip_input.wav"
            self.ffmpeg.convert_audio(audio_path, wav_path)
            audio_path = wav_path

        # 调用 Wav2Lip 推理（使用独立的 Python 3.8 环境，非主项目 3.12）
        # 解析路径为绝对路径（配置里的相对路径基于项目根目录）
        from ..core.config import PROJECT_ROOT
        project_root = Path(PROJECT_ROOT)

        def _abs(p: str) -> Path:
            path = Path(p)
            return path if path.is_absolute() else (project_root / p).resolve()

        env_python = _abs(self.wav2lip_env_python)
        inference_script = _abs(self.wav2lip_inference_script)

        # 使用绝对路径（Wav2Lip 从自身目录运行，相对路径会失效）
        checkpoint_abs = _abs(self.wav2lip_checkpoint)
        face_abs = Path(face_path).resolve()
        audio_abs = Path(audio_path).resolve()
        output_abs = Path(output_path).resolve()

        # 质量优先：使用配置的 resize_factor（默认 1=最高质量）
        # 唇形同步是核心卖点，绝不为提速牺牲精度
        auto_resize = int(self.wav2lip_config.get("resize_factor", 1))
        audio_dur = ctx.audio_duration or 0
        self.logger.info(
            f"Wav2Lip 推理参数: resize_factor={auto_resize}（质量优先），音频 {audio_dur:.1f}s"
        )

        # 确定 Wav2Lip 运行设备（基于配置 + 自动检测）
        w2l_device = "cpu"
        if self.wav2lip_device == "cuda":
            w2l_device = "cuda"
        elif self.wav2lip_device == "auto":
            try:
                from ..core.hardware_probe import detect_cuda
                if detect_cuda():
                    w2l_device = "cuda"
                    self.logger.info("Wav2Lip 自动检测到 CUDA，将使用 GPU 加速")
                else:
                    self.logger.info("Wav2Lip 未检测到 CUDA，使用 CPU 模式")
            except Exception:
                pass

        # wav2lip_env 的 site-packages 在 PYTHONPATH，需保证用独立解释器
        cmd = [
            str(env_python), str(inference_script),
            "--checkpoint_path", str(checkpoint_abs),
            "--face", str(face_abs),
            "--audio", str(audio_abs),
            "--outfile", str(output_abs),
            "--pads", *[str(p) for p in self.wav2lip_config.get("pads", [0, 20, 0, 0])],
            "--face_det_batch_size", str(self.wav2lip_config.get("face_det_batch_size", 8)),
            "--wav2lip_batch_size", str(self.wav2lip_config.get("wav2lip_batch_size", 16)),
            "--resize_factor", str(auto_resize),
            "--device", w2l_device,
        ]
        if self.wav2lip_config.get("nosmooth", False):
            cmd.append("--nosmooth")

        self.logger.info(
            f"运行 Wav2Lip 推理 (设备: {w2l_device}, env={env_python.parent.parent.name}, "
            f"resize_factor={auto_resize})，音频 {audio_dur:.1f}s，预计耗时数分钟至数十分钟..."
        )
        # Wav2Lip 推理脚本内部加载依赖文件用相对路径，必须在 Wav2Lip 根目录运行
        wav2lip_root = inference_script.parent
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=7200,  # 120分钟超时（与前端 maxWait 对齐）
                cwd=str(wav2lip_root),
            )
        except subprocess.TimeoutExpired:
            self.logger.error(f"Wav2Lip 推理超时（120分钟），音频时长 {audio_dur:.1f}s")
            raise RuntimeError(
                f"Wav2Lip 推理超时（120分钟），音频 {audio_dur:.1f}s。"
                f"建议：1) 缩短文案 2) 在设置中将 resize_factor 调高 3) 使用 GPU"
            )

        if result.returncode != 0:
            self.logger.error(f"Wav2Lip 推理失败: {result.stderr[-500:]}")
            raise RuntimeError(f"Wav2Lip 推理失败: {result.stderr[-300:]}")

        if not output_path.exists():
            raise RuntimeError("Wav2Lip 推理完成但输出文件不存在")

        self.logger.info(
            f"Wav2Lip 唇形同步完成: {output_path.name} "
            f"({output_path.stat().st_size // 1024}KB)"
        )

        # GFPGAN 人脸增强（可选，提升脸部清晰度，CPU 可跑但较慢）
        # 在竖屏转换前增强（横屏原始分辨率，增强效果更好）
        if self.gfpgan_cfg.get("enabled", False):
            enhanced = self._enhance_with_gfpgan(output_path, ctx)
            if enhanced:
                output_path = enhanced

        # Wav2Lip 输出尺寸 = face 输入尺寸（通常横屏，如 1920x1080）
        # 转成竖屏 1080x1920（人脸居中 + 模糊背景，主流口播做法）
        portrait_path = ctx.work_dir / "avatar_portrait.mp4"
        # 根据 scene 配置选择背景填充方式
        bg_mode = "blur"  # 默认模糊背景
        bg_color = "#000000"
        bg_image = ""
        if self.scene_bg_type == "solid":
            bg_mode = "solid"
            bg_color = self.scene_bg_color
        elif self.scene_bg_type == "image" and self.scene_bg_image:
            bg_image = self.scene_bg_image
            if Path(bg_image).exists():
                bg_mode = "image"
            else:
                self.logger.warning(f"背景图片不存在，回退到模糊背景: {bg_image}")
                bg_mode = "blur"
        # transparent 和其他情况保持 blur
        try:
            self.ffmpeg.to_portrait(
                video=output_path,
                output=portrait_path,
                target_resolution=self.output_resolution,
                fps=self.output_fps,
                background=bg_mode,
                bg_color=bg_color,
                bg_image=bg_image,
            )
            return portrait_path
        except Exception as e:
            self.logger.warning(
                f"竖屏转换失败，使用原始横屏输出: {e}"
            )
            return output_path

    def _enhance_with_gfpgan(self, video_path: Path, ctx: JobContext) -> Path | None:
        """GFPGAN 人脸增强（提升 Wav2Lip 脸部清晰度，带唇形保护）

        通过 wav2lip_env 独立 Python 调用 enhance.py：
        - GFPGAN 逐帧增强（weight=0.5 降侵略性）
        - 嘴部 mask 贴回保护 Wav2Lip 唇形精度
        CPU 模式 10 秒视频约需 5-15 分钟。

        Returns:
            增强后的视频路径；失败返回 None（降级用原视频）
        """
        from ..core.config import PROJECT_ROOT
        project_root = Path(PROJECT_ROOT)

        def _abs(p: str) -> Path:
            path = Path(p)
            return path if path.is_absolute() else (project_root / p).resolve()

        env_python = _abs(self.wav2lip_env_python)
        enhance_script = _abs(self.gfpgan_cfg.get("enhance_script", "../wav2lip_env/enhance.py"))
        model_path = _abs(self.gfpgan_cfg.get("model_path", "../Wav2Lip/gfpgan_weights/GFPGANv1.4.pth"))
        weight = self.gfpgan_cfg.get("weight", 0.5)
        device = self.gfpgan_cfg.get("device", "cpu")

        # 环境检查
        if not env_python.exists() or not enhance_script.exists() or not model_path.exists():
            self.logger.warning(
                f"GFPGAN 环境不完整（env/script/model），跳过增强。"
                f"script={enhance_script.exists()} model={model_path.exists()}"
            )
            return None

        enhanced_path = ctx.work_dir / "avatar_enhanced.mp4"
        cmd = [
            str(env_python), str(enhance_script),
            "--input", str(video_path.resolve()),
            "--output", str(enhanced_path.resolve()),
            "--model", str(model_path),
            "--weight", str(weight),
            "--device", device,
        ]
        self.logger.info(
            f"GFPGAN 人脸增强（{device} 模式，weight={weight}），"
            f"CPU 可能需要数分钟至数十分钟..."
        )
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=7200,  # 2小时超时
            )
            if result.returncode != 0:
                self.logger.warning(
                    f"GFPGAN 增强失败（返回码{result.returncode}），用原视频: "
                    f"{result.stderr[-300:]}"
                )
                return None
            if not enhanced_path.exists():
                self.logger.warning("GFPGAN 增强完成但输出文件不存在，用原视频")
                return None
            self.logger.info(
                f"GFPGAN 增强完成: {enhanced_path.name} "
                f"({enhanced_path.stat().st_size // 1024}KB)"
            )
            return enhanced_path
        except subprocess.TimeoutExpired:
            self.logger.warning("GFPGAN 增强超时，用原视频")
            return None
        except Exception as e:
            self.logger.warning(f"GFPGAN 增强异常，用原视频: {e}")
            return None

    def _get_avatar_reference(self, avatar_id: str) -> Path | None:
        """获取数字人参考素材

        Wav2Lip 视频驱动模式（保留原视频头部动作+表情，只换嘴型）：
          优先级：reference_video.mp4 > reference.mp4 > avatar.mp4
                  > reference.jpg > reference.png > avatar.jpg

        视频输入让 Wav2Lip 逐帧保留原视频的姿态/表情/手势，只重绘嘴部；
        照片输入会退化成"静态照片+嘴动"（头不动），仅作降级。
        """
        avatar_dir = self.avatars_dir / avatar_id
        if not avatar_dir.exists():
            return None

        # 优先查找参考视频（视频驱动 = 保留原动作）
        for name in ("reference_video.mp4", "reference.mp4", "avatar.mp4"):
            p = avatar_dir / name
            if p.exists():
                return p

        # 降级：参考照片（照片驱动 = 头不动，仅嘴动）
        for name in ("reference.jpg", "reference.png", "avatar.jpg", "avatar.png"):
            p = avatar_dir / name
            if p.exists():
                return p

        return None

    def _generate_cloud(
        self, ctx: JobContext, avatar_id: str, output_path: Path
    ) -> Path:
        """调用云端数字人 API（LatentSync / MuseTalk / EchoMimic）"""
        self.logger.info(
            f"云端数字人生成 provider={self.provider} "
            f"avatar={avatar_id} audio={ctx.audio_path}"
        )

        # 读取音频并 base64 编码
        audio_b64 = base64.b64encode(ctx.audio_path.read_bytes()).decode()

        payload = {
            "audio_base64": audio_b64,
            "avatar_id": avatar_id,
            "output_fps": self.output_fps,
            "output_resolution": list(self.output_resolution),
        }

        # LatentSync 专用参数（覆盖云端默认）
        if self.provider == "latentsync":
            ls_cfg = self.config.get("avatar.latentsync", {}) or {}
            payload["inference_steps"] = ls_cfg.get("inference_steps", 25)
            payload["resolution"] = ls_cfg.get("resolution", 512)
            payload["config_name"] = ls_cfg.get("config", "high_quality")

        resp = self.gpu.call_avatar(payload)

        # 记录实际使用的后端（云端返回）
        backend = resp.get("backend")
        if backend:
            ctx.metadata["avatar_backend"] = backend
            self.logger.info(f"云端实际后端: {backend}")

        video_b64 = resp.get("video_base64") or resp.get("data", {}).get("video_base64")
        if not video_b64:
            # 如果返回的是 URL，下载
            video_url = resp.get("video_url")
            if video_url:
                import httpx
                r = httpx.get(video_url, timeout=120)
                r.raise_for_status()
                output_path.parent.mkdir(parents=True, exist_ok=True)
                output_path.write_bytes(r.content)
                return output_path
            raise RuntimeError(f"数字人 API 返回无视频数据: {resp}")

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(base64.b64decode(video_b64))
        self.logger.info(f"云端数字人生成完成 video={output_path}")
        return output_path

    def _generate_mock(
        self, ctx: JobContext, avatar_id: str, output_path: Path
    ) -> Path:
        """Mock 模式：生成占位头像图 + 音频合成视频"""
        self.logger.info(
            f"Mock 数字人生成 avatar={avatar_id} "
            f"audio={ctx.audio_path} duration={ctx.audio_duration:.2f}s"
        )

        # 生成或获取占位头像图
        avatar_image = self._get_avatar_image(avatar_id)

        # 用 ffmpeg 合成图片 + 音频 = 视频
        self.ffmpeg.image_audio_to_video(
            image=avatar_image,
            audio=ctx.audio_path,
            output=output_path,
            fps=self.output_fps,
            resolution=self.output_resolution,
            video_bitrate="4M",
        )
        self.logger.info(f"Mock 数字人视频生成完成: {output_path}")
        return output_path

    def _apply_micro_motion(self, video_path: Path, ctx: JobContext) -> Path:
        """应用微动作层（FFmpeg 后处理）

        给数字人口播视频叠加：呼吸缩放 + 微抖动 + 眨眼亮度节奏。
        纯 FFmpeg 实现，CPU 即可，缓解"只有嘴动"的恐怖谷。
        失败时降级返回原视频（不阻断流程）。
        """
        output_path = ctx.work_dir / "avatar_with_motion.mp4"
        w, h = self.output_resolution
        try:
            result_path = self.ffmpeg.add_micro_motion(
                video=video_path,
                output=output_path,
                width=w,
                height=h,
                fps=self.output_fps,
                breathing_scale=float(
                    self.micro_motion_cfg.get("breathing_scale", 0.02)
                ),
                breathing_period=float(
                    self.micro_motion_cfg.get("breathing_period", 4.0)
                ),
                shake_amplitude=float(
                    self.micro_motion_cfg.get("shake_amplitude", 0.3)
                ),
                shake_period=float(
                    self.micro_motion_cfg.get("shake_period", 2.0)
                ),
                blink_enabled=bool(
                    self.micro_motion_cfg.get("blink_enabled", True)
                ),
                blink_interval=float(
                    self.micro_motion_cfg.get("blink_interval", 4.0)
                ),
            )
            self.logger.info(f"微动作层应用完成: {result_path.name}")
            return result_path
        except Exception as e:
            self.logger.warning(
                f"微动作层应用失败，降级使用原视频: {e}"
            )
            return video_path

    def _get_avatar_image(self, avatar_id: str) -> Path:
        """获取数字人头像图片

        优先使用已注册的参考图，否则生成占位图。
        """
        # 查找已注册形象
        avatar_dir = self.avatars_dir / avatar_id
        if avatar_dir.exists():
            for name in ("reference.jpg", "reference.png", "avatar.jpg"):
                p = avatar_dir / name
                if p.exists():
                    return p

        # 生成占位图
        placeholder = self.avatars_dir / avatar_id / "placeholder.jpg"
        placeholder.parent.mkdir(parents=True, exist_ok=True)
        self._generate_placeholder_image(placeholder, avatar_id)
        return placeholder

    def _generate_placeholder_image(
        self, output: Path, avatar_id: str
    ) -> None:
        """生成占位头像图（纯色背景 + 文字标识）"""
        w, h = self.output_resolution
        # 浅灰背景
        img = Image.new("RGB", (w, h), color=(60, 70, 90))
        draw = ImageDraw.Draw(img)

        # 尝试加载字体，失败用默认
        font_path = self.config.get("cover.font_path", "")
        try:
            font_large = ImageFont.truetype(font_path, 80) if font_path else ImageFont.load_default()
            font_small = ImageFont.truetype(font_path, 40) if font_path else ImageFont.load_default()
        except Exception:
            font_large = ImageFont.load_default()
            font_small = ImageFont.load_default()

        # 中心圆形头像占位
        cx, cy = w // 2, h // 2 - 100
        r = 200
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            fill=(120, 140, 180), outline=(200, 210, 230), width=4,
        )

        # 文字
        title = "数字人口播"
        subtitle = f"Avatar: {avatar_id}"
        for text, font, y_offset in [
            (title, font_large, 80),
            (subtitle, font_small, 180),
        ]:
            try:
                bbox = draw.textbbox((0, 0), text, font=font)
                tw = bbox[2] - bbox[0]
                th = bbox[3] - bbox[1]
            except Exception:
                tw, th = 400, 80
            draw.text(
                ((w - tw) // 2, cy + y_offset),
                text, fill=(255, 255, 255), font=font,
            )

        # 底部标识
        footer = "EnlyAI · Mock Mode"
        try:
            bbox = draw.textbbox((0, 0), footer, font=font_small)
            tw = bbox[2] - bbox[0]
        except Exception:
            tw = 300
        draw.text(((w - tw) // 2, h - 120), footer, fill=(180, 190, 210), font=font_small)

        img.save(str(output), "JPEG", quality=90)

    def register_avatar(
        self, avatar_id: str, reference_video: Path
    ) -> bool:
        """注册数字人形象

        Args:
            avatar_id: 形象 ID
            reference_video: 参考视频或照片（3-10s 正面说话，嘴巴不动）
                - wav2lip 模式：直接保存为参考素材，用于唇形同步
                - mock 模式：从视频抽一帧作为占位图
                - 云端模式：上传到云端服务
        """
        avatar_dir = self.avatars_dir / avatar_id
        avatar_dir.mkdir(parents=True, exist_ok=True)
        reference_video = Path(reference_video)

        if self.provider == "wav2lip":
            # Wav2Lip 模式：直接保存参考素材（照片或视频）
            try:
                ext = reference_video.suffix.lower()
                # 清理旧参考素材
                for old in avatar_dir.glob("reference*"):
                    old.unlink(missing_ok=True)
                # 根据类型保存
                if ext in (".jpg", ".jpeg", ".png", ".webp"):
                    ref_path = avatar_dir / "reference.jpg"
                    if ext != ".jpg":
                        # 转换为 jpg
                        from PIL import Image as _Image
                        img = _Image.open(reference_video).convert("RGB")
                        img.save(str(ref_path), "JPEG", quality=95)
                    else:
                        shutil.copy2(reference_video, ref_path)
                    kind = "photo"
                elif ext in (".mp4", ".mov", ".avi", ".mkv", ".webm"):
                    ref_path = avatar_dir / "reference_video.mp4"
                    shutil.copy2(reference_video, ref_path)
                    kind = "video"
                else:
                    raise RuntimeError(f"不支持的参考素材格式: {ext}")

                # 生成预览图（视频抽一帧，照片直接缩略）
                preview = avatar_dir / "reference.jpg" if kind == "photo" else avatar_dir / "preview.jpg"
                if kind == "video":
                    subprocess.run(
                        [
                            self.ffmpeg.ffmpeg, "-y",
                            "-i", str(ref_path),
                            "-frames:v", "1",
                            "-q:v", "2",
                            str(preview),
                        ],
                        capture_output=True, check=True,
                    )

                # 保存元数据
                import json
                (avatar_dir / "meta.json").write_text(
                    json.dumps({
                        "avatar_id": avatar_id,
                        "source": str(reference_video),
                        "mode": "wav2lip",
                        "reference_type": kind,
                        "reference_path": str(ref_path),
                        "has_lip_sync": True,
                    }, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                self.logger.info(
                    f"Wav2Lip 形象注册成功: {avatar_id} -> {ref_path.name} ({kind})"
                )
                return True
            except Exception as e:
                self.logger.error(f"Wav2Lip 形象注册失败: {e}")
                return False
        elif self.provider == "mock":
            # Mock 模式：从视频抽一帧作为参考图
            try:
                ref_img = avatar_dir / "reference.jpg"
                subprocess.run(
                    [
                        self.ffmpeg.ffmpeg, "-y",
                        "-i", str(reference_video),
                        "-frames:v", "1",
                        "-q:v", "2",
                        str(ref_img),
                    ],
                    capture_output=True, check=True,
                )
                self.logger.info(f"Mock 形象注册成功: {avatar_id} -> {ref_img}")
                # 保存元数据
                import json
                (avatar_dir / "meta.json").write_text(
                    json.dumps({
                        "avatar_id": avatar_id,
                        "source": str(reference_video),
                        "mode": "mock",
                    }, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                return True
            except Exception as e:
                self.logger.error(f"形象注册失败: {e}")
                return False
        else:
            # 云端模式：上传参考视频
            try:
                video_b64 = base64.b64encode(Path(reference_video).read_bytes()).decode()
                resp = self.gpu.call_avatar_register({
                    "avatar_id": avatar_id,
                    "reference_video_base64": video_b64,
                })
                return resp.get("success", False)
            except Exception as e:
                self.logger.error(f"云端形象注册失败: {e}")
                return False
