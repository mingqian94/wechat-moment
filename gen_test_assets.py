"""生成测试素材：3张图片 + 1个短视频"""
from PIL import Image, ImageDraw, ImageFont
import cv2
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

# 生成1个5秒的测试视频（1080x1080）
video_path = "test_video/test_clip.mp4"
fourcc = cv2.VideoWriter_fourcc(*'mp4v')
fps = 30
duration = 5
vw, vh = 1080, 1080
out = cv2.VideoWriter(video_path, fourcc, fps, (vw, vh))

for frame_idx in range(fps * duration):
    img = np.zeros((vh, vw, 3), dtype=np.uint8)
    t = frame_idx / (fps * duration)

    # 渐变背景
    for y in range(vh):
        ratio = y / vh
        r = int(255 * (1 - ratio) + 100 * ratio)
        g = int(150 * (1 - ratio) + 180 * ratio)
        b = int(100 * (1 - ratio) + 255 * ratio)
        img[y, :] = [b, g, r]

    # 移动的圆形
    cx = int(vw / 2 + 200 * np.sin(t * 2 * np.pi))
    cy = int(vh / 2 + 100 * np.cos(t * 2 * np.pi))
    cv2.circle(img, (cx, cy), 100, (255, 255, 255), -1)

    # 文字
    text = f"测试视频 {int(t*5)+1}s"
    cv2.putText(img, text, (vw//2 - 200, vh//2 + 180),
                cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 3)

    out.write(img)

out.release()
print(f"已生成: {video_path} (5秒, 1080x1080, 30fps)")
