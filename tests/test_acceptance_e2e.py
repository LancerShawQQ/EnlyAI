"""完整端到端验收测试

对标旗博士 9 大能力，验证完整流程：
1. 文案提取（mock 模式）
2. 文案仿写
3. TTS 语音合成
4. 数字人口播生成
5. 字幕生成
6. 视频合成
7. 标题生成
8. 封面生成
9. 多平台发布（manifest 模式）

验证项：
- 全流程无异常完成
- 每个步骤状态为 success/skipped
- 最终视频文件存在且可播放
- 封面图片存在
- 标题文案已生成
- 进度回调被正确触发
- 断点续跑功能正常
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from krvoiceai.app import KrVoiceAI


# 测试文案（模拟真实口播内容）
TEST_SCRIPT = """大家好，今天和大家聊聊如何高效学习这件事。

很多人觉得学习就是死记硬背，其实完全不是这样。我总结了三个方法，帮你事半功倍。

第一，主动回忆。看完一段内容后，合上书，试着回忆刚才看了什么。这比反复阅读有效十倍。

第二，间隔重复。不要一次性学完，而是分散到几天里。今天学一遍，明天复习，一周后再看。记忆会越来越牢固。

第三，费曼技巧。把学到的东西讲给别人听。如果讲不清楚，说明你还没真正理解。

这三个方法看起来简单，但真正坚持下来的人不多。从今天开始试试吧。

