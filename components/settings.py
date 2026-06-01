import json
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from components import components as service_components
from components import uihelpers

SETTINGS_FILE = Path(__file__).with_name("settings.txt")

THEMES = {
    "dark": {
        "name": "Dark",
        "root_bg": "#101010",
        "panel_bg": "#181818",
        "header_bg": "#151515",
        "text_bg": "#050505",
        "fg": "#ffffff",
        "muted_fg": "#cccccc",
        "label_fg": "#dddddd",
        "accent": "#234f9c",
        "good": "#00ff99",
        "warn": "#ffaa00",
        "error": "#ff4444",
        "link": "#ffd36a",
        "border": "#303030",
        "button_text": "#ffffff",
    },
    "light": {
        "name": "Light",
        "root_bg": "#f3f3f3",
        "panel_bg": "#ffffff",
        "header_bg": "#e9e9e9",
        "text_bg": "#ffffff",
        "fg": "#111111",
        "muted_fg": "#444444",
        "label_fg": "#222222",
        "accent": "#2563eb",
        "good": "#067a46",
        "warn": "#9a6700",
        "error": "#b42318",
        "link": "#8a5a00",
        "border": "#c7c7c7",
        "button_text": "#ffffff",
    },
}


def default_settings():
    return {
        "theme": "dark",
        "services": service_components.get_default_service_enabled(),
        "service_priorities": service_components.get_default_priorities(),
        "gpu": {
            "llm_gpu": "0",
            "tts_gpu": "1",
        },
        "behavior": {
            "stop_on_close": True,
        },
    }


def load_settings():
    try:
        data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8")) if SETTINGS_FILE.exists() else {}
    except Exception:
        data = {}

    merged = default_settings()
    if isinstance(data, dict):
        for section, value in data.items():
            if isinstance(value, dict) and isinstance(merged.get(section), dict):
                merged[section].update(value)
            else:
                merged[section] = value

    # Self-heal new service keys without overwriting existing user choices.
    services = merged.setdefault("services", {})
    for key, value in service_components.get_default_service_enabled().items():
        services.setdefault(key, value)
    priorities = merged.setdefault("service_priorities", {})
    for key, value in service_components.get_default_priorities().items():
        priorities.setdefault(key, value)
    save_settings(merged)
    return merged


def save_settings(data):
    try:
        SETTINGS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True
    except Exception:
        return False


def get_theme_name():
    value = str(load_settings().get("theme", "dark")).lower()
    return value if value in THEMES else "dark"


def get_theme_colors():
    return dict(THEMES[get_theme_name()])


def set_theme_name(theme_name):
    theme_name = str(theme_name).lower()
    if theme_name not in THEMES:
        theme_name = "dark"
    data = load_settings()
    data["theme"] = theme_name
    return save_settings(data)


def get_service_enabled():
    return dict(load_settings().get("services", default_settings()["services"]))


def set_service_enabled(key, enabled):
    data = load_settings()
    data.setdefault("services", {})[key] = bool(enabled)
    return save_settings(data)


def get_service_priorities():
    return {k: int(v) for k, v in load_settings().get("service_priorities", default_settings()["service_priorities"]).items()}


def set_service_priority(key, priority):
    data = load_settings()
    data.setdefault("service_priorities", {})[key] = int(priority)
    return save_settings(data)


def get_gpu_settings():
    return dict(load_settings().get("gpu", default_settings()["gpu"]))


def set_gpu_setting(key, value):
    data = load_settings()
    value = "" if str(value).lower() == "auto" else str(value).strip()
    data.setdefault("gpu", {})[key] = value
    return save_settings(data)


def services_are_busy(manager):
    """Fast busy check for Settings UI.

    Do not trigger live WSL/Docker checks while opening Settings; use cached
    service state/process info so the menu appears immediately.
    """
    try:
        if getattr(manager, "running", False) or getattr(manager, "stopping", False):
            return True
        states = getattr(manager, "_service_states_cache", {}) or {}
        if any(states.values()):
            return True
        for key in service_components.SERVICE_HANDLERS:
            if manager.service_process_active(key):
                return True
    except Exception:
        pass
    return False

