# Version: 1.1
import json
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from components import components as service_components
from components import uihelpers
from components import processorhandler

SETTINGS_FILE = Path(__file__).with_name("settings.txt")

THEMES = {
    "dark": {
        "name": "Dark",
        "root_bg": "#0f1115",
        "panel_bg": "#181b22",
        "header_bg": "#151821",
        "text_bg": "#0b0d12",
        "fg": "#f5f7fb",
        "muted_fg": "#aeb6c2",
        "label_fg": "#d8dee9",
        "accent": "#374151",
        "good": "#34d399",
        "warn": "#fbbf24",
        "error": "#f87171",
        "link": "#facc15",
        "border": "#2d3340",
        "button_text": "#ffffff",
        "button_primary": "#334155",
        "button_secondary": "#3f3f46",
        "button_good": "#256d3c",
        "button_bad": "#7a2e2e",
        "button_warn": "#7a5b1f",
    },
    "light": {
        "name": "Light",
        "root_bg": "#f4f6f8",
        "panel_bg": "#ffffff",
        "header_bg": "#e8edf3",
        "text_bg": "#ffffff",
        "fg": "#111827",
        "muted_fg": "#4b5563",
        "label_fg": "#1f2937",
        "accent": "#475569",
        "good": "#047857",
        "warn": "#a16207",
        "error": "#b91c1c",
        "link": "#8a5a00",
        "border": "#cbd5e1",
        "button_text": "#ffffff",
        "button_primary": "#475569",
        "button_secondary": "#52525b",
        "button_good": "#2f6f4e",
        "button_bad": "#8a3a3a",
        "button_warn": "#8a6a24",
    },
}


