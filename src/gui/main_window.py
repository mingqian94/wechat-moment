import os
import queue
import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable

from window_manager import activate_window


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
        self._cmd_queue: queue.Queue = queue.Queue()

        self.root = tk.Tk()
        self.root.title("朋友圈发布助手 v1.3")
        self.root.minsize(900, 680)
        self._center(960, 720)
        try:
            from logo import get_tkimage
            self._logo = get_tkimage(128)
            self.root.iconphoto(True, self._logo)
            import platform
            if platform.system() == "Windows":
                import ctypes
                ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("wechat-moment-publisher")
        except Exception:
            pass
        self._build()
        self._poll_log()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _center(self, w: int, h: int):
        """根据屏幕尺寸自适应，窗口打开即正合适"""
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()

        # 根据屏幕分辨率选择合适的窗口比例
        if screen_w >= 2560:
            w_ratio, h_ratio = 0.55, 0.70
        elif screen_w >= 1920:
            w_ratio, h_ratio = 0.65, 0.78
        else:
            w_ratio, h_ratio = 0.75, 0.82

        w_new = int(screen_w * w_ratio)
        h_new = int(screen_h * h_ratio)

        # 最小尺寸（确保所有内容完整显示）
        w_new = max(w_new, 960)
        h_new = max(h_new, 720)

        # 确保不超出屏幕
        w_new = min(w_new, screen_w - 60)
        h_new = min(h_new, screen_h - 60)

        x = (screen_w - w_new) // 2
        y = (screen_h - h_new) // 2
        self.root.geometry(f"{w_new}x{h_new}+{x}+{y}")

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

        # ── 主内容区（任务列表 + 添加任务面板）───────────────
        self.main_paned = tk.PanedWindow(root, orient="vertical", bg="#ddd")
        self.main_paned.pack(fill="both", expand=True, padx=16, pady=8)

        # 上方：任务列表
        left_frame = tk.Frame(self.main_paned, bg="#f5f5f5")
        self.main_paned.add(left_frame, minsize=160)

        # 任务列表标题 + 操作按钮
        task_hdr = tk.Frame(left_frame, bg="#f5f5f5")
        task_hdr.pack(fill="x", pady=(0, 2))
        tk.Label(task_hdr, text="今日任务", font=("", 10, "bold"), bg="#f5f5f5").pack(side="left")
        self.progress_var = tk.StringVar(value="0 / 0")
        tk.Label(task_hdr, textvariable=self.progress_var, font=("", 9), bg="#f5f5f5", fg="#888").pack(side="left", padx=(8, 0))
        self.delete_btn = ttk.Button(task_hdr, text="删除", command=self._delete_selected, state="disabled")
        self.delete_btn.pack(side="right", padx=(4, 0))
        self.edit_btn = ttk.Button(task_hdr, text="编辑", command=self._edit_selected, state="disabled")
        self.edit_btn.pack(side="right", padx=4)

        # 执行控制按钮
        ctrl_frame = tk.Frame(left_frame, bg="#f5f5f5")
        ctrl_frame.pack(fill="x", pady=4)
        ttk.Button(ctrl_frame, text="＋ 添加任务", command=self._toggle_add_panel).pack(side="left", padx=(0, 6))
        ttk.Button(ctrl_frame, text="⚡ 手动发送", command=self._manual_send).pack(side="left", padx=(0, 4))
        ttk.Button(ctrl_frame, text="⏹ 全部停止", command=self._stop).pack(side="left", padx=4)

        # 发布中提示（界面里显示，不进日志——不是运行记录，是操作提醒；常显，不随开始/停止/完成清空）
        self.running_warn_var = tk.StringVar(value="⚠ 发布过程中请勿使用电脑（程序将自动操作微信）")
        self.running_warn_label = tk.Label(left_frame, textvariable=self.running_warn_var,
                                            font=("", 9), fg="#e67e22", bg="#fff8e1", anchor="w")
        self.running_warn_label.pack(fill="x", pady=(0, 4))

        list_frame = tk.Frame(left_frame, bg="#f5f5f5")
        list_frame.pack(fill="both", expand=True)

        style = ttk.Style()
        style.configure("Treeview", rowheight=32, font=("", 10))
        style.configure("Treeview.Heading", font=("", 10, "bold"))

        cols = ("time", "alias", "media", "caption", "status")
        self.tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=12, selectmode="browse")
        headers = {"time": ("时间", 55), "alias": ("账号", 80), "media": ("素材", 120),
                   "caption": ("文案", 260), "status": ("状态", 70)}
        for col, (label, width) in headers.items():
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor="w", stretch=True)
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.tag_configure("failed", foreground="#c0392b")

        # 鼠标悬停 tooltip
        self._tooltip = tk.Label(root, bg="#fffbe6", relief="solid", bd=1, font=("", 9), wraplength=400)
        self.tree.bind("<Motion>", self._on_tree_motion)
        self.tree.bind("<Leave>", lambda e: self._tooltip.place_forget())

        # 右键菜单
        self._ctx_menu = tk.Menu(root, tearoff=0)
        self._ctx_menu.add_command(label="编辑此任务", command=self._edit_selected)
        self._ctx_menu.add_command(label="重发此任务", command=self._retry_selected)
        self._ctx_menu.add_separator()
        self._ctx_menu.add_command(label="删除此任务", command=self._delete_selected)
        self.tree.bind("<Button-2>", self._show_ctx_menu)
        self.tree.bind("<Button-3>", self._show_ctx_menu)
        self.tree.bind("<Double-1>", lambda e: self._edit_selected())

        # 右侧：添加/编辑任务面板（默认隐藏）
        self.add_panel = tk.Frame(self.main_paned, bg="#f5f5f5", relief="solid", bd=1)
        self._build_add_panel()

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

    def _build_add_panel(self):
        """构建内嵌的添加任务面板，带滚动条支持"""
        panel = self.add_panel
        pad_x = 16

        # 创建 Canvas + 滚动条实现可滚动面板
        canvas = tk.Canvas(panel, bg="#f5f5f5", highlightthickness=0)
        scrollbar_y = ttk.Scrollbar(panel, orient="vertical", command=canvas.yview)
        scrollbar_x = ttk.Scrollbar(panel, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=scrollbar_y.set, xscrollcommand=scrollbar_x.set)

        scrollbar_y.pack(side="right", fill="y")
        scrollbar_x.pack(side="bottom", fill="x")
        canvas.pack(side="left", fill="both", expand=True)

        # 在 Canvas 中创建可滚动框架
        self.add_panel_inner = tk.Frame(canvas, bg="#f5f5f5")
        canvas_window = canvas.create_window((0, 0), window=self.add_panel_inner, anchor="nw")

        def _on_frame_configure(event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))
            # 确保内嵌框架宽度与 Canvas 一致
            canvas.itemconfig(canvas_window, width=canvas.winfo_width())

        self.add_panel_inner.bind("<Configure>", _on_frame_configure)
        canvas.bind("<Configure>", _on_frame_configure)

        # 鼠标滚轮支持
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        # 使用内嵌框架作为实际容器
        panel = self.add_panel_inner

        def row_label(text, pady=(10, 2)):
            tk.Label(panel, text=text, font=("", 10, "bold"), bg="#f5f5f5", anchor="w").pack(
                fill="x", padx=pad_x, pady=pady)

        # 标题
        self.add_panel_title = tk.Label(panel, text="添加任务", font=("", 12, "bold"),
                                        bg="#f5f5f5", fg="#4a7c59")
        self.add_panel_title.pack(fill="x", padx=pad_x, pady=(12, 8))

        # 素材选择
        row_label("素材")
        img_frame = tk.Frame(panel, bg="#f5f5f5")
        img_frame.pack(fill="x", padx=pad_x)
        self.img_label = tk.Label(img_frame, text="未选择", font=("", 9), fg="#888", bg="#f5f5f5")
        self.img_label.pack(side="left")
        btn_frame = tk.Frame(img_frame, bg="#f5f5f5")
        btn_frame.pack(side="right")
        ttk.Button(btn_frame, text="选文件夹...", command=self._select_folder).pack(side="left", padx=(0, 4))
        ttk.Button(btn_frame, text="选文件...", command=self._select_files).pack(side="left")

        self.file_list_frame = tk.Frame(panel, bg="#f5f5f5")
        self.file_list_frame.pack(fill="x", padx=pad_x, pady=(4, 0))

        # 账号多选
        row_label("账号（可多选）")
        self.acct_select_frame = tk.Frame(panel, bg="#f5f5f5")
        self.acct_select_frame.pack(fill="x", padx=pad_x)
        self._refresh_account_checkboxes()

        # 文案
        row_label("文案")
        import sys
        _caption_font = ("Segoe UI Emoji", 10) if sys.platform == "win32" else ("", 10)
        self.caption_text = tk.Text(panel, height=4, font=_caption_font, wrap="word", relief="solid", bd=1)
        self.caption_text.pack(fill="x", padx=pad_x)
        tk.Label(panel, text="提示：表情符号在此处会显示为方块，属于输入框显示限制，不影响实际发布效果",
                 font=("", 8), fg="#888", bg="#f5f5f5", anchor="w").pack(fill="x", padx=pad_x, pady=(2, 0))

        # 发布时段
        row_label("发布时段（至少 3 分钟）")
        time_frame = tk.Frame(panel, bg="#f5f5f5")
        time_frame.pack(fill="x", padx=pad_x)
        self.start_var = tk.StringVar(value="09:00")
        self.end_var = tk.StringVar(value="12:00")
        ttk.Entry(time_frame, textvariable=self.start_var, width=7).pack(side="left")
        tk.Label(time_frame, text=" — ", bg="#f5f5f5").pack(side="left")
        ttk.Entry(time_frame, textvariable=self.end_var, width=7).pack(side="left")
        tk.Label(panel, text="⚠ 同一台电脑高频发布可能被微信限制",
                 font=("", 8), fg="#e67e22", bg="#f5f5f5", anchor="w").pack(
            fill="x", padx=pad_x, pady=(2, 0))

        # 按钮
        btn_frame = tk.Frame(panel, bg="#f5f5f5")
        btn_frame.pack(pady=14)
        ttk.Button(btn_frame, text="确  定", width=10, command=self._confirm_add).pack(side="left", padx=6)
        ttk.Button(btn_frame, text="取  消", width=10, command=self._hide_add_panel).pack(side="left", padx=6)

    def _refresh_account_checkboxes(self):
        """刷新账号多选框"""
        for w in self.acct_select_frame.winfo_children():
            w.destroy()
        self._alias_vars: dict[str, tk.BooleanVar] = {}
        aliases = [w.get("alias", f"微信-{i+1}") for i, w in enumerate(self.windows)] or ["微信-1"]
        for alias in aliases:
            var = tk.BooleanVar(value=True)
            self._alias_vars[alias] = var
            tk.Checkbutton(self.acct_select_frame, text=alias, variable=var,
                           bg="#f5f5f5", font=("", 10)).pack(side="left", padx=(0, 8))

    def _is_add_panel_shown(self) -> bool:
        # panes() 返回的是 Tcl_Obj，不是 str，不能直接用 widget in panes() 比较，
        # 必须转成字符串再比较路径名，否则永远是 False（试过，踩过的坑）
        return any(str(p) == str(self.add_panel) for p in self.main_paned.panes())

    def _toggle_add_panel(self):
        """切换添加任务面板的显示/隐藏"""
        if self._is_add_panel_shown():
            self._hide_add_panel()
        else:
            self._show_add_panel()

    def _show_add_panel(self):
        """显示添加任务面板"""
        self._reset_add_panel()
        self.add_panel_title.config(text="添加任务")
        self._edit_idx = None
        self.main_paned.add(self.add_panel, minsize=120)
        self._refresh_account_checkboxes()

    def _hide_add_panel(self):
        """隐藏添加任务面板"""
        if self._is_add_panel_shown():
            self.main_paned.remove(self.add_panel)

    def _reset_add_panel(self):
        """重置添加面板状态"""
        self.selected_images = []
        self._folder = ""
        self.img_label.config(text="未选择", fg="#888")
        for w in self.file_list_frame.winfo_children():
            w.destroy()
        self.caption_text.delete("1.0", "end")
        start_str, end_str = self._default_time_range()
        self.start_var.set(start_str)
        self.end_var.set(end_str)

    def _default_time_range(self) -> tuple[str, str]:
        """默认发布时段：起始取当前时间往上取整到 5 分钟（比如 12:22 取 12:25），
        结束为起始 + 30 分钟，超过当天就封顶到 23:55。
        """
        from datetime import datetime, timedelta
        now = datetime.now().replace(second=0, microsecond=0)
        add_minutes = (5 - now.minute % 5) % 5
        start_dt = now + timedelta(minutes=add_minutes)
        end_dt = start_dt + timedelta(minutes=30)
        day_end = start_dt.replace(hour=23, minute=55)
        if end_dt > day_end:
            end_dt = day_end
        return start_dt.strftime("%H:%M"), end_dt.strftime("%H:%M")

    def _validate_files(self, files: list[str]) -> tuple[list[str], str | None]:
        """验证文件列表，返回 (有效文件列表, 错误信息)"""
        if not files:
            return [], "未选择任何文件"

        exts = {".jpg", ".jpeg", ".png", ".bmp", ".mp4", ".mov"}
        valid_files = [f for f in files if os.path.splitext(f)[1].lower() in exts]
        if not valid_files:
            return [], "所选文件中没有图片或视频"

        # 检查混发：图片和视频不能混发
        has_img = any(os.path.splitext(f)[1].lower() in {".jpg", ".jpeg", ".png", ".bmp"} for f in valid_files)
        has_vid = any(os.path.splitext(f)[1].lower() in {".mp4", ".mov"} for f in valid_files)
        if has_img and has_vid:
            return [], "图片和视频不能混发，请分开选择"

        # 检查视频时长（微信限制30秒）
        video_exts = {".mp4", ".mov"}
        for f in valid_files:
            if os.path.splitext(f)[1].lower() in video_exts:
                try:
                    import cv2
                    cap = cv2.VideoCapture(f)
                    fps = cap.get(cv2.CAP_PROP_FPS)
                    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
                    duration = frame_count / fps if fps > 0 else 0
                    cap.release()
                    if duration > 30:
                        return [], f"视频 {os.path.basename(f)} 时长 {int(duration)} 秒，超过微信30秒限制，请裁剪后重试"
                except Exception:
                    pass  # 无法读取时长时跳过检查

        # 限制最多9个
        if len(valid_files) > 9:
            valid_files = valid_files[:9]

        return valid_files, None

    def _set_selected_files(self, files: list[str], source_name: str, append: bool = False):
        """设置/追加选中的文件并更新界面"""
        all_files = (list(self.selected_images) + list(files)) if append and self.selected_images else list(files)
        valid_files, error = self._validate_files(all_files)
        if error:
            messagebox.showwarning("提示", error)
            return
        self.selected_images = valid_files
        self._folder = source_name
        self.img_label.config(text=self._media_label(), fg="#333")
        self._refresh_file_list()

    def _select_folder(self):
        from tkinter import filedialog
        self.root.update()
        folder = filedialog.askdirectory(parent=self.root, title="选择素材文件夹（文件名 01-09 决定顺序）")
        if not folder:
            return
        exts = {".jpg", ".jpeg", ".png", ".bmp", ".mp4", ".mov"}
        files = sorted(
            os.path.join(folder, f) for f in os.listdir(folder)
            if os.path.splitext(f)[1].lower() in exts
        )
        self._set_selected_files(files, folder)

    def _select_files(self):
        from tkinter import filedialog
        self.root.update()
        files = filedialog.askopenfilenames(
            parent=self.root,
            title="选择素材文件（可多选，按选择顺序排列）",
            filetypes=[
                ("图片和视频", "*.jpg *.jpeg *.png *.bmp *.mp4 *.mov"),
                ("图片", "*.jpg *.jpeg *.png *.bmp"),
                ("视频", "*.mp4 *.mov"),
                ("所有文件", "*.*")
            ]
        )
        if not files:
            return
        # 追加到已有列表（选文件夹是替换，选文件是追加）
        self._set_selected_files(list(files), "自选文件", append=True)

    def _media_label(self) -> str:
        imgs = sum(1 for f in self.selected_images
                   if os.path.splitext(f)[1].lower() in {".jpg", ".jpeg", ".png", ".bmp"})
        vids = len(self.selected_images) - imgs
        folder = os.path.basename(self._folder) or self._folder
        parts = []
        if imgs:
            parts.append(f"{imgs}图")
        if vids:
            parts.append(f"{vids}视频")
        return f"{folder}  ({' '.join(parts)})"

    def _refresh_file_list(self):
        for w in self.file_list_frame.winfo_children():
            w.destroy()
        for i, path in enumerate(self.selected_images):
            name = os.path.basename(path)
            ext = os.path.splitext(name)[1].lower()
            icon = "🎬" if ext in {".mp4", ".mov"} else "🖼"
            tk.Label(self.file_list_frame, text=f"{icon} {i+1}. {name}",
                     font=("", 9), fg="#555", bg="#f5f5f5", anchor="w").pack(fill="x")

    def _confirm_add(self):
        from datetime import datetime, timedelta
        import random

        if not getattr(self, 'selected_images', []):
            messagebox.showwarning("提示", "请选择素材文件夹")
            return
        caption = self.caption_text.get("1.0", "end").strip()
        selected_aliases = [a for a, v in self._alias_vars.items() if v.get()]
        if not selected_aliases:
            messagebox.showwarning("提示", "请至少选择一个账号")
            return

        t_start = self._parse_time(self.start_var.get())
        t_end = self._parse_time(self.end_var.get())
        if not t_start or not t_end:
            messagebox.showwarning("提示", "时间格式错误，请填写 HH:MM")
            return
        now = datetime.now().replace(second=0, microsecond=0)
        if t_start < now:
            messagebox.showwarning("提示", f"开始时间不能早于当前时间（{now.strftime('%H:%M')}）")
            return
        if (t_end - t_start).total_seconds() < 3 * 60:
            messagebox.showwarning("提示", "时段至少 3 分钟")
            return

        slot_sec = int((t_end - t_start).total_seconds())
        n = len(selected_aliases)
        min_gap = 5 * 60
        times = []
        attempts = 0
        while len(times) < n and attempts < 2000:
            attempts += 1
            t = t_start + timedelta(seconds=random.randint(0, slot_sec))
            if all(abs((t - x).total_seconds()) >= min_gap for x in times):
                times.append(t)
        times.sort()
        if len(times) < n:
            step = slot_sec / n if n > 1 else slot_sec / 2
            times = [t_start + timedelta(seconds=step * i) for i in range(n)]

        tasks = []
        for alias, t in zip(selected_aliases, times):
            tasks.append({
                "alias": alias,
                "aliases": selected_aliases,
                "images": self.selected_images,
                "caption": caption,
                "prefer_time": t.strftime("%H:%M"),
                "scheduled_time": t,
                "scheduled_str": t.strftime("%H:%M:%S"),
                "status": "待发布",
            })

        if self._edit_idx is not None:
            self.tasks[self._edit_idx:self._edit_idx+1] = tasks
        else:
            self.tasks.extend(tasks)

        self._refresh_tree()
        self._hide_add_panel()
        # 确定任务后自动启动调度（若未运行）
        if not self._is_running:
            self._start()

    def _parse_time(self, s: str):
        from datetime import datetime
        try:
            t = datetime.strptime(s.strip(), "%H:%M")
            return datetime.today().replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        except ValueError:
            return None

    # ── 账号显示 ──────────────────────────────────────────
    def _refresh_accounts(self):
        for w in self.acct_frame_inner.winfo_children():
            w.destroy()
        if not self.windows:
            tk.Label(self.acct_frame_inner, text="⚠ 未检测到微信窗口，请先用多开工具登录账号",
                     fg="#c0392b", bg="#f5f5f5", font=("", 9)).pack(anchor="w")
            return
        for win in self.windows:
            alias = win.get("alias") or "微信"
            card = tk.Frame(self.acct_frame_inner, bg="#fff", relief="solid", bd=1, width=100, height=100)
            card.pack_propagate(False)
            card.pack(side="left", padx=6, pady=4)

            # 显示头像
            avatar_bytes = win.get("avatar_bytes")
            if avatar_bytes:
                try:
                    from PIL import Image, ImageTk
                    import io
                    img = Image.open(io.BytesIO(avatar_bytes))
                    img = img.resize((60, 60), Image.LANCZOS)
                    photo = ImageTk.PhotoImage(img)
                    lbl = tk.Label(card, image=photo, bg="#fff")
                    lbl.image = photo  # 保持引用
                    lbl.pack(pady=(6, 0))
                except Exception:
                    tk.Label(card, text="👤", font=("", 24), bg="#fff").pack(pady=(6, 0))
            else:
                tk.Label(card, text="👤", font=("", 24), bg="#fff").pack(pady=(6, 0))

            tk.Label(card, text=alias, font=("", 9), bg="#fff").pack(pady=(2, 0))

    @property
    def selected_aliases(self) -> list[str]:
        return [w.get("alias", f"微信-{i+1}") for i, w in enumerate(self.windows)]

    def update_accounts(self, windows: list[dict]):
        self.windows = windows
        self._refresh_accounts()
        self._refresh_account_checkboxes()

    # ── 任务操作 ──────────────────────────────────────────
    def _add_task(self):
        self._show_add_panel()

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
        has_tasks = len(self.tasks) > 0
        self.edit_btn.config(state="normal" if has_tasks else "disabled")
        self.delete_btn.config(state="normal" if has_tasks else "disabled")
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
        self._edit_idx = idx

        # 填充编辑数据
        self._reset_add_panel()
        self.add_panel_title.config(text="编辑任务")
        self.selected_images = task.get("images", [])
        self._folder = os.path.dirname(self.selected_images[0]) if self.selected_images else ""
        self.img_label.config(text=self._media_label(), fg="#333")
        self._refresh_file_list()
        self.caption_text.insert("1.0", task.get("caption", ""))
        time_str = task.get("scheduled_str", task.get("prefer_time", ""))
        self.start_var.set(time_str)
        self.end_var.set(time_str)

        # 设置账号选择
        for alias, var in self._alias_vars.items():
            var.set(alias == task.get("alias", ""))

        self.main_paned.add(self.add_panel, minsize=120)

    def _show_ctx_menu(self, event):
        item = self.tree.identify_row(event.y)
        if item:
            self.tree.selection_set(item)
            idx = self.tree.index(item)
            task = self.tasks[idx] if 0 <= idx < len(self.tasks) else {}
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
        times = [t.get("scheduled_str", "") for t in self.tasks if t.get("scheduled_str")]
        end_time = max(times) if times else ""
        self._is_running = True
        for t in self.tasks:
            if t.get("status") == "待发布":
                t["status"] = "等待中"
        self._refresh_tree()
        tip = "⚠ 发布过程中请勿使用电脑（程序将自动操作微信）"
        if end_time:
            tip += f"，预计最晚 {end_time} 完成"
        self.running_warn_var.set(tip)
        self.on_start()

    def _manual_send(self):
        """对选中任务立即发布（不等调度时间）"""
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在列表中选择要发送的任务")
            return
        idx = self.tree.index(sel[0])
        if not (0 <= idx < len(self.tasks)):
            return
        task = self.tasks[idx]
        if task.get("status") == "已发布":
            messagebox.showinfo("提示", "该任务已发布成功，无需重复发送")
            return
        task["status"] = "等待中"
        self._refresh_tree()
        if self.on_retry:
            self.on_retry(task)
        self.log(f"手动发送：{task.get('alias')} {task.get('scheduled_str', '')}")

    def _stop(self):
        self._is_running = False
        # 只重置未完成的任务，已发布状态保持不变
        for t in self.tasks:
            if t.get("status") in ("等待中", "发布中", "等待上一个任务完成"):
                t["status"] = "待发布"
        self._refresh_tree()
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
                self.log("今日任务全部完成 ✓")
        self.root.after(200, self._poll_log)

    def _on_close(self):
        if self.tasks:
            if not messagebox.askokcancel("退出确认", "退出后今日任务将清空，确认退出？"):
                return
        self.root.destroy()

    def run(self):
        # 启动时检测微信窗口（find_wechat_windows）会逐个激活每个微信窗口来截头像判断登录状态，
        # 检测完尝试恢复到"检测前的前台窗口"——但那时程序自己的窗口还没创建，且恢复用的裸
        # SetForegroundWindow 在非前台进程调用时常被 Windows 焦点锁定机制拒绝，实际效果是
        # 最后一个被激活的微信窗口留在最前面，程序自己的窗口反而在后面。这里创建完窗口后
        # 主动抢一次前台，用跟 activate_window 一样的 AttachThreadInput 技巧确保抢占成功。
        try:
            activate_window(self.root.winfo_id())
        except Exception:
            pass
        self.root.mainloop()
