"""
安卓端朋友圈发布流程 —— 全程 ADB 截屏 + 按屏幕比例坐标点击。

刻意不用无障碍服务（AccessibilityService）：微信 8.0.52+ 对无障碍节点做了混淆，
读到的元素是乱的；而坐标点击在系统输入层更接近真人，微信不容易封。代价是坐标依赖 UI 布局，
但客户确认发圈这几个按钮位置稳定、用户习惯不会乱动，所以可接受。

坐标全部用屏幕比例（0~1）表达，UI 不变的前提下天然跨分辨率——不同机型只要布局一致就通用，
不需要每台重新标定。比例值来自 2026-07-05 在小米15(1200x2670, HyperOS2) 上实测跑通的流程。

中文/emoji/换行文案：走 ADBKeyboard 输入法的 base64 广播通道（安卓唯一留给程序输入文字的
合法通道，因为 adb 无法写系统剪贴板、input text 只支持 ASCII）。整段文案在 PC 端准备好，
base64 编码后一条广播发过去原样输入——emoji、换行、排版一字不差，零特殊处理。
2026-07-05 实测：3图 + "中文+emoji😄+换行" 完整发布成功。

⚠ 仍待健壮化（见 TODO）：
  - "朋友圈素材"文件夹在相册列表里的位置写死了比例坐标（取决于设备有多少相册），
    稳健做法是截图 OCR/模板匹配定位该文件夹项
  - 多图目前只支持一行 3 张，超过要处理换行/滚动
"""
import base64
import time
from dataclasses import dataclass


# ── 发圈流程各步骤的比例坐标（实测值，UI 不变则跨分辨率通用）──────────
COORDS = {
    "discover_tab":     (0.620, 0.950),  # 底部"发现"tab（从微信首页进入时用）
    "moments_camera":   (0.929, 0.080),  # 朋友圈页右上角相机图标
    "menu_from_album":  (0.498, 0.885),  # 弹出菜单"从手机相册选择"
    "album_dropdown":   (0.498, 0.079),  # 相册顶部"图片和视频 ∨"下拉
    "folder_item":      (0.300, 0.452),  # "朋友圈素材"文件夹项（位置不稳，见 TODO）
    "album_done":       (0.866, 0.959),  # 相册"完成"按钮
    "caption_input":    (0.222, 0.145),  # 发表页"这一刻的想法..."文案框
    "post_button":      (0.893, 0.079),  # 发表页右上角"发表"绿色按钮
}

# 文件夹内图片选择圈的比例坐标：同一行 ry 固定，每列 rx 不同（3 列布局）
IMAGE_CHECK_ROW_RY = 0.127
IMAGE_CHECK_COL_RX = [0.200, 0.451, 0.703]  # 第 1/2/3 列

ADBKEYBOARD_IME = "com.android.adbkeyboard/.AdbIME"

STEP_WAIT = 2.0


@dataclass
class PublishResult:
    success: bool
    reason: str = ""


def _type_unicode(adb, text: str):
    """通过 ADBKeyboard 输入任意 Unicode 文本（中文/emoji/换行）。
    调用前需已切到 ADBKeyboard 输入法（见 publish_moment 的 IME 切换）。"""
    b64 = base64.b64encode(text.encode("utf-8")).decode("ascii")
    adb.shell(f"am broadcast -a ADB_INPUT_B64 --es msg {b64}")


def publish_moment(adb, image_count: int, caption: str = "",
                   restore_ime: str | None = None) -> PublishResult:
    """
    在已在朋友圈页的设备上发一条朋友圈（多图 + 中文文案）。
    adb: adb.Adb 实例
    image_count: 要选的图片数量（图片须已 push 到"朋友圈素材"文件夹，按文件名排序）
    caption: 文案（支持中文/emoji/换行；需设备已装 ADBKeyboard）
    restore_ime: 发完把输入法切回的 id（如搜狗），None 则不切回

    前置：调用方已确保在朋友圈页。返回 PublishResult。
    （失败检测/重试复用 PC 版 scheduler 思路，串多设备调度时在外层做。）
    """
    def tap(name: str):
        rx, ry = COORDS[name]
        adb.tap_ratio(rx, ry)
        time.sleep(STEP_WAIT)

    prev_ime = None
    try:
        adb.ensure_online()

        # Step 4: 相机 → 5: 从相册选择 → 6: 切"朋友圈素材"文件夹
        tap("moments_camera")
        tap("menu_from_album")
        tap("album_dropdown")
        tap("folder_item")

        # Step 6.2: 按顺序勾选前 image_count 张（点击顺序即图片排序）
        n = max(1, min(image_count, len(IMAGE_CHECK_COL_RX)))  # 目前一行 3 张，多图需扩展
        for i in range(n):
            adb.tap_ratio(IMAGE_CHECK_COL_RX[i], IMAGE_CHECK_ROW_RY)
            time.sleep(0.6)
        time.sleep(0.8)

        # Step 6.3: 完成
        tap("album_done")

        # Step 7: 中文文案（切到 ADBKeyboard → 输入）
        if caption:
            prev_ime = adb.shell("settings get secure default_input_method").strip()
            adb.shell(f"ime enable {ADBKEYBOARD_IME}")
            adb.shell(f"ime set {ADBKEYBOARD_IME}")
            time.sleep(0.6)
            tap("caption_input")
            _type_unicode(adb, caption)
            time.sleep(1.5)

        # Step 7.2: 发表
        tap("post_button")
        time.sleep(2.0)

        return PublishResult(True)
    except Exception as e:
        return PublishResult(False, f"发布异常: {e}")
    finally:
        # 恢复用户输入法（优先 restore_ime，否则切回发布前的）
        target_ime = restore_ime or prev_ime
        if target_ime and caption:
            try:
                adb.shell(f"ime set {target_ime}")
            except Exception:
                pass
