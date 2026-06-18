import platform
import time
from datetime import datetime
from pathlib import Path

import pyautogui

from window_manager import activate_window, get_window_rect
from image_recognition import find_and_click, take_screenshot

IS_WINDOWS = platform.system() == "Windows"

SCREENSHOT_DIR = Path(__file__).parent.parent / "错误截图"

# 各步骤操作延迟（秒）
OP_DELAY_MIN = 1.0
OP_DELAY_MAX = 3.0

import random


def _sleep():
    time.sleep(random.uniform(OP_DELAY_MIN, OP_DELAY_MAX))


def _error_shot(hwnd: int, step: str):
    rect = get_window_rect(hwnd)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = str(SCREENSHOT_DIR / f"error_{ts}_{step}.png")
    take_screenshot(rect, path)


def execute_publish(task: dict) -> dict:
    """
    执行单条发布任务。
    task: {alias, images, caption, hwnd}
    返回: {success: bool, reason: str}
    """
    hwnd = task.get("hwnd")
    alias = task.get("alias", "?")
    images: list[str] = task.get("images", [])
    caption: str = task.get("caption", "")

    # Mock 模式（Mac 开发）
    if not IS_WINDOWS:
        print(f"[Mock] 发布任务: {alias} | 图片数: {len(images)} | 文案: {caption[:20]}")
        time.sleep(1.5)
        return {"success": True, "reason": ""}

    # ── Step 1: 激活窗口 ──────────────────────────────────
    if not activate_window(hwnd):
        return {"success": False, "reason": "窗口激活失败"}
    _sleep()

    rect = get_window_rect(hwnd)

    # ── Step 2: 点击朋友圈入口 ────────────────────────────
    if not find_and_click("moments_btn.png", rect, timeout=6):
        _error_shot(hwnd, "moments_btn")
        return {"success": False, "reason": "找不到朋友圈按钮"}
    _sleep()

    # ── Step 3: 点击相机图标 ──────────────────────────────
    if not find_and_click("camera_btn.png", rect, timeout=6):
        _error_shot(hwnd, "camera_btn")
        return {"success": False, "reason": "找不到相机图标"}
    _sleep()

    # ── Step 4: 点击从相册选择 ────────────────────────────
    if not find_and_click("album_btn.png", rect, timeout=6):
        _error_shot(hwnd, "album_btn")
        return {"success": False, "reason": "找不到相册选择"}
    _sleep()

    # ── Step 5: 文件选择对话框 ────────────────────────────
    if not _select_images_dialog(images):
        _error_shot(hwnd, "file_dialog")
        return {"success": False, "reason": "图片选择失败"}
    time.sleep(2.5)  # 等待图片加载

    # ── Step 6: 粘贴文案 ─────────────────────────────────
    if not _paste_caption(caption):
        return {"success": False, "reason": "文案输入失败"}
    _sleep()

    # ── Step 7: 点击发表 ──────────────────────────────────
    if not find_and_click("post_btn.png", rect, timeout=10):
        _error_shot(hwnd, "post_btn")
        return {"success": False, "reason": "找不到发表按钮（可能发表按钮为灰色）"}

    time.sleep(2.0)  # 等待发表完成
    return {"success": True, "reason": ""}


def _select_images_dialog(image_paths: list[str]) -> bool:
    """等待微信弹出的文件选择对话框，用 WM_SETTEXT 直接写入路径后确认。仅 Windows 有效。"""
    if not IS_WINDOWS:
        return True
    import ctypes

    # 用 class 名匹配比标题更可靠，#32770 是 Windows 标准文件对话框
    deadline = time.time() + 8
    dialog_hwnd = 0
    while time.time() < deadline:
        dialog_hwnd = ctypes.windll.user32.FindWindowW("#32770", None)
        if dialog_hwnd:
            break
        time.sleep(0.3)

    if not dialog_hwnd:
        return False

    # 多图用双引号空格分隔，单图直接路径
    path_str = " ".join(f'"{p}"' for p in image_paths) if len(image_paths) > 1 else image_paths[0]

    # 文件名输入框层级：ComboBoxEx32 > ComboBox > Edit，找不到则直接找 Edit
    combo_ex = ctypes.windll.user32.FindWindowExW(dialog_hwnd, None, "ComboBoxEx32", None)
    combo = ctypes.windll.user32.FindWindowExW(combo_ex, None, "ComboBox", None) if combo_ex else 0
    edit = ctypes.windll.user32.FindWindowExW(combo, None, "Edit", None) if combo else 0
    if not edit:
        edit = ctypes.windll.user32.FindWindowExW(dialog_hwnd, None, "Edit", None)
    if not edit:
        return False

    WM_SETTEXT = 0x000C
    ctypes.windll.user32.SendMessageW(edit, WM_SETTEXT, 0, path_str)
    time.sleep(0.2)
    ctypes.windll.user32.SetForegroundWindow(dialog_hwnd)
    time.sleep(0.1)
    pyautogui.press("enter")
    return True


def _paste_caption(caption: str) -> bool:
    """用剪贴板粘贴文案，避免中文输入法问题。"""
    try:
        pyperclip.copy(caption)
        time.sleep(0.2)
        pyautogui.hotkey("ctrl", "v")
        return True
    except Exception as e:
        print(f"[Publisher] 文案粘贴失败: {e}")
        return False
