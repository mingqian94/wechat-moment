import platform
import random
import time
from pathlib import Path

import pyautogui
import cv2
import numpy as np
from PIL import ImageGrab

IS_WINDOWS = platform.system() == "Windows"

import sys as _sys
_BASE = Path(_sys._MEIPASS) if getattr(_sys, "frozen", False) else Path(__file__).parent.parent
TEMPLATES_DIR = _BASE / "templates"
MATCH_THRESHOLD = 0.80   # OpenCV 相似度阈值（0-1）

# 模板在 200% DPI（dpi=192）的机器上截取，物理像素对应此 DPI。
# 换到其他 DPI 的机器时，按钮物理像素大小按比例缩放，需要动态调整匹配尺度。
_TEMPLATE_DPI = 192  # 模板截取时的 DPI（96 × 缩放比）

def _system_dpi() -> int:
    if not IS_WINDOWS:
        return 96
    try:
        import ctypes
        # 临时以 DPI-unaware 模式查询系统 DPI，避免受进程 DPI 感知模式干扰
        return ctypes.windll.user32.GetDpiForSystem()
    except Exception:
        return 96

_current_dpi = _system_dpi()
_base_scale = _current_dpi / _TEMPLATE_DPI   # e.g. 100%→0.5, 125%→0.625, 150%→0.75, 200%→1.0
# 以基准缩放为中心，覆盖 ±25% 范围，共 9 个候选尺度
SCALES = sorted({
    round(_base_scale + d, 3)
    for d in [-0.25, -0.15, -0.08, -0.04, 0.0, 0.04, 0.08, 0.15, 0.25]
    if 0.25 <= _base_scale + d <= 2.5
})

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
    """截取区域，优先用桌面截图（ImageGrab），hwnd 仅在桌面截图疑似被遮挡时才用于 PrintWindow 兜底。

    2026-07-01 实测发现 PrintWindow(PW_RENDERFULLCONTENT) 对微信这个窗口不可靠——曾经在识别失败
    的瞬间截到一张几小时前的旧对话内容（陈旧缓存帧，不是实时画面），导致按钮明明在屏幕上却一直匹配
    不到。反而普通桌面截图（ImageGrab/BitBlt）两次诊断都截到了真实、实时的内容。
    之前用 PrintWindow 是为了应对"窗口被遮挡时 BitBlt 会透出背后桌面"的问题，但 execute_publish
    在截图前已经 activate_window() 把目标窗口真正置顶，遮挡风险已经不大，改为桌面截图优先、
    PrintWindow 仅作遮挡时的兜底（用 std 判断桌面截图是否疑似空白/被遮挡）。
    """
    screenshot = ImageGrab.grab(bbox=(x, y, x + w, y + h))
    img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

    if img.std() > 5 or not (hwnd and IS_WINDOWS):
        return img

    # 桌面截图疑似空白/被遮挡，退回 PrintWindow 兜底（窗口未真正置顶等极端情况）
    try:
        import ctypes
        import win32gui
        import win32ui
        from ctypes import windll
        import ctypes.wintypes as wintypes

        rect = wintypes.RECT()
        windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
        win_x, win_y = rect.left, rect.top
        win_w = rect.right - rect.left
        win_h = rect.bottom - rect.top

        rel_x = x - win_x
        rel_y = y - win_y

        hwndDC = win32gui.GetWindowDC(hwnd)
        mfcDC = win32ui.CreateDCFromHandle(hwndDC)
        saveDC = mfcDC.CreateCompatibleDC()
        fullBitMap = win32ui.CreateBitmap()
        fullBitMap.CreateCompatibleBitmap(mfcDC, win_w, win_h)
        saveDC.SelectObject(fullBitMap)
        windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 2)

        bmpstr = fullBitMap.GetBitmapBits(True)
        img_full = np.frombuffer(bmpstr, dtype=np.uint8)
        img_full.shape = (win_h, win_w, 4)

        rel_x = max(0, min(rel_x, win_w - w))
        rel_y = max(0, min(rel_y, win_h - h))
        crop = img_full[rel_y:rel_y+h, rel_x:rel_x+w]
        pw_img = cv2.cvtColor(crop, cv2.COLOR_BGRA2BGR)

        win32gui.DeleteObject(fullBitMap.GetHandle())
        saveDC.DeleteDC()
        mfcDC.DeleteDC()
        win32gui.ReleaseDC(hwnd, hwndDC)

        if pw_img.std() > 5:
            return pw_img
    except Exception as e:
        print(f"[ImageRecog] PrintWindow兜底失败: {e}")

    return img


def save_match_view(region: tuple[int, int, int, int], hwnd: int, save_path: str):
    """把 find_template 实际用来比对的那张图存下来（跟 take_screenshot 的 ImageGrab 不是同一路径，
    诊断"找不到按钮"时必须看这张图，而不是普通截图，两者在窗口未及时重绘时可能不一致）。
    这里不能直接用 cv2.imwrite——它在 Windows 上遇到含中文的路径会静默失败（返回 False 但不报错，
    错误截图目录"错误截图"本身就是中文），改用 cv2.imencode 编码后用普通文件句柄写，规避这个坑。"""
    rx, ry, rw, rh = region
    screen = _grab_region(rx, ry, rw, rh, hwnd=hwnd)
    Path(save_path).parent.mkdir(parents=True, exist_ok=True)
    ok, buf = cv2.imencode(".png", screen)
    if ok:
        with open(save_path, "wb") as f:
            f.write(buf.tobytes())


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


def _human_move_click(x: int, y: int):
    """模拟真人鼠标轨迹后点击，而不是瞬间跳到目标点的直线/瞬移。
    途中插入 1-3 个带随机偏移的中间点，每段用 ease 曲线、随机时长移动，
    到达目标前再做一次小幅微调，最后停顿一下再点击。
    """
    start_x, start_y = pyautogui.position()
    dist = max(1.0, ((x - start_x) ** 2 + (y - start_y) ** 2) ** 0.5)

    waypoint_count = random.choice([1, 1, 2, 3])
    points = []
    for i in range(1, waypoint_count + 1):
        ratio = i / (waypoint_count + 1)
        # 沿直线插值，再叠加随机横向偏移，偏移幅度跟距离挂钩，距离越远抖动空间越大
        bx = start_x + (x - start_x) * ratio
        by = start_y + (y - start_y) * ratio
        jitter = min(60.0, dist * 0.18)
        bx += random.uniform(-jitter, jitter)
        by += random.uniform(-jitter, jitter)
        points.append((bx, by))
    points.append((x, y))

    for px, py in points:
        seg_duration = random.uniform(0.08, 0.27)
        pyautogui.moveTo(px, py, duration=seg_duration, tween=pyautogui.easeInOutQuad)

    time.sleep(random.uniform(0.06, 0.22))
    pyautogui.click()


def find_and_click(template_name: str, region: tuple[int, int, int, int] | None = None,
                   timeout: float = 5.0, hwnd: int = None) -> bool:
    """循环查找模板并点击，超时返回 False。hwnd 用于直接截取窗口内容。"""
    deadline = time.time() + timeout
    while time.time() < deadline:
        pos = find_template(template_name, region, hwnd=hwnd)
        if pos:
            if IS_WINDOWS:
                _human_move_click(pos[0], pos[1])
            else:
                print(f"[Mock] 点击 {template_name} at {pos}")
            time.sleep(random.uniform(0.22, 0.41))
            return True
        time.sleep(random.uniform(0.22, 0.41))
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
