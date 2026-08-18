"""ServiceSupervisor 单元测试（不拉起真实服务，全部 mock）"""
from __future__ import annotations

from pathlib import Path

import pytest

import krvoiceai.core.service_supervisor as sup_mod
from krvoiceai.core.service_supervisor import ServiceSupervisor, _url_port


class _Cfg:
    """极简配置桩：仅支持 get('a.b.c', default)"""

    def __init__(self, data: dict):
        self.data = data

    def get(self, path: str, default=None):
        cur = self.data
        for k in path.split("."):
            if isinstance(cur, dict) and k in cur:
                cur = cur[k]
            else:
                return default
        return cur


DEFAULT_CFG = {
    "project": {"work_root": "workspace_data"},
    "services": {"auto_start": True, "conda_base": "", "cosyvoice": {}, "latentsync": {}},
    "llm": {"provider": "ollama"},
    "tts": {
        "provider": "cosyvoice",
        "cosyvoice": {"server_url": "http://localhost:8012"},
    },
    "avatar": {
        "provider": "latentsync",
        "latentsync": {
            "server_url": "http://localhost:8011",
            "resolution": 256,
            "inference_steps": 12,
        },
    },
}


@pytest.fixture
def cfg(monkeypatch):
    c = _Cfg(DEFAULT_CFG)
    monkeypatch.setattr(sup_mod, "get_config", lambda: c)
    return c


@pytest.fixture
def sup(cfg):
    return ServiceSupervisor()


