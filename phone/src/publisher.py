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
import io
import random
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, ImageStat


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
    "picker_grid": {
        "cols": 4,
        "top_ry": 0.108,
        "cell_ry": 0.112,
        "select_row_ry": 0.127,
        "select_col_rx": [0.200, 0.451, 0.703],
    },
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


def _list_enabled_imes(adb) -> list[str]:
    out = adb.shell("ime list -s", timeout=10)
    return [line.strip() for line in out.splitlines() if line.strip()]


def _choose_restore_ime(adb, preferred: str | None, prev_ime: str | None) -> str | None:
    candidates = [preferred, prev_ime]
    candidates += _list_enabled_imes(adb)
    for ime in candidates:
        if ime and ime != ADBKEYBOARD_IME:
            return ime
    return None


def _restore_user_keyboard(adb, preferred: str | None, prev_ime: str | None):
    target_ime = _choose_restore_ime(adb, preferred, prev_ime)
    if not target_ime:
        return
    current = adb.shell("settings get secure default_input_method", timeout=10).strip()
    if current != target_ime:
        adb.shell(f"ime set {target_ime}", timeout=10)


def _median_rgb(img: Image.Image) -> tuple[int, int, int]:
    """取缩略图中位色，用来粗略确认相册顶部是否是刚推入的素材。"""
    fitted = ImageOps.fit(img.convert("RGB"), (64, 64), method=Image.Resampling.LANCZOS)
    # 去掉选择圈/边线影响，取中间区域
    core = fitted.crop((8, 8, 56, 56))
    stat = ImageStat.Stat(core)
    return tuple(int(v) for v in stat.median)


def _color_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def _expected_thumb(local_path: Path) -> Image.Image:
    """读取本地素材用于相册缩略图校验。视频取第一帧，图片直接读取。"""
    suffix = local_path.suffix.lower()
    if suffix in {".mp4", ".mov"}:
        import cv2

        # OpenCV 在 Windows 上同样可能读不了中文路径；复制到 ASCII 临时路径再取首帧。
        with tempfile.TemporaryDirectory() as tmp:
            tmp_video = Path(tmp) / f"video{suffix}"
            shutil.copy2(local_path, tmp_video)
            cap = cv2.VideoCapture(str(tmp_video))
            try:
                ok, frame = cap.read()
            finally:
                cap.release()
        if not ok:
            raise ValueError(f"无法读取视频首帧: {local_path}")
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        return Image.fromarray(frame)
    return Image.open(local_path)


def _is_video_task(local_paths: list[str] | None) -> bool:
    return bool(
        local_paths
        and len(local_paths) == 1
        and Path(local_paths[0]).suffix.lower() in {".mp4", ".mov"}
    )


def _verify_picker_top_images(adb, expected_images: list[str], profile: dict,
                              on_step=None) -> tuple[bool, str]:
    """确认系统相册顶部前 N 个缩略图和刚推入的本地素材一致。

    这是发布前的硬闸：如果微信相册没有展示刚推入的素材，直接停在选择器页，不继续点
    完成/发表，避免误选用户真实照片。
    """
    if not expected_images:
        return False, "没有传入待验证素材，拒绝盲选相册图片"

    grid = profile.get("picker_grid", {})
    cols = int(grid.get("cols", 4))
    top_ry = float(grid.get("top_ry", 0.108))
    cell_ry = float(grid.get("cell_ry", 0.112))

    data = adb.screencap()
    screen = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = screen.size
    cell_w = w / cols
    y0 = int(h * top_ry)
    y1 = int(h * (top_ry + cell_ry))

    distances = []
    for i, local in enumerate(expected_images):
        if i >= cols:
            return False, "当前只支持验证首行素材，单次最多 4 张"
        local_path = Path(local)
        if not local_path.exists():
            return False, f"本地素材不存在，无法校验: {local_path}"

        x0 = int(i * cell_w)
        x1 = int((i + 1) * cell_w)
        thumb = screen.crop((x0, y0, x1, y1))
        try:
            expected = _expected_thumb(local_path)
        except Exception as e:
            return False, f"本地素材缩略图读取失败，拒绝盲选: {e}"
        dist = _color_distance(_median_rgb(expected), _median_rgb(thumb))
        distances.append(round(dist, 1))

    # 颜色中位数不是精确图片识别，只作为误选保护；阈值偏宽，主要拦截完全不相干的照片/证件图。
    if any(d > 90 for d in distances):
        return False, f"相册顶部素材校验失败，颜色距离={distances}，疑似没有停在刚推入的素材列表"

    if on_step:
        on_step(f"相册顶部素材校验通过（颜色距离={distances}）")
    return True, ""


