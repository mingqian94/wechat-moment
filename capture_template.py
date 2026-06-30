# -*- coding: utf-8 -*-
"""
截图工具：在屏幕上拖选一个区域，保存为指定模板文件。
用法：python capture_template.py retry_btn
"""
import sys, os, time
sys.stdout.reconfigure(encoding="utf-8")

try:
    import tkinter as tk
    from PIL import ImageGrab, Image
except ImportError:
    print("缺少依赖：pip install pillow")
    sys.exit(1)

name = (sys.argv[1] if len(sys.argv) > 1 else "template").rstrip(".png")
out = os.path.join(os.path.dirname(__file__), "templates", f"{name}.png")

print(f"目标文件：{out}")
print("操作：屏幕上会出现半透明遮罩，左键拖选要截取的区域，松手即保存。")
print("按 Esc 取消。")

root = tk.Tk()
root.attributes("-fullscreen", True)
root.attributes("-alpha", 0.25)
root.attributes("-topmost", True)
root.config(cursor="crosshair", bg="black")

start = [0, 0]
rect_id = None
canvas = tk.Canvas(root, cursor="crosshair", bg="black", highlightthickness=0)
canvas.pack(fill="both", expand=True)

def on_press(e):
    start[0], start[1] = e.x, e.y

def on_drag(e):
    global rect_id
    if rect_id:
        canvas.delete(rect_id)
    rect_id = canvas.create_rectangle(start[0], start[1], e.x, e.y,
                                       outline="red", width=2)

def on_release(e):
    x1, y1 = min(start[0], e.x), min(start[1], e.y)
    x2, y2 = max(start[0], e.x), max(start[1], e.y)
    root.destroy()
    if x2 - x1 < 4 or y2 - y1 < 4:
        print("选区太小，取消。")
        return
    time.sleep(0.15)  # 等窗口消失
    img = ImageGrab.grab(bbox=(x1, y1, x2, y2))
    os.makedirs(os.path.dirname(out), exist_ok=True)
    img.save(out)
    print(f"已保存：{out}  ({img.width}×{img.height}px)")

canvas.bind("<ButtonPress-1>", on_press)
canvas.bind("<B1-Motion>", on_drag)
canvas.bind("<ButtonRelease-1>", on_release)
root.bind("<Escape>", lambda e: root.destroy())
root.mainloop()
