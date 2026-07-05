"""
素材分发 —— 发布前把这条任务的图片/视频推到目标设备的"朋友圈素材"专用文件夹。

每次发布前先清空该文件夹再推入本次素材，避免上一条任务的残留图片被误选中
（publisher.publish_moment 是按"文件夹里第几张"选图，文件夹内容必须跟当前任务一致）。
"""
import os
from pathlib import Path

from adb import Adb, MOMENTS_FOLDER

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov"}


def push_task_media(adb: Adb, local_paths: list[str]) -> tuple[bool, str]:
    """把本地文件按顺序推到设备的朋友圈素材文件夹，返回 (成功?, 原因)。"""
    try:
        adb.shell(f"mkdir -p {MOMENTS_FOLDER}")
        adb.shell(f"rm -f {MOMENTS_FOLDER}/*")  # 清空上一条任务的残留

        for i, local in enumerate(local_paths, start=1):
            ext = os.path.splitext(local)[1].lower()
            remote = f"{MOMENTS_FOLDER}/{i:02d}{ext}"
            adb.push(local, remote)
            adb.media_scan(remote)

        return True, ""
    except Exception as e:
        return False, f"素材推送失败: {e}"


def media_type(local_paths: list[str]) -> str:
    """判断素材类型：image / video / mixed（跟 PC 版同规则，微信不支持图文混发）。"""
    exts = {Path(p).suffix.lower() for p in local_paths}
    has_img = bool(exts & IMAGE_EXTS)
    has_vid = bool(exts & VIDEO_EXTS)
    if has_img and has_vid:
        return "mixed"
    return "video" if has_vid else "image"
