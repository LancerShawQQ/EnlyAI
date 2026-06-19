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
