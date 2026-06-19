"""KrVoiceAI Web Server - FastAPI + 精美 Web UI

提供 REST API 和静态文件服务，替代 Gradio 作为主 UI。
"""
from __future__ import annotations

import asyncio
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..app import KrVoiceAI
from ..core.logger import get_logger
from ..core.settings_manager import get_settings_manager

logger = get_logger().bind(component="web_server")

# 全局 app 实例（懒加载）
_app_instance: Optional[KrVoiceAI] = None


def _get_app() -> KrVoiceAI:
    global _app_instance
    if _app_instance is None:
        _app_instance = KrVoiceAI()
    return _app_instance


# ============ 请求模型 ============

class GenerateRequest(BaseModel):
    script: str = ""
    reference_video_url: Optional[str] = None
    avatar_id: str = "default"
    voice_id: str = "default"
    script_mode: str = "polish"
    platform: str = "douyin"
    auto_publish: bool = False


class ModuleRunRequest(BaseModel):
    module_name: str
    script: str = ""
    reference_video_url: Optional[str] = None
    avatar_id: str = "default"
    voice_id: str = "default"
    script_mode: str = "polish"
    platform: str = "douyin"


class SettingsUpdateRequest(BaseModel):
    section: str
    data: dict[str, Any]


class TestLLMRequest(BaseModel):
    provider: str = "mock"
    api_key: str = ""
    base_url: str = ""
    model: str = ""


class TestTTSRequest(BaseModel):
    provider: str = "mock"
    api_base: str = ""
    api_key: str = ""


class TestAvatarRequest(BaseModel):
    provider: str = "mock"
    api_base: str = ""


class ScriptProcessRequest(BaseModel):
    """文案 AI 处理请求"""
    script: str = ""
    action: str = "polish"  # polish/rewrite/expand/shorten/style_xxx
    style: Optional[str] = None  # 幽默/严肃/活泼/专业/口语化
    topic: Optional[str] = None  # generate 模式下的主题


class BatchGenerateItem(BaseModel):
    script: str = ""
    reference_video_url: Optional[str] = None
    avatar_id: str = "default"
    voice_id: str = "default"
    script_mode: str = "polish"
    platform: str = "douyin"
    auto_publish: bool = False


class BatchGenerateRequest(BaseModel):
    items: list[BatchGenerateItem]
    parallel: int = 1  # 并发数（目前仅支持 1）


class TemplateApplyRequest(BaseModel):
    template_id: str


# ============ FastAPI 应用 ============

