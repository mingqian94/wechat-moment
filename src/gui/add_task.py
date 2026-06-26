import os
import random
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from datetime import datetime, timedelta
from typing import Callable


class AddTaskDialog:
    def __init__(self, parent: tk.Tk, account_aliases: list[str],
                 on_confirm: Callable[[list[dict]], None], task: dict | None = None):
        self.on_confirm = on_confirm
        self.selected_images: list[str] = task.get("images", []) if task else []
        self._folder = os.path.dirname(self.selected_images[0]) if self.selected_images else ""

        self._is_edit = task is not None
        self._original_task = task  # 编辑模式保留原始时间
        self.win = tk.Toplevel(parent)
        self.win.title("编辑任务" if self._is_edit else "添加发布任务")
        self.win.resizable(False, False)
        self.win.grab_set()
        self._center(440, 520 if self._is_edit else 600)
        self._build(account_aliases, task or {})

    def _center(self, w: int, h: int):
        self.win.update_idletasks()
        px = self.win.winfo_toplevel().winfo_x()
        py = self.win.winfo_toplevel().winfo_y()
        self.win.geometry(f"{w}x{h}+{px+40}+{py+40}")

    def _build(self, aliases: list[str], task: dict):
        win = self.win
        win.configure(bg="#f5f5f5")
        pad_x = 24

        def row_label(text):
            tk.Label(win, text=text, font=("", 10, "bold"), bg="#f5f5f5", anchor="w").pack(
                fill="x", padx=pad_x, pady=(10, 2))

        # 素材选择
        row_label("素材（文件名 01-09 决定顺序）")
        img_frame = tk.Frame(win, bg="#f5f5f5")
        img_frame.pack(fill="x", padx=pad_x)
        init_label = self._media_label() if self.selected_images else "未选择"
        init_fg = "#333" if self.selected_images else "#888"
        self.img_label = tk.Label(img_frame, text=init_label, font=("", 9), fg=init_fg, bg="#f5f5f5")
        self.img_label.pack(side="left")
        btn_frame = tk.Frame(img_frame, bg="#f5f5f5")
        btn_frame.pack(side="right")
        ttk.Button(btn_frame, text="选文件夹...", command=self._select_folder).pack(side="left", padx=(0, 4))
        ttk.Button(btn_frame, text="选文件...", command=self._select_files).pack(side="left")

        # 文件列表（最多显示9个）
        self.file_list_frame = tk.Frame(win, bg="#f5f5f5")
        self.file_list_frame.pack(fill="x", padx=pad_x, pady=(4, 0))
        if self.selected_images:
            self._refresh_file_list()

        # 账号多选（编辑模式隐藏，固定为当前任务账号）
        self._alias_vars: dict[str, tk.BooleanVar] = {}
        if not self._is_edit:
            row_label("账号（可多选）")
            acct_frame = tk.Frame(win, bg="#f5f5f5")
            acct_frame.pack(fill="x", padx=pad_x)
            selected_set = set(task.get("aliases", [task.get("alias")] if task.get("alias") else []))
            for alias in aliases:
                var = tk.BooleanVar(value=(alias in selected_set) or not selected_set)
                self._alias_vars[alias] = var
                tk.Checkbutton(acct_frame, text=alias, variable=var,
                               bg="#f5f5f5", font=("", 10)).pack(side="left", padx=(0, 8))
        else:
            # 编辑模式：固定账号，不展示选择器
            alias = task.get("alias", "")
            self._alias_vars[alias] = tk.BooleanVar(value=True)
            tk.Label(win, text=f"账号：{alias}", font=("", 10), bg="#f5f5f5", fg="#555", anchor="w").pack(
                fill="x", padx=pad_x, pady=(10, 0))

        # 文案
        row_label("文案")
        self.caption_text = tk.Text(win, height=4, font=("", 10), wrap="word", relief="solid", bd=1)
        self.caption_text.pack(fill="x", padx=pad_x)
        if task.get("caption"):
            self.caption_text.insert("1.0", task["caption"])

        # 发布时段（编辑模式只读展示，不可修改）
        if not self._is_edit:
            row_label("发布时段（至少 10 分钟）")
            time_frame = tk.Frame(win, bg="#f5f5f5")
            time_frame.pack(fill="x", padx=pad_x)
            self.start_var = tk.StringVar(value="09:00")
            self.end_var = tk.StringVar(value="12:00")
            ttk.Entry(time_frame, textvariable=self.start_var, width=7).pack(side="left")
            tk.Label(time_frame, text=" — ", bg="#f5f5f5").pack(side="left")
            ttk.Entry(time_frame, textvariable=self.end_var, width=7).pack(side="left")
            tk.Label(win, text="⚠ 同一台电脑高频发布可能被微信限制",
                     font=("", 8), fg="#e67e22", bg="#f5f5f5", anchor="w").pack(
                fill="x", padx=pad_x, pady=(2, 0))
        else:
            time_str = task.get("scheduled_str", task.get("prefer_time", ""))
            tk.Label(win, text=f"发布时间：{time_str}（不可修改）",
                     font=("", 10), bg="#f5f5f5", fg="#888", anchor="w").pack(
                fill="x", padx=pad_x, pady=(10, 0))

        # 按钮
        btn_frame = tk.Frame(win, bg="#f5f5f5")
        btn_frame.pack(pady=14)
        ttk.Button(btn_frame, text="确  定", width=12, command=self._confirm).pack(side="left", padx=8)
        ttk.Button(btn_frame, text="取  消", width=12, command=self.win.destroy).pack(side="left", padx=8)

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

    def _set_selected_files(self, files: list[str], source_name: str):
        """设置选中的文件并更新界面"""
        valid_files, error = self._validate_files(files)
        if error:
            messagebox.showwarning("提示", error, parent=self.win)
            return
        self.selected_images = valid_files
        self._folder = source_name
        self.img_label.config(text=self._media_label(), fg="#333")
        self._refresh_file_list()

    def _select_folder(self):
        folder = filedialog.askdirectory(title="选择素材文件夹（文件名 01-09 决定顺序）")
        if not folder:
            return
        exts = {".jpg", ".jpeg", ".png", ".bmp", ".mp4", ".mov"}
        files = sorted(
            os.path.join(folder, f) for f in os.listdir(folder)
            if os.path.splitext(f)[1].lower() in exts
        )
        self._set_selected_files(files, folder)

    def _select_files(self):
        files = filedialog.askopenfilenames(
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
        # 保持用户选择的顺序
        self._set_selected_files(list(files), "自选文件")

    def _parse_time(self, s: str) -> datetime | None:
        try:
            t = datetime.strptime(s.strip(), "%H:%M")
            return datetime.today().replace(hour=t.hour, minute=t.minute, second=0, microsecond=0)
        except ValueError:
            return None

    def _confirm(self):
        if not self.selected_images:
            messagebox.showwarning("提示", "请选择素材文件夹", parent=self.win)
            return
        caption = self.caption_text.get("1.0", "end").strip()
        if not caption:
            messagebox.showwarning("提示", "请输入文案", parent=self.win)
            return
        selected_aliases = [a for a, v in self._alias_vars.items() if v.get()]
        if not selected_aliases:
            messagebox.showwarning("提示", "请至少选择一个账号", parent=self.win)
            return

        if self._is_edit:
            # 编辑模式：保留原始时间，只更新文案和素材
            orig = self._original_task
            tasks = [{
                **orig,
                "images": self.selected_images,
                "caption": caption,
            }]
        else:
            t_start = self._parse_time(self.start_var.get())
            t_end = self._parse_time(self.end_var.get())
            if not t_start or not t_end:
                messagebox.showwarning("提示", "时间格式错误，请填写 HH:MM", parent=self.win)
                return
            now = datetime.now().replace(second=0, microsecond=0)
            if t_start < now:
                messagebox.showwarning("提示", f"开始时间不能早于当前时间（{now.strftime('%H:%M')}）", parent=self.win)
                return
            if (t_end - t_start).total_seconds() < 10 * 60:
                messagebox.showwarning("提示", "时段至少 10 分钟", parent=self.win)
                return

            # 在时段内随机分配时间点（互相间隔至少 5 分钟）
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
                    "scheduled_str": t.strftime("%H:%M"),
                    "status": "待发布",
                })

        self.win.destroy()
        self.on_confirm(tasks)
