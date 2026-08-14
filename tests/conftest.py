"""pytest 全局夹具"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from krvoiceai.core.config import Config, get_config


@pytest.fixture(scope="session")
def test_root(tmp_path_factory) -> Path:
    """会话级测试根目录"""
    return tmp_path_factory.mktemp("krvoiceai_test")


@pytest.fixture
def isolated_config(test_root: Path, monkeypatch) -> Config:
    """隔离的配置实例，所有路径指向临时目录"""
    work_root = test_root / "workspace_data"
    work_root.mkdir(parents=True, exist_ok=True)

    # 加载默认配置后覆盖路径
    cfg = Config.load()
    cfg.set("project.work_root", str(work_root))
    cfg.set("project.temp_root", str(work_root / "tmp"))
    cfg.set("logging.file", str(work_root / "logs" / "test.log"))
    cfg.set("logging.console", False)
    cfg.set("tts.voices_dir", str(work_root / "voices"))
    cfg.set("avatar.avatars_dir", str(work_root / "avatars"))
    cfg.set("asr.model_cache", str(work_root / "models" / "asr"))
    cfg.set("composer.bgm_dir", str(work_root / "bgm"))
    cfg.set("cover.templates_dir", str(work_root / "cover_templates"))
    cfg.set("publisher.cookies_dir", str(work_root / "cookies"))
    cfg.set("pipeline.db_path", str(work_root / "jobs.db"))
    cfg.set("pipeline.gpu_enabled", False)
    cfg.ensure_dirs()

    # 替换全局单例
    import krvoiceai.core.config as config_mod
    monkeypatch.setattr(config_mod, "_config", cfg)
    return cfg


@pytest.fixture
def job_work_dir(isolated_config, tmp_path) -> Path:
    """单个任务的工作目录"""
    d = tmp_path / "job_workdir"
    d.mkdir(parents=True, exist_ok=True)
    return d
