"""
已知设备清单 —— 记住所有添加/配对过的手机（按硬件序列号），不管当前在不在线都会
出现在界面列表里；配合定时自动扫描，标注哪些在线、哪些暂时连不上。

这跟 device_alias.py（只存别名）的区别：这里是完整的"设备台账"，一台设备第一次被
发现/添加后就永久记进来，之后即使它暂时离线（没插线、没开机、无线断了），程序依然
"认得"这台设备、显示它在列表里——不会因为暂时连不上就从界面消失，逼用户重新走一遍
"添加设备"流程。
"""
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

def _app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    root = Path(base) if base else Path.home() / "AppData" / "Local"
    path = root / "朋友圈发布助手"
    path.mkdir(parents=True, exist_ok=True)
    return path


REGISTRY_FILE = _app_data_dir() / "device_registry.json"


@dataclass
class KnownDevice:
    hw_serial: str
    alias: str
    model: str = ""            # 最后一次已知机型（离线时用它判断 Profile 是否就绪）
    last_seen_addr: str = ""   # 最后一次成功连接的地址，仅供参考展示（无线 ip 会变，不能用来重连）


def _load_all() -> dict[str, dict]:
    if REGISTRY_FILE.exists():
        try:
            return json.loads(REGISTRY_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_all(registry: dict[str, dict]):
    REGISTRY_FILE.write_text(json.dumps(registry, ensure_ascii=False, indent=2), encoding="utf-8")


def list_known() -> list[KnownDevice]:
    return [KnownDevice(hw_serial=k, **v) for k, v in _load_all().items()]


def upsert(hw_serial: str, alias: str | None = None, model: str | None = None,
           last_seen_addr: str | None = None):
    """新设备第一次出现，或已知设备信息有更新（换了机型识别结果/新的连接地址）时调用。
    只更新传了值的字段，alias 已存在时不会被空值覆盖掉。"""
    registry = _load_all()
    cur = registry.get(hw_serial, {"alias": "", "model": "", "last_seen_addr": ""})
    if alias:
        cur["alias"] = alias
    if model:
        cur["model"] = model
    if last_seen_addr:
        cur["last_seen_addr"] = last_seen_addr
    registry[hw_serial] = cur
    _save_all(registry)


def remove(hw_serial: str):
    registry = _load_all()
    if hw_serial in registry:
        del registry[hw_serial]
        _save_all(registry)
