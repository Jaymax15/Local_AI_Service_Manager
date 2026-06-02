"""Ollama model manager and curated model catalog.

This file is intentionally separate from services.py/installer.py so model choices
can grow without changing the service install system. It contains a small curated
list of well-known assistant and role-play models in practical sizes.
"""

import re
import threading
import time
import tkinter as tk
from tkinter import ttk

from components import settings as settings_store
from components import uihelpers


MODEL_CATALOG = [
    # Assistant / general purpose
    {"name": "llama3.2:1b", "label": "Llama 3.2 1B - assistant - tiny/fast", "category": "Assistant", "size": "1B"},
    {"name": "llama3.2:3b", "label": "Llama 3.2 3B - assistant - small", "category": "Assistant", "size": "3B"},
    {"name": "llama3.1:8b", "label": "Llama 3.1 8B - assistant - balanced", "category": "Assistant", "size": "8B"},
    {"name": "qwen2.5:3b", "label": "Qwen2.5 3B - assistant/coding - small", "category": "Assistant", "size": "3B"},
    {"name": "qwen2.5:7b", "label": "Qwen2.5 7B - assistant/coding - balanced", "category": "Assistant", "size": "7B"},
    {"name": "qwen2.5:14b", "label": "Qwen2.5 14B - assistant/coding - larger", "category": "Assistant", "size": "14B"},
    {"name": "mistral:7b", "label": "Mistral 7B - assistant - balanced", "category": "Assistant", "size": "7B"},
    {"name": "gemma2:2b", "label": "Gemma 2 2B - assistant - tiny", "category": "Assistant", "size": "2B"},
    {"name": "gemma2:9b", "label": "Gemma 2 9B - assistant - balanced", "category": "Assistant", "size": "9B"},
    {"name": "phi3:mini", "label": "Phi-3 Mini - assistant - tiny", "category": "Assistant", "size": "mini"},
    {"name": "deepseek-r1:1.5b", "label": "DeepSeek R1 1.5B - reasoning - tiny", "category": "Assistant", "size": "1.5B"},
    {"name": "deepseek-r1:7b", "label": "DeepSeek R1 7B - reasoning - balanced", "category": "Assistant", "size": "7B"},
    {"name": "codellama:7b", "label": "CodeLlama 7B - coding", "category": "Coding", "size": "7B"},
    {"name": "qwen2.5-coder:7b", "label": "Qwen2.5 Coder 7B - coding", "category": "Coding", "size": "7B"},
    # Role play / story oriented
    {"name": "dolphin-mistral:7b", "label": "Dolphin Mistral 7B - role play/chat", "category": "Role play", "size": "7B"},
    {"name": "dolphin-llama3:8b", "label": "Dolphin Llama 3 8B - role play/chat", "category": "Role play", "size": "8B"},
    {"name": "neural-chat:7b", "label": "Neural Chat 7B - role play/chat", "category": "Role play", "size": "7B"},
    {"name": "openchat:7b", "label": "OpenChat 7B - role play/chat", "category": "Role play", "size": "7B"},
    {"name": "nous-hermes2:10.7b", "label": "Nous Hermes 2 10.7B - role play/writing", "category": "Role play", "size": "10.7B"},
    {"name": "wizard-vicuna-uncensored:7b", "label": "Wizard Vicuna 7B - role play/chat", "category": "Role play", "size": "7B"},
]


