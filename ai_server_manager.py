import subprocess
import threading
import tkinter as tk
from tkinter import scrolledtext
import time
import webbrowser
import ctypes
import sys
import os

from components import settings as settings_window
from components import services as services_window
from components import components as service_components
from components import errorhandler
from components import uihelpers
import re
import traceback
import shlex
from pathlib import Path
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

# =====================================================
# CONFIG
# =====================================================

AI_DIR = service_components.AI_DIR
SILLY_DIR = service_components.SILLY_DIR
XTTS_IMAGE = "daswer123/xtts-api-server:latest"

# Stops stale AI services when the manager opens.
CLEAN_ON_MANAGER_START = True

# Disables Ollama systemd autostart when stopping.
DISABLE_OLLAMA_AUTOSTART = True

CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

# Default enabled service list. The Services window can change this at runtime.
DEFAULT_ENABLED_SERVICES = {
    "ollama": True,
    "xtts": True,
    "silly": True,
}


# =====================================================
# HELPERS
# =====================================================

def wsl_cmd(command):
    return ["wsl", "bash", "-lc", command]


def wsl_script_cmd(script_path):
    """Run an already-written shell script in WSL.

    V26 uses script files for long service start commands instead of pushing huge
    multiline strings through `wsl bash -lc`. This gives much better debug output
    and avoids quoting/escaping issues when folders move between drives.
    """
    return ["wsl", "bash", "-lc", f"bash {shlex.quote(str(script_path))}"]