def default_settings():
    return {
        "file_version": "1.1",
        "theme": "dark",
        "services": service_components.get_default_service_enabled(),
        "service_priorities": service_components.get_default_priorities(),
        "service_processors": {key: "auto" for key in service_components.SERVICE_HANDLERS},
        "service_versions": {key: service_components.SERVICE_HANDLERS[key].get("version_label", "latest") for key in service_components.SERVICE_HANDLERS},
        "gpu": {"llm_gpu": "", "tts_gpu": ""},  # legacy kept for older files
        "behavior": {"stop_on_close": True},
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
    for key, value in service_components.get_default_service_enabled().items():
        merged.setdefault("services", {}).setdefault(key, value)
    for key, value in service_components.get_default_priorities().items():
        merged.setdefault("service_priorities", {}).setdefault(key, value)
    for key in service_components.SERVICE_HANDLERS:
        merged.setdefault("service_processors", {}).setdefault(key, "auto")
        merged.setdefault("service_versions", {}).setdefault(key, service_components.SERVICE_HANDLERS[key].get("version_label", "latest"))
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
    out = {}
    for k, v in load_settings().get("service_priorities", default_settings()["service_priorities"]).items():
        try:
            out[k] = int(v)
        except Exception:
            out[k] = service_components.SERVICE_HANDLERS.get(k, {}).get("priority", 99)
    return out


def set_service_priority(key, priority):
    data = load_settings()
    try:
        priority = int(priority)
    except Exception:
        priority = service_components.SERVICE_HANDLERS.get(key, {}).get("priority", 99)
    data.setdefault("service_priorities", {})[key] = priority
    return save_settings(data)


def get_service_processors():
    data = load_settings().get("service_processors", {})
    return {k: str(v or "auto") for k, v in data.items()}


def set_service_processor(key, value):
    data = load_settings()
    value = str(value or "auto").strip()
    if not value:
        value = "auto"
    data.setdefault("service_processors", {})[key] = value
    return save_settings(data)


def get_service_versions():
    return {k: str(v or "latest") for k, v in load_settings().get("service_versions", {}).items()}

def set_service_version(key, version):
    data = load_settings()
    data.setdefault("service_versions", {})[key] = str(version or "latest")
    return save_settings(data)

def set_service_versions(values):
    data = load_settings()
    data.setdefault("service_versions", {}).update({str(k): str(v or "latest") for k, v in dict(values or {}).items()})
    return save_settings(data)

# Legacy compatibility. New UI stores per-service processor settings instead.
def get_gpu_settings():
    return dict(load_settings().get("gpu", default_settings()["gpu"]))

def set_gpu_setting(key, value):
    data = load_settings()
    data.setdefault("gpu", {})[key] = "" if str(value).lower() == "auto" else str(value).strip()
    return save_settings(data)


def services_are_busy(manager):
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


def cpu_label(manager=None):
    try:
        cpu = getattr(manager, "cpu_status_cache", {}) or {}
        name = cpu.get("name") or "CPU"
        return f"CPU - {name}"
    except Exception:
        return "CPU"


def processor_options(manager=None, supports_gpu=True, service_key=None):
    # V78: processor options are now built by the generic processor handler.
    # The old supports_gpu flag is kept for compatibility with older calls.
    if service_key:
        return processorhandler.option_pairs_for_service(service_key, manager)
    if supports_gpu:
        return [(opt.label, opt.id) for opt in processorhandler.detect_processors(manager)]
    return [(label, value) for label, value in processorhandler.option_pairs_for_service("piper", manager)]


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
    uihelpers.rounded_button(header, "CLOSE", win.destroy, bg=colors["button_bad"], width=92, height=32).pack(side=tk.RIGHT, padx=10, pady=8)
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
    win, body, colors = _locked_subwindow(manager, "Sudo access", 820, 390)
    tk.Label(body, text="Enter your WSL/Linux sudo password once. The manager creates /etc/sudoers.d/ai-manager so start/stop tasks can use sudo -n later. Your password is not saved.", bg=colors["root_bg"], fg=colors["muted_fg"], font=("Segoe UI", 10), anchor="w", justify=tk.LEFT, wraplength=760).pack(fill=tk.X, pady=(0, 12))
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

    uihelpers.rounded_button(row, "SETUP SUDO ACCESS", command=setup_sudo, bg=colors["button_warn"], width=190, height=38).pack(side=tk.LEFT)
    entry.focus_set()


def _option_menu(parent, variable, choices, colors, disabled=False, command=None, width=30):
    labels = [label for label, _value in choices]
    menu = tk.OptionMenu(parent, variable, *labels, command=(lambda _v: command() if command else None))
    menu.configure(bg=colors["text_bg"], fg=colors["fg"], activebackground=colors["panel_bg"], activeforeground=colors["fg"], highlightthickness=0, relief=tk.FLAT, font=("Segoe UI", 10, "bold"), width=width)
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
    tools = tk.Frame(outer, bg=colors["root_bg"])
    tools.pack(fill=tk.X, pady=(0, 14))
    uihelpers.rounded_button(tools, "SUDO ACCESS", command=lambda: open_sudo_window(manager), bg=colors["button_warn"], width=160, height=38).pack(side=tk.LEFT, padx=(0, 10), pady=4)
    uihelpers.rounded_button(tools, "OPEN POWERSHELL", command=lambda: open_powershell_terminal(manager), bg=colors["button_primary"], width=180, height=38).pack(side=tk.LEFT, padx=(0, 10), pady=4)

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
        manager.close_overlay(); manager.open_settings_panel()

    for value, label in (("dark", "Dark mode"), ("light", "Light mode")):
        tk.Radiobutton(theme_row, text=label, variable=theme_var, value=value, command=set_theme, bg=colors["panel_bg"], fg=colors["fg"], selectcolor=colors["text_bg"], activebackground=colors["panel_bg"], activeforeground=colors["fg"], font=("Segoe UI", 10, "bold")).pack(side=tk.LEFT, padx=(0, 18))

    update_panel = tk.Frame(outer, bg=colors["panel_bg"], padx=14, pady=14)
    update_panel.pack(fill=tk.BOTH, expand=True, pady=(0, 14))
    update_header = tk.Frame(update_panel, bg=colors["panel_bg"])
    update_header.pack(fill=tk.X, pady=(0, 8))
    tk.Label(update_header, text="Terminal", bg=colors["panel_bg"], fg=colors["fg"], font=("Segoe UI", 13, "bold"), anchor="w").pack(side=tk.LEFT, fill=tk.X, expand=True)

    update_running = {"value": False}
    update_button_holder = tk.Frame(update_header, bg=colors["panel_bg"])
    update_button_holder.pack(side=tk.RIGHT)

    log_frame = tk.Frame(update_panel, bg=colors["text_bg"], highlightbackground=colors["border"], highlightthickness=1)
    log_frame.pack(fill=tk.BOTH, expand=True)
    update_log = tk.Text(log_frame, bg=colors["text_bg"], fg=colors["fg"], insertbackground=colors["fg"], relief=tk.FLAT, wrap=tk.WORD, font=("Consolas", 9), padx=8, pady=7)
    update_scroll = tk.Scrollbar(log_frame, command=update_log.yview)
    update_log.configure(yscrollcommand=update_scroll.set)
    update_log.tag_configure("info", foreground=colors["fg"])
    update_log.tag_configure("success", foreground=colors["good"])
    update_log.tag_configure("error", foreground=colors["error"])
    update_log.tag_configure("warn", foreground=colors["warn"])
    update_log.tag_configure("muted", foreground=colors["muted_fg"])
    update_log.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    update_scroll.pack(side=tk.RIGHT, fill=tk.Y)
    update_log.bind("<Key>", lambda _e: "break")

    def update_log_tag(message):
        lower = str(message or "").lower()
        if "failed" in lower or "unsuccessful" in lower or "error" in lower:
            return "error"
        if "successful" in lower or "updated" in lower or "new " in lower or "added" in lower:
            return "success"
        if "warning" in lower or "note:" in lower:
            return "warn"
        if lower.startswith("---") or "no changes" in lower or "version" in lower:
            return "muted"
        return "info"

    def update_log_line(message, tag=None):
        try:
            text = str(message).rstrip()
            update_log.insert(tk.END, text + "\n", tag or update_log_tag(text))
            update_log.see(tk.END)
        except Exception:
            pass

    update_log_line("Ready. Click Update to check GitHub for model-list and manager file updates.", "muted")

    def run_updates():
        if update_running["value"]:
            return
        update_running["value"] = True
        try:
            update_btn.configure(state=tk.DISABLED)
        except Exception:
            pass
        update_log_line("---", "muted")
        update_log_line("Starting update check...", "info")

        def worker():
            app_changed = False
            try:
                from components import models as model_catalog
                from components import updateutil

                def log_from_worker(text, tag=None):
                    try:
                        manager.safe_ui(lambda t=text, g=tag: update_log_line(t, g))
                    except Exception:
                        update_log_line(text, tag)

                log_from_worker("Checking curated model list...", "info")
                try:
                    model_result = model_catalog.update_model_catalog_from_github(log_callback=lambda text: log_from_worker(text))
                    if model_result.get("ok"):
                        log_from_worker("Model-list check complete.", "success" if model_result.get("changed") else "muted")
                except Exception as e:
                    log_from_worker(f"Model-list update unsuccessful: {e}", "error")

                log_from_worker("---", "muted")
                log_from_worker("Checking manager files...", "info")
                app_result = updateutil.apply_manager_updates_from_github(log_callback=log_from_worker)
                app_changed = bool(app_result.get("changed"))
                try:
                    manager.write("[SETTINGS] Update check complete.", "system")
                except Exception:
                    pass
            except Exception as e:
                try:
                    manager.safe_ui(lambda err=e: update_log_line(f"Update unsuccessful: {err}", "error"))
                except Exception:
                    pass
            finally:
                def finish():
                    update_running["value"] = False
                    try:
                        update_btn.configure(state=tk.NORMAL)
                    except Exception:
                        pass
                    if app_changed:
                        try:
                            update_btn.configure(state=tk.DISABLED)
                        except Exception:
                            pass
                        update_log_line("Closing manager in 3 seconds. Please reopen it after update.", "warn")
                        try:
                            manager.root.after(3000, manager.root.destroy)
                        except Exception:
                            pass
                try:
                    manager.safe_ui(finish)
                except Exception:
                    finish()

        threading.Thread(target=worker, daemon=True).start()

    update_btn = uihelpers.rounded_button(update_button_holder, "Update", command=run_updates, bg=colors["button_primary"], width=138, height=34, font=("Segoe UI", 9, "bold"))
    update_btn.pack(side=tk.RIGHT)
    tk.Label(update_panel, text="Updates the model list and checks GitHub for newer manager files.", bg=colors["panel_bg"], fg=colors["muted_fg"], font=("Segoe UI", 9), anchor="w").pack(fill=tk.X, pady=(8, 0))

    tk.Label(panel, text="Service priorities and processor choices have moved to the Services menu.", bg=colors["panel_bg"], fg=colors["muted_fg"], font=("Segoe UI", 10), anchor="w").pack(fill=tk.X, pady=(4, 0))
    uihelpers.rounded_button(outer, "CLOSE SETTINGS", command=manager.close_overlay, bg=colors["accent"], width=160, height=38).pack(anchor="w", side=tk.BOTTOM)
