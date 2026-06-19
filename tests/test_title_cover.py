"""标题生成 + 封面生成模块测试"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from PIL import Image

from krvoiceai.core.audio_utils import generate_silent_wav
from krvoiceai.core.base_module import JobContext, ModuleStatus
from krvoiceai.core.ffmpeg_utils import FFmpegRunner
from krvoiceai.core.llm_client import LLMClient
from krvoiceai.modules.cover_generator import CoverGenerator
from krvoiceai.modules.title_generator import TitleGenerator


# ============ 标题生成测试 ============

@pytest.fixture
def mock_llm():
    llm = MagicMock(spec=LLMClient)
    llm.is_mock = True
    llm.chat.return_value = (
        "1. AI数字人到底有多强？看完惊呆了\n"
        "2. 3分钟搞懂数字人技术\n"
        "3. 这个AI工具让你效率翻10倍\n"
        "4. 数字人会取代真人吗？\n"
        "5. 零基础也能做数字人口播"
    )
    return llm


@pytest.fixture
def title_gen(isolated_config, mock_llm):
    return TitleGenerator(llm_client=mock_llm)


def test_title_generate_douyin(title_gen, mock_llm):
    """抖音标题生成"""
    titles = title_gen.generate("AI数字人技术介绍", "douyin")
    assert len(titles) == 5
    assert "AI数字人" in titles[0] or "惊呆" in titles[0]
    mock_llm.chat.assert_called_once()


def test_title_generate_bilibili(title_gen, mock_llm):
    """B站标题生成"""
    title_gen.generate("测试文案", "bilibili")
    messages = mock_llm.chat.call_args[0][0]
    assert "站" in messages[1]["content"]


def test_title_parse_strips_numbering(title_gen, mock_llm):
    """解析去除编号"""
    mock_llm.chat.return_value = "1. 标题一\n2. 标题二\n3. 标题三"
    titles = title_gen.generate("test", "douyin")
    assert titles == ["标题一", "标题二", "标题三"]


def test_title_run_success(title_gen, job_work_dir):
    """模块执行成功"""
    ctx = JobContext(
        work_dir=job_work_dir,
        script_text="AI数字人技术介绍",
        metadata={"platform": "douyin"},
    )
    ctx.ensure_work_dir()
    result = title_gen.execute(ctx)
    assert result.success is True
    assert ctx.title
    assert len(ctx.metadata["title_candidates"]) == 5
    assert title_gen.status == ModuleStatus.SUCCESS


def test_title_no_script(title_gen, job_work_dir):
    """无文案处理"""
    ctx = JobContext(work_dir=job_work_dir, script_text="")
    ctx.ensure_work_dir()
    result = title_gen.execute(ctx)
    assert result.success is False


def test_title_mock_llm(isolated_config):
    """Mock LLM 生成标题"""
    isolated_config.set("llm.api_key", "")
    gen = TitleGenerator()
    titles = gen.generate("如何高效学习", "douyin")
    assert len(titles) >= 1
    assert all(len(t) <= 50 for t in titles)


# ============ 封面生成测试 ============

@pytest.fixture
def cover_gen(isolated_config):
    return CoverGenerator()


@pytest.fixture
def sample_video(job_work_dir):
    """生成测试视频"""
    ff = FFmpegRunner()
    img = job_work_dir / "src.jpg"
    Image.new("RGB", (1080, 1920), (100, 120, 150)).save(str(img), "JPEG")
    audio = job_work_dir / "a.wav"
    generate_silent_wav(audio, 3.0)
    video = job_work_dir / "src.mp4"
    ff.image_audio_to_video(img, audio, video, fps=25)
    return video


def test_cover_template_mode(cover_gen, job_work_dir):
    """模板模式生成封面"""
    ctx = JobContext(
        work_dir=job_work_dir,
        title="AI数字人技术揭秘",
    )
    ctx.ensure_work_dir()
    result = cover_gen.execute(ctx)
    assert result.success is True
    assert ctx.cover_path.exists()
    img = Image.open(str(ctx.cover_path))
    assert img.size == cover_gen.resolution


def test_cover_frame_mode(cover_gen, job_work_dir, sample_video):
    """抽帧模式生成封面"""
    ctx = JobContext(
        work_dir=job_work_dir,
        raw_video_path=sample_video,
        title="测试封面标题",
    )
    ctx.ensure_work_dir()
    result = cover_gen.execute(ctx)
    assert result.success is True
    assert ctx.cover_path.exists()
    img = Image.open(str(ctx.cover_path))
    assert img.size == cover_gen.resolution


def test_cover_long_title_wraps(cover_gen, job_work_dir):
    """长标题自动换行"""
    long_title = "这是一个非常非常长的标题需要被自动换行处理才能显示完整"
    ctx = JobContext(
        work_dir=job_work_dir,
        title=long_title,
    )
    ctx.ensure_work_dir()
    result = cover_gen.execute(ctx)
    assert result.success is True
    assert ctx.cover_path.exists()


def test_cover_no_title_uses_default(cover_gen, job_work_dir):
    """无标题用默认"""
    ctx = JobContext(work_dir=job_work_dir, title="")
    ctx.ensure_work_dir()
    result = cover_gen.execute(ctx)
    assert result.success is True
    assert ctx.cover_path.exists()


def test_cover_is_valid_jpeg(cover_gen, job_work_dir):
    """生成有效 JPEG"""
    ctx = JobContext(work_dir=job_work_dir, title="测试")
    ctx.ensure_work_dir()
    cover_gen.execute(ctx)
    img = Image.open(str(ctx.cover_path))
    assert img.format == "JPEG"
    assert img.size[0] > 0 and img.size[1] > 0


def test_cover_resolution_matches(cover_gen, job_work_dir):
    """分辨率符合配置"""
    ctx = JobContext(work_dir=job_work_dir, title="测试分辨率")
    ctx.ensure_work_dir()
    cover_gen.execute(ctx)
    img = Image.open(str(ctx.cover_path))
    assert img.size == (1080, 1920)
