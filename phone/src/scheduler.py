"""
调度执行循环 —— 从 PC 版 scheduler.py 直接复制过来（同一套逻辑，PC 版已清理过死代码）。
publish_fn 在手机版这里换成对某台设备调用 publisher.publish_moment，其余不变：
串行执行、按 scheduled_time 触发、连续失败熔断、"已发布"状态被手动发送抢先时不重复发。
"""
import threading
import time
from datetime import datetime
from typing import Callable


class Scheduler:
    def __init__(self, schedule: list[dict], publish_fn: Callable, callbacks: dict):
        """
        publish_fn: 接收 task dict，返回 {success: bool, reason: str}
        callbacks:
          on_task_start(idx, task)
          on_task_done(idx, task, result)
          on_log(msg)
          on_all_done()
        """
        self.schedule = schedule
        self.publish_fn = publish_fn
        self.callbacks = callbacks
        self._running = False
        self._thread: threading.Thread | None = None
        self._consecutive_fail = 0
        self._publishing = False  # 当前是否有任务正在发布中

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _log(self, msg: str):
        cb = self.callbacks.get("on_log")
        if cb:
            cb(msg)

    def _run(self):
        for idx, task in enumerate(self.schedule):
            if not self._running:
                break

            # 跳过已成功发布的任务（停止后重启时保留已发布结果）
            if task.get("status") == "已发布":
                continue

            # 等待到发布时间
            self._wait_until(task["scheduled_time"])

            if not self._running:
                break

            # 等待期间任务可能已被"手动发送"发出去了（手动发送走独立线程，不经过本循环），
            # 等完必须重新检查状态，否则会把同一条再发一遍，失败时还会覆盖掉已发布状态
            if task.get("status") == "已发布":
                continue

            # 如果上一个任务还在发布中，等待其完成（失败也视为完成）
            if self._publishing:
                cb_waiting = self.callbacks.get("on_task_status")
                if cb_waiting:
                    cb_waiting(idx, "等待上一个任务完成")
                self._log(f"等待上一个任务完成后再发布: {task['alias']}")
                while self._publishing and self._running:
                    time.sleep(1)

            if not self._running:
                break

            # 排队等待期间也可能被手动发送处理掉，再查一次
            if task.get("status") == "已发布":
                continue

            self._publishing = True
            cb_start = self.callbacks.get("on_task_start")
            if cb_start:
                cb_start(idx, task)

            self._log(f"开始发布: {task['alias']} - {task.get('caption', '')[:20]}")

            try:
                result = self.publish_fn(task)
            except Exception as e:
                # publish_fn 内部本应把所有失败都包装成 {"success": False, ...} 返回，
                # 不该抛异常；这里兜底是为了不让调度线程的未捕获异常静默吞掉整条任务
                self._log(f"✗ 发布出现未捕获异常 [{task['alias']}]: {e}")
                result = {"success": False, "reason": f"未捕获异常: {e}"}
            self._publishing = False

            if result.get("success"):
                self._consecutive_fail = 0
                task["status"] = "已发布"
                self._log(f"✓ 发布成功: {task['alias']}")
            else:
                self._consecutive_fail += 1
                reason = result.get("reason", "未知错误")
                task["status"] = f"失败: {reason}"
                self._log(f"✗ 发布失败 [{task['alias']}]: {reason}")

                if self._consecutive_fail >= 3:
                    self._running = False
                    self._log("连续 3 条失败，已停止，请检查后手动重启")
                    break

            cb_done = self.callbacks.get("on_task_done")
            if cb_done:
                cb_done(idx, task, result)

        cb_all = self.callbacks.get("on_all_done")
        if cb_all:
            cb_all()
        self._log("今日任务全部完成")

    def _wait_until(self, target: datetime):
        while self._running:
            now = datetime.now()
            if now >= target:
                return
            remaining = (target - now).total_seconds()
            sleep_sec = min(remaining, 10)
            time.sleep(sleep_sec)

    def _sleep_interruptible(self, seconds: float):
        end = time.time() + seconds
        while self._running and time.time() < end:
            time.sleep(1)
