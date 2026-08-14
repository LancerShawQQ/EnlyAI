"""生成 EnlyAI 启动器图标

设计理念：
- 圆角方形背景，Apple 风格渐变（深蓝→紫色）
- 中央是声波+话筒的组合图案，体现 AI 语音/播客功能
- 简洁现代，高对比度
"""
from PIL import Image, ImageDraw, ImageFont
import math

def create_icon(size=256):
    """生成图标"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 圆角方形背景渐变（深蓝→紫色，Apple 风格）
    radius = int(size * 0.22)
    # 绘制圆角方形
    bbox = [0, 0, size - 1, size - 1]
    draw.rounded_rectangle(bbox, radius=radius, fill=(30, 30, 60, 0))

    # 手动渐变填充
    for y in range(size):
        ratio = y / size
        # 深蓝 (30, 60, 160) → 紫色 (90, 30, 150)
        r = int(30 + (90 - 30) * ratio)
        g = int(60 + (30 - 60) * ratio)
        b = int(160 + (150 - 160) * ratio)
        # 只在圆角方形范围内绘制
        for x in range(size):
            # 检查是否在圆角方形内
            if _in_rounded_rect(x, y, size, radius):
                img.putpixel((x, y), (r, g, b, 255))

    draw = ImageDraw.Draw(img)

    # 绘制声波柱（中央，对称分布）
    cx, cy = size // 2, size // 2
    bar_count = 5
    bar_width = max(2, size // 40)
    bar_gap = max(3, size // 35)
    total_width = bar_count * bar_width + (bar_count - 1) * bar_gap
    start_x = cx - total_width // 2

    # 声波柱高度模式（中间高，两边低，模拟声波）
    heights = [0.3, 0.6, 1.0, 0.6, 0.3]
    max_height = int(size * 0.35)

    for i in range(bar_count):
        h = int(max_height * heights[i])
        x = start_x + i * (bar_width + bar_gap)
        y1 = cy - h // 2
        y2 = cy + h // 2
        # 圆角柱
        draw.rounded_rectangle(
            [x, y1, x + bar_width - 1, y2],
            radius=max(1, bar_width // 2),
            fill=(255, 255, 255, 240),
        )

    # 话筒底座（声波下方的小圆点）
    dot_radius = max(2, size // 50)
    dot_y = cy + max_height // 2 + dot_radius * 3
    draw.ellipse(
        [cx - dot_radius, dot_y - dot_radius, cx + dot_radius, dot_y + dot_radius],
        fill=(255, 255, 255, 200),
    )
    # 话筒支架（U形弧线）
    arc_radius = int(size * 0.08)
    arc_bbox = [cx - arc_radius, cy - arc_radius + max_height // 4,
                cx + arc_radius, cy + arc_radius + max_height // 4]
    draw.arc(arc_bbox, start=0, end=180, fill=(255, 255, 255, 180), width=max(2, size // 60))

    return img


def _in_rounded_rect(x, y, size, radius):
    """判断点是否在圆角方形内"""
    # 四个角的圆心
    corners = [
        (radius, radius),  # 左上
        (size - 1 - radius, radius),  # 右上
        (radius, size - 1 - radius),  # 左下
        (size - 1 - radius, size - 1 - radius),  # 右下
    ]
    # 如果在中心矩形区域，直接 True
    if radius <= x <= size - 1 - radius or radius <= y <= size - 1 - radius:
        return True
    # 检查是否在四个角的圆内
    for cx, cy in corners:
        dist = math.sqrt((x - cx) ** 2 + (y - cy) ** 2)
        if dist <= radius:
            return True
    return False


if __name__ == "__main__":
    # 生成多尺寸图标
    for sz in [256, 128, 64, 48, 32]:
        icon = create_icon(sz)
        icon.save(f"d:\\cursor_project\\koubo\\KrVoiceAI\\assets\\icon_{sz}.png")
        print(f"生成 icon_{sz}.png")

    # 生成 ico 文件（多尺寸）
    icon_256 = create_icon(256)
    icon_128 = create_icon(128)
    icon_64 = create_icon(64)
    icon_48 = create_icon(48)
    icon_32 = create_icon(32)
    icon_256.save(
        "d:\\cursor_project\\koubo\\KrVoiceAI\\assets\\enlyai_icon.ico",
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32)],
    )
    print("生成 enlyai_icon.ico")
