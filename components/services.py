import threading
import tkinter as tk
from components import settings as settings_store
from components import components as service_components
from components import installer
from components import models as models_window
from components import uihelpers


def get_service_config():
    return service_components.get_service_config(settings_store.get_service_priorities())


SERVICE_CONFIG = get_service_config()


def _spinbox(parent, value, colors, disabled=False, command=None):
    var = tk.IntVar(value=int(value))
    spin = tk.Spinbox(
        parent, from_=0, to=9, width=4, textvariable=var,
        bg=colors["text_bg"], fg=colors["fg"], buttonbackground=colors["panel_bg"],
        relief=tk.FLAT, font=("Consolas", 10), state=tk.DISABLED if disabled else tk.NORMAL,
        command=command,
        justify="center",
    )
    return spin, var


def _option_menu(parent, variable, choices, colors, disabled=False, command=None, width=28):
    labels = [label for label, _value in choices]
    if not labels:
        labels = ["Auto"]
        choices = [("Auto", "auto")]
    menu = tk.OptionMenu(parent, variable, *labels, command=(lambda _v: command() if command else None))
    menu.configure(
        bg=colors["text_bg"], fg=colors["fg"], activebackground=colors["panel_bg"],
        activeforeground=colors["fg"], highlightthickness=0, relief=tk.FLAT,
        font=("Segoe UI", 9, "bold"), width=width,
    )
    try:
        menu["menu"].configure(bg=colors["text_bg"], fg=colors["fg"], activebackground=colors["panel_bg"], activeforeground=colors["fg"])
    except Exception:
        pass
    if disabled:
        menu.configure(state=tk.DISABLED)
    return menu


def _grid_label(parent, text, colors, col, header=False, anchor="center", padx=6):
    font = ("Segoe UI", 9, "bold") if header else ("Segoe UI", 11, "bold")
    fg = colors["muted_fg"] if header else colors["fg"]
    lbl = tk.Label(parent, text=text, bg=parent.cget("bg"), fg=fg, font=font, anchor=anchor)
    lbl.grid(row=0, column=col, sticky="nsew", padx=padx, pady=6)
    return lbl


