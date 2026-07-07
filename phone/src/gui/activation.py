import tkinter as tk
from tkinter import ttk, messagebox
from typing import Callable


class ActivationWindow:
    def __init__(self, on_success: Callable[[str], None]):
        self.on_success = on_success
        self.root = tk.Tk()
        self.root.title("朋友圈发布助手 · 操作手机版 - 激活")
        self.root.resizable(True, True)
        self.root.minsize(440, 300)
        self._center(480, 320)
        self._build()

    def _center(self, w: int, h: int):
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        w_new = max(min(w, screen_w - 60), 460)
        h_new = max(min(h, screen_h - 60), 320)
        x = (screen_w - w_new) // 2
        y = (screen_h - h_new) // 2
        self.root.geometry(f"{w_new}x{h_new}+{x}+{y}")

    def _build(self):
        root = self.root
        root.configure(bg="#f5f5f5")
        pad = {"padx": 24, "pady": 0}

        tk.Label(root, text="朋友圈发布助手 · 操作手机版", font=("", 16, "bold"), bg="#f5f5f5").pack(pady=(24, 4))
        tk.Label(root, text="请输入注册码以激活程序", font=("", 10), fg="#888", bg="#f5f5f5").pack()

        tk.Frame(root, height=1, bg="#ddd").pack(fill="x", padx=24, pady=12)

        tk.Label(root, text="注册码", font=("", 10, "bold"), bg="#f5f5f5", anchor="w").pack(fill="x", **pad)
        self.code_var = tk.StringVar()
        entry = ttk.Entry(root, textvariable=self.code_var, font=("Courier", 11))
        entry.pack(padx=24, pady=4, fill="x")
        entry.bind("<Return>", lambda _: self._activate())

        self.status_var = tk.StringVar()
        self.status_label = tk.Label(root, textvariable=self.status_var, font=("", 9),
                                     fg="red", bg="#f5f5f5")
        self.status_label.pack()

        btn_frame = tk.Frame(root, bg="#f5f5f5")
        btn_frame.pack(pady=12)
        ttk.Button(btn_frame, text="激  活", width=12, command=self._activate).pack(side="left", padx=6)
        ttk.Button(btn_frame, text="购买注册码", width=12, command=self._buy).pack(side="left", padx=6)

    def _activate(self):
        from auth import verify_code
        code = self.code_var.get().strip()
        if len(code) < 10:
            self.status_var.set("请输入完整注册码")
            return
        self.status_var.set("验证中...")
        self.root.update()
        result = verify_code(code)
        if result["ok"]:
            self.root.destroy()
            self.on_success(result["version"])
        else:
            self.status_var.set(f"激活失败：{result['reason']}")

    def _buy(self):
        messagebox.showinfo("购买注册码", "请联系微信 mingqian94 购买注册码")

    def run(self):
        self.root.mainloop()
