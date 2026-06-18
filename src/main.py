"""
朋友圈发布助手 v1.3
入口：授权检查 → 主界面 → 调度执行
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import logger
from auth import is_activated, get_version
from window_manager import find_wechat_windows, bind_aliases
from publisher import execute_publish
from scheduler import Scheduler
from gui.activation import ActivationWindow
from gui.main_window import MainWindow
from gui.add_task import AddTaskDialog


class App:
    def __init__(self):
        self.version = "基础版"
        self.windows: list[dict] = []
        self.scheduler: Scheduler | None = None
        self.main_win: MainWindow | None = None

    def run(self):
        logger.init()
        if is_activated():
            self.version = get_version()
            self._launch_main()
        else:
            act_win = ActivationWindow(on_success=self._on_activated)
            act_win.run()

    def _on_activated(self, version: str):
        self.version = version
        self._launch_main()

    def _launch_main(self):
        self.windows = bind_aliases(find_wechat_windows())

        self.main_win = MainWindow(
            version=self.version,
            windows=self.windows,
            on_add_task=self._on_add_task,
            on_start=self._on_start,
            on_stop=self._on_stop,
            on_retry=self._on_retry,
        )
        self.main_win.log(f"程序启动，检测到 {len(self.windows)} 个微信窗口")
        for w in self.windows:
            self.main_win.log(f"  {w['alias']} — HWND: {w['hwnd']} — {w['title']}")
        self.main_win.run()

    def _on_add_task(self, aliases: list[str]):
        AddTaskDialog(
            parent=self.main_win.root,
            account_aliases=aliases,
            on_confirm=self.main_win.add_task,
        )

    def _on_start(self):
        tasks = self.main_win.tasks
        hwnd_map = {w["alias"]: w["hwnd"] for w in self.windows}
        for task in tasks:
            task["hwnd"] = hwnd_map.get(task["alias"], 0)

        self.scheduler = Scheduler(
            schedule=tasks,
            publish_fn=execute_publish,
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
        hwnd_map = {w["alias"]: w["hwnd"] for w in self.windows}
        task["hwnd"] = hwnd_map.get(task["alias"], 0)
        import threading
        def _run():
            # 等待调度器当前任务完成再执行重发
            if self.scheduler and self.scheduler._publishing:
                self.main_win.log(f"等待当前任务完成后再重发：{task.get('alias')}")
                while self.scheduler._publishing:
                    import time; time.sleep(1)
            if self.scheduler:
                self.scheduler._publishing = True
            try:
                result = execute_publish(task)
            finally:
                if self.scheduler:
                    self.scheduler._publishing = False
            if result.get("success"):
                task["status"] = "已发布"
                self.main_win.log(f"✓ 重发成功：{task.get('alias')}")
            else:
                task["status"] = f"失败: {result.get('reason', '未知错误')}"
                self.main_win.log(f"✗ 重发失败：{task.get('alias')} — {result.get('reason')}")
            idx = self.main_win.tasks.index(task) if task in self.main_win.tasks else -1
            if idx >= 0:
                self.main_win.update_task_status(idx, task["status"])
        threading.Thread(target=_run, daemon=True).start()

    def _on_stop(self):
        if self.scheduler:
            self.scheduler.stop()
            self.main_win.log("已停止")


if __name__ == "__main__":
    App().run()
