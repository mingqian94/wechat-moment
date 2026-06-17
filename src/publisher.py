import platform
import time
from datetime import datetime
from pathlib import Path

import pyautogui
import pyperclip

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
    """等待文件选择对话框出现，输入图片路径后确认。"""
    import ctypes
    # 等待系统文件对话框
    deadline = time.time() + 8
    dialog_hwnd = 0
    while time.time() < deadline:
        # 查找常见文件选择对话框标题
        for title in ["打开", "Open", "选择文件"]:
            hwnd = ctypes.windll.user32.FindWindowW(None, title)
            if hwnd:
                dialog_hwnd = hwnd
                break
        if dialog_hwnd:
            break
        time.sleep(0.5)

    if not dialog_hwnd:
        return False

    # 构造多文件路径字符串（双引号空格分隔）
    path_str = " ".join(f'"{p}"' for p in image_paths)

    # 找到文件名输入框（Edit1）并填入路径
    edit_hwnd = ctypes.windll.user32.FindWindowExW(dialog_hwnd, None, "Edit", None)
    if not edit_hwnd:
        return False

    pyperclip.copy(path_str)
    ctypes.windll.user32.SetForegroundWindow(dialog_hwnd)
    time.sleep(0.3)
    pyautogui.hotkey("ctrl", "a")
    pyautogui.hotkey("ctrl", "v")
    time.sleep(0.3)
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
