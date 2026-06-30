# -*- coding: utf-8 -*-
# single-account publish test - calls execute_publish directly, bypassing GUI
import sys, os
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from window_manager import find_wechat_windows, bind_aliases

windows = bind_aliases(find_wechat_windows())
if not windows:
    print("no WeChat windows found")
    sys.exit(1)

print(f"[OK] found {len(windows)} WeChat window(s):")
for w in windows:
    print(f"  {w['alias']} HWND={w['hwnd']} title={w['title']}")

# ── 素材 ─────────────────────────────────────────────────
base = os.path.dirname(__file__)
images = [
    os.path.join(base, "test_images_real", "real_landscape1.jpg"),
    os.path.join(base, "test_images_real", "real_landscape2.jpg"),
    os.path.join(base, "test_images_real", "real_animal1.jpg"),
]

# ── 逐个账号发布 ─────────────────────────────────────────
from publisher import execute_publish

for w in windows:
    alias, hwnd = w["alias"], w["hwnd"]
    task = {"alias": alias, "images": images, "caption": "测试发布", "hwnd": hwnd}
    print(f"\n[{alias}] HWND={hwnd} | {len(images)} images ...")
    result = execute_publish(task)
    if result.get("success"):
        print(f"[{alias}] SUCCESS")
    else:
        print(f"[{alias}] FAIL: {result.get('reason', 'unknown')}")