def _mk(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


# ============ 环境探测 ============

def test_find_conda_env_python_found(tmp_path, monkeypatch):
    py = tmp_path / "miniconda3" / "envs" / "CosyVoice" / "python.exe"
    _mk(py)
    monkeypatch.setattr(sup_mod, "_conda_base_candidates", lambda: [tmp_path / "miniconda3"])
    assert sup_mod.find_conda_env_python("CosyVoice") == py


def test_find_conda_env_python_not_found(monkeypatch):
    monkeypatch.setattr(sup_mod, "_conda_base_candidates", lambda: [])
    assert sup_mod.find_conda_env_python("Nope") is None


def test_url_port():
    assert _url_port("http://localhost:8012", 8010) == 8012
    assert _url_port("http://localhost", 8010) == 8010
    assert _url_port("坏 url", 8010) == 8010


# ============ 启动描述构建 ============

def test_build_ollama_spec(cfg, monkeypatch):
    s = ServiceSupervisor()
    monkeypatch.setattr(sup_mod.shutil, "which", lambda name: None)
    spec, err = s._build_spec("ollama")
    assert spec is None and "ollama" in err

    monkeypatch.setattr(sup_mod.shutil, "which", lambda name: r"C:\Ollama\ollama.exe")
    spec, err = s._build_spec("ollama")
    assert spec is not None
    health, argv, cwd, env, log = spec
    assert health == "http://localhost:11434/api/tags"
    assert argv == [r"C:\Ollama\ollama.exe", "serve"]
    assert env.get("OLLAMA_KEEP_ALIVE") == "0"
    assert "ollama_service.log" in log


def test_build_cosyvoice_spec_prefers_repo_copy(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(sup_mod, "PROJECT_ROOT", tmp_path)
    _mk(tmp_path / "CosyVoice" / "cosyvoice_server.py")
    _mk(
        tmp_path / "CosyVoice" / "pretrained_models" / "models"
        / "FunAudioLLM--Fun-CosyVoice3-0.5B-2512" / "snapshots" / "master" / "config.yaml"
    )
    fake_py = tmp_path / "envs" / "CosyVoice" / "python.exe"
    _mk(fake_py)
    monkeypatch.setattr(sup_mod, "find_conda_env_python", lambda name: fake_py)

    s = ServiceSupervisor()
    spec, err = s._build_spec("cosyvoice")
    assert spec is not None, err
    health, argv, cwd, env, log = spec
    assert health == "http://localhost:8012/api/health"
    assert argv[0] == str(fake_py)
    assert argv[1] == str(tmp_path / "CosyVoice" / "cosyvoice_server.py")
    assert "--fp16" in argv
    assert "--port" in argv and "8012" in argv
    assert "--host" in argv and "127.0.0.1" in argv
    assert "--model_dir" in argv
    assert cwd == str(tmp_path / "CosyVoice")
    assert "cosyvoice_service.log" in log


def test_build_cosyvoice_spec_fallback_to_modules_copy(cfg, tmp_path, monkeypatch):
    """仓库内无拷贝时退回 krvoiceai/modules 版本，并补 PYTHONPATH"""
    monkeypatch.setattr(sup_mod, "PROJECT_ROOT", tmp_path)
    _mk(tmp_path / "CosyVoice" / "third_party" / "Matcha-TTS" / "setup.py")
    _mk(tmp_path / "krvoiceai" / "modules" / "cosyvoice_server.py")
    fake_py = tmp_path / "envs" / "CosyVoice" / "python.exe"
    _mk(fake_py)
    monkeypatch.setattr(sup_mod, "find_conda_env_python", lambda name: fake_py)

    s = ServiceSupervisor()
    spec, err = s._build_spec("cosyvoice")
    assert spec is not None, err
    health, argv, cwd, env, log = spec
    assert argv[1] == str(tmp_path / "krvoiceai" / "modules" / "cosyvoice_server.py")
    assert str(tmp_path / "CosyVoice") in env.get("PYTHONPATH", "")


def test_build_cosyvoice_spec_missing_python(cfg, monkeypatch):
    monkeypatch.setattr(sup_mod, "find_conda_env_python", lambda name: None)
    s = ServiceSupervisor()
    spec, err = s._build_spec("cosyvoice")
    assert spec is None and "CosyVoice" in err


def test_build_latentsync_spec(cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(sup_mod, "PROJECT_ROOT", tmp_path)
    project = tmp_path.parent / "LatentSync"
    _mk(project / "latentsync_server.py")
    fake_py = tmp_path / "envs" / "LatentSync" / "python.exe"
    _mk(fake_py)
    monkeypatch.setattr(sup_mod, "find_conda_env_python", lambda name: fake_py)

    s = ServiceSupervisor()
    spec, err = s._build_spec("latentsync")
    assert spec is not None, err
    health, argv, cwd, env, log = spec
    assert health == "http://localhost:8011/api/health"
    assert argv[0] == str(fake_py)
    assert cwd == str(project)
    assert "256" in argv and "12" in argv
    assert "latentsync_service.log" in log


def test_build_latentsync_spec_project_dir_override(cfg, tmp_path, monkeypatch):
    """配置显式指定 project_dir 时优先使用"""
    custom = tmp_path / "lsync-custom"
    _mk(custom / "latentsync_server.py")
    cfg.data.setdefault("services", {})["latentsync"] = {"project_dir": str(custom)}
    fake_py = tmp_path / "envs" / "LatentSync" / "python.exe"
    _mk(fake_py)
    monkeypatch.setattr(sup_mod, "find_conda_env_python", lambda name: fake_py)

    s = ServiceSupervisor()
    spec, err = s._build_spec("latentsync")
    assert spec is not None
    assert spec[2] == str(custom)


def test_needed_services(cfg):
    s = ServiceSupervisor()
    assert s.needed_services() == ["ollama", "cosyvoice", "latentsync"]
    cfg.data["tts"]["provider"] = "mock"
    cfg.data["avatar"]["provider"] = "mock"
    cfg.data["llm"]["provider"] = "mock"
    assert s.needed_services() == []


# ============ ensure / 状态机 ============

def test_ensure_reuses_healthy_service(cfg, sup, monkeypatch):
    """服务已健康时直接复用，绝不重复拉起"""
    monkeypatch.setattr(sup, "_probe", lambda url, timeout=3.0: True)

    def _no_spawn(*a, **k):
        raise AssertionError("不应拉起进程")

    monkeypatch.setattr(sup, "_spawn", _no_spawn)
    snap = sup.ensure("cosyvoice")
    assert snap["state"] == "running" and snap["healthy"] is True


def test_ensure_marks_failed_when_not_installable(cfg, sup, monkeypatch):
    monkeypatch.setattr(sup, "_probe", lambda url, timeout=3.0: False)
    monkeypatch.setattr(sup_mod.shutil, "which", lambda name: None)
    snap = sup.ensure("ollama")
    assert snap["state"] == "failed" and snap["healthy"] is False
    assert "ollama" in snap["error"]


def test_ensure_failed_cooldown(cfg, sup, monkeypatch):
    """失败后冷却期内不重复拉起"""
    monkeypatch.setattr(sup, "_probe", lambda url, timeout=3.0: False)
    monkeypatch.setattr(sup_mod.shutil, "which", lambda name: None)

    calls = []
    orig_spawn = sup._spawn

    def _spawn(name, spec):
        calls.append(name)

    sup.ensure("ollama")
    sup.ensure("ollama")  # 冷却期内：不应再次走到 spawn
    assert calls == []


def test_watch_marks_running_when_healthy(cfg, sup, monkeypatch):
    class _FakeProc:
        pid = 4321

        def poll(self):
            return None

    monkeypatch.setattr(sup, "_probe", lambda url, timeout=3.0: True)
    sup._watch("cosyvoice", _FakeProc(), "http://x/api/health", 5)
    assert sup._get_state("cosyvoice").state == "running"


def test_watch_marks_failed_on_timeout(cfg, sup, monkeypatch):
    class _DeadProc:
        pid = 4321

        def poll(self):
            return 3

    monkeypatch.setattr(sup, "_probe", lambda url, timeout=3.0: False)
    sup._watch("cosyvoice", _DeadProc(), "http://x/api/health", 0.2)
    st = sup._get_state("cosyvoice")
    assert st.state == "failed"
    assert "3" in st.error  # 退出码写进错误信息


# ============ 预检文案 ============

def test_preflight_message_starting(cfg, sup):
    st = sup._get_state("cosyvoice")
    st.state = "starting"
    st.log_path = "x/cosyvoice_service.log"
    msg = sup.preflight_message("cosyvoice", "手动运行 xxx")
    assert "正在自动启动" in msg and "稍后" in msg
    assert "手动运行" not in msg


def test_preflight_message_failed(cfg, sup):
    st = sup._get_state("cosyvoice")
    st.state = "failed"
    st.error = "进程退出码 1"
    st.log_path = "x/cosyvoice_service.log"
    msg = sup.preflight_message("cosyvoice", "手动运行 xxx")
    assert "自动启动失败" in msg and "手动运行 xxx" in msg


def test_preflight_message_not_installable(cfg, sup, monkeypatch):
    monkeypatch.setattr(sup_mod.shutil, "which", lambda name: None)
    msg = sup.preflight_message("ollama", "手动运行 xxx")
    assert "未找到 ollama" in msg and "手动运行 xxx" in msg
