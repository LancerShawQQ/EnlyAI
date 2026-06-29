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
from ..modules.script_extractor import ScriptExtractor

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
    template_id: Optional[str] = None  # generate 模式下使用的爆款模板 ID


class ParseShareTextRequest(BaseModel):
    """分享文本轻量解析请求（仅解析 URL + 描述，不触发下载/ASR）"""
    text: str = ""


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

    @app.post("/api/generate/async")
    async def generate_async(req: GenerateRequest):
        """异步提交视频生成任务，立即返回 job_id，前端轮询 /api/jobs/{job_id} 获取进度"""
        krvoice = _get_app()
        # 提交任务（仅创建，不阻塞）
        job_id = krvoice.orchestrator.submit_job(
            script=req.script,
            reference_video_url=req.reference_video_url,
            avatar_id=req.avatar_id,
            voice_id=req.voice_id,
            script_mode=req.script_mode,
            metadata={"platform": req.platform, "auto_publish": req.auto_publish},
            broll_clips=req.broll_clips,
        )
        # 在后台线程中运行任务（不等待完成）
        loop = asyncio.get_event_loop()
        loop.run_in_executor(
            None,
            lambda: krvoice.orchestrator.run_job(job_id),
        )
        return {"job_id": job_id, "status": "pending"}

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

    @app.post("/api/broll/suggest")
    async def suggest_broll_clips(req: dict):
        """B-roll 智能推荐（对标剪映智能匹配素材）

        Body: {"job_id": "xxx", "max_clips": 5}
        从 job 上下文读取文案+字幕时间戳，结合素材库生成 B-roll 推荐片段
        """
        import json as _json
        from ..modules.broll_engine import BRollEngine
        loop = asyncio.get_event_loop()

        job_id = req.get("job_id", "")
        max_clips = int(req.get("max_clips", 5))
        if not job_id:
            raise HTTPException(400, "缺少 job_id")

        def _suggest():
            # 1. 读 job context
            ctx_file = Path("workspace_data") / "jobs" / job_id / "context.json"
            if not ctx_file.exists():
                return {"success": False, "error": "任务上下文不存在"}
            try:
                ctx = _json.loads(ctx_file.read_text(encoding="utf-8"))
            except Exception as e:
                return {"success": False, "error": f"读取上下文失败: {e}"}

            # 2. 提取 script / subtitle_segments / video_duration
            input_data = ctx.get("input_data", {}) or {}
            metadata = ctx.get("metadata", {}) or {}
            script = (
                input_data.get("script")
                or metadata.get("script_text")
                or metadata.get("script")
                or metadata.get("extracted_script")
                or ""
            )
            subtitle_segments = (
                metadata.get("subtitle_segments")
                or input_data.get("subtitle_segments")
                or []
            )
            video_duration = float(metadata.get("video_duration") or 0)
            if not video_duration and subtitle_segments:
                video_duration = float(subtitle_segments[-1].get("end", 0))

            # 3. 读素材库
            broll_dir = Path("./config/broll_assets")
            assets = []
            if broll_dir.exists():
                for f in sorted(broll_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
                    if f.is_file():
                        ext = f.suffix.lower()
                        if ext in (".mp4", ".mov", ".avi", ".mkv", ".webm",
                                   ".jpg", ".jpeg", ".png", ".webp", ".bmp"):
                            kind = "video" if ext in (".mp4", ".mov", ".avi", ".mkv", ".webm") else "image"
                            assets.append({
                                "path": str(f),
                                "filename": f.name,
                                "kind": kind,
                                "size": f.stat().st_size,
                            })

            if not assets:
                return {"success": False, "error": "素材库为空，请先上传 B-roll 素材"}
            if not script and not subtitle_segments:
                return {"success": False, "error": "任务无文案和字幕，无法智能推荐"}

            # 4. 调用智能推荐
            engine = BRollEngine()
            engine.setup()
            suggestions = engine.suggest_broll_clips(
                script=script,
                subtitle_segments=subtitle_segments,
                assets=assets,
                video_duration=video_duration,
                max_clips=max_clips,
            )
            return {
                "success": True,
                "suggestions": suggestions,
                "meta": {
                    "script_length": len(script),
                    "subtitle_count": len(subtitle_segments),
                    "asset_count": len(assets),
                    "video_duration": video_duration,
                },
            }

        return await loop.run_in_executor(None, _suggest)

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

    @app.get("/api/cover/styles")
    async def get_cover_styles():
        """获取封面样式预设列表（对标剪映封面模板库）"""
        from ..modules.cover_generator import COVER_STYLE_PRESETS
        # 返回精简版（不含内部颜色元组，前端不需要）
        styles = [
            {
                "id": s["id"],
                "name": s["name"],
                "icon": s["icon"],
                "desc": s["desc"],
            }
            for s in COVER_STYLE_PRESETS
        ]
        return {"success": True, "styles": styles}

    @app.post("/api/cover/preview")
    async def cover_preview(req: dict):
        """生成封面预览图（不走流水线，供 UI 实时预览/重新生成）

        Body: {"title": "封面标题", "style_id": "deep_blue"}
        """
        from ..modules.cover_generator import CoverGenerator
        from pathlib import Path
        import time as _time

        title = (req.get("title") or "口播视频").strip()
        style_id = req.get("style_id", "deep_blue")
        if len(title) > 30:
            title = title[:30]

        loop = asyncio.get_event_loop()

        def _gen():
            # 输出到 workspace_data 目录，使前端可通过 /api/files 访问（/api/files 安全检查仅允许 workspace_data/tmp）
            output_dir = Path("workspace_data") / "cover_previews"
            output_dir.mkdir(parents=True, exist_ok=True)
            output = output_dir / f"cover_preview_{int(_time.time())}.jpg"
            engine = CoverGenerator()
            engine.setup()
            engine.preview(title, output, style_id=style_id)
            return output

        output_path = await loop.run_in_executor(None, _gen)
        # 返回 posix 风格路径，避免 Windows 反斜杠在前端 URL 编码时出问题
        return {"success": True, "cover_path": output_path.as_posix()}

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

    # ============ 文案试听 API ============

    @app.post("/api/preview/tts")
    async def preview_tts(req: dict):
        """文案试听：合成任意文本片段，返回音频文件路径

        用于文案编辑区实时试听，支持选中文本或全文前 200 字。
        可选传入 speed/volume/pitch/emotion 实时预览不同语音效果。
        """
        krvoice = _get_app()
        text = (req.get("text") or "").strip()
        voice_id = req.get("voice_id", "default")
        if not text:
            return {"success": False, "error": "无文案可试听"}
        # 限制试听长度（避免长时间等待）
        if len(text) > 200:
            text = text[:200]
            logger.info(f"文案试听：截断到 200 字")
        # 可选音频参数（语速/音量/音高/情感）
        speed = req.get("speed")
        volume = req.get("volume")
        pitch = req.get("pitch")
        emotion = req.get("emotion")
        # 类型转换
        try:
            speed = float(speed) if speed is not None else None
        except (TypeError, ValueError):
            speed = None
        try:
            volume = int(volume) if volume is not None else None
        except (TypeError, ValueError):
            volume = None
        try:
            pitch = int(pitch) if pitch is not None else None
        except (TypeError, ValueError):
            pitch = None
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: krvoice.preview_tts(
                text, voice_id, speed=speed, volume=volume,
                pitch=pitch, emotion=emotion,
            ),
        )
        return result

    # ============ 文案 AI 处理 API ============

    @app.get("/api/script/templates")
    async def get_script_templates():
        """获取文案爆款模板列表"""
        from ..app import SCRIPT_TEMPLATES
        return {"success": True, "templates": SCRIPT_TEMPLATES}

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
                template_id=req.template_id,
            )
        )
        return result

    @app.post("/api/script/parse")
    async def parse_share_text(req: ParseShareTextRequest):
        """轻量解析分享文本：返回识别到的 URL 和描述（不触发下载/ASR）

        用于前端实时预览：用户粘贴抖音/快手分享文本时，
        立即显示识别到的 URL 和文案描述，确认无误后再点"提取文案"。
        """
        text = (req.text or "").strip()
        if not text:
            return {"success": True, "url": "", "desc": ""}
        try:
            url = ScriptExtractor._extract_url_from_text(text)
            desc = ScriptExtractor._extract_desc_from_share_text(text)
            return {"success": True, "url": url, "desc": desc}
        except Exception as e:
            logger.warning(f"解析分享文本失败: {e}")
            return {"success": False, "url": "", "desc": "", "error": str(e)}

    # ============ 文案提取 Cookies 配置（抖音/快手反爬绕过） ============

    @app.post("/api/script/cookies")
    async def upload_script_cookies(file: UploadFile = File(...)):
        """上传抖音/快手 cookies 文件（Netscape 格式 .txt），用于 yt-dlp 绕过反爬

        上传后自动更新 asr.cookies_file 配置并触发热重建，立即生效。
        导出方法：浏览器安装 EditThisCookie / Get cookies.txt 插件，
        访问 douyin.com 并登录后导出为 .txt（Netscape 格式）。
        """
        cookies_dir = Path("./config/cookies")
        cookies_dir.mkdir(parents=True, exist_ok=True)
        # 校验扩展名
        suffix = Path(file.filename or "cookies.txt").suffix.lower()
        if suffix not in (".txt", ""):
            raise HTTPException(400, f"cookies 文件需为 .txt 格式（Netscape），收到: {suffix}")
        # 固定文件名（覆盖旧文件）
        save_path = cookies_dir / "douyin_cookies.txt"
        content = await file.read()
        # 简单校验 Netscape 格式（首行通常为 # Netscape HTTP Cookie File）
        text_head = content.decode("utf-8", errors="ignore").strip()[:200]
        if text_head and "#" not in text_head and "Netscape" not in text_head:
            logger.warning("上传的 cookies 文件可能不是标准 Netscape 格式，仍尝试保存")
        with open(save_path, "wb") as f:
            f.write(content)
        # 更新配置并触发热重建（script_extractor 重新读取 cookies_file）
        abs_path = str(save_path.resolve())
        try:
            get_settings_manager().update_section("asr", {"cookies_file": abs_path})
        except Exception as e:
            logger.warning(f"更新 asr.cookies_file 配置失败: {e}")
        logger.info(f"cookies 文件已保存: {save_path} ({len(content)} bytes), 配置已热更新")
        return {
            "success": True,
            "path": abs_path,
            "filename": "douyin_cookies.txt",
            "size": len(content),
            "message": "cookies 已配置，yt-dlp 下载将自动使用",
        }

    @app.get("/api/script/cookies")
    async def get_script_cookies():
        """查询当前 cookies 配置状态"""
        try:
            asr_config = get_settings_manager().get_section("asr", mask_sensitive=False)
        except Exception:
            asr_config = {}
        cookies_file = asr_config.get("cookies_file", "")
        exists = bool(cookies_file and Path(cookies_file).exists())
        info: dict = {
            "configured": bool(cookies_file),
            "exists": exists,
            "path": cookies_file,
        }
        if exists:
            p = Path(cookies_file)
            info["size"] = p.stat().st_size
            info["mtime"] = int(p.stat().st_mtime)
        return info

    @app.delete("/api/script/cookies")
    async def delete_script_cookies():
        """删除 cookies 文件并清空配置"""
        try:
            asr_config = get_settings_manager().get_section("asr", mask_sensitive=False)
        except Exception:
            asr_config = {}
        cookies_file = asr_config.get("cookies_file", "")
        deleted = False
        if cookies_file and Path(cookies_file).exists():
            try:
                Path(cookies_file).unlink()
                deleted = True
            except Exception as e:
                logger.warning(f"删除 cookies 文件失败: {e}")
        # 清空配置并热重建
        try:
            get_settings_manager().update_section("asr", {"cookies_file": ""})
        except Exception as e:
            logger.warning(f"清空 asr.cookies_file 配置失败: {e}")
        return {"success": True, "deleted": deleted}

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
