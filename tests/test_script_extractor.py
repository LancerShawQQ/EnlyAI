"""对标文案提取模块测试"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from krvoiceai.core.base_module import JobContext, ModuleStatus
from krvoiceai.modules.script_extractor import ScriptExtractor


@pytest.fixture
def extractor(isolated_config):
    isolated_config.set("asr.provider", "mock")
    ext = ScriptExtractor()
    ext.setup()
    # Mock 网页抓取方法，避免测试时发起真实网络请求（Playwright/httpx）
    ext._extract_from_web_page = MagicMock(return_value=("", ""))
    return ext


def test_no_url_skipped(extractor, job_work_dir):
    """无 URL 时跳过"""
    ctx = JobContext(work_dir=job_work_dir)
    ctx.ensure_work_dir()
    result = extractor.execute(ctx)
    assert result.success is True
    assert result.data["skipped"] is True


def test_mock_extract_douyin(extractor):
    """Mock 提取抖音文案"""
    text = extractor.extract("https://www.douyin.com/video/123")
    assert "抖音" in text
    assert len(text) > 50
    assert "点赞" in text  # CTA


def test_mock_extract_bilibili(extractor):
    """Mock 提取 B 站文案"""
    text = extractor.extract("https://www.bilibili.com/video/BV1234")
    assert "B站" in text


def test_mock_extract_youtube(extractor):
    """Mock 提取 YouTube 文案"""
    text = extractor.extract("https://www.youtube.com/watch?v=abc")
    assert "YouTube" in text


def test_mock_extract_generic(extractor):
    """Mock 提取通用文案"""
    text = extractor.extract("https://example.com/video")
    assert len(text) > 50


def test_clean_text_removes_fillers(extractor):
    """清洗去除语气词"""
    dirty = "嗯啊今天那个聊聊这个话题嗯对吧"
    cleaned = extractor._clean_text(dirty)
    assert "嗯" not in cleaned
    assert "啊" not in cleaned
    assert "那个" not in cleaned
    assert "今天" in cleaned


def test_clean_text_merges_punctuation(extractor):
    """合并连续标点"""
    dirty = "你好。。。世界！！！"
    cleaned = extractor._clean_text(dirty)
    assert cleaned == "你好。世界！"


def test_run_sets_input_script(extractor, job_work_dir):
    """执行后设置 input_script"""
    ctx = JobContext(
        work_dir=job_work_dir,
        reference_video_url="https://www.douyin.com/video/123",
    )
    ctx.ensure_work_dir()
    result = extractor.execute(ctx)
    assert result.success is True
    assert ctx.input_script  # 提取的文案被设为 input_script
    assert extractor.status == ModuleStatus.SUCCESS


def test_run_preserves_existing_input_script(extractor, job_work_dir):
    """已有 input_script 时不覆盖"""
    ctx = JobContext(
        work_dir=job_work_dir,
        reference_video_url="https://www.douyin.com/video/123",
        input_script="用户自定义文案",
    )
    ctx.ensure_work_dir()
    extractor.execute(ctx)
    assert ctx.input_script == "用户自定义文案"
    # 但提取结果仍存入 metadata
    assert ctx.metadata["extracted_script"]


def test_extract_with_rewrite_flow(extractor, job_work_dir):
    """提取 + 仿写联动验证"""
    from krvoiceai.core.llm_client import LLMClient
    from krvoiceai.modules.script_writer import ScriptWriter

    # 提取
    ctx = JobContext(
        work_dir=job_work_dir,
        reference_video_url="https://www.bilibili.com/video/BV1234",
        metadata={"script_mode": "rewrite"},
    )
    ctx.ensure_work_dir()
    extractor.execute(ctx)

    # 仿写
    llm = LLMClient()  # mock 模式
    writer = ScriptWriter(llm_client=llm)
    rewritten = writer.write(ctx.input_script, mode="rewrite")
    assert rewritten
    assert len(rewritten) > 20


# ============ URL 提取边界用例（修复反引号/包裹符 Bug） ============

def test_extract_url_backtick_wrapped():
    """反引号包围的 URL 应正确提取，不带反引号"""
    text = "`https://v.douyin.com/ft9Ds7C-8Fs/`"
    url = ScriptExtractor._extract_url_from_text(text)
    assert url == "https://v.douyin.com/ft9Ds7C-8Fs/"
    assert "`" not in url


def test_extract_url_backtick_with_token_suffix():
    """反引号包围 + 口令后缀"""
    text = "`https://v.douyin.com/ft9Ds7C-8Fs/` anq:/ :1pm"
    url = ScriptExtractor._extract_url_from_text(text)
    assert url == "https://v.douyin.com/ft9Ds7C-8Fs/"
    assert "`" not in url
    assert "anq" not in url


def test_extract_url_from_full_share_text():
    """完整抖音分享文本（用户实际粘贴的格式）"""
    text = (
        "1.25 复制打开抖音，看看【风芒新闻的作品】深圳一三甲医院涉嫌伪造病历 "
        "七旬老人腿疼住院 手术... `https://v.douyin.com/ft9Ds7C-8Fs/` "
        "anq:/ :1pm 03/29 P@K.Wm"
    )
    url = ScriptExtractor._extract_url_from_text(text)
    assert url == "https://v.douyin.com/ft9Ds7C-8Fs/"
    assert "`" not in url


def test_extract_url_with_token_suffix_no_backtick():
    """URL + 口令后缀（无反引号），不应把口令带入 URL"""
    text = "https://v.douyin.com/Dy9OhN6yTe8/ f@B.Gv 07/20 :2pm VYZ:/"
    url = ScriptExtractor._extract_url_from_text(text)
    assert url == "https://v.douyin.com/Dy9OhN6yTe8/"
    assert "f@B" not in url


def test_extract_url_chinese_quote_wrapped():
    """中文引号「」包围的 URL"""
    text = "「https://v.douyin.com/xxx/」"
    url = ScriptExtractor._extract_url_from_text(text)
    assert url == "https://v.douyin.com/xxx/"


def test_extract_desc_from_share_text_with_backtick():
    """从含反引号的抖音分享文本提取描述，末尾不带反引号"""
    text = (
        "1.25 复制打开抖音，看看【风芒新闻的作品】深圳一三甲医院涉嫌伪造病历 "
        "七旬老人腿疼住院 手术... `https://v.douyin.com/ft9Ds7C-8Fs/` "
        "anq:/ :1pm 03/29 P@K.Wm"
    )
    desc = ScriptExtractor._extract_desc_from_share_text(text)
    assert desc  # 非空
    assert "`" not in desc
    assert "深圳一三甲医院" in desc
