"""ASS 字幕样式器（对标剪映/CapCut 字幕效果）

将分句时间戳转为 ASS 格式字幕，支持：
- 8+ 样式预设（抖音爆款/新闻/科技蓝/古风金/卡点粉/极简白/霓虹/综艺花字）
- 5+ 入场动画（淡入/滑入/缩放/弹跳/打字机）
- 逐字高亮（karaoke 扫光效果）
- 描边/阴影/背景框/字间距
- 多位置（顶部/居中/底部）

ASS 格式优势：
- 原生支持 \\k/\\kf karaoke 标签（逐字高亮）
- 原生支持 \\t 动画变换（缩放/移动/淡入）
- 原生支持 \\fad 淡入淡出
- 原生支持 \\move 位移
- 比 SRT + force_style 表达力强 10 倍
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


# ===== 字幕样式预设（对标剪映热门字幕样式） =====
# 颜色格式：&HAABBGGRR（AA=透明度00不透明~FF透明，BBGGRR=蓝绿红）
SUBTITLE_STYLE_PRESETS: dict[str, dict[str, Any]] = {
    "minimal_white": {
        "label": "极简白字",
        "primary_color": "&H00FFFFFF",      # 白
        "outline_color": "&H00000000",      # 黑描边
        "shadow_color": "&H80000000",       # 半透黑阴影
        "outline": 2,
        "shadow": 1,
        "bold": True,
        "border_style": 1,                  # 1=描边+阴影
    },
    "douyin_hot": {
        "label": "抖音爆款（黄字黑边）",
        "primary_color": "&H0000FFFF",      # 黄 (BGR)
        "outline_color": "&H00000000",      # 黑
        "shadow_color": "&H80000000",
        "outline": 3,
        "shadow": 2,
        "bold": True,
        "border_style": 1,
    },
    "tech_blue": {
        "label": "科技蓝",
        "primary_color": "&H00FFCC44",      # 橙黄 (BGR: BB=44,GG=CC,RR=FF -> #FFCC44)
        "outline_color": "&H00882200",      # 深蓝边
        "shadow_color": "&H80000000",
        "outline": 2,
        "shadow": 1,
        "bold": True,
        "border_style": 1,
    },
    "classic_gold": {
        "label": "古风金",
        "primary_color": "&H0000D7FF",      # 金色 (BGR: #FFD700)
        "outline_color": "&H00002A4D",      # 深蓝
        "shadow_color": "&H80000000",
        "outline": 2,
        "shadow": 2,
        "bold": True,
        "border_style": 1,
    },
    "pop_pink": {
        "label": "卡点粉",
        "primary_color": "&H00FF6BB6",      # 粉 (BGR: #B66BFF)
        "outline_color": "&H00FFFFFF",      # 白边
        "shadow_color": "&H80FF6BB6",
        "outline": 2,
        "shadow": 1,
        "bold": True,
        "border_style": 1,
    },
    "news_red": {
        "label": "新闻红",
        "primary_color": "&H00FFFFFF",      # 白字
        "outline_color": "&H80000000",      # 半透黑背景
        "shadow_color": "&H00000000",
        "outline": 0,
        "shadow": 0,
        "bold": True,
        "border_style": 3,                  # 3=纯色背景框
    },
    "neon_glow": {
        "label": "霓虹发光",
        "primary_color": "&H00FF00FF",      # 霓虹紫
        "outline_color": "&H00FF00FF",      # 同色描边（发光感）
        "shadow_color": "&H00FF00FF",
        "outline": 4,
        "shadow": 3,
        "bold": True,
        "border_style": 1,
    },
    "variety_pop": {
        "label": "综艺花字",
        "primary_color": "&H00FFFFFF",      # 白
        "outline_color": "&H000000FF",      # 红描边
        "shadow_color": "&H80000000",
        "outline": 4,
        "shadow": 2,
        "bold": True,
        "border_style": 1,
    },
}

# ===== 动画预设（ASS 标签实现） =====
ANIMATION_PRESETS: dict[str, str] = {
    "none": "",
    # 淡入淡出：\fad(入场ms,出场ms)
    "fade": "\\fad(300,200)",
    # 滑入：\move(x1,y1,x2,y2) 从下方滑入
    "slide": "\\move(x,x+0,x,x-30,0,300)\\fad(300,200)",
    # 缩放：\fscx/\fscy + \t 从 80% 到 100%
    "zoom": "\\fscx80\\fscy80\\t(0,300,\\fscx100\\fscy100)\\fad(200,200)",
    # 弹跳：先放大到 120% 再回 100%
    "bounce": "\\fscx50\\fscy50\\t(0,150,\\fscx120\\fscy120)\\t(150,300,\\fscx100\\fscy100)\\fad(150,150)",
    # 打字机：逐字显示（通过 \alpha 控制，这里用快速淡入近似）
    "typewriter": "\\fad(100,100)",
}

# 位置映射（ASS Alignment：小键盘布局 1-9）
POSITION_ALIGNMENT: dict[str, int] = {
    "bottom_left": 1,
    "bottom_center": 2,
    "bottom_right": 3,
    "center_left": 4,
    "center": 5,
    "center_right": 6,
    "top_left": 7,
    "top_center": 8,
    "top_right": 9,
}


def _ass_time(seconds: float) -> str:
    """秒数转 ASS 时间格式 H:MM:SS.cc"""
    if seconds < 0:
        seconds = 0
    cs = round(seconds * 100)
    if cs >= 6000:  # 100cs = 1s
        cs = 0
        seconds += 1
    total_cs = int(round(seconds * 100))
    h = total_cs // 360000
    m = (total_cs % 360000) // 6000
    s = (total_cs % 6000) // 100
    c = total_cs % 100
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def _find_chinese_font() -> str:
    """查找系统中可用的中文字体名（跨平台）"""
    import os
    import platform

    # Windows 中文字体（系统自带）
    if platform.system() == "Windows":
        win_fonts = [
            ("C:/Windows/Fonts/msyh.ttc", "Microsoft YaHei"),        # 微软雅黑
            ("C:/Windows/Fonts/msyhbd.ttc", "Microsoft YaHei"),      # 微软雅黑粗体
            ("C:/Windows/Fonts/simhei.ttf", "SimHei"),               # 黑体
            ("C:/Windows/Fonts/simsun.ttc", "SimSun"),               # 宋体
        ]
        for path, name in win_fonts:
            if os.path.exists(path):
                return name

    # macOS 中文字体
    if platform.system() == "Darwin":
        mac_fonts = [
            ("/System/Library/Fonts/PingFang.ttc", "PingFang SC"),
            ("/Library/Fonts/Songti.ttc", "Songti SC"),
        ]
        for path, name in mac_fonts:
            if os.path.exists(path):
                return name

    # Linux 中文字体
    # 字体文件路径 -> ASS FontName 映射
    candidates = [
        ("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", "Noto Sans CJK SC"),
        ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", "Noto Sans CJK SC"),
        ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", "WenQuanYi Zen Hei"),
        ("/usr/share/fonts/truetype/wqy/wqy-microhei.ttc", "WenQuanYi Micro Hei"),
        ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "DejaVu Sans"),
    ]
    for path, name in candidates:
        if os.path.exists(path):
            return name
    return "Arial"


def segments_to_ass(
    segments: list[dict],
    preset: str = "minimal_white",
    animation: str = "fade",
    font_size: int = 28,
    font_name: str = "",
    position: str = "bottom",
    alignment: str = "center",
    margin_v: int = 80,
    karaoke: bool = False,
    bold: bool = True,
    italic: bool = False,
    outline_width: int | None = None,
    shadow_distance: int | None = None,
    letter_spacing: int = 0,
    line_spacing: float = 1.2,
    play_res_x: int = 1080,
    play_res_y: int = 1920,
    max_chars_per_line: int = 0,
) -> str:
    """将分句时间戳列表转为 ASS 字幕字符串

    Args:
        segments: [{"text": "...", "start": 0.0, "end": 2.5}, ...]
        preset: 样式预设名（见 SUBTITLE_STYLE_PRESETS）
        animation: 动画预设名（见 ANIMATION_PRESETS）
        font_size: 字号
        font_name: 字体名（空则自动检测）
        position: 垂直位置 top/center/bottom
        alignment: 水平对齐 left/center/right
        margin_v: 垂直边距
        karaoke: 是否启用逐字高亮
        bold/italic: 粗体/斜体
        outline_width/shadow_distance: 覆盖预设的描边/阴影
        letter_spacing: 字间距
        line_spacing: 行高倍数
        play_res_x/y: ASS PlayResX/Y（视频分辨率）
        max_chars_per_line: 每行最大字符数（0=自动按分辨率计算）。
            超过自动折行（插入 \\N），避免长句超出屏幕被裁剪。

    Returns:
        ASS 格式字幕字符串
    """
    style = SUBTITLE_STYLE_PRESETS.get(preset, SUBTITLE_STYLE_PRESETS["minimal_white"])

    # 合并参数
    final_font = font_name or _find_chinese_font()
    final_outline = outline_width if outline_width is not None else style["outline"]
    final_shadow = shadow_distance if shadow_distance is not None else style["shadow"]
    final_bold = -1 if bold else 0
    final_italic = -1 if italic else 0

    # 位置对齐
    pos_key = f"{position}_{alignment}"
    ass_align = POSITION_ALIGNMENT.get(pos_key, 2)

    # 行高（ASS 用像素，1.2 倍约等于 +20% 字号）
    ass_line_spacing = int(font_size * (line_spacing - 1.0))

    # 构建 ASS 头部
    header = f"""[Script Info]
