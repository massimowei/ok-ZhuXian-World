import json
import tkinter as tk
from tkinter import ttk
from tools.danqing.entry import run

def start():
    root = tk.Tk()
    root.title("丹青模拟器")
    root.geometry("720x520")

    container = ttk.Frame(root, padding=12)
    container.pack(fill="both", expand=True)

    title = ttk.Label(container, text="丹青模拟器 - 最小可运行 UI", font=("Segoe UI", 14))
    title.pack(anchor="w")

    form = ttk.Frame(container, padding=(0, 10))
    form.pack(fill="x")

    ttk.Label(form, text="卡组ID（逗号分隔）").grid(row=0, column=0, sticky="w")
    deck_var = tk.StringVar(value="yanhong,wenmin,linfeng")
    deck_entry = ttk.Entry(form, textvariable=deck_var)
    deck_entry.grid(row=0, column=1, sticky="we", padx=(8, 0))

    ttk.Label(form, text="等级").grid(row=1, column=0, sticky="w", pady=(8, 0))
    level_var = tk.StringVar(value="6")
    level_entry = ttk.Entry(form, textvariable=level_var, width=6)
    level_entry.grid(row=1, column=1, sticky="w", padx=(8, 0), pady=(8, 0))

    form.columnconfigure(1, weight=1)

    output = tk.Text(container, height=18, wrap="word")
    output.pack(fill="both", expand=True, pady=(12, 0))

    def on_run():
        raw = deck_var.get().strip()
        deck_ids = [x.strip() for x in raw.split(",") if x.strip()]
        try:
            level = int(level_var.get().strip())
        except Exception:
            level = 6
        result = run(deck_ids, level=level)
        output.delete("1.0", "end")
        output.insert("1.0", json.dumps(result, ensure_ascii=False, indent=2))

    actions = ttk.Frame(container, padding=(0, 12))
    actions.pack(fill="x")
    run_btn = ttk.Button(actions, text="运行模拟", command=on_run)
    run_btn.pack(side="left")

    root.mainloop()
