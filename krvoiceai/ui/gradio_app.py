"""Gradio Web UI - KrVoiceAI 虚拟人口播智能体（单页引导式工作流，对标旗博士）

界面结构：单页竖向全展开，5 步引导 + 顶部状态 + 底部高级区
  ① 文案来源   - 抖音/视频链接提取 或 直接输入
  ② 文案优化   - AI 润色/仿写 + 试听（可编辑）
  ③ 原创检测   - simhash + 违禁词 + LLM 风控，显示原因
  ④ 形象&音色  - 下拉选择 + 内联快速注册（无需跳页）
  ⑤ 一键生成&发布 - 生成视频 + 多平台发布
  底部高级区：设置 / 历史任务 / 系统状态（折叠，不干扰主流程）
"""
from __future__ import annotations

import json
import shutil
import time
import tempfile
import webbrowser
from pathlib import Path
from typing import Optional

try:
    import gradio as gr
except ImportError:
    gr = None

from ..app import KrVoiceAI
from ..core.settings_manager import get_settings_manager
from ..core.logger import get_logger

# 步骤中文名映射
STEP_NAMES = {
    "script_extract": "文案提取",
    "script_write": "文案优化",
    "originality_check": "原创检测",
    "tts": "语音合成",
    "avatar": "数字人生成",
    "subtitle": "字幕生成",
    "broll": "画中画/插播",
    "title": "标题生成",
    "cover": "封面生成",
    "compose": "视频合成",
    "publish": "多平台发布",
}

# 修正后的真实管线顺序（title/cover 在 compose 之前，与 pipeline/state.py 一致）
STEP_ORDER = [
    "script_extract", "script_write", "originality_check", "tts", "avatar",
    "subtitle", "broll", "title", "cover", "compose", "publish",
]

STATUS_ICON = {
    "pending": "⏳", "running": "🔄", "success": "✅",
    "failed": "❌", "skipped": "⏭️", "retry": "🔁",
}

# 各平台创作者发布页 URL
PUBLISH_URLS = {
    "douyin": "https://creator.douyin.com/creator-micro/content/upload",
    "bilibili": "https://member.bilibili.com/platform/upload/video/frame",
    "kuaishou": "https://cp.kuaishou.com/article/publish/video",
    "wechat_video": "https://channels.weixin.qq.com/platform/post/create",
}

_app: Optional[KrVoiceAI] = None


def _get_app() -> KrVoiceAI:
    global _app
    if _app is None:
        _app = KrVoiceAI()
    return _app


def _format_progress(steps_state: dict) -> str:
    """渲染竖向步骤进度"""
    lines = []
    for step in STEP_ORDER:
        name = STEP_NAMES.get(step, step)
        status = steps_state.get(step, "pending")
        icon = STATUS_ICON.get(status, "⏳")
        lines.append(f"{icon} {name}")
    return "\n".join(lines)


def _refresh_avatar_voice_options():
    """刷新形象/音色下拉选项，返回 (avatar_update, voice_update, default_avatar, default_voice)"""
    app = _get_app()
    avatars = app.list_avatars()
    voices = app.list_voices()
    a_ids = [a["avatar_id"] for a in avatars] or ["default"]
    v_ids = [v["voice_id"] for v in voices] or ["default"]
    return (
        gr.update(choices=a_ids, value=a_ids[0]),
        gr.update(choices=v_ids, value=v_ids[0]),
        a_ids[0], v_ids[0],
    )


# 自定义 CSS（Gradio 6.0+ 通过 launch(css=...) 注入）
CUSTOM_CSS = """
.step-card {
    border: 1px solid #e0e0e0;
    border-radius: 12px;
    padding: 20px;
    margin-bottom: 16px;
    background: white;
}
.step-header {
    font-size: 20px;
    font-weight: bold;
    color: #1e293b;
    margin-bottom: 4px;
}
.step-desc {
    font-size: 13px;
    color: #64748b;
    margin-bottom: 14px;
}
.step-nav {
    position: sticky;
    top: 0;
    z-index: 100;
    background: white;
    padding: 10px 16px;
    border-bottom: 1px solid #e2e8f0;
    display: flex;
    gap: 24px;
    justify-content: center;
    flex-wrap: wrap;
}
.step-nav a {
    text-decoration: none;
    color: #2563eb;
    font-size: 14px;
    font-weight: 500;
}
.status-banner {
    padding: 12px 16px;
    border-radius: 8px;
    margin-bottom: 12px;
    font-size: 14px;
}
"""