Title: KrVoiceAI Subtitles
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 0
ScaledBorderAndShadow: yes
YCbCr Matrix: TV.709

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{final_font},{font_size},{style["primary_color"]},&H0000FFFF,{style["outline_color"]},{style["shadow_color"]},{final_bold},{final_italic},0,0,100,100,{letter_spacing},0,{style["border_style"]},{final_outline},{final_shadow},{ass_align},40,40,{margin_v},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    # 构建事件行
    events: list[str] = []
    anim_tag = ANIMATION_PRESETS.get(animation, "")

    # 自动计算每行最大字符数（基于分辨率和字号）
    # 竖屏 1080 宽，左右各留 80px 边距，可用宽度 920px
    # 中文字符宽度 ≈ 字号，每行字符数 ≈ (可用宽度 - 边距) / 字号
    if max_chars_per_line <= 0:
        usable_w = play_res_x - 160  # 左右各 80px 边距
        max_chars_per_line = max(8, int(usable_w / font_size))

    def _wrap_text(text: str) -> str:
        """长文本自动折行（按标点和字数），插入 \\N"""
        import re
        text = text.strip()
        if len(text) <= max_chars_per_line:
            return text

        # 按标点分段（句号/逗号/问号/感叹号/分号），保留标点
        parts = re.split(r'(?<=[，。？！；,?!;])', text)
        lines = []
        cur = ""
        for p in parts:
            if not p:
                continue
            if len(cur) + len(p) <= max_chars_per_line:
                cur += p
            else:
                if cur:
                    lines.append(cur)
                # 单段超长，按字数硬切
                while len(p) > max_chars_per_line:
                    lines.append(p[:max_chars_per_line])
                    p = p[max_chars_per_line:]
                cur = p
        if cur:
            lines.append(cur)
        return "\\N".join(lines)

    for seg in segments:
        start = _ass_time(seg["start"])
        end = _ass_time(seg["end"])
        # 先把原始换行转成 \\N，再自动折行
        raw_text = seg["text"].strip().replace("\n", "\\N")
        if karaoke:
            # 逐字高亮：优先用词级时间戳，否则按字数均分
            # 注意：karaoke 模式下逐字 \\kf 标签已含完整文本，不折行
            text = _build_karaoke_text(
                seg["text"], seg["start"], seg["end"],
                words=seg.get("words"),
            )
        else:
            # 应用自动折行（长句按标点和字数拆成多行，插入 \\N）
            wrapped = _wrap_text(seg["text"].strip())
            if anim_tag:
                # 应用动画标签（替换占位符）
                tag = anim_tag.replace("x,x", f"{play_res_x//2},{play_res_x//2}")
                text = "{" + tag + "}" + wrapped
            else:
                text = wrapped

        events.append(
            f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}"
        )

    return header + "\n".join(events) + "\n"


