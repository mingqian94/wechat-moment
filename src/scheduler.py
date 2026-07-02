import random
import threading
import time
from datetime import datetime, timedelta
from typing import Callable


# ── 养号策略 ──────────────────────────────────────────────
ACCOUNT_LEVELS = [
    {"min_days": 0,  "max_days": 7,   "level": "S", "daily": 2, "hourly": 1, "min_interval": 360},
    {"min_days": 7,  "max_days": 30,  "level": "A", "daily": 5, "hourly": 2, "min_interval": 40},
    {"min_days": 30, "max_days": None,"level": "B", "daily": 8, "hourly": 3, "min_interval": 25},
]

# 高峰时段（小时范围），发布密度适当提高
PEAK_HOURS = [(12, 13), (18, 19), (20, 21)]

# 随机分钟桶：避开整点/半点
MINUTE_BUCKETS = [(3, 12), (18, 27), (33, 42), (48, 57)]


def get_account_level(registration_days: int) -> dict:
    for lvl in ACCOUNT_LEVELS:
        if lvl["max_days"] is None or registration_days < lvl["max_days"]:
            return lvl
    return ACCOUNT_LEVELS[-1]


def _random_minute() -> int:
    bucket = random.choice(MINUTE_BUCKETS)
    return random.randint(bucket[0], bucket[1])


def _jitter(value: float, pct: float = 0.2) -> float:
    """对 value 做 ±pct 随机抖动。"""
    return value * (1 + random.uniform(-pct, pct))


def generate_schedule(tasks: list[dict], accounts: list[dict]) -> list[dict]:
    """
    tasks: [{alias, images, caption, prefer_time, type}]
    accounts: [{alias, registration_days}]
    返回: tasks 列表，每条带 scheduled_time (datetime) 和 status
    """
    account_map = {a["alias"]: a for a in accounts}
    # 记录每个账号上次发布时间（datetime）
    last_time: dict[str, datetime] = {}
    # 工作窗口
    today = datetime.now().date()
    window_start = datetime.combine(today, datetime.min.time()).replace(hour=9)
    window_end = datetime.combine(today, datetime.min.time()).replace(hour=22)

    scheduled = []
    for task in tasks:
        alias = task["alias"]
        acct = account_map.get(alias, {"alias": alias, "registration_days": 60})
        level = get_account_level(acct["registration_days"])
        min_interval = int(_jitter(level["min_interval"]))  # 分钟，带抖动

        if task.get("prefer_time"):
            # 用户指定时间：解析后加 ±5 分钟抖动
            h, m = map(int, task["prefer_time"].split(":"))
            base = datetime.combine(today, datetime.min.time()).replace(hour=h, minute=m)
            jitter_min = random.randint(-5, 5)
            t = base + timedelta(minutes=jitter_min)
        else:
            # 自动排班：上次发布时间 + 最小间隔
            prev = last_time.get(alias, window_start)
            t = prev + timedelta(minutes=min_interval)
            # 随机分钟（避整点/半点）
            t = t.replace(minute=_random_minute())

        # 约束在时间窗口内
        t = max(t, window_start)
        t = min(t, window_end - timedelta(minutes=1))

        last_time[alias] = t

        scheduled.append({
            **task,
            "scheduled_time": t,
            "scheduled_str": t.strftime("%H:%M"),
            "status": "待发布",
        })

    scheduled.sort(key=lambda x: x["scheduled_time"])
    return scheduled


# ── 调度执行循环 ──────────────────────────────────────────
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
                # （线程里抛异常不会让主程序崩，但会让这条任务卡在"发布中"状态不再更新）
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