def _center_on_services(manager, win, width=900, height=600):
    manager.root.update_idletasks()
    anchor = getattr(manager, "overlay", None) or manager.root
    x = anchor.winfo_rootx() + max(0, (anchor.winfo_width() - width) // 2)
    y = anchor.winfo_rooty() + max(0, (anchor.winfo_height() - height) // 2)
    win.geometry(f"{width}x{height}+{x}+{y}")


def _safe_model_name(value):
    value = str(value or "").strip()
    # Ollama names commonly use letters, numbers, dots, underscores, dashes, slashes and tags.
    if not re.fullmatch(r"[A-Za-z0-9._:/-]{1,120}", value):
        return ""
    return value


def _parse_ollama_list(text):
    models = []
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line or line.lower().startswith("name"):
            continue
        parts = line.split()
        if parts:
            models.append(parts[0])
    return models


def _run_model_command(manager, command, timeout=None, on_line=None):
    try:
        if hasattr(manager, "run_stream") and on_line is not None:
            return manager.run_stream(command, on_line=on_line, timeout=timeout)
        out = manager.run_capture(command, timeout=timeout)
        return 0, out
    except Exception as e:
        return 1, str(e)


def open_models_window(manager):
    colors = settings_store.get_theme_colors()
    try:
        if not manager.is_service_installed("ollama"):
            manager.write("[MODELS] Ollama must be installed before opening Manage Models.", "warn")
            return
    except Exception:
        pass

    backdrop = uihelpers.show_modal_backdrop(manager)
    win = tk.Toplevel(manager.root)
    win.overrideredirect(True)
    win.configure(bg=colors["text_bg"])
    _center_on_services(manager, win)
    win.transient(manager.root)
    try:
        win.wm_attributes("-topmost", 1)
    except Exception:
        pass
    win.grab_set()

    installed_models = []
    installed_rows_frame = None
    status_var = tk.StringVar(value="Checking installed models...")
    selected_model = tk.StringVar(value=MODEL_CATALOG[0]["label"])
    search_var = tk.StringVar(value="")

    def close_models():
        try:
            manager.schedule_global_refresh(2000, log=False)
        except Exception:
            pass
        try:
            win.wm_attributes("-topmost", 0)
        except Exception:
            pass
        try:
            win.destroy()
        except Exception:
            pass
        uihelpers.hide_modal_backdrop(manager)

    win.bind("<Escape>", lambda _e: close_models())

    outer = tk.Frame(win, bg=colors["text_bg"], highlightbackground=colors["border"], highlightthickness=1)
    outer.pack(fill=tk.BOTH, expand=True)
    header = tk.Frame(outer, bg=colors["header_bg"])
    header.pack(fill=tk.X)
    tk.Label(header, text="Model manager", bg=colors["header_bg"], fg=colors["fg"], font=("Segoe UI", 14, "bold"), anchor="w", padx=12, pady=10).pack(side=tk.LEFT, fill=tk.X, expand=True)
    uihelpers.rounded_button(header, "CLOSE", close_models, bg=colors["button_bad"], width=92, height=32).pack(side=tk.RIGHT, padx=10, pady=8)

    body = tk.Frame(outer, bg=colors["root_bg"])
    body.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)
    tk.Label(body, text="Install Ollama models from the curated list, or remove models already installed.", bg=colors["root_bg"], fg=colors["muted_fg"], font=("Segoe UI", 10), anchor="w").pack(fill=tk.X, pady=(0, 10))

    top = tk.Frame(body, bg=colors["panel_bg"], highlightbackground=colors["border"], highlightthickness=1, padx=10, pady=10)
    top.pack(fill=tk.X, pady=(0, 10))
    tk.Label(top, text="Search models", bg=colors["panel_bg"], fg=colors["muted_fg"], font=("Segoe UI", 9, "bold"), anchor="w").grid(row=0, column=0, sticky="w", padx=(0, 10))
    search_entry = tk.Entry(top, textvariable=search_var, bg=colors["text_bg"], fg=colors["fg"], insertbackground=colors["fg"], relief=tk.FLAT, font=("Segoe UI", 10))
    search_entry.grid(row=1, column=0, sticky="ew", padx=(0, 10), pady=(4, 0))
    tk.Label(top, text="Select model", bg=colors["panel_bg"], fg=colors["muted_fg"], font=("Segoe UI", 9, "bold"), anchor="w").grid(row=0, column=1, sticky="w")
    combo = ttk.Combobox(top, textvariable=selected_model, values=[m["label"] for m in MODEL_CATALOG], state="readonly", width=56)
    combo.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=(4, 0))
    top.grid_columnconfigure(0, weight=2)
    top.grid_columnconfigure(1, weight=5)

    def selected_name():
        label = selected_model.get()
        for model in MODEL_CATALOG:
            if model["label"] == label:
                return model["name"]
        return _safe_model_name(label.split()[0] if label else "")

    def filter_models(*_):
        q = search_var.get().strip().lower()
        values = [m["label"] for m in MODEL_CATALOG if not q or q in m["label"].lower() or q in m["name"].lower() or q in m["category"].lower() or q in m["size"].lower()]
        if not values:
            values = [m["label"] for m in MODEL_CATALOG]
        combo["values"] = values
        if selected_model.get() not in values:
            selected_model.set(values[0])

    search_var.trace_add("write", filter_models)

    action_row = tk.Frame(top, bg=colors["panel_bg"])
    action_row.grid(row=1, column=2, sticky="e", pady=(4, 0))

    content = tk.Frame(body, bg=colors["panel_bg"], highlightbackground=colors["border"], highlightthickness=1)
    content.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
    header_row = tk.Frame(content, bg=colors["header_bg"])
    header_row.pack(fill=tk.X)
    tk.Label(header_row, text="Installed models", bg=colors["header_bg"], fg=colors["muted_fg"], font=("Segoe UI", 9, "bold"), anchor="center").pack(fill=tk.X, pady=7)

    installed_rows_frame = tk.Frame(content, bg=colors["panel_bg"], padx=10, pady=10)
    installed_rows_frame.pack(fill=tk.BOTH, expand=True)

    status = tk.Label(body, textvariable=status_var, bg=colors["root_bg"], fg=colors["warn"], font=("Segoe UI", 10, "bold"), anchor="w")
    status.pack(fill=tk.X)

    def refresh_installed_rows():
        nonlocal installed_models
        for child in installed_rows_frame.winfo_children():
            child.destroy()
        if not installed_models:
            tk.Label(installed_rows_frame, text="No Ollama models installed yet.", bg=colors["panel_bg"], fg=colors["warn"], font=("Segoe UI", 11, "bold"), anchor="center").pack(fill=tk.X, pady=18)
            return
        for idx, model_name in enumerate(installed_models):
            row_bg = uihelpers.soft_row_bg(colors, idx)
            row = tk.Frame(installed_rows_frame, bg=row_bg, highlightbackground=colors["border"], highlightthickness=1)
            row.pack(fill=tk.X, pady=4)
            tk.Label(row, text=model_name, bg=row_bg, fg=colors["fg"], font=("Segoe UI", 11, "bold"), anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True, padx=12, pady=7)
            uihelpers.rounded_button(row, "Remove", command=lambda n=model_name: remove_model(n), bg=colors["button_bad"], width=118, height=31, font=("Segoe UI", 9, "bold")).pack(side=tk.RIGHT, padx=12, pady=5)

    def load_installed_models():
        status_var.set("Checking installed models...")
        def worker():
            cmd = "sudo -n systemctl start ollama >/dev/null 2>&1 || true; ollama list 2>&1"
            rc, out = _run_model_command(manager, cmd, timeout=20)
            models = _parse_ollama_list(out) if rc == 0 else []
            def apply():
                nonlocal installed_models
                installed_models = models
                refresh_installed_rows()
                status_var.set(f"Installed models: {len(models)}" if rc == 0 else "Could not read installed models. Check Ollama service/logs.")
            manager.safe_ui(apply)
        threading.Thread(target=worker, daemon=True).start()

    def install_selected_model():
        name = _safe_model_name(selected_name())
        if not name:
            status_var.set("Invalid model name selected.")
            return
        status_var.set(f"Installing {name}...")
        def on_line(line):
            text = str(line).strip()
            if not text:
                return
            if "%" in text or "pulling" in text.lower() or "verifying" in text.lower() or "success" in text.lower():
                manager.safe_ui(lambda t=text: status_var.set(f"Installing {name}: {t[:90]}"))
        def worker():
            manager.write(f"[MODELS] Installing Ollama model: {name}", "system")
            cmd = f"sudo -n systemctl start ollama >/dev/null 2>&1 || true; ollama pull {name}"
            rc, out = _run_model_command(manager, cmd, timeout=3600, on_line=on_line)
            if rc == 0:
                manager.write(f"[MODELS] Installed model: {name}", "good")
                manager.safe_ui(lambda: status_var.set(f"Installed {name}. Refreshing model list..."))
                time.sleep(0.5)
                load_installed_models()
            else:
                manager.write(f"[MODELS] ERROR: Model install failed for {name}: {out}", "error")
                manager.safe_ui(lambda: status_var.set(f"Install failed for {name}. Check terminal log."))
        threading.Thread(target=worker, daemon=True).start()

    def remove_model(name):
        safe = _safe_model_name(name)
        if not safe:
            status_var.set("Invalid model name.")
            return
        status_var.set(f"Removing {safe}...")
        def worker():
            manager.write(f"[MODELS] Removing Ollama model: {safe}", "system")
            rc, out = _run_model_command(manager, f"ollama rm {safe} 2>&1", timeout=120)
            if rc == 0:
                manager.write(f"[MODELS] Removed model: {safe}", "good")
                manager.safe_ui(lambda: status_var.set(f"Removed {safe}. Refreshing model list..."))
                time.sleep(0.5)
                load_installed_models()
            else:
                manager.write(f"[MODELS] ERROR: Model remove failed for {safe}: {out}", "error")
                manager.safe_ui(lambda: status_var.set(f"Remove failed for {safe}. Check terminal log."))
        threading.Thread(target=worker, daemon=True).start()

    uihelpers.rounded_button(action_row, "Install Model", command=install_selected_model, bg=colors["button_good"], width=145, height=32, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT)

    load_installed_models()
    try:
        search_entry.focus_set()
    except Exception:
        pass