def _build_karaoke_text(
    text: str, start: float, end: float,
    words: list[dict] | None = None,
) -> str:
    """构建逐字高亮 ASS 文本

    将文本拆为单字，每个字用 \\kf<厘秒> 标签分配时长。
    PrimaryColour = 高亮后颜色，SecondaryColour = 高亮前颜色。

    Args:
        text: 字幕文本
        start: 开始时间（秒）
        end: 结束时间（秒）
        words: 词级时间戳（可选，来自 faster-whisper）。
               有词级时间戳时按真实时长分配 \\kf，精度远高于均分。
               格式: [{"text": "字", "start": 0.0, "end": 0.2}, ...]

    Returns:
        带 \\kf 标签的 ASS 文本
    """
    # ===== 有词级时间戳：按真实时长逐字高亮（最优精度）=====
    if words:
        # 把所有词的字符展开，每个字用其所属词的 start/end 区间
        # （faster-whisper 中文 word 通常已是单字或短词，直接用词时长）
        parts: list[str] = []
        for w in words:
            wt = w.get("text", "").strip()
            if not wt:
                continue
            ws = w.get("start", start)
            we = w.get("end", end)
            # 一个词可能是多字，按字数均分该词时长
            dur_cs = max(1, int(round((we - ws) * 100)))
            chars = [c for c in wt if c.strip()]
            if not chars:
                continue
            if len(chars) == 1:
                parts.append(f"{{\\kf{dur_cs}}}{chars[0]}")
            else:
                per_cs = max(1, dur_cs // len(chars))
                for i, ch in enumerate(chars):
                    if i == len(chars) - 1:
                        remaining = max(1, dur_cs - per_cs * (len(chars) - 1))
                        parts.append(f"{{\\kf{remaining}}}{ch}")
                    else:
                        parts.append(f"{{\\kf{per_cs}}}{ch}")
        if parts:
            return "".join(parts)
        # 词级时间戳为空，落入下面均分兜底

    # ===== 兜底：无词级时间戳，按字数均分 =====
    chars = [c for c in text.strip() if c.strip()]
    if not chars:
        return text

    total_dur_cs = int(round((end - start) * 100))  # 总时长（厘秒）
    per_char_cs = max(1, total_dur_cs // len(chars))

    parts = []
    for i, ch in enumerate(chars):
        # 最后一个字取剩余时长，避免 rounding 误差
        if i == len(chars) - 1:
            remaining = total_dur_cs - per_char_cs * (len(chars) - 1)
            dur = max(1, remaining)
        else:
            dur = per_char_cs
        parts.append(f"{{\\kf{dur}}}{ch}")

    return "".join(parts)


def write_ass_file(
    segments: list[dict],
    output_path: Path,
    **style_kwargs,
) -> Path:
    """生成 ASS 字幕文件

    Args:
        segments: 分句时间戳列表
        output_path: 输出路径（.ass）
        **style_kwargs: 传给 segments_to_ass 的样式参数

    Returns:
        输出路径
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    ass_content = segments_to_ass(segments, **style_kwargs)
    output_path.write_text(ass_content, encoding="utf-8")
    return output_path


def srt_to_ass(
    srt_path: Path,
    output_path: Path,
    preset: str = "minimal_white",
    animation: str = "fade",
    karaoke: bool = False,
    **style_kwargs,
) -> Path:
    """将现有 SRT 字幕转为 ASS 格式（应用样式）

    Args:
        srt_path: 输入 SRT 文件
        output_path: 输出 ASS 文件
        preset/animation/karaoke: 样式参数
        **style_kwargs: 其他样式参数

    Returns:
        输出路径
    """
    srt_path = Path(srt_path)
    segments = _parse_srt(srt_path)
    return write_ass_file(
        segments, output_path,
        preset=preset, animation=animation, karaoke=karaoke,
        **style_kwargs,
    )


def _parse_srt(srt_path: Path) -> list[dict]:
    """解析 SRT 文件为 segments 列表"""
    content = Path(srt_path).read_text(encoding="utf-8")
    segments: list[dict] = []
    blocks = content.strip().split("\n\n")
    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        # 时间行：00:00:01,000 --> 00:00:03,500
        time_line = lines[1]
        parts = time_line.split(" --> ")
        if len(parts) != 2:
            continue
        start = _srt_time_to_seconds(parts[0].strip())
        end = _srt_time_to_seconds(parts[1].strip())
        text = "\n".join(lines[2:]).strip()
        segments.append({"text": text, "start": start, "end": end})
    return segments


def _srt_time_to_seconds(time_str: str) -> float:
    """SRT 时间 HH:MM:SS,mmm 转秒"""
    time_str = time_str.replace(",", ".")
    h, m, s = time_str.split(":")
    return int(h) * 3600 + int(m) * 60 + float(s)
