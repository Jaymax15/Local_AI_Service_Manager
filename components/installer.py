"""Installer window and service install catalog for AI Server Manager V18.

Add installable services here. Runtime details live in components.py.
The installer creates service folders and compose files, then the Services menu
will automatically show the service because it is now installed.
"""

import threading
import tkinter as tk
from tkinter import messagebox
from components import components as service_components
from components import uihelpers
from components import settings as settings_store

AI_DIR = service_components.AI_DIR
TTS_DIR = service_components.TTS_DIR
WEBUI_DIR = service_components.WEBUI_DIR

# =====================================================
# Install commands
# =====================================================

INSTALL_OPEN_WEBUI = f'''#!/usr/bin/env bash
set -e
mkdir -p {WEBUI_DIR}/open-webui/data
cd {WEBUI_DIR}/open-webui
SECRET="$(openssl rand -hex 32 2>/dev/null || date +%s%N)"
cat > docker-compose.yml <<EOF
services:
  open-webui:
    image: ghcr.io/open-webui/open-webui:main
    container_name: open-webui
    restart: unless-stopped
    ports:
      - "3000:8080"
    environment:
      - WEBUI_SECRET_KEY=$SECRET
      - OLLAMA_BASE_URL=http://host.docker.internal:11434
    volumes:
      - ./data:/app/backend/data
    extra_hosts:
      - "host.docker.internal:host-gateway"
EOF
docker compose pull
echo "Open WebUI installed at {WEBUI_DIR}/open-webui"
'''

INSTALL_KOKORO = f'''#!/usr/bin/env bash
set -e
mkdir -p {TTS_DIR}/kokoro
cd {TTS_DIR}/kokoro
cat > docker-compose.yml <<'EOF'
services:
  kokoro-fastapi:
    image: ghcr.io/remsky/kokoro-fastapi-gpu:v0.2.1
    container_name: kokoro-fastapi
    restart: unless-stopped
    ports:
      - "8880:8880"
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities:
                - gpu
EOF
docker compose pull
echo "Kokoro installed at {TTS_DIR}/kokoro"
'''

INSTALL_PIPER = f'''#!/usr/bin/env bash
set -e
mkdir -p {TTS_DIR}/piper/piper-data
cd {TTS_DIR}/piper
cat > docker-compose.yml <<'EOF'
services:
  piper:
    image: kamilkrawiec/piper-openai-tts:master
    container_name: piper-openai-tts
    restart: unless-stopped
    ports:
      - "5000:5000"
    environment:
      - PORT=5000
      - DATA_DIR=/data
    volumes:
      - ./piper-data:/data
EOF
docker compose pull
echo "Piper installed at {TTS_DIR}/piper"
'''

INSTALL_OLLAMA = '''#!/usr/bin/env bash
set -e
curl -fsSL https://ollama.com/install.sh | sh
echo "Ollama install script complete."
'''

SERVICE_CATALOG = [
    {
        "key": "ollama",
        "display": "Ollama",
        "version_label": "latest",
        "version_command": "curl -fsSL https://api.github.com/repos/ollama/ollama/releases/latest 2>/dev/null | grep -m1 '\"tag_name\"' | sed -E 's/.*\"([^\"]+)\".*/\\1/' || echo latest",
        "install_command": INSTALL_OLLAMA,
    },
    {
        "key": "xtts",
        "display": "XTTS2",
        "version_label": "project compose",
        "version_command": "echo project-compose",
        "install_command": None,
    },
    {
        "key": "kokoro",
        "display": "Kokoro",
        "version_label": "v0.2.1 GPU",
        "version_command": "docker manifest inspect ghcr.io/remsky/kokoro-fastapi-gpu:v0.2.1 >/dev/null 2>&1 && echo v0.2.1 || echo v0.2.1",
        "install_command": INSTALL_KOKORO,
    },
    {
        "key": "piper",
        "display": "Piper",
        "version_label": "master",
        "version_command": "docker manifest inspect kamilkrawiec/piper-openai-tts:master >/dev/null 2>&1 && echo master || echo master",
        "install_command": INSTALL_PIPER,
    },
    {
        "key": "silly",
        "display": "SillyTavern",
        "version_label": "project folder",
        "version_command": "echo project-folder",
        "install_command": None,
    },
    {
        "key": "openwebui",
        "display": "Open WebUI",
        "version_label": "main",
        "version_command": "docker manifest inspect ghcr.io/open-webui/open-webui:main >/dev/null 2>&1 && echo main || echo main",
        "install_command": INSTALL_OPEN_WEBUI,
    },
]


