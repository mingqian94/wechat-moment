"""
手机版主界面 —— 仿 PC 版 main_window.py 的结构和交互习惯，但账号列表换成设备列表，
执行层是 ADB 驱动真机而不是操作 PC 上的微信窗口。
"""
import os
import queue
import random
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import ttk, messagebox, filedialog
from typing import Callable

import distributor


class MainWindow:
    def __init__(self, version: str, devices: list,
                 on_start: Callable,
                 on_stop: Callable,
                 on_retry: Callable | None = None,
                 on_diagnose: Callable | None = None,
                 on_rename: Callable | None = None,
                 on_rescan: Callable | None = None,
                 on_add_device: Callable | None = None):
        self.version = version
        self.devices = devices  # list[device_manager.Device]
        self.on_start = on_start
        self.on_stop = on_stop
        self.on_retry = on_retry
        self.on_diagnose = on_diagnose
        self.on_rename = on_rename
        self.on_rescan = on_rescan
        self.on_add_device = on_add_device

        self.tasks: list[dict] = []
        self._is_running = False
        self._log_queue: queue.Queue = queue.Queue()
        self._cmd_queue: queue.Queue = queue.Queue()
        self.selected_media: list[str] = []

        self.root = tk.Tk()
        self.root.title("朋友圈发布助手")
        self.root.minsize(900, 680)
        self._center(960, 720)
        self._build()
        self._poll_log()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _center(self, w: int, h: int):
        self.root.update_idletasks()
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        w_new = max(min(w, screen_w - 60), 900)
        h_new = max(min(h, screen_h - 60), 680)
        x = (screen_w - w_new) // 2
        y = (screen_h - h_new) // 2
        self.root.geometry(f"{w_new}x{h_new}+{x}+{y}")

    # ── 构建界面 ──────────────────────────────────────────
    def _build(self):
        root = self.root
        root.configure(bg="#f5f5f5")

        top = tk.Frame(root, bg="#4a7c59", height=56)
        top.pack(fill="x")
        top.pack_propagate(False)
        tk.Label(top, text="朋友圈发布助手",
                 font=("", 15, "bold"), fg="white", bg="#4a7c59").pack(side="left", padx=(16, 20), pady=14)

        # ── 设备状态 ──────────────────────────────────────
        dev_frame = tk.LabelFrame(root, text="手机设备", bg="#f5f5f5", font=("", 10))
        dev_frame.pack(fill="x", padx=16, pady=(10, 0))
        dev_btn_row = tk.Frame(dev_frame, bg="#f5f5f5")
        dev_btn_row.pack(fill="x", padx=8, pady=(4, 0))
        ttk.Button(dev_btn_row, text="🔄 重新扫描", command=self._rescan_devices).pack(side="left", padx=(0, 4))
        ttk.Button(dev_btn_row, text="➕ 添加设备", command=self._add_device_dialog).pack(side="left")
        self.dev_frame_inner = tk.Frame(dev_frame, bg="#f5f5f5")
        self.dev_frame_inner.pack(fill="x", padx=8, pady=6)
        self._refresh_devices()

        # ── 主内容区 ──────────────────────────────────────
        self.main_paned = tk.PanedWindow(root, orient="vertical", bg="#ddd")
        self.main_paned.pack(fill="both", expand=True, padx=16, pady=8)

        left_frame = tk.Frame(self.main_paned, bg="#f5f5f5")
        self.main_paned.add(left_frame, minsize=160)

        # 任务标题/进度 + 全部操作按钮放同一行
        ctrl_frame = tk.Frame(left_frame, bg="#f5f5f5")
        ctrl_frame.pack(fill="x", pady=4)
        tk.Label(ctrl_frame, text="今日任务", font=("", 10, "bold"), bg="#f5f5f5").pack(side="left")
        self.progress_var = tk.StringVar(value="0 / 0")
        tk.Label(ctrl_frame, textvariable=self.progress_var, font=("", 9), bg="#f5f5f5", fg="#888").pack(side="left", padx=(8, 14))
        ttk.Button(ctrl_frame, text="＋ 添加任务", command=self._toggle_add_panel).pack(side="left", padx=(0, 6))
        ttk.Button(ctrl_frame, text="⚡ 再发一次", command=self._manual_send).pack(side="left", padx=(0, 4))
        ttk.Button(ctrl_frame, text="⏹ 全部停止", command=self._stop).pack(side="left", padx=4)
        ttk.Button(ctrl_frame, text="🔧 设备自检", command=self._diagnose_selected).pack(side="left", padx=4)
        self.delete_btn = ttk.Button(ctrl_frame, text="删除", command=self._delete_selected, state="disabled")
        self.delete_btn.pack(side="right", padx=(4, 0))

        self.running_warn_var = tk.StringVar(value="⚠ 发布过程中请勿操作手机（程序将自动操作微信）")
        tk.Label(left_frame, textvariable=self.running_warn_var, font=("", 9),
                 fg="#e67e22", bg="#fff8e1", anchor="w").pack(fill="x", pady=(0, 4))

        list_frame = tk.Frame(left_frame, bg="#f5f5f5")
        list_frame.pack(fill="both", expand=True)

        style = ttk.Style()
        style.configure("Treeview", rowheight=32, font=("", 10))
        style.configure("Treeview.Heading", font=("", 10, "bold"))

        cols = ("time", "device", "media", "caption", "status")
        self.tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=12, selectmode="browse")
        headers = {"time": ("时间", 65), "device": ("设备", 90), "media": ("素材", 120),
                   "caption": ("文案", 260), "status": ("状态", 90)}
        for col, (label, width) in headers.items():
            self.tree.heading(col, text=label)
            self.tree.column(col, width=width, anchor="w", stretch=True)
        vsb = ttk.Scrollbar(list_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        self.tree.tag_configure("failed", foreground="#c0392b")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.delete_btn.config(
            state="normal" if self.tree.selection() else "disabled"))

        # ── 添加任务面板（默认隐藏）───────────────────────
        self.add_panel = tk.Frame(self.main_paned, bg="#f5f5f5")
        self._build_add_panel(self.add_panel)

        # ── 运行日志 ───────────────────────────────────────
        log_frame = tk.Frame(root, bg="#f5f5f5")
        log_frame.pack(fill="both", padx=16, pady=(0, 10))
        tk.Label(log_frame, text="运行日志", font=("", 10, "bold"), bg="#f5f5f5", anchor="w").pack(fill="x")
        self.log_text = tk.Text(log_frame, height=8, state="disabled", bg="#1e1e1e", fg="#d4d4d4", font=("Consolas", 9))
        self.log_text.pack(fill="both", expand=True)

    def _build_add_panel(self, panel):
        pad_x = 10
        canvas = tk.Canvas(panel, bg="#f5f5f5", highlightthickness=0)
        scrollbar = ttk.Scrollbar(panel, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")

        form = tk.Frame(canvas, bg="#f5f5f5")
        form_window = canvas.create_window((0, 0), window=form, anchor="nw")

        def _sync_scroll_region(_event=None):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _sync_width(event):
            canvas.itemconfigure(form_window, width=event.width)

        def _bind_mousewheel(_event):
            canvas.bind_all("<MouseWheel>", _on_mousewheel)

        def _unbind_mousewheel(_event):
            canvas.unbind_all("<MouseWheel>")

        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        form.bind("<Configure>", _sync_scroll_region)
        canvas.bind("<Configure>", _sync_width)
        canvas.bind("<Enter>", _bind_mousewheel)
        canvas.bind("<Leave>", _unbind_mousewheel)

        def row_label(text):
            tk.Label(form, text=text, font=("", 9, "bold"), bg="#f5f5f5", anchor="w").pack(fill="x", padx=pad_x, pady=(6, 2))

        tk.Label(form, text="添加任务", font=("", 12, "bold"), bg="#f5f5f5").pack(pady=(8, 2))

        row_label("素材")
        self.media_label = tk.Label(form, text="未选择", bg="#f5f5f5", fg="#888",
                                     anchor="w", justify="left")
        self.media_label.pack(fill="x", padx=pad_x)
        btn_frame = tk.Frame(form, bg="#f5f5f5")
        btn_frame.pack(fill="x", padx=pad_x, pady=(2, 0))
        ttk.Button(btn_frame, text="选文件夹...", command=self._select_folder).pack(side="left", padx=(0, 4))
        ttk.Button(btn_frame, text="选文件...", command=self._select_files).pack(side="left")

        row_label("目标设备（可多选，每台各生成一条任务）")
        self.dev_select_frame = tk.Frame(form, bg="#f5f5f5")
        self.dev_select_frame.pack(fill="x", padx=pad_x)
        self._refresh_device_checkboxes()

        row_label("文案")
        self.caption_text = tk.Text(form, height=3, wrap="word", relief="solid", bd=1)
        self.caption_text.pack(fill="x", padx=pad_x)
        tk.Label(form, text="提示：支持中文/emoji/换行，设备需已装 ADBKeyboard",
                 font=("", 8), fg="#888", bg="#f5f5f5", anchor="w").pack(fill="x", padx=pad_x, pady=(2, 0))

        row_label("发布时段（至少 3 分钟）")
        time_frame = tk.Frame(form, bg="#f5f5f5")
        time_frame.pack(fill="x", padx=pad_x)
        self.start_var = tk.StringVar(value="09:00")
        self.end_var = tk.StringVar(value="12:00")
        ttk.Entry(time_frame, textvariable=self.start_var, width=7).pack(side="left")
        tk.Label(time_frame, text=" — ", bg="#f5f5f5").pack(side="left")
        ttk.Entry(time_frame, textvariable=self.end_var, width=7).pack(side="left")

        btn_row = tk.Frame(form, bg="#f5f5f5")
        btn_row.pack(pady=8)
        ttk.Button(btn_row, text="确  定", width=10, command=self._confirm_add).pack(side="left", padx=6)
        ttk.Button(btn_row, text="取  消", width=10, command=self._hide_add_panel).pack(side="left", padx=6)

    # ── 设备显示 ──────────────────────────────────────────
    def set_devices(self, devices: list):
        """重新扫描/添加设备后，App 层调用这个方法把最新设备列表刷进界面。"""
        self.devices = devices
        self._refresh_devices()
        self._refresh_device_checkboxes()

    def update_devices(self, devices: list):
        self._cmd_queue.put(("devices", devices))

    def _rescan_devices(self):
        if self.on_rescan:
            self.on_rescan()
        else:
            self.log("未接入重新扫描逻辑")

    def _add_device_dialog(self):
        win = tk.Toplevel(self.root)
        win.title("添加设备")
        win.configure(bg="#f5f5f5")
        win.resizable(False, False)
        pad = {"padx": 16, "pady": (8, 2)}

        tk.Label(win, text="设备别名（比如「手机-张三」，存到本地，下次重连自动记得）",
                 font=("", 9), bg="#f5f5f5", anchor="w").pack(fill="x", **pad)
        alias_var = tk.StringVar()
        ttk.Entry(win, textvariable=alias_var, width=32).pack(padx=16, fill="x")

        tk.Label(win, text="连接地址（ip:port，无线调试页面显示的连接端口）",
                 font=("", 9), bg="#f5f5f5", anchor="w").pack(fill="x", **pad)
        connect_var = tk.StringVar()
        ttk.Entry(win, textvariable=connect_var, width=32).pack(padx=16, fill="x")

        # 用勾选框代替让用户自己判断"算不算配对过"——不确定就先不勾直接试连接，
        # 连接失败了日志里会提示回来勾这个再填配对信息，不用用户自己猜状态
        need_pair_var = tk.BooleanVar(value=False)
        pair_fields_frame = tk.Frame(win, bg="#f5f5f5")
        pair_addr_var = tk.StringVar()
        pair_code_var = tk.StringVar()

        def _toggle_pair_fields():
            if need_pair_var.get():
                pair_fields_frame.pack(fill="x", after=need_pair_chk)
            else:
                pair_fields_frame.pack_forget()

        need_pair_chk = ttk.Checkbutton(win, text="这是首次接入的新设备（需要配对）",
                                        variable=need_pair_var, command=_toggle_pair_fields)
        need_pair_chk.pack(fill="x", padx=16, pady=(10, 0))

        tk.Label(pair_fields_frame, text="配对地址（ip:port，配对码旁边显示的，跟连接地址不是同一个）",
                 font=("", 9), bg="#f5f5f5", anchor="w").pack(fill="x", **pad)
        ttk.Entry(pair_fields_frame, textvariable=pair_addr_var, width=32).pack(padx=16, fill="x")
        tk.Label(pair_fields_frame, text="配对码", font=("", 9), bg="#f5f5f5", anchor="w").pack(fill="x", **pad)
        ttk.Entry(pair_fields_frame, textvariable=pair_code_var, width=32).pack(padx=16, fill="x")

        def _confirm():
            connect_addr = connect_var.get().strip()
            if not connect_addr:
                messagebox.showwarning("提示", "请填写连接地址", parent=win)
                return
            alias = alias_var.get().strip()
            if need_pair_var.get():
                pair_addr = pair_addr_var.get().strip()
                pair_code = pair_code_var.get().strip()
            else:
                pair_addr = pair_code = ""  # 没勾选就当没填，忽略输入框里任何残留内容
            win.destroy()
            if self.on_add_device:
                self.on_add_device(connect_addr, pair_addr or None, pair_code or None, alias or None)

        btn_row = tk.Frame(win, bg="#f5f5f5")
        btn_row.pack(pady=12)
        ttk.Button(btn_row, text="确  定", width=10, command=_confirm).pack(side="left", padx=6)
        ttk.Button(btn_row, text="取  消", width=10, command=win.destroy).pack(side="left", padx=6)

    def _rename_device(self, dev):
        from tkinter import simpledialog
        new_alias = simpledialog.askstring("改备注", f"给 {dev.model} 起个备注名：",
                                            initialvalue=dev.alias, parent=self.root)
        if not new_alias or not new_alias.strip():
            return
        new_alias = new_alias.strip()
        if self.on_rename:
            self.on_rename(dev, new_alias)
        else:
            dev.rename(new_alias)
        self._refresh_devices()
        self._refresh_device_checkboxes()
        self.log(f"设备备注已改为：{new_alias}")

    def _refresh_devices(self):
        for w in self.dev_frame_inner.winfo_children():
            w.destroy()
        if not self.devices:
            tk.Label(self.dev_frame_inner, text="（还没有设备，点「添加设备」接入第一台）",
                     bg="#f5f5f5", fg="#888").pack(side="left")
            return
        for d in self.devices:
            if not d.online:
                color = "#999"
                status = "离线"
            elif d.ready:
                color = "#2e7d32"
                status = "就绪"
            else:
                color = "#c0392b"
                status = "未标定坐标"
            f = tk.Frame(self.dev_frame_inner, bg="#f5f5f5")
            f.pack(side="left", padx=8)
            alias_label = tk.Label(f, text=d.alias, font=("", 9, "bold"), bg="#f5f5f5", cursor="hand2",
                                   fg=("#999" if not d.online else "#000"))
            alias_label.pack()
            alias_label.bind("<Double-Button-1>", lambda e, dev=d: self._rename_device(dev))
            tk.Label(f, text=d.model, font=("", 8), bg="#f5f5f5", fg="#666").pack()
            tk.Label(f, text=status, font=("", 8), bg="#f5f5f5", fg=color).pack()
            tk.Label(f, text="双击改备注", font=("", 7), bg="#f5f5f5", fg="#aaa").pack()

    def _refresh_device_checkboxes(self):
        for w in self.dev_select_frame.winfo_children():
            w.destroy()
        # key 用 hw_serial（硬件序列号，稳定）而不是 serial（无线连接串，重连换端口就变，
        # 离线设备 serial 还是空字符串，多台离线设备会互相覆盖 key）
        self.dev_vars: dict[str, tk.BooleanVar] = {}
        for d in self.devices:
            var = tk.BooleanVar(value=d.ready)  # 离线/未标定的默认不勾
            self.dev_vars[d.hw_serial] = var
            label = f"{d.alias}({d.model})" + ("" if d.online else " [离线]")
            chk = ttk.Checkbutton(self.dev_select_frame, text=label, variable=var)
            if not d.online:
                chk.state(["disabled"])  # 离线设备选不了，避免生成一条永远发不出去的任务
            chk.pack(side="left", padx=4)

    # ── 添加/编辑面板显示 ─────────────────────────────────
    def _is_add_panel_shown(self) -> bool:
        return any(str(p) == str(self.add_panel) for p in self.main_paned.panes())

    def _toggle_add_panel(self):
        if self._is_add_panel_shown():
            self._hide_add_panel()
        else:
            self._show_add_panel()

    def _show_add_panel(self):
        if not self._is_add_panel_shown():
            self._reset_add_form()
            self.main_paned.add(self.add_panel, minsize=260)
            self.root.after(50, self._fit_add_panel)

    def _fit_add_panel(self):
        """打开添加任务面板时压缩上方任务列表，保证底部时间/按钮在常见屏幕上可见。"""
        try:
            panes = self.main_paned.panes()
            if len(panes) >= 2:
                self.main_paned.sash_place(0, 0, 240)
        except Exception:
            pass

    def _hide_add_panel(self):
        if self._is_add_panel_shown():
            self.main_paned.remove(self.add_panel)

    def _reset_add_form(self):
        self._set_selected_media([])
        self.caption_text.delete("1.0", "end")
        now = datetime.now() + timedelta(minutes=4)
        end = now + timedelta(minutes=5)
        self.start_var.set(now.strftime("%H:%M"))
        self.end_var.set(end.strftime("%H:%M"))
        for d in self.devices:
            var = self.dev_vars.get(d.hw_serial)
            if var is not None:
                var.set(d.ready)

    # ── 素材选择 ──────────────────────────────────────────
    def _select_folder(self):
        # 用回 Windows 原生"选择文件夹"对话框（用户熟悉的操作习惯）。原生对话框本身
        # 不显示文件内容，"选完之后能不能确认对不对"这个诉求靠 _set_selected_media
        # 展示完整文件名列表来解决，不用换成自制浏览器。
        folder = filedialog.askdirectory(parent=self.root, title="选择素材文件夹（文件名 01-09 决定顺序）")
        if not folder:
            return
        exts = {".jpg", ".jpeg", ".png", ".bmp", ".mp4", ".mov"}
        files = sorted(
            os.path.join(folder, f) for f in os.listdir(folder)
            if os.path.splitext(f)[1].lower() in exts
        )
        self._set_selected_media(files)

    def _select_files(self):
        files = filedialog.askopenfilenames(
            parent=self.root, title="选择素材文件（可多选，按选择顺序排列）",
            filetypes=[("图片和视频", "*.jpg *.jpeg *.png *.bmp *.mp4 *.mov"), ("所有文件", "*.*")]
        )
        if not files:
            return
        self._set_selected_media(list(files))

    def _set_selected_media(self, files: list[str]):
        # 完整列出文件名（不省略），方便用户确认选对了内容——尤其"选文件夹"用的是
        # 原生对话框、选的过程中看不到里面有什么，选完这里必须让用户一眼核对清楚。
        self.selected_media = files
        if not files:
            self.media_label.config(text="未选择", fg="#888")
            return
        names = "\n".join(f"{i+1}. {os.path.basename(f)}" for i, f in enumerate(files))
        self.media_label.config(text=f"共 {len(files)} 个素材（按此顺序发布）：\n{names}", fg="#333")

    # ── 确认添加 ──────────────────────────────────────────
    def _parse_time(self, s: str):
        try:
            t = datetime.strptime(s.strip(), "%H:%M")
            return datetime.today().replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        except ValueError:
            return None

    def _confirm_add(self):
        if not self.selected_media:
            messagebox.showwarning("提示", "请先选择素材")
            return
        media_type = distributor.media_type(self.selected_media)
        if media_type == "mixed":
            messagebox.showwarning("提示", "微信不支持图片和视频混发，请拆成两条任务")
            return
        if media_type == "video" and len(self.selected_media) != 1:
            messagebox.showwarning("提示", "视频任务一次只支持 1 个视频")
            return
        selected_devices = [d for d in self.devices if self.dev_vars.get(d.hw_serial, tk.BooleanVar()).get()]
        if not selected_devices:
            messagebox.showwarning("提示", "请至少选择一个设备")
            return
        caption = self.caption_text.get("1.0", "end").rstrip("\n")

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
        n = len(selected_devices)
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

        for dev, t in zip(selected_devices, times):
            self.tasks.append({
                # 存 hw_serial（硬件序列号）不存 serial：无线设备的 serial 是 ip:port，
                # 重连/换端口就变，任务是提前建的，执行时设备可能已经用了新的连接串，
                # hw_serial 是跨连接方式稳定的设备身份，任务归属要靠它找，不能靠 serial
                "device_hw_serial": dev.hw_serial,
                "device_alias": dev.alias,
                "images": list(self.selected_media),
                "media_type": media_type,
                "caption": caption,
                "scheduled_time": t,
                "scheduled_str": t.strftime("%H:%M:%S"),
                "status": "待发布",
            })

        self._refresh_tree()
        self._hide_add_panel()
        if not self._is_running:
            self._start()

    # ── 任务列表 ──────────────────────────────────────────
    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        done = sum(1 for t in self.tasks if t.get("status") in ("已发布", "待确认"))
        self.progress_var.set(f"{done} / {len(self.tasks)}")
        for t in self.tasks:
            media_type = t.get("media_type") or distributor.media_type(t["images"])
            media_desc = "1个视频" if media_type == "video" else f"{len(t['images'])}张图片"
            status = t.get("status", "")
            tags = ("failed",) if status.startswith("失败") else ()
            self.tree.insert("", "end", values=(
                t.get("scheduled_str", ""), t.get("device_alias", ""),
                media_desc, t.get("caption", "")[:30], status
            ), tags=tags)

    def _delete_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
        if 0 <= idx < len(self.tasks):
            del self.tasks[idx]
            self._refresh_tree()

    # ── 执行控制 ──────────────────────────────────────────
    def _start(self):
        if not self.tasks:
            messagebox.showinfo("提示", "请先添加任务")
            return
        self._is_running = True
        for t in self.tasks:
            if t.get("status") == "待发布":
                t["status"] = "等待中"
        self._refresh_tree()
        self.on_start()

    def _manual_send(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "请先在列表中选择要发送的任务")
            return
        idx = self.tree.index(sel[0])
        if not (0 <= idx < len(self.tasks)):
            return
        task = self.tasks[idx]
        if task.get("status") in ("已发布", "待确认"):
            messagebox.showinfo("提示", "该任务已发布成功，无需重复发送")
            return
        task["status"] = "等待中"
        self._refresh_tree()
        if self.on_retry:
            self.on_retry(task)
        self.log(f"再发一次：{task.get('device_alias')} {task.get('scheduled_str', '')}")

    def _stop(self):
        self._is_running = False
        for t in self.tasks:
            if t.get("status") in ("等待中", "发布中", "等待上一个任务完成"):
                t["status"] = "待发布"
        self._refresh_tree()
        self.on_stop()

    def _diagnose_selected(self):
        if not self.devices:
            messagebox.showinfo("提示", "没有检测到设备")
            return
        if self.on_diagnose:
            for d in self.devices:
                self.on_diagnose(d)

    def on_all_done(self):
        self._cmd_queue.put(("all_done",))

    def update_task_status(self, idx: int, status: str):
        self._cmd_queue.put(("status", idx, status))

    # ── 日志 ──────────────────────────────────────────────
    def log(self, msg: str):
        self._log_queue.put(msg)

    def _poll_log(self):
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
            elif cmd[0] == "devices":
                _, devices = cmd
                self.set_devices(devices)
            elif cmd[0] == "all_done":
                self._is_running = False
                self.log("今日任务全部完成 ✓")
        self.root.after(200, self._poll_log)

    def _on_close(self):
        if self.tasks and any(t.get("status") not in ("待发布", "已发布") for t in self.tasks):
            if not messagebox.askyesno("确认退出", "还有任务在进行中，确定退出吗？"):
                return
        self.root.destroy()

    def run(self):
        self.root.mainloop()
