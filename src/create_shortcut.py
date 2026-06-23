"""
创建带图标的 Windows 快捷方式
"""
import os
import sys
from pathlib import Path

# 需要安装 pywin32: pip install pywin32
try:
    from win32com.client import Dispatch
except ImportError:
    print("请先安装 pywin32: pip install pywin32")
    sys.exit(1)

# 路径
repo_dir = Path(__file__).parent.parent
src_dir = repo_dir / "src"
logo_py = src_dir / "logo.py"

# 生成图标文件
print("正在生成图标文件...")
os.chdir(src_dir)
sys.path.insert(0, str(src_dir))

from logo import make_logo
from PIL import Image

# 生成多种尺寸的图标
img = make_logo(256)
icon_path = repo_dir / "app_icon.ico"

# PIL 保存 ICO
img.save(str(icon_path), format='ICO', sizes=[(16,16), (32,32), (48,48), (64,64), (128,128), (256,256)])
print(f"图标已保存: {icon_path}")

# 创建快捷方式
shortcut_path = repo_dir / "朋友圈发布助手.lnk"
target_path = sys.executable  # python.exe
working_dir = str(src_dir)
arguments = f"{src_dir / 'main.py'}"

shell = Dispatch('WScript.Shell')
shortcut = shell.CreateShortCut(str(shortcut_path))
shortcut.TargetPath = target_path
shortcut.WorkingDirectory = working_dir
shortcut.Arguments = arguments
shortcut.IconLocation = str(icon_path) + ",0"
shortcut.Description = "朋友圈发布助手 v1.3"
shortcut.Save()

print(f"快捷方式已创建: {shortcut_path}")
print("\n使用方法:")
print(f"  双击运行: {shortcut_path}")
print("  任务栏将显示绿色神经网络图标")
