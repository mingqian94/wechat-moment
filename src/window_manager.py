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

    def find_wechat_windows() -> list[dict]:
        hwnds = _enum_windows_by_class("WeChatMainWndForPC")
        windows = []
        for hwnd in hwnds:
            buf = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, buf, 256)
            pid = ctypes.c_ulong(0)
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            windows.append({"hwnd": hwnd, "pid": pid.value, "title": buf.value})
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
    """给每个窗口分配 A1/A2/A3... 别名。"""
    for i, w in enumerate(windows):
        w["alias"] = f"A{i + 1}"
    return windows
