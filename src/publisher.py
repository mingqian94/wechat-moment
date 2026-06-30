import os
import platform
import random
import time
from datetime import datetime
from pathlib import Path

import pyautogui
import pyperclip

from window_manager import activate_window, get_window_rect, find_moments_window, close_window
from image_recognition import find_and_click, find_template, take_screenshot

IS_WINDOWS = platform.system() == "Windows"

SCREENSHOT_DIR = Path(__file__).parent.parent / "错误截图"

# 各步骤操作延迟（秒），故意用非整数的范围，避免每次间隔都差不多长被识别成机器节奏
OP_DELAY_MIN = 0.85
OP_DELAY_MAX = 2.95


def _sleep():
    time.sleep(random.uniform(OP_DELAY_MIN, OP_DELAY_MAX))


def _error_shot(hwnd: int, step: str):
    rect = get_window_rect(hwnd)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = str(SCREENSHOT_DIR / f"error_{ts}_{step}.png")
    take_screenshot(rect, path)


def _wait_for_send_failure(hwnd: int, timeout: float, main_hwnd: int = None) -> bool:
    """点完发表后轮询检测"未发送"提示是否出现（图片/视频上传到这步才真正完成或失败，
    点完发表按钮那一刻只代表点击成功，不代表真的发出去了）。
    用"照片未发送"/"视频未发送"两种文案共有的"未发送"三个字做模板匹配——这三个字是纯文字
    渲染不会变，但图标本身会变色/动画，不能用图标做模板（踩过的坑）。
    timeout 内出现就是失败，返回 True；一直没出现，在没有更可靠的"成功"信号的情况下，
    只能视为成功，返回 False。
    main_hwnd: 主微信窗口，失败 toast 有时出现在主窗口而非朋友圈弹窗，同时扫两个。
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        rect = get_window_rect(hwnd)
        if find_template("send_failed_text.png", rect, hwnd=hwnd):
            return True
        # 同时检查主窗口（多账号风控时 toast 可能出现在主窗口）
        if main_hwnd and main_hwnd != hwnd:
            main_rect = get_window_rect(main_hwnd)
            if find_template("send_failed_text.png", main_rect, hwnd=main_hwnd):
                return True
        time.sleep(random.uniform(0.7, 1.3))
    return False


VIDEO_EXTS = {".mp4", ".mov"}
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


def _is_video(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in VIDEO_EXTS


def _is_image(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in IMAGE_EXTS


def _get_media_type(paths: list[str]) -> str:
    """判断素材类型：image / video / mixed"""
    has_img = any(_is_image(p) for p in paths)
    has_vid = any(_is_video(p) for p in paths)
    if has_vid and has_img:
        return "mixed"
    return "video" if has_vid else "image"


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

    # 判断素材类型
    media_type = _get_media_type(images)
    if media_type == "mixed":
        return {"success": False, "reason": "图片和视频不能混发，请分开创建任务"}

    # Mock 模式（Mac 开发）
    if not IS_WINDOWS:
        print(f"[Mock] 发布任务: {alias} | 类型: {media_type} | 文件数: {len(images)} | 文案: {caption[:20]}")
        time.sleep(random.uniform(1.15, 1.85))
        return {"success": True, "reason": ""}

    # ── Step 1: 激活窗口 ──────────────────────────────────
    if not activate_window(hwnd):
        return {"success": False, "reason": "窗口激活失败"}
    _sleep()

    rect = get_window_rect(hwnd)

    # ── Step 2: 点击朋友圈入口 ────────────────────────────
    if not find_and_click("moments_btn.png", rect, timeout=6, hwnd=hwnd):
        _error_shot(hwnd, "moments_btn")
        return {"success": False, "reason": "找不到朋友圈按钮"}
    _sleep()

    # 点击朋友圈后会弹出一个独立的新顶层窗口（不是主窗口的子区域），
    # 相机/发表按钮都在这个新窗口里，后续步骤必须切到这个 hwnd，否则永远找不到按钮
    moments_hwnd = find_moments_window(hwnd)
    if not moments_hwnd:
        _error_shot(hwnd, "moments_window")
        return {"success": False, "reason": "找不到朋友圈弹出窗口"}
    if not activate_window(moments_hwnd):
        return {"success": False, "reason": "朋友圈窗口激活失败"}
    moments_rect = get_window_rect(moments_hwnd)

    # ── Step 3: 点击相机图标 ──────────────────────────────
    if not find_and_click("camera_btn.png", moments_rect, timeout=6, hwnd=moments_hwnd):
        _error_shot(moments_hwnd, "camera_btn")
        return {"success": False, "reason": "找不到相机图标"}
    _sleep()

    # ── Step 4: 文件选择对话框 ────────────────────────────
    # 新版微信直接弹出文件管理器，没有"从相册选择"中间步骤
    # 老版微信需要先点"album_btn.png"，如果找不到则跳过
    album_clicked = find_and_click("album_btn.png", moments_rect, timeout=2, hwnd=moments_hwnd)
    if album_clicked:
        _sleep()

    if media_type == "video":
        if not _select_video_dialog(images):
            _error_shot(moments_hwnd, "file_dialog")
            return {"success": False, "reason": "视频选择失败"}
        # 视频需要本地转码+上传准备，按文件大小估算等待时间，避免转码未完成就点发表导致"视频未发送"
        size_mb = os.path.getsize(images[0]) / (1024 * 1024) if os.path.exists(images[0]) else 0
        base_wait = max(8.0, min(30.0, size_mb * 1.5))
        time.sleep(base_wait + random.uniform(-0.6, 0.9))
    else:
        if not _select_images_dialog(images):
            _error_shot(moments_hwnd, "file_dialog")
            return {"success": False, "reason": "图片选择失败"}
        # 等图片上传准备完成再点发表，否则会出现"照片未发送"——点击没点错，是点早了。
        # 按张数给足时间，张数越多本地处理越久，单张给 5 秒兜底。
        base_wait = max(5.0, 1.5 * len(images))
        time.sleep(base_wait + random.uniform(-0.4, 0.7))

    # ── Step 6: 粘贴文案 ─────────────────────────────────
    if not _paste_caption(caption):
        return {"success": False, "reason": "文案输入失败"}
    _sleep()

    # ── Step 7: 点击发表 ──────────────────────────────────
    moments_rect = get_window_rect(moments_hwnd)
    if not find_and_click("post_btn.png", moments_rect, timeout=10, hwnd=moments_hwnd):
        _error_shot(moments_hwnd, "post_btn")
        return {"success": False, "reason": "找不到发表按钮（可能发表按钮为灰色）"}

    time.sleep(random.uniform(1.7, 2.6))  # 先等一下，让"未发送"有机会出现

    # 点发表只代表点击成功，不代表真的发出去了——图片/视频上传完成（或失败）还要等一会儿。
    # 视频 20s，图片 20s（风控导致的失败信号可能延迟超过 8s，之前 8s 会漏检）。
    # 同时扫主窗口，防止 toast 出现在主窗口而非朋友圈弹窗。
    check_timeout = 20.0
    if _wait_for_send_failure(moments_hwnd, check_timeout, main_hwnd=hwnd):
        _error_shot(moments_hwnd, "send_failed_1st")
        # 出现"未发送"后等 3-6 秒，点击横幅触发重发
        if _retry_failed_send(moments_hwnd, main_hwnd=hwnd):
            # 重发按钮点到了，再等一轮确认是否成功
            if _wait_for_send_failure(moments_hwnd, check_timeout, main_hwnd=hwnd):
                _error_shot(moments_hwnd, "send_failed_retry")
                return {"success": False, "reason": "重发后仍失败（账号风控或网络问题）"}
            close_window(moments_hwnd)
            return {"success": True, "reason": ""}
        else:
            _error_shot(moments_hwnd, "send_failed")
            return {"success": False, "reason": "发送失败（未发送，重发按钮未找到）"}

    # 发布成功后把朋友圈弹窗关掉，避免残留挡住下一个账号的操作
    close_window(moments_hwnd)

    return {"success": True, "reason": ""}


def _retry_failed_send(moments_hwnd: int, main_hwnd: int = None) -> bool:
    """检测到"未发送"横幅后，等 3-6 秒点击横幅，再点「发表」触发重发。
    返回 True 表示成功点到了发表按钮；False 表示找不到，不重发。
    """
    time.sleep(random.uniform(3.0, 6.0))

    # 点击"未发送"横幅，微信会弹出包含「发表」按钮的重发对话框
    rect = get_window_rect(moments_hwnd)
    if not find_and_click("send_failed_text.png", rect, timeout=3, hwnd=moments_hwnd):
        if main_hwnd and main_hwnd != moments_hwnd:
            main_rect = get_window_rect(main_hwnd)
            find_and_click("send_failed_text.png", main_rect, timeout=3, hwnd=main_hwnd)
    time.sleep(random.uniform(0.8, 1.5))

    # 弹出的重发对话框与首次发表相同，直接复用 post_btn.png（「发表」绿色按钮）
    rect = get_window_rect(moments_hwnd)
    if find_and_click("post_btn.png", rect, timeout=4, hwnd=moments_hwnd):
        return True
    return False


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
        time.sleep(random.uniform(0.24, 0.37))

    if not dialog_hwnd:
        return False

    # 路径统一转反斜杠（tkinter askopenfilenames 返回正斜杠，Windows 文件对话框会报"文件名无效"）
    norm = [p.replace("/", "\\") for p in image_paths]
    # 多图用双引号空格分隔，单图直接路径
    path_str = " ".join(f'"{p}"' for p in norm) if len(norm) > 1 else norm[0]

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
    # 模拟真人选完文件后看一眼再确认，不要填完立刻回车
    time.sleep(random.uniform(2.1, 4.8))
    ctypes.windll.user32.SetForegroundWindow(dialog_hwnd)
    time.sleep(random.uniform(0.08, 0.18))
    pyautogui.press("enter")
    return True


def _select_video_dialog(video_paths: list[str]) -> bool:
    """
    等待微信弹出的文件选择对话框，选择视频文件。
    微信视频选择逻辑与图片类似，但一次只能选一个视频。
    仅 Windows 有效。
    """
    if not IS_WINDOWS:
        return True
    import ctypes

    # 微信限制一次只能发一个视频
    if len(video_paths) > 1:
        print(f"[Publisher] 警告：微信一次只能发一个视频，已取第一个: {video_paths[0]}")
    video_path = video_paths[0]

    # 用 class 名匹配比标题更可靠，#32770 是 Windows 标准文件对话框
    deadline = time.time() + 8
    dialog_hwnd = 0
    while time.time() < deadline:
        dialog_hwnd = ctypes.windll.user32.FindWindowW("#32770", None)
        if dialog_hwnd:
            break
        time.sleep(random.uniform(0.24, 0.37))

    if not dialog_hwnd:
        return False

    # 尝试切换到"视频"视图（部分微信版本需要）
    # 先尝试发送 Ctrl+2 切换到视频标签（如果文件管理器支持）
    ctypes.windll.user32.SetForegroundWindow(dialog_hwnd)
    time.sleep(random.uniform(0.15, 0.28))

    # 文件名输入框层级：ComboBoxEx32 > ComboBox > Edit，找不到则直接找 Edit
    combo_ex = ctypes.windll.user32.FindWindowExW(dialog_hwnd, None, "ComboBoxEx32", None)
    combo = ctypes.windll.user32.FindWindowExW(combo_ex, None, "ComboBox", None) if combo_ex else 0
    edit = ctypes.windll.user32.FindWindowExW(combo, None, "Edit", None) if combo else 0
    if not edit:
        edit = ctypes.windll.user32.FindWindowExW(dialog_hwnd, None, "Edit", None)
    if not edit:
        return False

    WM_SETTEXT = 0x000C
    ctypes.windll.user32.SendMessageW(edit, WM_SETTEXT, 0, video_path.replace("/", "\\"))
    # 模拟真人选完文件后看一眼再确认，不要填完立刻回车
    time.sleep(random.uniform(2.1, 4.8))
    ctypes.windll.user32.SetForegroundWindow(dialog_hwnd)
    time.sleep(random.uniform(0.08, 0.18))
    pyautogui.press("enter")
    return True


def _paste_caption(caption: str) -> bool:
    """用剪贴板粘贴文案，避免中文输入法问题。"""
    try:
        pyperclip.copy(caption)
        time.sleep(random.uniform(0.16, 0.34))
        pyautogui.hotkey("ctrl", "v")
        return True
    except Exception as e:
        print(f"[Publisher] 文案粘贴失败: {e}")
        return False