def create_app() -> FastAPI:
    app = FastAPI(title="KrVoiceAI", version="0.2.0")

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 静态文件（Web UI）
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    # ============ 页面路由 ============

    @app.get("/")
    async def index():
        index_file = static_dir / "index.html"
        if index_file.exists():
            return FileResponse(str(index_file))
        return JSONResponse({"error": "UI 文件未找到"}, status_code=404)

    # ============ API 路由 ============

    @app.get("/api/health")
    async def health():
        return _get_app().health_check()

    @app.post("/api/generate")
    async def generate(req: GenerateRequest):
        """一键生成视频（全流程）"""
        krvoice = _get_app()
        # 在线程池中运行（避免阻塞事件循环）
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: krvoice.submit_and_run(
                script=req.script,
                reference_video_url=req.reference_video_url,
                avatar_id=req.avatar_id,
                voice_id=req.voice_id,
                script_mode=req.script_mode,
                platform=req.platform,
                auto_publish=req.auto_publish,
            )
        )
        return result

    @app.post("/api/module/run")
    async def run_module(req: ModuleRunRequest):
        """单模块执行"""
        krvoice = _get_app()
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: krvoice.run_single_module(
                module_name=req.module_name,
                script=req.script,
                reference_video_url=req.reference_video_url,
                avatar_id=req.avatar_id,
                voice_id=req.voice_id,
                script_mode=req.script_mode,
                platform=req.platform,
            )
        )
        return result

    @app.get("/api/jobs")
    async def list_jobs(limit: int = 50):
        return _get_app().list_jobs(limit)

    @app.get("/api/jobs/{job_id}")
    async def get_job(job_id: str):
        job = _get_app().get_job(job_id)
        if not job:
            raise HTTPException(404, "任务不存在")
        return job

    @app.delete("/api/jobs/{job_id}")
    async def delete_job(job_id: str):
        ok = _get_app().delete_job(job_id)
        return {"deleted": ok}

    @app.post("/api/jobs/{job_id}/rerun")
    async def rerun_job(job_id: str):
        loop = asyncio.get_event_loop()
        ok = await loop.run_in_executor(
            None, lambda: _get_app().rerun_job(job_id)
        )
        return {"success": ok}

    @app.get("/api/avatars")
    async def list_avatars():
        return _get_app().list_avatars()

    @app.post("/api/avatars/register")
    async def register_avatar(
        avatar_id: str = Form(...),
        file: UploadFile = File(...),
    ):
        # 保存上传文件到临时位置
        suffix = Path(file.filename or "ref.mp4").suffix or ".mp4"
        tmp = Path(tempfile.mktemp(suffix=suffix))
        with open(tmp, "wb") as f:
            shutil.copyfileobj(file.file, f)
        ok = _get_app().register_avatar(avatar_id, tmp)
        tmp.unlink(missing_ok=True)
        return {"success": ok, "avatar_id": avatar_id}

    @app.get("/api/voices")
    async def list_voices():
        return _get_app().list_voices()

    @app.post("/api/voices/register")
    async def register_voice(
        voice_id: str = Form(...),
        file: UploadFile = File(...),
    ):
        suffix = Path(file.filename or "sample.wav").suffix or ".wav"
        tmp = Path(tempfile.mktemp(suffix=suffix))
        with open(tmp, "wb") as f:
            shutil.copyfileobj(file.file, f)
        ok = _get_app().register_voice(voice_id, tmp)
        tmp.unlink(missing_ok=True)
        return {"success": ok, "voice_id": voice_id}

    # 文件下载（视频/封面等）
    @app.get("/api/files")
    async def get_file(path: str):
        p = Path(path)
        if not p.exists() or not p.is_file():
            raise HTTPException(404, "文件不存在")
        # 安全检查：只允许访问 workspace_data 目录
        if "workspace_data" not in str(p.resolve()) and "tmp" not in str(p.resolve()):
            raise HTTPException(403, "无权访问")
        return FileResponse(str(p))

    # ============ 设置中心 API ============

    @app.get("/api/settings")
    async def get_settings():
        """获取全部配置（敏感字段掩码）"""
        return get_settings_manager().get_all(mask_sensitive=True)

    @app.get("/api/settings/{section}")
    async def get_settings_section(section: str):
        """获取某段配置"""
        if section not in ("llm", "tts", "avatar", "asr", "composer",
                           "cover", "publisher", "pipeline", "project", "logging"):
            raise HTTPException(400, f"无效的配置段: {section}")
        return get_settings_manager().get_section(section, mask_sensitive=True)

    @app.put("/api/settings/{section}")
    async def update_settings_section(section: str, req: SettingsUpdateRequest):
        """更新某段配置（持久化 + 热更新）"""
        if req.section != section:
            raise HTTPException(400, "section 不一致")
        return get_settings_manager().update_section(section, req.data)

    @app.delete("/api/settings/{section}")
    async def reset_settings_section(section: str):
        """重置某段为默认"""
        return get_settings_manager().reset_section(section)

    @app.delete("/api/settings")
    async def reset_all_settings():
        """重置全部用户配置"""
        return get_settings_manager().reset_all()

    @app.get("/api/settings/presets/all")
    async def get_presets():
        """获取 provider 预设（供前端下拉）"""
        return get_settings_manager().get_provider_presets()

    @app.get("/api/creative/presets")
    async def get_creative_presets():
        """获取创作预设（字幕样式/动画/情感/姿态/滤镜/转场）"""
        return get_settings_manager().get_creative_presets()

    @app.get("/api/templates")
    async def get_templates():
        """获取创作模板列表"""
        return get_settings_manager().get_templates()

    @app.post("/api/templates/apply")
    async def apply_template(req: TemplateApplyRequest):
        """一键应用创作模板"""
        return get_settings_manager().apply_template(req.template_id)

    @app.get("/api/bgm/library")
    async def get_bgm_library():
        """获取 BGM 素材库"""
        cfg = _get_app().config
        return cfg.get("bgm_library", {}) or {}

    @app.post("/api/settings/test/llm")
    async def test_llm(req: TestLLMRequest):
        """测试 LLM 连接"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: get_settings_manager().test_llm(req.model_dump())
        )

    @app.post("/api/settings/test/tts")
    async def test_tts(req: TestTTSRequest):
        """测试 TTS 连接"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: get_settings_manager().test_tts(req.model_dump())
        )

    @app.post("/api/settings/test/avatar")
    async def test_avatar(req: TestAvatarRequest):
        """测试数字人服务连接"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: get_settings_manager().test_avatar(req.model_dump())
        )

    # ============ 文案 AI 处理 API ============

    @app.post("/api/script/process")
    async def process_script(req: ScriptProcessRequest):
        """AI 文案处理：润色/仿写/扩写/缩写/风格转换/生成"""
        krvoice = _get_app()
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: krvoice.process_script(
                script=req.script, action=req.action,
                style=req.style, topic=req.topic,
            )
        )
        return result

    # ============ 批量处理 API ============

    @app.post("/api/batch/generate")
    async def batch_generate(req: BatchGenerateRequest):
        """批量生成视频（串行执行，返回每个任务结果）"""
        krvoice = _get_app()
        loop = asyncio.get_event_loop()
        results = []

        def run_batch():
            batch_results = []
            for i, item in enumerate(req.items):
                try:
                    r = krvoice.submit_and_run(
                        script=item.script,
                        reference_video_url=item.reference_video_url,
                        avatar_id=item.avatar_id,
                        voice_id=item.voice_id,
                        script_mode=item.script_mode,
                        platform=item.platform,
                        auto_publish=item.auto_publish,
                    )
                    r["batch_index"] = i
                    batch_results.append(r)
                except Exception as e:
                    batch_results.append({
                        "batch_index": i, "success": False, "error": str(e)
                    })
            return batch_results

        results = await loop.run_in_executor(None, run_batch)
        return {"total": len(req.items), "results": results}

    return app


app = create_app()


def launch(host: str = "0.0.0.0", port: int = 8000) -> None:
    """启动 Web 服务"""
    import uvicorn
    logger.info(f"启动 Web 服务: http://{host}:{port}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    launch()
