"""
设备管理 —— 发现在线手机、识别机型、分配别名、绑定坐标 Profile。

类比 PC 版 window_manager.find_wechat_windows()：程序启动时扫一遍，得到一份
带别名、带 Profile 的设备列表，交给上层（GUI/scheduler）使用。
"""
import subprocess
from dataclasses import dataclass, field

from adb import Adb
import device_profile


@dataclass
class Device:
    serial: str          # adb 设备号（USB 或 ip:port）
    model: str            # ro.product.model
    alias: str = ""       # 手机-01 / 手机-02 ...
    profile: dict | None = None   # 该机型的坐标 Profile，None 表示未标定
    adb: Adb | None = None

    @property
    def ready(self) -> bool:
        """能不能直接拿来发布：在线 + 有 Profile。"""
        return self.profile is not None


def _list_serials(adb_path: str) -> list[str]:
    """裸 `adb devices`，列出当前在线的设备号（不含未授权/离线的）。
    无线调试的手机会同时列出 ip:port 和 mDNS 自动发现的 adb-xxx._adb-tls-connect._tcp
    两个"序列号"，其实是同一台物理设备——2026-07-05 实测发现，不过滤会把一台手机
    在设备列表里显示成两台。只保留 ip:port / USB 序列号形式，过滤掉 mDNS 名字。"""
    proc = subprocess.run([adb_path, "devices"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
    out = proc.stdout.decode("utf-8", "replace")
    serials = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device" and "_adb-tls-connect._tcp" not in parts[0]:
            serials.append(parts[0])
    return serials


def discover_devices(adb_path: str) -> list[Device]:
    """扫描所有在线设备，识别机型，查 Profile，分配别名。"""
    devices = []
    for i, serial in enumerate(_list_serials(adb_path)):
        adb = Adb(adb_path, serial)
        try:
            model = adb.shell("getprop ro.product.model").strip()
        except Exception:
            model = "未知机型"
        profile = device_profile.get_profile(model)
        devices.append(Device(
            serial=serial,
            model=model,
            alias=f"手机-{i+1:02d}",
            profile=profile,
            adb=adb,
        ))
    return devices


def summarize(devices: list[Device]) -> str:
    lines = []
    for d in devices:
        status = "就绪" if d.ready else "⚠ 该机型未标定坐标"
        lines.append(f"  {d.alias} — {d.model} ({d.serial}) — {status}")
    return "\n".join(lines) if lines else "  （未检测到在线设备）"
