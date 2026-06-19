"""Gradio Web UI"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

try:
    import gradio as gr
except ImportError:
    gr = None

from ..app import KrVoiceAI
from ..core.logger import get_logger


_app: Optional[KrVoiceAI] = None


def _get_app() -> KrVoiceAI:
    global _app
    if _app is None:
        _app = KrVoiceAI()
    return _app


def _build_ui() -> "gr.Blocks":
    """构建 Gradio 界面"""
    app = _get_app()

    with gr.Blocks(title="KrVoiceAI 虚拟人口播智能体", theme=gr.themes.Soft()) as demo:
        gr.Markdown("# KrVoiceAI 虚拟人口播智能体")
        gr.Markdown("对标旗博士的离线批量口播视频自动化生成系统")

        with gr.Tab("生成视频"):
            with gr.Row():
                with gr.Column(scale=2):
                    script_input = gr.Textbox(
                        label="口播文案",
                        placeholder="输入文案，或留空使用参考视频提取",
                        lines=8,
                    )
                    ref_url = gr.Textbox(
                        label="参考视频 URL（可选，用于文案提取）",
                        placeholder="https://...",
                    )
                    with gr.Row():
                        avatar_dd = gr.Dropdown(
                            label="数字人形象",
                            choices=["default"],
                            value="default",
                        )
                        voice_dd = gr.Dropdown(
                            label="音色",
                            choices=["default"],
                            value="default",
                        )
                    with gr.Row():
                        mode_dd = gr.Dropdown(
                            label="文案模式",
                            choices=["polish", "rewrite", "generate"],
                            value="polish",
                        )
                        platform_dd = gr.Dropdown(
                            label="目标平台",
                            choices=["douyin", "bilibili", "kuaishou", "wechat_video"],
                            value="douyin",
                        )
                    auto_publish = gr.Checkbox(label="自动发布", value=False)
                    run_btn = gr.Button("开始生成", variant="primary", size="lg")

                with gr.Column(scale=1):
                    status_out = gr.Textbox(label="任务状态", lines=3)
                    video_out = gr.Video(label="生成结果")
                    title_out = gr.Textbox(label="标题")
                    info_out = gr.JSON(label="详细信息")

            def _run(script, url, avatar, voice, mode, platform, publish):
                result = app.submit_and_run(
                    script=script,
                    reference_video_url=url or None,
                    avatar_id=avatar,
                    voice_id=voice,
                    script_mode=mode,
                    platform=platform,
                    auto_publish=publish,
                )
                status = f"任务 {result['job_id']}: {result['status']}"
                video_path = result["output"].get("final_video")
                title = result["output"].get("title", "")
                return status, video_path, title, result

            def _refresh_avatars():
                avatars = app.list_avatars()
                ids = [a["avatar_id"] for a in avatars] or ["default"]
                return gr.update(choices=ids, value=ids[0])

            def _refresh_voices():
                voices = app.list_voices()
                ids = [v["voice_id"] for v in voices] or ["default"]
                return gr.update(choices=ids, value=ids[0])

            run_btn.click(
                _run,
                inputs=[script_input, ref_url, avatar_dd, voice_dd,
                        mode_dd, platform_dd, auto_publish],
                outputs=[status_out, video_out, title_out, info_out],
            )
            demo.load(_refresh_avatars, outputs=avatar_dd)
            demo.load(_refresh_voices, outputs=voice_dd)

        with gr.Tab("任务管理"):
            with gr.Row():
                refresh_btn = gr.Button("刷新列表")
                limit_slider = gr.Slider(5, 100, value=20, step=5, label="显示数量")
            jobs_table = gr.Dataframe(
                headers=["任务ID", "状态", "创建时间"],
                label="任务列表",
            )
            with gr.Row():
                job_id_input = gr.Textbox(label="任务 ID")
                status_btn = gr.Button("查看详情")
                rerun_btn = gr.Button("重跑任务")
            job_detail = gr.JSON(label="任务详情")

            def _list_jobs(limit):
                jobs = app.list_jobs(int(limit))
                return [[j["job_id"], j["status"], j.get("created_at", "")]
                        for j in jobs]

            def _show_job(job_id):
                return app.get_job(job_id)

            def _rerun(job_id):
                ok = app.rerun_job(job_id)
                return {"job_id": job_id, "rerun_success": ok}

            refresh_btn.click(_list_jobs, inputs=limit_slider, outputs=jobs_table)
            status_btn.click(_show_job, inputs=job_id_input, outputs=job_detail)
            rerun_btn.click(_rerun, inputs=job_id_input, outputs=job_detail)
            demo.load(_list_jobs, inputs=limit_slider, outputs=jobs_table)

        with gr.Tab("形象管理"):
            with gr.Row():
                avatar_id_input = gr.Textbox(label="形象 ID")
                avatar_video = gr.File(label="参考视频（3-10s 正面说话）")
            reg_avatar_btn = gr.Button("注册形象")
            avatar_result = gr.Textbox(label="结果")
            avatars_list = gr.JSON(label="已注册形象")

            def _reg_avatar(aid, video):
                if not video:
                    return "请上传参考视频", None
                ok = app.register_avatar(aid, Path(video.name))
                return "注册成功" if ok else "注册失败", app.list_avatars()

            def _list_avatars():
                return app.list_avatars()

            reg_avatar_btn.click(
                _reg_avatar,
                inputs=[avatar_id_input, avatar_video],
                outputs=[avatar_result, avatars_list],
            )
            demo.load(_list_avatars, outputs=avatars_list)

        with gr.Tab("音色管理"):
            with gr.Row():
                voice_id_input = gr.Textbox(label="音色 ID")
                voice_audio = gr.File(label="样本音频（3-10s 干净人声）")
            reg_voice_btn = gr.Button("注册音色")
            voice_result = gr.Textbox(label="结果")
            voices_list = gr.JSON(label="已注册音色")

            def _reg_voice(vid, audio):
                if not audio:
                    return "请上传样本音频", None
                ok = app.register_voice(vid, Path(audio.name))
                return "注册成功" if ok else "注册失败", app.list_voices()

            def _list_voices():
                return app.list_voices()

            reg_voice_btn.click(
                _reg_voice,
                inputs=[voice_id_input, voice_audio],
                outputs=[voice_result, voices_list],
            )
            demo.load(_list_voices, outputs=voices_list)

        with gr.Tab("系统状态"):
            health_btn = gr.Button("检查系统状态")
            health_out = gr.JSON(label="系统状态")

            def _health():
                return app.health_check()

            health_btn.click(_health, outputs=health_out)
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
