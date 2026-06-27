import platform
import random
import time

IS_WINDOWS = platform.system() == "Windows"

if IS_WINDOWS:
    import ctypes
    import ctypes.wintypes as wintypes
    from ctypes import windll

    user32 = windll.user32

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

    def _capture_window(hwnd: int):
        """截取窗口图像，返回 PIL Image。
        优先使用 PrintWindow(PW_RENDERFULLCONTENT)，能正确截取硬件加速/分层渲染的子区域
        （如新版微信左侧导航栏、头像），桌面DC BitBlt 对这类区域会透出背后桌面，故仅作降级方案。
        """
        try:
            import win32gui
            import win32ui
            from ctypes import windll
            import numpy as np
            from PIL import Image

            rect = wintypes.RECT()
            windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            x, y = rect.left, rect.top
            w = rect.right - rect.left
            h = rect.bottom - rect.top

            if w <= 0 or h <= 0:
                return None

            # 方法1：PrintWindow（flag=2，PW_RENDERFULLCONTENT），正确处理硬件加速渲染区域
            try:
                hwndDC = win32gui.GetWindowDC(hwnd)
                mfcDC = win32ui.CreateDCFromHandle(hwndDC)
                saveDC = mfcDC.CreateCompatibleDC()
                bmp = win32ui.CreateBitmap()
                bmp.CreateCompatibleBitmap(mfcDC, w, h)
                saveDC.SelectObject(bmp)
                windll.user32.PrintWindow(hwnd, saveDC.GetSafeHdc(), 2)

                bmpstr = bmp.GetBitmapBits(True)
                img = np.frombuffer(bmpstr, dtype=np.uint8)
                img = np.reshape(img, (h, w, 4))
                pil = Image.fromarray(img[:, :, :3], 'RGB')

                win32gui.DeleteObject(bmp.GetHandle())
                saveDC.DeleteDC()
                mfcDC.DeleteDC()
                win32gui.ReleaseDC(hwnd, hwndDC)

                std = np.std(np.array(pil))
                if std > 5:
                    return pil
            except Exception:
                pass

            # 方法2：桌面DC截图（降级方案，部分硬件加速/分层区域可能透出背后桌面）
            try:
                desktop_hwnd = windll.user32.GetDesktopWindow()
                desktopDC = win32gui.GetWindowDC(desktop_hwnd)
                mfcDC = win32ui.CreateDCFromHandle(desktopDC)
                saveDC = mfcDC.CreateCompatibleDC()
                bmp = win32ui.CreateBitmap()
                bmp.CreateCompatibleBitmap(mfcDC, w, h)
                saveDC.SelectObject(bmp)
                saveDC.BitBlt((0, 0), (w, h), mfcDC, (x, y), 0x00CC0020)

                bmpstr = bmp.GetBitmapBits(True)
                img = np.frombuffer(bmpstr, dtype=np.uint8)
                img = np.reshape(img, (h, w, 4))
                # GetBitmapBits 返回 BGRA，需转成 RGB
                pil = Image.fromarray(img, 'RGBA').convert('RGB')

                win32gui.DeleteObject(bmp.GetHandle())
                saveDC.DeleteDC()
                mfcDC.DeleteDC()
                win32gui.ReleaseDC(desktop_hwnd, desktopDC)

                return pil
            except Exception:
                pass

            return None
        except Exception:
            return None

    def _capture_avatar_from_window(hwnd: int) -> bytes | None:
        """截取微信窗口左上角头像区域，返回 PNG 字节。
        头像在新版微信（Qt51514QWindowIcon）左侧导航栏中，相对窗口左上角是固定像素偏移，
        与窗口尺寸无关（导航栏宽度不随窗口缩放变化），故用固定偏移而非比例定位。
        截图前会先激活窗口，确保窗口可见。
        """
        try:
            import numpy as np
            from PIL import Image
            import io
            import time

            # 先激活窗口，确保窗口可见（硬件加速的窗口必须可见才能截图）
            if not activate_window(hwnd):
                return None
            time.sleep(random.uniform(0.16, 0.27))

            # 截取整个窗口
            img = _capture_window(hwnd)
            if img is None:
                return None

            win_w, win_h = img.size

            if win_w <= 0 or win_h <= 0:
                return None

            # 固定像素偏移（基于新版微信导航栏实测校准）
            AVATAR_X = 40
            AVATAR_Y = 90
            AVATAR_SIZE = 62

            # 确保不超出窗口范围
            AVATAR_X = max(0, min(AVATAR_X, win_w - 1))
            AVATAR_Y = max(0, min(AVATAR_Y, win_h - 1))
            AVATAR_SIZE = min(AVATAR_SIZE, win_w - AVATAR_X, win_h - AVATAR_Y)

            if AVATAR_SIZE <= 0:
                return None

            # 裁剪头像区域
            avatar_img = img.crop((AVATAR_X, AVATAR_Y, AVATAR_X + AVATAR_SIZE, AVATAR_Y + AVATAR_SIZE))
            avatar_img = avatar_img.resize((64, 64), Image.LANCZOS)

            buf = io.BytesIO()
            avatar_img.save(buf, format='PNG')
            return buf.getvalue()
        except Exception:
            return None

    def _check_login_and_get_avatar(hwnd: int) -> tuple[bool, bytes | None]:
        """判断微信是否已登录，同时返回头像（已登录时）。
        依据：登录后的微信窗口有左侧导航栏，宽度较大；未登录的登录窗口较窄。
        同时辅助判断头像区域颜色丰富度。
        """
        try:
            import numpy as np
            from PIL import Image
            import io

            # 1. 检查窗口尺寸 - 登录后的微信主窗口通常宽高都较大
            rect = wintypes.RECT()
            windll.user32.GetWindowRect(hwnd, ctypes.byref(rect))
            win_w = rect.right - rect.left
            win_h = rect.bottom - rect.top

            # 未登录的登录窗口通常比较窄，且高度/宽度比偏大
            # 登录后主窗口通常宽度 > 700，高度 > 500，宽高比 > 1.2
            if win_w < 700 or win_h < 500:
                return False, None
            if win_w / win_h < 1.1:
                return False, None

            # 2. 截取头像区域
            avatar_bytes = _capture_avatar_from_window(hwnd)
            if not avatar_bytes:
                return False, None

            # 3. 检查头像区域颜色丰富度 - 真实头像颜色丰富，未登录区域颜色单一
            img = Image.open(io.BytesIO(avatar_bytes))
            img_array = np.array(img)

            if len(img_array.shape) == 3:
                std = np.std(img_array[:, :, :3])
                # 同时检查中心区域的颜色丰富度（头像中心应该更丰富）
                h, w = img_array.shape[:2]
                center_region = img_array[h//4:3*h//4, w//4:3*w//4, :3]
                center_std = np.std(center_region)
            else:
                std = np.std(img_array)
                center_std = std

            # 真实头像颜色标准差通常 > 30，单色/默认图标通常 < 20
            # 中心区域应该更丰富（排除边框等干扰）
            if std > 20 and center_std > 25:
                return True, avatar_bytes
            else:
                return False, None
        except Exception as e:
            print(f"[WindowMgr] _check_login_and_get_avatar 异常: {e}")
            import traceback
            traceback.print_exc()
            return False, None

    def find_wechat_windows() -> list[dict]:
        # 保存当前前台窗口，遍历完后恢复
        foreground_hwnd = user32.GetForegroundWindow()

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

                # 判断是否已登录，同时获取头像
                is_logged_in, avatar_bytes = _check_login_and_get_avatar(hwnd)
                if not is_logged_in:
                    continue

                windows.append({
                    "hwnd": hwnd,
                    "pid": pid.value,
                    "title": title,
                    "avatar_bytes": avatar_bytes,
                })

        # 恢复之前的前台窗口
        if foreground_hwnd and user32.IsWindow(foreground_hwnd):
            user32.SetForegroundWindow(foreground_hwnd)
            time.sleep(random.uniform(0.07, 0.14))

        return windows

    def activate_window(hwnd: int) -> bool:
        """激活窗口并置于前台。
        裸调用 SetForegroundWindow 在调用进程不是当前前台进程时常被 Windows 焦点锁定机制拒绝
        （后台脚本调度时正是这种情况）。这里用 AttachThreadInput 把本线程"接到"当前前台线程的
        输入队列上，借用其焦点权限，是 Windows 自动化里激活窗口的标准做法。
        """
        if not user32.IsWindow(hwnd):
            return False
        # 如果最小化则恢复
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        # 微信失去焦点后会把自己设成不可见（不是最小化，IsIconic 是 False，
        # 但 IsWindowVisible 是 0），上面那个 IsIconic 判断盖不住这种情况，要单独处理
        if not user32.IsWindowVisible(hwnd):
            user32.ShowWindow(hwnd, 5)  # SW_SHOW

        kernel32 = windll.kernel32
        cur_thread = kernel32.GetCurrentThreadId()
        fg_hwnd = user32.GetForegroundWindow()
        fg_thread = user32.GetWindowThreadProcessId(fg_hwnd, None)
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)

        attached_fg = False
        attached_target = False
        try:
            if fg_thread and fg_thread != cur_thread:
                attached_fg = bool(user32.AttachThreadInput(cur_thread, fg_thread, True))
            if target_thread and target_thread != cur_thread:
                attached_target = bool(user32.AttachThreadInput(cur_thread, target_thread, True))

            user32.BringWindowToTop(hwnd)
            user32.SetForegroundWindow(hwnd)
        finally:
            if attached_fg:
                user32.AttachThreadInput(cur_thread, fg_thread, False)
            if attached_target:
                user32.AttachThreadInput(cur_thread, target_thread, False)

        time.sleep(random.uniform(0.24, 0.38))
        return user32.GetForegroundWindow() == hwnd

    def get_window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
        rect = wintypes.RECT()
        if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return rect.left, rect.top, rect.right - rect.left, rect.bottom - rect.top
        return None

    def find_moments_window(main_hwnd: int, timeout: float = 5.0) -> int | None:
        """点击"朋友圈"后会弹出一个独立的新顶层窗口（不是主窗口的子区域），
        相机/发表按钮都在这个新窗口里，必须切换 hwnd 才能正确截图/找按钮。
        按主窗口所属 pid 查找除主窗口外新出现的可见顶层窗口，标题含"朋友圈"优先。
        """
        main_pid = ctypes.c_ulong(0)
        user32.GetWindowThreadProcessId(main_hwnd, ctypes.byref(main_pid))

        deadline = time.time() + timeout
        while time.time() < deadline:
            candidates = []

            @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
            def callback(hwnd, _):
                if hwnd == main_hwnd or not user32.IsWindowVisible(hwnd):
                    return True
                pid = ctypes.c_ulong(0)
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                if pid.value != main_pid.value:
                    return True
                rect = wintypes.RECT()
                user32.GetWindowRect(hwnd, ctypes.byref(rect))
                w, h = rect.right - rect.left, rect.bottom - rect.top
                if w < 200 or h < 200:
                    return True
                title = ctypes.create_unicode_buffer(256)
                user32.GetWindowTextW(hwnd, title, 256)
                candidates.append((hwnd, title.value))
                return True

            user32.EnumWindows(callback, 0)

            for hwnd, title in candidates:
                if "朋友圈" in title:
                    return hwnd
            if candidates:
                return candidates[0][0]

            time.sleep(random.uniform(0.16, 0.27))
        return None

    def close_window(hwnd: int) -> bool:
        """关闭窗口（发 WM_CLOSE），用于发布完成后把朋友圈弹窗收掉，
        避免残留弹窗挡住下一个账号的操作。失败（比如窗口已经不存在）不抛异常，返回 False。
        """
        try:
            if not user32.IsWindow(hwnd):
                return True
            WM_CLOSE = 0x0010
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
            return True
        except Exception:
            return False

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

    def find_moments_window(main_hwnd: int, timeout: float = 5.0) -> int | None:
        return main_hwnd

    def close_window(hwnd: int) -> bool:
        print(f"[Mock] close_window hwnd={hwnd}")
        return True


def bind_aliases(windows: list[dict]) -> list[dict]:
    """保留头像字节数据用于界面显示，alias 使用简单序号。"""
    for i, w in enumerate(windows):
        w["alias"] = f"微信-{i + 1}"
    return windows
