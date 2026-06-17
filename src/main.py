"""
首饰朋友圈助手 v1.3
入口：授权检查 → 主界面 → 调度执行
"""
import sys
from pathlib import Path

# 确保 src/ 在模块搜索路径里
sys.path.insert(0, str(Path(__file__).parent))

from auth import is_activated, get_version
from window_manager import find_wechat_windows, bind_aliases, get_window_rect
from publisher import execute_publish
from scheduler import generate_schedule, Scheduler, get_account_level
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
        # 补充养号级别标签
        for w in self.windows:
            reg_days = w.get("registration_days", 60)
            lvl = get_account_level(reg_days)
            w["level_label"] = f"{lvl['level']}级"

        self.main_win = MainWindow(
            version=self.version,
            windows=self.windows,
            on_add_task=self._on_add_task,
            on_generate=self._on_generate,
            on_start=self._on_start,
            on_pause=self._on_pause,
            on_stop=self._on_stop,
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

    def _on_generate(self):
        tasks = self.main_win.tasks
        accounts = [
            {
                "alias": w["alias"],
                "registration_days": w.get("registration_days", 60),
            }
            for w in self.windows
        ]
        scheduled = generate_schedule(tasks, accounts)
        self.main_win.update_schedule(scheduled)

    def _on_start(self):
        tasks = self.main_win.tasks
        # 把窗口句柄注入到 task 里
        hwnd_map = {w["alias"]: w["hwnd"] for w in self.windows}
        for task in tasks:
            task["hwnd"] = hwnd_map.get(task["alias"], 0)

        self.scheduler = Scheduler(
            schedule=tasks,
            publish_fn=execute_publish,
            callbacks={
                "on_task_start": lambda idx, t: self.main_win.update_task_status(idx, "发布中"),
                "on_task_done": lambda idx, t, r: self.main_win.update_task_status(idx, t["status"]),
                "on_log": self.main_win.log,
                "on_all_done": self.main_win.on_all_done,
            },
        )
        self.scheduler.start()
        self.main_win.log("调度开始")

    def _on_pause(self):
        if self.scheduler:
            if self.main_win._is_paused:
                self.scheduler.pause()
                self.main_win.log("已暂停")
            else:
                self.scheduler.resume()
                self.main_win.log("已继续")

    def _on_stop(self):
        if self.scheduler:
            self.scheduler.stop()
            self.main_win.log("已停止")


if __name__ == "__main__":
    App().run()
