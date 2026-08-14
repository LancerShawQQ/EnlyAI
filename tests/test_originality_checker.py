"""文案查重 + 风控模块测试"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from krvoiceai.core.base_module import JobContext, ModuleStatus
from krvoiceai.core.text_similarity import (
    hamming_distance,
    is_likely_duplicate,
    normalize_text,
    simhash,
    simhash_similarity,
)
from krvoiceai.modules.originality_checker import OriginalityChecker


# ============ 夹具 ============

@pytest.fixture
def checker(isolated_config, job_work_dir):
    """默认配置的查重器（违禁词库用项目内置的）

    注：注入非 mock 的 llm，以测试完整查重链路（SimHash + 违禁词 + LLM）。
    mock llm 在产品逻辑里会跳过查重（避免固定模板误伤），不利于单元测试。
    """
    isolated_config.set(
        "originality.banned_words_file",
        str(Path(__file__).parent.parent / "config" / "banned_words.txt"),
    )
    isolated_config.set("originality.llm_risk_check", False)  # 默认关 LLM，单独测
    # 注入一个 is_mock=False 的假 LLM，绕过 mock 跳过逻辑
    fake_llm = MagicMock()
    fake_llm.is_mock = False
    fake_llm.chat.return_value = '{"level": "low", "reason": "ok", "risks": []}'
    c = OriginalityChecker(llm_client=fake_llm)
    c.setup()
    return c


@pytest.fixture
def clean_history(isolated_config, job_work_dir):
    """确保历史库为空"""
    db = Path(isolated_config.get("originality.history_db"))
    if db.exists():
        db.unlink()


# ============ SimHash 工具测试 ============

def test_simhash_stable():
    """SimHash 对相同文本稳定"""
    a = simhash("今天天气真好，适合出去玩")
    b = simhash("今天天气真好，适合出去玩")
    assert a == b


def test_simhash_similar_text_close():
    """相似文本的 SimHash 海明距离小

    注：短文本对单字差异较敏感，一字之差相似度约 0.80-0.85（仍远高于无关文本）
    """
    a = simhash("我总结了三个高效学习的方法，帮你事半功倍")
    b = simhash("我总结了三个高效学习的方法，让你事半功倍")
    # 仅一字之差，相似度应明显高于无关文本
    assert simhash_similarity(a, b) > 0.80


def test_simhash_different_text_far():
    """完全不同文本的 SimHash 海明距离大"""
    a = simhash("今天天气真好适合出去玩")
    b = simhash("量子力学是研究微观粒子运动规律的物理学分支")
    assert simhash_similarity(a, b) < 0.7
    assert is_likely_duplicate(a, b, threshold=0.85) is False


def test_normalize_text():
    """文本归一化：去空白标点"""
    assert normalize_text("Hello， 世界！") == "hello世界"
    assert normalize_text("  a b  c  ") == "abc"


def test_hamming_distance():
    """海明距离"""
    assert hamming_distance(0b1010, 0b0101) == 4
    assert hamming_distance(0b1111, 0b1111) == 0


# ============ 违禁词扫描测试 ============

def test_banned_words_loaded(checker):
    """违禁词库正确加载"""
    assert len(checker._banned_words) > 0
    assert "第一" in checker._banned_words
    assert "国家级" in checker._banned_words


def test_banned_words_scan_hit(checker, job_work_dir):
    """命中违禁词 → 失败"""
    ctx = JobContext(
        work_dir=job_work_dir,
        script_text="我们的产品是全国第一品牌，绝对包赚不赔！",
    )
    ctx.ensure_work_dir()
    result = checker.execute(ctx)

    assert result.success is False
    assert "违禁词" in result.error
    hits = result.data["banned_words"]
    assert "第一" in hits
    assert "包赚" in hits


def test_banned_words_scan_clean(checker, job_work_dir, clean_history):
    """无违禁词 → 通过"""
    ctx = JobContext(
        work_dir=job_work_dir,
        script_text="今天分享一个关于时间管理的小技巧，希望对你有帮助。",
    )
    ctx.ensure_work_dir()
    result = checker.execute(ctx)

    assert result.success is True
    assert result.data.get("status") == "passed"
    assert "simhash" in result.data


# ============ 查重 / 历史库测试 ============

def test_duplicate_detection(checker, job_work_dir, clean_history):
    """与历史文案高度相似 → 失败"""
    text1 = "我总结了三个高效学习的方法，帮你事半功倍，主动回忆、间隔重复、费曼技巧。"
    text2 = "我总结了三个高效学习的方法，让你事半功倍，主动回忆、间隔重复、费曼技巧。"

    # 先写入历史
    ctx1 = JobContext(work_dir=job_work_dir, script_text=text1)
    ctx1.ensure_work_dir()
    checker.execute(ctx1)

    # 再查近似文案
    ctx2 = JobContext(work_dir=job_work_dir, script_text=text2)
    ctx2.ensure_work_dir()
    result = checker.execute(ctx2)

    assert result.success is False
    assert "相似度过高" in result.error
    assert "duplicate" in result.data


def test_history_written_on_pass(checker, job_work_dir, clean_history):
    """通过后写入历史库"""
    ctx = JobContext(
        work_dir=job_work_dir,
        script_text="完全原创的一段全新文案内容，关于编程入门。",
        job_id="job_test_001",
    )
    ctx.ensure_work_dir()
    checker.execute(ctx)

    db = Path(checker.history_db)
    assert db.exists()
    import sqlite3
    conn = sqlite3.connect(str(db))
    row = conn.execute(
        "SELECT job_id, preview FROM history WHERE job_id=?", ("job_test_001",)
    ).fetchone()
    conn.close()
    assert row is not None
    assert "编程入门" in row[1]


# ============ 跳过 / 降级测试 ============

def test_disabled_skips(isolated_config, job_work_dir):
    """enabled=false → 跳过"""
    isolated_config.set("originality.enabled", False)
    c = OriginalityChecker()
    c.setup()
    ctx = JobContext(
        work_dir=job_work_dir,
        script_text="全国第一！包赚不赔！",  # 即使有违禁词也跳过
    )
    ctx.ensure_work_dir()
    result = c.execute(ctx)
    assert result.success is True
    assert result.data.get("skipped") is True


def test_empty_script_fails(checker, job_work_dir):
    """空文案 → 失败"""
    ctx = JobContext(work_dir=job_work_dir, script_text="")
    ctx.ensure_work_dir()
    result = checker.execute(ctx)
    assert result.success is False
    assert "无文案" in result.error


def test_no_banned_file_no_crash(isolated_config, job_work_dir):
    """违禁词库文件不存在不报错"""
    isolated_config.set("originality.banned_words_file", "/nonexistent/words.txt")
    c = OriginalityChecker()
    c.setup()
    assert c._banned_words == []
    # 仍能正常运行（仅查重 + LLM）
    ctx = JobContext(
        work_dir=job_work_dir,
        script_text="一段普通文案。",
    )
    ctx.ensure_work_dir()
    result = c.execute(ctx)
    assert result.success is True


# ============ LLM 风控测试 ============

def test_llm_risk_high_blocks(isolated_config, job_work_dir, clean_history):
    """LLM 判定 high → 失败"""
    mock_llm = MagicMock()
    mock_llm.is_mock = False
    mock_llm.chat.return_value = json.dumps({
        "level": "high",
        "reason": "含虚假宣传",
        "risks": ["日入过万"],
    })
    isolated_config.set("originality.llm_risk_check", True)
    c = OriginalityChecker(llm_client=mock_llm)
    c.setup()

    ctx = JobContext(
        work_dir=job_work_dir,
        script_text="一段普通但需要 LLM 判断的文案。",
    )
    ctx.ensure_work_dir()
    result = c.execute(ctx)
    assert result.success is False
    assert "LLM 风控" in result.error
    assert result.data["llm_risk"]["level"] == "high"


def test_llm_risk_low_passes(isolated_config, job_work_dir, clean_history):
    """LLM 判定 low → 通过"""
    mock_llm = MagicMock()
    mock_llm.is_mock = False
    mock_llm.chat.return_value = json.dumps({
        "level": "low", "reason": "无风险", "risks": [],
    })
    isolated_config.set("originality.llm_risk_check", True)
    c = OriginalityChecker(llm_client=mock_llm)
    c.setup()

    ctx = JobContext(
        work_dir=job_work_dir,
        script_text="一段安全的普通文案内容。",
    )
    ctx.ensure_work_dir()
    result = c.execute(ctx)
    assert result.success is True
    assert result.data["llm_risk"]["level"] == "low"


def test_llm_risk_skipped_when_mock(isolated_config, job_work_dir, clean_history):
    """LLM mock 模式 → 跳过 LLM 风控"""
    mock_llm = MagicMock()
    mock_llm.is_mock = True  # 关键：mock 模式
    mock_llm.chat.return_value = '{"level": "high"}'  # 即使返回 high 也不应触发
    isolated_config.set("originality.llm_risk_check", True)
    c = OriginalityChecker(llm_client=mock_llm)
    c.setup()

    ctx = JobContext(
        work_dir=job_work_dir,
        script_text="一段安全文案。",
    )
    ctx.ensure_work_dir()
    result = c.execute(ctx)
    # mock 模式跳过 LLM，应通过
    assert result.success is True
    assert "llm_risk" not in result.data


def test_llm_risk_parse_fallback(isolated_config, job_work_dir, clean_history):
    """LLM 返回非 JSON → 降级为 low"""
    mock_llm = MagicMock()
    mock_llm.is_mock = False
    mock_llm.chat.return_value = "这不是JSON，是一段普通文字"
    isolated_config.set("originality.llm_risk_check", True)
    c = OriginalityChecker(llm_client=mock_llm)
    c.setup()

    ctx = JobContext(
        work_dir=job_work_dir, script_text="普通文案。"
    )
    ctx.ensure_work_dir()
    result = c.execute(ctx)
    assert result.success is True
    assert result.data["llm_risk"]["level"] == "low"
