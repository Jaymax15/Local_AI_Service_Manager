import threading
import tkinter as tk
from tkinter import messagebox
from components import settings as settings_store
from components import components as service_components
from components import installer
from components import uihelpers


def get_service_config():
    return service_components.get_service_config(settings_store.get_service_priorities())


SERVICE_CONFIG = get_service_config()


def build_services(parent, manager):
    """Internal fixed Services panel.

    Only installed services are shown here. Missing services live in Add service.
    Priority stays internal and is never shown to the user.
    """
    colors = settings_store.get_theme_colors()
    parent.configure(bg=colors["root_bg"])

    tk.Label(parent, text="Services", bg=colors["root_bg"], fg=colors["fg"], font=("Segoe UI", 18, "bold"), anchor="w").pack(fill=tk.X, pady=(0, 8))
    tk.Label(
        parent,
        text="Enable installed services for START ALL. Use Add service to install new services, or Uninstall to remove one.",
        bg=colors["root_bg"], fg=colors["muted_fg"], font=("Segoe UI", 11), anchor="w", justify=tk.LEFT,
    ).pack(fill=tk.X, pady=(0, 16))

    list_frame = tk.Frame(parent, bg=colors["panel_bg"], padx=12, pady=12)
    list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 18))

    header = tk.Frame(list_frame, bg=colors["panel_bg"])
    header.pack(fill=tk.X, pady=(0, 8))
    for text, width in (("Service", 20), ("Enabled", 10), ("URL", 22), ("Action", 12)):
        tk.Label(header, text=text, bg=colors["panel_bg"], fg=colors["muted_fg"], font=("Segoe UI", 9, "bold"), width=width, anchor="w").pack(side=tk.LEFT, padx=(0, 8))

    saved_services = settings_store.get_service_enabled()
    row_widgets = {}

    def row_is_installed(key):
        # Use V20 manager cache. Do not run WSL checks while building the Tk window.
        try:
            return manager.is_service_installed(key)
        except Exception:
            return True

    def rebuild_services_panel():
        manager.close_overlay()
        manager.open_services_panel()

    def uninstall_service(key):
        display = service_components.SERVICE_HANDLERS[key].get("display", key)
        if not messagebox.askyesno(
            "Uninstall service",
            f"Uninstall {display}?\n\nThis will stop the service and remove its service folder if the manager owns one.",
        ):
            return
        row_widgets[key]["uninstall"].config(text="REMOVING...", state=tk.DISABLED, bg="#7a5b1f")
        manager.write(f"[SERVICES] Uninstall requested for {display}.")

        def worker():
            service_components.uninstall_service(manager, key)
            manager.safe_ui(rebuild_services_panel)

        threading.Thread(target=worker, daemon=True).start()

    installed_any = False
    for display, key, url, _priority in get_service_config():
        if not row_is_installed(key):
            manager.service_enabled[key] = False
            settings_store.set_service_enabled(key, False)
            continue
        installed_any = True
        row = tk.Frame(list_frame, bg=colors["panel_bg"])
        row.pack(fill=tk.X, pady=6)

        tk.Label(row, text=display, bg=colors["panel_bg"], fg=colors["fg"], font=("Segoe UI", 11, "bold"), width=20, anchor="w").pack(side=tk.LEFT, padx=(0, 8))

        default = service_components.SERVICE_HANDLERS[key].get("default_enabled", True)
        var = tk.BooleanVar(value=manager.service_enabled.get(key, saved_services.get(key, default)))

        def on_toggle(k=key, v=var):
            manager.set_service_enabled(k, v.get())

        check = tk.Checkbutton(
            row, text="", variable=var, command=on_toggle,
            bg=colors["panel_bg"], fg=colors["fg"], selectcolor=colors["text_bg"],
            activebackground=colors["panel_bg"], activeforeground=colors["fg"], width=10, anchor="w",
        )
        check.pack(side=tk.LEFT, padx=(0, 8))

        url_label = tk.Label(row, text=url, bg=colors["panel_bg"], fg=colors["link"], font=("Consolas", 10, "underline"), width=22, anchor="w", cursor="hand2")
        url_label.pack(side=tk.LEFT, padx=(0, 8))
        uihelpers.make_link(url_label, url)

        uninstall_btn = uihelpers.rounded_button(
            row, "UNINSTALL", command=lambda k=key: uninstall_service(k),
            bg="#9b1c1c", width=118, height=32, font=("Segoe UI", 9, "bold")
        )
        uninstall_btn.pack(side=tk.LEFT, padx=(0, 8))

        row_widgets[key] = {"var": var, "check": check, "uninstall": uninstall_btn}

    if not installed_any:
        tk.Label(
            list_frame,
            text="No services are installed yet. Use ADD SERVICE to install one.",
            bg=colors["panel_bg"], fg=colors["warn"], font=("Segoe UI", 11, "bold"), anchor="w",
        ).pack(fill=tk.X, pady=10)

    button_row = tk.Frame(parent, bg=colors["root_bg"])
    button_row.pack(anchor="w")

    uihelpers.rounded_button(button_row, "CLOSE SERVICES", command=manager.close_overlay, bg="#5b357a", width=160, height=38).pack(side=tk.LEFT, padx=(0, 10))
    uihelpers.rounded_button(button_row, "ADD SERVICE", command=lambda: installer.open_installer_window(manager), bg="#1f7a3a", width=145, height=38).pack(side=tk.LEFT, padx=(0, 10))
    def refresh_then_rebuild():
        def worker():
            try:
                manager.refresh_installed_services(log=True)
            finally:
                manager.safe_ui(rebuild_services_panel)
        threading.Thread(target=worker, daemon=True).start()

    uihelpers.rounded_button(button_row, "REFRESH", command=refresh_then_rebuild, bg="#234f9c", width=110, height=38).pack(side=tk.LEFT)
