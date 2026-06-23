import platform
import time
from pathlib import Path

import pyautogui
import cv2
import numpy as np
from PIL import ImageGrab

IS_WINDOWS = platform.system() == "Windows"

TEMPLATES_DIR = Path(__file__).parent.parent / "templates"
MATCH_THRESHOLD = 0.80   # OpenCV 相似度阈值（0-1）
SCALES = [1.0, 0.9, 0.85, 0.8, 1.1, 1.15]  # 多尺度容错

_template_cache: dict[str, np.ndarray | None] = {}


def _load_template(name: str) -> np.ndarray | None:
    if name not in _template_cache:
        path = TEMPLATES_DIR / name
        _template_cache[name] = cv2.imread(str(path), cv2.IMREAD_COLOR) if path.exists() else None
        if _template_cache[name] is None:
            print(f"[ImageRecog] 模板文件不存在: {name}")
    return _template_cache[name]


def reload_templates():
    _template_cache.clear()


def _grab_region(x: int, y: int, w: int, h: int, hwnd: int = None) -> np.ndarray:
    """截取区域，支持通过 hwnd 直接截取窗口内容（无视遮挡）"""
    if hwnd and IS_WINDOWS:
        try:
            import win32gui
            import win32ui
            import win32con
            from ctypes import windll

            # 获取窗口 DC
            hwndDC = win32gui.GetWindowDC(hwnd)
            mfcDC = win32ui.CreateDCFromHandle(hwndDC)
            saveDC = mfcDC.CreateCompatibleDC()

            saveBitMap = win32ui.CreateBitmap()
            saveBitMap.CreateCompatibleBitmap(mfcDC, w, h)
            saveDC.SelectObject(saveBitMap)

            # 使用 PrintWindow 截取窗口内容
            windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 2)

            # 转换为 numpy
            bmpinfo = saveBitMap.GetInfo()
            bmpstr = saveBitMap.GetBitmapBits(True)
            img = np.frombuffer(bmpstr, dtype=np.uint8)
            img.shape = (h, w, 4)
            img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)

            # 清理
            win32gui.DeleteObject(saveBitMap.GetHandle())
            saveDC.DeleteDC()
            mfcDC.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwndDC)

            return img
        except Exception as e:
            print(f"[ImageRecog] 窗口截图失败，回退到屏幕截图: {e}")

    # 回退：屏幕截图
    screenshot = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    return cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)


def find_template(template_name: str, region: tuple[int, int, int, int] | None = None,
                  hwnd: int = None
                  ) -> tuple[int, int] | None:
    """
    在 region（x, y, w, h）内查找模板图，返回匹配中心点的屏幕坐标 (abs_x, abs_y)。
    region=None 则全屏搜索。
    hwnd: 指定窗口句柄，可无视遮挡直接截取窗口内容
    """
    tpl = _load_template(template_name)
    if tpl is None:
        return None

    if region:
        rx, ry, rw, rh = region
    else:
        screen_w, screen_h = pyautogui.size()
        rx, ry, rw, rh = 0, 0, screen_w, screen_h

    if IS_WINDOWS:
        screen = _grab_region(rx, ry, rw, rh, hwnd=hwnd)
    else:
        # Mac 开发模式：直接用 ImageGrab
        screenshot = ImageGrab.grab(bbox=(rx, ry, rx + rw, ry + rh))
        screen = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

    th, tw = tpl.shape[:2]

    for scale in SCALES:
        if scale != 1.0:
            new_w = int(tw * scale)
            new_h = int(th * scale)
            if new_w < 4 or new_h < 4:
                continue
            tpl_scaled = cv2.resize(tpl, (new_w, new_h))
        else:
            tpl_scaled = tpl

        if screen.shape[0] < tpl_scaled.shape[0] or screen.shape[1] < tpl_scaled.shape[1]:
            continue

        result = cv2.matchTemplate(screen, tpl_scaled, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val >= MATCH_THRESHOLD:
            # 转换为屏幕绝对坐标（模板中心）
            cx = rx + max_loc[0] + tpl_scaled.shape[1] // 2
            cy = ry + max_loc[1] + tpl_scaled.shape[0] // 2
            return cx, cy

    return None


def find_and_click(template_name: str, region: tuple[int, int, int, int] | None = None,
                   timeout: float = 5.0, hwnd: int = None) -> bool:
    """循环查找模板并点击，超时返回 False。hwnd 用于直接截取窗口内容。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        pos = find_template(template_name, region, hwnd=hwnd)
        if pos:
            if IS_WINDOWS:
                pyautogui.click(pos[0], pos[1])
            else:
                print(f"[Mock] 点击 {template_name} at {pos}")
            time.sleep(0.3)
            return True
        time.sleep(0.3)
    return False


def take_screenshot(region: tuple[int, int, int, int] | None, save_path: str):
    """截图保存，用于错误记录。"""
    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    if region:
        rx, ry, rw, rh = region
        img = ImageGrab.grab(bbox=(rx, ry, rx + rw, ry + rh))
    else:
        img = ImageGrab.grab()
    img.save(save_path)
    print(f"[ImageRecog] 截图保存: {save_path}")
