"""文案生成模块测试"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from krvoiceai.core.base_module import JobContext, ModuleStatus
from krvoiceai.core.llm_client import LLMClient
from krvoiceai.modules.script_writer import ScriptWriter


@pytest.fixture
def mock_llm():
    """Mock LLM 客户端"""
    llm = MagicMock(spec=LLMClient)
    llm.is_mock = True
    llm.provider = "mock"
    llm.chat.return_value = (
        "大家好，今天聊聊AI。\n\n这个话题很重要。\n\n点赞关注，下期见。"
    )
    return llm


@pytest.fixture
def writer(mock_llm, isolated_config):
    return ScriptWriter(llm_client=mock_llm)


def test_write_polish(writer, mock_llm):
    """润色模式"""
    result = writer.write("AI 很厉害", mode="polish")
    assert "AI" in result
    mock_llm.chat.assert_called_once()
    messages = mock_llm.chat.call_args[0][0]
    assert messages[0]["role"] == "system"
    assert "润色" in messages[1]["content"]


def test_write_rewrite(writer, mock_llm):
    """仿写模式"""
    result = writer.write("原文内容", mode="rewrite")
    assert result
    messages = mock_llm.chat.call_args[0][0]
    assert "仿写" in messages[1]["content"]


def test_write_generate(writer, mock_llm):
    """生成模式"""
    result = writer.write("如何高效学习", mode="generate")
    assert result
    messages = mock_llm.chat.call_args[0][0]
    assert "创作" in messages[1]["content"]


def test_write_invalid_mode(writer):
    """非法模式"""
    with pytest.raises(ValueError, match="不支持"):
        writer.write("test", mode="invalid")


def test_run_success(writer):
    """模块执行成功"""
    ctx = JobContext(input_script="测试文案", metadata={"script_mode": "polish"})
    result = writer.execute(ctx)
    assert result.success is True
    assert ctx.script_text
    assert result.data["mode"] == "polish"
    assert result.data["char_count"] > 0
    assert writer.status == ModuleStatus.SUCCESS


def test_run_empty_input(writer):
    """空输入处理"""
    ctx = JobContext(input_script="")
    result = writer.execute(ctx)
    assert result.success is False
    assert "为空" in result.error


def test_run_llm_failure(isolated_config):
    """LLM 调用失败"""
    llm = MagicMock(spec=LLMClient)
    llm.is_mock = False
    llm.provider = "deepseek"
    llm.chat.side_effect = RuntimeError("API 超时")
    w = ScriptWriter(llm_client=llm)
    ctx = JobContext(input_script="测试")
    result = w.execute(ctx)
    assert result.success is False
    assert "API 超时" in result.error


def test_postprocess_cleanup():
    """后处理清理空行"""
    llm = MagicMock(spec=LLMClient)
    llm.is_mock = True
    llm.chat.return_value = "\n\n  第一行  \n\n\n\n第二行\n\n  \n"
    w = ScriptWriter(llm_client=llm)
    result = w.write("input", mode="polish")
    assert result == "第一行\n\n第二行"


def test_mock_llm_no_key(isolated_config):
    """无 API key 时自动 mock"""
    isolated_config.set("llm.api_key", "")
    client = LLMClient()
    assert client.is_mock is True
    result = client.chat([{"role": "user", "content": "测试主题"}])
    assert "测试主题" in result
    assert len(result) > 50


def test_mock_llm_with_key(isolated_config):
    """有 API key 时非 mock"""
    isolated_config.set("llm.api_key", "sk-test")
    isolated_config.set("llm.provider", "deepseek")
    client = LLMClient()
    assert client.is_mock is False
