# Version: 1.6
"""Ollama model manager and curated model catalog.

V75 keeps the model catalog into components/models.txt so GitHub can update the
available model list without changing this Python UI file. The Python side owns
searching, filtering, installing, removing, and updating that text catalog.
"""

from pathlib import Path
import base64
import shlex
import re
import threading
import time
import tkinter as tk
from tkinter import ttk
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

from components import settings as settings_store
from components import uihelpers


MODEL_LIST_PATH = Path(__file__).with_name("models.txt")
MODEL_LIST_URL = "https://raw.githubusercontent.com/Jaymax15/Local_AI_Service_Manager/main/components/models.txt"
MODEL_CATEGORIES = ["Assistant", "Roleplay", "Vision"]

def _to_wsl_path(path):
    """Convert the manager project root to a WSL path so Ollama models stay portable."""
    raw = str(path).strip().replace('\\', '/')
    if len(raw) >= 3 and raw[1] == ':' and raw[2] == '/':
        return f"/mnt/{raw[0].lower()}{raw[2:]}"
    marker = '/mnt/'
    idx = raw.lower().find(marker)
    if idx >= 0:
        return raw[idx:]
    return raw


def _quote_sh(value):
    return shlex.quote(str(value or ""))


def _ollama_portable_command(extra_command=""):
    """Return a WSL-safe command that repairs Ollama's portable model path, then runs extra_command.

    V89 avoids reading /proc/<pid>/environ because the GUI sudo whitelist does not
    allow sudo cat/tr for arbitrary /proc files. Instead it repairs the systemd
    override, daemon-reloads, restarts/starts Ollama when needed, and verifies the
    active systemd Environment property points at the portable model folder.
    """
    ai_dir = _to_wsl_path(Path(__file__).resolve().parent.parent).rstrip('/')
    base = f"{ai_dir}/ollama"
    models = f"{base}/models"
    script = f"""#!/usr/bin/env bash
set -u
OLLAMA_BASE={_quote_sh(base)}
OLLAMA_MODEL_DIR={_quote_sh(models)}

mkdir -p "$OLLAMA_MODEL_DIR" >/dev/null 2>&1 || true

if id ollama >/dev/null 2>&1; then
  sudo -n mkdir -p /usr/share/ollama /var/lib/ollama "$OLLAMA_MODEL_DIR" >/dev/null 2>&1 || true
  sudo -n chown -R ollama:ollama /usr/share/ollama /var/lib/ollama "$OLLAMA_BASE" >/dev/null 2>&1 || true
fi

sudo -n mkdir -p /etc/systemd/system/ollama.service.d >/dev/null 2>&1 || true
cat > /tmp/ai-manager-models-ollama-override.conf <<EOF
[Service]
Environment="HOME=/usr/share/ollama"
Environment="OLLAMA_MODELS=$OLLAMA_MODEL_DIR"
Environment="OLLAMA_KEEP_ALIVE=-1"
Environment="OLLAMA_HOST=0.0.0.0:11434"
EOF
sudo -n install -m 0644 /tmp/ai-manager-models-ollama-override.conf /etc/systemd/system/ollama.service.d/override.conf >/dev/null 2>&1 || true
rm -f /tmp/ai-manager-models-ollama-override.conf
sudo -n systemctl daemon-reload >/dev/null 2>&1 || true

service_env_matches() {{
  env_line=$(systemctl show ollama --property=Environment --value 2>/dev/null || true)
  printf '%s\n' "$env_line" | grep -F "OLLAMA_MODELS=$OLLAMA_MODEL_DIR" >/dev/null 2>&1
}}

api_ready() {{
  curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1
}}

if ! service_env_matches; then
  echo "[MODELS] Repairing Ollama model path to $OLLAMA_MODEL_DIR"
  sudo -n systemctl stop ollama >/dev/null 2>&1 || true
fi

# Restart whenever the service is inactive, or after an override repair, so pulls
# use the portable folder immediately instead of an old running environment.
if ! systemctl is-active --quiet ollama 2>/dev/null || ! api_ready; then
  sudo -n systemctl start ollama >/dev/null 2>&1 || true
else
  # A quick restart is safer for Model Manager actions because it guarantees the
  # latest override is live before list/pull/remove runs.
  sudo -n systemctl restart ollama >/dev/null 2>&1 || true
fi

for _i in $(seq 1 40); do
  api_ready && break
  sleep 1
done

if ! service_env_matches; then
  echo "ERROR[MODELS-PATH-001]: Ollama systemd environment is not using portable model folder: $OLLAMA_MODEL_DIR"
  exit 86
fi

if ! api_ready; then
  echo 'ERROR[MODELS-PATH-002]: Ollama API did not become ready after model-path repair.'
  exit 87
fi

{extra_command}
"""
    payload = base64.b64encode(script.encode("utf-8")).decode("ascii")
    return f"printf '%s' '{payload}' | base64 -d | bash"

