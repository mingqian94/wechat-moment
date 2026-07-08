"""
iPhone 控制封装。

当前 iOS 26.5 实测可用能力：
- USB 识别设备
- Developer Mode + DeveloperDiskImage 后，可从电脑启动微信
- 可把文案写入 iPhone 剪贴板
- 可截图留证

不可用能力：
- CoreDevice 触控在本机 iOS 26.5 返回“Remote control requires iOS 27.0 or later”
- WDA/XCUITest 需要额外签名 Runner，交付前不纳入主流程

所以 iPhone 只做“半自动发布”：到点复制文案并打开微信，素材选择和发表由人工完成。
"""
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import threading
import asyncio
from dataclasses import dataclass
from pathlib import Path
from contextlib import redirect_stderr, redirect_stdout

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_PMD3_LOCK = threading.Lock()


class IosError(Exception):
    pass


def _run_hidden(cmd: list[str], **kwargs):
    if _CREATE_NO_WINDOW:
        kwargs.setdefault("creationflags", _CREATE_NO_WINDOW)
    return subprocess.run(cmd, **kwargs)


def _python_exe() -> str:
    if getattr(sys, "frozen", False):
        # 打包版若要支持 iPhone，需要随包带 Python/pymobiledevice3 或让客户安装后配置环境变量。
        return os.environ.get("WM_PYTHON_PATH", sys.executable)
    return sys.executable


def _pmd3_cmd() -> list[str]:
    env = os.environ.get("WM_PYMOBILEDEVICE3_PATH")
    if env:
        return [env]
    if getattr(sys, "frozen", False):
        return []
    return [_python_exe(), "-m", "pymobiledevice3"]


def _run_inprocess(args: list[str], udid: str | None = None) -> str:
    """Run pymobiledevice3 inside the packaged exe.

    PyInstaller apps cannot reliably execute themselves as `exe -m pymobiledevice3`, so the
    frozen build calls the Typer CLI entrypoint in-process and captures stdout/stderr.
    """
    with _PMD3_LOCK:
        from pymobiledevice3.__main__ import main as pmd3_main

        old_argv = sys.argv[:]
        old_udid = os.environ.get("PYMOBILEDEVICE3_UDID")
        code = 0
        with tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as out, \
                tempfile.TemporaryFile("w+", encoding="utf-8", errors="replace") as err:
            try:
                sys.argv = ["pymobiledevice3", *args]
                if udid:
                    os.environ["PYMOBILEDEVICE3_UDID"] = udid
                elif "PYMOBILEDEVICE3_UDID" in os.environ:
                    del os.environ["PYMOBILEDEVICE3_UDID"]
                with redirect_stdout(out), redirect_stderr(err):
                    try:
                        pmd3_main()
                    except SystemExit as e:
                        code = int(e.code or 0) if isinstance(e.code, int) else 1
            finally:
                sys.argv = old_argv
                if old_udid is None:
                    os.environ.pop("PYMOBILEDEVICE3_UDID", None)
                else:
                    os.environ["PYMOBILEDEVICE3_UDID"] = old_udid
            out.seek(0)
            err.seek(0)
            text = out.read() + err.read()
        if code != 0:
            raise IosError(text.strip() or f"pymobiledevice3 failed: {' '.join(args)}")
        return text


