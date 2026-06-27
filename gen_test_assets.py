"""生成测试素材：3张图片 + 1个短视频。

视频部分需要 `pip install imageio imageio-ffmpeg`（仅本脚本用，不是项目运行依赖）。
之前用 OpenCV 默认的 mp4v 编码出来是老式 MPEG-4 Part2（FMP4），不是真手机视频会用的 H.264，
微信的上传/转码管线可能根本不认；这里用 imageio-ffmpeg 自带的 ffmpeg 二进制编码成真正的 H.264，
跟真实视频更接近。
"""
from PIL import Image, ImageDraw, ImageFont
import numpy as np
import os

os.makedirs("test_images", exist_ok=True)
os.makedirs("test_video", exist_ok=True)

# 生成3张测试图片（1080x1080 朋友圈尺寸）
colors = [
    ((255, 152, 100), (255, 94, 98)),
    ((102, 126, 234), (118, 75, 162)),
    ((15, 155, 255), (30, 200, 180)),
]
titles = ["早安 🌅", "下午茶 ☕", "晚安 🌙"]
subtitles = [
    "今天也要元气满满哦！",
    "享受这片刻的宁静~",
    "明天又是新的一天 💪",
]

for i in range(3):
    w, h = 1080, 1080
    img = Image.new('RGB', (w, h))
    draw = ImageDraw.Draw(img)

    c1, c2 = colors[i]
    for y in range(h):
        ratio = y / h
        r = int(c1[0] * (1 - ratio) + c2[0] * ratio)
        g = int(c1[1] * (1 - ratio) + c2[1] * ratio)
        b = int(c1[2] * (1 - ratio) + c2[2] * ratio)
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    try:
        font_title = ImageFont.truetype("msyh.ttc", 120)
        font_sub = ImageFont.truetype("msyh.ttc", 50)
    except Exception:
        font_title = ImageFont.load_default(size=80)
        font_sub = ImageFont.load_default(size=40)

    draw.text((w//2, h//2 - 80), titles[i], fill="white", font=font_title, anchor="mm")
    draw.text((w//2, h//2 + 60), subtitles[i], fill=(255, 255, 255, 200), font=font_sub, anchor="mm")

    img.save(f"test_images/0{i+1}.jpg", quality=90)
    print(f"已生成: test_images/0{i+1}.jpg")

# 生成1个5秒的测试视频（1080x1080，真实 H.264 编码）
import imageio_ffmpeg as iio

video_path = "test_video/test_clip.mp4"
fps = 30
duration = 5
vw, vh = 1080, 1080

writer = iio.write_frames(
    video_path, (vw, vh), fps=fps, codec='libx264',
    output_params=['-pix_fmt', 'yuv420p'],
)
writer.send(None)

for frame_idx in range(fps * duration):
    img = np.zeros((vh, vw, 3), dtype=np.uint8)
    t = frame_idx / (fps * duration)

    # 渐变背景（按行跨步填色，避免逐行 Python 循环太慢）
    for y in range(0, vh, 4):
        ratio = y / vh
        r = int(255 * (1 - ratio) + 100 * ratio)
        g = int(150 * (1 - ratio) + 180 * ratio)
        b = int(100 * (1 - ratio) + 255 * ratio)
        img[y:y + 4, :] = [r, g, b]

    # 移动的圆形
    cx = int(vw / 2 + 200 * np.sin(t * 2 * np.pi))
    cy = int(vh / 2 + 100 * np.cos(t * 2 * np.pi))
    yy, xx = np.ogrid[:vh, :vw]
    mask = (xx - cx) ** 2 + (yy - cy) ** 2 <= 100 ** 2
    img[mask] = [255, 255, 255]

    writer.send(img)

writer.close()
print(f"已生成: {video_path} (5秒, ~1080x1080, 30fps, H.264)")
