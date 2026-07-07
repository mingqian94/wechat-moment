# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

block_cipher = None
repo = Path.cwd()
phone_src = repo / "phone" / "src"
platform_tools = repo / "phone" / "platform-tools"

a = Analysis(
    [str(phone_src / "main.py")],
    pathex=[str(phone_src)],
    binaries=[],
    datas=[],
    hiddenimports=[
        "PIL._tkinter_finder",
        "cv2",
        "numpy",
        "adb",
        "auth",
        "device_manager",
        "device_profile",
        "device_registry",
        "diagnostics",
        "distributor",
        "logger",
        "publisher",
        "scheduler",
        "gui.activation",
        "gui.main_window",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="朋友圈发布助手",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    Tree(str(platform_tools), prefix="platform-tools"),
    strip=False,
    upx=True,
    upx_exclude=[],
    name="朋友圈发布助手",
)