def pmd3_available() -> bool:
    try:
        if getattr(sys, "frozen", False) and not os.environ.get("WM_PYMOBILEDEVICE3_PATH"):
            import pymobiledevice3  # noqa: F401
            return True
        proc = _run_hidden(_pmd3_cmd() + ["--help"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        return proc.returncode == 0
    except Exception:
        return False


def _run(args: list[str], timeout: float = 30, text: str | None = None,
         udid: str | None = None) -> str:
    if getattr(sys, "frozen", False) and not os.environ.get("WM_PYMOBILEDEVICE3_PATH"):
        return _run_inprocess(args, udid=udid)
    env = os.environ.copy()
    if udid:
        env["PYMOBILEDEVICE3_UDID"] = udid
    proc = _run_hidden(
        _pmd3_cmd() + args,
        input=text,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != 0:
        raise IosError(out.strip() or f"pymobiledevice3 failed: {' '.join(args)}")
    return out


@dataclass
class IosController:
    udid: str
    host: str = ""

    def copy_text(self, text: str):
        if not text:
            return
        _run(["developer", "core-device", "copy", "--userspace", text], timeout=20, udid=self.udid)

    def launch_wechat(self):
        _run(
            ["developer", "core-device", "launch-application", "--userspace", "com.tencent.xin", "noop"],
            timeout=30,
            udid=self.udid,
        )

    def ensure_developer_ready(self):
        status = _run(["amfi", "developer-mode-status"], timeout=20, udid=self.udid).strip().lower()
        if "true" not in status:
            raise IosError("iPhone 未开启开发者模式：设置 → 隐私与安全性 → 开发者模式")
        _run(["mounter", "auto-mount"], timeout=60, udid=self.udid)

    def screenshot_to(self, path: str | Path):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        _run(
            ["developer", "core-device", "screen-capture", "screenshot", "--userspace", str(path)],
            timeout=30,
            udid=self.udid,
        )


def list_devices() -> list[dict]:
    if not pmd3_available():
        return []
    try:
        raw = _run(["usbmux", "list"], timeout=20)
        devices = json.loads(raw)
    except Exception:
        return []

    result = []
    for d in devices:
        if d.get("DeviceClass") != "iPhone":
            continue
        udid = d.get("UniqueDeviceID") or d.get("Identifier")
        if not udid:
            continue
        result.append({
            "udid": udid,
            "name": d.get("DeviceName") or "iPhone",
            "model": d.get("ProductType") or "iPhone",
            "version": d.get("ProductVersion") or "",
            "connection": "USB",
        })
    return result


def _fix_ios_name(value: str | None) -> str:
    """Best-effort fix for Chinese device names returned mojibake from WiFi lockdown."""
    if not value:
        return "iPhone"
    for enc in ("latin1", "cp1252"):
        try:
            fixed = value.encode(enc).decode("gbk")
            if fixed and fixed != value:
                return fixed
        except Exception:
            pass
    return value


def _tcp_open(host: str, port: int, timeout: float = 0.8) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        return True
    except Exception:
        return False
    finally:
        sock.close()


def _arp_hosts() -> list[str]:
    hosts: list[str] = []
    try:
        proc = _run_hidden(["arp", "-a"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5)
        text = proc.stdout.decode("utf-8", "replace")
    except Exception:
        return hosts
    for match in re.finditer(r"\b((?:192\.168|10|172\.(?:1[6-9]|2\d|3[01]))\.\d+\.\d+)\b", text):
        ip = match.group(1)
        if ip.endswith(".1") or ip.endswith(".255") or ip in hosts:
            continue
        hosts.append(ip)
    return hosts


async def _wifi_devices(timeout: float) -> list[dict]:
    from pymobiledevice3.bonjour import browse_remotepairing
    from pymobiledevice3.lockdown import create_using_tcp

    devices: list[dict] = []
    seen_hosts: set[str] = set()
    candidate_hosts: list[str] = []
    for answer in await browse_remotepairing(timeout=timeout):
        for address in answer.addresses:
            host = address.full_ip
            if not host or ":" in host or "%" in host or host in seen_hosts:
                continue
            seen_hosts.add(host)
            candidate_hosts.append(host)

    manual_hosts = [h.strip() for h in os.environ.get("WM_IOS_WIFI_HOSTS", "").split(",") if h.strip()]
    for host in [*manual_hosts, *_arp_hosts()]:
        if host not in seen_hosts and _tcp_open(host, 62078):
            seen_hosts.add(host)
            candidate_hosts.append(host)

    for host in candidate_hosts:
            try:
                lockdown = await asyncio.wait_for(create_using_tcp(host, autopair=False), timeout=4)
                try:
                    info = lockdown.short_info
                    devices.append({
                        # WiFi lockdown on this iOS build does not expose UDID in short_info.
                        # Keep the IP as a session identity and merge with known devices by name/model.
                        "udid": info.get("UniqueDeviceID") or f"wifi:{host}",
                        "name": _fix_ios_name(info.get("DeviceName")) or "iPhone",
                        "model": info.get("ProductType") or "iPhone",
                        "version": info.get("ProductVersion") or "",
                        "host": host,
                        "connection": "WiFi",
                    })
                finally:
                    await lockdown.close()
            except Exception:
                continue
    return devices


def list_wifi_devices(timeout: float = 3.0) -> list[dict]:
    if not pmd3_available():
        return []
    try:
        return asyncio.run(_wifi_devices(timeout))
    except Exception:
        return []


def list_all_devices() -> list[dict]:
    devices = list_devices()
    seen = {(d.get("connection"), d.get("udid"), d.get("host")) for d in devices}
    for d in list_wifi_devices():
        key = (d.get("connection"), d.get("udid"), d.get("host"))
        if key not in seen:
            devices.append(d)
            seen.add(key)
    return devices
