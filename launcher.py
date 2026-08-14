"""EnlyAI 启动器

双击运行此 exe：
1. 自动启动后端服务（uvicorn）
2. 等待服务就绪后自动打开浏览器
3. 在控制台窗口显示运行状态，关闭窗口即停止服务
"""
import os
import sys
import time
import threading
import webbrowser
import socket
from pathlib import Path


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
    """查找虚拟环境的 python"""
    root = find_project_root()
    # 优先用虚拟环境
    venv_python = root / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return str(venv_python)
    # 回退到系统 python
    return sys.executable


def is_port_in_use(port=8000):
    """检查端口是否被占用"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_for_server(port=8000, timeout=30):
    """等待服务启动"""
    start = time.time()
    while time.time() - start < timeout:
        if is_port_in_use(port):
            return True
        time.sleep(0.5)
    return False


def main():
    root = find_project_root()
    os.chdir(str(root))

    port = 8000
    url = f"http://localhost:{port}"

    # 如果服务已经在运行，直接打开浏览器
    if is_port_in_use(port):
        print(f"[EnlyAI] 检测到服务已在运行（端口 {port}），直接打开浏览器...")
        webbrowser.open(url)
        input("\n按 Enter 键关闭此窗口...")
        return

    print("=" * 50)
    print("  EnlyAI - AI 语音播客生成平台")
    print("=" * 50)
    print(f"\n[1/3] 正在启动服务（端口 {port}）...")
    print(f"      项目目录: {root}")
    print(f"      Python: {find_python()}")

    # 启动 uvicorn（作为子进程）
    python_exe = find_python()
    import subprocess

    proc = subprocess.Popen(
        [python_exe, "-m", "uvicorn", "krvoiceai.web.server:app",
         "--host", "0.0.0.0", "--port", str(port)],
        cwd=str(root),
    )

    # 等待服务就绪
    print(f"\n[2/3] 等待服务就绪...")
    if wait_for_server(port, timeout=30):
        print(f"      服务已启动!")
        print(f"\n[3/3] 正在打开浏览器...")
        time.sleep(1)  # 再等1秒让服务完全就绪
        webbrowser.open(url)
        print(f"\n{'=' * 50}")
        print(f"  EnlyAI 已启动!")
        print(f"  浏览器地址: {url}")
        print(f"  关闭此窗口即可停止服务")
        print(f"{'=' * 50}\n")
    else:
        print(f"      服务启动超时，请检查日志")
        proc.terminate()
        input("\n按 Enter 键关闭...")
        return

    # 等待进程结束（用户关闭窗口时子进程也会被终止）
    try:
        proc.wait()
    except KeyboardInterrupt:
        proc.terminate()
        proc.wait()


if __name__ == "__main__":
    main()