DEFAULT_MODELS_TEXT = """# Version: 1.1
# AI Server Manager model list
# Format: category|ollama_name|display_label|size_or_note
# Categories currently used by the UI: Assistant, Roleplay, Vision
# Keep this file plain text so it can be updated from GitHub without changing models.py.

[Assistant]
llama3.2:1b|Llama 3.2 1B - tiny/fast|1B
llama3.2:3b|Llama 3.2 3B - small|3B
llama3.1:8b|Llama 3.1 8B - balanced|8B
llama3.3:70b|Llama 3.3 70B - large/high quality|70B
qwen2.5:3b|Qwen2.5 3B - small assistant/coding|3B
qwen2.5:7b|Qwen2.5 7B - balanced assistant/coding|7B
qwen2.5:14b|Qwen2.5 14B - larger assistant/coding|14B
mistral:7b|Mistral 7B - balanced assistant|7B
gemma2:2b|Gemma 2 2B - tiny assistant|2B
gemma2:9b|Gemma 2 9B - balanced assistant|9B
gemma3:4b|Gemma 3 4B - newer small assistant|4B
gemma3:12b|Gemma 3 12B - newer balanced assistant|12B
phi3:mini|Phi-3 Mini - tiny assistant|mini
phi4:latest|Phi-4 - compact reasoning assistant|latest
deepseek-r1:1.5b|DeepSeek R1 1.5B - tiny reasoning|1.5B
deepseek-r1:7b|DeepSeek R1 7B - balanced reasoning|7B
deepseek-r1:14b|DeepSeek R1 14B - stronger reasoning|14B
codellama:7b|CodeLlama 7B - coding|7B
qwen2.5-coder:1.5b|Qwen2.5 Coder 1.5B - tiny coding|1.5B
qwen2.5-coder:7b|Qwen2.5 Coder 7B - coding|7B
qwen2.5-coder:14b|Qwen2.5 Coder 14B - larger coding|14B
starcoder2:3b|StarCoder2 3B - small coding|3B
starcoder2:7b|StarCoder2 7B - balanced coding|7B

[Roleplay]
dolphin-mistral:7b|Dolphin Mistral 7B - chat/roleplay|7B
dolphin-llama3:8b|Dolphin Llama 3 8B - chat/roleplay|8B
neural-chat:7b|Neural Chat 7B - chat/roleplay|7B
openchat:7b|OpenChat 7B - chat/roleplay|7B
nous-hermes2:10.7b|Nous Hermes 2 10.7B - writing/roleplay|10.7B
wizard-vicuna-uncensored:7b|Wizard Vicuna 7B - chat/roleplay|7B
llama2-uncensored:7b|Llama 2 Uncensored 7B - roleplay/chat|7B
mistral-nemo:12b|Mistral Nemo 12B - writing/chat|12B

[Vision]
llava:7b|LLaVA 7B - image understanding|7B
llava:13b|LLaVA 13B - stronger image understanding|13B
llava:34b|LLaVA 34B - large image understanding|34B
llava-llama3:8b|LLaVA Llama 3 8B - image chat|8B
bakllava:7b|BakLLaVA 7B - image chat|7B
moondream:latest|Moondream - small vision model|latest
minicpm-v:8b|MiniCPM-V 8B - compact vision model|8B
"""