def build_services(parent, manager):
    """Internal fixed Services panel."""
    colors = settings_store.get_theme_colors()
    parent.configure(bg=colors["root_bg"])

    tk.Label(
        parent,
        text="Enable installed services, set launch priority, and choose processor preference. Stop all services before changing priority.",
        bg=colors["root_bg"], fg=colors["muted_fg"], font=("Segoe UI", 10), anchor="w", justify=tk.LEFT,
    ).pack(fill=tk.X, pady=(0, 12))

    busy = settings_store.services_are_busy(manager)
    if busy:
        tk.Label(parent, text="Services are running. Priority and processor controls are locked until STOP ALL is complete.", bg=colors["root_bg"], fg=colors["warn"], font=("Segoe UI", 10, "bold"), anchor="w").pack(fill=tk.X, pady=(0, 8))

    list_wrap = tk.Frame(parent, bg=colors["panel_bg"], highlightbackground=colors.get("border", "#303030"), highlightthickness=1)
    list_wrap.pack(fill=tk.BOTH, expand=True, pady=(0, 14))
    canvas = tk.Canvas(list_wrap, bg=colors["panel_bg"], highlightthickness=0)
    scrollbar = tk.Scrollbar(list_wrap, orient="vertical", command=canvas.yview, bg="#2a2a2a", troughcolor=colors["root_bg"])
    rows = tk.Frame(canvas, bg=colors["panel_bg"], padx=12, pady=12)
    rows_id = canvas.create_window((0, 0), window=rows, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    rows.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(rows_id, width=e.width))

    header = tk.Frame(rows, bg=colors["header_bg"])
    header.pack(fill=tk.X, pady=(0, 8))
    for col, weight in enumerate((4, 2, 2, 5)):
        header.grid_columnconfigure(col, weight=weight, uniform="svc")
    _grid_label(header, "Service", colors, 0, header=True)
    _grid_label(header, "Enabled", colors, 1, header=True)
    _grid_label(header, "Priority", colors, 2, header=True)
    _grid_label(header, "Processor", colors, 3, header=True)

    saved_services = settings_store.get_service_enabled()
    priorities = settings_store.get_service_priorities()
    processors = settings_store.get_service_processors()

    def row_is_installed(key):
        try:
            return manager.is_service_installed(key)
        except Exception:
            return service_components.is_installed(manager, key)

    def save_priority(key, var):
        if settings_store.services_are_busy(manager):
            manager.write("[SERVICES] Stop all services before changing priority.", "warn")
            return
        settings_store.set_service_priority(key, var.get())
        manager.service_priorities = settings_store.get_service_priorities()
        manager.write(f"[SERVICES] {service_components.SERVICE_HANDLERS[key]['display']} priority set to {var.get()}.", "system")
        manager.last_service_snapshot = ""
        try:
            manager.schedule_global_refresh(2000, log=False)
        except Exception:
            pass

    def save_processor(key, label_to_value, var):
        # Visual selector for now. Store the preference, but do not wire real GPU routing yet.
        if settings_store.services_are_busy(manager):
            manager.write("[SERVICES] Processor selector is locked while services are running.", "warn")
            return
        value = label_to_value.get(var.get(), "auto")
        settings_store.set_service_processor(key, value)
        manager.service_processors = settings_store.get_service_processors()
        manager.write(f"[SERVICES] {service_components.SERVICE_HANDLERS[key]['display']} processor preference set to {var.get()}.", "system")
        manager.last_service_snapshot = ""

    installed_any = False
    row_index = 0
    for display, key, _url, default_priority in get_service_config():
        if not row_is_installed(key):
            manager.service_enabled[key] = False
            settings_store.set_service_enabled(key, False)
            continue
        installed_any = True
        handler = service_components.SERVICE_HANDLERS.get(key, {})
        row_bg = uihelpers.soft_row_bg(colors, row_index)
        row_index += 1
        row = tk.Frame(rows, bg=row_bg, highlightbackground=colors.get("border", "#303030"), highlightthickness=1)
        row.pack(fill=tk.X, pady=4)
        for col, weight in enumerate((4, 2, 2, 5)):
            row.grid_columnconfigure(col, weight=weight, uniform="svc")

        tk.Label(row, text=display, bg=row_bg, fg=colors["fg"], font=("Segoe UI", 11, "bold"), anchor="center").grid(row=0, column=0, sticky="nsew", padx=6, pady=8)

        default = handler.get("default_enabled", True)
        enabled_var = tk.BooleanVar(value=manager.service_enabled.get(key, saved_services.get(key, default)))
        def on_toggle(k=key, v=enabled_var):
            manager.set_service_enabled(k, v.get())
            try:
                manager.schedule_global_refresh(2000, log=False)
            except Exception:
                pass
        check_cell = tk.Frame(row, bg=row_bg)
        check_cell.grid(row=0, column=1, sticky="nsew", padx=6, pady=6)
        tk.Checkbutton(check_cell, text="", variable=enabled_var, command=on_toggle, bg=row_bg, fg=colors["fg"], selectcolor=colors["text_bg"], activebackground=row_bg, activeforeground=colors["fg"]).pack(anchor="center")

        spin_cell = tk.Frame(row, bg=row_bg)
        spin_cell.grid(row=0, column=2, sticky="nsew", padx=6, pady=6)
        spin, prio_var = _spinbox(spin_cell, priorities.get(key, default_priority), colors, disabled=busy, command=lambda k=key: None)
        spin.pack(anchor="center")
        spin.configure(command=lambda k=key, v=prio_var: save_priority(k, v))
        spin.bind("<FocusOut>", lambda _e, k=key, v=prio_var: save_priority(k, v))
        spin.bind("<Return>", lambda _e, k=key, v=prio_var: save_priority(k, v))

        # Always show the processor selector for visual consistency, even if real routing is not ready.
        proc_choices = settings_store.processor_options(manager, supports_gpu=True)
        if len(proc_choices) < 2:
            proc_choices = [("Auto", "auto"), ("CPU", "cpu")]
        label_to_value = {label: value for label, value in proc_choices}
        value_to_label = {value: label for label, value in proc_choices}
        proc_value = processors.get(key, "auto")
        proc_var = tk.StringVar(value=value_to_label.get(proc_value, "Auto"))
        proc_cell = tk.Frame(row, bg=row_bg)
        proc_cell.grid(row=0, column=3, sticky="nsew", padx=6, pady=6)
        proc_menu = _option_menu(proc_cell, proc_var, proc_choices, colors, disabled=busy, command=lambda k=key, m=label_to_value, v=proc_var: save_processor(k, m, v), width=28)
        proc_menu.pack(anchor="center")

    if not installed_any:
        tk.Label(rows, text="No services are installed yet. Use Manage Services to install one.", bg=colors["panel_bg"], fg=colors["warn"], font=("Segoe UI", 11, "bold"), anchor="center").pack(fill=tk.X, pady=18)

    button_row = tk.Frame(parent, bg=colors["root_bg"])
    button_row.pack(fill=tk.X)
    left_buttons = tk.Frame(button_row, bg=colors["root_bg"])
    left_buttons.pack(side=tk.LEFT)
    uihelpers.rounded_button(left_buttons, "CLOSE SERVICES", command=manager.close_overlay, bg=colors["accent"], width=160, height=38).pack(side=tk.LEFT, padx=(0, 10))
    uihelpers.rounded_button(left_buttons, "Manage Services", command=lambda: installer.open_installer_window(manager), bg=colors["button_good"], width=175, height=38).pack(side=tk.LEFT, padx=(0, 10))

    ollama_installed = row_is_installed("ollama")
    model_btn = uihelpers.rounded_button(left_buttons, "Manage Models", command=lambda: models_window.open_models_window(manager), bg=colors["button_primary"], width=175, height=38)
    model_btn.pack(side=tk.LEFT, padx=(0, 10))
    if not ollama_installed:
        model_btn.set_enabled(False, text="Manage Models", bg=colors["button_secondary"])

    def auto_refresh_open_panel():
        try:
            if parent is None or not parent.winfo_exists():
                return
        except Exception:
            return

        before = dict(getattr(manager, "installed_services", {}))

        def worker():
            try:
                after = manager.refresh_installed_services(log=False)
                if after != before:
                    manager.safe_ui(lambda: (manager.close_overlay(), manager.open_services_panel()))
                    return
            except Exception:
                pass
            try:
                if parent is not None and parent.winfo_exists():
                    parent.after(5000, auto_refresh_open_panel)
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    try:
        parent.after(5000, auto_refresh_open_panel)
    except Exception:
        pass