def publish_moment(adb, image_count: int, caption: str = "",
                   restore_ime: str | None = None, profile: dict | None = None,
                   start_from_wechat_home: bool = False,
                   expected_images: list[str] | None = None,
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
    expected_images: 本地素材路径。传入后会在相册选择页截图校验顶部缩略图确实是这些素材；
             校验失败会直接返回失败，避免误选用户真实照片。
    on_step: 可选回调 on_step(str)，每完成一个可辨认的步骤就调用一次，用于把发布过程
             逐步打进运行日志（"点击相机"、"选择素材"……），而不是只有最终成功/失败一行。

    返回 PublishResult。（失败检测/重试复用 PC 版 scheduler 思路，串多设备调度时在外层做。）
    """
    profile = profile or DEFAULT_PROFILE
    coords = profile["coords"]
    picker_grid = profile.get("picker_grid", {})
    check_row_ry = picker_grid.get("select_row_ry", profile["image_check_row_ry"])
    check_col_rx = picker_grid.get("select_col_rx", profile["image_check_col_rx"])

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
        prev_ime = adb.shell("settings get secure default_input_method").strip()

        if start_from_wechat_home:
            if "discover_tab" not in coords or "moments_entry" not in coords:
                return PublishResult(False, "该机型未标定微信首页→朋友圈的导航坐标，无法自动导航"
                                             "（需要先按 README「新增机型标定」流程标定 discover_tab/moments_entry）")
            tap("discover_tab", "打开微信「发现」")
            tap("moments_entry", "进入朋友圈")

        # Step 4: 相机 → 5: 从相册选择。刚推入的素材应出现在系统相册顶部；
        # 后续先校验顶部缩略图，再允许勾选，避免误选用户真实照片。
        tap("moments_camera", "点击相机图标")
        tap("menu_from_album", "选择「从手机相册选择」")

        ok, reason = _verify_picker_top_images(adb, expected_images or [], profile, _step)
        if not ok:
            return PublishResult(False, reason)

        # Step 6.2: 按顺序勾选前 image_count 张（点击顺序即图片排序）
        n = max(1, min(image_count, len(check_col_rx)))  # 目前一行 3 张，多图需扩展
        for i in range(n):
            adb.tap_ratio(check_col_rx[i], check_row_ry)
            _sleep(PICK_WAIT)
        _step(f"已选择 {n} 张素材")
        _sleep(STEP_WAIT)

        # Step 6.3: 完成
        tap("album_done", "确认选图")
        if _is_video_task(expected_images):
            # 微信选视频后会先进视频编辑页，仍需再点一次“完成”才回到朋友圈编辑页。
            tap("album_done", "确认视频编辑")

        # Step 7: 中文文案（切到 ADBKeyboard → 输入）
        if caption:
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
        # 恢复用户输入法。若发布前已经停在 ADBKeyboard，则切到任一已启用的非 ADBKeyboard 输入法，
        # 避免业务人员发完后手机键盘仍是 ADBKeyboard。
        try:
            _restore_user_keyboard(adb, restore_ime, prev_ime)
        except Exception:
            pass
