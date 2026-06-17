import queue
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable


class MainWindow:
    def __init__(self, version: str, windows: list[dict],
                 on_add_task: Callable,
                 on_generate: Callable,
                 on_start: Callable,
                 on_pause: Callable,
                 on_stop: Callable):
        self.version = version
        self.windows = windows
        self.on_add_task = on_add_task
        self.on_generate = on_generate
        self.on_start = on_start
        self.on_pause = on_pause
        self.on_stop = on_stop

        self.tasks: list[dict] = []
        self._is_running = False
        self._is_paused = False
        self._log_queue: queue.Queue = queue.Queue()

        self.root = tk.Tk()
        self.root.title("朋友圈助手 v1.3")
        self.root.minsize(700, 620)
        self._center(720, 660)
        self._build()
        self._poll_log()

    def _center(self, w: int, h: int):
        self.root.geometry(f"{w}x{h}")
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth() - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")

    def _build(self):
        root = self.root
        root.configure(bg="#f5f5f5")

        # ── 顶部标题 ──────────────────────────────────────
        top = tk.Frame(root, bg="#4a7c59", height=56)
        top.pack(fill="x")
        top.pack_propagate(False)
        tk.Label(top, text="朋友圈助手",
                 font=("", 15, "bold"), fg="white", bg="#4a7c59").pack(side="left", padx=20, pady=14)

        # ── 账号状态 ──────────────────────────────────────
        acct_frame = tk.LabelFrame(root, text="微信账号", bg="#f5f5f5", font=("", 10))
        acct_frame.pack(fill="x", padx=16, pady=(10, 0))
        self.acct_frame_inner = tk.Frame(acct_frame, bg="#f5f5f5")
        self.acct_frame_inner.pack(fill="x", padx=8, pady=6)
        self._refresh_accounts()

        # ── 操作按钮 ──────────────────────────────────────
        btn_frame = tk.Frame(root, bg="#f5f5f5")
        btn_frame.pack(fill="x", padx=16, pady=8)
        ttk.Button(btn_frame, text="＋ 添加任务", command=self._add_task).pack(side="left", padx=(0, 6))
        ttk.Button(btn_frame, text="生成时间表", command=self._generate).pack(side="left", padx=6)
        self.start_btn = ttk.Button(btn_frame, text="开始执行", command=self._start)
        self.start_btn.pack(side="left", padx=6)
        self.pause_btn = ttk.Button(btn_frame, text="暂  停", command=self._pause, state="disabled")
        self.pause_btn.pack(side="left", padx=6)
        ttk.Button(btn_frame, text="停  止", command=self._stop).pack(side="left", padx=6)

        # ── 进度 ──────────────────────────────────────────
        prog_frame = tk.Frame(root, bg="#f5f5f5")
        prog_frame.pack(fill="x", padx=16)
        self.progress_var = tk.StringVar(value="今日进度：0 / 0")
        tk.Label(prog_frame, textvariable=self.progress_var, font=("", 9), bg="#f5f5f5", fg="#555").pack(side="left")

        # ── 任务列表 ──────────────────────────────────────
        tk.Label(root, text="今日任务", font=("", 10, "bold"), bg="#f5f5f5", anchor="w").pack(
            fill="x", padx=16, pady=(8, 2))
        list_frame = tk.Frame(root, bg="#f5f5f5")
        list_frame.pack(fill="both", padx=16, expand=False)

        cols = ("time", "alias", "caption", "type", "status")
        self.tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=8, selectmode="browse")
        headers = {"time": ("时间", 60), "alias": ("账号", 50),
                   "caption": ("文案", 340), "type": ("类型", 60), "status": ("状态", 80)}
        for col, (label, width) in headers.items():
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor="w")
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        # 右键删除
        menu = tk.Menu(root, tearoff=0)
        menu.add_command(label="删除此任务", command=self._delete_selected)
        self.tree.bind("<Button-2>", lambda e: menu.post(e.x_root, e.y_root))
        self.tree.bind("<Button-3>", lambda e: menu.post(e.x_root, e.y_root))

        # ── 日志 ──────────────────────────────────────────
        tk.Label(root, text="运行日志", font=("", 10, "bold"), bg="#f5f5f5", anchor="w").pack(
            fill="x", padx=16, pady=(8, 2))
        log_frame = tk.Frame(root, bg="#f5f5f5")
        log_frame.pack(fill="both", expand=True, padx=16, pady=(0, 12))
        self.log_text = tk.Text(log_frame, height=8, font=("Courier", 9),
                                state="disabled", bg="#1e1e1e", fg="#d4d4d4",
                                relief="flat", wrap="word")
        log_vsb = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=log_vsb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        log_vsb.pack(side="right", fill="y")

    # ── 账号显示 ──────────────────────────────────────────
    def _refresh_accounts(self):
        for w in self.acct_frame_inner.winfo_children():
            w.destroy()
        if not self.windows:
            tk.Label(self.acct_frame_inner, text="⚠ 未检测到微信窗口，请先用多开工具登录账号",
                     fg="#c0392b", bg="#f5f5f5", font=("", 9)).pack(anchor="w")
            return
        for i, win in enumerate(self.windows):
            alias = win.get("alias") or f"A{i+1}"
            card = tk.Frame(self.acct_frame_inner, bg="#fff", relief="solid", bd=1, width=90, height=60)
            card.pack_propagate(False)
            card.pack(side="left", padx=6, pady=4)
            tk.Label(card, text=alias, font=("", 12, "bold"), bg="#fff").pack(pady=(8, 0))
            tk.Label(card, text=win.get("level_label", "B级"), font=("", 8), fg="#666", bg="#fff").pack()
            tk.Label(card, text="在线", font=("", 8), fg="#27ae60", bg="#fff").pack()

    def update_accounts(self, windows: list[dict]):
        self.windows = windows
        self._refresh_accounts()

    # ── 任务操作 ──────────────────────────────────────────
    def _add_task(self):
        aliases = [w.get("alias", f"A{i+1}") for i, w in enumerate(self.windows)] or ["A1", "A2", "A3"]
        self.on_add_task(aliases)

    def add_task(self, task: dict):
        self.tasks.append(task)
        self._refresh_tree()

    def _generate(self):
        if not self.tasks:
            messagebox.showinfo("提示", "请先添加任务")
            return
        self.on_generate()

    def update_schedule(self, scheduled: list[dict]):
        self.tasks = scheduled
        self._refresh_tree()
        messagebox.showinfo("生成成功", "时间表已生成，请确认后点「开始执行」")

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        done = sum(1 for t in self.tasks if t.get("status") == "已发布")
        self.progress_var.set(f"今日进度：{done} / {len(self.tasks)}")
        for task in self.tasks:
            time_str = task.get("scheduled_str", task.get("prefer_time", "自动"))
            caption_preview = task.get("caption", "")[:40]
            self.tree.insert("", "end", values=(
                time_str,
                task.get("alias", ""),
                caption_preview,
                task.get("type", ""),
                task.get("status", "待发布"),
            ))

    def _delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        if 0 <= idx < len(self.tasks):
            self.tasks.pop(idx)
            self._refresh_tree()

    def update_task_status(self, idx: int, status: str):
        if 0 <= idx < len(self.tasks):
            self.tasks[idx]["status"] = status
        self._refresh_tree()

    # ── 执行控制 ──────────────────────────────────────────
    def _start(self):
        if not self.tasks:
            messagebox.showinfo("提示", "请先生成时间表")
            return
        self._is_running = True
        self._is_paused = False
        self.start_btn.config(state="disabled")
        self.pause_btn.config(state="normal")
        self.on_start()

    def _pause(self):
        self._is_paused = not self._is_paused
        if self._is_paused:
            self.pause_btn.config(text="继  续")
            self.on_pause()
        else:
            self.pause_btn.config(text="暂  停")
            self.on_pause()

    def _stop(self):
        self._is_running = False
        self._is_paused = False
        self.start_btn.config(state="normal")
        self.pause_btn.config(state="disabled", text="暂  停")
        self.on_stop()

    def on_all_done(self):
        self._is_running = False
        self.start_btn.config(state="normal")
        self.pause_btn.config(state="disabled", text="暂  停")
        self.log("今日任务全部完成 ✓")

    # ── 日志 ──────────────────────────────────────────────
    def log(self, msg: str):
        self._log_queue.put(msg)

    def _poll_log(self):
        while not self._log_queue.empty():
            msg = self._log_queue.get_nowait()
            from datetime import datetime
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_text.config(state="normal")
            self.log_text.insert("end", f"{ts}  {msg}\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        self.root.after(200, self._poll_log)

    def run(self):
        self.root.mainloop()
