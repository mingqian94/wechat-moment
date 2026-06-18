import os
import queue
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable


class MainWindow:
    def __init__(self, version: str, windows: list[dict],
                 on_add_task: Callable,
                 on_start: Callable,
                 on_stop: Callable,
                 on_retry: Callable | None = None):
        self.version = version
        self.windows = windows
        self.on_add_task = on_add_task
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_retry = on_retry

        self.tasks: list[dict] = []
        self._is_running = False
        self._is_paused = False
        self._log_queue: queue.Queue = queue.Queue()
        self._cmd_queue: queue.Queue = queue.Queue()  # 后台线程投递 UI 更新

        self.root = tk.Tk()
        self.root.title("朋友圈发布助手 v1.3")
        self.root.minsize(700, 620)
        self._center(720, 660)
        try:
            from logo import get_tkimage
            self._logo = get_tkimage(128)
            self.root.iconphoto(True, self._logo)
        except Exception:
            pass
        self._build()
        self._poll_log()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

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
        try:
            from logo import get_tkimage
            self._logo_header = get_tkimage(32)
            tk.Label(top, image=self._logo_header, bg="#4a7c59").pack(side="left", padx=(16, 4), pady=12)
        except Exception:
            pass
        tk.Label(top, text="朋友圈发布助手",
                 font=("", 15, "bold"), fg="white", bg="#4a7c59").pack(side="left", padx=(4, 20), pady=14)

        # ── 账号状态 ──────────────────────────────────────
        acct_frame = tk.LabelFrame(root, text="微信账号", bg="#f5f5f5", font=("", 10))
        acct_frame.pack(fill="x", padx=16, pady=(10, 0))
        self.acct_frame_inner = tk.Frame(acct_frame, bg="#f5f5f5")
        self.acct_frame_inner.pack(fill="x", padx=8, pady=6)
        self._refresh_accounts()

        # ── 任务操作 ──────────────────────────────────────
        btn_frame = tk.Frame(root, bg="#f5f5f5")
        btn_frame.pack(fill="x", padx=16, pady=8)
        ttk.Button(btn_frame, text="＋ 添加任务", command=self._add_task).pack(side="left", padx=(0, 6))

        # 执行控制区，加分隔和说明
        tk.Frame(btn_frame, width=1, bg="#ccc").pack(side="left", fill="y", padx=8, pady=4)
        ctrl_wrap = tk.Frame(btn_frame, bg="#f5f5f5")
        ctrl_wrap.pack(side="left")
        ctrl_btns = tk.Frame(ctrl_wrap, bg="#f5f5f5")
        ctrl_btns.pack()
        self.start_btn = ttk.Button(ctrl_btns, text="▶ 开始全部", command=self._start)
        self.start_btn.pack(side="left", padx=(0, 4))
        ttk.Button(ctrl_btns, text="⏹ 全部停止", command=self._stop).pack(side="left", padx=4)

        # ── 任务列表标题 + 进度 + 编辑删除 ───────────────
        task_hdr = tk.Frame(root, bg="#f5f5f5")
        task_hdr.pack(fill="x", padx=16, pady=(8, 2))
        tk.Label(task_hdr, text="今日任务", font=("", 10, "bold"), bg="#f5f5f5").pack(side="left")
        self.progress_var = tk.StringVar(value="0 / 0")
        tk.Label(task_hdr, textvariable=self.progress_var, font=("", 9), bg="#f5f5f5", fg="#888").pack(side="left", padx=(8, 0))
        ttk.Button(task_hdr, text="删除", command=self._delete_selected).pack(side="right", padx=(4, 0))
        ttk.Button(task_hdr, text="编辑", command=self._edit_selected).pack(side="right", padx=4)
        list_frame = tk.Frame(root, bg="#f5f5f5")
        list_frame.pack(fill="both", padx=16, expand=False)

        cols = ("time", "alias", "media", "caption", "status")
        self.tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=8, selectmode="browse")
        headers = {"time": ("时间", 55), "alias": ("账号", 45), "media": ("素材", 120),
                   "caption": ("文案", 260), "status": ("状态", 70)}
        for col, (label, width) in headers.items():
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor="w", stretch=False)
        self.tree.column("caption", stretch=True)
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.tag_configure("failed", foreground="#c0392b")

        # 鼠标悬停 tooltip 显示完整内容
        self._tooltip = tk.Label(root, bg="#fffbe6", relief="solid", bd=1, font=("", 9), wraplength=400)
        self.tree.bind("<Motion>", self._on_tree_motion)
        self.tree.bind("<Leave>", lambda e: self._tooltip.place_forget())

        # 右键菜单：编辑 / 重发 / 删除
        self._ctx_menu = tk.Menu(root, tearoff=0)
        self._ctx_menu.add_command(label="编辑此任务", command=self._edit_selected)
        self._ctx_menu.add_command(label="重发此任务", command=self._retry_selected)
        self._ctx_menu.add_separator()
        self._ctx_menu.add_command(label="删除此任务", command=self._delete_selected)
        self.tree.bind("<Button-2>", self._show_ctx_menu)
        self.tree.bind("<Button-3>", self._show_ctx_menu)
        self.tree.bind("<Double-1>", lambda e: self._edit_selected())

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
            card = tk.Frame(self.acct_frame_inner, bg="#fff", relief="solid", bd=1, width=90, height=50)
            card.pack_propagate(False)
            card.pack(side="left", padx=6, pady=4)
            tk.Label(card, text=alias, font=("", 12, "bold"), bg="#fff").pack(pady=(6, 0))
            tk.Label(card, text="在线", font=("", 8), fg="#27ae60", bg="#fff").pack()

    @property
    def selected_aliases(self) -> list[str]:
        return [w.get("alias", f"A{i+1}") for i, w in enumerate(self.windows)]

    def update_accounts(self, windows: list[dict]):
        self.windows = windows
        self._refresh_accounts()

    # ── 任务操作 ──────────────────────────────────────────
    def _add_task(self):
        aliases = [w.get("alias", f"A{i+1}") for i, w in enumerate(self.windows)] or ["A1", "A2", "A3"]
        self.on_add_task(aliases)

    def add_task(self, tasks: list[dict]):
        self.tasks.extend(tasks)
        self._refresh_tree()

    def _on_tree_motion(self, event):
        item = self.tree.identify_row(event.y)
        col = self.tree.identify_column(event.x)
        if not item or not col:
            self._tooltip.place_forget()
            return
        col_idx = int(col[1:]) - 1
        vals = self.tree.item(item, "values")
        if col_idx >= len(vals):
            self._tooltip.place_forget()
            return
        text = vals[col_idx]
        col_name = self.tree["columns"][col_idx]
        if col_name not in ("media", "caption", "status"):
            self._tooltip.place_forget()
            return
        idx = self.tree.index(item)
        task = self.tasks[idx] if 0 <= idx < len(self.tasks) else {}
        if col_name == "caption":
            text = task.get("caption", text)
        elif col_name == "media":
            images = task.get("images", [])
            text = "\n".join(os.path.basename(f) for f in images) if images else text
        elif col_name == "status":
            status = task.get("status", "")
            if not status.startswith("失败"):
                self._tooltip.place_forget()
                return
            text = status
        self._tooltip.config(text=text)
        self._tooltip.place(x=event.x_root - self.root.winfo_rootx() + 12,
                            y=event.y_root - self.root.winfo_rooty() + 16)

    @staticmethod
    def _ellipsis(text: str, max_chars: int) -> str:
        return text if len(text) <= max_chars else text[:max_chars - 1] + "…"

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        done = sum(1 for t in self.tasks if t.get("status") == "已发布")
        self.progress_var.set(f"{done} / {len(self.tasks)} 已发布")
        for task in self.tasks:
            time_str = task.get("scheduled_str", task.get("prefer_time", "自动"))
            images = task.get("images", [])
            folder = os.path.basename(os.path.dirname(images[0])) if images else ""
            imgs = sum(1 for f in images if os.path.splitext(f)[1].lower() in {".jpg",".jpeg",".png",".bmp"})
            vids = len(images) - imgs
            parts = []
            if imgs: parts.append(f"{imgs}图")
            if vids: parts.append(f"{vids}视频")
            media_full = f"{folder} {' '.join(parts)}" if folder else " ".join(parts)
            status = task.get("status", "待发布")
            status_display = "失败 ⚠" if status.startswith("失败") else status
            tag = ("failed",) if status.startswith("失败") else ()
            self.tree.insert("", "end", values=(
                time_str,
                task.get("alias", ""),
                self._ellipsis(media_full, 16),
                self._ellipsis(task.get("caption", ""), 28),
                status_display,
            ), tags=tag)

    def _edit_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        if not (0 <= idx < len(self.tasks)):
            return
        task = self.tasks[idx]
        aliases = [w.get("alias", f"A{i+1}") for i, w in enumerate(self.windows)] or ["A1", "A2", "A3"]

        def on_confirm(updated_list: list[dict]):
            self.tasks[idx:idx+1] = updated_list
            self._refresh_tree()

        from gui.add_task import AddTaskDialog
        AddTaskDialog(parent=self.root, account_aliases=aliases, on_confirm=on_confirm, task=task)

    def _show_ctx_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            idx = self.tree.index(item)
            task = self.tasks[idx] if 0 <= idx < len(self.tasks) else {}
            # 只有失败任务才显示重发
            state = "normal" if task.get("status", "").startswith("失败") else "disabled"
            self._ctx_menu.entryconfig("重发此任务", state=state)
            self._ctx_menu.post(event.x_root, event.y_root)

    def _retry_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        if not (0 <= idx < len(self.tasks)):
            return
        task = self.tasks[idx]
        if not task.get("status", "").startswith("失败"):
            return
        task["status"] = "等待中"
        self._refresh_tree()
        if self.on_retry:
            self.on_retry(task)
        self.log(f"重发任务：{task.get('alias')} {task.get('prefer_time', '')}")

    def _delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        if not (0 <= idx < len(self.tasks)):
            return
        task = self.tasks[idx]
        alias = task.get("alias", "")
        time_str = task.get("scheduled_str", task.get("prefer_time", ""))
        if not messagebox.askokcancel("确认删除", f"删除任务：{alias} {time_str}？"):
            return
        self.tasks.pop(idx)
        self._refresh_tree()

    def update_task_status(self, idx: int, status: str):
        self._cmd_queue.put(("status", idx, status))

    # ── 执行控制 ──────────────────────────────────────────
    def _start(self):
        if not self.tasks:
            messagebox.showinfo("提示", "请先添加任务")
            return
        # 计算最晚发布时间
        times = [t.get("scheduled_str", "") for t in self.tasks if t.get("scheduled_str")]
        end_time = max(times) if times else ""
        tip = "发布过程中程序将自动控制鼠标和键盘操作微信，请勿使用电脑。"
        if end_time:
            tip += f"\n\n预计最晚完成时间：{end_time}"
        if not messagebox.askokcancel("开始发布", tip):
            return
        self._is_running = True
        self.start_btn.config(state="disabled")
        for t in self.tasks:
            if t.get("status") == "待发布":
                t["status"] = "等待中"
        self._refresh_tree()
        self.on_start()

    def _stop(self):
        self._is_running = False
        self.start_btn.config(state="normal")
        self.on_stop()

    def on_all_done(self):
        self._cmd_queue.put(("all_done",))

    # ── 日志 ──────────────────────────────────────────────
    def log(self, msg: str):
        self._log_queue.put(msg)
        try:
            import logger
            logger.write(msg)
        except Exception:
            pass

    def _poll_log(self):
        from datetime import datetime
        while not self._log_queue.empty():
            msg = self._log_queue.get_nowait()
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_text.config(state="normal")
            self.log_text.insert("end", f"{ts}  {msg}\n")
            self.log_text.see("end")
            self.log_text.config(state="disabled")
        while not self._cmd_queue.empty():
            cmd = self._cmd_queue.get_nowait()
            if cmd[0] == "status":
                _, idx, status = cmd
                if 0 <= idx < len(self.tasks):
                    self.tasks[idx]["status"] = status
                self._refresh_tree()
            elif cmd[0] == "all_done":
                self._is_running = False
                self.start_btn.config(state="normal")
                self.log("今日任务全部完成 ✓")
        self.root.after(200, self._poll_log)

    def _on_close(self):
        if self.tasks:
            if not messagebox.askokcancel("退出确认", "退出后今日任务将清空，确认退出？"):
                return
        self.root.destroy()

    def run(self):
        self.root.mainloop()
