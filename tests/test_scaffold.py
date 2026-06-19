"""P0 脚手架烟雾测试"""
from __future__ import annotations

from pathlib import Path

from krvoiceai.core.config import Config, get_config
from krvoiceai.core.logger import setup_logging, get_logger
from krvoiceai.core.base_module import BaseModule, JobContext, ModuleResult, ModuleStatus
from krvoiceai.core.storage import Storage
from krvoiceai.pipeline.state import JobStore, JobStatus, PIPELINE_STEPS


def test_config_load_default():
    """配置可加载默认文件"""
    cfg = Config.load()
    assert cfg.get("project.name") == "KrVoiceAI"
    assert cfg.get("llm.provider") == "deepseek"
    assert cfg.get("avatar.provider") == "musetalk"


def test_config_env_override(monkeypatch):
    """环境变量可覆盖配置"""
    monkeypatch.setenv("KRVOICEAI_LLM_API_KEY", "sk-test-123")
    monkeypatch.setenv("KRVOICEAI_PIPELINE_GPU_ENABLED", "true")
    cfg = Config.load()
    assert cfg.get("llm.api_key") == "sk-test-123"
    assert cfg.get("pipeline.gpu_enabled") is True


def test_config_set_runtime():
    """运行时可修改配置"""
    cfg = Config.load()
    cfg.set("llm.model", "deepseek-reasoner")
    assert cfg.get("llm.model") == "deepseek-reasoner"


def test_config_ensure_dirs(tmp_path):
    """配置可创建所需目录"""
    cfg = Config.load()
    cfg.set("project.work_root", str(tmp_path / "ws"))
    cfg.set("project.temp_root", str(tmp_path / "ws" / "tmp"))
    cfg.set("tts.voices_dir", str(tmp_path / "ws" / "voices"))
    cfg.ensure_dirs()
    assert (tmp_path / "ws").exists()
    assert (tmp_path / "ws" / "tmp").exists()
    assert (tmp_path / "ws" / "voices").exists()


def test_logger_setup():
    """日志可初始化"""
    setup_logging()
    log = get_logger()
    log.info("测试日志输出")


class _DummyModule(BaseModule):
    name = "dummy"
    requires_gpu = False

    def run(self, ctx: JobContext) -> ModuleResult:
        ctx.script_text = "hello"
        return ModuleResult(success=True, data={"output": "hello"})


class _FailingModule(BaseModule):
    name = "failing"

    def run(self, ctx: JobContext) -> ModuleResult:
        raise RuntimeError("故意失败")


def test_base_module_execute_success(tmp_path):
    """模块执行成功路径"""
    m = _DummyModule()
    ctx = JobContext(work_dir=tmp_path)
    ctx.ensure_work_dir()
    result = m.execute(ctx)
    assert result.success is True
    assert result.data["output"] == "hello"
    assert m.status == ModuleStatus.SUCCESS
    assert result.duration > 0


def test_base_module_execute_failure(tmp_path):
    """模块执行失败路径（异常捕获）"""
    m = _FailingModule()
    ctx = JobContext(work_dir=tmp_path)
    result = m.execute(ctx)
    assert result.success is False
    assert "RuntimeError" in (result.error or "")
    assert m.status == ModuleStatus.FAILED


def test_job_context_workdir(tmp_path):
    """任务上下文工作目录创建"""
    ctx = JobContext(work_dir=tmp_path / "job123")
    ctx.ensure_work_dir()
    assert (tmp_path / "job123").exists()
    assert len(ctx.job_id) > 0


def test_storage_job_dir(tmp_path, monkeypatch):
    """存储可创建任务目录"""
    cfg = Config.load()
    cfg.set("project.work_root", str(tmp_path / "ws"))
    cfg.set("project.temp_root", str(tmp_path / "ws" / "tmp"))
    import krvoiceai.core.config as cm
    monkeypatch.setattr(cm, "_config", cfg)
    s = Storage()
    d = s.job_dir("job-abc")
    assert d.exists()
    assert d.name == "job-abc"


def test_job_store_create_and_query(tmp_path, monkeypatch):
    """任务状态库可创建与查询"""
    cfg = Config.load()
    cfg.set("pipeline.db_path", str(tmp_path / "jobs.db"))
    import krvoiceai.core.config as cm
    monkeypatch.setattr(cm, "_config", cfg)

    store = JobStore()
    store.create_job("job-1", {"script": "测试文案"})
    job = store.get_job("job-1")
    assert job is not None
    assert job["status"] == JobStatus.PENDING.value
    assert job["input"]["script"] == "测试文案"
    assert len(job["steps"]) == len(PIPELINE_STEPS)
    assert all(s["status"] == "pending" for s in job["steps"])


def test_job_store_step_update(tmp_path, monkeypatch):
    """任务步骤状态可更新"""
    cfg = Config.load()
    cfg.set("pipeline.db_path", str(tmp_path / "jobs.db"))
    import krvoiceai.core.config as cm
    monkeypatch.setattr(cm, "_config", cfg)

    store = JobStore()
    store.create_job("job-2", {})
    from krvoiceai.pipeline.state import StepStatus
    store.update_step("job-2", "tts", StepStatus.RUNNING)
    store.update_step("job-2", "tts", StepStatus.SUCCESS,
                      result={"audio": "out.wav"}, duration=1.5)
    job = store.get_job("job-2")
    tts_step = [s for s in job["steps"] if s["step"] == "tts"][0]
    assert tts_step["status"] == "success"
    assert tts_step["duration"] == 1.5
