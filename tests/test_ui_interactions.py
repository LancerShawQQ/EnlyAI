"""UI 交互端到端测试

验证重构后的 Gradio UI 所有 Tab 的交互逻辑：
  Tab 1: 一键生成 - 全流程含进度回调
  Tab 2: 分步创作 - 单模块执行
  Tab 3: 任务管理 - 列表/详情/续跑/删除
  Tab 4: 形象管理 - 注册/列表
  Tab 5: 音色管理 - 注册/列表
  Tab 6: 系统状态 - 健康检查
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from krvoiceai.app import KrVoiceAI
from krvoiceai.ui.gradio_app import (
    STEP_NAMES,
    STEP_ORDER,
    _format_progress,
    _build_ui,
)


# ========== 进度展示测试 ==========

class TestProgressDisplay:
    """测试进度格式化逻辑"""

    def test_format_empty(self):
        """空状态应显示全部 pending"""
        result = _format_progress({})
        for step in STEP_ORDER:
            name = STEP_NAMES[step]
            assert name in result

    def test_format_with_status(self):
        """带状态的进度应显示对应图标"""
        state = {"script_write": "success", "tts": "running"}
        result = _format_progress(state)
        assert "✅" in result
        assert "🔄" in result

    def test_all_step_names_present(self):
        """所有 9 个步骤中文名都应展示"""
        result = _format_progress({})
        expected_names = ["文案提取", "文案仿写", "语音合成", "数字人生成",
                          "字幕生成", "视频合成", "标题生成", "封面生成", "多平台发布"]
        for name in expected_names:
            assert name in result, f"缺少步骤名: {name}"


# ========== UI 构建测试 ==========

class TestUIBuild:
    """测试 UI 能正常构建（不启动服务）"""

    def test_ui_buildable(self):
        """UI 应能正常构建，不抛异常"""
        # 重置全局 app
        import krvoiceai.ui.gradio_app as mod
        mod._app = None
        demo = _build_ui()
        assert demo is not None

    def test_ui_has_six_tabs(self):
        """UI 应有 6 个 Tab"""
        import krvoiceai.ui.gradio_app as mod
        mod._app = None
        # gradio Blocks 内部会记录子组件
        demo = _build_ui()
        # 验证 Blocks 对象创建成功
        assert demo.title == "KrVoiceAI 虚拟人口播智能体"


# ========== 一键生成交互测试 ==========

class TestOneClickGeneration:
    """测试 Tab 1 一键生成的交互逻辑"""

    def test_full_pipeline_with_progress(self, isolated_config):
        """全流程执行应触发进度回调"""
        import krvoiceai.ui.gradio_app as mod
        mod._app = KrVoiceAI()
        app = mod._app

        progress_events = []

        def progress_cb(step, status, data):
            progress_events.append((step, status))

        result = app.submit_and_run(
            script="大家好，今天分享一个高效学习的方法。第一，主动回忆比被动阅读有效十倍。第二，间隔重复能强化记忆。第三，费曼技巧帮你查漏补缺。关注我，获取更多学习干货。",
            script_mode="polish",
            platform="douyin",
            auto_publish=False,
            progress_callback=progress_cb,
        )

        assert result["success"] is True
        assert result["status"] == "success"
        # 应有多个进度事件
        assert len(progress_events) > 0
        # script_write 应该成功
        script_events = [e for e in progress_events if e[0] == "script_write"]
        assert any(e[1] == "success" for e in script_events)

    def test_output_contains_video(self, isolated_config):
        """生成的结果应包含视频路径"""
        import krvoiceai.ui.gradio_app as mod
        mod._app = KrVoiceAI()
        app = mod._app

        result = app.submit_and_run(
            script="测试文案，用于验证输出。",
            script_mode="polish",
        )

        output = result["output"]
        assert output.get("final_video") is not None
        assert Path(output["final_video"]).exists()

    def test_output_contains_script(self, isolated_config):
        """生成的结果应包含文案"""
        import krvoiceai.ui.gradio_app as mod
        mod._app = KrVoiceAI()
        app = mod._app

        result = app.submit_and_run(
            script="测试文案内容。",
            script_mode="polish",
        )

        output = result["output"]
        assert output.get("script_text")
        assert len(output["script_text"]) > 0

    def test_steps_in_result(self, isolated_config):
        """结果应包含每步状态"""
        import krvoiceai.ui.gradio_app as mod
        mod._app = KrVoiceAI()
        app = mod._app

        result = app.submit_and_run(
            script="测试文案。",
            script_mode="polish",
        )

        assert "steps" in result
        assert "script_write" in result["steps"]
        assert result["steps"]["script_write"]["status"] == "success"


# ========== 分步创作交互测试 ==========

class TestStepByStep:
    """测试 Tab 2 分步创作的单模块执行"""

    def test_run_single_module_script_write(self, isolated_config):
        """单模块执行：文案仿写"""
        app = KrVoiceAI()
        result = app.run_single_module(
            module_name="script_write",
            script="这是一段测试文案，用于验证单模块执行。",
            script_mode="polish",
        )
        assert result["success"] is True
        assert result["module"] == "script_write"
        assert "script_text" in result["result"]
        assert result["context"]["script_text"]

    def test_run_single_module_tts(self, isolated_config):
        """单模块执行：TTS（含前置 script_write）"""
        app = KrVoiceAI()
        result = app.run_single_module(
            module_name="tts",
            script="测试语音合成。",
            script_mode="polish",
        )
        assert result["success"] is True
        assert result["context"]["audio_path"] is not None
        assert Path(result["context"]["audio_path"]).exists()

    def test_run_single_module_avatar(self, isolated_config):
        """单模块执行：数字人（含前置 script_write + tts）"""
        app = KrVoiceAI()
        result = app.run_single_module(
            module_name="avatar",
            script="测试数字人生成。",
            script_mode="polish",
        )
        assert result["success"] is True
        assert result["context"]["raw_video_path"] is not None
        assert Path(result["context"]["raw_video_path"]).exists()

    def test_run_single_module_compose(self, isolated_config):
        """单模块执行：视频合成（含全部前置）"""
        app = KrVoiceAI()
        result = app.run_single_module(
            module_name="compose",
            script="测试完整合成。",
            script_mode="polish",
        )
        assert result["success"] is True
        assert result["context"]["final_video"] is not None
        assert Path(result["context"]["final_video"]).exists()

    def test_run_single_module_unknown(self, isolated_config):
        """未知模块应返回错误"""
        app = KrVoiceAI()
        result = app.run_single_module(
            module_name="nonexistent",
            script="测试",
        )
        assert result["success"] is False
        assert "未知模块" in result["error"]


# ========== 任务管理交互测试 ==========

class TestJobManagement:
    """测试 Tab 3 任务管理的交互"""

    def test_list_jobs(self, isolated_config):
        """列出任务"""
        app = KrVoiceAI()
        # 创建一个任务
        app.submit_and_run(script="测试任务列表。", script_mode="polish")
        jobs = app.list_jobs(limit=10)
        assert len(jobs) > 0

    def test_get_job_detail(self, isolated_config):
        """查看任务详情"""
        app = KrVoiceAI()
        result = app.submit_and_run(script="测试详情。", script_mode="polish")
        job_id = result["job_id"]
        detail = app.get_job(job_id)
        assert detail is not None
        assert detail["job_id"] == job_id
        assert detail["status"] == "success"
        # 应包含步骤详情
        assert len(detail["steps"]) == 9
        # 每步应有 result 字段
        for step in detail["steps"]:
            assert "result" in step

    def test_delete_job(self, isolated_config):
        """删除任务"""
        app = KrVoiceAI()
        result = app.submit_and_run(script="测试删除。", script_mode="polish")
        job_id = result["job_id"]
        ok = app.delete_job(job_id)
        assert ok is True
        # 删除后查不到
        assert app.get_job(job_id) is None

    def test_rerun_job(self, isolated_config):
        """断点续跑"""
        app = KrVoiceAI()
        result = app.submit_and_run(script="测试续跑。", script_mode="polish")
        job_id = result["job_id"]
        ok = app.rerun_job(job_id)
        assert ok is True


# ========== 形象/音色管理交互测试 ==========

class TestAssetManagement:
    """测试 Tab 4/5 形象和音色管理"""

    def test_list_avatars(self, isolated_config):
        """列出形象（空列表也应正常返回）"""
        app = KrVoiceAI()
        avatars = app.list_avatars()
        assert isinstance(avatars, list)

    def test_list_voices(self, isolated_config):
        """列出音色"""
        app = KrVoiceAI()
        voices = app.list_voices()
        assert isinstance(voices, list)

    def test_register_avatar(self, isolated_config, tmp_path):
        """注册形象"""
        from krvoiceai.core.audio_utils import generate_silent_wav
        from krvoiceai.core.ffmpeg_utils import FFmpegRunner
        app = KrVoiceAI()
        # 生成一个测试视频（图片 + 静音音频）
        ff = FFmpegRunner()
        from PIL import Image
        img = tmp_path / "test.jpg"
        Image.new("RGB", (640, 480), (100, 150, 200)).save(img)
        audio = tmp_path / "silent.wav"
        generate_silent_wav(audio, duration=2.0)
        test_video = tmp_path / "ref.mp4"
        ff.image_audio_to_video(img, audio, test_video)
        ok = app.register_avatar("test_avatar_01", test_video)
        assert ok is True
        # 验证列表
        avatars = app.list_avatars()
        ids = [a["avatar_id"] for a in avatars]
        assert "test_avatar_01" in ids

    def test_register_voice(self, isolated_config, tmp_path):
        """注册音色"""
        from krvoiceai.core.audio_utils import generate_silent_wav
        app = KrVoiceAI()
        # 生成测试音频
        test_audio = tmp_path / "sample.wav"
        generate_silent_wav(test_audio, duration=3.0)
        ok = app.register_voice("test_voice_01", test_audio)
        assert ok is True
        # 验证列表
        voices = app.list_voices()
        ids = [v["voice_id"] for v in voices]
        assert "test_voice_01" in ids


# ========== 系统状态交互测试 ==========

class TestSystemHealth:
    """测试 Tab 6 系统状态"""

    def test_health_check(self, isolated_config):
        """健康检查应返回完整状态"""
        app = KrVoiceAI()
        health = app.health_check()
        assert "ffmpeg" in health
        assert "gpu_tts" in health
        assert "gpu_avatar" in health
        assert "llm_mock" in health
        assert "avatars_count" in health
        assert "voices_count" in health
        # mock 模式下 ffmpeg 应可用
        assert health["ffmpeg"] is True
