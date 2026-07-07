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

坐标不再是模块级全局常量——手机型号/分辨率不统一（客户 20 台机型不一样），必须按
机型取用各自的 Profile（见 device_profile.py）。DEFAULT_PROFILE 是 2026-07-05 在
小米15 上实测跑通的那份，没传 profile 参数时用它兜底（方便单测/没有 Profile 库时用）。
"""
import base64
import random
import time
from dataclasses import dataclass


# 兜底 Profile：小米15 (1200x2670, HyperOS2) 实测跑通的坐标，没传 profile 时使用
DEFAULT_PROFILE = {
    "coords": {
        "discover_tab":     (0.620, 0.950),
        "moments_camera":   (0.929, 0.080),
        "menu_from_album":  (0.498, 0.885),
        "album_dropdown":   (0.498, 0.079),
        "folder_item":      (0.300, 0.452),
        "album_done":       (0.866, 0.959),
        "caption_input":    (0.222, 0.145),
        "post_button":      (0.893, 0.079),
    },
    "image_check_row_ry": 0.127,
    "image_check_col_rx": [0.200, 0.451, 0.703],
}

ADBKEYBOARD_IME = "com.android.adbkeyboard/.AdbIME"

# 各步骤等待都用随机区间，不用固定整数秒——固定节奏本身就是机器特征（跟 PC 版一个教训）。
# 步骤间常规停顿
STEP_WAIT = (1.6, 3.4)
# 选图时每张之间的小停顿
PICK_WAIT = (0.4, 0.9)
# 发表前的"看一眼再发"停顿——关键的对外动作，模拟真人确认，故意给足且随机
REVIEW_WAIT = (2.8, 5.6)


def _sleep(rng: tuple[float, float]):
    time.sleep(random.uniform(*rng))


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
                   restore_ime: str | None = None, profile: dict | None = None,
                   start_from_wechat_home: bool = False,
                   on_step=None) -> PublishResult:
    """
    发一条朋友圈（多图 + 中文文案）。
    adb: adb.Adb 实例
    image_count: 要选的图片数量（图片须已 push 到"朋友圈素材"文件夹，按文件名排序）
    caption: 文案（支持中文/emoji/换行；需设备已装 ADBKeyboard）
    restore_ime: 发完把输入法切回的 id（如搜狗），None 则不切回
    profile: 该设备机型的坐标 Profile（device_profile.get_profile 的返回值）；
             None 时用 DEFAULT_PROFILE 兜底（仅小米15 验证过，其他机型必须传各自 profile）
    start_from_wechat_home: True 时先从微信首页导航到朋友圈页（需要 profile["coords"] 里有
             discover_tab + moments_entry 这两个坐标——这两个坐标**按机型各自标定**，不是
             通用值；没标定的机型传 True 会直接返回失败，不会瞎猜坐标去点）。
             默认 False：假定设备已经停在朋友圈页（当前调度流程的实际用法）。
    on_step: 可选回调 on_step(str)，每完成一个可辨认的步骤就调用一次，用于把发布过程
             逐步打进运行日志（"点击相机"、"选择素材"……），而不是只有最终成功/失败一行。

    返回 PublishResult。（失败检测/重试复用 PC 版 scheduler 思路，串多设备调度时在外层做。）
    """
    profile = profile or DEFAULT_PROFILE
    coords = profile["coords"]
    check_row_ry = profile["image_check_row_ry"]
    check_col_rx = profile["image_check_col_rx"]

    def _step(msg: str):
        if on_step:
            on_step(msg)

    def tap(name: str, step_msg: str | None = None):
        rx, ry = coords[name]
        adb.tap_ratio(rx, ry)
        if step_msg:
            _step(step_msg)
        _sleep(STEP_WAIT)

    prev_ime = None
    try:
        adb.ensure_online()

        if start_from_wechat_home:
            if "discover_tab" not in coords or "moments_entry" not in coords:
                return PublishResult(False, "该机型未标定微信首页→朋友圈的导航坐标，无法自动导航"
                                             "（需要先按 README「新增机型标定」流程标定 discover_tab/moments_entry）")
            tap("discover_tab", "打开微信「发现」")
            tap("moments_entry", "进入朋友圈")

        # Step 4: 相机 → 5: 从相册选择 → 6: 切"朋友圈素材"文件夹
        tap("moments_camera", "点击相机图标")
        tap("menu_from_album", "选择「从手机相册选择」")
        tap("album_dropdown", "打开相册文件夹列表")
        tap("folder_item", "切换到「朋友圈素材」文件夹")

        # Step 6.2: 按顺序勾选前 image_count 张（点击顺序即图片排序）
        n = max(1, min(image_count, len(check_col_rx)))  # 目前一行 3 张，多图需扩展
        for i in range(n):
            adb.tap_ratio(check_col_rx[i], check_row_ry)
            _sleep(PICK_WAIT)
        _step(f"已选择 {n} 张素材")
        _sleep(STEP_WAIT)

        # Step 6.3: 完成
        tap("album_done", "确认选图")

        # Step 7: 中文文案（切到 ADBKeyboard → 输入）
        if caption:
            prev_ime = adb.shell("settings get secure default_input_method").strip()
            adb.shell(f"ime enable {ADBKEYBOARD_IME}")
            adb.shell(f"ime set {ADBKEYBOARD_IME}")
            _sleep(PICK_WAIT)
            tap("caption_input")
            _type_unicode(adb, caption)
            _step("输入文案")
            _sleep(STEP_WAIT)  # 打完字停顿，像真人写完看一眼

        # Step 7.2: 发表前"看一眼再发"，关键对外动作故意慢下来避免机器节奏
        _sleep(REVIEW_WAIT)
        tap("post_button", "点击发表")
        _sleep(STEP_WAIT)

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
