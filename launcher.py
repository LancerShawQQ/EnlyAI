"""EnlyAI 启动器

双击运行此 exe：
1. 启动 Web 后端（uvicorn）——后端会自动拉起缺失的依赖服务
   （Ollama / CosyVoice TTS / LatentSync 数字人，见 krvoiceai/core/service_supervisor.py）
2. 等待服务就绪后自动打开浏览器
3. 退出机制：关闭此窗口（或 Web 界面的"退出"按钮）即停止全部进程——
   Job Object（KILL_ON_JOB_CLOSE）由内核保证 Web 及其拉起的所有服务
   一并终止，无显存/端口残留；手动另开的服务窗口不受影响
"""
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser
import socket
from pathlib import Path

# Job Object 句柄（模块级引用，进程存活期间保持打开；
# 句柄关闭时内核自动终止 Job 内所有进程——见 _setup_kill_on_close_job）
_job_handle = None
# 若当前进程已在其他 Job 中（无法直接加入），改为在启动子进程后把子进程加入
_job_assign_child = False


def _setup_kill_on_close_job():
    """创建 KILL_ON_JOB_CLOSE 的 Job Object

    退出兜底：launcher 无论以何种方式结束（用户关窗 / Ctrl+C / 崩溃 / taskkill），
    Job 句柄被内核关闭 → Job 内所有进程（Web 后端及其拉起的 CosyVoice /
    LatentSync / Ollama）被强制终止，不留显存/端口残留。

    优先把 launcher 自身加入 Job；若 launcher 已属于其他 Job（某些终端/
    后台启动器会预置 Job，AssignProcessToJobObject 会被拒绝），则退化为
    启动后把 Web 子进程加入 Job（覆盖整棵服务进程树，效果等同）。
    """
    global _job_handle, _job_assign_child
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes

        class _IO_COUNTERS(ctypes.Structure):
            _fields_ = [(n, ctypes.c_uint64) for n in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class _BASIC_LIMIT(ctypes.Structure):
            _fields_ = [
                ("PerProcessUserTimeLimit", ctypes.c_int64),
                ("PerJobUserTimeLimit", ctypes.c_int64),
                ("LimitFlags", ctypes.c_uint32),
                ("MinimumWorkingSetSize", ctypes.c_size_t),
                ("MaximumWorkingSetSize", ctypes.c_size_t),
                ("ActiveProcessLimit", ctypes.c_uint32),
                ("Affinity", ctypes.c_size_t),
                ("PriorityClass", ctypes.c_uint32),
                ("SchedulingClass", ctypes.c_uint32)]

        class _EXTENDED_LIMIT(ctypes.Structure):
            _fields_ = [
                ("BasicLimitInformation", _BASIC_LIMIT),
                ("IoInfo", _IO_COUNTERS),
                ("ProcessMemoryLimit", ctypes.c_size_t),
                ("JobMemoryLimit", ctypes.c_size_t),
                ("PeakProcessMemoryUsed", ctypes.c_size_t),
                ("PeakJobMemoryUsed", ctypes.c_size_t)]

        kernel32 = ctypes.windll.kernel32
        job = kernel32.CreateJobObjectW(None, None)
        if not job:
            return
        info = _EXTENDED_LIMIT()
        info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        JobObjectExtendedLimitInformation = 9
        if not kernel32.SetInformationJobObject(
            wintypes.HANDLE(job),
            JobObjectExtendedLimitInformation,
            ctypes.byref(info),
            ctypes.sizeof(info),
        ):
            return
        _job_handle = job  # 保持引用，进程退出前不关闭

        if kernel32.AssignProcessToJobObject(
            wintypes.HANDLE(job), kernel32.GetCurrentProcess()
        ):
            print("[EnlyAI] 退出保护已启用（关闭窗口即停止全部服务）")
        else:
            # launcher 已在其他 Job 中：改为把 Web 子进程加入（_spawn_web 后执行）
            _job_assign_child = True
            print("[EnlyAI] 退出保护将在 Web 启动后启用")
    except Exception as e:
        print(f"[EnlyAI] 退出保护启用失败（不影响使用，但请用界面退出按钮退出）: {e}")


def _assign_child_to_job(proc):
    """把 Web 子进程加入 Job（launcher 自身无法加入时的退化路径）"""
    global _job_assign_child
    if not _job_assign_child or _job_handle is None:
        return
    try:
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        if kernel32.AssignProcessToJobObject(
            wintypes.HANDLE(_job_handle), wintypes.HANDLE(int(proc._handle))
        ):
            print("[EnlyAI] 退出保护已启用（关闭窗口即停止全部服务）")
    except Exception as e:
        print(f"[EnlyAI] 子进程退出保护绑定失败: {e}")


def find_project_root():
    """查找项目根目录（包含 krvoiceai 包的目录）"""
    # exe 所在目录
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent

    # 向上查找直到找到 krvoiceai 目录
    for p in [base] + list(base.parents):
        if (p / "krvoiceai" / "__init__.py").exists():
            return p
    return base


def find_python():
    """查找可运行 Web 后端的 Python（虚拟环境 → conda krvoiceai 环境 → 当前解释器）"""
    root = find_project_root()
    candidates = [
        root / ".venv" / "Scripts" / "python.exe",
        Path.home() / "miniconda3" / "envs" / "krvoiceai" / "python.exe",
        Path.home() / "anaconda3" / "envs" / "krvoiceai" / "python.exe",
        Path("C:/ProgramData/miniconda3/envs/krvoiceai/python.exe"),
        Path("C:/ProgramData/anaconda3/envs/krvoiceai/python.exe"),
    ]
    for py in candidates:
        if py.exists():
            return str(py)
    # 回退到当前解释器（打包 exe 场景下 sys.executable 是 exe 本身，不能用来跑 uvicorn）
    if not getattr(sys, "frozen", False):
        return sys.executable
    return None


def is_port_in_use(port):
    """检查端口是否被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def is_enlyai_web(port, timeout=8):
    """判断端口上运行的是否是 EnlyAI Web 服务（而非其他程序抢占了端口）。

    超时给足：/api/health 会同步探测依赖服务，冷启动/生成期间响应较慢。
    """
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout) as r:
            return r.status == 200
    except Exception:
        return False


def _pause(msg):
    """等待用户按 Enter（无终端环境如后台启动时直接跳过，不崩溃）"""
    try:
        input(msg)
    except EOFError:
        pass


def wait_for_server(port, timeout=60):
    """等待服务启动（TCP 端口探测）

    不用 /api/health HTTP 探测：该接口会同步探测 TTS/数字人等依赖服务，
    冷启动期间响应可达数秒，会被 2 秒超时误判为"服务未就绪"导致误报启动失败。
    """
    start = time.time()
    while time.time() - start < timeout:
        if is_port_in_use(port):
            return True
        time.sleep(0.5)
    return False


def pick_port(preferred=8000):
    """选择 Web 端口：优先 8000；被其他程序占用时依次向后找空闲端口"""
    if not is_port_in_use(preferred) or is_enlyai_web(preferred):
        return preferred
    for port in range(preferred + 1, preferred + 10):
        if not is_port_in_use(port):
            print(f"[EnlyAI] 端口 {preferred} 被其他程序占用，改用 {port}")
            return port
    return None


def clear_pycache(root):
    """清除 krvoiceai 的 .pyc 缓存，避免代码更新后旧字节码生效"""
    base = root / "krvoiceai"
    if not base.exists():
        return
    removed = 0
    for pyc in base.rglob("*.pyc"):
        try:
            pyc.unlink()
            removed += 1
        except OSError:
            pass
    for cache in base.rglob("__pycache__"):
        try:
            cache.rmdir()
        except OSError:
            pass
    if removed:
        print(f"[EnlyAI] 已清除 {removed} 个过期的 .pyc 缓存")


def main():
    # 控制台输出重定向（如 GBK 终端）时避免 UnicodeEncodeError 崩溃；
    # 行缓冲：后台/重定向场景也能实时看到启动进度
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except Exception:
        pass

    root = find_project_root()
    os.chdir(str(root))

    # 退出保护：launcher 结束时内核强制终止 Web 及其拉起的全部依赖服务
    _setup_kill_on_close_job()

    print("=" * 50)
    print("  EnlyAI - AI 口播/播客生成平台")
    print("=" * 50)
    print(f"      项目目录: {root}")

    # 如果 Web 服务已经在运行，直接打开浏览器（重复双击 exe 的场景）
    if is_enlyai_web(8000):
        print("[EnlyAI] 检测到服务已在运行（端口 8000），直接打开浏览器...")
        webbrowser.open("http://localhost:8000")
        _pause("\n按 Enter 键关闭此窗口...")
        return

    python_exe = find_python()
    if python_exe is None:
        print("[EnlyAI] 错误：未找到可用的 Python 环境。")
        print("       请先运行 启动.bat 完成环境安装（自动创建 .venv）。")
        _pause("\n按 Enter 键关闭...")
        return
    print(f"      Python: {python_exe}")

    port = pick_port(8000)
    if port is None:
        print("[EnlyAI] 错误：端口 8000-8009 均被占用，请释放端口后重试。")
        _pause("\n按 Enter 键关闭...")
        return
    url = f"http://localhost:{port}"

    # 清除过期字节码缓存（历史遗留问题：代码更新后旧 .pyc 仍在生效）
    clear_pycache(root)

    # 启动 uvicorn（作为子进程）。
    # 只绑定 127.0.0.1：本机访问足够，且避免 Windows 防火墙弹窗
    print(f"\n[1/2] 正在启动 Web 服务（端口 {port}）...")
    proc = subprocess.Popen(
        [python_exe, "-m", "uvicorn", "krvoiceai.web.server:app",
         "--host", "127.0.0.1", "--port", str(port)],
        cwd=str(root),
    )
    _assign_child_to_job(proc)

    print("[2/2] 等待服务就绪（首次启动会自动拉起 Ollama/CosyVoice/LatentSync，")
    print("     其中 CosyVoice 模型加载约 50 秒，期间生成按钮会提示稍候）...")
    if wait_for_server(port, timeout=60):
        print(f"      Web 服务已启动!")
        webbrowser.open(url)
        print(f"\n{'=' * 50}")
        print(f"  EnlyAI 已启动!")
        print(f"  浏览器地址: {url}")
        print(f"  关闭此窗口即可退出（Web + TTS/数字人等全部服务一并停止）")
        print(f"{'=' * 50}\n")
    else:
        print("      服务启动超时。请查看日志：workspace_data/logs/krvoiceai.log")
        proc.terminate()
        _pause("\n按 Enter 键关闭...")
        return

    # 等待进程结束（用户关闭窗口时子进程也会被终止）
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()


if __name__ == "__main__":
    main()
