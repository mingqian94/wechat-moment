"""
安卓端朋友圈发布流程 —— 全程 ADB 截屏 + 按屏幕比例坐标点击。

刻意不用无障碍服务（AccessibilityService）：微信 8.0.52+ 对无障碍节点做了混淆，
读到的元素是乱的；而坐标点击在系统输入层更接近真人，微信不容易封。代价是坐标依赖 UI 布局，
但客户确认发圈这几个按钮位置稳定、用户习惯不会乱动，所以可接受。

坐标全部用屏幕比例（0~1）表达，UI 不变的前提下天然跨分辨率——不同机型只要布局一致就通用，
不需要每台重新标定。比例值来自 2026-07-02 在小米15(1200x2670, HyperOS2) 上实测跑通的流程。

⚠ 两个还没解决的工程点（见 TODO）：
  1. 中文文案输入：adb input text 只支持 ASCII，中文要装 ADBKeyboard 或走剪贴板方案
  2. "朋友圈素材"文件夹在相册列表里的位置不固定（取决于设备有多少相册），
     现在写死了比例坐标，稳健做法是截图 OCR/模板匹配找到该文件夹项——待补
"""
import time
from dataclasses import dataclass


# ── 发圈流程各步骤的比例坐标（实测值，UI 不变则跨分辨率通用）──────────
# 每个值是 (rx, ry)，屏幕宽高的比例
COORDS = {
    "discover_tab":     (0.620, 0.950),  # 底部"发现"tab
    "moments_camera":   (0.929, 0.080),  # 朋友圈页右上角相机图标
    "menu_from_album":  (0.498, 0.885),  # 弹出菜单"从手机相册选择"
    "album_dropdown":   (0.498, 0.079),  # 相册顶部"图片和视频 ∨"下拉
    # ↓ 相册文件夹项位置不稳定，见 TODO；这是"朋友圈素材"当时的位置
    "folder_item":      (0.300, 0.452),
    "first_image_check":(0.200, 0.127),  # 文件夹内第1张图右上角选择圈
    "album_done":       (0.866, 0.959),  # 相册"完成"按钮
    "caption_input":    (0.222, 0.145),  # 发表页"这一刻的想法..."文案框
    "post_button":      (0.893, 0.079),  # 发表页右上角"发表"绿色按钮
}

# 各步骤之间的等待（秒），给微信页面切换/加载留时间
STEP_WAIT = 2.0


@dataclass
class PublishResult:
    success: bool
    reason: str = ""


def publish_moment(adb, image_remote_paths: list[str], caption: str = "",
                   enter_from: str = "moments") -> PublishResult:
    """
    在已连接的设备上发一条朋友圈。
    adb: adb.Adb 实例
    image_remote_paths: 已经 push 到"朋友圈素材"文件夹的图片手机路径（用于确认数量）
    caption: 文案（中文输入未实现，见 TODO）
    enter_from: "moments" 表示已在朋友圈页；"wechat_home" 表示从微信首页开始

    返回 PublishResult。注意：这一版是把实测跑通的坐标序列固化下来，
    还没接失败检测/重试（那部分复用 PC 版 scheduler 的思路，下一步做）。
    """
    def tap(name: str):
        rx, ry = COORDS[name]
        adb.tap_ratio(rx, ry)
        time.sleep(STEP_WAIT)

    try:
        adb.ensure_online()

        # Step 1-3: 进到朋友圈页（enter_from=="moments" 时假设已在朋友圈页）
        # TODO: enter_from=="wechat_home" 时需补"发现→朋友圈"入口坐标（本次实测因草稿
        #       恢复直接落在了朋友圈页，没走到这两步，坐标待补）
        if enter_from == "wechat_home":
            return PublishResult(False, "从微信首页进入的坐标还没标定（发现→朋友圈入口待补）")

        # Step 4: 点右上角相机
        tap("moments_camera")
        # Step 5: 菜单选"从手机相册选择"
        tap("menu_from_album")
        # Step 6: 切到"朋友圈素材"文件夹
        tap("album_dropdown")
        tap("folder_item")
        # Step 6.2: 选第1张图（多图/顺序选择待扩展）
        tap("first_image_check")
        # Step 6.3: 完成
        tap("album_done")

        # Step 7: 文案（TODO：中文输入）
        if caption:
            # adb input text 不支持中文，这里先跳过，避免发出乱码
            # 方案：安装 ADBKeyboard.apk，切换输入法后用 broadcast 发文本
            pass

        # Step 7.2: 发表
        tap("post_button")

        return PublishResult(True)
    except Exception as e:
        return PublishResult(False, f"发布异常: {e}")
