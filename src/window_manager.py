import platform
import time

IS_WINDOWS = platform.system() == "Windows"

if IS_WINDOWS:
    import ctypes
    import ctypes.wintypes as wintypes

    user32 = ctypes.windll.user32

    def _enum_windows_by_class(class_name: str) -> list[int]:
        results = []

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
        def callback(hwnd, _):
            buf = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, buf, 256)
            if buf.value == class_name:
                results.append(hwnd)
            return True

        user32.EnumWindows(callback, 0)
        return results

    # 支持的微信窗口类名（传统版 + 新版/UWP版）
    WECHAT_CLASS_NAMES = ["WeChatMainWndForPC", "Qt51514QWindowIcon"]

    def _capture_window_screenshot(hwnd: int, width: int = 200, height: int = 200) -> bytes | None:
        """截取窗口左上角区域（头像位置），返回 PNG 字节"""
        try:
            import win32gui
            import win32ui
            from ctypes import windll

            hwndDC = win32gui.GetWindowDC(hwnd)
            mfcDC = win32ui.CreateDCFromHandle(hwndDC)
            saveDC = mfcDC.CreateCompatibleDC()

            saveBitMap = win32ui.CreateBitmap()
            saveBitMap.CreateCompatibleBitmap(mfcDC, width, height)
            saveDC.SelectObject(saveBitMap)

            windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 2)

            bmpinfo = saveBitMap.GetInfo()
            bmpstr = saveBitMap.GetBitmapBits(True)

            import numpy as np
            from PIL import Image
            img = np.frombuffer(bmpstr, dtype=np.uint8)
            img.shape = (height, width, 4)
            img = Image.fromarray(img[:, :, :3], 'RGB')

            import io
            buf = io.BytesIO()
            img.save(buf, format='PNG')

            win32gui.DeleteObject(saveBitMap.GetHandle())
            saveDC.DeleteDC()
            mfcDC.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwndDC)

            return buf.getvalue()
        except Exception:
            return None

    def _capture_avatar_from_window(hwnd: int) -> bytes | None:
        """截取微信窗口左上角头像区域，返回 PNG 字节。
        新版微信头像位置：窗口内偏移约 (15, 45)，尺寸约 40x40
        """
        try:
            import win32gui
            import win32ui
            from ctypes import windll

            # 头像在窗口内的位置（根据实际界面估算）
            AVATAR_X = 15
            AVATAR_Y = 45
            AVATAR_W = 40
            AVATAR_H = 40

            hwndDC = win32gui.GetWindowDC(hwnd)
            mfcDC = win32ui.CreateDCFromHandle(hwndDC)
            saveDC = mfcDC.CreateCompatibleDC()

            saveBitMap = win32ui.CreateBitmap()
            saveBitMap.CreateCompatibleBitmap(mfcDC, AVATAR_W, AVATAR_H)
            saveDC.SelectObject(saveBitMap)

            # 使用 BitBlt 从窗口指定位置复制
            windll.gdi32.BitBlt(
                saveDC.GetSafeHdc(), 0, 0, AVATAR_W, AVATAR_H,
                hwndDC, AVATAR_X, AVATAR_Y, 0x00CC0020  # SRCCOPY
            )

            bmpstr = saveBitMap.GetBitmapBits(True)

            import numpy as np
            from PIL import Image
            img = np.frombuffer(bmpstr, dtype=np.uint8)
            img.shape = (AVATAR_H, AVATAR_W, 4)
            img = Image.fromarray(img[:, :, :3], 'RGB')

            import io
            buf = io.BytesIO()
            img.save(buf, format='PNG')

            win32gui.DeleteObject(saveBitMap.GetHandle())
            saveDC.DeleteDC()
            mfcDC.DeleteDC()
            win32gui.ReleaseDC(hwnd, hwndDC)

            return buf.getvalue()
        except Exception:
            return None

    def find_wechat_windows() -> list[dict]:
        windows = []
        for class_name in WECHAT_CLASS_NAMES:
            hwnds = _enum_windows_by_class(class_name)
            for hwnd in hwnds:
                buf = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, buf, 256)
                title = buf.value
                # 过滤：标题必须包含"微信"
                if "微信" not in title:
                    continue
                pid = ctypes.c_ulong(0)
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

                # 截取头像区域作为唯一标识
                avatar_bytes = _capture_avatar_from_window(hwnd)

                windows.append({
                    "hwnd": hwnd,
                    "pid": pid.value,
                    "title": title,
                    "avatar_bytes": avatar_bytes,
                })
        return windows

    def activate_window(hwnd: int) -> bool:
        if not user32.IsWindow(hwnd):
            return False
        # 如果最小化则恢复
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.3)
        return user32.GetForegroundWindow() == hwnd

    def get_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
        rect = wintypes.RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
        return None

else:
    # Mac / 开发模式：返回 mock 数据，不做实际操作
    _MOCK_WINDOWS = [
        {"hwnd": 10001, "pid": 1001, "title": "微信 (Mock A1)"},
        {"hwnd": 10002, "pid": 1002, "title": "微信 (Mock A2)"},
        {"hwnd": 10003, "pid": 1003, "title": "微信 (Mock A3)"},
    ]

    def find_wechat_windows() -> list[dict]:
        return _MOCK_WINDOWS

    def activate_window(hwnd: int) -> bool:
        print(f"[Mock] activate_window hwnd={hwnd}")
        return True

    def get_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
        return (0, 0, 800, 600)


def bind_aliases(windows: list[dict]) -> list[dict]:
    """保留头像字节数据用于界面显示，alias 使用简单序号。"""
    for i, w in enumerate(windows):
        w["alias"] = f"微信-{i + 1}"
    return windows