def _ensure_model_file():
    try:
        if not MODEL_LIST_PATH.exists() or not MODEL_LIST_PATH.read_text(encoding="utf-8", errors="ignore").strip():
            MODEL_LIST_PATH.write_text(DEFAULT_MODELS_TEXT, encoding="utf-8")
    except Exception:
        pass


def _normalise_category(value):
    raw = str(value or "").strip().lower().replace(" ", "")
    if raw in {"assistant", "assist", "general", "coding", "code"}:
        return "Assistant"
    if raw in {"roleplay", "role-play", "rp", "chat", "story", "writing"}:
        return "Roleplay"
    if raw in {"vision", "image", "images", "multimodal", "visual"}:
        return "Vision"
    return "Assistant"


def load_model_catalog():
    """Read components/models.txt and return normalised model dictionaries."""
    _ensure_model_file()
    models = []
    current_category = "Assistant"
    try:
        text = MODEL_LIST_PATH.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        text = DEFAULT_MODELS_TEXT

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_category = _normalise_category(line[1:-1])
            continue

        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 4 and parts[0] in MODEL_CATEGORIES:
            category, name, label, size = parts[:4]
        elif len(parts) >= 3:
            category = current_category
            name, label, size = parts[:3]
        elif len(parts) == 2:
            category = current_category
            name, label = parts
            size = ""
        else:
            continue

        name = _safe_model_name(name)
        if not name:
            continue
        category = _normalise_category(category)
        label = label or name
        size = size or ""
        display = f"{label} [{name}]" if name not in label else label
        models.append({"name": name, "label": label, "display": display, "category": category, "size": size})

    # De-duplicate by category + name while preserving file order.
    seen = set()
    unique = []
    for model in models:
        key = (model["category"], model["name"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(model)
    return unique or _fallback_catalog()



def model_catalog_version(text=None):
    """Return a friendly version marker from models.txt if one is present."""
    try:
        if text is None:
            _ensure_model_file()
            text = MODEL_LIST_PATH.read_text(encoding="utf-8", errors="ignore")
        for raw in str(text or "").splitlines()[:25]:
            line = raw.strip().lstrip("#").strip()
            lower = line.lower()
            if lower.startswith("version:"):
                return line.split(":", 1)[1].strip() or "unknown"
            if lower.startswith("catalog version:"):
                return line.split(":", 1)[1].strip() or "unknown"
    except Exception:
        pass
    return "unknown"


def parse_model_catalog_text(text):
    """Parse supplied model-list text without touching the local file."""
    current_category = "Assistant"
    models = []
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("[") and line.endswith("]"):
            current_category = _normalise_category(line[1:-1])
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 4 and _normalise_category(parts[0]) in MODEL_CATEGORIES:
            category, name, label, size = parts[:4]
        elif len(parts) >= 3:
            category = current_category
            name, label, size = parts[:3]
        elif len(parts) == 2:
            category = current_category
            name, label = parts
            size = ""
        else:
            continue
        name = _safe_model_name(name)
        if not name:
            continue
        category = _normalise_category(category)
        label = label or name
        size = size or ""
        display = f"{label} [{name}]" if name not in label else label
        models.append({"name": name, "label": label, "display": display, "category": category, "size": size})
    seen = set()
    unique = []
    for model in models:
        key = (model["category"], model["name"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(model)
    return unique


def _download_model_catalog_text(timeout=20):
    req = Request(MODEL_LIST_URL, headers={"User-Agent": "AI-Server-Manager"})
    with urlopen(req, timeout=timeout) as resp:
        data = resp.read(512000).decode("utf-8", errors="replace")
    if "|" not in data or len(data.strip()) < 40:
        raise ValueError("Downloaded model list did not look valid.")
    if not parse_model_catalog_text(data):
        raise ValueError("Downloaded model list did not contain valid model entries.")
    return data


def update_model_catalog_from_github(log_callback=None):
    """Download models.txt, compare with local models, write it, and return result info."""
    def log(message):
        if log_callback:
            try:
                log_callback(str(message))
            except Exception:
                pass

    _ensure_model_file()
    old_text = MODEL_LIST_PATH.read_text(encoding="utf-8", errors="ignore") if MODEL_LIST_PATH.exists() else ""
    old_models = parse_model_catalog_text(old_text)
    old_version = model_catalog_version(old_text)

    log("Checking GitHub for models.txt...")
    new_text = _download_model_catalog_text(timeout=20)
    new_models = parse_model_catalog_text(new_text)
    new_version = model_catalog_version(new_text)

    log(f"Local list version: {old_version}")
    log(f"GitHub list version: {new_version}")

    version_known = old_version != "unknown" and new_version != "unknown"
    if version_known and old_version == new_version:
        log("No changes made. Your model list version is already up to date.")
        return {"ok": True, "changed": False, "added": [], "removed": [], "version": new_version, "count": len(new_models)}

    old_keys = {(m["category"], m["name"]) for m in old_models}
    new_keys = {(m["category"], m["name"]) for m in new_models}
    added = [m for m in new_models if (m["category"], m["name"]) not in old_keys]
    removed = [m for m in old_models if (m["category"], m["name"]) not in new_keys]

    if old_text.strip() == new_text.strip():
        log("No changes made. Your model list is already up to date.")
        return {"ok": True, "changed": False, "added": added, "removed": removed, "version": new_version, "count": len(new_models)}

    MODEL_LIST_PATH.write_text(new_text, encoding="utf-8")
    log("Download successful. Local models.txt has been updated.")

    if added:
        by_cat = {cat: [] for cat in MODEL_CATEGORIES}
        for model in added:
            by_cat.setdefault(model["category"], []).append(model)
        for cat in MODEL_CATEGORIES:
            items = by_cat.get(cat, [])
            if not items:
                continue
            label = "Vision" if cat == "Vision" else cat
            log(f"New {label} models added:")
            for model in items:
                size = f" ({model['size']})" if model.get("size") else ""
                log(f"  - {model['label']} [{model['name']}]{size}")
    else:
        log("No new model entries were added. File content changed only in notes, edits, or formatting.")

    if removed:
        log(f"Note: {len(removed)} old model entr{'y was' if len(removed) == 1 else 'ies were'} removed from the GitHub list.")

    log(f"Available models in list: {len(new_models)}")
    return {"ok": True, "changed": True, "added": added, "removed": removed, "version": new_version, "count": len(new_models)}


def _fallback_catalog():
    return [
        {"name": "llama3.2:3b", "label": "Llama 3.2 3B - small", "display": "Llama 3.2 3B - small [llama3.2:3b]", "category": "Assistant", "size": "3B"},
        {"name": "llama3.1:8b", "label": "Llama 3.1 8B - balanced", "display": "Llama 3.1 8B - balanced [llama3.1:8b]", "category": "Assistant", "size": "8B"},
        {"name": "dolphin-mistral:7b", "label": "Dolphin Mistral 7B - chat/roleplay", "display": "Dolphin Mistral 7B - chat/roleplay [dolphin-mistral:7b]", "category": "Roleplay", "size": "7B"},
        {"name": "llava:7b", "label": "LLaVA 7B - image understanding", "display": "LLaVA 7B - image understanding [llava:7b]", "category": "Vision", "size": "7B"},
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
        lower = line.lower()
        if not line or lower.startswith("name"):
            continue
        # Never show shell/error output as installed model names.
        if lower.startswith(("/bin/bash", "bash:", "error", "error[", "traceback", "sudo:")):
            continue
        parts = line.split()
        if not parts:
            continue
        name = _safe_model_name(parts[0])
        if name:
            models.append(name)
    return models


def _run_model_command(manager, command, timeout=None, on_line=None):
    try:
        if hasattr(manager, "run_stream") and on_line is not None:
            return manager.run_stream(command, on_line=on_line, timeout=timeout)
        out = manager.run_capture(command, timeout=timeout)
        return 0, out
    except Exception as e:
        return 1, str(e)


def _score_model(model, query):
    if not query:
        return 100
    hay = f"{model.get('label','')} {model.get('name','')} {model.get('category','')} {model.get('size','')}".lower()
    q = query.lower().strip()
    if q in model.get("name", "").lower():
        return 500
    if q in model.get("label", "").lower():
        return 400
    words = [w for w in re.split(r"\s+", q) if w]
    if words and all(w in hay for w in words):
        return 300 + len(words)
    score = 0
    for w in words:
        if w in hay:
            score += 50
        else:
            # very light fuzzy scoring for typos/partial words
            for token in re.split(r"[^a-z0-9.:-]+", hay):
                if token.startswith(w[:3]) and len(w) >= 3:
                    score += 15
                    break
    return score


def open_models_window(manager):
    colors = settings_store.get_theme_colors()
    try:
        if not manager.is_service_installed("ollama"):
            manager.write("[MODELS] Ollama must be installed before opening Manage Models.", "warn")
            return
    except Exception:
        pass

    model_catalog = load_model_catalog()

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
    category_var = tk.StringVar(value="Assistant")
    selected_model = tk.StringVar(value="")
    _combo_values = []

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

    win.bind("<Escape>", lambda _e: close_models())

    outer = tk.Frame(win, bg=colors["text_bg"], highlightbackground=colors["border"], highlightthickness=1)
    outer.pack(fill=tk.BOTH, expand=True)
    header = tk.Frame(outer, bg=colors["header_bg"])
    header.pack(fill=tk.X)
    tk.Label(header, text="Model manager", bg=colors["header_bg"], fg=colors["fg"], font=("Segoe UI", 14, "bold"), anchor="w", padx=12, pady=10).pack(side=tk.LEFT, fill=tk.X, expand=True)
    uihelpers.rounded_button(header, "CLOSE", close_models, bg=colors["button_bad"], width=92, height=32).pack(side=tk.RIGHT, padx=10, pady=8)

    body = tk.Frame(outer, bg=colors["root_bg"])
    body.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)
    tk.Label(body, text="Install Ollama models from the curated list, update the list from GitHub, or remove models already installed.", bg=colors["root_bg"], fg=colors["muted_fg"], font=("Segoe UI", 10), anchor="w").pack(fill=tk.X, pady=(0, 10))

    top = tk.Frame(body, bg=colors["panel_bg"], highlightbackground=colors["border"], highlightthickness=1, padx=10, pady=10)
    top.pack(fill=tk.X, pady=(0, 10))

    tk.Label(top, text="Type", bg=colors["panel_bg"], fg=colors["muted_fg"], font=("Segoe UI", 9, "bold"), anchor="w").grid(row=0, column=0, sticky="w", padx=(0, 10))
    category_combo = ttk.Combobox(top, textvariable=category_var, values=MODEL_CATEGORIES, state="readonly", width=13)
    category_combo.grid(row=1, column=0, sticky="ew", padx=(0, 10), pady=(4, 0))

    tk.Label(top, text="Search / select model", bg=colors["panel_bg"], fg=colors["muted_fg"], font=("Segoe UI", 9, "bold"), anchor="w").grid(row=0, column=1, sticky="w")
    combo = ttk.Combobox(top, textvariable=selected_model, values=[], state="normal", width=62)
    combo.grid(row=1, column=1, sticky="ew", padx=(0, 10), pady=(4, 0))

    action_row = tk.Frame(top, bg=colors["panel_bg"])
    action_row.grid(row=1, column=2, sticky="e", pady=(4, 0))
    top.grid_columnconfigure(0, weight=0)
    top.grid_columnconfigure(1, weight=8)
    top.grid_columnconfigure(2, weight=0)

    content = tk.Frame(body, bg=colors["panel_bg"], highlightbackground=colors["border"], highlightthickness=1)
    content.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
    header_row = tk.Frame(content, bg=colors["header_bg"])
    header_row.pack(fill=tk.X)
    tk.Label(header_row, text="Installed models", bg=colors["header_bg"], fg=colors["muted_fg"], font=("Segoe UI", 9, "bold"), anchor="center").pack(fill=tk.X, pady=7)

    installed_rows_frame = tk.Frame(content, bg=colors["panel_bg"], padx=10, pady=10)
    installed_rows_frame.pack(fill=tk.BOTH, expand=True)

    status = tk.Label(body, textvariable=status_var, bg=colors["root_bg"], fg=colors["warn"], font=("Segoe UI", 10, "bold"), anchor="w")
    status.pack(fill=tk.X)

    def models_for_current_filter():
        category = category_var.get() or "Assistant"
        typed = selected_model.get().strip()
        base = [m for m in model_catalog if m["category"] == category]
        scored = []
        for model in base:
            score = _score_model(model, typed)
            if not typed or score > 0:
                scored.append((score, model))
        scored.sort(key=lambda item: (-item[0], item[1]["label"].lower()))
        return [m for _score, m in scored]

    def update_combo_values(open_dropdown=False, preserve_text=True):
        nonlocal _combo_values
        before = selected_model.get()
        models = models_for_current_filter()
        values = [m["display"] for m in models]
        _combo_values = values
        combo["values"] = values
        if not preserve_text or (before not in values and not before.strip()):
            selected_model.set(values[0] if values else "")
        if open_dropdown and values:
            try:
                combo.event_generate("<Down>")
            except Exception:
                pass

    def selected_name():
        value = selected_model.get().strip()
        for model in model_catalog:
            if value in {model["display"], model["label"], model["name"]}:
                return model["name"]
        # If the user typed text that includes [model:name], extract it.
        m = re.search(r"\[([^\]]+)\]\s*$", value)
        if m:
            return _safe_model_name(m.group(1))
        # Last fallback: allow advanced users to type an Ollama model name directly.
        return _safe_model_name(value.split()[0] if value else "")

    def on_combo_key(_event=None):
        update_combo_values(open_dropdown=True, preserve_text=True)

    def on_category_change(_event=None):
        selected_model.set("")
        update_combo_values(open_dropdown=False, preserve_text=False)

    combo.bind("<KeyRelease>", on_combo_key)
    combo.bind("<Button-1>", lambda _e: update_combo_values(open_dropdown=True, preserve_text=True))
    category_combo.bind("<<ComboboxSelected>>", on_category_change)

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
            cmd = _ollama_portable_command("ollama list 2>&1")
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
            cmd = _ollama_portable_command(f"ollama pull {shlex.quote(name)}")
            rc, out = _run_model_command(manager, cmd, timeout=3600, on_line=on_line)
            if rc == 0:
                verify_cmd = _ollama_portable_command(f"ollama list 2>&1 | awk '{{print $1}}' | grep -Fx -- {shlex.quote(name)} >/dev/null")
                verify_rc, verify_out = _run_model_command(manager, verify_cmd, timeout=40)
                if verify_rc == 0:
                    manager.write(f"[MODELS] Installed model: {name}", "good")
                    manager.safe_ui(lambda: status_var.set(f"Installed {name}. Refreshing model list..."))
                    time.sleep(0.5)
                    load_installed_models()
                else:
                    manager.write(f"[MODELS] ERROR: Pull completed, but Ollama did not report model in portable model folder: {name}. {verify_out}", "error")
                    manager.safe_ui(lambda: status_var.set(f"Install verification failed for {name}. Check terminal log."))
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
            rc, out = _run_model_command(manager, _ollama_portable_command(f"ollama rm {shlex.quote(safe)} 2>&1"), timeout=120)
            if rc == 0:
                manager.write(f"[MODELS] Removed model: {safe}", "good")
                manager.safe_ui(lambda: status_var.set(f"Removed {safe}. Refreshing model list..."))
                time.sleep(0.5)
                load_installed_models()
            else:
                manager.write(f"[MODELS] ERROR: Model remove failed for {safe}: {out}", "error")
                manager.safe_ui(lambda: status_var.set(f"Remove failed for {safe}. Check terminal log."))
        threading.Thread(target=worker, daemon=True).start()

    uihelpers.rounded_button(action_row, "Install Model", command=install_selected_model, bg=colors["button_good"], width=138, height=32, font=("Segoe UI", 9, "bold")).pack(side=tk.LEFT, padx=(0, 8))

    update_combo_values(open_dropdown=False, preserve_text=False)
    load_installed_models()
    try:
        combo.focus_set()
    except Exception:
        pass
