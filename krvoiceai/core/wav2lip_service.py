"""Wav2Lip 服务客户端 + 进程管理

将 Wav2Lip 推理从"每次启动子进程"改为"调用常驻 HTTP 服务"，节省每次 ~30-50s
的子进程启动 + 模型加载固定开销（冷启动场景下可节省 ~8 分钟）。

核心职责：
1. 进程管理：启动/停止 wav2lip_server.py 子进程（用 wav2lip_env 解释器）
2. 健康检查：轮询 /health 确认服务就绪
3. 推理调用：POST /generate 触发唇形同步推理
4. 崩溃恢复：检测服务崩溃后自动重启

使用方式：
    from .wav2lip_service import Wav2LipService
    service = Wav2LipService.get_instance()
    service.ensure_running()  # 确保服务运行
    result = service.generate(face, audio, outfile, pads=[10,40,10,10])
"""
from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

import httpx

from .config import PROJECT_ROOT, get_config
from .logger import get_logger


class Wav2LipService:
    """Wav2Lip 服务客户端（单例）

    线程安全说明：
    - ensure_running() 用锁保护，避免并发启动
    - generate() 不加锁（服务端已用 threading.Lock 串行化推理）
    - 进程句柄用锁保护
    """

    _instance: Optional["Wav2LipService"] = None
    _instance_lock = threading.Lock()

    def __init__(self):
        self.config = get_config()
        self.logger = get_logger().bind(component="wav2lip_service")

        # Wav2Lip 配置（与 avatar_engine.py 读取方式一致）
        wav2lip_cfg = self.config.get("avatar.wav2lip", {}) or {}
        self.env_python = self._abs_path(wav2lip_cfg.get(
            "env_python", "../wav2lip_env/Scripts/python.exe"
        ))
        self.checkpoint_path = self._abs_path(wav2lip_cfg.get(
            "checkpoint_path", "../Wav2Lip/checkpoints/wav2lip_gan.pth"
        ))
        self.inference_script = self._abs_path(wav2lip_cfg.get(
            "inference_script", "../Wav2Lip/inference.py"
        ))
        self.face_det_batch = int(wav2lip_cfg.get("face_det_batch_size", 2))
        self.wav2lip_batch = int(wav2lip_cfg.get("wav2lip_batch_size", 2))
        self.device = wav2lip_cfg.get("device", "auto")

        # wav2lip_server.py 路径（与 inference.py 同目录）
        self.server_script = self.inference_script.parent / "wav2lip_server.py"

        # 服务配置
        self.port = int(self.config.get("wav2lip_service.port", 8011))
        self.host = self.config.get("wav2lip_service.host", "127.0.0.1")
        self.startup_timeout = int(self.config.get(
            "wav2lip_service.startup_timeout", 120
        ))  # 等待服务就绪的最长时间（秒）
        self.generate_timeout = int(self.config.get(
            "wav2lip_service.generate_timeout", 1800
        ))  # 单次推理超时（秒），默认 30 分钟

        self.base_url = f"http://{self.host}:{self.port}"

        # 进程管理
        self._process: Optional[subprocess.Popen] = None
        self._process_lock = threading.Lock()
        self._started_by_us = False  # 是否由本客户端启动（决定是否由本客户端关闭）

        self.logger.info(
            f"Wav2LipService 初始化: port={self.port} "
            f"env={self.env_python.parent.parent.name} "
            f"checkpoint={self.checkpoint_path.name} "
            f"server_script={self.server_script.name}"
        )

    @classmethod
    def get_instance(cls) -> "Wav2LipService":
        """获取单例实例"""
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def _abs_path(self, p: str) -> Path:
        """将相对路径解析为绝对路径（基于 PROJECT_ROOT）"""
        path = Path(p)
        return path if path.is_absolute() else (Path(PROJECT_ROOT) / p).resolve()

    # ========================================================================
    # 健康检查
    # ========================================================================

    def is_healthy(self) -> bool:
        """检查服务是否健康（已启动且模型加载完成）"""
        try:
            r = httpx.get(f"{self.base_url}/health", timeout=5)
            if r.status_code != 200:
                return False
            data = r.json()
            return data.get("ready", False) is True
        except Exception as e:
            self.logger.debug(f"健康检查失败: {e}")
            return False

    def get_status(self) -> dict:
        """获取服务详细状态"""
        try:
            r = httpx.get(f"{self.base_url}/health", timeout=5)
            if r.status_code == 200:
                return r.json()
        except Exception:
            pass
        return {"ready": False, "error": "service unreachable"}

    # ========================================================================
    # 进程管理
    # ========================================================================

    def start(self) -> bool:
        """启动 wav2lip_server 子进程

        Returns:
            True 表示服务已就绪，False 表示启动失败或超时
        """
        with self._process_lock:
            # 如果进程已在运行且健康，直接返回
            if self._process is not None and self._process.poll() is None:
                if self.is_healthy():
                    self.logger.info("wav2lip_server 已在运行且就绪")
                    return True
                # 进程在但未就绪，等待加载
                self.logger.info("wav2lip_server 进程在运行，等待模型加载...")
                return self._wait_ready(self.startup_timeout)

            # 检查脚本存在
            if not self.server_script.exists():
                self.logger.error(f"wav2lip_server.py 不存在: {self.server_script}")
                return False

            # 检查 env_python 存在
            if not self.env_python.exists():
                self.logger.error(f"wav2lip_env python 不存在: {self.env_python}")
                return False

            # 检查 checkpoint 存在
            if not self.checkpoint_path.exists():
                self.logger.error(f"checkpoint 不存在: {self.checkpoint_path}")
                return False

            # 启动子进程
            cmd = [
                str(self.env_python),
                str(self.server_script),
                "--port", str(self.port),
                "--host", self.host,
                "--checkpoint_path", str(self.checkpoint_path),
                "--device", self.device,
                "--face_det_batch_size", str(self.face_det_batch),
                "--wav2lip_batch_size", str(self.wav2lip_batch),
            ]

            self.logger.info(f"启动 wav2lip_server: {cmd}")

            # 工作目录必须是 Wav2Lip 根目录（与 inference.py 一致）
            wav2lip_root = self.server_script.parent

            # 创建日志文件（避免子进程 stdout 阻塞）
            log_dir = Path(PROJECT_ROOT) / "workspace_data" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "wav2lip_server.log"

            self._log_file = open(log_file, "a", encoding="utf-8")

            try:
                self._process = subprocess.Popen(
                    cmd,
                    cwd=str(wav2lip_root),
                    stdout=self._log_file,
                    stderr=subprocess.STDOUT,
                    # Windows 下用 CREATE_NO_WINDOW 避免弹出控制台窗口
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                self._started_by_us = True
                self.logger.info(
                    f"wav2lip_server 已启动 PID={self._process.pid} "
                    f"log={log_file}"
                )
            except Exception as e:
                self.logger.error(f"启动 wav2lip_server 失败: {e}")
                self._log_file.close()
                return False

            # 等待服务就绪
            return self._wait_ready(self.startup_timeout)

    def _wait_ready(self, timeout: int) -> bool:
        """轮询 /health 直到 ready=true 或超时"""
        self.logger.info(f"等待 wav2lip_server 就绪（超时 {timeout}s）...")
        start = time.time()
        while time.time() - start < timeout:
            # 检查进程是否意外退出
            if self._process is not None and self._process.poll() is not None:
                exit_code = self._process.returncode
                self.logger.error(
                    f"wav2lip_server 进程意外退出 exit_code={exit_code}"
                )
                self._process = None
                return False

            try:
                r = httpx.get(f"{self.base_url}/health", timeout=3)
                if r.status_code == 200:
                    data = r.json()
                    if data.get("ready"):
                        elapsed = time.time() - start
                        self.logger.info(
                            f"wav2lip_server 就绪 (device={data.get('device')}, "
                            f"face_batch={data.get('face_det_batch')}, "
                            f"wav2lip_batch={data.get('wav2lip_batch')}, "
                            f"耗时 {elapsed:.1f}s)"
                        )
                        return True
                    # 服务已启动但模型还在加载
                    progress = data.get("progress", "")
                    if int(elapsed := time.time() - start) % 10 == 0:
                        self.logger.info(
                            f"模型加载中... progress={progress} "
                            f"elapsed={elapsed:.0f}s"
                        )
            except Exception:
                pass  # 服务还没启动，继续等

            time.sleep(2)

        self.logger.error(f"等待 wav2lip_server 就绪超时（{timeout}s）")
        return False

    def ensure_running(self) -> bool:
        """确保服务运行（不健康则启动）

        Returns:
            True 表示服务已就绪
        """
        # 先检查是否已健康（可能是外部启动的服务）
        if self.is_healthy():
            return True

        # 不健康，尝试启动
        return self.start()

    def stop(self) -> None:
        """停止 wav2lip_server 子进程"""
        with self._process_lock:
            if not self._started_by_us:
                # 不是本客户端启动的，不负责关闭
                self.logger.debug("服务非本客户端启动，跳过关闭")
                return

            if self._process is None:
                return

            # 尝试优雅关闭
            try:
                httpx.post(f"{self.base_url}/shutdown", timeout=5)
                self.logger.info("已发送 /shutdown 请求")
            except Exception as e:
                self.logger.warning(f"发送 /shutdown 失败: {e}")

            # 等待进程退出（最多 10 秒）
            try:
                self._process.wait(timeout=10)
                self.logger.info(f"wav2lip_server 已退出 code={self._process.returncode}")
            except subprocess.TimeoutExpired:
                self.logger.warning("wav2lip_server 未在 10s 内退出，强制终止")
                self._process.kill()
                try:
                    self._process.wait(timeout=5)
                except Exception:
                    pass

            self._process = None
            if hasattr(self, "_log_file"):
                try:
                    self._log_file.close()
                except Exception:
                    pass

    # ========================================================================
    # 推理调用
    # ========================================================================

    def generate(
        self,
        face_path: str | Path,
        audio_path: str | Path,
        outfile_path: str | Path,
        pads: list[int] | None = None,
        resize_factor: int = 1,
        nosmooth: bool = False,
        fps: float = 25.0,
    ) -> dict:
        """调用 wav2lip_server 生成唇形同步视频

        Args:
            face_path: 参考人脸视频/图片路径
            audio_path: 音频文件路径（wav 优先）
            outfile_path: 输出视频路径
            pads: 人脸 padding [top, bottom, left, right]
            resize_factor: 缩放因子（1=最高质量）
            nosmooth: 是否禁用人脸框平滑
            fps: 静态图片的默认 fps

        Returns:
            服务返回的字典，包含 success/outfile/duration/frames 等

        Raises:
            RuntimeError: 服务不可用或推理失败
        """
        if pads is None:
            pads = [0, 10, 0, 0]

        # 确保服务运行
        if not self.ensure_running():
            raise RuntimeError(
                "wav2lip_server 不可用且无法启动，请检查配置和日志: "
                f"workspace_data/logs/wav2lip_server.log"
            )

        # 转为绝对路径字符串
        face_abs = str(Path(face_path).resolve())
        audio_abs = str(Path(audio_path).resolve())
        outfile_abs = str(Path(outfile_path).resolve())

        payload = {
            "face_path": face_abs,
            "audio_path": audio_abs,
            "outfile_path": outfile_abs,
            "pads": list(pads),
            "resize_factor": int(resize_factor),
            "nosmooth": bool(nosmooth),
            "fps": float(fps),
        }

        self.logger.info(
            f"调用 /generate: face={Path(face_abs).name} "
            f"audio={Path(audio_abs).name} -> {Path(outfile_abs).name}"
        )

        start = time.time()
        try:
            r = httpx.post(
                f"{self.base_url}/generate",
                json=payload,
                timeout=self.generate_timeout,
            )
            r.raise_for_status()
            result = r.json()
            elapsed = time.time() - start
            self.logger.info(
                f"/generate 完成: duration={result.get('duration', 0):.1f}s "
                f"frames={result.get('frames', 0)} "
                f"elapsed={elapsed:.1f}s"
            )
            return result
        except httpx.HTTPStatusError as e:
            # 服务返回错误状态码
            status_code = e.response.status_code
            detail = ""
            try:
                detail = e.response.json().get("detail", "")
            except Exception:
                detail = e.response.text[:200]
            self.logger.error(f"/generate HTTP {status_code}: {detail}")

            # 如果是 503（服务未就绪或繁忙），可能是崩溃了，尝试重启
            if status_code == 503:
                self.logger.warning("服务返回 503，可能已崩溃，尝试重启...")
                self._restart()
                raise RuntimeError(f"服务繁忙或崩溃: {detail}")
            raise RuntimeError(f"推理失败 (HTTP {status_code}): {detail}")
        except httpx.RequestError as e:
            # 网络错误，服务可能崩溃
            self.logger.error(f"/generate 网络错误: {e}")
            self.logger.warning("服务可能已崩溃，尝试重启...")
            self._restart()
            raise RuntimeError(f"服务网络错误: {e}")

    def _restart(self) -> None:
        """重启服务（崩溃恢复）"""
        with self._process_lock:
            # 强制终止旧进程
            if self._process is not None and self._process.poll() is None:
                self.logger.warning("强制终止旧 wav2lip_server 进程")
                self._process.kill()
                try:
                    self._process.wait(timeout=5)
                except Exception:
                    pass
            self._process = None

        # 重新启动
        self.start()

    # ========================================================================
    # 上下文管理（支持 with 语句）
    # ========================================================================

    def __enter__(self):
        self.ensure_running()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()
        return False
