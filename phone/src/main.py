"""
朋友圈发布助手 · 手机版
入口：授权检查 → 设备发现 → 主界面 → 调度执行
"""
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import logger
from auth import is_activated, get_version
import device_manager
import device_profile
import distributor
import publisher
import diagnostics
from scheduler import Scheduler
from gui.activation import ActivationWindow
from gui.main_window import MainWindow


def _find_adb_path() -> str:
    """找 adb.exe：优先环境变量 WM_ADB_PATH，其次程序旁边的 platform-tools/，
    最后寄望于系统 PATH 里已经有 adb（都不需要就报错，提示用户配置）。"""
    env = os.environ.get("WM_ADB_PATH")
    if env and Path(env).exists():
        return env
    local = Path(__file__).parent.parent / "platform-tools" / "adb.exe"
    if local.exists():
        return str(local)
    return "adb"  # 交给系统 PATH


class App:
    def __init__(self):
        self.version = "基础版"
        self.adb_path = _find_adb_path()
        self.devices: list = []
        self.scheduler: Scheduler | None = None
        self.main_win: MainWindow | None = None

    def run(self):
        logger.init()
        device_profile.ensure_seeded()
        if is_activated():
            self.version = get_version()
            self._launch_main()
        else:
            act_win = ActivationWindow(on_success=self._on_activated)
            act_win.run()

    def _on_activated(self, version: str):
        self.version = version
        self._launch_main()

    # 自动重新扫描的间隔——设备列表要能自己发现"谁掉线了/谁刚连上"，不用一直手动点
    AUTO_RESCAN_INTERVAL_MS = 3 * 60 * 1000  # 3 分钟

    def _launch_main(self):
        self.devices = device_manager.discover_devices(self.adb_path)

        self.main_win = MainWindow(
            version=self.version,
            devices=self.devices,
            on_start=self._on_start,
            on_stop=self._on_stop,
            on_retry=self._on_retry,
            on_diagnose=self._on_diagnose,
            on_rescan=self._on_rescan,
            on_add_device=self._on_add_device,
        )
        self._log_devices(f"程序启动，检测到 {len(self.devices)} 台设备")
        self.main_win.root.after(self.AUTO_RESCAN_INTERVAL_MS, self._auto_rescan_tick)
        self.main_win.run()

    def _auto_rescan_tick(self):
        self._on_rescan()
        self.main_win.root.after(self.AUTO_RESCAN_INTERVAL_MS, self._auto_rescan_tick)

    def _log_devices(self, header: str):
        self.main_win.log(header)
        for d in self.devices:
            if not d.online:
                status = "离线"
            else:
                status = "就绪" if d.ready else "⚠ 该机型未标定坐标"
            self.main_win.log(f"  {d.alias} — {d.model} ({d.serial or '—'}) — {status}")

    def _on_rescan(self):
        def _run():
            self.devices = device_manager.discover_devices(self.adb_path)
            self.main_win.set_devices(self.devices)
            self._log_devices(f"重新扫描完成，检测到 {len(self.devices)} 台设备")
        threading.Thread(target=_run, daemon=True).start()

    def _on_add_device(self, connect_addr: str, pair_addr: str | None, pair_code: str | None,
                       alias: str | None = None):
        import adb as adb_module
        import device_registry

        def _run():
            if pair_addr and pair_code:
                self.main_win.log(f"配对 {pair_addr} ...")
                ok, out = adb_module.pair(self.adb_path, pair_addr, pair_code)
                if not ok:
                    self.main_win.log(f"✗ 配对失败: {out.strip()}")
                    return
                self.main_win.log("✓ 配对成功")
            self.main_win.log(f"连接 {connect_addr} ...")
            ok, out = adb_module.connect(self.adb_path, connect_addr)
            if not ok:
                self.main_win.log(f"✗ 连接失败: {out.strip()}"
                                  + ("" if pair_addr else "（如果是首次接入的新设备，勾选"
                                     "「这是首次接入的新设备」填配对信息再试）"))
                return
            self.main_win.log("✓ 连接成功")

            if alias:
                # 连上之后才拿得到硬件序列号（备注按它持久化，不是按会变化的连接串）
                try:
                    hw_serial = adb_module.Adb(self.adb_path, connect_addr).shell("getprop ro.serialno").strip()
                    device_registry.upsert(hw_serial, alias=alias, last_seen_addr=connect_addr)
                    self.main_win.log(f"设备备注已存为「{alias}」")
                except Exception as e:
                    self.main_win.log(f"⚠ 备注保存失败（不影响使用）：{e}")

            self._on_rescan()
        threading.Thread(target=_run, daemon=True).start()

    # ── 调度 ──────────────────────────────────────────────
    def _publish_fn(self, task: dict) -> dict:
        alias = task.get("device_alias", "")

        def step_log(msg: str):
            self.main_win.log(f"  [{alias}] {msg}")

        dev = next((d for d in self.devices if d.hw_serial == task["device_hw_serial"]), None)
        if dev is None:
            return {"success": False, "reason": "设备未找到（可能已从已知设备清单移除）"}
        if not dev.online:
            return {"success": False, "reason": "设备离线，请检查手机连接"}
        if dev.profile is None:
            return {"success": False, "reason": f"机型 {dev.model} 未标定坐标"}

        step_log("推送素材到手机相册专用文件夹")
        ok, reason = distributor.push_task_media(dev.adb, task["images"])
        if not ok:
            return {"success": False, "reason": reason}
        step_log("素材推送完成")

        result = publisher.publish_moment(
            dev.adb,
            image_count=len(task["images"]),
            caption=task.get("caption", ""),
            profile=dev.profile,
            on_step=step_log,
        )
        return {"success": result.success, "reason": result.reason}

    def _on_start(self):
        tasks = self.main_win.tasks
        if self.scheduler and self.scheduler._running:
            existing_ids = {id(t) for t in self.scheduler.schedule}
            added = [t for t in tasks if id(t) not in existing_ids]
            if added:
                self.scheduler.schedule.extend(added)
                self.main_win.log(f"已追加 {len(added)} 条新任务到队列")
            return

        self.scheduler = Scheduler(
            schedule=tasks,
            publish_fn=self._publish_fn,
            callbacks={
                "on_task_start": lambda idx, t: self.main_win.update_task_status(idx, "发布中"),
                "on_task_status": lambda idx, s: self.main_win.update_task_status(idx, s),
                "on_task_done": lambda idx, t, r: self.main_win.update_task_status(idx, t["status"]),
                "on_log": self.main_win.log,
                "on_all_done": self.main_win.on_all_done,
            },
        )
        self.scheduler.start()
        self.main_win.log("调度开始")

    def _on_retry(self, task: dict):
        def _run():
            if self.scheduler and self.scheduler._publishing:
                self.main_win.log(f"等待当前任务完成后再重发：{task.get('device_alias')}")
                while self.scheduler and self.scheduler._publishing:
                    time.sleep(1)
            if self.scheduler:
                self.scheduler._publishing = True
            try:
                result = self._publish_fn(task)
            finally:
                if self.scheduler:
                    self.scheduler._publishing = False
            if result.get("success"):
                task["status"] = "已发布"
                self.main_win.log(f"✓ 重发成功：{task.get('device_alias')}")
            else:
                task["status"] = f"失败: {result.get('reason', '未知错误')}"
                self.main_win.log(f"✗ 重发失败：{task.get('device_alias')} — {result.get('reason')}")
            idx = self.main_win.tasks.index(task) if task in self.main_win.tasks else -1
            if idx >= 0:
                self.main_win.update_task_status(idx, task["status"])
        threading.Thread(target=_run, daemon=True).start()

    def _on_stop(self):
        if self.scheduler:
            self.scheduler.stop()
            self.main_win.log("已停止")

    def _on_diagnose(self, dev):
        def _run():
            self.main_win.log(f"[{dev.alias}] 开始自检...")
            results = diagnostics.run_diagnostics(dev.adb)
            self.main_win.log(f"[{dev.alias}] 自检结果：\n{diagnostics.format_report(results)}")
        threading.Thread(target=_run, daemon=True).start()


if __name__ == "__main__":
    App().run()
