"""
Export/import local handover state for moving the controller to another PC.

This intentionally contains only ADB trust files and this app's device registry.
Do not add photos, logs, activation files, or task content here.
"""
import json
import shutil
from datetime import datetime
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import device_registry


ADB_TRUST_FILES = ("adbkey", "adbkey.pub", "adb_known_hosts.pb")
ANDROID_DIR = Path.home() / ".android"


def _backup_existing(path: Path, ts: str):
    if path.exists():
        backup = Path(f"{path}.bak-{ts}")
        shutil.copy2(path, backup)


def export_config(zip_path: str | Path) -> list[str]:
    zip_path = Path(zip_path)
    if zip_path.suffix.lower() != ".zip":
        zip_path = zip_path.with_suffix(".zip")
    zip_path.parent.mkdir(parents=True, exist_ok=True)

    exported: list[str] = []
    manifest = {
        "name": "朋友圈发布助手连接配置",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "contains": [],
    }
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as zf:
        for name in ADB_TRUST_FILES:
            src = ANDROID_DIR / name
            if src.exists():
                arcname = f"android/{name}"
                zf.write(src, arcname)
                exported.append(arcname)
                manifest["contains"].append(arcname)

        if device_registry.REGISTRY_FILE.exists():
            arcname = "app/device_registry.json"
            zf.write(device_registry.REGISTRY_FILE, arcname)
            exported.append(arcname)
            manifest["contains"].append(arcname)

        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))

    return exported


def import_config(zip_path: str | Path) -> list[str]:
    zip_path = Path(zip_path)
    imported: list[str] = []
    ts = datetime.now().strftime("%Y%m%d%H%M%S")

    with ZipFile(zip_path, "r") as zf:
        names = set(zf.namelist())

        ANDROID_DIR.mkdir(parents=True, exist_ok=True)
        for name in ADB_TRUST_FILES:
            arcname = f"android/{name}"
            if arcname in names:
                target = ANDROID_DIR / name
                _backup_existing(target, ts)
                target.write_bytes(zf.read(arcname))
                imported.append(arcname)

        if "app/device_registry.json" in names:
            target = device_registry.REGISTRY_FILE
            target.parent.mkdir(parents=True, exist_ok=True)
            _backup_existing(target, ts)
            target.write_bytes(zf.read("app/device_registry.json"))
            imported.append("app/device_registry.json")

    return imported
