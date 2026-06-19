"""Gradio Web UI - 对标旗博士流水线式分步布局

界面结构：
  Tab 1: 一键生成（全流程，含实时进度）
  Tab 2: 分步创作（单模块调试，对标旗博士模块化设计）
  Tab 3: 任务管理（历史记录、断点续跑）
  Tab 4: 形象管理（数字人注册）
  Tab 5: 音色管理（声音克隆注册）
  Tab 6: 系统状态（健康检查）
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

try:
    import gradio as gr
except ImportError:
    gr = None

from ..app import KrVoiceAI
from ..core.logger import get_logger

# 步骤中文名映射
STEP_NAMES = {
    "script_extract": "文案提取",
    "script_write": "文案仿写",
    "tts": "语音合成",
    "avatar": "数字人生成",
    "subtitle": "字幕生成",
    "compose": "视频合成",
    "title": "标题生成",
    "cover": "封面生成",
    "publish": "多平台发布",
}

STEP_ORDER = [
    "script_extract", "script_write", "tts", "avatar",
    "subtitle", "compose", "title", "cover", "publish",
]

# 步骤状态图标
STATUS_ICON = {
    "pending": "⏳",
    "running": "🔄",
    "success": "✅",
    "failed": "❌",
    "skipped": "⏭️",
    "retry": "🔁",
}

_app: Optional[KrVoiceAI] = None


def _get_app() -> KrVoiceAI:
    global _app
    if _app is None:
        _app = KrVoiceAI()
    return _app


def _format_progress(steps_state: dict) -> str:
    """格式化进度展示"""
    lines = []
    for step in STEP_ORDER:
        name = STEP_NAMES.get(step, step)
        status = steps_state.get(step, "pending")
        icon = STATUS_ICON.get(status, "⏳")
        lines.append(f"{icon} {name}")
    return "\n".join(lines)


def _build_ui() -> "gr.Blocks":
    """构建 Gradio 界面 - 对标旗博士"""
    app = _get_app()

    # 自定义 CSS：对标旗博士的清爽风格
    custom_css = """
    .step-progress {
        font-family: monospace;
        font-size: 14px;
        line-height: 2;
        padding: 16px;
        background: #f7f7f8;
        border-radius: 8px;
        border: 1px solid #e0e0e0;
    }
    .section-title {
        font-size: 18px;
        font-weight: bold;
        color: #2563eb;
        margin: 12px 0 8px 0;
        padding-bottom: 6px;
        border-bottom: 2px solid #2563eb;
    }
    .status-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 12px;
        font-weight: bold;
    }
    """

    with gr.Blocks(
        title="KrVoiceAI 虚拟人口播智能体",
    ) as demo:
        # 顶部标题区
        gr.HTML("""
        <div style="text-align: center; padding: 16px 0; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 12px; margin-bottom: 16px;">
            <h1 style="color: white; margin: 0; font-size: 28px;">KrVoiceAI 虚拟人口播智能体</h1>
            <p style="color: rgba(255,255,255,0.9); margin: 8px 0 0 0;">对标旗博士 · 离线批量口播视频自动化生成系统</p>
        </div>
        """)

        # ============ Tab 1: 一键生成 ============
        with gr.Tab("🎬 一键生成"):
            gr.HTML('<div class="section-title">输入设置</div>')
            with gr.Row():
                with gr.Column(scale=3):
                    script_input = gr.Textbox(
                        label="口播文案",
                        placeholder="直接输入文案，或留空并在下方填写参考视频链接自动提取...",
                        lines=6,
                        info="支持 150-500 字，系统会自动润色/仿写",
                    )
                    ref_url = gr.Textbox(
                        label="参考视频链接（可选，用于对标文案提取）",
                        placeholder="粘贴抖音/快手/B站视频链接，自动提取文案",
                        info="留空则直接使用上方文案",
                    )
                    with gr.Row():
                        mode_dd = gr.Dropdown(
                            label="文案模式",
                            choices=[("润色", "polish"), ("仿写", "rewrite"), ("全新生成", "generate")],
                            value="polish",
                            info="润色=优化表达 | 仿写=语义级改写 | 生成=根据主题创作",
                        )
                        platform_dd = gr.Dropdown(
                            label="目标平台",
                            choices=["douyin", "bilibili", "kuaishou", "wechat_video"],
                            value="douyin",
                        )
                    with gr.Row():
                        avatar_dd = gr.Dropdown(
                            label="数字人形象",
                            choices=["default"],
                            value="default",
                            allow_custom_value=True,
                        )
                        voice_dd = gr.Dropdown(
                            label="音色",
                            choices=["default"],
                            value="default",
                            allow_custom_value=True,
                        )
                    with gr.Row():
                        auto_publish = gr.Checkbox(
                            label="自动发布到目标平台",
                            value=False,
                            info="勾选后视频生成完成自动发布",
                        )
                        refresh_btn = gr.Button("🔄 刷新形象/音色", size="sm")

                    run_btn = gr.Button(
                        "🚀 开始生成视频",
                        variant="primary",
                        size="lg",
                    )

                with gr.Column(scale=2):
                    gr.HTML('<div class="section-title">实时进度</div>')
                    progress_out = gr.Textbox(
                        label="流水线进度",
                        value=_format_progress({}),
                        elem_classes=["step-progress"],
                        lines=10,
                        interactive=False,
                    )
                    status_out = gr.Textbox(
                        label="任务状态",
                        lines=2,
                        interactive=False,
                    )

            gr.HTML('<div class="section-title">生成结果</div>')
            with gr.Row():
                with gr.Column(scale=2):
                    video_out = gr.Video(label="成片预览")
                with gr.Column(scale=1):
                    title_out = gr.Textbox(label="标题", interactive=False)
                    cover_out = gr.Image(label="封面", type="filepath")
                    script_out = gr.Textbox(
                        label="最终文案", lines=5, interactive=False,
                    )
                    info_out = gr.JSON(label="详细信息")

            def _run(script, url, avatar, voice, mode, platform, publish):
                """执行全流程，实时更新进度"""
                steps_state = {s: "pending" for s in STEP_ORDER}

                def progress_cb(step_name, status, data):
                    steps_state[step_name] = status

                result = app.submit_and_run(
                    script=script,
                    reference_video_url=url or None,
                    avatar_id=avatar,
                    voice_id=voice,
                    script_mode=mode,
                    platform=platform,
                    auto_publish=publish,
                    progress_callback=progress_cb,
                )

                progress_text = _format_progress(steps_state)
                status_text = f"任务 {result['job_id']}: {result['status']}"
                if result.get("error"):
                    status_text += f" | 错误: {result['error']}"

                output = result.get("output", {})
                video_path = output.get("final_video")
                title = output.get("title", "")
                cover = output.get("cover")
                final_script = output.get("script_text", "")

                return (
                    progress_text, status_text,
                    video_path, title, cover, final_script, result,
                )

            def _refresh():
                avatars = app.list_avatars()
                voices = app.list_voices()
                a_ids = [a["avatar_id"] for a in avatars] or ["default"]
                v_ids = [v["voice_id"] for v in voices] or ["default"]
                return (
                    gr.update(choices=a_ids, value=a_ids[0]),
                    gr.update(choices=v_ids, value=v_ids[0]),
                )

            run_btn.click(
                _run,
                inputs=[script_input, ref_url, avatar_dd, voice_dd,
                        mode_dd, platform_dd, auto_publish],
                outputs=[progress_out, status_out,
                         video_out, title_out, cover_out, script_out, info_out],
            )
            refresh_btn.click(_refresh, outputs=[avatar_dd, voice_dd])
            demo.load(_refresh, outputs=[avatar_dd, voice_dd])

        # ============ Tab 2: 分步创作（单模块调试）============
        with gr.Tab("🔧 分步创作"):
            gr.Markdown("### 模块化分步执行（对标旗博士单环节调试）")
            gr.Markdown("可单独执行任一模块，便于调试和定制。前置模块会自动执行以准备上下文。")

            with gr.Row():
                with gr.Column(scale=1):
                    gr.HTML('<div class="section-title">基础设置</div>')
                    step_script = gr.Textbox(
                        label="口播文案",
                        placeholder="输入文案...",
                        lines=4,
                    )
                    step_ref_url = gr.Textbox(
                        label="参考视频链接（可选）",
                        placeholder="https://...",
                    )
                    with gr.Row():
                        step_avatar = gr.Dropdown(
                            label="数字人形象",
                            choices=["default"],
                            value="default",
                            allow_custom_value=True,
                        )
                        step_voice = gr.Dropdown(
                            label="音色",
                            choices=["default"],
                            value="default",
                            allow_custom_value=True,
                        )
                    with gr.Row():
                        step_mode = gr.Dropdown(
                            label="文案模式",
                            choices=[("润色", "polish"), ("仿写", "rewrite"), ("生成", "generate")],
                            value="polish",
                        )
                        step_platform = gr.Dropdown(
                            label="目标平台",
                            choices=["douyin", "bilibili", "kuaishou", "wechat_video"],
                            value="douyin",
                        )

                    gr.HTML('<div class="section-title">选择模块执行</div>')
                    module_dd = gr.Dropdown(
                        label="执行模块",
                        choices=[(STEP_NAMES[s], s) for s in STEP_ORDER],
                        value="script_write",
                    )
                    run_module_btn = gr.Button(
                        "▶️ 执行此模块",
                        variant="primary",
                    )

                with gr.Column(scale=2):
                    module_result_out = gr.JSON(label="模块执行结果")
                    module_ctx_out = gr.JSON(label="当前上下文")
                    module_audio = gr.Audio(label="音频产物", type="filepath")
                    module_video = gr.Video(label="视频产物")

            def _run_module(script, url, avatar, voice, mode, platform, module_name):
                result = app.run_single_module(
                    module_name=module_name,
                    script=script,
                    reference_video_url=url or None,
                    avatar_id=avatar,
                    voice_id=voice,
                    script_mode=mode,
                    platform=platform,
                )
                ctx = result.get("context", {})
                audio_path = ctx.get("audio_path")
                video_path = ctx.get("raw_video_path") or ctx.get("final_video")
                return result, ctx, audio_path, video_path

            def _refresh_step():
                avatars = app.list_avatars()
                voices = app.list_voices()
                a_ids = [a["avatar_id"] for a in avatars] or ["default"]
                v_ids = [v["voice_id"] for v in voices] or ["default"]
                return (
                    gr.update(choices=a_ids, value=a_ids[0]),
                    gr.update(choices=v_ids, value=v_ids[0]),
                )

            run_module_btn.click(
                _run_module,
                inputs=[step_script, step_ref_url, step_avatar, step_voice,
                        step_mode, step_platform, module_dd],
                outputs=[module_result_out, module_ctx_out, module_audio, module_video],
            )
            demo.load(_refresh_step, outputs=[step_avatar, step_voice])

        # ============ Tab 3: 任务管理 ============
        with gr.Tab("📋 任务管理"):
            gr.HTML('<div class="section-title">任务列表</div>')
            with gr.Row():
                refresh_jobs_btn = gr.Button("🔄 刷新列表", variant="primary", size="sm")
                limit_slider = gr.Slider(5, 100, value=20, step=5, label="显示数量")

            jobs_table = gr.Dataframe(
                headers=["任务ID", "状态", "创建时间", "时长"],
                label="历史任务",
                interactive=False,
            )

            gr.HTML('<div class="section-title">任务操作</div>')
            with gr.Row():
                job_id_input = gr.Textbox(label="任务 ID", scale=2)
                with gr.Column(scale=3):
                    with gr.Row():
                        detail_btn = gr.Button("📋 查看详情", size="sm")
                        rerun_btn = gr.Button("🔁 断点续跑", size="sm")
                        delete_btn = gr.Button("🗑️ 删除任务", size="sm", variant="stop")

            job_detail = gr.JSON(label="任务详情（含每步结果）")

            def _fmt_time(ts):
                if not ts:
                    return ""
                return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))

            def _list_jobs(limit):
                jobs = app.list_jobs(int(limit))
                rows = []
                for j in jobs:
                    # 计算总时长
                    detail = app.get_job(j["job_id"])
                    total_dur = sum(
                        s.get("duration") or 0 for s in detail.get("steps", [])
                    ) if detail else 0
                    rows.append([
                        j["job_id"],
                        j["status"],
                        _fmt_time(j.get("created_at")),
                        f"{total_dur:.1f}s",
                    ])
                return rows

            def _show_job(job_id):
                if not job_id:
                    return {"error": "请输入任务 ID"}
                return app.get_job(job_id)

            def _rerun(job_id):
                if not job_id:
                    return {"error": "请输入任务 ID"}
                ok = app.rerun_job(job_id)
                return {"job_id": job_id, "rerun_success": ok}

            def _delete(job_id):
                if not job_id:
                    return {"error": "请输入任务 ID"}
                ok = app.delete_job(job_id)
                return {"job_id": job_id, "deleted": ok}

            refresh_jobs_btn.click(_list_jobs, inputs=limit_slider, outputs=jobs_table)
            detail_btn.click(_show_job, inputs=job_id_input, outputs=job_detail)
            rerun_btn.click(_rerun, inputs=job_id_input, outputs=job_detail)
            delete_btn.click(_delete, inputs=job_id_input, outputs=job_detail)
            demo.load(_list_jobs, inputs=limit_slider, outputs=jobs_table)

        # ============ Tab 4: 形象管理 ============
        with gr.Tab("👤 形象管理"):
            gr.HTML('<div class="section-title">注册数字人形象</div>')
            gr.Markdown(
                "上传 3-10 秒正面说话视频，系统会提取形象用于口播生成。\n\n"
                "**要求**：正面人脸、光线充足、分辨率 ≥ 720p"
            )
            with gr.Row():
                with gr.Column(scale=1):
                    avatar_id_input = gr.Textbox(
                        label="形象 ID（英文字母+数字）",
                        placeholder="如：anchor_01",
                    )
                    avatar_video = gr.File(
                        label="参考视频（3-10s 正面说话）",
                        file_types=[".mp4", ".mov", ".avi"],
                    )
                    reg_avatar_btn = gr.Button("📥 注册形象", variant="primary")
                    avatar_result = gr.Textbox(label="注册结果", interactive=False)

                with gr.Column(scale=1):
                    gr.HTML('<div class="section-title">已注册形象</div>')
                    avatars_gallery = gr.JSON(label="形象列表")
                    refresh_avatars_btn = gr.Button("🔄 刷新", size="sm")

            def _reg_avatar(aid, video):
                if not aid:
                    return "请输入形象 ID", app.list_avatars()
                if not video:
                    return "请上传参考视频", app.list_avatars()
                ok = app.register_avatar(aid, Path(video.name))
                msg = f"✅ 形象 {aid} 注册成功" if ok else f"❌ 注册失败"
                return msg, app.list_avatars()

            reg_avatar_btn.click(
                _reg_avatar,
                inputs=[avatar_id_input, avatar_video],
                outputs=[avatar_result, avatars_gallery],
            )
            refresh_avatars_btn.click(
                lambda: app.list_avatars(), outputs=avatars_gallery,
            )
            demo.load(lambda: app.list_avatars(), outputs=avatars_gallery)

        # ============ Tab 5: 音色管理 ============
        with gr.Tab("🎙️ 音色管理"):
            gr.HTML('<div class="section-title">注册音色（声音克隆）</div>')
            gr.Markdown(
                "上传 5-10 秒干净人声样本，系统会克隆音色用于语音合成。\n\n"
                "**要求**：单人说话、无背景噪音、无音乐"
            )
            with gr.Row():
                with gr.Column(scale=1):
                    voice_id_input = gr.Textbox(
                        label="音色 ID（英文字母+数字）",
                        placeholder="如：voice_01",
                    )
                    voice_audio = gr.File(
                        label="样本音频（5-10s 干净人声）",
                        file_types=[".wav", ".mp3", ".m4a", ".flac"],
                    )
                    reg_voice_btn = gr.Button("📥 注册音色", variant="primary")
                    voice_result = gr.Textbox(label="注册结果", interactive=False)

                with gr.Column(scale=1):
                    gr.HTML('<div class="section-title">已注册音色</div>')
                    voices_gallery = gr.JSON(label="音色列表")
                    refresh_voices_btn = gr.Button("🔄 刷新", size="sm")

            def _reg_voice(vid, audio):
                if not vid:
                    return "请输入音色 ID", app.list_voices()
                if not audio:
                    return "请上传样本音频", app.list_voices()
                ok = app.register_voice(vid, Path(audio.name))
                msg = f"✅ 音色 {vid} 注册成功" if ok else f"❌ 注册失败"
                return msg, app.list_voices()

            reg_voice_btn.click(
                _reg_voice,
                inputs=[voice_id_input, voice_audio],
                outputs=[voice_result, voices_gallery],
            )
            refresh_voices_btn.click(
                lambda: app.list_voices(), outputs=voices_gallery,
            )
            demo.load(lambda: app.list_voices(), outputs=voices_gallery)

        # ============ Tab 6: 系统状态 ============
        with gr.Tab("⚙️ 系统状态"):
            gr.HTML('<div class="section-title">系统健康检查</div>')
            with gr.Row():
                health_btn = gr.Button("🔍 检查系统状态", variant="primary")
                refresh_health_btn = gr.Button("🔄 刷新", size="sm")

            health_out = gr.JSON(label="系统状态")

            # 状态说明
            gr.Markdown(
                """
                ### 状态说明

                | 项目 | 含义 |
                |------|------|
                | `ffmpeg` | FFmpeg 是否可用（视频处理必需） |
                | `gpu_tts` | 云端 TTS 服务是否在线 |
                | `gpu_avatar` | 云端数字人服务是否在线 |
                | `llm_mock` | LLM 是否为 mock 模式（无 API Key） |
                | `avatars_count` | 已注册数字人形象数量 |
                | `voices_count` | 已注册音色数量 |

                **提示**：GPU 服务不在线时，TTS 和数字人模块会自动降级为 mock 模式，
                可跑通全流程但产物为占位内容。配置云端 GPU 后即可生成真实音视频。
                """
            )

            def _health():
                return app.health_check()

            health_btn.click(_health, outputs=health_out)
            refresh_health_btn.click(_health, outputs=health_out)
            demo.load(_health, outputs=health_out)

    return demo


def launch(host: str = "0.0.0.0", port: int = 7860) -> None:
    """启动 Gradio 服务"""
    if gr is None:
        raise RuntimeError("gradio 未安装，请运行 pip install gradio")
    demo = _build_ui()
    logger = get_logger()
    logger.info(f"启动 Gradio 服务: http://{host}:{port}")
    demo.launch(server_name=host, server_port=port, show_error=True)


if __name__ == "__main__":
    launch()
