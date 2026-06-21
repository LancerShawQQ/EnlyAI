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
    broll_clips: Optional[list] = None  # B-roll 画中画/插播片段


class ModuleRunRequest(BaseModel):
    module_name: str
    script: str = ""
    reference_video_url: Optional[str] = None
    avatar_id: str = "default"
    voice_id: str = "default"
    script_mode: str = "polish"
    platform: str = "douyin"
    broll_clips: Optional[list] = None


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
    action: str = "polish"  # polish/rewrite/expand/shorten/style/extract/generate
    style: Optional[str] = None  # 幽默/严肃/活泼/专业/口语化
    topic: Optional[str] = None  # generate 模式下的主题
    reference_url: Optional[str] = None  # extract 模式下的参考视频链接


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
            return FileResponse(
                str(index_file),
                headers={
                    "Cache-Control": "no-cache, no-store, must-revalidate",
                    "Pragma": "no-cache",
                    "Expires": "0",
                },
            )
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
                broll_clips=req.broll_clips,
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
                broll_clips=req.broll_clips,
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

    @app.get("/api/avatars/{avatar_id}/preview")
    async def get_avatar_preview(avatar_id: str):
        """获取数字人参考图预览"""
        avatars_dir = Path(_get_app().config.get("avatar.avatars_dir", "./config/avatars"))
        avatar_dir = avatars_dir / avatar_id
        if not avatar_dir.exists():
            raise HTTPException(404, "形象不存在")
        # 查找参考图
        for name in ("reference.jpg", "reference.png", "preview.jpg", "placeholder.jpg"):
            p = avatar_dir / name
            if p.exists():
                return FileResponse(str(p))
        raise HTTPException(404, "无参考图")

    # ============ B-roll 画中画素材管理 ============

    @app.post("/api/broll/upload")
    async def upload_broll(file: UploadFile = File(...)):
        """上传 B-roll 素材（视频/图片），返回可引用的路径"""
        broll_dir = Path("./config/broll_assets")
        broll_dir.mkdir(parents=True, exist_ok=True)
        suffix = Path(file.filename or "asset").suffix or ".mp4"
        # 生成唯一文件名
        import time as _t
        filename = f"broll_{int(_t.time())}_{file.filename}"
        # 清理文件名中的危险字符
        filename = "".join(c for c in filename if c.isalnum() or c in "._-")
        save_path = broll_dir / filename
        with open(save_path, "wb") as f:
            shutil.copyfileobj(file.file, f)
        return {
            "success": True,
            "path": str(save_path),
            "filename": filename,
            "size": save_path.stat().st_size,
        }

    @app.get("/api/broll/assets")
    async def list_broll_assets():
        """列出所有已上传的 B-roll 素材"""
        broll_dir = Path("./config/broll_assets")
        if not broll_dir.exists():
            return []
        assets = []
        for f in sorted(broll_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
            if f.is_file():
                ext = f.suffix.lower()
                kind = "video" if ext in (".mp4", ".mov", ".avi", ".mkv", ".webm") else "image"
                assets.append({
                    "path": str(f),
                    "filename": f.name,
                    "kind": kind,
                    "size": f.stat().st_size,
                })
        return assets

    @app.get("/api/broll/assets/{filename}")
    async def get_broll_asset(filename: str):
        """获取 B-roll 素材文件（用于预览）"""
        broll_dir = Path("./config/broll_assets")
        # 防止路径穿越
        safe_name = Path(filename).name
        p = broll_dir / safe_name
        if not p.exists() or not p.is_file():
            raise HTTPException(404, "素材不存在")
        return FileResponse(str(p))

    @app.post("/api/broll/apply")
    async def apply_broll(
        video_path: str = Form(...),
        clips_json: str = Form(...),
    ):
        """对已有视频应用 B-roll（独立调用，不经过完整流水线）

        Args:
            video_path: 输入视频路径
            clips_json: B-roll 片段列表 JSON 字符串
        """
        import json
        from ..modules.broll_engine import BRollEngine
        loop = asyncio.get_event_loop()

        def _apply():
            video = Path(video_path)
            if not video.exists():
                return {"success": False, "error": "视频不存在"}
            try:
                clips = json.loads(clips_json)
            except Exception as e:
                return {"success": False, "error": f"clips_json 解析失败: {e}"}
            engine = BRollEngine()
            engine.setup()
            output = video.parent / "broll_applied.mp4"
            result = engine.apply_broll_to_existing_video(video, clips, output)
            return {
                "success": True,
                "output_path": str(result),
                "size": result.stat().st_size,
            }

        return await loop.run_in_executor(None, _apply)

    @app.post("/api/video/quick-edit")
    async def quick_edit_video(
        video_path: str = Form(...),
        action: str = Form(...),
        params_json: str = Form(""),
    ):
        """快捷剪辑：裁剪/音量/淡入淡出

        Args:
            video_path: 输入视频路径
            action: 操作类型 trim / volume / fade
            params_json: 操作参数 JSON
                - trim: {start, end}
                - volume: {volume}
                - fade: {fade_in, fade_out}
        """
        import json
        from ..core.ffmpeg_utils import FFmpegRunner
        loop = asyncio.get_event_loop()

        def _edit():
            video = Path(video_path)
            if not video.exists():
                return {"success": False, "error": "视频不存在"}
            try:
                params = json.loads(params_json) if params_json else {}
            except Exception as e:
                return {"success": False, "error": f"params_json 解析失败: {e}"}
            ff = FFmpegRunner()
            if not ff.available():
                return {"success": False, "error": "FFmpeg 不可用"}
            stem = video.stem
            suffix = video.suffix
            if action == "trim":
                start = float(params.get("start", 0))
                end = params.get("end")
                end = float(end) if end is not None else None
                out = video.parent / f"{stem}_trimmed{suffix}"
                ff.trim_video(video, out, start=start, end=end)
            elif action == "volume":
                vol = float(params.get("volume", 1.0))
                out = video.parent / f"{stem}_vol{suffix}"
                ff.adjust_volume(video, out, volume=vol)
            elif action == "fade":
                fi = float(params.get("fade_in", 0))
                fo = float(params.get("fade_out", 0))
                out = video.parent / f"{stem}_fade{suffix}"
                ff.add_fade(video, out, fade_in=fi, fade_out=fo)
            else:
                return {"success": False, "error": f"未知操作: {action}"}
            return {
                "success": True,
                "output_path": str(out),
                "size": out.stat().st_size if out.exists() else 0,
            }

        return await loop.run_in_executor(None, _edit)

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
                           "cover", "publisher", "pipeline", "project", "logging",
                           "subtitle", "scene", "audio", "effects"):
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

    # ============ 场景化预制模板 API（对标腾讯智影/万兴播爆） ============

    @app.get("/api/scene/templates")
    async def get_scene_templates():
        """获取场景化预制模板列表（含文案骨架、样式推荐、形象/音色推荐）"""
        import yaml
        from pathlib import Path as _Path
        tpl_file = _Path("./config/presets/scene_templates.yaml")
        if not tpl_file.exists():
            return {"templates": {}}
        with open(tpl_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        templates = data.get("templates", {})
        # 返回精简信息（不含完整文案骨架，按需获取）
        result = {}
        for tid, tpl in templates.items():
            result[tid] = {
                "label": tpl.get("label", tid),
                "icon": tpl.get("icon", "📋"),
                "category": tpl.get("category", "其他"),
                "description": tpl.get("description", ""),
                "placeholders": list(tpl.get("placeholders", {}).keys()),
                "style": tpl.get("style", {}),
                "avatar_scene": tpl.get("avatar_scene", {}),
            }
        return {"templates": result}

    @app.get("/api/scene/templates/{template_id}")
    async def get_scene_template_detail(template_id: str):
        """获取单个场景模板详情（含完整文案骨架）"""
        import yaml
        from pathlib import Path as _Path
        tpl_file = _Path("./config/presets/scene_templates.yaml")
        if not tpl_file.exists():
            return {"success": False, "error": "模板文件不存在"}
        with open(tpl_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        templates = data.get("templates", {})
        if template_id not in templates:
            return {"success": False, "error": f"模板 {template_id} 不存在"}
        return {"success": True, "template": templates[template_id]}

    @app.post("/api/scene/fill-script")
    async def fill_scene_script(req: dict):
        """根据场景模板和占位符填充值，生成完整文案

        Body: {"template_id": "product_selling", "values": {"product_name": "蓝牙耳机", ...}}
        """
        import yaml
        from pathlib import Path as _Path
        tpl_file = _Path("./config/presets/scene_templates.yaml")
        if not tpl_file.exists():
            return {"success": False, "error": "模板文件不存在"}
        with open(tpl_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        templates = data.get("templates", {})
        template_id = req.get("template_id", "")
        values = req.get("values", {})
        if template_id not in templates:
            return {"success": False, "error": f"模板 {template_id} 不存在"}
        tpl = templates[template_id]
        script = tpl.get("script_template", "")
        # 替换占位符 {key} -> values[key]
        for key, val in values.items():
            script = script.replace(f"{{{key}}}", str(val))
        # 检查未填充的占位符
        import re
        unfilled = re.findall(r"\{(\w+)\}", script)
        return {
            "success": True,
            "script": script.strip(),
            "unfilled_placeholders": unfilled,
            "template_id": template_id,
        }

    @app.post("/api/scene/apply")
    async def apply_scene_template(req: dict):
        """一键应用场景模板：设置样式+BGM+滤镜+转场+情感+语速

        Body: {"template_id": "product_selling"}
        """
        import yaml
        from pathlib import Path as _Path
        tpl_file = _Path("./config/presets/scene_templates.yaml")
        if not tpl_file.exists():
            return {"success": False, "error": "模板文件不存在"}
        with open(tpl_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        templates = data.get("templates", {})
        template_id = req.get("template_id", "")
        if template_id not in templates:
            return {"success": False, "error": f"模板 {template_id} 不存在"}
        tpl = templates[template_id]
        style = tpl.get("style", {})
        sm = get_settings_manager()
        applied = []

        # 按配置段分组应用
        # 1. 字幕样式段
        sub_updates = {}
        if "subtitle_preset" in style:
            sub_updates["preset"] = style["subtitle_preset"]
        if "subtitle_animation" in style:
            sub_updates["animation"] = style["subtitle_animation"]
        if sub_updates:
            r = sm.update_section("subtitle", sub_updates)
            if r.get("success"):
                applied.append("subtitle")

        # 2. 音频段（BGM+情感+语速）
        audio_updates = {}
        if "bgm_track" in style:
            audio_updates["bgm"] = {"enabled": True, "track": style["bgm_track"]}
        if "emotion" in style:
            audio_updates["emotion"] = style["emotion"]
        if "speech_speed" in style:
            audio_updates["speed"] = style["speech_speed"]
        if audio_updates:
            r = sm.update_section("audio", audio_updates)
            if r.get("success"):
                applied.append("audio")

        # 3. 效果段（滤镜+转场）
        effects_updates = {}
        if "filter" in style:
            effects_updates["filter"] = style["filter"]
        if "transition" in style:
            effects_updates["transition"] = style["transition"]
        if effects_updates:
            r = sm.update_section("effects", effects_updates)
            if r.get("success"):
                applied.append("effects")

        return {
            "success": True,
            "template_id": template_id,
            "applied_sections": applied,
            "template": tpl,
        }

    @app.get("/api/presets/avatars")
    async def get_preset_avatars():
        """获取预制数字人形象库"""
        import yaml
        from pathlib import Path as _Path
        lib_file = _Path("./config/presets/avatar_voice_library.yaml")
        if not lib_file.exists():
            return {"avatars": {}}
        with open(lib_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return {"avatars": data.get("avatars", {})}

    @app.get("/api/presets/avatars/{avatar_id}/image")
    async def get_preset_avatar_image(avatar_id: str):
        """获取预制形象占位图"""
        from pathlib import Path as _Path
        from fastapi.responses import FileResponse
        img_path = _Path(f"./config/presets/avatars/{avatar_id}.jpg")
        if not img_path.exists():
            return {"success": False, "error": "形象图不存在"}
        return FileResponse(str(img_path), media_type="image/jpeg")

    @app.post("/api/presets/avatars/{avatar_id}/register")
    async def register_preset_avatar(avatar_id: str):
        """将预制形象注册为用户形象（对标万兴播爆"一键使用模板形象"）

        将 config/presets/avatars/{avatar_id}.jpg 复制到 avatars 目录，
        使用户可直接在向导中选择该形象。
        """
        from pathlib import Path as _Path
        import shutil
        src = _Path(f"./config/presets/avatars/{avatar_id}.jpg")
        if not src.exists():
            return {"success": False, "error": "预制形象图不存在"}
        target_id = f"preset_{avatar_id}"
        ok = _get_app().register_avatar(target_id, src)
        return {"success": ok, "avatar_id": target_id}

    @app.get("/api/presets/voices")
    async def get_preset_voices():
        """获取预制音色库"""
        import yaml
        from pathlib import Path as _Path
        lib_file = _Path("./config/presets/avatar_voice_library.yaml")
        if not lib_file.exists():
            return {"voices": {}}
        with open(lib_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return {"voices": data.get("voices", {})}

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
        """AI 文案处理：润色/仿写/扩写/缩写/风格转换/生成/提取"""
        krvoice = _get_app()
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: krvoice.process_script(
                script=req.script, action=req.action,
                style=req.style, topic=req.topic,
                reference_url=req.reference_url,
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
