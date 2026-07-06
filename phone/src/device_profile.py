"""
机型坐标 Profile 库 —— 手机型号/分辨率不统一，坐标不能全局写死一套。

每个机型（`ro.product.model`）对应一份坐标 Profile（比例坐标，见 publisher.py 的
COORDS 结构）。新机型接入前必须先标定（开发者用 adb 截屏走一遍流程记录坐标，见
项目 README「新增机型标定」一节），标定结果存进这个 JSON 文件，之后同型号所有设备
直接复用，不用每台单独标定。

Profile 文件是可写运行时文件（放在 exe 旁边，不是仓库里的静态资源），跟 activation.dat
处理方式一样——本地这几个（.venv/build 产物）都不进仓库，只有下面这个 SEED_PROFILES
里内置的默认值会随代码分发。
"""
import json
import sys
from pathlib import Path

_APP_DIR = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).parent.parent
PROFILE_FILE = _APP_DIR / "device_profiles.json"

# 2026-07-05/06 在小米15 (1200x2670, HyperOS2) 上实测跑通的坐标，作为内置种子 Profile，
# 只对这一个机型有效——不同机型分辨率/UI布局不统一，坐标不能跨机型套用，新机型接入前
# 必须照 README「新增机型标定」的流程各自标定一遍，不能假设这份坐标通用。
# moments_entry（微信首页"发现"→"朋友圈"入口）是 2026-07-06 新标定的，同样只对本机型有效；
# 缺这个键的机型，publisher.py 会跳过自动导航，要求设备已停在朋友圈页（不会瞎猜坐标去点）。
SEED_PROFILES = {
    "24129PN74C": {  # 小米15 的 ro.product.model
        "display_name": "小米15",
        "coords": {
            "discover_tab":     [0.620, 0.950],
            "moments_entry":    [0.204, 0.1375],
            "moments_camera":   [0.929, 0.080],
            "menu_from_album":  [0.498, 0.885],
            "album_dropdown":   [0.498, 0.079],
            "folder_item":      [0.300, 0.452],
            "album_done":       [0.866, 0.959],
            "caption_input":    [0.222, 0.145],
            "post_button":      [0.893, 0.079],
        },
        "image_check_row_ry": 0.127,
        "image_check_col_rx": [0.200, 0.451, 0.703],
    }
}


def _load_all() -> dict:
    if PROFILE_FILE.exists():
        try:
            return json.loads(PROFILE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return dict(SEED_PROFILES)


def _save_all(profiles: dict):
    PROFILE_FILE.write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")


def get_profile(model: str) -> dict | None:
    """按机型（ro.product.model）查 Profile，没有返回 None（需要标定）。"""
    return _load_all().get(model)


def save_profile(model: str, profile: dict):
    """标定完成后保存一个机型的 Profile（覆盖式）。"""
    profiles = _load_all()
    profiles[model] = profile
    _save_all(profiles)


def list_known_models() -> list[str]:
    return list(_load_all().keys())


def ensure_seeded():
    """首次运行时把内置种子 Profile 落盘，之后可在文件里直接编辑/追加。"""
    if not PROFILE_FILE.exists():
        _save_all(dict(SEED_PROFILES))
