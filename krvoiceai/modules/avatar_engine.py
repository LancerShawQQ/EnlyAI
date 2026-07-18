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
        # LongCat 配置（云端高质量引擎，需 8GB+ 显存 GPU 服务器）
        self.longcat_cfg = self.config.get("avatar.longcat", {}) or {}
        self.longcat_server_url = self.longcat_cfg.get("server_url", "")
        self.longcat_api_key = self.longcat_cfg.get("api_key", "")
        self.longcat_model_type = self.longcat_cfg.get("model_type", "avatar-v1.5")
        self.longcat_resolution = self.longcat_cfg.get("resolution", "480p")
        self.longcat_timeout = self.longcat_cfg.get("timeout", 600)
        # MuseTalk 配置（本地高质量引擎，视频驱动模式，解决头部移动唇形精度问题）
        # 优势：256×256 逐帧人脸对齐，单步潜空间 inpainting，比 Wav2Lip 唇形更精准
        # 要求：需 NVIDIA GPU（官方最低 4GB fp16），独立 Python 3.10 conda 环境
        self.musetalk_cfg = self.config.get("avatar.musetalk", {}) or {}
        self.musetalk_server_url = self.musetalk_cfg.get("server_url", "")
        self.musetalk_api_key = self.musetalk_cfg.get("api_key", "")
        self.musetalk_version = self.musetalk_cfg.get("version", "v15")
        self.musetalk_use_float16 = self.musetalk_cfg.get("use_float16", True)
        self.musetalk_fps = self.musetalk_cfg.get("fps", 25)
        self.musetalk_bbox_shift = self.musetalk_cfg.get("bbox_shift", 5)
        self.musetalk_timeout = self.musetalk_cfg.get("timeout", 600)
        # 环境检测缓存（进程内只检测一次，避免每次 run() 重复等待 torch import）
        self._env_check_result: tuple[bool, str] | None = None

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
        elif self.provider == "longcat":
            if not self.longcat_server_url:
                self.logger.warning(
                    "LongCat 引擎未配置 server_url，请在设置中心配置云端服务器地址"
                )
            else:
                self.logger.info(
                    f"数字人模块初始化 provider=longcat "
                    f"server={self.longcat_server_url} "
                    f"model={self.longcat_model_type} res={self.longcat_resolution}"
                )
        elif self.provider == "musetalk":
            if not self.musetalk_server_url:
                self.logger.warning(
                    "MuseTalk 引擎未配置 server_url，请在设置中心配置 MuseTalk 服务地址"
                )
            else:
                self.logger.info(
                    f"数字人模块初始化 provider=musetalk "
                    f"server={self.musetalk_server_url} "
                    f"version={self.musetalk_version} fp16={self.musetalk_use_float16}"
                )
        else:
            self.logger.info(f"数字人模块初始化 provider={self.provider}")
        super().setup()

    def _check_wav2lip_env(self) -> tuple[bool, str]:
        """检查 Wav2Lip 独立运行环境是否就绪

        不再静默降级。返回 (ready, reason)。
        ready=True 表示可真实推理；ready=False 时 reason 给出具体缺失项和指引。

        结果缓存在实例变量中，进程内只检测一次（torch import 约30s，
        避免每次 run() 重复检测导致在高负载时超时）。
        """
        if self._env_check_result is not None:
            return self._env_check_result

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
        # timeout=180s：torch import 正常约30s，高负载时可达120s+，给足余量
        try:
            result = subprocess.run(
                [str(env_python), "-c",
                 "import torch, librosa, cv2, numpy, scipy; "
                 "print('deps ok', torch.__version__)"],
                capture_output=True, text=True, timeout=180,
            )
            if result.returncode != 0:
                self._env_check_result = (False, (
                    f"wav2lip_env 依赖缺失: {result.stderr[-200:]}。"
                    f"请在该环境执行 pip install torch librosa opencv-python scipy。"
                ))
                return self._env_check_result
        except Exception as e:
            self._env_check_result = (False, f"检测 wav2lip_env 依赖异常: {e}")
            return self._env_check_result

        self._env_check_result = (True, "ok")
        return self._env_check_result

    def _check_wav2lip_deps(self) -> bool:
        """[已废弃] 检查主环境依赖 —— 改用 _check_wav2lip_env 检测独立环境

        保留仅为向后兼容。Wav2Lip 现在用独立 Python 3.8 环境，主环境无需这些依赖。
        """
        return False

    def _validate_reference_video_faces(
        self, video_path: Path, env_python: Path | None = None
    ) -> None:
        """参考视频预检查：抽帧检测人脸，提前发现"部分帧无人脸"问题

        Wav2Lip 要求参考视频所有帧都有人脸，否则会在 face_detect 阶段失败。
        如果在推理开始后才发现，用户已等待数十分钟（GPU）或数小时（CPU）。
        本方法在推理前抽帧（每30帧取1帧）快速检测，发现问题立即报错。

        Raises:
            RuntimeError: 当抽检帧中存在无人脸帧时
        """
        import tempfile
        try:
            # 确定 env_python（用于调用 cv2）
            if env_python is None:
                from ..core.config import PROJECT_ROOT
                project_root = Path(PROJECT_ROOT)
                def _abs(p: str) -> Path:
                    path = Path(p)
                    return path if path.is_absolute() else (project_root / p).resolve()
                env_python = _abs(self.wav2lip_env_python)

            with tempfile.TemporaryDirectory() as tmp:
                tmp_path = Path(tmp)
                # 每30帧抽1帧，快速采样
                import subprocess as _sp
                _sp.run(
                    [self.ffmpeg.ffmpeg, "-y", "-i", str(video_path),
                     "-vf", "select='not(mod(n,30))'",
                     "-vsync", "vfr", "-q:v", "2",
                     str(tmp_path / "frame_%04d.jpg")],
                    capture_output=True, timeout=60,
                )
                frames = sorted(tmp_path.glob("frame_*.jpg"))
                if not frames:
                    self.logger.warning("参考视频抽帧失败，跳过预检查")
                    return

                # 用 wav2lip_env 的 cv2 检测人脸
                check_script = (
                    "import cv2, sys, os\n"
                    "cascade = cv2.CascadeClassifier("
                    "cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')\n"
                    "no_face = []\n"
                    "for f in sys.argv[1:]:\n"
                    "    img = cv2.imread(f)\n"
                    "    if img is None: continue\n"
                    "    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)\n"
                    "    faces = cascade.detectMultiScale("
                    "gray, scaleFactor=1.1, minNeighbors=3, minSize=(60, 60))\n"
                    "    if len(faces) == 0:\n"
                    "        no_face.append(os.path.basename(f))\n"
                    "if no_face:\n"
                    "    print('NO_FACE:' + ','.join(no_face))\n"
                    "else:\n"
                    "    print('ALL_OK:' + str(len(sys.argv) - 1))\n"
                )
                r = _sp.run(
                    [str(env_python), "-c", check_script] + [str(f) for f in frames],
                    capture_output=True, text=True, timeout=60,
                )
                if r.returncode == 0 and "NO_FACE:" in r.stdout:
                    no_face_frames = r.stdout.split("NO_FACE:")[1].strip()
                    raise RuntimeError(
                        f"参考视频 {video_path.name} 部分帧无人脸（{no_face_frames}）。"
                        f"Wav2Lip 要求所有帧都有人脸，否则推理会失败。"
                        f"请重新上传全程有人脸的视频，或裁剪掉无人脸的片段。"
                    )
                elif r.returncode == 0 and "ALL_OK" in r.stdout:
                    count = r.stdout.split("ALL_OK:")[1].strip()
                    self.logger.info(f"参考视频预检查通过（{count} 帧采样均有人脸）")
                else:
                    self.logger.warning(
                        f"参考视频预检查异常（跳过）: stdout={r.stdout[:100]}, stderr={r.stderr[:100]}"
                    )
        except RuntimeError:
            raise
        except Exception as e:
            # 预检查失败不阻断流程，仅警告（避免环境影响主流程）
            self.logger.warning(f"参考视频预检查失败（跳过）: {e}")

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
            elif self.provider == "longcat":
                video_path = self._generate_longcat(ctx, avatar_id, output_path)
            elif self.provider == "musetalk":
                video_path = self._generate_musetalk(ctx, avatar_id, output_path)
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

        # 参考视频预检查：抽帧检测人脸，提前发现"部分帧无人脸"问题
        # 避免 Wav2Lip 跑数十分钟后才在 face_detect 阶段失败
        if face_path.suffix.lower() in (".mp4", ".mov", ".avi", ".mkv", ".webm"):
            self._validate_reference_video_faces(face_path, env_python=None)

        # 准备音频（Wav2Lip 需要 wav 格式）
        audio_path = ctx.audio_path
        if audio_path.suffix.lower() != ".wav":
            wav_path = ctx.work_dir / "wav2lip_input.wav"
            self.ffmpeg.convert_audio(audio_path, wav_path)
            audio_path = wav_path

        # 调用 Wav2Lip 服务（常驻进程，模型加载一次复用，节省每次 ~30-50s 固定开销）
        # 设备检测 / batch_size 选择 / 模型加载 由服务端负责，客户端只需传文件路径
        from ..core.wav2lip_service import Wav2LipService

        # 使用绝对路径（服务端通过 HTTP 接收路径，需能访问）
        face_abs = Path(face_path).resolve()
        audio_abs = Path(audio_path).resolve()
        output_abs = Path(output_path).resolve()

        # 质量优先：使用配置的 resize_factor（默认 1=最高质量）
        # 唇形同步是核心卖点，绝不为提速牺牲精度
        auto_resize = int(self.wav2lip_config.get("resize_factor", 1))
        audio_dur = ctx.audio_duration or 0
        pads = list(self.wav2lip_config.get("pads", [0, 20, 0, 0]))
        nosmooth = bool(self.wav2lip_config.get("nosmooth", False))

        self.logger.info(
            f"Wav2Lip 推理参数: resize_factor={auto_resize}（质量优先），音频 {audio_dur:.1f}s"
        )

        # 获取服务单例（首次调用会触发服务启动，后续复用）
        service = Wav2LipService.get_instance()

        # 查询服务状态，打印设备/batch 信息（一次）
        status = service.get_status()
        if status.get("ready"):
            self.logger.info(
                f"wav2lip_server 就绪: device={status.get('device')} "
                f"face_batch={status.get('face_det_batch')} "
                f"wav2lip_batch={status.get('wav2lip_batch')}"
            )

        self.logger.info(
            f"调用 Wav2Lip 服务推理: face={face_abs.name} audio={audio_abs.name} "
            f"-> {output_abs.name}，音频 {audio_dur:.1f}s，预计耗时数分钟至数十分钟..."
        )

        try:
            result = service.generate(
                face_path=face_abs,
                audio_path=audio_abs,
                outfile_path=output_abs,
                pads=pads,
                resize_factor=auto_resize,
                nosmooth=nosmooth,
                fps=float(self.output_fps),
            )
        except RuntimeError as e:
            self.logger.error(f"Wav2Lip 服务推理失败: {e}")
            raise RuntimeError(
                f"Wav2Lip 推理失败: {e}。"
                f"建议：1) 检查 workspace_data/logs/wav2lip_server.log "
                f"2) 确认 wav2lip_env 和 checkpoint 配置正确"
            )

        if not output_path.exists():
            raise RuntimeError("Wav2Lip 推理完成但输出文件不存在")

        self.logger.info(
            f"Wav2Lip 唇形同步完成: {output_path.name} "
            f"({output_path.stat().st_size // 1024}KB) "
            f"推理耗时 {result.get('duration', 0):.1f}s"
        )

        # 轻量锐化后处理：Wav2Lip 输出的人脸区域（尤其嘴唇）常有轻微模糊，
        # 用 unsharp 滤镜增强边缘清晰度（GPU 模式下几乎不增加耗时）
        # 不启用 GFPGAN 时用此方案作为快速质量提升
        if not self.gfpgan_cfg.get("enabled", False):
            try:
                sharpened_path = output_path.with_name("avatar_sharpened.mp4")
                import subprocess as _sp
                _sharpen_cmd = [
                    self.ffmpeg.ffmpeg,
                    "-y", "-i", str(output_path),
                    "-vf", "unsharp=5:5:0.8:3:3:0.4",
                    "-c:a", "copy",
                    str(sharpened_path),
                ]
                _r = _sp.run(_sharpen_cmd, capture_output=True, text=True, timeout=120)
                if _r.returncode == 0 and sharpened_path.exists():
                    output_path = sharpened_path
                    self.logger.info(f"唇形锐化完成: {output_path.name}")
                else:
                    self.logger.warning(f"唇形锐化失败（不影响输出）: {_r.stderr[-150:]}")
            except Exception as _e:
                self.logger.warning(f"唇形锐化异常（不影响输出）: {_e}")

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

        # 性能优化：输入视频若已是竖屏，无需 boxblur+overlay 的横转竖处理
        # 情况1: 竖屏且分辨率匹配目标 → 直接复制（0 秒）
        # 情况2: 竖屏但分辨率不匹配 → 轻量 scale 重编码（~3 秒，不用 boxblur+overlay）
        # 情况3: 横屏 → 走 to_portrait（boxblur+overlay，约 10 秒）
        target_w, target_h = self.output_resolution
        in_info = self.ffmpeg.probe_video_info(output_path)
        if in_info and in_info.height > in_info.width:
            # 竖屏输入
            if in_info.width == target_w and in_info.height == target_h:
                # 分辨率完全匹配，直接复制（最快）
                import shutil
                shutil.copy2(output_path, portrait_path)
                self.logger.info(
                    f"输入已是竖屏 {target_w}x{target_h}，跳过 to_portrait（直接复制）"
                )
                return portrait_path
            else:
                # 竖屏但分辨率不匹配，轻量 scale 重编码（不走 boxblur+overlay）
                import subprocess as _sp
                scale_cmd = [
                    self.ffmpeg.ffmpeg, "-y",
                    "-i", str(output_path),
                    "-vf", f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
                           f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black,fps={self.output_fps}",
                    "-map", "0:v", "-map", "0:a?",
                    "-c:v", "libx264", "-preset", "fast",
                    "-crf", "20", "-maxrate", "6M", "-bufsize", "12M",
                    "-pix_fmt", "yuv420p",
                    "-c:a", "aac", "-b:a", "192k",
                    "-movflags", "+faststart",
                    str(portrait_path),
                ]
                _r = _sp.run(scale_cmd, capture_output=True, text=True, timeout=300)
                if _r.returncode == 0 and portrait_path.exists():
                    self.logger.info(
                        f"输入竖屏 {in_info.width}x{in_info.height} → {target_w}x{target_h} "
                        f"轻量 scale（跳过 boxblur+overlay）"
                    )
                    return portrait_path
                else:
                    self.logger.warning(
                        f"竖屏 scale 失败，回退到 to_portrait: {_r.stderr[-150:]}"
                    )
        # 横屏输入，走标准 to_portrait
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

    def _generate_longcat(
        self, ctx: JobContext, avatar_id: str, output_path: Path
    ) -> Path:
        """使用 LongCat-Video-Avatar 生成唇形同步视频（云端高质量引擎）

        通过 HTTP 调用云端 LongCat 服务，生成商用级唇形同步视频。
        优势：Whisper-large-v3 音频编码器 + 全身时序稳定 + DMD 蒸馏加速。
        要求：云端需 8GB+ 显存 GPU。

        输入：音频 + 参考人物图片（可选）
        输出：高质量唇形同步视频
        """
        from .longcat_avatar_engine import LongCatAvatarClient

        if not self.longcat_server_url:
            raise RuntimeError(
                "LongCat 引擎未配置 server_url，请在设置中心配置云端服务器地址"
            )

        self.logger.info(
            f"LongCat 数字人生成 server={self.longcat_server_url} "
            f"avatar={avatar_id} audio={ctx.audio_path}"
        )

        # 查找参考图片（avatar 目录下的 reference.jpg）
        ref_image = None
        avatar_dir = self.avatars_dir / avatar_id
        if avatar_dir.exists():
            for name in ("reference.jpg", "reference.png", "preview.jpg"):
                p = avatar_dir / name
                if p.exists():
                    ref_image = p
                    break

        # 构建 prompt（描述性提示词，越详细效果越好）
        # 根据数字人姿态（scene.pose）动态构造姿态描述词，让 LongCat 生成对应构图
        pose = self.config.get("scene.pose", "half_body")
        pose_desc_map = {
            "standing": "standing full body",
            "sitting": "sitting half body",
            "half_body": "half body, waist up",
            "closeup": "close-up face shot",
        }
        pose_desc = pose_desc_map.get(pose, "half body, waist up")
        prompt = (
            f"A person is speaking naturally with natural expressions, "
            f"looking at camera, wearing casual clothes, "
            f"{pose_desc}, in a clean environment"
        )
        self.logger.info(f"LongCat prompt (pose={pose}): {prompt}")

        client = LongCatAvatarClient(
            server_url=self.longcat_server_url,
            api_key=self.longcat_api_key,
            timeout=self.longcat_timeout,
            model_type=self.longcat_model_type,
            resolution=self.longcat_resolution,
        )

        # 根据音频时长估算段数（每段约 10s）
        num_segments = max(1, int(ctx.audio_duration / 10) + 1)

        video_bytes = client.generate(
            audio_path=ctx.audio_path,
            reference_image=ref_image,
            prompt=prompt,
            num_segments=num_segments,
        )

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(video_bytes)
        self.logger.info(
            f"LongCat 数字人生成完成 video={output_path} size={len(video_bytes)} bytes"
        )
        return output_path

    def _generate_musetalk(
        self, ctx: JobContext, avatar_id: str, output_path: Path
    ) -> Path:
        """使用 MuseTalk 生成唇形同步视频（本地高质量引擎）

        MuseTalk 是"视频驱动"模式，与 Wav2Lip 使用方式一致：
        输入数字人参考视频 + TTS 音频 → 生成唇形同步视频。

        优势（对比 Wav2Lip）：
        - 256×256 标准化人脸区域单步潜空间 inpainting
        - 逐帧重新检测+对齐人脸，解决头部移动时唇形精度下降
        - v1.5 加 GAN+感知+sync loss，唇形质量明显更好

        要求：需 NVIDIA GPU（官方最低 4GB fp16），独立 Python 3.10 conda 环境。
        部署：将 musetalk_server.py 部署到 MuseTalk conda 环境中运行。
        """
        from .musetalk_avatar_engine import MuseTalkAvatarClient

        if not self.musetalk_server_url:
            raise RuntimeError(
                "MuseTalk 引擎未配置 server_url，请在设置中心配置 MuseTalk 服务地址"
            )

        # 获取参考人脸视频（与 Wav2Lip 相同的逻辑）
        face_path = self._get_avatar_reference(avatar_id)
        if not face_path:
            raise RuntimeError(
                f"数字人 {avatar_id} 无参考照片/视频，请先上传真人照片或视频注册形象"
            )

        self.logger.info(
            f"MuseTalk 唇形同步 avatar={avatar_id} audio={ctx.audio_path.name} "
            f"duration={ctx.audio_duration:.1f}s face_ref={face_path.name} "
            f"version={self.musetalk_version} fp16={self.musetalk_use_float16}"
        )

        # 准备音频（MuseTalk 需要 wav 格式）
        audio_path = ctx.audio_path
        if audio_path.suffix.lower() != ".wav":
            wav_path = ctx.work_dir / "musetalk_input.wav"
            self.ffmpeg.convert_audio(audio_path, wav_path)
            audio_path = wav_path

        # MuseTalk 需要视频文件作为输入（视频驱动模式）
        # 如果参考是图片，需先转为视频（MuseTalk 会用图片生成静态视频帧）
        video_path = face_path
        if face_path.suffix.lower() in (".jpg", ".jpeg", ".png"):
            # 图片转视频：用 ffmpeg 生成静态帧视频
            static_video = ctx.work_dir / "musetalk_input_video.mp4"
            if not static_video.exists():
                import subprocess
                duration = ctx.audio_duration or 10
                cmd = [
                    "ffmpeg", "-y", "-loop", "1", "-i", str(face_path),
                    "-c:v", "libx264", "-t", str(duration),
                    "-pix_fmt", "yuv420p", "-r", str(self.musetalk_fps),
                    str(static_video),
                ]
                subprocess.run(cmd, capture_output=True, timeout=60, check=True)
            video_path = static_video

        client = MuseTalkAvatarClient(
            server_url=self.musetalk_server_url,
            api_key=self.musetalk_api_key,
            timeout=self.musetalk_timeout,
            version=self.musetalk_version,
            use_float16=self.musetalk_use_float16,
            fps=self.musetalk_fps,
        )

        video_bytes = client.generate(
            audio_path=audio_path,
            video_path=video_path,
            output_path=output_path,
            bbox_shift=self.musetalk_bbox_shift,
        )

        self.logger.info(
            f"MuseTalk 数字人生成完成 video={output_path} size={len(video_bytes)} bytes"
        )
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
