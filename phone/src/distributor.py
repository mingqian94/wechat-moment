"""
素材分发 —— 发布前把这条任务的图片/视频推到目标设备的"朋友圈素材"专用文件夹。

每次发布前先清空该文件夹再推入本次素材，避免上一条任务的残留图片被误选中
（publisher.publish_moment 是按"文件夹里第几张"选图，文件夹内容必须跟当前任务一致）。
"""
import os
import time
from pathlib import Path

from adb import Adb, MOMENTS_FOLDER

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov"}


def push_task_media(adb: Adb, local_paths: list[str]) -> tuple[bool, str]:
    """把本地文件按顺序推到设备的朋友圈素材文件夹，返回 (成功?, 原因)。"""
    try:
        adb.shell(f"mkdir -p {MOMENTS_FOLDER}")
        adb.shell(f"rm -f {MOMENTS_FOLDER}/*")  # 清空上一条任务的残留

        batch_id = time.strftime("%Y%m%d_%H%M%S")
        # 系统/微信相册按最新写入倒序展示；反向 push，才能让选择器顶部保持任务原顺序。
        indexed_paths = list(enumerate(local_paths, start=1))
        for i, local in reversed(indexed_paths):
            ext = os.path.splitext(local)[1].lower()
            # 固定 01.jpg/02.jpg 会被 Android/微信相册复用旧缩略图缓存，导致界面显示
            # 上一轮素材。每轮发布用唯一文件名，同时保留序号保证排序稳定。
            remote = f"{MOMENTS_FOLDER}/wm_{batch_id}_{i:02d}{ext}"
            adb.push(local, remote)
            adb.media_scan(remote)
            time.sleep(0.2)

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