关注我，获取更多学习干货。"""


class TestFullPipelineAcceptance:
    """完整端到端验收测试"""

    def test_full_9_module_pipeline(self, isolated_config):
        """验收测试：9 大模块全流程"""
        app = KrVoiceAI()

        progress_log = []

        def progress_cb(step, status, data):
            progress_log.append({
                "step": step,
                "status": status,
                "has_data": bool(data),
            })

        result = app.submit_and_run(
            script=TEST_SCRIPT,
            script_mode="polish",
            platform="douyin",
            auto_publish=False,
            progress_callback=progress_cb,
        )

        # === 整体验收 ===
        assert result["success"] is True, f"任务失败: {result.get('error')}"
        assert result["status"] == "success"

        # === 步骤验收 ===
        steps = result["steps"]
        # script_extract 应跳过（无参考 URL）
        assert steps["script_extract"]["status"] == "skipped"
        # 核心步骤应成功
        for step in ["script_write", "tts", "avatar", "subtitle", "compose"]:
            assert steps[step]["status"] == "success", \
                f"步骤 {step} 状态异常: {steps[step]}"
        # title/cover 应成功
        assert steps["title"]["status"] == "success"
        assert steps["cover"]["status"] == "success"
        # publish 应跳过（auto_publish=False）
        assert steps["publish"]["status"] == "skipped"

        # === 产物验收 ===
        output = result["output"]
        # 视频文件
        assert output["final_video"] is not None
        video_path = Path(output["final_video"])
        assert video_path.exists(), f"视频文件不存在: {video_path}"
        assert video_path.stat().st_size > 1000, "视频文件过小"
        # 文案
        assert output["script_text"], "文案为空"
        assert len(output["script_text"]) > 50, "文案过短"
        # 音频
        assert output["audio_path"] is not None
        audio_path = Path(output["audio_path"])
        assert audio_path.exists(), "音频文件不存在"
        # 字幕
        assert output["subtitle"] is not None
        subtitle_path = Path(output["subtitle"])
        assert subtitle_path.exists(), "字幕文件不存在"
        # 标题
        assert output["title"], "标题为空"
        # 封面
        assert output["cover"] is not None
        cover_path = Path(output["cover"])
        assert cover_path.exists(), "封面文件不存在"

        # === 进度回调验收 ===
        assert len(progress_log) > 0, "未触发进度回调"
        # 应包含 success 事件
        success_events = [e for e in progress_log if e["status"] == "success"]
        assert len(success_events) >= 7, \
            f"成功事件不足: {len(success_events)}"

    def test_pipeline_with_reference_url(self, isolated_config):
        """验收测试：带参考视频 URL（mock 提取文案）"""
        app = KrVoiceAI()

        result = app.submit_and_run(
            script="",  # 留空，使用参考视频提取
            reference_video_url="https://www.douyin.com/video/test123",
            script_mode="rewrite",
            platform="bilibili",
        )

        assert result["success"] is True
        # script_extract 应执行（有 URL）
        assert result["steps"]["script_extract"]["status"] == "success"
        # 提取的文案应非空
        assert result["output"]["script_text"]

    def test_pipeline_auto_publish(self, isolated_config):
        """验收测试：自动发布（manifest 模式）"""
        app = KrVoiceAI()

        result = app.submit_and_run(
            script="测试自动发布功能。",
            script_mode="polish",
            platform="douyin",
            auto_publish=True,
        )

        assert result["success"] is True
        # publish 应执行
        assert result["steps"]["publish"]["status"] == "success"

    def test_pipeline_all_platforms(self, isolated_config):
        """验收测试：所有平台"""
        app = KrVoiceAI()
        platforms = ["douyin", "bilibili", "kuaishou", "wechat_video"]

        for platform in platforms:
            result = app.submit_and_run(
                script=f"测试 {platform} 平台。",
                script_mode="polish",
                platform=platform,
            )
            assert result["success"] is True, \
                f"平台 {platform} 失败: {result.get('error')}"

    def test_pipeline_all_script_modes(self, isolated_config):
        """验收测试：所有文案模式"""
        app = KrVoiceAI()
        modes = ["polish", "rewrite", "generate"]

        for mode in modes:
            result = app.submit_and_run(
                script="测试不同文案模式的效果。",
                script_mode=mode,
            )
            assert result["success"] is True, \
                f"模式 {mode} 失败: {result.get('error')}"
            assert result["output"]["script_text"], \
                f"模式 {mode} 文案为空"

    def test_resume_from_failure(self, isolated_config):
        """验收测试：断点续跑"""
        app = KrVoiceAI()

        # 第一次运行
        result1 = app.submit_and_run(
            script="测试断点续跑功能。",
            script_mode="polish",
        )
        assert result1["success"] is True
        job_id = result1["job_id"]

        # 重跑（应从已完成状态续跑，快速完成）
        ok = app.rerun_job(job_id)
        assert ok is True

    def test_video_is_playable(self, isolated_config, tmp_path):
        """验收测试：视频可播放（FFmpeg 可探测时长）"""
        app = KrVoiceAI()
        from krvoiceai.core.ffmpeg_utils import FFmpegRunner

        result = app.submit_and_run(
            script="测试视频可播放性。",
            script_mode="polish",
        )

        video_path = Path(result["output"]["final_video"])
        ff = FFmpegRunner()
        duration = ff.probe_duration(video_path)
        assert duration > 0, f"视频时长为 0: {video_path}"

    def test_subtitle_is_valid_srt(self, isolated_config):
        """验收测试：字幕是合法 SRT 格式"""
        app = KrVoiceAI()

        result = app.submit_and_run(
            script="测试字幕格式。",
            script_mode="polish",
        )

        subtitle_path = Path(result["output"]["subtitle"])
        content = subtitle_path.read_text(encoding="utf-8")
        # SRT 基本格式检查
        assert "-->" in content, "字幕缺少时间轴标记"
        # 应有序号
        lines = content.strip().split("\n")
        assert lines[0].strip().isdigit(), "字幕第一行不是序号"

    def test_cover_is_valid_image(self, isolated_config):
        """验收测试：封面是合法图片"""
        app = KrVoiceAI()
        from PIL import Image

        result = app.submit_and_run(
            script="测试封面图片。",
            script_mode="polish",
        )

        cover_path = Path(result["output"]["cover"])
        img = Image.open(cover_path)
        assert img.size[0] > 0 and img.size[1] > 0, "封面图片尺寸异常"

    def test_title_is_meaningful(self, isolated_config):
        """验收测试：标题有意义"""
        app = KrVoiceAI()

        result = app.submit_and_run(
            script="测试标题生成质量。",
            script_mode="polish",
            platform="douyin",
        )

        title = result["output"]["title"]
        assert title, "标题为空"
        assert len(title) >= 5, f"标题过短: {title}"


class TestSingleModuleAcceptance:
    """单模块验收测试（对标旗博士单环节调试）"""

    def test_each_module_executable(self, isolated_config):
        """验收测试：每个模块都能单独执行"""
        app = KrVoiceAI()
        modules_to_test = [
            "script_write", "tts", "avatar",
            "subtitle", "compose", "title", "cover",
        ]

        for module_name in modules_to_test:
            result = app.run_single_module(
                module_name=module_name,
                script="测试单模块执行。",
                script_mode="polish",
            )
            assert result["success"] is True, \
                f"模块 {module_name} 执行失败: {result.get('error')}"

    def test_module_context_propagation(self, isolated_config):
        """验收测试：模块间上下文传递"""
        app = KrVoiceAI()

        # 执行到 compose，验证上下文
        result = app.run_single_module(
            module_name="compose",
            script="测试上下文传递。",
            script_mode="polish",
        )

        ctx = result["context"]
        # 前置模块的产物应在上下文中
        assert ctx["script_text"], "文案未传递"
        assert ctx["audio_path"], "音频未传递"
        assert ctx["raw_video_path"], "数字人视频未传递"
        assert ctx["subtitle_path"], "字幕未传递"
        assert ctx["final_video"], "最终视频未生成"
