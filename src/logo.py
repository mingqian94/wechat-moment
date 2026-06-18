"""
生成程序 Logo：神经网络简笔风格
返回 PIL Image，可直接用于 tkinter PhotoImage
"""
from PIL import Image, ImageDraw


def make_logo(size: int = 48, bg: tuple = (74, 124, 89), fg: tuple = (255, 255, 255)) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size

    # 圆形背景
    d.ellipse([0, 0, s - 1, s - 1], fill=bg)

    # 节点坐标（归一化后 × size）
    nodes = [
        (0.50, 0.22),  # 顶部中心
        (0.22, 0.55),  # 左中
        (0.78, 0.55),  # 右中
        (0.38, 0.80),  # 左下
        (0.62, 0.80),  # 右下
    ]
    pts = [(int(x * s), int(y * s)) for x, y in nodes]

    # 连线
    edges = [(0, 1), (0, 2), (1, 2), (1, 3), (2, 4), (3, 4), (1, 4), (2, 3)]
    lw = max(1, s // 24)
    for a, b in edges:
        d.line([pts[a], pts[b]], fill=(*fg, 180), width=lw)

    # 节点圆点
    r = max(2, s // 12)
    for x, y in pts:
        d.ellipse([x - r, y - r, x + r, y + r], fill=fg)

    return img


def get_tkimage(size: int = 48):
    """返回 tkinter 可用的 PhotoImage。2x 超采样后缩回 size，边缘更平滑。"""
    import io
    import base64
    import tkinter as tk
    # 2x 渲染再缩小，抗锯齿效果更好
    img = make_logo(size * 2)
    img = img.resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue())
    return tk.PhotoImage(data=b64)
