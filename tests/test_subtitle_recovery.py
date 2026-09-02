"""字幕行边界恢复测试（r8 P1：_recover_script_slice 多段场景静默失效）

覆盖 QA 交付的 5 个场景 + 单调游标/整段覆盖：
- A: TTS 完美按行切（含标点）
- B: TTS 合并多行为 1 段且丢标点（QA 实测 0% 的场景）
- C: TTS 按行切但丢标点
- D: TTS 多段、段内含标点、跨行
- E: TTS 某段被改写（回退 TTS 文本，自身标点边界仍安全）
- F: 重复短语 + 单调游标不错配
- G: r7 原始场景（单段覆盖全文，行间无标点）
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

from krvoiceai.core.base_module import JobContext
from krvoiceai.modules.subtitle_engine import SubtitleEngine

PUNCT_RE = re.compile(
    r"[\s\u3000，。！？!?；;、,\.：:·—…\"'‘’“”「」『』（）()\[\]【】<>《》]+"
)

SCRIPT = """大家好，欢迎来到英语学习课堂。
今天教你三招让孩子敢开口说英语。
第一招啊每天抽出十分钟陪孩子读。
第二招对着屏幕跟读模仿语音语调。
第三招及时鼓励孩子的每一次尝试。
现在点个关注试试看吧。"""

NO_PUNCT_SCRIPT = (
    "哈喽朋友们，我是英里AI外教\n今天我跟你们分享三个小妙招\n让孩子敢开口说英语啊\n"
    "第一招每天只要10分钟\n对着屏幕跟读模仿\n第二招重点来啦\n要像复读机一样重复\n"
    "第三招最关键是及时鼓励\n孩子敢开口就是最理想的结果\n现在就点个关注\n"
    "收藏起来坚持10天\n开口说英语就靠它了"
)


def _tokens(src: str) -> list[str]:
    """源文最小语义单元：按标点/换行切分（token 内不含标点空白）"""
    return [p for p in PUNCT_RE.split(src) if p]


def _norm(s: str) -> str:
    return PUNCT_RE.sub("", s)


def _seg_token_aligned(seg_text: str, tokens: list[str]) -> bool:
    """段必须是连续 token 的完整拼接（不允许落在 token 中间=词中切断）"""
    t = _norm(seg_text)
    if not t:
        return True
    for i in range(len(tokens)):
        acc = ""
        for j in range(i, len(tokens)):
            acc += tokens[j]
            if acc == t:
                return True
            if len(acc) >= len(t):
                break
    return False


def _run_engine(script: str, tts_segments, max_chars: int = 18) -> list[dict]:
    ctx = JobContext(job_id="test_sub_recovery", work_dir=Path("./workspace_data/tmp/test_sub_recovery"))
    ctx.script_text = script
    ctx.metadata["tts_timestamps"] = tts_segments
    total = max(s["end"] for s in tts_segments)
    ctx.audio_duration = total
    eng = SubtitleEngine(config={"get": lambda k, d=None: d})
    eng.setup()
    eng.max_chars = max_chars
    segs = eng._from_tts_timestamps(ctx)
    assert segs, "应产生字幕段"
    return segs


def _assert_boundary_safe(segs: list[dict], src: str):
    tokens = _tokens(src)
    bad = [s["text"] for s in segs if not _seg_token_aligned(s["text"], tokens)]
    assert not bad, f"存在词中切断的段: {bad}"
    # 全覆盖：所有段拼接后与源文归一化一致（不丢字不重字）
    joined = _norm("".join(s["text"] for s in segs))
    assert joined == _norm(src), f"字幕覆盖与源文不一致"


# ========== 场景 A：TTS 完美按行切（含标点） ==========

def test_scenario_a_perfect_lines():
    lines = [l for l in SCRIPT.split("\n") if l.strip()]
    ts = [
        {"text": l, "start": i * 2.0, "end": (i + 1) * 2.0}
        for i, l in enumerate(lines)
    ]
    segs = _run_engine(SCRIPT, ts)
    assert len(segs) == len(lines)
    for s, l in zip(segs, lines):
        assert s["text"] == l
    _assert_boundary_safe(segs, SCRIPT)


# ========== 场景 B：TTS 合并多行为 1 段且丢标点（QA 实测修复前 0%） ==========

def test_scenario_b_merged_no_punct():
    ts = [
        {"text": "大家好欢迎来到英语学习课堂今天教你三招让孩子敢开口说英语",
         "start": 0.0, "end": 4.0},
        {"text": "第一招啊每天抽出十分钟陪孩子读第二招对着屏幕跟读模仿语音语调"
                 "第三招及时鼓励孩子的每一次尝试现在点个关注试试看吧",
         "start": 4.0, "end": 16.0},
    ]
    segs = _run_engine(SCRIPT, ts, max_chars=40)
    # 恢复成功：段文本应含原文标点（说明走了源文恢复而非 TTS 原文）
    assert any("。" in s["text"] or "，" in s["text"] for s in segs), \
        "未恢复源文标点（回退到了丢标点的 TTS 文本）"
    _assert_boundary_safe(segs, SCRIPT)


# ========== 场景 C：TTS 按行切但丢标点 ==========

def test_scenario_c_lines_no_punct():
    lines = [l for l in SCRIPT.split("\n") if l.strip()]
    ts = [
        {"text": _norm(l), "start": i * 2.0, "end": (i + 1) * 2.0}
        for i, l in enumerate(lines)
    ]
    segs = _run_engine(SCRIPT, ts)
    assert len(segs) == len(lines)
    for s, l in zip(segs, lines):
        assert _norm(s["text"]) == _norm(l)
    _assert_boundary_safe(segs, SCRIPT)


# ========== 场景 D：多段、段内跨行、含标点 ==========

def test_scenario_d_multi_seg_with_punct():
    ts = [
        {"text": "大家好，欢迎来到英语学习课堂。今天教你三招", "start": 0.0, "end": 3.5},
        {"text": "让孩子敢开口说英语", "start": 3.5, "end": 5.0},
        {"text": "第一招啊每天抽出十分钟陪孩子读", "start": 5.0, "end": 8.0},
        {"text": "第二招对着屏幕跟读模仿语音语调", "start": 8.0, "end": 11.0},
        {"text": "第三招及时鼓励孩子的每一次尝试", "start": 11.0, "end": 14.0},
        {"text": "现在点个关注试试看吧", "start": 14.0, "end": 16.0},
    ]
    segs = _run_engine(SCRIPT, ts)
    _assert_boundary_safe(segs, SCRIPT)


# ========== 场景 E：某段被改写（回退 TTS 文本，边界仍安全） ==========

def test_scenario_e_rewritten_seg():
    ts = [
        {"text": "大家好欢迎来到英语学习课堂", "start": 0.0, "end": 2.0},
        # 改写段：加了连接词，源文恢复必然失败 → 回退 TTS 文本
        {"text": "接下来我要教你三招让孩子敢开口说英语", "start": 2.0, "end": 5.0},
        {"text": "第一招啊每天抽出十分钟陪孩子读", "start": 5.0, "end": 8.0},
        {"text": "第二招对着屏幕跟读模仿语音语调", "start": 8.0, "end": 11.0},
        {"text": "第三招及时鼓励孩子的每一次尝试", "start": 11.0, "end": 14.0},
        {"text": "现在点个关注试试看吧", "start": 14.0, "end": 16.0},
    ]
    segs = _run_engine(SCRIPT, ts)
    # 未改写段仍按源文行边界；改写段单独成段不炸
    assert len(segs) >= 5
    texts = [s["text"] for s in segs]
    assert any("接下来我要教你三招" in t for t in texts), "改写段应保留"
    # 源文可恢复部分必须边界安全（按源文 token 检查可恢复的段）
    tokens = _tokens(SCRIPT)
    aligned = [t for t in texts if _seg_token_aligned(t, tokens)]
    assert len(aligned) >= len(texts) - 2, "除改写段外全部应边界安全"


# ========== 场景 F：重复短语 + 单调游标 ==========

def test_scenario_f_repeated_phrase_monotonic():
    src = "坚持很重要\n每天坚持十分钟\n坚持就会看到效果\n最终你会感谢坚持的自己"
    ts = [
        {"text": "坚持很重要", "start": 0.0, "end": 1.0},
        {"text": "每天坚持十分钟", "start": 1.0, "end": 2.5},
        {"text": "坚持就会看到效果", "start": 2.5, "end": 4.0},
        {"text": "最终你会感谢坚持的自己", "start": 4.0, "end": 6.0},
    ]
    segs = _run_engine(src, ts)
    # 相邻短行按 max_chars 合并是预期行为（4 行 → 2 段），
    # 关键是不错配重复短语、时间单调、边界安全
    starts = [s["start"] for s in segs]
    assert starts == sorted(starts), "时间戳应单调"
    assert starts[0] == 0.0 and segs[-1]["end"] == 6.0, "时间覆盖完整"
    _assert_boundary_safe(segs, src)
    # 归一化拼接等于源文（重复短语没有被错误复制/丢失）
    assert _norm("".join(s["text"] for s in segs)) == _norm(src)


# ========== 场景 G：r7 原始场景（单段覆盖全文、行间无标点） ==========

def test_scenario_g_single_segment_no_line_punct():
    joined = "".join(NO_PUNCT_SCRIPT.split("\n"))
    ts = [{"text": joined, "start": 0.0, "end": 21.74}]
    segs = _run_engine(NO_PUNCT_SCRIPT, ts)
    _assert_boundary_safe(segs, NO_PUNCT_SCRIPT)
    # QA 点名的切断词完整
    all_text = _norm("".join(s["text"] for s in segs))
    for word in ["三个小妙招", "重点来啦", "开口说英语"]:
        assert word in all_text


# ========== _recover_script_slice 静态方法单测 ==========

def test_recover_static_method():
    r = SubtitleEngine._recover_script_slice("你好，世界。\n第二行", "你好世界")
    assert r == "你好，世界"
    r2 = SubtitleEngine._recover_script_slice("你好，世界。\n第二行", "第二行")
    assert r2 == "第二行"
    r3 = SubtitleEngine._recover_script_slice("你好世界", "不存在的文本")
    assert r3 is None