def _status_color(installed):
    return "#00ff99" if installed else "#ffaa00"


def _center_on_services(manager, win, width=820, height=520):
    manager.root.update_idletasks()
    anchor = manager.overlay if getattr(manager, "overlay", None) is not None else manager.root
    x = anchor.winfo_rootx() + max(0, (anchor.winfo_width() - width) // 2)
    y = anchor.winfo_rooty() + max(0, (anchor.winfo_height() - height) // 2)
    win.geometry(f"{width}x{height}+{x}+{y}")


def open_installer_window(manager):
    colors = settings_store.get_theme_colors()
    win = tk.Toplevel(manager.root)
    win.overrideredirect(True)  # custom themed border/header; locked, unmovable
    win.configure(bg=colors["text_bg"])
    _center_on_services(manager, win)
    win.transient(manager.root)
    win.grab_set()

    outer = tk.Frame(win, bg=colors["text_bg"], highlightbackground=colors["border"], highlightthickness=1)
    outer.pack(fill=tk.BOTH, expand=True)

    header = tk.Frame(outer, bg=colors["header_bg"])
    header.pack(fill=tk.X)
    tk.Label(
        header,
        text="Add service",
        bg=colors["header_bg"],
        fg=colors["fg"],
        font=("Segoe UI", 14, "bold"),
        anchor="w",
        padx=12,
        pady=10,
    ).pack(side=tk.LEFT, fill=tk.X, expand=True)
    uihelpers.rounded_button(header, "CLOSE", win.destroy, bg="#9b1c1c", width=92, height=32).pack(side=tk.RIGHT, padx=10, pady=8)

    body = tk.Frame(outer, bg=colors["root_bg"])
    body.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)

    tk.Label(
        body,
        text="Pick a service to install. Installed services can be enabled from the Services menu.",
        bg=colors["root_bg"],
        fg=colors["muted_fg"],
        font=("Segoe UI", 10),
        anchor="w",
    ).pack(fill=tk.X, pady=(0, 12))

    # Scrollable list for future expansion.
    list_wrap = tk.Frame(body, bg=colors["panel_bg"])
    list_wrap.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
    canvas = tk.Canvas(list_wrap, bg=colors["panel_bg"], highlightthickness=0)
    scrollbar = tk.Scrollbar(list_wrap, orient="vertical", command=canvas.yview, bg="#2a2a2a", troughcolor=colors["root_bg"])
    rows = tk.Frame(canvas, bg=colors["panel_bg"], padx=10, pady=10)
    rows_id = canvas.create_window((0, 0), window=rows, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _on_rows_configure(_event=None):
        canvas.configure(scrollregion=canvas.bbox("all"))
    def _on_canvas_configure(event):
        canvas.itemconfigure(rows_id, width=event.width)
    rows.bind("<Configure>", _on_rows_configure)
    canvas.bind("<Configure>", _on_canvas_configure)
    canvas.bind_all("<MouseWheel>", lambda e: canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

    status_labels = {}
    version_labels = {}
    buttons = {}

    def refresh_row(item):
        key = item["key"]
        try:
            installed = manager.is_service_installed(key)
        except Exception:
            installed = service_components.is_installed(manager, key)
        version = item.get("version_label", "latest")
        version_labels[key].config(text=f"V{version}")
        status_labels[key].config(text="Installed" if installed else "Not installed", fg=_status_color(installed))
        install_cmd = item.get("install_command")
        if installed:
            buttons[key].config(text="Installed", state=tk.DISABLED, bg="#303030")
        elif not install_cmd:
            buttons[key].config(text="Manual", state=tk.DISABLED, bg="#303030")
        else:
            buttons[key].config(text="Install", state=tk.NORMAL, bg="#1f7a3a")

    def refresh_versions():
        def worker():
            for item in SERVICE_CATALOG:
                key = item["key"]
                cmd = item.get("version_command")
                if not cmd:
                    continue
                try:
                    out = manager.run_capture(cmd, timeout=18)
                    first = str(out).strip().splitlines()[0] if str(out).strip() else item.get("version_label", "latest")
                    manager.safe_ui(lambda k=key, v=first: version_labels[k].config(text=f"V{v}"))
                except Exception:
                    pass
        threading.Thread(target=worker, daemon=True).start()

    def install_item(item):
        key = item["key"]
        display = item["display"]
        cmd = item.get("install_command")
        if not cmd:
            messagebox.showinfo("Manual install", f"{display} does not have an automatic installer yet.")
            return

        buttons[key].config(text="Installing...", state=tk.DISABLED, bg="#7a5b1f")
        status_labels[key].config(text="Installing", fg="#ffaa00")
        manager.write(f"[INSTALLER] Installing {display}...")

        def worker():
            output = manager.run_capture(cmd, timeout=900)
            for line in str(output).splitlines():
                line = line.strip()
                if line:
                    manager.write(f"[INSTALLER] {line}")
            try:
                manager.refresh_installed_services()
                installed = manager.is_service_installed(key)
            except Exception:
                installed = service_components.is_installed(manager, key)
            if installed:
                manager.write(f"[INSTALLER] {display} installed.", "good")
            else:
                manager.write(f"[INSTALLER] {display} installer finished, but installed check did not pass.", "warn")
            manager.safe_ui(lambda i=item: refresh_row(i))
            manager.safe_ui(lambda: manager.close_overlay() or manager.open_services_panel())

        threading.Thread(target=worker, daemon=True).start()

    for item in SERVICE_CATALOG:
        row = tk.Frame(rows, bg=colors["panel_bg"])
        row.pack(fill=tk.X, pady=5)

        tk.Label(row, text=item["display"], bg=colors["panel_bg"], fg=colors["fg"], font=("Segoe UI", 11, "bold"), width=18, anchor="w").pack(side=tk.LEFT)
        version_labels[item["key"]] = tk.Label(row, text=f"V{item.get('version_label', 'latest')}", bg=colors["panel_bg"], fg="#2f6fed" if settings_store.get_theme_name()=="light" else "#b7d7ff", font=("Consolas", 10), width=18, anchor="w")
        version_labels[item["key"]].pack(side=tk.LEFT, padx=(8, 8))
        status_labels[item["key"]] = tk.Label(row, text="Checking", bg=colors["panel_bg"], fg=colors["warn"], font=("Segoe UI", 10, "bold"), width=14, anchor="w")
        status_labels[item["key"]].pack(side=tk.LEFT, padx=(8, 8))
        buttons[item["key"]] = uihelpers.rounded_button(row, "Install", command=lambda i=item: install_item(i), bg="#1f7a3a", width=110, height=32, font=("Segoe UI", 9, "bold"))
        buttons[item["key"]].pack(side=tk.RIGHT)
        refresh_row(item)

    bottom = tk.Frame(body, bg=colors["root_bg"])
    bottom.pack(fill=tk.X)
    uihelpers.rounded_button(bottom, "REFRESH", command=lambda: [refresh_row(i) for i in SERVICE_CATALOG], bg="#234f9c", width=110, height=34).pack(side=tk.LEFT, padx=(0, 8))
    uihelpers.rounded_button(bottom, "CHECK VERSIONS", command=refresh_versions, bg="#5b357a", width=150, height=34).pack(side=tk.LEFT, padx=(0, 8))
