import tkinter as tk
from tkinter import ttk, filedialog
from typing import Callable


class AddTaskDialog:
    def __init__(self, parent: tk.Tk, account_aliases: list[str], on_confirm: Callable[[dict], None]):
        self.on_confirm = on_confirm
        self.selected_images: list[str] = []

        self.win = tk.Toplevel(parent)
        self.win.title("添加发布任务")
        self.win.resizable(False, False)
        self.win.grab_set()
        self._center(440, 480)
        self._build(account_aliases)

    def _center(self, w: int, h: int):
        self.win.update_idletasks()
        px = self.win.winfo_toplevel().winfo_x()
        py = self.win.winfo_toplevel().winfo_y()
        self.win.geometry(f"{w}x{h}+{px+40}+{py+40}")

    def _build(self, aliases: list[str]):
        win = self.win
        win.configure(bg="#f5f5f5")
        pad_x = 24

        def row_label(text):
            tk.Label(win, text=text, font=("", 10, "bold"), bg="#f5f5f5", anchor="w").pack(
                fill="x", padx=pad_x, pady=(10, 2))

        # 账号
        row_label("账号")
        self.alias_var = tk.StringVar(value=aliases[0] if aliases else "A1")
        ttk.Combobox(win, textvariable=self.alias_var, values=aliases, state="readonly", width=10).pack(
            padx=pad_x, anchor="w")

        # 图片
        row_label("图片")
        img_frame = tk.Frame(win, bg="#f5f5f5")
        img_frame.pack(fill="x", padx=pad_x)
        self.img_label = tk.Label(img_frame, text="未选择", font=("", 9), fg="#888", bg="#f5f5f5")
        self.img_label.pack(side="left")
        ttk.Button(img_frame, text="选择图片...", command=self._select_images).pack(side="right")

        # 文案
        row_label("文案")
        self.caption_text = tk.Text(win, height=5, font=("", 10), wrap="word",
                                    relief="solid", bd=1)
        self.caption_text.pack(fill="x", padx=pad_x)

        # 发布时间
        row_label("发布时间")
        time_frame = tk.Frame(win, bg="#f5f5f5")
        time_frame.pack(fill="x", padx=pad_x)
        self.time_mode = tk.StringVar(value="auto")
        rb_auto = ttk.Radiobutton(time_frame, text="自动排班", variable=self.time_mode,
                                  value="auto", command=self._toggle_time)
        rb_auto.pack(side="left")
        rb_manual = ttk.Radiobutton(time_frame, text="指定时间", variable=self.time_mode,
                                    value="manual", command=self._toggle_time)
        rb_manual.pack(side="left", padx=(12, 4))
        self.time_var = tk.StringVar(value="09:00")
        self.time_entry = ttk.Entry(time_frame, textvariable=self.time_var, width=7, state="disabled")
        self.time_entry.pack(side="left")

        # 类型
        row_label("内容类型（影响养号策略）")
        self.type_var = tk.StringVar(value="上新")
        ttk.Combobox(win, textvariable=self.type_var,
                     values=["上新", "返图", "日常"], state="readonly", width=10).pack(
            padx=pad_x, anchor="w")

        # 按钮
        btn_frame = tk.Frame(win, bg="#f5f5f5")
        btn_frame.pack(pady=16)
        ttk.Button(btn_frame, text="确  定", width=12, command=self._confirm).pack(side="left", padx=8)
        ttk.Button(btn_frame, text="取  消", width=12, command=self.win.destroy).pack(side="left", padx=8)

    def _toggle_time(self):
        if self.time_mode.get() == "manual":
            self.time_entry.config(state="normal")
        else:
            self.time_entry.config(state="disabled")

    def _select_images(self):
        paths = filedialog.askopenfilenames(
            title="选择图片（可多选）",
            filetypes=[("图片文件", "*.jpg *.jpeg *.png *.bmp"), ("所有文件", "*.*")]
        )
        if paths:
            self.selected_images = list(paths)
            count = len(self.selected_images)
            self.img_label.config(text=f"已选 {count} 张", fg="#333")

    def _confirm(self):
        if not self.selected_images:
            tk.messagebox.showwarning("提示", "请选择至少一张图片", parent=self.win)
            return
        caption = self.caption_text.get("1.0", "end").strip()
        if not caption:
            tk.messagebox.showwarning("提示", "请输入文案", parent=self.win)
            return
        prefer_time = self.time_var.get() if self.time_mode.get() == "manual" else ""
        task = {
            "alias": self.alias_var.get(),
            "images": self.selected_images,
            "caption": caption,
            "prefer_time": prefer_time,
            "type": self.type_var.get(),
            "status": "待发布",
        }
        self.win.destroy()
        self.on_confirm(task)
