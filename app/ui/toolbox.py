import json
import os
import threading
import time
import traceback
import tkinter as tk
from tkinter import ttk

from tools.danqing.entry import run as run_danqing


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _load_app_config(project_root):
    return _read_json(os.path.join(project_root, "config", "app.json"), {"name": "OK Tools", "version": "0.0.0"})


def _load_tools_config(project_root):
    tools = _read_json(os.path.join(project_root, "config", "tools.json"), [])
    if isinstance(tools, list):
        return tools
    return []


def _apply_dark_theme(root):
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    bg = "#1f1f1f"
    panel = "#2b2b2b"
    panel_2 = "#303030"
    text = "#e6e6e6"
    muted = "#a7a7a7"
    accent = "#27d7d7"

    root.configure(bg=bg)

    style.configure("TFrame", background=bg)
    style.configure("Panel.TFrame", background=panel)
    style.configure("Card.TFrame", background=panel_2)

    style.configure("TLabel", background=bg, foreground=text)
    style.configure("Muted.TLabel", background=bg, foreground=muted)
    style.configure("Panel.TLabel", background=panel, foreground=text)
    style.configure("CardTitle.TLabel", background=panel_2, foreground=text, font=("Segoe UI", 12))
    style.configure("CardDesc.TLabel", background=panel_2, foreground=muted, font=("Segoe UI", 9))

    style.configure("TButton", padding=(10, 8))
    style.configure("Primary.TButton", padding=(12, 8))
    style.map(
        "Primary.TButton",
        background=[("active", accent), ("!active", "#3a3a3a")],
        foreground=[("active", "#0b0b0b"), ("!active", text)],
    )

    style.configure("Sidebar.TFrame", background="#191919")
    style.configure("Sidebar.TButton", padding=(10, 12), anchor="w", background="#191919", foreground=text)
    style.map(
        "Sidebar.TButton",
        background=[("active", "#242424")],
        foreground=[("active", text)],
    )

    style.configure("TEntry", fieldbackground="#1a1a1a", foreground=text)
    style.configure("TSpinbox", fieldbackground="#1a1a1a", foreground=text)

    return {"bg": bg, "panel": panel, "panel_2": panel_2, "text": text, "muted": muted, "accent": accent}


