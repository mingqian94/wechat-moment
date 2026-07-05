"""
ADB 封装层 —— 所有跟手机的交互都走这里。

设计要点（都是 2026-07-02 在小米15/HyperOS 上实测踩过的坑）：
- 截屏必须二进制安全：`exec-out screencap -p` 用 subprocess 直接读 stdout 字节流，
  绝不能经过 PowerShell 的 `>` 重定向（会按 UTF-16 编码把 PNG 二进制打乱）。
- 模拟点击（input tap/keyevent）在 MIUI/HyperOS 上需要"USB调试（安全设置）"开关打开，
  且改开关后要重启手机、重连调试会话才生效——这是设备端一次性配置，代码里管不了，
  但 tap 失败时要能识别出 INJECT_EVENTS 报错并给出明确提示。
- 无线 ADB 的 daemon 一重启就掉线，端口也会变；连接要能自动重连。
"""
import subprocess
import time
from pathlib import Path


class AdbError(Exception):
    pass


class InjectPermissionError(AdbError):
    """input 注入被 MIUI 拦截——"USB调试（安全设置）"没开或没重启生效。"""


class Adb:
    def __init__(self, adb_path: str, serial: str):
        """adb_path: adb.exe 路径；serial: 设备序列号（无线为 ip:port）"""
        self.adb_path = adb_path
        self.serial = serial
        self._w = self._h = None  # 屏幕物理分辨率，懒加载

    # ── 底层命令 ────────────────────────────────────────────
    def _run(self, args: list[str], binary: bool = False, timeout: float = 30):
        """执行 adb -s <serial> <args>。binary=True 时返回 stdout 原始字节。"""
        cmd = [self.adb_path, "-s", self.serial, *args]
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
        )
        if binary:
            return proc.stdout
        out = proc.stdout.decode("utf-8", "replace")
        err = proc.stderr.decode("utf-8", "replace")
        return out, err, proc.returncode

    def shell(self, cmd: str, timeout: float = 30) -> str:
        out, err, code = self._run(["shell", cmd], timeout=timeout)
        if code != 0 or "SecurityException" in err or "SecurityException" in out:
            if "INJECT_EVENTS" in (out + err):
                raise InjectPermissionError(
                    "模拟点击被系统拦截：请在开发者选项打开"
                    "\"USB调试（安全设置）—允许模拟点击\"，打开后重启手机再试"
                )
            if code != 0:
                raise AdbError(f"shell 失败: {cmd}\n{err or out}")
        return out

    # ── 连接管理 ────────────────────────────────────────────
    def connect(self) -> bool:
        """（无线）连接设备。已连返回 True。"""
        out, err, _ = self._run_global(["connect", self.serial])
        return "connected" in out or "already" in out

    def is_online(self) -> bool:
        out, _, _ = self._run_global(["devices"])
        for line in out.splitlines():
            if line.startswith(self.serial) and "device" in line.split():
                return True
        return False

    def ensure_online(self):
        """确保在线，掉线自动重连一次。"""
        if self.is_online():
            return
        self.connect()
        time.sleep(0.5)
        if not self.is_online():
            raise AdbError(f"设备 {self.serial} 连不上（无线调试可能已关闭或端口变了）")

    def _run_global(self, args: list[str], timeout: float = 20):
        """不带 -s 的全局命令（connect/devices）。"""
        cmd = [self.adb_path, *args]
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
        return (proc.stdout.decode("utf-8", "replace"),
                proc.stderr.decode("utf-8", "replace"),
                proc.returncode)

    # ── 屏幕 ────────────────────────────────────────────────
    def resolution(self) -> tuple[int, int]:
        """物理分辨率 (宽, 高)，缓存。"""
        if self._w is None:
            out = self.shell("wm size")
            # "Physical size: 1200x2670"
            part = out.split(":")[-1].strip()
            w, h = part.split("x")
            self._w, self._h = int(w), int(h)
        return self._w, self._h

    def screencap(self) -> bytes:
        """截屏，返回 PNG 字节流（二进制安全，不落盘）。"""
        data = self._run(["exec-out", "screencap", "-p"], binary=True)
        if not data[:4] == b"\x89PNG":
            # 极少数机型 exec-out 会污染换行，回退到 screencap 到设备再 pull
            self.shell("screencap -p /sdcard/_wmcap.png")
            data = self._run(["exec-out", "cat", "/sdcard/_wmcap.png"], binary=True)
            self.shell("rm -f /sdcard/_wmcap.png")
        return data

    def screencap_to(self, path: str):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(self.screencap())

    # ── 输入 ────────────────────────────────────────────────
    def tap(self, x: int, y: int):
        self.shell(f"input tap {x} {y}")

    def tap_ratio(self, rx: float, ry: float):
        """按屏幕比例点击（0~1）。UI 不变的前提下天然跨分辨率。"""
        w, h = self.resolution()
        self.tap(int(w * rx), int(h * ry))

    def swipe(self, x1: int, y1: int, x2: int, y2: int, ms: int = 300):
        self.shell(f"input swipe {x1} {y1} {x2} {y2} {ms}")

    def key(self, keycode: str):
        self.shell(f"input keyevent {keycode}")

    def back(self):
        self.key("KEYCODE_BACK")

    def home(self):
        self.key("KEYCODE_HOME")

    # ── 文件 ────────────────────────────────────────────────
    def push(self, local: str, remote: str):
        out, err, code = self._run(["push", local, remote])
        if code != 0:
            raise AdbError(f"push 失败: {local} -> {remote}\n{err}")

    def media_scan(self, remote_file: str):
        """让相册立即识别新推入的图片。"""
        self.shell(
            f"am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE "
            f"-d file://{remote_file}"
        )
