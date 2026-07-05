"""
设备自检 —— 新手机接入时跑一遍，逐项确认这台设备真的能被自动化操作。

按用户要求覆盖：连接、截屏、模拟点击、推图片、推视频、键盘（ADBKeyboard）。
不确认"发圈流程"本身（那需要真的操作微信，自检只验证底层能力），流程是否走通
由 publisher.py 实际发布时验证。
"""
import tempfile
from dataclasses import dataclass
from pathlib import Path

from adb import Adb, AdbError, InjectPermissionError, MOMENTS_FOLDER
from publisher import ADBKEYBOARD_IME


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str = ""


def _make_test_image(path: Path):
    from PIL import Image
    img = Image.new("RGB", (100, 100), color=(80, 160, 220))
    img.save(path, format="PNG")


def _make_test_video(path: Path):
    import cv2
    import numpy as np
    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
    writer = cv2.VideoWriter(str(path), fourcc, 10, (160, 120))
    for _ in range(10):  # 1 秒，纯色帧，只为测试推送链路，不测试真实拍摄内容
        writer.write(np.full((120, 160, 3), 200, dtype="uint8"))
    writer.release()


def run_diagnostics(adb: Adb) -> list[CheckResult]:
    results = []

    # 1. 连接
    try:
        adb.ensure_online()
        results.append(CheckResult("ADB连接", True))
    except AdbError as e:
        results.append(CheckResult("ADB连接", False, str(e)))
        return results  # 连不上，后面都测不了

    # 2. 截屏
    try:
        png = adb.screencap()
        ok = png[:4] == b"\x89PNG"
        results.append(CheckResult("截屏", ok, "" if ok else "返回内容不是有效 PNG"))
    except Exception as e:
        results.append(CheckResult("截屏", False, str(e)))

    # 3. 模拟点击（用无害的 HOME 键）
    try:
        adb.home()
        results.append(CheckResult("模拟点击", True))
    except InjectPermissionError as e:
        results.append(CheckResult("模拟点击", False, str(e)))
    except Exception as e:
        results.append(CheckResult("模拟点击", False, f"未知错误: {e}"))

    # 4. 推图片到专用文件夹
    try:
        with tempfile.TemporaryDirectory() as tmp:
            local_img = Path(tmp) / "_diag.png"
            _make_test_image(local_img)
            remote_img = f"{MOMENTS_FOLDER}/_diag_test.png"
            adb.shell(f"mkdir -p {MOMENTS_FOLDER}")
            adb.push(str(local_img), remote_img)
            listing = adb.shell(f"ls {remote_img}")
            ok = "_diag_test.png" in listing
            adb.shell(f"rm -f {remote_img}")
            results.append(CheckResult("推图片", ok, "" if ok else f"push 后未在设备上找到文件: {listing}"))
    except Exception as e:
        results.append(CheckResult("推图片", False, str(e)))

    # 5. 推视频到专用文件夹
    try:
        with tempfile.TemporaryDirectory() as tmp:
            local_vid = Path(tmp) / "_diag.mp4"
            _make_test_video(local_vid)
            remote_vid = f"{MOMENTS_FOLDER}/_diag_test.mp4"
            adb.shell(f"mkdir -p {MOMENTS_FOLDER}")
            adb.push(str(local_vid), remote_vid)
            listing = adb.shell(f"ls {remote_vid}")
            ok = "_diag_test.mp4" in listing
            adb.shell(f"rm -f {remote_vid}")
            results.append(CheckResult("推视频", ok, "" if ok else f"push 后未在设备上找到文件: {listing}"))
    except Exception as e:
        results.append(CheckResult("推视频", False, str(e)))

    # 6. 键盘（ADBKeyboard 已安装 + 能切换）
    try:
        packages = adb.shell("pm list packages")
        installed = "com.android.adbkeyboard" in packages
        if not installed:
            results.append(CheckResult("键盘(ADBKeyboard)", False,
                                       "未安装，需按《手机配置清单》手动装 ADBKeyboard.apk"))
        else:
            prev_ime = adb.shell("settings get secure default_input_method").strip()
            adb.shell(f"ime enable {ADBKEYBOARD_IME}")
            adb.shell(f"ime set {ADBKEYBOARD_IME}")
            cur = adb.shell("settings get secure default_input_method").strip()
            ok = cur == ADBKEYBOARD_IME
            if prev_ime and prev_ime != ADBKEYBOARD_IME:
                adb.shell(f"ime set {prev_ime}")  # 测完切回用户原输入法
            results.append(CheckResult("键盘(ADBKeyboard)", ok,
                                       "" if ok else "已安装但切换输入法未生效"))
    except Exception as e:
        results.append(CheckResult("键盘(ADBKeyboard)", False, str(e)))

    return results


def format_report(results: list[CheckResult]) -> str:
    lines = []
    for r in results:
        mark = "✓" if r.ok else "✗"
        line = f"  {mark} {r.name}"
        if not r.ok and r.detail:
            line += f" — {r.detail}"
        lines.append(line)
    return "\n".join(lines)
