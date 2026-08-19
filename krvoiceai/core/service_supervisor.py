r"""依赖服务监管器（Service Supervisor）

确保 EnlyAI 的本地依赖服务（Ollama / CosyVoice / LatentSync）随 Web 后端自动拉起。
用户双击 EnlyAI.exe 即可完整使用，无需先手动运行 scripts/start_all.bat。

设计要点：
- 按当前配置的 provider 决定需要哪些服务（mock/云端 provider 不拉本地服务）；
- 服务已在运行（无论由谁启动）直接复用，绝不重复拉起；
- 拉起后由后台守护线程轮询健康检查，状态机：stopped → starting → running / failed；
- 子进程独立存活（Web 重启不杀服务，避免每次重复 50 秒模型加载）；
- 子进程 CREATE_NO_WINDOW 无窗口运行，日志重定向到 workspace_data/logs/<name>_service.log；
- conda 环境自动探测（CONDA_EXE / 常见安装路径），可用 config/services 段覆盖。

配置覆盖（config/default.yaml 的 services 段）：
    services:
      auto_start: true
      conda_base: ""            # 留空自动探测
      cosyvoice:
        python: ""              # 留空用 <conda_base>/envs/CosyVoice/python.exe
        fp16: true
      latentsync:
        python: ""
        project_dir: ""         # 留空自动探测（../LatentSync 或 C:\AI_projects\LatentSync）
"""
from __future__ import annotations

import os
import shutil
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

from .config import PROJECT_ROOT, get_config
from .logger import get_logger

logger = get_logger().bind(component="supervisor")

# 各服务健康检查就绪等待时长（秒）：冷启动与其他任务竞争 CPU/GPU 时加载更慢，留足余量
# （实测：CPU 被分析任务占满时 CosyVoice 加载可超 150s、LatentSync 管线加载可超 90s）
STARTUP_TIMEOUTS = {"ollama": 60, "cosyvoice": 300, "latentsync": 240}
# 失败后允许重试的最短间隔（秒），防止用户反复点击生成造成拉起风暴
RETRY_INTERVAL = 60

_TITLES = {
    "ollama": "Ollama LLM 服务",
    "cosyvoice": "CosyVoice TTS 服务",
    "latentsync": "LatentSync 数字人服务",
}


def _conda_base_candidates() -> list[Path]:
    """枚举本机可能的 conda 安装根目录（按可信度排序）"""
    candidates: list[Path] = []

    # 1. 显式配置
    cfg_base = get_config().get("services.conda_base", "")
    if cfg_base:
        candidates.append(Path(cfg_base))

    # 2. CONDA_EXE 环境变量（通常是 <base>/Scripts/conda.exe）
    conda_exe = os.environ.get("CONDA_EXE", "")
    if conda_exe:
        candidates.append(Path(conda_exe).resolve().parents[1])

    # 3. 常见安装位置
    home = Path.home()
    for name in ("miniconda3", "anaconda3", "miniforge3", "mambaforge"):
        candidates.append(home / name)
        candidates.append(Path("C:/ProgramData") / name)
        candidates.append(Path("C:/") / name)

    seen: set[str] = set()
    unique: list[Path] = []
    for c in candidates:
        key = str(c).lower().rstrip("\\/")
        if key not in seen:
            seen.add(key)
            unique.append(c)
    return unique


def find_conda_env_python(env_name: str) -> Optional[Path]:
    """在常见 conda 安装位置查找指定环境的 python.exe"""
    for base in _conda_base_candidates():
        py = base / "envs" / env_name / "python.exe"
        if py.exists():
            return py
    return None


def _url_port(url: str, default: int) -> int:
    try:
        return urlsplit(url).port or default
    except Exception:
        return default


