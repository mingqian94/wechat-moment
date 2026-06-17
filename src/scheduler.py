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
        self._paused = False
        self._thread: threading.Thread | None = None
        self._consecutive_fail = 0

    def start(self):
        self._running = True
        self._paused = False
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

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

            # 等待到发布时间
            self._wait_until(task["scheduled_time"])

            if not self._running:
                break

            # 暂停检查
            while self._paused and self._running:
                time.sleep(1)

            if not self._running:
                break

            cb_start = self.callbacks.get("on_task_start")
            if cb_start:
                cb_start(idx, task)

            self._log(f"开始发布: {task['alias']} - {task.get('caption', '')[:20]}")

            result = self.publish_fn(task)

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

            # 不同账号之间额外间隔
            if idx < len(self.schedule) - 1:
                next_task = self.schedule[idx + 1]
                if next_task["alias"] != task["alias"]:
                    gap = random.randint(10, 15) * 60
                    self._log(f"账号切换，等待 {gap // 60} 分钟...")
                    self._sleep_interruptible(gap)

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