def wsl_available(timeout=6):
    """Return (ok, message) for the Windows-to-WSL handoff.

    ERROR[95] is reserved for WSL being unavailable, crashed, timed out, or not
    responding. This is separate from service-level errors like Docker/sudo.
    """
    try:
        result = subprocess.run(
            ["wsl", "bash", "-lc", "echo WSL_OK"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=CREATE_NO_WINDOW,
            timeout=timeout,
        )
        output = (result.stdout or "").strip()
        if result.returncode == 0 and "WSL_OK" in output:
            return True, output
        return False, output or f"wsl exited with code {result.returncode}"
    except subprocess.TimeoutExpired:
        return False, f"WSL did not respond within {timeout} seconds"
    except FileNotFoundError as e:
        return False, f"wsl.exe not found: {e}"
    except Exception as e:
        return False, str(e)


def run_cmd(command, timeout=None, capture=False):
    try:
        if capture:
            return subprocess.check_output(
                wsl_cmd(command),
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
                timeout=timeout,
            )

        return subprocess.run(
            wsl_cmd(command),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            timeout=timeout,
        )

    except subprocess.TimeoutExpired:
        return f"[SYSTEM] Command timed out after {timeout} seconds." if capture else None
    except subprocess.CalledProcessError as e:
        if capture:
            out = getattr(e, "output", "") or ""
            return out if out.strip() else f"[SYSTEM] Command failed with exit code {getattr(e, 'returncode', 'unknown')}."
        return None
    except Exception as e:
        return str(e) if capture else None


def service_ok(command):
    try:
        result = subprocess.run(
            wsl_cmd(command),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=CREATE_NO_WINDOW,
            timeout=3,
        )
        return result.returncode == 0
    except Exception:
        return False


def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def hex_color(r, g, b):
    return f"#{int(r):02x}{int(g):02x}{int(b):02x}"


def gradient_green_red(value, maximum):
    pct = clamp(value / maximum if maximum else 0, 0, 1)
    r = 60 + (255 - 60) * pct
    g = 255 - (255 - 60) * pct
    b = 90 - 50 * pct
    return hex_color(r, g, b)


def gradient_blue_red(value, maximum=80):
    pct = clamp(value / maximum if maximum else 0, 0, 1)
    r = 80 + (255 - 80) * pct
    g = 180 - 120 * pct
    b = 255 - 220 * pct
    return hex_color(r, g, b)


# =====================================================
# SUDO SETUP
# =====================================================


def has_sudo_access():
    """Return True when sudoers allows the real manager commands non-interactively.

    Do not use `systemctl status ollama` as the test. systemctl status can
    return non-zero when Ollama is simply stopped, which made the manager think
    sudo was broken even when sudoers was fine.
    """
    tests = [
        "sudo -n systemctl --version >/dev/null 2>&1",
        "sudo -n pkill --version >/dev/null 2>&1",
    ]
    return all(service_ok(t) for t in tests)


def sudo_can(command):
    """Check one exact sudo command without asking for a password."""
    return service_ok(f"sudo -n {command} >/dev/null 2>&1")

def setup_sudo_permissions():
    # Legacy entry point kept for compatibility. The active installer now lives
    # inside the Settings panel and calls AIManager.install_sudo_permissions_from_settings().
    subprocess.Popen(["wsl", "bash", "-lc", "echo Use Settings inside AI Server Manager to setup sudo access; read -p 'Press Enter to close...'"])


# =====================================================
# COMMANDS
# =====================================================

SUDO_ERROR_TEXT = "SUDO ACCESS NOT GIVEN! Go to settings to fix."

OLLAMA_RUN = """
echo "[OLLAMA] Starting Ollama..."
sudo -n systemctl enable ollama >/dev/null 2>&1 || true
sudo -n systemctl start ollama || true
echo "[OLLAMA] Ollama start command sent."
journalctl -u ollama -n 40 -f --no-pager
"""

XTTS_RUN = f"""
echo "[XTTS] Starting XTTS2 using existing docker-compose.yml..."
echo "[XTTS] Ollama and SillyTavern are not touched by this XTTS process."
cd {AI_DIR}/TTS/xtts || {{ echo "[XTTS] ERROR: XTTS folder missing: {AI_DIR}/TTS/xtts"; exit 20; }}

if ! command -v docker >/dev/null 2>&1; then
  echo "[XTTS] ERROR: docker command not found in WSL."
  echo "[XTTS] Docker worked manually, so check WSL PATH / Docker Desktop WSL integration."
  exit 81
fi

if ! docker info >/dev/null 2>&1; then
  echo "[XTTS] ERROR: Docker is not reachable from WSL."
  echo "[XTTS] Try manually: docker info"
  exit 81
fi

if [ ! -f docker-compose.yml ] && [ ! -f compose.yml ]; then
  echo "[XTTS] ERROR: No docker-compose.yml found in {AI_DIR}/TTS/xtts."
  exit 82
fi

echo "[XTTS] Using compose file in: $(pwd)"
echo "[XTTS] Starting compose service. This is the same method that worked manually."
docker compose up --remove-orphans
"""

WARMUP_XTTS = """
echo "[WARMUP] Waiting for XTTS model..."

ready=0
for i in {1..120}; do
  if curl -fsS http://127.0.0.1:8020/speakers >/dev/null 2>&1; then
    echo "[WARMUP] XTTS API reachable."
    ready=1
    sleep 2
    break
  fi
  sleep 1
done

if [ "$ready" != "1" ]; then
  echo "[WARMUP] ERROR: XTTS did not become reachable on http://127.0.0.1:8020."
  exit 83
fi

echo "[WARMUP] Pre-loading XTTS voice/model..."
if ! curl -s -X POST "http://127.0.0.1:8020/tts_to_audio/" \
  -H "Content-Type: application/json" \
  -d '{"text":"Ready.","speaker_wav":"Female_v3","language":"en"}' \
  --output {service_components.XTTS_DIR}/output/warmup.wav >/dev/null 2>&1; then
  echo "[WARMUP] WARNING: XTTS API reachable, but warmup request failed."
else
  echo "[WARMUP] XTTS warmup complete."
fi
"""

SILLY_RUN = f"""
echo "[SILLYTAVERN] Starting SillyTavern..."
echo "[SILLYTAVERN] Please be patient. SillyTavern can take a while to compile frontend files and open the browser."
echo "[SILLYTAVERN] If the window looks quiet for a moment, it is probably still starting. Wait until you see: SillyTavern is listening."
cd {SILLY_DIR} || {{ echo "[SILLYTAVERN] ERROR: folder not found: {SILLY_DIR}"; exit 20; }}
npm run start
"""


# =====================================================
# MANAGER
# =====================================================

class AIManager:
    def __init__(self, root):
        self.root = root
        self.root.title("AI Server Manager V71")
        self.fixed_width = 1460
        self.fixed_height = 970
        self._enforcing_fixed_size = False
        self.root.geometry(f"{self.fixed_width}x{self.fixed_height}")
        self.colors = settings_window.get_theme_colors()
        self.root.configure(bg=self.colors.get("root_bg", "#101010"))

        self.running = False
        self.stopping = False
        self.processes = {}

        self.service_enabled = settings_window.get_service_enabled()
        self.service_priorities = settings_window.get_service_priorities()
        self.gpu_settings = settings_window.get_gpu_settings()
        self.service_processors = settings_window.get_service_processors()

        # V20 performance caches. Avoid running many WSL/Docker/curl checks on the Tk UI path.
        self.installed_services = {key: bool(handler.get("default_enabled", True)) for key, handler in service_components.SERVICE_HANDLERS.items()}
        self._installed_last_check = 0
        self._installed_refreshing = False
        self._installed_lock = threading.Lock()
        self._service_states_cache = {key: False for key in service_components.SERVICE_HANDLERS}
        self._service_states_last_check = 0
        self._service_states_lock = threading.Lock()
        # V28: live-state debounce. Some services report READY before the
        # slower global monitor sees both API + process/container checks. Keep
        # a short trusted-ready grace period and require repeated failures
        # before changing the AI SERVICES panel back to STOPPED.
        self._service_state_grace_until = {key: 0 for key in service_components.SERVICE_HANDLERS}
        self._service_down_counts = {key: 0 for key in service_components.SERVICE_HANDLERS}
        self.gpu_rows_cache = []
        self.cpu_status_cache = {"name": "CPU", "util": None, "temp": None, "temp_source": None}
        self._last_cpu_probe = 0
        self.startup_ready = False

        # V18: service list is dynamic. Add new services in components/components.py
        # and components/services.py instead of editing this manager file.
        self.healthy_since = {key: None for key in service_components.SERVICE_HANDLERS}

        self.last_service_snapshot = ""
        self.last_gpu_snapshot = ""
        self.last_cpu_snapshot = ""
        self.overlay = None
        self.overlay_title = None
        self._global_refresh_after_id = None

        self.enable_dark_title_bar()
        self.make_ui()
        self.apply_theme()
        self.root.bind("<Configure>", self.enforce_fixed_normal_size)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # V21: block the UI with a real loading screen while expensive WSL/Docker/GPU
        # checks warm their caches. This keeps Settings/Services fast once visible.
        self.show_loading_screen()
        threading.Thread(target=self.preload_startup_data, daemon=True).start()

    # =====================================================
    # STARTUP LOADING SCREEN
    # =====================================================

    def show_loading_screen(self):
        c = self.colors
        self.loading_overlay = tk.Frame(self.root, bg="#050505")
        self.loading_overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.loading_overlay.lift()

        box = tk.Frame(self.loading_overlay, bg="#050505")
        box.place(relx=0.5, rely=0.5, anchor="center", width=720, height=220)

        tk.Label(
            box, text="AI Server Manager", bg="#050505", fg="#ffffff",
            font=("Segoe UI", 26, "bold")
        ).pack(pady=(8, 6))

        self.loading_text = tk.Label(
            box, text="Loading...", bg="#050505", fg="#cccccc",
            font=("Segoe UI", 11, "bold")
        )
        self.loading_text.pack(pady=(0, 18))

        bar_outer = tk.Canvas(box, bg="#050505", height=24, highlightthickness=0, bd=0)
        bar_outer.pack(fill=tk.X, padx=70)
        self.loading_bar_outer = bar_outer
        self.loading_bar_percent = 0
        bar_outer.bind("<Configure>", lambda _e: self._draw_loading_bar(getattr(self, "loading_bar_percent", 0)))

        self.loading_percent = tk.Label(
            box, text="0%", bg="#050505", fg="#ffd36a",
            font=("Consolas", 12, "bold")
        )
        self.loading_percent.pack(pady=(10, 0))

        self.root.update_idletasks()

    def _draw_loading_bar(self, pct):
        try:
            c = self.loading_bar_outer
            c.delete("all")
            w = max(10, c.winfo_width())
            h = max(10, c.winfo_height())
            r = 8
            def rr(x1, y1, x2, y2, fill):
                c.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline=fill)
                c.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline=fill)
                c.create_oval(x1, y1, x1 + 2*r, y1 + 2*r, fill=fill, outline=fill)
                c.create_oval(x2 - 2*r, y1, x2, y1 + 2*r, fill=fill, outline=fill)
                c.create_oval(x1, y2 - 2*r, x1 + 2*r, y2, fill=fill, outline=fill)
                c.create_oval(x2 - 2*r, y2 - 2*r, x2, y2, fill=fill, outline=fill)
            rr(0, 0, w, h, "#242936")
            fill_w = max(0, int(w * max(0, min(100, pct)) / 100))
            if fill_w > 2:
                rr(0, 0, max(2*r, fill_w), h, "#2f6f4e")
        except Exception:
            pass

    def update_loading(self, percent, message):
        def apply():
            try:
                pct = max(0, min(100, int(percent)))
                self.loading_text.config(text=message)
                self.loading_percent.config(text=f"{pct}%")
                self.loading_bar_percent = pct
                self._draw_loading_bar(pct)
                self.loading_overlay.lift()
            except Exception:
                pass
        self.safe_ui(apply)

    def preload_startup_data(self):
        """Warm caches before the user reaches the main window."""
        steps = [
            (8, "Loading settings...", self._preload_settings),
            (18, "Checking installed services...", lambda: self.refresh_installed_services(log=False)),
            (34, "Checking service versions...", self._preload_service_versions),
            (48, "Preparing AI service monitor...", self._preload_service_states),
            (64, "Reading GPU monitor...", self._preload_gpu_info),
            (84, "Reading CPU monitor...", self._preload_cpu_info),
            (96, "Preparing interface...", lambda: time.sleep(0.10)),
            (100, "Ready.", lambda: time.sleep(0.10)),
        ]
        for pct, message, fn in steps:
            self.update_loading(pct, message)
            try:
                fn()
            except Exception:
                pass
        self.safe_ui(self.finish_startup_load)

    def _preload_settings(self):
        self.service_enabled = settings_window.get_service_enabled()
        self.service_priorities = settings_window.get_service_priorities()
        self.gpu_settings = settings_window.get_gpu_settings()
        self.service_processors = settings_window.get_service_processors()
        self.colors = settings_window.get_theme_colors()


    def _preload_service_versions(self):
        """Check installer version labels during startup and store them for Add Service.

        This replaces the old manual CHECK VERSIONS button in the installer UI.
        It is intentionally best-effort and quick; Docker/image checks are skipped
        when Docker is missing so the loading screen does not hang.
        """
        try:
            from components import installer as installer_window
            versions = {}
            for item in getattr(installer_window, "SERVICE_CATALOG", []):
                key = item.get("key")
                default = item.get("version_label", "latest")
                cmd = item.get("version_command")
                if not key:
                    continue
                versions[key] = default
                # Avoid slow Docker manifest checks when Docker is missing.
                if cmd and "docker" not in cmd:
                    try:
                        out = self.run_capture(cmd, timeout=6)
                        first = str(out).strip().splitlines()[0] if str(out).strip() else default
                        versions[key] = first
                    except Exception:
                        versions[key] = default
            settings_window.set_service_versions(versions)
        except Exception as e:
            try:
                self.write(f"[SYSTEM] Version preload warning: {e}", "warn")
            except Exception:
                pass

    def _preload_service_states(self):
        # Force one state refresh now so later UI draws use the cache.
        with self._service_states_lock:
            self._service_states_last_check = 0
        self.get_service_states()

    def _preload_gpu_info(self):
        try:
            result = subprocess.check_output(
                [
                    "nvidia-smi",
                    "--query-gpu=index,name,memory.used,memory.total,utilization.gpu,temperature.gpu",
                    "--format=csv,noheader,nounits",
                ],
                text=True, encoding="utf-8", errors="replace",
                creationflags=CREATE_NO_WINDOW, timeout=5,
            )
            rows = []
            for row in result.strip().splitlines():
                idx, name, used, total, util, temp = [x.strip() for x in row.split(",")]
                rows.append((idx, name, int(used), int(total), int(util), int(temp)))
            self.gpu_rows_cache = rows
        except Exception:
            self.gpu_rows_cache = []

    def _preload_cpu_info(self):
        try:
            self.cpu_status_cache = self.get_cpu_status()
            self._last_cpu_probe = time.time()
        except Exception:
            self.cpu_status_cache = {"name": "CPU", "util": None, "temp": None, "temp_source": None}

    def finish_startup_load(self):
        self.startup_ready = True
        try:
            self.colors = settings_window.get_theme_colors()
            self.apply_theme()
            # V28: do not reveal the main window until the visible monitor panes
            # have been drawn from their warmed caches at least once.
            mapping = services_window.get_service_config()
            states = self.get_service_states()
            active = {key: self.service_process_active(key) for _, key, _, _ in mapping}
            self.render_services(mapping, states, active)
            self.render_gpu(self.gpu_rows_cache or [])
            self.render_cpu(self.cpu_status_cache)
        except Exception:
            pass
        try:
            self.loading_overlay.destroy()
        except Exception:
            pass

        threading.Thread(target=self.gpu_monitor_loop, daemon=True).start()
        threading.Thread(target=self.cpu_monitor_loop, daemon=True).start()
        threading.Thread(target=self.service_loop, daemon=True).start()

        if CLEAN_ON_MANAGER_START:
            threading.Thread(target=self.initial_cleanup, daemon=True).start()
        else:
            self.set_status("Status: stopped", self.colors.get("label_fg", "#dddddd"))

    # =====================================================
    # UI
    # =====================================================

    def enforce_fixed_normal_size(self, event=None):
        """Keep the normal window size fixed, but still allow true maximize."""
        if event is not None and event.widget is not self.root:
            return
        if self._enforcing_fixed_size:
            return
        try:
            if self.root.state() == "zoomed":
                return
        except Exception:
            pass

        width = self.root.winfo_width()
        height = self.root.winfo_height()
        if width != self.fixed_width or height != self.fixed_height:
            self._enforcing_fixed_size = True
            self.root.after_idle(self._restore_fixed_normal_size)

    def _restore_fixed_normal_size(self):
        try:
            if self.root.state() != "zoomed":
                self.root.geometry(f"{self.fixed_width}x{self.fixed_height}")
        finally:
            self._enforcing_fixed_size = False

    def enable_dark_title_bar(self):
        if sys.platform != "win32":
            return
        try:
            self.root.update_idletasks()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            value = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 19, ctypes.byref(value), ctypes.sizeof(value))
        except Exception:
            pass

    def apply_theme(self):
        """Apply light/dark theme to existing windows and panels."""
        try:
            self.colors = settings_window.get_theme_colors()
        except Exception:
            self.colors = getattr(self, "colors", {}) or {}
        c = self.colors
        root_bg = c.get("root_bg", "#101010")
        panel_bg = c.get("panel_bg", "#181818")
        header_bg = c.get("header_bg", "#151515")
        text_bg = c.get("text_bg", "#050505")
        fg = c.get("fg", "white")
        label_fg = c.get("label_fg", "#dddddd")
        muted_fg = c.get("muted_fg", "#cccccc")

        def recolor(widget):
            try:
                cls = widget.winfo_class()
                current_bg = None
                try:
                    current_bg = widget.cget("bg")
                except Exception:
                    pass
                if isinstance(widget, uihelpers.RoundedButton):
                    # Keep the button fill colour intact. Only recolour the Canvas background
                    # behind the rounded button so light/dark mode does not make buttons invisible.
                    try:
                        parent_bg = widget.master.cget("bg")
                    except Exception:
                        parent_bg = root_bg
                    try:
                        tk.Canvas.configure(widget, bg=parent_bg)
                    except Exception:
                        pass
                    widget._draw(widget.normal_bg if widget.enabled else widget.disabled_bg)
                elif isinstance(widget, (tk.Frame, tk.Canvas)):
                    if current_bg in ("#050505", "#101010", "#181818", "#151515", "#303030", "SystemButtonFace", "white", "#ffffff", "#f3f3f3", "#e9e9e9"):
                        widget.configure(bg=root_bg if current_bg in ("#101010", "SystemButtonFace", "white", "#ffffff", "#f3f3f3") else panel_bg)
                elif isinstance(widget, tk.Label):
                    bg = widget.cget("bg")
                    if bg in ("#050505", "#101010", "#181818", "#151515", "SystemButtonFace"):
                        widget.configure(bg=root_bg if bg == "#101010" else panel_bg, fg=fg if widget.cget("fg") in ("white", "#ffffff") else muted_fg)
                elif isinstance(widget, (tk.Text, scrolledtext.ScrolledText)):
                    widget.configure(bg=panel_bg if widget is not self.log else text_bg, fg=label_fg, insertbackground=fg)
                elif isinstance(widget, tk.Entry):
                    widget.configure(bg=text_bg, fg=fg, insertbackground=fg)
                elif isinstance(widget, tk.Checkbutton):
                    widget.configure(bg=panel_bg, fg=fg, selectcolor=text_bg, activebackground=panel_bg, activeforeground=fg)
                elif isinstance(widget, tk.Radiobutton):
                    widget.configure(bg=panel_bg, fg=fg, selectcolor=text_bg, activebackground=panel_bg, activeforeground=fg)
            except Exception:
                pass
            try:
                for child in widget.winfo_children():
                    recolor(child)
            except Exception:
                pass

        try:
            self.root.configure(bg=root_bg)
            recolor(self.root)
            self.status.configure(bg=root_bg)
            self.configure_log_tags()
            self.last_service_snapshot = ""
        except Exception:
            pass

    def make_ui(self):
        c = self.colors
        top = tk.Frame(self.root, bg=c.get("root_bg", "#101010"))
        top.pack(fill=tk.X, padx=12, pady=10)

        uihelpers.rounded_button(top, "START ALL", command=self.start_all_threaded, bg=c.get("button_good", "#256d3c"), width=170, height=38).pack(side=tk.LEFT, padx=5)
        uihelpers.rounded_button(top, "STOP ALL", command=self.stop_all_threaded, bg=c.get("button_bad", "#7a2e2e"), width=170, height=38).pack(side=tk.LEFT, padx=5)
        uihelpers.rounded_button(top, "SETTINGS", command=self.open_settings_panel, bg=c.get("button_primary", "#334155"), width=190, height=38).pack(side=tk.LEFT, padx=5)
        uihelpers.rounded_button(top, "SERVICES", command=self.open_services_panel, bg=c.get("button_secondary", "#3f3f46"), width=170, height=38).pack(side=tk.LEFT, padx=5)

        self.status = tk.Label(
            self.root,
            text="Status: starting manager...",
            anchor="w",
            bg=c.get("root_bg", "#101010"),
            fg=c.get("warn", "#ffaa00"),
            font=("Segoe UI", 11, "bold"),
        )
        self.status.pack(fill=tk.X, padx=14)

        services_frame = tk.Frame(self.root, bg=c.get("panel_bg", "#181818"))
        services_frame.pack(fill=tk.X, padx=14, pady=(8, 4))
        self.services = tk.Text(
            services_frame,
            height=7,
            bg=c.get("panel_bg", "#181818"),
            fg=c.get("label_fg", "#dddddd"),
            font=("Consolas", 10),
            relief=tk.FLAT,
            padx=10,
            pady=8,
            state="disabled",
            wrap=tk.NONE,
        )
        services_scroll = tk.Scrollbar(services_frame, orient="vertical", command=self.services.yview, bg="#2a2a2a", troughcolor=c.get("root_bg", "#101010"))
        self.services.configure(yscrollcommand=services_scroll.set)
        self.services.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # V34: keep mouse-wheel scrolling but hide the visual scrollbar.
        # services_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        gpu_cpu_frame = tk.Frame(self.root, bg=c.get("root_bg", "#101010"))
        gpu_cpu_frame.pack(fill=tk.X, padx=14, pady=(4, 8))

        self.gpu_text = tk.Text(
            gpu_cpu_frame,
            height=6,
            bg=c.get("panel_bg", "#181818"),
            fg=c.get("label_fg", "#dddddd"),
            font=("Consolas", 10),
            relief=tk.FLAT,
            padx=10,
            pady=8,
            state="disabled",
        )
        self.gpu_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 2))

        self.cpu_text = tk.Text(
            gpu_cpu_frame,
            height=6,
            bg=c.get("panel_bg", "#181818"),
            fg=c.get("label_fg", "#dddddd"),
            font=("Consolas", 10),
            relief=tk.FLAT,
            padx=10,
            pady=8,
            state="disabled",
        )
        self.cpu_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(2, 0))

        self.log = scrolledtext.ScrolledText(
            self.root,
            wrap=tk.WORD,
            font=("Consolas", 10),
            bg=c.get("text_bg", "#050505"),
            fg=c.get("label_fg", "#d8d8d8"),
            insertbackground="white",
            relief=tk.FLAT,
        )
        self.log.pack(fill=tk.BOTH, expand=True, padx=14, pady=10)
        try:
            self.log.vbar.pack_forget()
        except Exception:
            pass
        try:
            self.log.vbar.config(
                bg="#2a2a2a",
                troughcolor="#101010",
                activebackground="#444444",
                highlightthickness=0,
                bd=0,
                relief=tk.FLAT,
            )
        except Exception:
            pass
        self.configure_log_tags()

    def configure_log_tags(self):
        c = getattr(self, "colors", settings_window.get_theme_colors())
        self.log.tag_config("info", foreground=c.get("label_fg", "#d8d8d8"))
        self.log.tag_config("good", foreground=c.get("good", "#00ff99"))
        self.log.tag_config("warn", foreground=c.get("warn", "#ffaa00"))
        self.log.tag_config("error", foreground=c.get("error", "#ff4444"))
        self.log.tag_config("system", foreground="#2f6fed" if settings_window.get_theme_name()=="light" else "#b7d7ff")
        self.log.tag_config("endpoint", foreground=c.get("link", "#ffd36a"))
        self.log.tag_config("link", foreground=c.get("link", "#ffd36a"), underline=True)
        self.log.tag_bind("link", "<Enter>", lambda _e: self.log.config(cursor="hand2"))
        self.log.tag_bind("link", "<Leave>", lambda _e: self.log.config(cursor=""))
        self.log.tag_config("banner_dark", foreground="#1f7a3a")
        self.log.tag_config("banner_light", foreground="#7CFF9B")

    def safe_ui(self, fn):
        self.root.after(0, fn)

    def write(self, text, style=None):
        text = errorhandler.clean_ansi(str(text))
        text = errorhandler.summarize(text)
        if not text:
            return
        style = style or errorhandler.classify(text)

        def do_write():
            if style == "banner":
                # Draw system dividers with a simple two-tone green effect.
                stripped = text.strip()
                label = stripped.strip("=").strip()
                self.log.insert(tk.END, "\n", "info")
                self.log.insert(tk.END, "========== ", "banner_dark")
                self.log.insert(tk.END, label, "banner_light")
                self.log.insert(tk.END, " ==========\n", "banner_dark")
            else:
                self.insert_log_text(text + "\n", style)
            self.log.see(tk.END)

        self.safe_ui(do_write)

    def insert_log_text(self, text, style="info"):
        """Insert log text while making visible URLs clickable."""
        url_re = re.compile(r"(https?://[^\s]+|(?:localhost|127\.0\.0\.1):\d+(?:/[^\s]*)?)")
        pos = 0
        for match in url_re.finditer(text):
            if match.start() > pos:
                self.log.insert(tk.END, text[pos:match.start()], style)
            url = match.group(0).rstrip(".,)")
            tag = f"link_{abs(hash(url))}"
            self.log.tag_config(tag, foreground=self.colors.get("link", "#ffd36a"), underline=True)
            self.log.tag_bind(tag, "<Button-1>", lambda _e, u=url: uihelpers.open_url(u))
            self.log.tag_bind(tag, "<Enter>", lambda _e: self.log.config(cursor="hand2"))
            self.log.tag_bind(tag, "<Leave>", lambda _e: self.log.config(cursor=""))
            self.log.insert(tk.END, url, (style, tag))
            pos = match.start() + len(url)
        if pos < len(text):
            self.log.insert(tk.END, text[pos:], style)

    def set_status(self, text, color):
        self.safe_ui(lambda: self.status.config(text=text, fg=color))

    # =====================================================
    # SERVICE COMPONENT HELPERS
    # =====================================================

    def run_shell(self, command, timeout=None):
        return run_cmd(command, timeout=timeout, capture=False)

    def run_capture(self, command, timeout=None):
        return run_cmd(command, timeout=timeout, capture=True)

    def run_stream(self, command, on_line=None, timeout=None):
        """Run a WSL command and stream combined stdout/stderr line-by-line.

        Installer windows use this so progress labels update while long downloads
        and Docker pulls are actually running, instead of only after the command
        completes. The full text is still returned for marker verification.
        """
        lines = []
        proc = None
        try:
            proc = subprocess.Popen(
                wsl_cmd(command),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
                bufsize=1,
            )
            start = time.time()
            while True:
                raw = proc.stdout.readline() if proc.stdout is not None else ""
                if raw:
                    line = raw.rstrip("\r\n")
                    lines.append(line)
                    if on_line is not None:
                        try:
                            on_line(line)
                        except Exception as cb_err:
                            lines.append(f"[SYSTEM] stream callback warning: {cb_err}")
                    continue
                if proc.poll() is not None:
                    break
                if timeout and (time.time() - start) > timeout:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    msg = f"[SYSTEM] Command timed out after {timeout} seconds."
                    lines.append(msg)
                    if on_line is not None:
                        try:
                            on_line(msg)
                        except Exception:
                            pass
                    return 124, "\n".join(lines)
                time.sleep(0.05)
            try:
                if proc.stdout is not None:
                    for raw in proc.stdout.readlines():
                        line = raw.rstrip("\r\n")
                        if line:
                            lines.append(line)
                            if on_line is not None:
                                try:
                                    on_line(line)
                                except Exception:
                                    pass
            except Exception:
                pass
            return int(proc.returncode or 0), "\n".join(lines)
        except Exception as e:
            msg = str(e)
            if on_line is not None:
                try:
                    on_line(msg)
                except Exception:
                    pass
            return 1, msg

    def service_ok(self, command):
        return service_ok(command)

    # =====================================================
    # INTERNAL PANELS
    # =====================================================

    def close_overlay(self):
        if self.overlay is not None:
            self.overlay.destroy()
            self.overlay = None
            self.overlay_title = None
        self.overlay_title = None
        self._global_refresh_after_id = None

    def open_overlay(self, title):
        self.close_overlay()
        self.overlay_title = title

        c = self.colors
        self.overlay = tk.Frame(self.root, bg=c.get("root_bg", "#101010"), highlightbackground=c.get("border", "#303030"), highlightthickness=1)
        # Full-screen in-place overlay. It fully covers the manager and cannot be moved separately.
        self.overlay.place(relx=0, rely=0, relwidth=1, relheight=1)
        self.overlay.lift()

        header = tk.Frame(self.overlay, bg=c.get("header_bg", "#151515"))
        header.pack(fill=tk.X)

        tk.Label(
            header,
            text=title,
            anchor="w",
            bg=c.get("header_bg", "#151515"),
            fg=c.get("fg", "white"),
            font=("Segoe UI", 13, "bold"),
            padx=12,
            pady=10,
        ).pack(side=tk.LEFT, fill=tk.X, expand=True)

        uihelpers.rounded_button(header, "CLOSE", command=self.close_overlay, bg="#9b1c1c", width=100, height=34).pack(side=tk.RIGHT, padx=10, pady=8)

        body = tk.Frame(self.overlay, bg=c.get("root_bg", "#101010"))
        body.pack(fill=tk.BOTH, expand=True, padx=12, pady=12)
        return body

    def open_settings_panel(self):
        body = self.open_overlay("Settings")
        try:
            self.root.bind("<Escape>", lambda _e: (self.close_overlay(), self.schedule_global_refresh(2000, log=False)))
        except Exception:
            pass
        settings_window.build_settings(body, self)

    def open_services_panel(self):
        body = self.open_overlay("Services")
        try:
            self.root.bind("<Escape>", lambda _e: (self.close_overlay(), self.schedule_global_refresh(2000, log=False)))
        except Exception:
            pass
        services_window.build_services(body, self)

    def schedule_global_refresh(self, delay_ms=2000, log=False):
        """Debounced universal UI refresh after install/uninstall or service changes.

        It refreshes installed-service state once on a worker thread, redraws the
        main AI SERVICES panel, and rebuilds the currently open overlay only if
        it is one of the service/settings panels. This avoids refresh buttons
        while also avoiding the old heavy constant polling problem.
        """
        try:
            if self._global_refresh_after_id is not None:
                try:
                    self.root.after_cancel(self._global_refresh_after_id)
                except Exception:
                    pass
                self._global_refresh_after_id = None

            def kick():
                self._global_refresh_after_id = None

                def worker():
                    try:
                        self.refresh_installed_services(log=log)
                    except Exception as e:
                        if log:
                            self.write(f"[SYSTEM] Global refresh installed check failed: {e}", "warn")
                    try:
                        self.force_service_state_refresh()
                    except Exception:
                        pass

                    def rebuild_open_overlay():
                        title = getattr(self, "overlay_title", None)
                        if title == "Services":
                            self.open_services_panel()
                        elif title == "Settings":
                            self.open_settings_panel()

                    try:
                        self.safe_ui(rebuild_open_overlay)
                    except Exception:
                        pass

                threading.Thread(target=worker, daemon=True).start()

            self._global_refresh_after_id = self.root.after(int(delay_ms), kick)
        except Exception as e:
            if log:
                self.write(f"[SYSTEM] Could not schedule global refresh: {e}", "warn")

    def set_service_enabled(self, key, enabled):
        self.service_enabled[key] = bool(enabled)
        self.healthy_since.setdefault(key, None)
        settings_window.set_service_enabled(key, enabled)
        self.write(f"[SERVICES] {key} {'enabled' if enabled else 'disabled'}.")
        self.last_service_snapshot = ""


    def warn_sudo_missing(self, action="use sudo"):
        self.write(f"[SYSTEM] {SUDO_ERROR_TEXT}")
        self.write(f"[SYSTEM] Action blocked while trying to {action}.")

    def has_docker_access(self):
        return service_ok("command -v docker >/dev/null 2>&1 && (docker info >/dev/null 2>&1 || sudo -n docker info >/dev/null 2>&1 || sudo -n docker info >/dev/null 2>&1)")

    def docker_shell(self, args):
        return (
            "if docker info >/dev/null 2>&1; then "
            f"docker {args}; "
            "elif sudo -n docker info >/dev/null 2>&1; then "
            f"sudo -n docker {args}; "
            "else exit 81; fi"
        )

    def docker_ok(self, args):
        return service_ok(self.docker_shell(args))

    def run_docker(self, args, timeout=8):
        return run_cmd(self.docker_shell(args), timeout=timeout)

    def install_sudo_permissions_from_settings(self, sudo_password, on_status=None):
        """Delegate sudoers setup to components/sudo.py.

        This keeps sudo setup isolated so it can be patched without changing the
        main manager logic every time.
        """
        try:
            from components import sudo as sudo_helper
            return sudo_helper.install_sudo_permissions(self, sudo_password, on_status)
        except Exception as e:
            self.write(f"[SETTINGS] Sudo helper error: {e}", "error")
            if on_status is not None:
                self.safe_ui(lambda: on_status(f"Sudo helper error: {e}", "#ff4444"))

    # =====================================================
    # LOG FILTERING
    # =====================================================

    def useful_log_line(self, name, line):
        return errorhandler.should_show(name, line)

    # =====================================================
    # PROCESS START
    # =====================================================

    def _write_service_script(self, name, command):
        """Write a service start script beside the manager and return its WSL path."""
        try:
            root = Path(getattr(service_components, "LOCAL_AI_DIR", Path(__file__).resolve().parent))
            runtime = root / "cache" / "manager_runtime"
            runtime.mkdir(parents=True, exist_ok=True)
            safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(name).lower())
            script = runtime / f"start_{safe_name}.sh"
            body = f"""#!/usr/bin/env bash
set +e
export PYTHONUNBUFFERED=1
cd {shlex.quote(str(getattr(service_components, 'AI_DIR', '')))} 2>/dev/null || true
echo "[{name}] DEBUG: start script file running."
echo "[{name}] DEBUG: whoami=$(whoami 2>/dev/null || echo unknown), pwd=$(pwd 2>/dev/null || echo unknown)"
{command}
rc=$?
echo "[{name}] EXIT_CODE:$rc"
exit $rc
"""
            # Force Linux line endings. Windows Python can otherwise leave CRLF in
            # multiline generated shell scripts, which causes Bash errors like:
            #   $'\r': command not found
            #   syntax error near unexpected token `$'do\r''
            body = body.replace("\r\n", "\n").replace("\r", "\n")
            with open(script, "w", encoding="utf-8", newline="\n") as f:
                f.write(body)
            try:
                os.chmod(script, 0o755)
            except Exception:
                pass
            to_wsl = getattr(service_components, "_to_wsl_path", None)
            if callable(to_wsl):
                return to_wsl(script)
            return str(script).replace('\\', '/')
        except Exception as e:
            self.write(f"[{name}] ERROR[91]: could not write service script: {e}", "error")
            return None

    def run_logged(self, name, command):
        if name in self.processes and self.processes[name].poll() is None:
            self.write(f"[{name}] Already has a manager process. Skipping duplicate start.")
            return self.processes[name]

        self.write(f"\n========== STARTING {name} ==========")

        ok, msg = wsl_available(timeout=6)
        if not ok:
            self.write(f"[{name}] ERROR[95]: WSL is not responding or has crashed: {msg}", "error")
            self.write(f"[{name}] ERROR[95]: Try: wsl --shutdown, then reopen Ubuntu/WSL and start the manager again.", "error")
            return None

        script_wsl_path = self._write_service_script(name, command)
        if not script_wsl_path:
            return None
        self.write(f"[{name}] DEBUG: start script: {script_wsl_path}", "system")

        try:
            proc = subprocess.Popen(
                wsl_script_cmd(script_wsl_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=CREATE_NO_WINDOW,
            )
        except FileNotFoundError as e:
            self.write(f"[{name}] ERROR[87]: executable not found while launching WSL: {e}", "error")
            return None
        except PermissionError as e:
            self.write(f"[{name}] ERROR[85]: permission denied while launching WSL: {e}", "error")
            return None
        except Exception as e:
            self.write(f"[{name}] ERROR[90]: could not launch command: {e}", "error")
            return None

        self.processes[name] = proc
        self.write(f"[{name}] DEBUG: Windows process PID={proc.pid}", "system")

        def reader():
            try:
                saw_output = False
                for line in proc.stdout:
                    saw_output = True
                    clean = line.rstrip()
                    lowered = clean.lower()
                    if "sudo: a password is required" in lowered or "sudo access not given" in lowered:
                        self.write(f"[{name}] {SUDO_ERROR_TEXT}", "error")
                        continue
                    if "permission denied" in lowered:
                        self.write(f"[{name}] ERROR[85]: {clean}", "error")
                        continue
                    if "$'\\r': command not found" in lowered or "unexpected token `$'do\\r''" in lowered:
                        self.write(f"[{name}] ERROR[96]: generated shell script had Windows CRLF line endings: {clean}", "error")
                        continue
                    if "command not found" in lowered or "not found" in lowered and "folder" not in lowered:
                        self.write(f"[{name}] ERROR[87]: {clean}", "error")
                        continue
                    if "ERROR[" in clean or "EXIT_CODE:" in clean or "DEBUG:" in clean:
                        self.write(f"[{name}] {clean}", "error" if "ERROR[" in clean else "system")
                        continue
                    if self.useful_log_line(name, clean):
                        line, style = errorhandler.process_line(name, f"[{name}] {clean}")
                        if line:
                            self.write(line, style)

                code = proc.wait()
                if not saw_output:
                    self.write(f"[{name}] ERROR[92]: start process ended or stalled with no output. Check WSL/Docker/SystemD manually.", "error")
                if code not in (0, None):
                    if self.stopping and code in (1, 15, -15, 143):
                        return
                    if code == 85:
                        self.write(f"[{name}] ERROR[85]: permission denied.", "error")
                    elif code == 86:
                        self.write(f"[{name}] {SUDO_ERROR_TEXT}", "error")
                    elif code == 87:
                        self.write(f"[{name}] ERROR[87]: executable not found.", "error")
                    else:
                        self.write(f"[{name}] ERROR[{code}]: command exited with code {code}.", "error")
            except Exception as e:
                self.write(f"[{name}] ERROR[93]: log reader stopped: {e}", "error")

        threading.Thread(target=reader, daemon=True).start()
        return proc

    # =====================================================
    # START / STOP
    # =====================================================

    def start_all_threaded(self):
        threading.Thread(target=self.start_all, daemon=True).start()

    def start_all(self):
        if self.running:
            self.write("Already running. Press STOP ALL first if you want a clean restart.")
            return

        self.running = True
        self.stopping = False
        self.set_status("Status: loading...", "#ffaa00")

        ok, msg = wsl_available(timeout=6)
        if not ok:
            self.write(f"[SYSTEM] ERROR[95]: WSL is not responding or has crashed: {msg}", "error")
            self.write("[SYSTEM] ERROR[95]: Try running `wsl --shutdown` in PowerShell, then reopen WSL and the manager.", "error")
            self.running = False
            self.set_status("Status: WSL error", "#ff4444")
            return

        self.stop_stale_before_start()

        self.service_priorities = settings_window.get_service_priorities()
        self.gpu_settings = settings_window.get_gpu_settings()
        self.service_processors = settings_window.get_service_processors()
        self.service_enabled = settings_window.get_service_enabled()
        self.refresh_installed_services(log=True)
        ordered = service_components.start_order(self.service_enabled, self.service_priorities)
        self.write(f"[DEBUG] AI root candidates: {', '.join(getattr(service_components, 'AI_DIR_CANDIDATES', [service_components.AI_DIR]))}", "system")
        self.write(f"[DEBUG] Enabled launch order: {', '.join(ordered) if ordered else 'none'}", "system")
        current_priority = None

        for key in ordered:
            handler = service_components.SERVICE_HANDLERS[key]
            display = handler.get("display", key)
            priority = int(self.service_priorities.get(key, handler.get("priority", 99)))
            if priority != current_priority:
                current_priority = priority
                self.write(f"\n========== START PRIORITY {priority} ==========")

            installed = self.is_service_installed(key)
            self.write(f"[DEBUG] Next service: {display} | installed={installed} | priority={priority}", "system")
            if not installed:
                self.write(f"[{display}] Not installed. Skipping start.", "warn")
                continue
            try:
                if handler.get("running", lambda m: False)(self):
                    self.write(f"[{display}] Already running. Skipping start.", "good")
                    continue
            except Exception as e:
                self.write(f"[{display}] WARNING: running check failed before start: {e}", "warn")

            try:
                handler["start"](self)
            except Exception as e:
                self.write(f"[{display}] ERROR[90]: start handler crashed: {e}", "error")
                self.write(traceback.format_exc(), "error")
                continue
            self.wait_for_service_start(key)

        self.wait_until_ready()

    def wait_for_service_start(self, key):
        """Wait for one service to finish its own startup check before starting the next.

        Services still use their normal live health checks, but launch is now clean and
        sequential: priority first, then alphabetical inside each priority level.
        """
        handler = service_components.SERVICE_HANDLERS.get(key, {})
        display = handler.get("display", key)
        timeout = int(handler.get("ready_timeout", 120))
        start = time.time()
        last_note = 0
        check_delay = 2.0
        note_delay = 10.0
        while time.time() - start < timeout:
            try:
                if handler.get("running", lambda m: False)(self):
                    self._mark_service_state(key, True)
                    self.write(f"[{display}] Ready. Continuing launch queue.", "good")
                    try:
                        threading.Timer(5.0, self.force_service_state_refresh).start()
                    except Exception:
                        pass
                    return True
            except Exception as e:
                self.write(f"[{display}] WARNING: ready check failed: {e}", "warn")
            if time.time() - last_note > note_delay:
                last_note = time.time()
                try:
                    active = self.service_process_active(key)
                except Exception:
                    active = False
                self.write(f"[{display}] Waiting for ready check... manager_process_active={active}", "system")
            # Avoid tight polling while a service is booting. This keeps the terminal useful
            # without spamming repeated readiness lines or burning CPU.
            time.sleep(check_delay)
        self.write(f"[{display}] Startup check timed out. Continuing launch queue with warning.", "warn")
        return False

    def stop_stale_before_start(self):
        self.write("\n========== CHECKING SELECTED SERVICES BEFORE START ==========")
        for key in service_components.stop_order(self.service_enabled, include_disabled=False, priorities=self.service_priorities):
            handler = service_components.SERVICE_HANDLERS[key]
            display = handler.get("display", key)
            if not self.is_service_installed(key):
                continue
            try:
                is_up = bool(handler.get("running", lambda m: False)(self))
            except Exception:
                is_up = False
            if not is_up:
                continue
            self.write(f"[{display}] Already running from an earlier session. Cleaning before fresh start.", "warn")
            if "force_stop" in handler:
                handler["force_stop"](self)
            elif "stop" in handler:
                handler["stop"](self, force=False)

    def stop_all_threaded(self):
        threading.Thread(target=self.stop_all, daemon=True).start()

    def stop_all(self):
        self.write("\n========== SAFE STOP ==========")
        self.stopping = True
        self.set_status("Status: stopping...", "#ffaa00")

        states = self.get_service_states()
        for key in service_components.stop_order(self.service_enabled, include_disabled=False, priorities=self.service_priorities):
            handler = service_components.SERVICE_HANDLERS[key]
            display = handler.get("display", key)
            if not self.is_service_installed(key):
                continue
            # V30: stop enabled+installed services even when the monitor is wrong.
            # Docker/GPU services can be running detached with no manager process, and
            # skipped stops are the main cause of VRAM not being released. Each stop
            # handler performs its own safe no-op checks.
            if "stop" in handler:
                if states.get(key, False) or self.service_process_active(key):
                    self.write(f"[{display}] Stop requested; service is active.")
                else:
                    self.write(f"[{display}] Stop requested; verifying it is fully closed.")
                handler["stop"](self, force=True)
                self._mark_service_state(key, False)

        for name, proc in list(self.processes.items()):
            try:
                if proc.poll() is None:
                    self.write(f'Attempting stop "{name}" manager process.')
                    proc.terminate()
                    time.sleep(0.5)
                if proc.poll() is None:
                    self.write(f'Force stopping "{name}" manager process.')
                    proc.kill()
            except Exception:
                pass

        self.processes.clear()
        self.running = False
        self.stopping = False

        for key in self.healthy_since:
            self.healthy_since[key] = None
        try:
            with self._service_states_lock:
                self._service_state_grace_until = {key: 0 for key in service_components.SERVICE_HANDLERS}
                self._service_down_counts = {key: 99 for key in service_components.SERVICE_HANDLERS}
                self._service_states_cache = {key: False for key in service_components.SERVICE_HANDLERS}
                self._service_states_last_check = time.time()
            self.last_service_snapshot = ""
        except Exception:
            pass

        self.set_status("Status: stopped", "#dddddd")
        self.write("All selected AI services stopped. VRAM/RAM should now be released.")
        try:
            threading.Timer(5.0, self.force_service_state_refresh).start()
        except Exception:
            pass

    def restart_xtts_threaded(self):
        threading.Thread(target=self.restart_xtts, daemon=True).start()

    def restart_xtts(self):
        self.write("\n========== RESTARTING XTTS2 ==========")
        service_components.SERVICE_HANDLERS["xtts"]["stop"](self, force=True)
        if self.service_enabled.get("xtts", True):
            service_components.SERVICE_HANDLERS["xtts"]["start"](self)
        else:
            self.write("[XTTS2] Disabled in Services. Restart skipped.")

    # =====================================================
    # FORCE STOP METHODS
    # =====================================================

    def stop_xtts(self):
        self.write('[XTTS2] Stopping XTTS docker compose stack...')
        run_cmd(f"cd {AI_DIR}/TTS/xtts && docker compose down --remove-orphans", timeout=30)
        time.sleep(2)

        if not self.docker_ok("ps --format '{{.Names}}' | grep -qx xtts-api-server"):
            self.write('[XTTS2] Stopped.')
        else:
            self.write('[XTTS2] Still running. Trying force remove...')
            self.run_docker("rm -f xtts-api-server >/dev/null 2>&1 || true", timeout=8)
            time.sleep(1)
            if not self.docker_ok("ps --format '{{.Names}}' | grep -qx xtts-api-server"):
                self.write('[XTTS2] Force stopped.')
            else:
                self.write('[XTTS2] Could not stop. Container still running.')

    def force_stop_xtts(self):
        run_cmd(f"cd {AI_DIR}/TTS/xtts && docker compose down --remove-orphans >/dev/null 2>&1 || true", timeout=30)

    def silly_running(self):
        return service_ok("curl -m 0.8 -sS -o /dev/null http://127.0.0.1:8000 >/dev/null 2>&1") or service_ok(
            "docker ps --format '{{.Names}}' 2>/dev/null | grep -qx sillytavern"
        ) or service_ok(
            "ps -eo pid,args | grep -E 'node .*server\\.js' | grep -v grep >/dev/null"
        )

    def stop_silly(self):
        if not self.silly_running():
            self.write('[SILLYTAVERN] Not running. Skipping stop.')
            return

        self.write('Attempting stop "SillyTavern" attempt 1.')
        run_cmd("pkill -TERM -f 'node .*server\\.js' 2>/dev/null || true", timeout=5)
        time.sleep(1)

        if not self.silly_running():
            self.write('[SILLYTAVERN] Stopped after attempt 1.')
            return

        self.write('Attempting stop "SillyTavern" attempt 2.')
        run_cmd("pkill -TERM -f 'node .*server\\.js' 2>/dev/null || true", timeout=5)
        time.sleep(1)

        if not self.silly_running():
            self.write('[SILLYTAVERN] Stopped after attempt 2.')
            return

        self.write('Force stopping "SillyTavern".')
        run_cmd("pkill -KILL -f 'node .*server\\.js' 2>/dev/null || true", timeout=5)
        time.sleep(1)

        if not self.silly_running():
            self.write('[SILLYTAVERN] Force stopped.')
        else:
            self.write('[SILLYTAVERN] Could not stop. Real process still detected.')

    def force_stop_silly(self):
        if self.silly_running():
            run_cmd("pkill -KILL -f 'node .*server\\.js' 2>/dev/null || true", timeout=5)

    def real_ollama_running(self):
        return service_ok(
            "ps -eo pid,args | grep -E '/usr/local/bin/ollama (serve|runner)|ollama runner' | grep -v grep >/dev/null"
        )

    def stop_ollama(self, force=False):
        if not self.real_ollama_running() and not service_ok("curl -m 0.8 -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1"):
            self.write('[OLLAMA] Not running. Skipping stop.')
            return

        self.write('Attempting stop "Ollama" attempt 1: asking systemd to stop safely.')
        run_cmd("sudo -n systemctl stop ollama >/dev/null 2>&1 || true", timeout=8)
        run_cmd("sudo -n systemctl disable ollama >/dev/null 2>&1 || true", timeout=8)
        time.sleep(2)

        if not self.real_ollama_running() and not service_ok("curl -m 0.8 -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1"):
            self.write('[OLLAMA] Fully stopped after attempt 1. Autostart disabled.')
            return

        self.write('Attempting stop "Ollama" attempt 2: sending TERM to Ollama processes.')
        run_cmd("sudo -n pkill -TERM -f '/usr/local/bin/ollama' >/dev/null 2>&1 || true", timeout=5)
        run_cmd("sudo -n pkill -TERM -f 'ollama runner' >/dev/null 2>&1 || true", timeout=5)
        run_cmd("sudo -n pkill -TERM -f 'ollama serve' >/dev/null 2>&1 || true", timeout=5)
        time.sleep(2)

        if not self.real_ollama_running() and not service_ok("curl -m 0.8 -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1"):
            self.write('[OLLAMA] Fully stopped after attempt 2.')
            return

        self.write('Force stopping "Ollama": SIGKILL for stuck Ollama processes.')
        run_cmd("sudo -n systemctl kill ollama >/dev/null 2>&1 || true", timeout=5)
        run_cmd("sudo -n pkill -9 -f '/usr/local/bin/ollama' >/dev/null 2>&1 || true", timeout=5)
        run_cmd("sudo -n pkill -9 -f 'ollama runner' >/dev/null 2>&1 || true", timeout=5)
        run_cmd("sudo -n pkill -9 -f 'ollama serve' >/dev/null 2>&1 || true", timeout=5)
        time.sleep(2)

        if not self.real_ollama_running() and not service_ok("curl -m 0.8 -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1"):
            self.write('[OLLAMA] Fully stopped and unloaded from VRAM.')
        else:
            self.write('[OLLAMA] WARNING: Could not fully stop. Ollama API/process still detected.', 'warn')

    def initial_cleanup(self):
        self.refresh_installed_services()
        self.write("Manager opened. Cleaning stale AI services...")
        self.stop_stale_before_start()
        self.set_status("Status: stopped", "#dddddd")

    # =====================================================
    # READY CHECK
    # =====================================================

    def wait_until_ready(self):
        self.set_status("Status: checking services...", "#ffaa00")

        for _ in range(90):
            checks = self.get_service_states()
            wanted_keys = [
                k for k in service_components.enabled_service_keys(self.service_enabled)
                if self.is_service_installed(k)
            ]
            wanted_ready = bool(wanted_keys) and all(checks.get(k, False) for k in wanted_keys)
            if wanted_ready:
                self.set_status("Status: running", "#00ff99")
                self.write("\nAll services running.")
                return
            time.sleep(0.5)

        self.set_status("Status: running with warnings", "#ffaa00")
        self.write("Some services did not confirm ready. Check service panel/logs.")

    # =====================================================
    # SERVICE STATES
    # =====================================================

    def is_service_installed(self, key):
        """Fast cached installed check used by UI and start/stop paths."""
        if key not in service_components.SERVICE_HANDLERS:
            return False
        return bool(self.installed_services.get(key, service_components.SERVICE_HANDLERS[key].get("default_enabled", True)))

    def refresh_installed_services(self, log=False):
        """Refresh installed-service status without blocking the UI.

        V22 first checks the local project folders through Python. That is the
        safest portable method when AI_SERVER moves drives/PCs because it does
        not depend on the WSL path conversion being perfect. It then optionally
        merges a quick WSL check for Ollama/system services.
        """
        try:
            snap = {key: False for key in service_components.SERVICE_HANDLERS}

            # 1) Fast local check. This fixes the case where installed folders
            # exist but WSL path detection misses them.
            try:
                local_snap = service_components.local_installed_snapshot()
                for key, value in local_snap.items():
                    if key in snap:
                        snap[key] = bool(value)
            except Exception as e:
                if log:
                    self.write(f"[SYSTEM] Local installed check warning: {e}", "warn")

            # 2) Quick WSL check across all candidate roots. This can confirm
            # compose/package files and detect a system Ollama install.
            try:
                roots = getattr(service_components, "AI_DIR_CANDIDATES", [service_components.AI_DIR])
                roots_text = " ".join([repr(str(r)) for r in roots if str(r).strip()])
                script = f"""
check_compose() {{ [ -d "$1" ] && ( [ -f "$1/docker-compose.yml" ] || [ -f "$1/docker-compose.yaml" ] || [ -f "$1/compose.yml" ] || [ -f "$1/compose.yaml" ] ); }}
check_node_app() {{ [ -d "$1" ] && ( [ -f "$1/package.json" ] || [ -d "$1/public" ] || [ -d "$1/src" ] ); }}
found_compose() {{ rel1="$1"; rel2="$2"; shift 2; for root in "$@"; do check_compose "$root/$rel1" && return 0; check_compose "$root/$rel2" && return 0; done; return 1; }}
found_dir() {{ rel1="$1"; rel2="$2"; shift 2; for root in "$@"; do [ -d "$root/$rel1" ] && return 0; [ -d "$root/$rel2" ] && return 0; done; return 1; }}
found_node() {{ rel1="$1"; rel2="$2"; shift 2; for root in "$@"; do check_node_app "$root/$rel1" && return 0; check_node_app "$root/$rel2" && return 0; done; return 1; }}
roots=( {roots_text} )
printf 'ollama=%s\n' "$( (command -v ollama >/dev/null 2>&1 || systemctl list-unit-files ollama.service --no-legend 2>/dev/null | grep -q '^ollama.service') && echo 1 || echo 0 )"
printf 'xtts=%s\n' "$( found_compose TTS/xtts xtts "${{roots[@]}}" && echo 1 || echo 0 )"
printf 'kokoro=%s\n' "$( found_compose TTS/kokoro kokoro "${{roots[@]}}" && echo 1 || echo 0 )"
printf 'piper=%s\n' "$( found_compose TTS/piper piper "${{roots[@]}}" && echo 1 || echo 0 )"
printf 'silly=%s\n' "$( found_node webUI/sillytavern sillytavern "${{roots[@]}}" && echo 1 || echo 0 )"
printf 'openwebui=%s\n' "$( found_compose webUI/open-webui open-webui "${{roots[@]}}" && echo 1 || echo 0 )"
"""
                out = self.run_capture(script, timeout=5)
                for line in str(out).splitlines():
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        if k in snap and v.strip() == "1":
                            snap[k] = True
            except Exception as e:
                if log:
                    self.write(f"[SYSTEM] WSL installed check warning: {e}", "warn")

            self.installed_services = snap
            self._installed_last_check = time.time()
            self.last_service_snapshot = ""
            if log:
                installed = ", ".join(service_components.SERVICE_HANDLERS[k].get("display", k) for k, v in snap.items() if v) or "none"
                roots = ", ".join(getattr(service_components, "AI_DIR_CANDIDATES", [service_components.AI_DIR]))
                self.write(f"[SYSTEM] Installed service list refreshed: {installed}.", "system")
                self.write(f"[SYSTEM] Search root: {roots}", "system")
        except Exception as e:
            if log:
                self.write(f"[SYSTEM] Installed service refresh failed: {e}", "warn")
        return dict(self.installed_services)

    def refresh_installed_services_async(self, log=False, redraw=True):
        """Refresh installed-service status on a worker thread, with no overlap."""
        try:
            if getattr(self, "_installed_refreshing", False):
                return
            self._installed_refreshing = True
            def worker():
                try:
                    before = dict(getattr(self, "installed_services", {}))
                    snap = self.refresh_installed_services(log=log)
                    if redraw and snap != before:
                        self.force_service_state_refresh()
                finally:
                    self._installed_refreshing = False
            threading.Thread(target=worker, daemon=True).start()
        except Exception:
            self._installed_refreshing = False

    def _mark_service_state(self, key, is_up):
        """Update the cached live-state immediately after a direct ready check.

        V28 also adds a short ready grace period. Docker compose commands exit
        quickly, while the global monitor can momentarily fail one of its two
        checks and flip the display back to STOPPED. A confirmed ready service
        stays shown as RUNNING during this grace period unless STOP ALL is active.
        """
        try:
            now = time.time()
            with self._service_states_lock:
                current = dict(getattr(self, "_service_states_cache", {}) or {})
                for svc_key in service_components.SERVICE_HANDLERS:
                    current.setdefault(svc_key, False)
                current[key] = bool(is_up)
                self._service_states_cache = current
                self._service_states_last_check = now
                if bool(is_up):
                    self._service_state_grace_until[key] = now + 75
                    self._service_down_counts[key] = 0
                else:
                    self._service_state_grace_until[key] = 0
                    self._service_down_counts[key] = 99
            if bool(is_up):
                self.healthy_since.setdefault(key, now)
                if self.healthy_since.get(key) is None:
                    self.healthy_since[key] = now
            else:
                self.healthy_since[key] = None
            self.last_service_snapshot = ""
        except Exception:
            pass

    def _probe_http_url(self, url, timeout=0.55):
        """Fast Windows-side HTTP probe for the AI SERVICES pane.

        V30 deliberately checks localhost from the manager process instead of
        shelling into WSL for every monitor tick. If the URL answers at all
        with a non-5xx response, the user-facing service is considered up.
        This fixes false STOPPED/STARTING states caused by slow WSL curl calls,
        container-name differences, or detached Docker processes.
        """
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AI-Server-Manager/monitor"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return int(getattr(resp, "status", 200) or 200) < 500
        except urllib.error.HTTPError as e:
            try:
                return int(e.code) < 500
            except Exception:
                return True
        except Exception:
            return False

    def _probe_service_http(self, key):
        probes = {
            "ollama": ["http://127.0.0.1:11434/api/tags", "http://localhost:11434/api/tags"],
            "xtts": ["http://127.0.0.1:8020/speakers", "http://127.0.0.1:8020/docs", "http://127.0.0.1:8020/openapi.json"],
            "kokoro": ["http://127.0.0.1:8880/docs", "http://127.0.0.1:8880/openapi.json", "http://127.0.0.1:8880/v1/audio/voices"],
            "piper": ["http://127.0.0.1:5000/docs", "http://127.0.0.1:5000/openapi.json", "http://127.0.0.1:5000/"],
            "silly": ["http://127.0.0.1:8000/", "http://localhost:8000/"],
            "openwebui": ["http://127.0.0.1:3000/", "http://127.0.0.1:3000/api/config", "http://localhost:3000/"],
        }
        return any(self._probe_http_url(url) for url in probes.get(key, []))

    def get_service_states(self):
        """Live service checks using Windows-side HTTP/API probes only.

        The AI SERVICES pane should show what is actually reachable by the user,
        not what a stale manager process, Docker container name, or WSL command
        guesses is running. Checks are parallel and cached briefly so they stay
        live without slowing the UI.
        """
        now = time.time()
        with self._service_states_lock:
            if now - self._service_states_last_check < 0.75:
                return dict(self._service_states_cache)

        keys = list(service_components.SERVICE_HANDLERS.keys())
        states = {key: False for key in keys}
        try:
            with ThreadPoolExecutor(max_workers=min(8, max(1, len(keys)))) as pool:
                future_map = {pool.submit(self._probe_service_http, key): key for key in keys}
                for fut in as_completed(future_map, timeout=2.5):
                    key = future_map[fut]
                    try:
                        states[key] = bool(fut.result())
                    except Exception:
                        states[key] = False
        except Exception as e:
            self.write(f"[SYSTEM] WARNING: service HTTP monitor failed: {e}", "warn")
            states = dict(self._service_states_cache)

        with self._service_states_lock:
            self._service_states_cache = states
            self._service_states_last_check = now
        return dict(states)

    def force_service_state_refresh(self):
        """Force a monitor refresh, then redraw the AI SERVICES panel."""
        try:
            with self._service_states_lock:
                self._service_states_last_check = 0
            states = self.get_service_states()
            mapping = services_window.get_service_config()
            active = {key: self.service_process_active(key) for _, key, _, _ in mapping}
            self.last_service_snapshot = ""
            self.safe_ui(lambda m=mapping, s=states, a=active: self.render_services(m, s, a))
        except Exception as e:
            self.write(f"[SYSTEM] WARNING: forced service refresh failed: {e}", "warn")

    def service_process_active(self, key):
        handler = service_components.SERVICE_HANDLERS.get(key, {})
        for name in handler.get("process_names", []):
            proc = self.processes.get(name)
            if proc is not None and proc.poll() is None:
                return True
        return False

    def uptime(self, key):
        start = self.healthy_since.get(key)
        if not start:
            return "-"

        seconds = int(time.time() - start)
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60

        if h:
            return f"{h}h {m}m"
        if m:
            return f"{m}m {s}s"
        return f"{s}s"

    def service_loop(self):
        while True:
            try:
                self.service_priorities = settings_window.get_service_priorities()
                self.service_enabled = settings_window.get_service_enabled()
                mapping = services_window.get_service_config()
                now = time.time()
                if now - getattr(self, "_installed_last_check", 0) >= 5:
                    self.refresh_installed_services_async(log=False, redraw=False)
                states = self.get_service_states()

                for item in mapping:
                    display, key, url = item[:3]
                    self.healthy_since.setdefault(key, None)
                    if states.get(key, False) and self.healthy_since[key] is None:
                        self.healthy_since[key] = now
                    if not states.get(key, False):
                        self.healthy_since[key] = None

                active = {key: self.service_process_active(key) for _, key, _, _ in mapping}
                uptime_tick = int(time.time()) if any(self.healthy_since.values()) else 0
                snapshot = str(states) + str(active) + str(self.healthy_since) + str(uptime_tick) + str(self.running) + str(self.stopping) + str(self.service_enabled) + str(self.installed_services)
                if snapshot != self.last_service_snapshot:
                    self.last_service_snapshot = snapshot
                    self.safe_ui(lambda m=mapping, s=states, a=active: self.render_services(m, s, a))

            except Exception as e:
                self.safe_ui(lambda: self.render_service_error(e))

            time.sleep(1)

    def render_service_error(self, e):
        self.services.config(state="normal")
        self.services.delete("1.0", tk.END)
        self.services.insert(tk.END, f"Service monitor error: {e}")
        self.services.config(state="disabled")

    def _insert_service_cell(self, display, key, url, status, tag, dot, updown, width=63):
        start_index = self.services.index(tk.END)
        self.services.insert(tk.END, f"{display:<12} ", "label")
        self.services.insert(tk.END, f"{status:<8}", tag)
        self.services.insert(tk.END, f" Up:{self.uptime(key):<7} ", "label")
        link_text = f"{url:<17}"
        clean_url = str(url).strip()
        link_tag = f"svc_link_{key}"
        self.services.tag_config(link_tag, foreground=self.colors.get("link", "#ffd36a"), underline=True)
        self.services.tag_bind(link_tag, "<Button-1>", lambda _e, u=clean_url: uihelpers.open_url(u))
        self.services.tag_bind(link_tag, "<Enter>", lambda _e: self.services.config(cursor="hand2"))
        self.services.tag_bind(link_tag, "<Leave>", lambda _e: self.services.config(cursor=""))
        self.services.insert(tk.END, link_text, ("url", link_tag))
        self.services.insert(tk.END, " ", "label")
        self.services.insert(tk.END, dot, tag)
        self.services.insert(tk.END, f" {updown}", tag)
        end_index = self.services.index(tk.END)
        # Pad the cell to a fixed width so the second column lines up cleanly.
        try:
            used = int(float(end_index.split(".")[1])) - int(float(start_index.split(".")[1]))
            if used < width:
                self.services.insert(tk.END, " " * (width - used), "label")
        except Exception:
            self.services.insert(tk.END, "   ", "label")

    def render_services(self, mapping, states, active=None):
        active = active or {}
        self.services.config(state="normal")
        self.services.delete("1.0", tk.END)

        self.services.tag_config("running", foreground=self.colors.get("good", "#00ff99"))
        self.services.tag_config("starting", foreground=self.colors.get("warn", "#ffaa00"))
        self.services.tag_config("closing", foreground=self.colors.get("warn", "#ffaa00"))
        self.services.tag_config("stopped", foreground=self.colors.get("error", "#ff4444"))
        self.services.tag_config("label", foreground=self.colors.get("label_fg", "#dddddd"))
        self.services.tag_config("url", foreground=self.colors.get("link", "#ffd36a"), underline=True)

        self.services.insert(tk.END, "AI SERVICES:\n", "label")

        rows = []
        for item in mapping:
            display, key, url = item[:3]
            if not self.service_enabled.get(key, True):
                continue
            if not self.is_service_installed(key):
                continue

            if states.get(key, False):
                status, tag, dot, updown = "RUNNING", "running", "●", "UP"
            elif self.stopping and (active.get(key, False) or self.service_process_active(key)):
                status, tag, dot, updown = "CLOSING", "closing", "●", "CLOSE"
            elif active.get(key, False):
                status, tag, dot, updown = "STARTING", "starting", "●", "CHECK"
            else:
                status, tag, dot, updown = "STOPPED", "stopped", "●", "DOWN"
            rows.append((display, key, url, status, tag, dot, updown))

        first_col = rows[:5]
        second_col = rows[5:10]
        overflow = rows[10:]
        for i in range(max(len(first_col), len(second_col))):
            if i < len(first_col):
                self._insert_service_cell(*first_col[i])
            else:
                self.services.insert(tk.END, " " * 63, "label")
            if i < len(second_col):
                self._insert_service_cell(*second_col[i])
            self.services.insert(tk.END, "\n", "label")

        for item in overflow:
            self._insert_service_cell(*item)
            self.services.insert(tk.END, "\n", "label")

        if not rows:
            self.services.insert(tk.END, "No enabled installed services. Open Services, then Manage Services to install or enable services.\n", "stopped")

        self.services.config(state="disabled")

    # =====================================================
    # GPU MONITOR
    # =====================================================

    def gpu_monitor_loop(self):
        """Live GPU monitor. Runs independently so slow CPU/WSL probes cannot block it."""
        while True:
            try:
                result = subprocess.check_output(
                    [
                        "nvidia-smi",
                        "--query-gpu=index,name,memory.used,memory.total,utilization.gpu,temperature.gpu",
                        "--format=csv,noheader,nounits",
                    ],
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=CREATE_NO_WINDOW,
                    timeout=2,
                )

                rows = []
                for row in result.strip().splitlines():
                    idx, name, used, total, util, temp = [x.strip() for x in row.split(",")]
                    rows.append((idx, name, int(used), int(total), int(util), int(temp)))

                self.gpu_rows_cache = rows
                snapshot = str(rows)
                if snapshot != self.last_gpu_snapshot:
                    self.last_gpu_snapshot = snapshot
                    self.safe_ui(lambda r=rows: self.render_gpu(r))
            except Exception as e:
                self.safe_ui(lambda: self.render_gpu_error(e))

            time.sleep(1.0)

    def cpu_monitor_loop(self):
        """Live CPU monitor. Utilization is refreshed often; temperature is throttled."""
        while True:
            try:
                now = time.time()
                cpu = dict(self.cpu_status_cache or {"name": "CPU", "util": None, "temp": None, "temp_source": None})

                try:
                    util = subprocess.check_output(
                        ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average"],
                        text=True, encoding="utf-8", errors="replace", creationflags=CREATE_NO_WINDOW, timeout=2,
                    ).strip()
                    if util:
                        cpu["util"] = int(float(util))
                except Exception:
                    pass

                if now - getattr(self, "_last_cpu_probe", 0) > 10 or not cpu.get("name") or cpu.get("temp") is None:
                    heavy = self.get_cpu_status()
                    if heavy:
                        heavy["util"] = cpu.get("util", heavy.get("util"))
                        cpu = heavy
                    self._last_cpu_probe = now

                self.cpu_status_cache = cpu
                snapshot = str(cpu)
                if snapshot != self.last_cpu_snapshot:
                    self.last_cpu_snapshot = snapshot
                    self.safe_ui(lambda c=cpu: self.render_cpu(c))
            except Exception as e:
                self.safe_ui(lambda: self.render_cpu_error(e))

            time.sleep(1.5)

    def render_gpu_error(self, e):
        self.gpu_text.config(state="normal")
        self.gpu_text.delete("1.0", tk.END)
        self.gpu_text.insert(tk.END, f"GPU monitor error: {e}")
        self.gpu_text.config(state="disabled")

    def get_cpu_status(self):
        cpu = {"name": "CPU", "util": None, "temp": None, "temp_source": None}

        # Windows CPU name and utilization.
        try:
            name = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name)"],
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
                timeout=3,
            ).strip()
            if name:
                cpu["name"] = name
        except Exception:
            pass

        try:
            util = subprocess.check_output(
                ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_Processor | Measure-Object -Property LoadPercentage -Average).Average"],
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
                timeout=3,
            ).strip()
            if util:
                cpu["util"] = int(float(util))
        except Exception:
            pass

        # 1) Try WSL/Linux sensors first. If btop can see CPU temps, it is
        # usually reading the same /sys/class/hwmon or sensors data.
        linux_temp_cmd = r'''
get_temp_from_hwmon() {
  for input in /sys/class/hwmon/hwmon*/temp*_input; do
    [ -r "$input" ] || continue
    label=""
    label_file="${input%_input}_label"
    [ -r "$label_file" ] && label="$(cat "$label_file" 2>/dev/null)"
    case "$label" in
      *Package*|*Tctl*|*Tdie*|*CPU*|*Core*|*Composite*)
        raw="$(cat "$input" 2>/dev/null)"
        [ -n "$raw" ] || continue
        awk -v r="$raw" 'BEGIN { if (r > 1000) printf "%d|WSL hwmon", r/1000; else printf "%d|WSL hwmon", r }'
        return 0
        ;;
    esac
  done
  for input in /sys/class/hwmon/hwmon*/temp*_input /sys/class/thermal/thermal_zone*/temp; do
    [ -r "$input" ] || continue
    raw="$(cat "$input" 2>/dev/null)"
    [ -n "$raw" ] || continue
    awk -v r="$raw" 'BEGIN { c=(r > 1000 ? r/1000 : r); if (c > 0 && c < 130) { printf "%d|WSL thermal", c; exit 0 } }'
    return 0
  done
  return 1
}
if command -v sensors >/dev/null 2>&1; then
  sensors 2>/dev/null | awk '
    /Package id 0|Tctl|Tdie|CPU|Core 0|Composite/ {
      for (i=1;i<=NF;i++) if ($i ~ /^\+?[0-9.]+°C$/) { gsub(/[+°C]/,"",$i); printf "%d|lm-sensors", $i; exit }
    }'
fi
get_temp_from_hwmon
'''
        try:
            temp_out = subprocess.check_output(
                wsl_cmd(linux_temp_cmd),
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
                timeout=4,
            ).strip()
            if temp_out:
                first = temp_out.splitlines()[0].strip()
                if "|" in first:
                    value, source = first.split("|", 1)
                    cpu["temp"] = int(float(value.strip()))
                    cpu["temp_source"] = source.strip()
                    return cpu
        except Exception:
            pass

        # 2) Try LibreHardwareMonitor/OpenHardwareMonitor on Windows.
        ps_temp = r'''
$ErrorActionPreference = 'SilentlyContinue'
function Get-TempFromNamespace($ns) {
    $sensors = Get-CimInstance -Namespace $ns -ClassName Sensor -ErrorAction SilentlyContinue |
        Where-Object { $_.SensorType -eq 'Temperature' -and $_.Value -ne $null }
    $preferred = $sensors | Where-Object {
        $_.Name -match 'CPU Package|CPU Core|Core Max|Tctl|Tdie|Package'
    } | Select-Object -First 1
    if (-not $preferred) { $preferred = $sensors | Select-Object -First 1 }
    if ($preferred) { return [math]::Round([double]$preferred.Value) }
    return $null
}
$t = Get-TempFromNamespace 'root/LibreHardwareMonitor'
if ($t -ne $null) { Write-Output ("$t|LibreHardwareMonitor"); exit }
$t = Get-TempFromNamespace 'root/OpenHardwareMonitor'
if ($t -ne $null) { Write-Output ("$t|OpenHardwareMonitor"); exit }
# Some Windows builds expose thermal zones through performance counters instead of WMI.
try {
    $counter = Get-Counter '\Thermal Zone Information(*)\Temperature' -ErrorAction SilentlyContinue
    $sample = $counter.CounterSamples | Where-Object { $_.CookedValue -gt 250 -and $_.CookedValue -lt 420 } | Select-Object -First 1
    if ($sample) {
        $c = [math]::Round([double]$sample.CookedValue - 273.15)
        if ($c -gt -20 -and $c -lt 130) { Write-Output ("$c|Windows Thermal Counter"); exit }
    }
} catch {}

$acpi = Get-CimInstance MSAcpi_ThermalZoneTemperature -Namespace root/wmi -ErrorAction SilentlyContinue |
    Select-Object -First 1 -ExpandProperty CurrentTemperature
if ($acpi) {
    $c = [math]::Round(($acpi / 10) - 273.15)
    if ($c -gt -20 -and $c -lt 130) { Write-Output ("$c|Windows ACPI"); exit }
}

# Final option: if the user has a helper CLI/script, call it. It should print just the temperature number.
$helperPaths = @(
    "$PSScriptRoot\tools\cpu-temp.ps1",
    "$PWD\tools\cpu-temp.ps1",
    "$HOME\cpu-temp.ps1"
)
foreach ($hp in $helperPaths) {
    if (Test-Path $hp) {
        $raw = powershell -NoProfile -ExecutionPolicy Bypass -File $hp 2>$null | Select-Object -First 1
        if ($raw -match '([0-9]+(?:\.[0-9]+)?)') {
            $c = [math]::Round([double]$Matches[1])
            if ($c -gt 0 -and $c -lt 130) { Write-Output ("$c|CPU temp helper"); exit }
        }
    }
}
'''
        try:
            temp_out = subprocess.check_output(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_temp],
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
                timeout=5,
            ).strip()
            if temp_out:
                first = temp_out.splitlines()[0].strip()
                if "|" in first:
                    value, source = first.split("|", 1)
                    cpu["temp"] = int(float(value.strip()))
                    cpu["temp_source"] = source.strip()
                else:
                    cpu["temp"] = int(float(first))
        except Exception:
            pass

        return cpu

    def render_cpu_error(self, e):
        self.cpu_text.config(state="normal")
        self.cpu_text.delete("1.0", tk.END)
        self.cpu_text.insert(tk.END, f"CPU monitor error: {e}")
        self.cpu_text.config(state="disabled")

    def render_gpu(self, rows):
        self.gpu_text.config(state="normal")
        self.gpu_text.delete("1.0", tk.END)

        self.gpu_text.tag_config("label", foreground="#dddddd")
        self.gpu_text.insert(tk.END, "GPU STATUS:\n", "label")

        gpu_name_colors = ["#7CFF9B", "#46E6B0", "#A3FF7C", "#5CFFDA"]

        for i, (idx, name, used, total, util, temp) in enumerate(rows):
            name_tag = f"gpu_name_{idx}"
            vram_tag = f"vram_{idx}"
            util_tag = f"util_{idx}"
            temp_tag = f"temp_{idx}"

            self.gpu_text.tag_config(name_tag, foreground=gpu_name_colors[i % len(gpu_name_colors)])
            self.gpu_text.tag_config(vram_tag, foreground=gradient_green_red(used, total))
            self.gpu_text.tag_config(util_tag, foreground=gradient_green_red(util, 100))
            self.gpu_text.tag_config(temp_tag, foreground=gradient_blue_red(temp, 80))

            self.gpu_text.insert(tk.END, f"GPU {idx} | ", "label")
            self.gpu_text.insert(tk.END, f"{name:<28}", name_tag)
            self.gpu_text.insert(tk.END, " | VRAM ", "label")
            self.gpu_text.insert(tk.END, f"{used:>5}/{total:<5} MB", vram_tag)
            self.gpu_text.insert(tk.END, " | Util ", "label")
            self.gpu_text.insert(tk.END, f"{util:>3}%", util_tag)
            self.gpu_text.insert(tk.END, " | Temp ", "label")
            self.gpu_text.insert(tk.END, f"{temp:>3}C\n", temp_tag)

        self.gpu_text.config(state="disabled")

    def render_cpu(self, cpu):
        cpu = cpu or {"name": "CPU", "util": None, "temp": None}
        cpu_name = cpu.get("name") or "CPU"
        cpu_util = cpu.get("util")
        cpu_temp = cpu.get("temp")
        cpu_temp_source = cpu.get("temp_source")

        self.cpu_text.config(state="normal")
        self.cpu_text.delete("1.0", tk.END)

        self.cpu_text.tag_config("label", foreground="#dddddd")
        self.cpu_text.tag_config("cpu_name", foreground="#7CFF9B")
        self.cpu_text.tag_config("cpu_util", foreground=gradient_green_red(cpu_util or 0, 100))
        self.cpu_text.tag_config("cpu_temp", foreground=gradient_blue_red(cpu_temp or 0, 80))

        self.cpu_text.insert(tk.END, "CPU STATUS:\n", "label")
        self.cpu_text.insert(tk.END, "CPU  | ", "label")
        self.cpu_text.insert(tk.END, f"{cpu_name}\n", "cpu_name")
        self.cpu_text.insert(tk.END, "Util | ", "label")
        self.cpu_text.insert(tk.END, f"{cpu_util:>3}%\n" if cpu_util is not None else "  -%\n", "cpu_util")
        self.cpu_text.insert(tk.END, "Temp | ", "label")
        self.cpu_text.insert(tk.END, f"{cpu_temp:>3}C\n" if cpu_temp is not None else "  -C\n", "cpu_temp")

        self.cpu_text.config(state="disabled")

    # =====================================================
    # MISC
    # =====================================================

    def open_silly(self):
        webbrowser.open("http://localhost:8000")

    def on_close(self):
        self.stop_all()
        self.root.destroy()


# =====================================================
# MAIN
# =====================================================

if __name__ == "__main__":
    root = tk.Tk()
    app = AIManager(root)
    root.mainloop()