class _ServiceState:
    """单个服务的运行状态"""

    def __init__(self, name: str):
        self.name = name
        self.state = "stopped"  # stopped / starting / running / failed
        self.error: str = ""
        self.log_path: str = ""
        self.started_by_us = False
        self.pid: Optional[int] = None
        self.last_attempt = 0.0
        self.proc: Optional[subprocess.Popen] = None
        self.log_handle = None

    def snapshot(self, healthy: Optional[bool] = None) -> dict[str, Any]:
        return {
            "name": self.name,
            "state": self.state,
            "healthy": healthy,
            "error": self.error,
            "log_path": self.log_path,
            "started_by_us": self.started_by_us,
            "pid": self.pid,
        }


class ServiceSupervisor:
    """本地依赖服务监管器（单例，见 get_service_supervisor）"""

    def __init__(self):
        self._lock = threading.Lock()
        self._states: dict[str, _ServiceState] = {}

    # ============ 对外接口 ============

    def needed_services(self) -> list[str]:
        """根据当前配置的 provider 推导需要拉起的本地服务"""
        cfg = get_config()
        names: list[str] = []
        if cfg.get("llm.provider", "mock") == "ollama":
            names.append("ollama")
        if cfg.get("tts.provider", "mock") == "cosyvoice":
            names.append("cosyvoice")
        if cfg.get("avatar.provider", "mock") == "latentsync":
            names.append("latentsync")
        return names

    def ensure_all(self) -> dict[str, dict[str, Any]]:
        """确保所有需要的服务就绪（后台守护线程异步等待，本方法立即返回）"""
        return {name: self.ensure(name) for name in self.needed_services()}

    def ensure(self, name: str) -> dict[str, Any]:
        """确保单个服务已启动（幂等，返回含 healthy 的状态快照）。

        - 健康探测通过 → running（无论服务由谁启动，直接复用）；
        - 正在启动 → 立即返回 starting（守护线程负责等待就绪）；
        - 启动失败且在冷却期内 → 返回 failed 快照，不重复拉起。
        """
        st = self._get_state(name)
        spec, spec_err = self._build_spec(name)

        if spec and self._probe(spec[0]):
            with self._lock:
                st.state = "running"
                st.error = ""
            return st.snapshot(healthy=True)

        with self._lock:
            if st.state == "starting":
                return st.snapshot(healthy=False)
            if st.state == "failed" and time.time() - st.last_attempt < RETRY_INTERVAL:
                return st.snapshot(healthy=False)
            st.last_attempt = time.time()
            st.state = "starting"
            st.error = ""

        if spec is None:
            self._mark_failed(st, spec_err or "无法构建启动命令")
            return st.snapshot(healthy=False)

        try:
            self._spawn(name, spec)
        except Exception as e:  # 拉起异常不向上传播（预检/启动流程不能被拖垮）
            self._mark_failed(st, f"拉起进程异常: {e}")
        return st.snapshot(healthy=False)

    def wait_ready(self, name: str, timeout: float = 60.0) -> bool:
        """阻塞等待某服务健康就绪（供测试/预检兜底使用）"""
        spec, _ = self._build_spec(name)
        if spec is None:
            return False
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._probe(spec[0]):
                with self._lock:
                    self._get_state(name).state = "running"
                return True
            time.sleep(2)
        return False

    def status(self) -> dict[str, Any]:
        """全部受管服务的状态快照（含实时健康探测，三服务并行）"""
        from concurrent.futures import ThreadPoolExecutor

        snap: dict[str, Any] = {}
        probes: list[tuple[str, Optional[tuple]]] = []
        for name in ("ollama", "cosyvoice", "latentsync"):
            st = self._get_state(name)
            spec, _ = self._build_spec(name)
            probes.append((name, spec))
            snap[name] = st.snapshot()

        def _probe(spec):
            if spec is None:
                return False
            return self._probe(spec[0])

        # 并行探测（串行时单个 3s 超时会拖满 9s+）
        with ThreadPoolExecutor(max_workers=3) as ex:
            for name, healthy in zip((p[0] for p in probes), ex.map(_probe, (p[1] for p in probes))):
                s = snap[name]
                s["healthy"] = healthy
                if healthy:
                    # 注意：锁内不可调用 _get_state()（其内部再取同一把非重入锁会死锁，
                    # 曾导致一次 /api/services 请求永久阻塞整个事件循环）
                    with self._lock:
                        st = self._states.get(name)
                        if st is not None:
                            st.state = "running"
                            st.error = ""
                    s["state"] = "running"
        return {"auto_start": self._auto_start_enabled(), "services": snap}

    def preflight_message(self, name: str, manual_hint: str) -> str:
        """生成预检失败文案：区分"自动启动中 / 自动启动失败 / 未能安装"三种情况"""
        st = self._get_state(name)
        title = _TITLES.get(name, name)
        if st.state == "starting":
            load_hint = "（模型加载约 1 分钟）" if name == "cosyvoice" else ""
            return (
                f"{title} 正在自动启动{load_hint}，请稍后 30-60 秒重试。"
                f"日志：{st.log_path}"
            )
        if st.state == "failed":
            err = f"自动启动失败（{st.error}）。" if st.error else "自动启动失败。"
            log = f"日志：{st.log_path}。" if st.log_path else ""
            return f"{title} {err}{log}可{manual_hint}"
        spec, spec_err = self._build_spec(name)
        if spec is None:
            return f"{title} {spec_err}。可{manual_hint}"
        return f"{title} 未运行。可{manual_hint}"

    def shutdown_owned(self) -> dict[str, int]:
        """终止所有由本进程拉起的服务（用户主动退出应用时调用）

        只清理 started_by_us 的进程（Ollama 若是系统服务/手动启动则不受影响）。
        服务进程独立于 Web 存活（CREATE_NO_WINDOW 分离控制台），
        因此 Web 退出时必须显式终止，否则显存/端口资源不释放。
        """
        with self._lock:
            targets = [
                (name, st) for name, st in self._states.items()
                if st.started_by_us and st.proc is not None
            ]
        stopped: dict[str, int] = {}
        for name, st in targets:
            if st.proc.poll() is not None:
                continue
            try:
                st.proc.terminate()  # Windows 上即 TerminateProcess，GPU 显存随进程释放
                stopped[name] = st.pid or 0
                logger.info(f"[supervisor] 已停止 {name}（pid={st.pid}）")
            except Exception as e:
                logger.warning(f"[supervisor] 停止 {name} 失败: {e}")
        # 等待退出，超时强杀
        for name, st in targets:
            try:
                st.proc.wait(timeout=10)
            except Exception:
                try:
                    st.proc.kill()
                except Exception:
                    pass
            with self._lock:
                st.state = "stopped"
                st.started_by_us = False
                st.proc = None
                st.pid = None
                if st.log_handle:
                    try:
                        st.log_handle.close()
                    except Exception:
                        pass
                    st.log_handle = None
        return stopped

    # ============ 内部实现 ============

    def _auto_start_enabled(self) -> bool:
        return bool(get_config().get("services.auto_start", True))

    def _get_state(self, name: str) -> _ServiceState:
        with self._lock:
            if name not in self._states:
                self._states[name] = _ServiceState(name)
            return self._states[name]

    def _probe(self, url: str, timeout: float = 3.0) -> bool:
        try:
            import httpx

            r = httpx.get(url, timeout=timeout)
            return r.status_code < 500
        except Exception:
            return False

    def _mark_failed(self, st: _ServiceState, error: str):
        with self._lock:
            st.state = "failed"
            st.error = error
        logger.warning(f"[supervisor] {st.name} 启动失败: {error}")

    def _build_spec(self, name: str) -> tuple[Optional[tuple], str]:
        """构建服务启动描述 (health_url, argv, cwd, env, log_path)。

        返回 (spec, error)：不可构建时 spec 为 None、error 说明原因。
        """
        cfg = get_config()
        if name == "ollama":
            return self._build_ollama_spec()
        if name == "cosyvoice":
            return self._build_cosyvoice_spec(cfg)
        if name == "latentsync":
            return self._build_latentsync_spec(cfg)
        return None, f"未知服务 {name}"

    def _log_dir(self) -> Path:
        work_root = Path(get_config().get("project.work_root") or "workspace_data")
        if not work_root.is_absolute():
            work_root = PROJECT_ROOT / work_root
        d = work_root / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _build_ollama_spec(self) -> tuple[Optional[tuple], str]:
        exe = shutil.which("ollama") or shutil.which("ollama.exe")
        if not exe:
            return None, "未找到 ollama（未安装或不在 PATH，请从 https://ollama.com 安装）"
        env = os.environ.copy()
        # 8GB 显存三方分时复用：LLM 调用后立即卸载模型，把显存让给 TTS/数字人
        env.setdefault("OLLAMA_KEEP_ALIVE", "0")
        return (
            "http://localhost:11434/api/tags",
            [exe, "serve"],
            None,
            env,
            str(self._log_dir() / "ollama_service.log"),
        ), ""

    def _build_cosyvoice_spec(self, cfg) -> tuple[Optional[tuple], str]:
        python = cfg.get("services.cosyvoice.python", "") or find_conda_env_python("CosyVoice")
        if not python:
            return None, (
                "未找到 CosyVoice conda 环境"
                "（可用 services.cosyvoice.python 指定 python.exe 路径）"
            )

        port = _url_port(cfg.get("tts.cosyvoice.server_url", "http://localhost:8012"), 8012)

        # 首选 CosyVoice 仓库内的脚本拷贝（start_all.bat 验证过的路径）；
        # 退而求其次用 krvoiceai/modules 版本，需 PYTHONPATH 补全仓库根 + Matcha-TTS
        repo_dir = PROJECT_ROOT / "CosyVoice"
        script = repo_dir / "cosyvoice_server.py"
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"
        if not script.exists():
            script = PROJECT_ROOT / "krvoiceai" / "modules" / "cosyvoice_server.py"
            if not script.exists():
                return None, f"未找到 cosyvoice_server.py（{script}）"
            matcha = repo_dir / "third_party" / "Matcha-TTS"
            env["PYTHONPATH"] = os.pathsep.join(
                [str(repo_dir)] + ([str(matcha)] if matcha.exists() else [])
            )

        argv = [str(python), str(script), "--port", str(port), "--host", "127.0.0.1"]
        if cfg.get("services.cosyvoice.fp16", True):
            argv.append("--fp16")
        # 显式传模型目录：对 krvoiceai/modules 版本是必需的（其默认路径基于脚本位置）
        model_dir = (
            repo_dir / "pretrained_models" / "models"
            / "FunAudioLLM--Fun-CosyVoice3-0.5B-2512" / "snapshots" / "master"
        )
        if model_dir.exists():
            argv += ["--model_dir", str(model_dir)]

        return (
            f"http://localhost:{port}/api/health",
            argv,
            str(repo_dir) if repo_dir.exists() else str(PROJECT_ROOT),
            env,
            str(self._log_dir() / "cosyvoice_service.log"),
        ), ""

    def _build_latentsync_spec(self, cfg) -> tuple[Optional[tuple], str]:
        python = cfg.get("services.latentsync.python", "") or find_conda_env_python("LatentSync")
        if not python:
            return None, (
                "未找到 LatentSync conda 环境"
                "（可用 services.latentsync.python 指定 python.exe 路径）"
            )

        # 项目目录探测：配置 → 兄弟目录 → 常见绝对路径
        project_dir: Optional[Path] = None
        for cand in (
            cfg.get("services.latentsync.project_dir", ""),
            str(PROJECT_ROOT.parent / "LatentSync"),
            "C:/AI_projects/LatentSync",
        ):
            if cand and (Path(cand) / "latentsync_server.py").exists():
                project_dir = Path(cand)
                break
        if project_dir is None:
            return None, (
                "未找到 LatentSync 项目目录（含 latentsync_server.py，"
                "可用 services.latentsync.project_dir 指定）"
            )

        port = _url_port(cfg.get("avatar.latentsync.server_url", "http://localhost:8011"), 8011)
        resolution = cfg.get("avatar.latentsync.resolution", 256)
        steps = cfg.get("avatar.latentsync.inference_steps", 12)

        script = project_dir / "latentsync_server.py"
        if not script.exists():
            # 项目目录里没有服务脚本时，用 krvoiceai/modules 版本（其 sys.path 取自 CWD）
            script = PROJECT_ROOT / "krvoiceai" / "modules" / "latentsync_server.py"
            if not script.exists():
                return None, f"未找到 latentsync_server.py（{script}）"

        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUNBUFFERED"] = "1"

        argv = [
            str(python), str(script),
            "--port", str(port), "--host", "127.0.0.1",
            "--resolution", str(resolution),
            "--inference_steps", str(steps),
        ]
        return (
            f"http://localhost:{port}/api/health",
            argv,
            str(project_dir),
            env,
            str(self._log_dir() / "latentsync_service.log"),
        ), ""

    def _spawn(self, name: str, spec: tuple):
        health_url, argv, cwd, env, log_path = spec
        st = self._get_state(name)

        log_f = open(log_path, "ab")
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        proc = subprocess.Popen(
            argv,
            cwd=cwd,
            stdout=log_f,
            stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL,
            env=env,
            creationflags=creationflags,
        )
        with self._lock:
            st.proc = proc
            st.log_handle = log_f
            st.log_path = log_path
            st.pid = proc.pid
            st.started_by_us = True
            st.state = "starting"

        logger.info(
            f"[supervisor] 拉起 {name} pid={proc.pid} "
            f"timeout={STARTUP_TIMEOUTS.get(name, 90)}s 日志={log_path}"
        )

        threading.Thread(
            target=self._watch,
            args=(name, proc, health_url, STARTUP_TIMEOUTS.get(name, 90)),
            daemon=True,
            name=f"supervisor-{name}",
        ).start()

    def _watch(self, name: str, proc: subprocess.Popen, health_url: str, timeout: float):
        """守护线程：轮询健康检查直到就绪/超时"""
        st = self._get_state(name)
        deadline = time.time() + timeout
        exit_code: Optional[int] = None
        while time.time() < deadline:
            if self._probe(health_url):
                with self._lock:
                    st.state = "running"
                    st.error = ""
                logger.info(f"[supervisor] {name} 已就绪（pid={proc.pid}）")
                return
            rc = proc.poll()
            if rc is not None and exit_code is None:
                exit_code = rc
                # 进程退出不一定意味着失败：可能已有另一实例在加载并即将就绪，
                # 继续轮询健康检查直到超时再下结论
                logger.warning(f"[supervisor] {name} 进程提前退出 code={rc}，继续探测健康状态")
            time.sleep(3)

        if self._probe(health_url):
            with self._lock:
                st.state = "running"
                st.error = ""
            return

        detail = f"进程退出码 {exit_code}" if exit_code is not None else "健康检查超时"
        self._mark_failed(st, f"{detail}（{timeout:.0f}s 内未就绪）")


_supervisor: Optional[ServiceSupervisor] = None
_supervisor_lock = threading.Lock()


def get_service_supervisor() -> ServiceSupervisor:
    """获取进程级单例"""
    global _supervisor
    with _supervisor_lock:
        if _supervisor is None:
            _supervisor = ServiceSupervisor()
        return _supervisor


def start_dependency_services_in_background() -> None:
    """Web 后端启动时调用：后台线程拉起缺失的依赖服务（永不阻塞、永不抛异常）"""
    sup = get_service_supervisor()

    def _run():
        try:
            if not sup._auto_start_enabled():
                logger.info("[supervisor] services.auto_start=false，跳过依赖服务自动拉起")
                return
            for name, snap in sup.ensure_all().items():
                logger.info(
                    f"[supervisor] {name}: state={snap['state']} "
                    f"error={snap.get('error') or '无'}"
                )
        except Exception as e:
            logger.warning(f"[supervisor] 依赖服务自动拉起异常（不影响 Web 启动）: {e}")

    threading.Thread(target=_run, daemon=True, name="supervisor-ensure-all").start()