class ScrollableFrame(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.canvas = tk.Canvas(self, highlightthickness=0, bd=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = ttk.Frame(self.canvas)
        self.inner_id = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")

        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self.canvas.bind("<Configure>", self._on_canvas_configure)

        self.canvas.bind("<Enter>", self._on_enter)
        self.canvas.bind("<Leave>", self._on_leave)

    def _on_inner_configure(self, _):
        self.canvas.configure(scrollregion=self.canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self.canvas.itemconfigure(self.inner_id, width=event.width)

    def _on_mousewheel(self, event):
        try:
            delta = int(-1 * (event.delta / 120))
        except Exception:
            delta = 0
        if delta != 0:
            self.canvas.yview_scroll(delta, "units")

    def _on_enter(self, _):
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

    def _on_leave(self, _):
        try:
            self.canvas.unbind_all("<MouseWheel>")
        except Exception:
            pass


class CollapsibleCard(ttk.Frame):
    def __init__(self, master, title, desc, on_run=None):
        super().__init__(master, style="Card.TFrame", padding=14)
        self.on_run = on_run
        self.expanded = tk.BooleanVar(value=True)

        header = ttk.Frame(self, style="Card.TFrame")
        header.pack(fill="x")

        left = ttk.Frame(header, style="Card.TFrame")
        left.pack(side="left", fill="x", expand=True)

        ttk.Label(left, text=title, style="CardTitle.TLabel").pack(anchor="w")
        ttk.Label(left, text=desc, style="CardDesc.TLabel").pack(anchor="w", pady=(4, 0))

        right = ttk.Frame(header, style="Card.TFrame")
        right.pack(side="right")

        self.run_btn = ttk.Button(right, text="开始", style="Primary.TButton", command=self._handle_run)
        self.run_btn.pack(side="left")

        self.toggle_btn = ttk.Button(right, text="▾", command=self._toggle)
        self.toggle_btn.pack(side="left", padx=(10, 0))

        self.body = ttk.Frame(self, style="Card.TFrame", padding=(0, 14, 0, 0))
        self.body.pack(fill="x")

    def _toggle(self):
        self.expanded.set(not self.expanded.get())
        if self.expanded.get():
            self.body.pack(fill="x")
            self.toggle_btn.configure(text="▾")
        else:
            self.body.forget()
            self.toggle_btn.configure(text="▸")

    def _handle_run(self):
        if callable(self.on_run):
            self.on_run()

def _render_danqing_page(parent, log, set_status):
    wrapper = ttk.Frame(parent, style="Panel.TFrame")
    wrapper.pack(fill="both", expand=True)

    header = ttk.Frame(wrapper, style="Panel.TFrame")
    header.pack(fill="x")
    ttk.Label(header, text="丹青模拟器", style="Panel.TLabel", font=("Segoe UI", 16)).pack(anchor="w")
    ttk.Label(header, text="输入卡组 ID，运行本地计算并查看结果", style="Muted.TLabel").pack(anchor="w", pady=(6, 0))

    card = ttk.Frame(wrapper, style="Card.TFrame", padding=16)
    card.pack(fill="x", pady=(14, 0))

    form = ttk.Frame(card, style="Card.TFrame")
    form.pack(fill="x")

    deck_var = tk.StringVar(value="yanhong,wenmin,linfeng")
    level_var = tk.IntVar(value=6)
    max_time_var = tk.IntVar(value=180)
    seed_var = tk.StringVar(value="")

    ttk.Label(form, text="卡组ID（逗号分隔）", style="CardDesc.TLabel").grid(row=0, column=0, sticky="w")
    ttk.Entry(form, textvariable=deck_var).grid(row=0, column=1, sticky="we", padx=(12, 0))

    ttk.Label(form, text="等级", style="CardDesc.TLabel").grid(row=1, column=0, sticky="w", pady=(10, 0))
    ttk.Spinbox(form, from_=0, to=6, textvariable=level_var, width=6).grid(row=1, column=1, sticky="w", padx=(12, 0), pady=(10, 0))

    ttk.Label(form, text="战斗时长(秒)", style="CardDesc.TLabel").grid(row=2, column=0, sticky="w", pady=(10, 0))
    ttk.Spinbox(form, from_=10, to=600, textvariable=max_time_var, width=8).grid(row=2, column=1, sticky="w", padx=(12, 0), pady=(10, 0))

    ttk.Label(form, text="随机种子(可空)", style="CardDesc.TLabel").grid(row=3, column=0, sticky="w", pady=(10, 0))
    ttk.Entry(form, textvariable=seed_var, width=12).grid(row=3, column=1, sticky="w", padx=(12, 0), pady=(10, 0))

    form.columnconfigure(1, weight=1)

    actions = ttk.Frame(card, style="Card.TFrame")
    actions.pack(fill="x", pady=(14, 0))

    output = tk.Text(wrapper, height=14, wrap="word", bg="#141414", fg="#e6e6e6", insertbackground="#e6e6e6", relief="flat")
    output.pack(fill="both", expand=True, pady=(14, 0))

    running = {"value": False}

    def _set_running(value):
        running["value"] = value

    def _run_in_thread():
        raw = deck_var.get().strip()
        deck_ids = [x.strip() for x in raw.split(",") if x.strip()]
        level = int(level_var.get())
        max_time = float(max_time_var.get())
        seed_raw = seed_var.get().strip()
        seed = None
        if seed_raw:
            try:
                seed = int(seed_raw)
            except Exception:
                seed = None

        started_at = time.time()
        log(f"开始运行：deck={deck_ids} level={level} time={max_time}s seed={seed if seed is not None else '默认'}")
        set_status("运行中…")
        try:
            result = run_danqing(deck_ids, level=level, max_time=max_time, seed=seed)
            payload = json.dumps(result, ensure_ascii=False, indent=2)
            elapsed = time.time() - started_at
            log(f"运行完成：{elapsed:.2f}s")

            def _apply_result():
                output.delete("1.0", "end")
                output.insert("1.0", payload)

            output.after(0, _apply_result)
        except Exception:
            err = traceback.format_exc()
            log(err.rstrip())

            def _apply_error():
                output.delete("1.0", "end")
                output.insert("1.0", err)

            output.after(0, _apply_error)
        finally:
            _set_running(False)
            set_status("就绪")

    def on_run():
        if running["value"]:
            return
        _set_running(True)
        threading.Thread(target=_run_in_thread, daemon=True).start()

    run_btn = ttk.Button(actions, text="开始", style="Primary.TButton", command=on_run)
    run_btn.pack(side="left")
    return wrapper


def start():
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    app_cfg = _load_app_config(project_root)
    tools_cfg = _load_tools_config(project_root)

    root = tk.Tk()
    root.title(f"{app_cfg.get('name')} v{app_cfg.get('version')}")
    root.geometry("1180x720")
    root.minsize(980, 620)

    theme = _apply_dark_theme(root)

    root_grid = ttk.Frame(root)
    root_grid.pack(fill="both", expand=True)
    root_grid.columnconfigure(0, weight=1)
    root_grid.rowconfigure(1, weight=1)

    titlebar = ttk.Frame(root_grid, style="Panel.TFrame", padding=(14, 12))
    titlebar.grid(row=0, column=0, sticky="nsew")
    title_left = ttk.Frame(titlebar, style="Panel.TFrame")
    title_left.pack(side="left", fill="x", expand=True)
    ttk.Label(title_left, text=f"{app_cfg.get('name')}", style="Panel.TLabel", font=("Segoe UI", 16)).pack(anchor="w")
    ttk.Label(title_left, text="桌面工具箱（参考 ok-wuthering-waves 的导航 + 内容 + 日志布局）", style="Muted.TLabel").pack(
        anchor="w", pady=(4, 0)
    )

    status_var = tk.StringVar(value="就绪")
    ttk.Label(titlebar, textvariable=status_var, style="Muted.TLabel").pack(side="right")

    body = ttk.PanedWindow(root_grid, orient="horizontal")
    body.grid(row=1, column=0, sticky="nsew")

    sidebar = ttk.Frame(body, style="Sidebar.TFrame", padding=(10, 10))
    body.add(sidebar, weight=0)

    main = ttk.PanedWindow(body, orient="vertical")
    body.add(main, weight=1)

    content_shell = ttk.Frame(main, style="Panel.TFrame", padding=14)
    main.add(content_shell, weight=3)

    content = ScrollableFrame(content_shell)
    content.pack(fill="both", expand=True)
    content.canvas.configure(background=theme["panel"])
    content.inner.configure(style="Panel.TFrame")

    log_shell = ttk.Frame(main, style="Panel.TFrame", padding=(14, 10))
    main.add(log_shell, weight=1)

    log_top = ttk.Frame(log_shell, style="Panel.TFrame")
    log_top.pack(fill="x")
    ttk.Label(log_top, text="运行日志", style="Panel.TLabel", font=("Segoe UI", 12)).pack(side="left")

    log_text = tk.Text(log_shell, height=8, wrap="word", bg="#101010", fg="#e6e6e6", insertbackground="#e6e6e6", relief="flat")
    log_text.pack(fill="both", expand=True, pady=(10, 0))

    def set_status(text):
        status_var.set(text)

    def log(message):
        ts = time.strftime("%H:%M:%S")
        log_text.insert("end", f"[{ts}] {message}\n")
        log_text.see("end")

    selected_tool_id = tk.StringVar(value="")
    selected_btn = {"value": None}

    style = ttk.Style(root)
    style.configure("SidebarSelected.TButton", padding=(10, 12), anchor="w", background="#242424", foreground=theme["text"])

    def render_tool(tool_id):
        for child in list(content.inner.winfo_children()):
            child.destroy()
        if tool_id == "danqing":
            _render_danqing_page(content.inner, log=log, set_status=set_status)
            return
        if tool_id == "rili":
            ttk.Label(content.inner, text="游戏日历需要 Qt 版本（请用 python main.py 启动）", style="Panel.TLabel").pack(
                anchor="w"
            )
            ttk.Label(
                content.inner,
                text="如果你看到这里，说明 Qt 启动失败并回退到了 Tkinter。",
                style="Muted.TLabel",
            ).pack(anchor="w", pady=(6, 0))
            return
        if tool_id == "tianshu":
            ttk.Label(content.inner, text="天书模拟器需要 Qt 版本（请用 python main.py 启动）", style="Panel.TLabel").pack(
                anchor="w"
            )
            ttk.Label(
                content.inner,
                text="如果你看到这里，说明 Qt 启动失败并回退到了 Tkinter。",
                style="Muted.TLabel",
            ).pack(anchor="w", pady=(6, 0))
            return
        ttk.Label(content.inner, text="该工具暂未实现", style="Panel.TLabel").pack(anchor="w")

    def on_select(tool_id):
        selected_tool_id.set(tool_id)
        render_tool(tool_id)

    def add_sidebar_button(tool):
        tool_id = tool.get("id") or ""
        name = tool.get("name") or tool_id
        btn = ttk.Button(sidebar, text=name, style="Sidebar.TButton")
        btn.configure(command=lambda b=btn, tid=tool_id: (select_button(b), on_select(tid)))
        btn.pack(fill="x", pady=6)
        return btn

    def select_button(btn):
        prev = selected_btn["value"]
        if prev is not None and prev.winfo_exists():
            prev.configure(style="Sidebar.TButton")
        selected_btn["value"] = btn
        if btn is not None and btn.winfo_exists():
            btn.configure(style="SidebarSelected.TButton")

    if tools_cfg:
        buttons = []
        for t in tools_cfg:
            buttons.append((t.get("id") or "", add_sidebar_button(t)))
        first_id = tools_cfg[0].get("id") or ""
        if first_id:
            on_select(first_id)
            for tool_id, btn in buttons:
                if tool_id == first_id:
                    select_button(btn)
                    break
    else:
        ttk.Label(sidebar, text="无工具配置", style="Panel.TLabel").pack(padx=10, pady=10)

    root.mainloop()