def gpu_options(manager=None):
    """Return list of (label, value) GPU choices, with Auto first.

    Prefer the manager's startup/monitor cache so opening Settings does not block.
    """
    options = [("Auto", "")]
    cached = []
    try:
        if manager is not None:
            cached = getattr(manager, "gpu_rows_cache", []) or []
    except Exception:
        cached = []
    for row in cached:
        try:
            idx, name = str(row[0]), str(row[1])
            options.append((f"GPU {idx} - {name}", idx))
        except Exception:
            pass
    if len(options) > 1:
        return options

    cmd = ["nvidia-smi", "--query-gpu=index,name", "--format=csv,noheader,nounits"]
    out = ""
    try:
        out = subprocess.check_output(cmd, text=True, encoding="utf-8", errors="replace", timeout=1.5).strip()
    except Exception:
        out = ""
    for line in str(out).splitlines():
        parts = [p.strip() for p in line.split(",", 1)]
        if not parts or not parts[0].isdigit():
            continue
        idx = parts[0]
        name = parts[1] if len(parts) > 1 else f"GPU {idx}"
        options.append((f"GPU {idx} - {name}", idx))
    return options

def _center_locked_window(manager, win, width=760, height=480):
    manager.root.update_idletasks()
    anchor = getattr(manager, "overlay", None) or manager.root
    x = anchor.winfo_rootx() + max(0, (anchor.winfo_width() - width) // 2)
    y = anchor.winfo_rooty() + max(0, (anchor.winfo_height() - height) // 2)
    win.geometry(f"{width}x{height}+{x}+{y}")


def _locked_subwindow(manager, title, width=760, height=480):
    colors = get_theme_colors()
    win = tk.Toplevel(manager.root)
    win.overrideredirect(True)
    win.configure(bg=colors["text_bg"])
    _center_locked_window(manager, win, width, height)
    win.transient(manager.root)
    win.grab_set()

    outer = tk.Frame(win, bg=colors["text_bg"], highlightbackground=colors["border"], highlightthickness=1)
    outer.pack(fill=tk.BOTH, expand=True)
    header = tk.Frame(outer, bg=colors["header_bg"])
    header.pack(fill=tk.X)
    tk.Label(header, text=title, bg=colors["header_bg"], fg=colors["fg"], font=("Segoe UI", 14, "bold"), anchor="w", padx=12, pady=10).pack(side=tk.LEFT, fill=tk.X, expand=True)
    uihelpers.rounded_button(header, "CLOSE", win.destroy, bg="#9b1c1c", width=92, height=32).pack(side=tk.RIGHT, padx=10, pady=8)
    body = tk.Frame(outer, bg=colors["root_bg"], padx=14, pady=12)
    body.pack(fill=tk.BOTH, expand=True)
    return win, body, colors


def open_powershell_terminal(manager=None):
    try:
        if sys.platform == "win32":
            subprocess.Popen(["powershell.exe"], creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen(["powershell.exe"])
    except Exception as e:
        if manager is not None:
            manager.write(f"[SETTINGS] Could not open PowerShell: {e}", "error")


def open_sudo_window(manager):
    win, body, colors = _locked_subwindow(manager, "Sudo access", 780, 360)
    tk.Label(body, text="Enter your WSL/Linux sudo password once. The manager creates /etc/sudoers.d/ai-manager so start/stop tasks can use sudo -n later. Your password is not saved.", bg=colors["root_bg"], fg=colors["muted_fg"], font=("Segoe UI", 10), anchor="w", justify=tk.LEFT, wraplength=720).pack(fill=tk.X, pady=(0, 12))
    box = tk.Frame(body, bg=colors["panel_bg"], padx=14, pady=14)
    box.pack(fill=tk.X)
    row = tk.Frame(box, bg=colors["panel_bg"])
    row.pack(fill=tk.X, pady=(0, 10))
    tk.Label(row, text="Sudo password:", bg=colors["panel_bg"], fg=colors["label_fg"], font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=(0, 8))
    password_var = tk.StringVar()
    entry = tk.Entry(row, textvariable=password_var, show="*", bg=colors["text_bg"], fg=colors["fg"], insertbackground=colors["fg"], relief=tk.FLAT, font=("Consolas", 11), width=34)
    entry.pack(side=tk.LEFT, padx=(0, 10), ipady=6)
    status_var = tk.StringVar(value="Status: not installed/tested in this session.")
    status = tk.Label(box, textvariable=status_var, bg=colors["panel_bg"], fg=colors["warn"], font=("Segoe UI", 10, "bold"), anchor="w")
    status.pack(fill=tk.X, pady=(0, 10))

    def set_status(message, color=None):
        status_var.set("Status: " + message)
        status.config(fg=color or colors["muted_fg"])

    def setup_sudo():
        manager.install_sudo_permissions_from_settings(password_var.get(), set_status)
        password_var.set("")

    uihelpers.rounded_button(row, "SETUP SUDO ACCESS", command=setup_sudo, bg="#7a5b1f", width=190, height=38).pack(side=tk.LEFT)
    entry.focus_set()


def open_priority_window(manager):
    win, body, colors = _locked_subwindow(manager, "Service priorities", 760, 520)
    busy = services_are_busy(manager)
    note = "Change launch priority. Lower numbers start first." if not busy else "Stop all services before changing service priorities."
    tk.Label(body, text=note, bg=colors["root_bg"], fg=colors["warn"] if busy else colors["muted_fg"], font=("Segoe UI", 10, "bold" if busy else "normal"), anchor="w", justify=tk.LEFT).pack(fill=tk.X, pady=(0, 12))
    list_frame = tk.Frame(body, bg=colors["panel_bg"], padx=12, pady=12)
    list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
    current = get_service_priorities()
    vars_by_key = {}
    for display, key, url, default_priority in service_components.get_service_config(current):
        row = tk.Frame(list_frame, bg=colors["panel_bg"])
        row.pack(fill=tk.X, pady=5)
        tk.Label(row, text=display, bg=colors["panel_bg"], fg=colors["fg"], font=("Segoe UI", 11, "bold"), width=20, anchor="w").pack(side=tk.LEFT)
        var = tk.IntVar(value=int(current.get(key, default_priority)))
        vars_by_key[key] = var
        spin = tk.Spinbox(row, from_=0, to=9, width=5, textvariable=var, bg=colors["text_bg"], fg=colors["fg"], buttonbackground=colors["panel_bg"], relief=tk.FLAT, font=("Consolas", 10), state=tk.DISABLED if busy else tk.NORMAL)
        spin.pack(side=tk.LEFT, padx=(8, 12))
        tk.Label(row, text=url, bg=colors["panel_bg"], fg=colors["link"], font=("Consolas", 10), anchor="w").pack(side=tk.LEFT)

    def save_priorities():
        if services_are_busy(manager):
            manager.write("[SETTINGS] Stop all services before changing service priorities.", "warn")
            return
        for key, var in vars_by_key.items():
            set_service_priority(key, var.get())
        manager.service_priorities = get_service_priorities()
        manager.last_service_snapshot = ""
        manager.write("[SETTINGS] Service priorities saved.", "system")
        win.destroy()

    btn = uihelpers.rounded_button(body, "SAVE PRIORITIES", command=save_priorities, bg="#1f7a3a", width=170, height=38)
    btn.pack(side=tk.LEFT)
    if busy:
        btn.set_enabled(False)


def _option_menu(parent, variable, choices, colors, disabled=False):
    labels = [label for label, _value in choices]
    menu = tk.OptionMenu(parent, variable, *labels)
    menu.configure(bg=colors["text_bg"], fg=colors["fg"], activebackground=colors["panel_bg"], activeforeground=colors["fg"], highlightthickness=0, relief=tk.FLAT, font=("Segoe UI", 10, "bold"), width=30)
    try:
        menu["menu"].configure(bg=colors["text_bg"], fg=colors["fg"], activebackground=colors["panel_bg"], activeforeground=colors["fg"])
    except Exception:
        pass
    if disabled:
        menu.configure(state=tk.DISABLED)
    return menu


def build_settings(parent, manager):
    colors = get_theme_colors()
    parent.configure(bg=colors["root_bg"])

    outer = tk.Frame(parent, bg=colors["root_bg"])
    outer.pack(fill=tk.BOTH, expand=True)

    tk.Label(outer, text="Settings", bg=colors["root_bg"], fg=colors["fg"], font=("Segoe UI", 18, "bold"), anchor="w").pack(fill=tk.X, pady=(0, 10))

    # Sub-menu buttons stay at the top.
    tools = tk.Frame(outer, bg=colors["root_bg"])
    tools.pack(fill=tk.X, pady=(0, 14))
    uihelpers.rounded_button(tools, "SUDO ACCESS", command=lambda: open_sudo_window(manager), bg="#7a5b1f", width=160, height=38).pack(side=tk.LEFT, padx=(0, 10), pady=4)
    uihelpers.rounded_button(tools, "OPEN POWERSHELL", command=lambda: open_powershell_terminal(manager), bg="#234f9c", width=180, height=38).pack(side=tk.LEFT, padx=(0, 10), pady=4)
    prio_btn = uihelpers.rounded_button(tools, "SERVICE PRIORITIES", command=lambda: open_priority_window(manager), bg="#5b357a", width=190, height=38)
    prio_btn.pack(side=tk.LEFT, padx=(0, 10), pady=4)

    busy = services_are_busy(manager)
    if busy:
        prio_btn.set_enabled(False)
        tk.Label(outer, text="Stop all services before changing GPU or priority settings.", bg=colors["root_bg"], fg=colors["warn"], font=("Segoe UI", 10, "bold"), anchor="w").pack(fill=tk.X, pady=(0, 10))

    panel = tk.Frame(outer, bg=colors["panel_bg"], padx=14, pady=14)
    panel.pack(fill=tk.X, pady=(0, 14))

    tk.Label(panel, text="Theme", bg=colors["panel_bg"], fg=colors["fg"], font=("Segoe UI", 13, "bold"), anchor="w").pack(fill=tk.X, pady=(0, 8))
    theme_var = tk.StringVar(value=get_theme_name())
    theme_row = tk.Frame(panel, bg=colors["panel_bg"])
    theme_row.pack(fill=tk.X, pady=(0, 12))

    def set_theme():
        set_theme_name(theme_var.get())
        manager.apply_theme()
        manager.write(f"[SETTINGS] Theme changed to {THEMES[get_theme_name()]['name']}.", "system")
        manager.close_overlay()
        manager.open_settings_panel()

    for value, label in (("dark", "Dark mode"), ("light", "Light mode")):
        tk.Radiobutton(theme_row, text=label, variable=theme_var, value=value, command=set_theme, bg=colors["panel_bg"], fg=colors["fg"], selectcolor=colors["text_bg"], activebackground=colors["panel_bg"], activeforeground=colors["fg"], font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=(0, 18))

    tk.Label(panel, text="GPU", bg=colors["panel_bg"], fg=colors["fg"], font=("Segoe UI", 13, "bold"), anchor="w").pack(fill=tk.X, pady=(4, 8))
    gpu = get_gpu_settings()
    choices = gpu_options(manager)
    label_to_value = {label: value for label, value in choices}
    value_to_label = {value: label for label, value in choices}
    llm_var = tk.StringVar(value=value_to_label.get(gpu.get("llm_gpu", ""), "Auto"))
    tts_var = tk.StringVar(value=value_to_label.get(gpu.get("tts_gpu", ""), "Auto"))

    for label, var in (("LLM GPU", llm_var), ("TTS GPU", tts_var)):
        row = tk.Frame(panel, bg=colors["panel_bg"])
        row.pack(fill=tk.X, pady=5)
        tk.Label(row, text=label + ":", bg=colors["panel_bg"], fg=colors["fg"], font=("Segoe UI", 11, "bold"), width=12, anchor="w").pack(side=tk.LEFT)
        _option_menu(row, var, choices, colors, disabled=busy).pack(side=tk.LEFT, padx=(8, 12))

    def save_gpu():
        if services_are_busy(manager):
            manager.write("[SETTINGS] Stop all services before changing GPU settings.", "warn")
            return
        set_gpu_setting("llm_gpu", label_to_value.get(llm_var.get(), ""))
        set_gpu_setting("tts_gpu", label_to_value.get(tts_var.get(), ""))
        manager.gpu_settings = get_gpu_settings()
        manager.write("[SETTINGS] GPU settings saved.", "system")

    save_btn = uihelpers.rounded_button(panel, "SAVE GPU SETTINGS", command=save_gpu, bg="#1f7a3a", width=180, height=38)
    save_btn.pack(anchor="w", pady=(10, 0))
    if busy:
        save_btn.set_enabled(False)

    tk.Frame(outer, bg=colors["root_bg"]).pack(fill=tk.BOTH, expand=True)
    uihelpers.rounded_button(outer, "CLOSE SETTINGS", command=manager.close_overlay, bg=colors["accent"], width=160, height=38).pack(anchor="w", side=tk.BOTTOM)