def _build_ui() -> "gr.Blocks":
    """构建单页引导式 Gradio 界面"""
    app = _get_app()

    with gr.Blocks(title="KrVoiceAI 虚拟人口播智能体") as demo:
        # ===== Hero banner =====
        gr.HTML("""
        <div style="text-align: center; padding: 18px 0; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); border-radius: 12px; margin-bottom: 12px;">
            <h1 style="color: white; margin: 0; font-size: 26px;">KrVoiceAI 虚拟人口播智能体</h1>
            <p style="color: rgba(255,255,255,0.92); margin: 6px 0 0 0;">本地声音克隆 · Wav2Lip 数字人 · 一键多平台发布 —— 5 步生成口播视频</p>
        </div>
        """)

        # ===== 粘滞步骤导航 =====
        gr.HTML("""
        <div class="step-nav">
            <a href="#step1">① 文案来源</a>
            <a href="#step2">② 文案优化</a>
            <a href="#step3">③ 原创检测</a>
            <a href="#step4">④ 形象&音色</a>
            <a href="#step5">⑤ 生成&发布</a>
        </div>
        """)

        # ===== 状态横幅 =====
        status_banner = gr.HTML("<div class='status-banner'>正在检查系统状态...</div>")

        # 共享的画中画片段 State（修复：编辑器与生成共用同一个 State）
        broll_state = gr.State([])

        # ============================================================
        # 第 ① 步：文案来源
        # ============================================================
        gr.HTML('<div id="step1"></div>')
        with gr.Group(elem_classes=["step-card"]):
            gr.HTML('<div class="step-header">① 文案来源</div>')
            gr.HTML('<div class="step-desc">粘贴抖音/快手/B站链接自动提取文案，或直接输入文案</div>')

            with gr.Row():
                ref_url = gr.Textbox(
                    label="视频/文章链接（可选）",
                    placeholder="粘贴抖音分享文本、v.douyin.com 链接、或新闻文章链接",
                    scale=4,
                )
                extract_btn = gr.Button("📋 提取文案", variant="secondary", scale=1)

            script_input = gr.Textbox(
                label="口播文案（提取结果会填入此处，可直接编辑）",
                lines=6,
                placeholder="在这里输入或粘贴文案，也可用上方按钮从链接自动提取...",
                info="建议 150-500 字",
            )
            char_count = gr.Markdown("字数：0")
            extract_status = gr.Markdown("粘贴链接后点击「提取文案」按钮")

            def _extract_script(url, progress=gr.Progress(track_tqdm=False)):
                """从链接提取文案（抖音/快手反爬时自动用分享文本文案）"""
                if not url or not url.strip():
                    return None, "⚠️ 请先粘贴链接", "字数：0"
                progress(0.1, desc="正在解析链接并提取文案（抖音视频可能需 20-40 秒）...")
                try:
                    app = _get_app()
                    res = app.process_script(script="", action="extract", reference_url=url.strip())
                    progress(0.9, desc="提取完成")
                    if res.get("success") and res.get("script"):
                        text = res["script"]
                        is_mock = res.get("mock", False)
                        tag = "（⚠️ 容错降级生成的示例文案，建议手动修改）" if is_mock else ""
                        return text, f"✅ 提取成功（{len(text)} 字）{tag}", f"字数：{len(text)}"
                    else:
                        err = res.get("error", "未知错误")
                        hint = "\n\n💡 建议：直接在第①步手动输入文案，或粘贴完整抖音分享文本（含文案描述）。"
                        return None, f"❌ 提取失败：{err}{hint}", "字数：0"
                except Exception as e:
                    hint = "\n\n💡 建议：直接手动输入文案，或粘贴完整抖音分享文本。"
                    return None, f"❌ 提取失败：{e}{hint}", "字数：0"

            def _count_chars(text):
                n = len(text) if text else 0
                return f"字数：{n}"

            extract_btn.click(
                _extract_script, inputs=[ref_url],
                outputs=[script_input, extract_status, char_count],
            )
            script_input.change(_count_chars, inputs=[script_input], outputs=[char_count])

        # ============================================================
        # 第 ② 步：文案优化
        # ============================================================
        gr.HTML('<div id="step2"></div>')
        with gr.Group(elem_classes=["step-card"]):
            gr.HTML('<div class="step-header">② 文案优化（可预览、可编辑）</div>')
            gr.HTML('<div class="step-desc">用 AI 润色/仿写文案，结果可手动修改，并可试听效果</div>')

            with gr.Row():
                opt_mode = gr.Dropdown(
                    label="优化模式",
                    choices=[("润色（保留原意，更流畅）", "polish"),
                             ("仿写（同主题换表达）", "rewrite"),
                             ("全新生成（按主题创作）", "generate")],
                    value="polish", scale=2,
                )
                opt_style = gr.Dropdown(
                    label="风格（可选）",
                    choices=[("默认", None), ("口语化", "口语化"), ("幽默", "幽默"),
                             ("严肃", "严肃"), ("活泼", "活泼"), ("专业", "专业")],
                    value=None, scale=2,
                )
                optimize_btn = gr.Button("✨ AI 优化文案", variant="primary", scale=1)

            script_optimized = gr.Textbox(
                label="优化后文案（可编辑）",
                lines=6,
                placeholder="点击「AI 优化文案」生成，或直接在此输入最终文案...",
            )
            opt_info = gr.Markdown("优化后的文案会显示在此，可直接编辑")

            with gr.Row():
                preview_voice = gr.Dropdown(
                    label="试听用音色", choices=["default"], value="default",
                    allow_custom_value=True, scale=3,
                )
                preview_btn = gr.Button("🔊 试听这段文案", variant="secondary", scale=2)
            preview_audio = gr.Audio(label="试听结果", type="filepath")

            def _optimize(text, mode, style, progress=gr.Progress(track_tqdm=False)):
                """AI 优化文案"""
                if not text or not text.strip():
                    return None, "⚠️ 请先在第①步输入文案", f"字数：0"
                progress(0.2, desc="AI 正在优化文案...")
                try:
                    app = _get_app()
                    action = mode
                    res = app.process_script(script=text, action=action, style=style)
                    progress(0.9, desc="优化完成")
                    if res.get("success") and res.get("script"):
                        opt_text = res["script"]
                        return opt_text, f"✅ 优化完成（{len(opt_text)} 字，模式={action}）", f"字数：{len(opt_text)}"
                    else:
                        return None, f"❌ 优化失败：{res.get('error', '未知错误')}", "字数：0"
                except Exception as e:
                    return None, f"❌ 优化失败：{e}", "字数：0"

            def _preview(text, voice, progress=gr.Progress(track_tqdm=False)):
                """试听文案合成"""
                if not text or not text.strip():
                    return None, "⚠️ 请先输入优化后文案"
                progress(0.3, desc="正在合成语音试听（CPU 合成，稍候）...")
                try:
                    app = _get_app()
                    res = app.preview_tts(text, voice)
                    progress(0.95, desc="合成完成")
                    if res["success"]:
                        return res["audio_path"], f"✅ 试听成功（{res['duration']}s）"
                    else:
                        return None, f"❌ 试听失败：{res.get('error')}"
                except Exception as e:
                    return None, f"❌ 试听失败：{e}"

            optimize_btn.click(
                _optimize, inputs=[script_input, opt_mode, opt_style],
                outputs=[script_optimized, opt_info, char_count],
            )
            # 优化后文案改写回 script_input（让用户继续编辑/检测）
            script_optimized.change(
                lambda t: t if t else None,
                inputs=[script_optimized], outputs=[script_input],
            )
            preview_btn.click(
                _preview, inputs=[script_optimized, preview_voice],
                outputs=[preview_audio, opt_info],
            )

        # ============================================================
        # 第 ③ 步：原创检测
        # ============================================================
        gr.HTML('<div id="step3"></div>')
        with gr.Group(elem_classes=["step-card"]):
            gr.HTML('<div class="step-header">③ 原创检测</div>')
            gr.HTML('<div class="step-desc">检查文案是否与历史重复、是否命中违禁词、LLM 风控评估</div>')

            check_btn = gr.Button("🔍 检测原创度", variant="primary")
            check_result = gr.HTML("<div style='color:#94a3b8;'>点击上方按钮开始检测</div>")

            def _check_originality(text, progress=gr.Progress(track_tqdm=False)):
                """原创检测（轻量级，直接调 checker，不重复跑 script_write）"""
                if not text or not text.strip():
                    return "<div style='color:#ef4444;'>⚠️ 请先输入文案</div>"
                progress(0.3, desc="正在检测原创度...")
                try:
                    app = _get_app()
                    res = app.check_originality(text)
                    progress(0.95, desc="检测完成")
                    if not res.get("success"):
                        err = res.get("error", "检测失败")
                        result = res.get("data", {}) or {}
                        detail_html = ""
                        if result.get("banned_words"):
                            words = result["banned_words"]
                            detail_html += f"<div>🚫 命中违禁词：<b style='color:#ef4444;'>{', '.join(words)}</b></div>"
                        if result.get("duplicate"):
                            dup = result["duplicate"]
                            detail_html += f"<div>🔁 与历史文案相似度过高：{dup.get('similarity', 0)*100:.0f}%</div>"
                        if result.get("llm_risk"):
                            risk = result["llm_risk"]
                            detail_html += f"<div>⚠️ LLM 风控：{risk.get('level','')} - {risk.get('reason','')}</div>"
                        return (f"<div style='color:#ef4444;font-weight:bold;'>❌ 未通过：{err}</div>"
                                f"{detail_html}"
                                f"<div style='color:#64748b;margin-top:8px;'>💡 可在第②步改写后重新检测</div>")
                    else:
                        result = res.get("data", {}) or {}
                        simhash = result.get("simhash", "")
                        status = result.get("status", "passed")
                        auto_fixed = result.get("banned_auto_fixed", [])
                        extra = ""
                        if auto_fixed:
                            extra = f"<div style='color:#f59e0b;'>🔧 已自动修正违禁词：{', '.join(auto_fixed)}</div>"
                        note = ""
                        if result.get("skipped_dupcheck"):
                            note = "<div style='color:#94a3b8;font-size:12px;'>(已跳过查重，仅违禁词扫描)</div>"
                        return (f"<div style='color:#10b981;font-weight:bold;'>✅ 通过原创检测</div>"
                                f"<div style='color:#64748b;font-size:13px;'>状态: {status} | simhash: {simhash}</div>"
                                f"{extra}{note}")
                except Exception as e:
                    return f"<div style='color:#ef4444;'>❌ 检测出错：{e}</div>"

            check_btn.click(_check_originality, inputs=[script_input], outputs=[check_result])

        # ============================================================
        # 第 ④ 步：形象 & 音色（内联快速注册）
        # ============================================================
        gr.HTML('<div id="step4"></div>')
        with gr.Group(elem_classes=["step-card"]):
            gr.HTML('<div class="step-header">④ 数字人形象 & 音色</div>')
            gr.HTML('<div class="step-desc">选择已注册的形象和音色；没有的话可点「快速注册」内联上传，无需跳页</div>')

            with gr.Row():
                with gr.Column(scale=1):
                    gr.HTML('<b>🧑 数字人形象</b>')
                    avatar_dd = gr.Dropdown(label="选择形象", choices=["default"], value="default", allow_custom_value=True)
                    avatar_preview = gr.Video(label="形象预览", visible=False)

                    with gr.Accordion("➕ 快速注册新形象", open=False):
                        new_avatar_id = gr.Textbox(label="形象名称（如 anchor_wang）", placeholder="英文/拼音")
                        new_avatar_video = gr.Video(label="上传口播人像视频（5-30秒，正脸）", include_audio=True)
                        reg_avatar_btn = gr.Button("💾 注册形象", size="sm")
                        reg_avatar_status = gr.Textbox(label="注册结果", interactive=False)

                with gr.Column(scale=1):
                    gr.HTML('<b>🎙️ 音色</b>')
                    voice_dd = gr.Dropdown(label="选择音色", choices=["default"], value="default", allow_custom_value=True)
                    gr.HTML('<div style="font-size:12px;color:#64748b;">default = MOSS 内置音色；克隆音色需上传样本注册</div>')

                    with gr.Accordion("➕ 快速注册新音色（声音克隆）", open=False):
                        new_voice_id = gr.Textbox(label="音色名称（如 teacher_li）", placeholder="英文/拼音")
                        new_voice_sample = gr.Audio(label="上传参考音频（5-30秒人声）", type="filepath")
                        reg_voice_btn = gr.Button("💾 注册音色", size="sm")
                        reg_voice_status = gr.Textbox(label="注册结果", interactive=False)

            def _register_avatar(aid, video):
                if not aid or not video:
                    return "❌ 请填写名称并上传视频", gr.update(), None, gr.update(visible=False)
                try:
                    app = _get_app()
                    ok = app.register_avatar(aid, Path(video))
                    av, vv, da, dv = _refresh_avatar_voice_options()
                    msg = f"✅ 形象 {aid} 注册成功！" if ok else f"❌ 注册失败"
                    return msg, av, da, gr.update(visible=False)
                except Exception as e:
                    return f"❌ 注册失败：{e}", gr.update(), None, gr.update(visible=False)

            def _register_voice(vid, sample):
                if not vid or not sample:
                    return "❌ 请填写名称并上传音频", gr.update(), None
                try:
                    app = _get_app()
                    ok = app.register_voice(vid, Path(sample))
                    av, vv, da, dv = _refresh_avatar_voice_options()
                    msg = f"✅ 音色 {vid} 注册成功！" if ok else f"❌ 注册失败"
                    return msg, vv, dv
                except Exception as e:
                    return f"❌ 注册失败：{e}", gr.update(), None

            def _preview_avatar(aid):
                """预览选中形象"""
                if not aid or aid == "default":
                    return None, gr.update(visible=False)
                app = _get_app()
                avatars_dir = Path(app.config.get("avatar.avatars_dir", "./config/avatars"))
                ref = avatars_dir / aid / "reference_video.mp4"
                if ref.exists():
                    return str(ref), gr.update(visible=True)
                return None, gr.update(visible=False)

            reg_avatar_btn.click(
                _register_avatar, inputs=[new_avatar_id, new_avatar_video],
                outputs=[reg_avatar_status, avatar_dd, avatar_dd, avatar_preview],
            )
            reg_voice_btn.click(
                _register_voice, inputs=[new_voice_id, new_voice_sample],
                outputs=[reg_voice_status, voice_dd, preview_voice],
            )
            avatar_dd.change(_preview_avatar, inputs=[avatar_dd], outputs=[avatar_preview, avatar_preview])

        # ============================================================
        # 第 ⑤ 步：一键生成 & 发布
        # ============================================================
        gr.HTML('<div id="step5"></div>')
        with gr.Group(elem_classes=["step-card"]):
            gr.HTML('<div class="step-header">⑤ 一键生成 & 发布</div>')
            gr.HTML('<div class="step-desc">确认文案/形象/音色后，点击生成；完成后可一键发布到各平台</div>')

            with gr.Row():
                with gr.Column(scale=1):
                    platform_dd = gr.Dropdown(
                        label="目标平台",
                        choices=["douyin", "bilibili", "kuaishou", "wechat_video"],
                        value="douyin",
                    )
                    with gr.Accordion("🎛️ 画中画/插播（可选）", open=False):
                        gr.HTML('<div style="font-size:12px;color:#64748b;">在指定时间段插入插播画面：cut=全屏替换，pip=角窗</div>')
                        broll_path = gr.Textbox(label="插播视频/图片路径", placeholder="D:/videos/broll.mp4")
                        with gr.Row():
                            broll_start = gr.Number(label="开始(s)", value=0, minimum=0)
                            broll_end = gr.Number(label="结束(s)", value=5, minimum=0)
                            broll_mode = gr.Dropdown(label="模式", choices=[("全屏替换", "cut"), ("角窗", "pip")], value="cut")
                        broll_add_btn = gr.Button("➕ 添加片段", size="sm")
                        broll_timeline = gr.Textbox(label="时间线", lines=6, interactive=False, placeholder="（空）")
                        broll_clear_btn = gr.Button("🗑️ 清空", size="sm")

                    run_btn = gr.Button("🚀 开始生成视频", variant="primary", size="lg")

                with gr.Column(scale=1):
                    progress_out = gr.Textbox(
                        label="实时进度", value=_format_progress({}), lines=12, interactive=False,
                    )
                    run_status = gr.Textbox(label="任务状态", interactive=False)

            # 生成结果
            gr.HTML('<div style="margin-top:16px;font-weight:bold;font-size:16px;">生成结果</div>')
            with gr.Row():
                with gr.Column(scale=2):
                    video_out = gr.Video(label="成片预览")
                with gr.Column(scale=1):
                    title_out = gr.Textbox(label="标题", interactive=False)
                    cover_out = gr.Image(label="封面", type="filepath")
                    final_script = gr.Textbox(label="最终文案", lines=4, interactive=False)
            final_video_state = gr.State(None)

            with gr.Row():
                pub_douyin = gr.Button("📤 发布到抖音", size="sm")
                pub_bili = gr.Button("📤 发布到B站", size="sm")
                pub_kuaishou = gr.Button("📤 发布到快手", size="sm")
                pub_wechat = gr.Button("📤 发布到视频号", size="sm")
            publish_guide = gr.Textbox(label="发布清单（复制到平台）", lines=5, interactive=False)

            # ---- 画中画操作 ----
            def _broll_add(path, start, end, mode, current):
                if not path or not Path(path).exists():
                    return current, "❌ 路径无效或文件不存在"
                clip = {"path": path, "start": float(start), "end": float(end), "mode": mode, "volume": 1.0}
                current = list(current) + [clip]
                return current, _broll_timeline_render(current)

            def _broll_clear():
                return [], "（空）"

            def _broll_timeline_render(clips):
                if not clips:
                    return "（空）"
                lines = []
                for c in sorted(clips, key=lambda x: x["start"]):
                    tag = "全屏" if c["mode"] == "cut" else "角窗"
                    lines.append(f"[{c['start']:.1f}-{c['end']:.1f}] {tag} {c['path']}")
                return "\n".join(lines)

            broll_add_btn.click(
                _broll_add, inputs=[broll_path, broll_start, broll_end, broll_mode, broll_state],
                outputs=[broll_state, broll_timeline],
            )
            broll_clear_btn.click(_broll_clear, outputs=[broll_state, broll_timeline])

            # ---- 一键生成 ----
            def _run(script, avatar, voice, platform, broll):
                """执行完整生成流程"""
                # 优先用优化后的文案，否则用原始输入
                final_text = script
                if not final_text or not final_text.strip():
                    return (_format_progress({}), "❌ 请先在第①步输入文案",
                            None, "", None, "", None, None)
                steps_state = {s: "pending" for s in STEP_ORDER}
                def progress_cb(step_name, status, data):
                    steps_state[step_name] = status
                try:
                    result = app.submit_and_run(
                        script=final_text, reference_video_url=None,
                        avatar_id=avatar, voice_id=voice, script_mode="polish",
                        platform=platform, auto_publish=False,
                        broll_clips=broll or None, progress_callback=progress_cb,
                    )
                    progress_text = _format_progress(steps_state)
                    status_text = f"任务 {result['job_id']}: {result['status']}"
                    if result.get("error"):
                        status_text += f" | 错误: {result['error']}"
                    output = result.get("output", {})
                    fv = output.get("final_video")
                    title = output.get("title", "")
                    cover = output.get("cover")
                    script_text = output.get("script_text", "")
                    return (progress_text, status_text, fv, title, cover, script_text, fv, fv)
                except Exception as e:
                    return (_format_progress({}), f"❌ 生成失败：{e}",
                            None, "", None, "", None, None)

            run_btn.click(
                _run, inputs=[script_optimized, avatar_dd, voice_dd, platform_dd, broll_state],
                outputs=[progress_out, run_status, video_out, title_out, cover_out, final_script, final_video_state, final_video_state],
            )

            # ---- 发布按钮 ----
            def _open_publish(platform, video, title, script):
                if not video:
                    return "⚠️ 请先生成视频"
                url = PUBLISH_URLS.get(platform)
                tag_str = "#数字人 #AI口播 #口播视频"
                guide = f"【标题】{title or '口播视频'}\n\n【标签】{tag_str}\n\n【视频文件】{video}"
                try:
                    webbrowser.open(url)
                    return f"✅ 已打开 {platform} 创作者中心，请上传视频并粘贴清单。\n\n{guide}"
                except Exception as e:
                    return f"⚠️ 浏览器打开失败：{e}\n请手动访问：{url}\n\n{guide}"

            for btn, plat in [(pub_douyin, "douyin"), (pub_bili, "bilibili"),
                              (pub_kuaishou, "kuaishou"), (pub_wechat, "wechat_video")]:
                btn.click(
                    lambda v, t, s, p=plat: _open_publish(p, v, t, s),
                    inputs=[final_video_state, title_out, final_script],
                    outputs=[publish_guide],
                )

        # ============================================================
        # 底部高级区（折叠，不干扰主流程）
        # ============================================================
        with gr.Accordion("⚙️ 高级（设置 / 历史任务 / 系统状态）", open=False):
            with gr.Tabs():
                # ---- 设置 ----
                with gr.Tab("设置"):
                    settings_mgr = get_settings_manager()
                    cur_tts = settings_mgr.get_section("tts", mask_sensitive=False) or {}
                    cur_avatar = settings_mgr.get_section("avatar", mask_sensitive=False) or {}
                    cur_sub = settings_mgr.get_section("subtitle", mask_sensitive=False) or {}
                    cur_llm = settings_mgr.get_section("llm", mask_sensitive=False) or {}
                    cur_moss = (cur_tts.get("moss_nano") or {})
                    w2l = cur_avatar.get("wav2lip") or {}
                    gf = cur_avatar.get("gfpgan") or {}

                    with gr.Row():
                        tts_provider = gr.Dropdown(
                            label="TTS 引擎",
                            choices=[("MOSS-TTS-Nano 本地克隆", "moss_nano"), ("小米 MiMo 云端", "mimo"),
                                     ("GPT-SoVITS 云端", "gpt_sovits"), ("Edge-TTS", "edge_tts"), ("Mock", "mock")],
                            value=cur_tts.get("provider", "moss_nano"),
                        )
                        tts_threads = gr.Slider(label="CPU 线程数", minimum=1, maximum=16, value=cur_moss.get("cpu_threads", 4))
                        moss_builtin = gr.Dropdown(
                            label="内置音色", choices=["Junhao", "Trump", "Ava", "Bella", "Adam", "Nathan"],
                            value=cur_moss.get("builtin_voice", "Junhao"),
                        )
                    with gr.Row():
                        wav2lip_python = gr.Textbox(label="Wav2Lip Python 路径",
                            value=w2l.get("env_python", "D:/cursor_project/koubo/wav2lip_env/Scripts/python.exe"))
                        gfpgan_enabled = gr.Checkbox(label="开启 GFPGAN 人脸增强", value=gf.get("enabled", False))
                        gfpgan_stride = gr.Slider(label="GFPGAN 步长", minimum=1, maximum=8, value=gf.get("stride", 1))
                    with gr.Row():
                        sub_size = gr.Slider(label="字幕字号", minimum=20, maximum=80, value=cur_sub.get("font_size", 36))
                        sub_margin = gr.Slider(label="字幕底部边距", minimum=40, maximum=300, value=cur_sub.get("margin_v", 120))
                        sub_karaoke = gr.Checkbox(label="卡拉OK高亮", value=cur_sub.get("karaoke", True))
                    with gr.Row():
                        llm_key = gr.Textbox(label="LLM API Key", value=cur_llm.get("api_key", ""), type="password")
                    with gr.Row():
                        save_btn = gr.Button("💾 保存设置（热生效）", variant="primary")
                    settings_status = gr.Textbox(label="保存结果", interactive=False)

                    def _save(t_p, t_t, t_b, w_p, g_e, g_s, s_s, s_m, s_k, l_k):
                        msgs = []
                        r = settings_mgr.update_section("tts", {"provider": t_p, "moss_nano": {"cpu_threads": int(t_t), "builtin_voice": t_b}})
                        msgs.append(r.get("message", ""))
                        r = settings_mgr.update_section("avatar", {"wav2lip": {"env_python": w_p}, "gfpgan": {"enabled": bool(g_e), "stride": int(g_s)}})
                        msgs.append(r.get("message", ""))
                        r = settings_mgr.update_section("subtitle", {"font_size": int(s_s), "margin_v": int(s_m), "karaoke": bool(s_k)})
                        msgs.append(r.get("message", ""))
                        r = settings_mgr.update_section("llm", {"api_key": l_k})
                        msgs.append(r.get("message", ""))
                        return "✅ " + " | ".join(msgs)

                    save_btn.click(
                        _save, inputs=[tts_provider, tts_threads, moss_builtin, wav2lip_python,
                                       gfpgan_enabled, gfpgan_stride, sub_size, sub_margin, sub_karaoke, llm_key],
                        outputs=[settings_status],
                    )

                # ---- 历史任务 ----
                with gr.Tab("历史任务"):
                    refresh_jobs_btn = gr.Button("🔄 刷新")
                    jobs_table = gr.Dataframe(
                        headers=["任务ID", "状态", "耗时(s)", "成片", "时间"],
                        datatype=["str", "str", "number", "str", "str"],
                        value=[], interactive=False, wrap=True,
                    )
                    with gr.Row():
                        rerun_id = gr.Textbox(label="任务ID（续跑）", scale=2)
                        rerun_btn = gr.Button("▶️ 续跑", size="sm")
                        del_id = gr.Textbox(label="任务ID（删除）", scale=2)
                        del_btn = gr.Button("🗑️ 删除", size="sm")
                    job_out = gr.Textbox(label="操作结果", interactive=False)

                    def _refresh_jobs():
                        jobs = app.list_jobs(limit=50)
                        rows = []
                        for j in jobs:
                            out = j.get("output") or {}
                            rows.append([
                                j.get("job_id", "")[:12], j.get("status", ""),
                                round(j.get("elapsed", 0) or 0, 1),
                                out.get("final_video", "") or "",
                                time.strftime("%m-%d %H:%M", time.localtime(j.get("created_at", 0))),
                            ])
                        return rows

                    def _find_job(jid):
                        for j in app.list_jobs(limit=200):
                            if j.get("job_id", "").startswith(jid) or j.get("job_id") == jid:
                                return j.get("job_id")
                        return None

                    def _rerun(jid):
                        full = _find_job(jid)
                        if not full:
                            return f"❌ 未找到 {jid}"
                        ok = app.rerun_job(full)
                        return f"{'✅ 续跑完成' if ok else '❌ 续跑失败'}: {full}"

                    def _del(jid):
                        full = _find_job(jid)
                        if not full:
                            return f"❌ 未找到 {jid}"
                        app.delete_job(full)
                        return f"✅ 已删除 {full}"

                    refresh_jobs_btn.click(_refresh_jobs, outputs=[jobs_table])
                    rerun_btn.click(_rerun, inputs=[rerun_id], outputs=[job_out])
                    del_btn.click(_del, inputs=[del_id], outputs=[job_out])

                # ---- 系统状态 ----
                with gr.Tab("系统状态"):
                    sys_status = gr.JSON(label="系统状态", value={})
                    refresh_sys_btn = gr.Button("🔄 刷新状态")
                    refresh_sys_btn.click(lambda: _get_app().health_check(), outputs=[sys_status])

        # ===== 页面加载时初始化 =====
        def _init_page():
            """页面加载：刷新状态横幅 + 形象/音色下拉"""
            app = _get_app()
            try:
                health = app.health_check()
            except Exception:
                health = {}
            ffmpeg_ok = health.get("ffmpeg", False)
            llm_mock = health.get("llm_mock", True)
            avatars_n = health.get("avatars_count", 0)
            voices_n = health.get("voices_count", 0)
            status_color = "#dcfce7" if ffmpeg_ok else "#fee2e2"
            status_text_color = "#166534" if ffmpeg_ok else "#991b1b"
            status_parts = []
            status_parts.append(f"{'✅' if ffmpeg_ok else '❌'} FFmpeg")
            status_parts.append(f"{'✅' if not llm_mock else '⚠️'} LLM{'(模拟)' if llm_mock else ''}")
            status_parts.append(f"🧑 形象×{avatars_n}")
            status_parts.append(f"🎙️ 音色×{voices_n}")
            banner = (
                f"<div class='status-banner' style='background:{status_color};color:{status_text_color};'>"
                f"{'&nbsp;&nbsp;|&nbsp;&nbsp;'.join(status_parts)}"
                + ("<br><span style='font-size:12px;'>💡 还没有形象/音色？在第④步点「快速注册」上传</span>" if (avatars_n == 0 or voices_n == 0) else "")
                + "</div>"
            )
            # 刷新下拉
            av, vv, _, _ = _refresh_avatar_voice_options()
            return banner, av, vv, vv, health

        demo.load(
            _init_page,
            outputs=[status_banner, avatar_dd, voice_dd, preview_voice, sys_status],
        )

    return demo


def launch(host: str = "127.0.0.1", port: int = 7860, share: bool = False) -> None:
    """启动 Gradio 服务（默认 127.0.0.1 本机访问，避免防火墙弹窗）"""
    if gr is None:
        raise RuntimeError("gradio 未安装，请运行: pip install gradio")
    demo = _build_ui()
    logger = get_logger()
    logger.info(f"启动 Gradio 服务: http://{host}:{port}")
    demo.queue(default_concurrency_limit=5, max_size=20).launch(
                        server_name=host, server_port=port, share=share,
                        inbrowser=True, show_error=True,
                        css=CUSTOM_CSS, theme=gr.themes.Soft())


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=7860)
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--share", action="store_true")
    args = parser.parse_args()
    launch(host=args.host, port=args.port, share=args.share)
