"""
设备管理 —— 发现全部"已知设备"（含离线的），识别在线机型，绑定坐标 Profile。

跟单纯"扫一遍 adb devices"的区别：设备列表显示的是**所有添加/配对过的手机**，不管
当前在不在线——20 台手机不可能一直全部在线，用户需要一直能看到"我有哪些设备"，
而不是一台暂时没插线/没连网就从列表里消失、下次还得重新走一遍添加流程。
"""
import subprocess
import re
from dataclasses import dataclass

from adb import Adb, _run_hidden
import device_profile
import device_registry

_AUTO_ALIAS_RE = re.compile(r"^手机-\d{2}$")


@dataclass
class Device:
    serial: str             # adb 连接串（USB 序列号或 ip:port）；离线时为空字符串
    hw_serial: str          # ro.serialno，硬件序列号，跨连接方式稳定，设备身份靠它认
    model: str              # ro.product.model（离线设备用最后一次已知的机型）
    alias: str = ""         # 手机-01 / 手机-02 ...（或用户自定义备注名）
    profile: dict | None = None   # 该机型的坐标 Profile，None 表示未标定
    adb: Adb | None = None
    online: bool = True
    platform: str = "android"
    ios: object | None = None

    @property
    def ready(self) -> bool:
        """能不能立即拿去发布：在线 + 该机型已标定坐标。"""
        if self.platform == "ios":
            return self.online
        return self.online and self.profile is not None

    def rename(self, new_alias: str):
        """改备注名并持久化到已知设备清单（按硬件序列号存，重连/换端口/离线后依然认得）。"""
        self.alias = new_alias
        device_registry.upsert(self.hw_serial, alias=new_alias)


def _list_serials(adb_path: str) -> list[str]:
    """裸 `adb devices`，列出当前在线的设备号（不含未授权/离线的）。
    无线调试的手机会同时列出 ip:port 和 mDNS 自动发现的 adb-xxx._adb-tls-connect._tcp
    两个"序列号"，其实是同一台物理设备。这里不能直接过滤 mDNS：换 WiFi 后有时只有
    mDNS 项先出现；而且 Windows 会把重名 mDNS 展示成 `adb-xxx (2)._adb...`，序列号里
    带空格，不能用固定列 split。去重放到 discover_devices 里按硬件序列号做。"""
    proc = _run_hidden([adb_path, "devices"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
    out = proc.stdout.decode("utf-8", "replace")
    serials = []
    for line in out.splitlines()[1:]:
        parts = line.split()
        if not parts:
            continue
        status_idx = next((i for i, p in enumerate(parts) if p in {"device", "offline", "unauthorized"}), -1)
        if status_idx > 0 and parts[status_idx] == "device":
            serials.append(" ".join(parts[:status_idx]))

    def _sort_key(serial: str):
        is_mdns = "_adb-tls-connect._tcp" in serial
        return (1 if is_mdns else 0, serial)

    return sorted(serials, key=_sort_key)


def discover_devices(adb_path: str) -> list[Device]:
    """扫描全部已知设备。在线的：现查机型 + Profile，同时把最新信息记进已知清单；
    已知清单里这次没扫到在线的：用清单里最后一次记录的机型/别名展示，标记离线。"""
    known = {kd.hw_serial: kd for kd in device_registry.list_known()}
    seen_hw = set()
    devices = []

    # 已知清单里已用过的别名，用来给全新设备分配不重复的默认序号
    used_defaults = {kd.alias for kd in known.values()}
    next_idx = 1

    def _next_default_alias():
        nonlocal next_idx
        while f"手机-{next_idx:02d}" in used_defaults:
            next_idx += 1
        alias = f"手机-{next_idx:02d}"
        used_defaults.add(alias)
        next_idx += 1
        return alias

    def _default_alias_for_profile(profile: dict | None) -> str:
        base = profile.get("display_name") if profile else ""
        if not base:
            return _next_default_alias()
        alias = base
        suffix = 2
        while alias in used_defaults:
            alias = f"{base}-{suffix:02d}"
            suffix += 1
        used_defaults.add(alias)
        return alias

    for serial in _list_serials(adb_path):
        adb = Adb(adb_path, serial)
        try:
            model = adb.shell("getprop ro.product.model").strip()
        except Exception:
            model = "未知机型"
        try:
            hw_serial = adb.shell("getprop ro.serialno").strip()
        except Exception:
            hw_serial = serial  # 取不到硬件序列号时退化用连接串（离线后可能认不出，不影响本次使用）
        if hw_serial in seen_hw:
            continue

        profile = device_profile.get_profile(model)
        kd = known.get(hw_serial)
        if kd and kd.alias and not _AUTO_ALIAS_RE.match(kd.alias):
            alias = kd.alias
        else:
            alias = _default_alias_for_profile(profile)
        device_registry.upsert(hw_serial, alias=alias, model=model, last_seen_addr=serial, platform="android")
        seen_hw.add(hw_serial)

        devices.append(Device(
            serial=serial,
            hw_serial=hw_serial,
            model=model,
            alias=alias,
            profile=profile,
            adb=adb,
            online=True,
            platform="android",
        ))

    try:
        import ios_device

        for item in ios_device.list_devices():
            udid = item["udid"]
            kd = known.get(udid)
            if kd and kd.alias and not _AUTO_ALIAS_RE.match(kd.alias):
                alias = kd.alias
            else:
                alias = item.get("name") or _next_default_alias()
            model = f"{item.get('model') or 'iPhone'} iOS {item.get('version') or ''}".strip()
            device_registry.upsert(udid, alias=alias, model=model, last_seen_addr="USB", platform="ios")
            seen_hw.add(udid)
            devices.append(Device(
                serial=udid,
                hw_serial=udid,
                model=model,
                alias=alias,
                profile=None,
                adb=None,
                online=True,
                platform="ios",
                ios=ios_device.IosController(udid),
            ))
    except Exception:
        # Android 主流程不能因为 iPhone 依赖缺失而不可用。
        pass

    for hw_serial, kd in known.items():
        if hw_serial in seen_hw:
            continue
        platform = kd.platform or "android"
        devices.append(Device(
            serial="",
            hw_serial=hw_serial,
            model=kd.model or "未知机型",
            alias=kd.alias,
            profile=device_profile.get_profile(kd.model) if platform == "android" and kd.model else None,
            adb=None,
            online=False,
            platform=platform,
        ))

    return devices


def summarize(devices: list[Device]) -> str:
    lines = []
    for d in devices:
        if not d.online:
            status = "离线"
        elif d.platform == "ios":
            status = "iPhone半自动"
        else:
            status = "就绪" if d.ready else "⚠ 该机型未标定坐标"
        lines.append(f"  {d.alias} — {d.model} ({d.serial or '离线'}) — {status}")
    return "\n".join(lines) if lines else "  （未检测到任何设备，先用「添加设备」接入）"
