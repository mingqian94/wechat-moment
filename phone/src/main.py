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
from gui.activation import ActivationWindow


def _find_adb_path() -> str:
    """找 adb.exe：优先环境变量 WM_ADB_PATH，其次程序旁边的 platform-tools/，
    最后寄望于系统 PATH 里已经有 adb（都不需要就报错，提示用户配置）。"""
    env = os.environ.get("WM_ADB_PATH")
    if env and Path(env).exists():
        return env
    candidates = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        candidates.extend([
            exe_dir / "platform-tools" / "adb.exe",
            exe_dir / "_internal" / "platform-tools" / "adb.exe",
        ])
    candidates.append(Path(__file__).resolve().parent.parent / "platform-tools" / "adb.exe")
    for local in candidates:
        if local.exists():
            return str(local)
    return "adb"  # 交给系统 PATH


class App:
    def __init__(self):
        self.version = "基础版"
        self.adb_path = _find_adb_path()
        self.devices: list = []
        self.scheduler = None
        self.main_win = None
        self._push_verified_hw: set[str] = set()

    def run(self):
        import device_profile

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
        from gui.main_window import MainWindow

        self.devices = []

        self.main_win = MainWindow(
            version=self.version,
            devices=self.devices,
            on_start=self._on_start,
            on_stop=self._on_stop,
            on_retry=self._on_retry,
            on_diagnose=self._on_diagnose,
            on_rescan=self._on_rescan,
            on_add_device=self._on_add_device,
            on_export_config=self._on_export_config,
            on_import_config=self._on_import_config,
        )
        self.main_win.log("程序启动，正在后台扫描设备...")
        self._on_rescan()
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
                status = "iPhone半自动" if getattr(d, "platform", "android") == "ios" else (
                    "就绪" if d.ready else "⚠ 该机型未标定坐标"
                )
            self.main_win.log(f"  {d.alias} — {d.model} ({d.serial or '—'}) — {status}")

    def _on_rescan(self):
        def _run():
            try:
                import device_manager

                self.devices = device_manager.discover_devices(self.adb_path)
                self.main_win.update_devices(self.devices)
                self._log_devices(f"重新扫描完成，检测到 {len(self.devices)} 台设备")
                self._verify_image_push_for_new_devices()
            except Exception as e:
                self.main_win.log(f"✗ 重新扫描失败：{e}")
        threading.Thread(target=_run, daemon=True).start()

    def _verify_image_push_for_new_devices(self):
        """设备首次在线时顺手验证能否把合成测试图推到朋友圈素材目录。"""
        for dev in self.devices:
            if getattr(dev, "platform", "android") == "ios":
                continue
            if not dev.online or dev.adb is None or dev.hw_serial in self._push_verified_hw:
                continue
            self._push_verified_hw.add(dev.hw_serial)

            def _run(d=dev):
                import diagnostics

                self.main_win.log(f"[{d.alias}] 连接验证：推送合成测试图到朋友圈素材目录...")
                result = diagnostics.verify_image_push(d.adb)
                if result.ok:
                    self.main_win.log(f"[{d.alias}] ✓ 连接验证通过：可以推图片到朋友圈素材目录")
                else:
                    self._push_verified_hw.discard(d.hw_serial)
                    self.main_win.log(f"[{d.alias}] ✗ 连接验证失败：{result.detail}")

            threading.Thread(target=_run, daemon=True).start()

    def _on_export_config(self, path: str):
        def _run():
            try:
                import config_transfer

                exported = config_transfer.export_config(path)
                if exported:
                    self.main_win.log(f"✓ 连接配置已导出：{path}")
                    self.main_win.log("  已包含：" + "、".join(exported))
                else:
                    self.main_win.log("⚠ 没找到可导出的 ADB 信任文件或设备别名配置")
            except Exception as e:
                self.main_win.log(f"✗ 导出连接配置失败：{e}")

        threading.Thread(target=_run, daemon=True).start()

    def _on_import_config(self, path: str):
        def _run():
            try:
                import config_transfer
                from adb import _run_hidden

                imported = config_transfer.import_config(path)
                if not imported:
                    self.main_win.log("⚠ 配置包里没有可导入的连接配置")
                    return
                self.main_win.log("✓ 连接配置已导入：" + "、".join(imported))
                try:
                    _run_hidden([self.adb_path, "kill-server"], timeout=10)
                    self.main_win.log("  已重启 ADB，正在重新扫描设备...")
                except Exception as e:
                    self.main_win.log(f"  ADB 重启失败，请手动重启程序后再试：{e}")
                self._on_rescan()
            except Exception as e:
                self.main_win.log(f"✗ 导入连接配置失败：{e}")

        threading.Thread(target=_run, daemon=True).start()

    def _on_add_device(self, connect_addr: str, pair_addr: str | None, pair_code: str | None,
                       alias: str | None = None):
        import adb as adb_module
        import device_registry

        def _run():
            try:
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
            except Exception as e:
                self.main_win.log(f"✗ 添加设备失败：{e}")
        threading.Thread(target=_run, daemon=True).start()

    # ── 调度 ──────────────────────────────────────────────
    def _publish_fn(self, task: dict) -> dict:
        import distributor
        import publisher

        alias = task.get("device_alias", "")

        def step_log(msg: str):
            self.main_win.log(f"  [{alias}] {msg}")

        dev = next((d for d in self.devices if d.hw_serial == task["device_hw_serial"]), None)
        if dev is None:
            return {"success": False, "reason": "设备未找到（可能已从已知设备清单移除）"}
        if not dev.online:
            return {"success": False, "reason": "设备离线，请检查手机连接"}
        if getattr(dev, "platform", "android") == "ios":
            return self._publish_ios(dev, task, step_log)
        if dev.profile is None:
            return {"success": False, "reason": f"机型 {dev.model} 未标定坐标"}

        media_type = distributor.media_type(task["images"])
        if media_type == "mixed":
            return {"success": False, "reason": "微信不支持图片和视频混发，请拆成两条任务"}
        if media_type == "video" and len(task["images"]) != 1:
            return {"success": False, "reason": "视频任务一次只支持 1 个视频"}

        step_log("唤醒手机屏幕并保持亮屏")
        try:
            dev.adb.shell("input keyevent KEYCODE_WAKEUP", timeout=5)
            dev.adb.shell("wm dismiss-keyguard", timeout=5)
            dev.adb.shell("svc power stayon true", timeout=5)
        except Exception as e:
            step_log(f"亮屏设置失败，继续尝试发布：{e}")

        step_log("推送素材到手机相册专用文件夹")
        ok, reason = distributor.push_task_media(dev.adb, task["images"])
        if not ok:
            return {"success": False, "reason": reason}
        step_log("素材推送完成")

        step_log("启动微信并进入首页")
        dev.adb.shell("am force-stop com.tencent.mm")
        time.sleep(1)
        dev.adb.shell("monkey -p com.tencent.mm -c android.intent.category.LAUNCHER 1")
        time.sleep(3)

        result = publisher.publish_moment(
            dev.adb,
            image_count=len(task["images"]),
            caption=task.get("caption", ""),
            profile=dev.profile,
            start_from_wechat_home=True,
            expected_images=task["images"],
            on_step=step_log,
        )
        if result.success:
            return {
                "success": True,
                "pending_confirm": True,
                "reason": "流程已提交，需人工回看朋友圈确认真实发布状态",
            }
        return {"success": False, "reason": result.reason}

    def _publish_ios(self, dev, task: dict, step_log) -> dict:
        """iPhone 半自动：复制文案并打开微信。iOS 26.5 不支持电脑侧远程触控。"""
        if dev.ios is None:
            return {"success": False, "reason": "iPhone 控制器未初始化"}
        try:
            step_log("iPhone 半自动模式：检查开发者模式并挂载开发者镜像")
            dev.ios.ensure_developer_ready()
            if task.get("caption"):
                step_log("复制文案到 iPhone 剪贴板")
                dev.ios.copy_text(task.get("caption", ""))
            step_log("打开微信，请人工进入朋友圈选择素材并粘贴文案发表")
            dev.ios.launch_wechat()
            return {
                "success": True,
                "pending_confirm": True,
                "reason": "iPhone 已打开微信并复制文案，需人工选择素材并发表",
            }
        except Exception as e:
            return {"success": False, "reason": f"iPhone 半自动失败：{e}"}

    def _on_start(self):
        from scheduler import Scheduler

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
                task["status"] = "待确认" if result.get("pending_confirm") else "已发布"
                self.main_win.log(f"✓ 重发流程完成：{task.get('device_alias')} — {result.get('reason', '')}")
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
            import diagnostics

            self.main_win.log(f"[{dev.alias}] 开始自检...")
            if getattr(dev, "platform", "android") == "ios":
                results = diagnostics.run_ios_diagnostics(dev.ios)
            else:
                results = diagnostics.run_diagnostics(dev.adb)
            report = diagnostics.format_report(results)
            self.main_win.log(f"[{dev.alias}] 自检结果：{report}" if "\n" not in report else f"[{dev.alias}] 自检结果：\n{report}")
        threading.Thread(target=_run, daemon=True).start()


if __name__ == "__main__":
    App().run()
