# Version: 1.2
"""Shared path helpers for AI Server Manager.

Keeps project-root and data-folder paths in one place so components can be
reorganized without breaking portable service folders.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


def _find_project_root() -> Path:
    candidates = []
    try:
        candidates.append(Path(__file__).resolve().parents[2])
    except Exception:
        pass
    try:
        if sys.argv and sys.argv[0]:
            candidates.append(Path(sys.argv[0]).resolve().parent)
    except Exception:
        pass
    try:
        candidates.append(Path.cwd().resolve())
    except Exception:
        pass

    seen = set()
    for candidate in candidates:
        try:
            root = candidate.resolve()
            key = str(root).lower() if os.name == "nt" else str(root)
            if key in seen:
                continue
            seen.add(key)
            if (root / "components").exists() and ((root / "ai_server_manager.py").exists() or list(root.glob("*manager*.py"))):
                return root
        except Exception:
            continue
    try:
        return Path(__file__).resolve().parents[2]
    except Exception:
        return Path.cwd().resolve()


def to_wsl_path(path) -> str:
    raw = str(path).strip()
    try:
        if os.name == "nt":
            raw = os.path.abspath(raw)
    except Exception:
        pass
    raw = raw.replace("\\", "/")
    if raw.startswith("//wsl.localhost/") or raw.startswith("//wsl$/"):
        marker = "/mnt/"
        idx = raw.lower().find(marker)
        if idx >= 0:
            return raw[idx:]
    if len(raw) >= 3 and raw[1] == ":" and raw[2] == "/":
        return f"/mnt/{raw[0].lower()}{raw[2:]}"
    return raw


PROJECT_ROOT = _find_project_root()
COMPONENTS_ROOT = PROJECT_ROOT / "components"
CORE_ROOT = COMPONENTS_ROOT / "core"
UI_ROOT = COMPONENTS_ROOT / "ui"
INSTALL_ROOT = COMPONENTS_ROOT / "install"
UPDATE_ROOT = COMPONENTS_ROOT / "update"
DATA_ROOT = COMPONENTS_ROOT / "data"
IMAGES_ROOT = COMPONENTS_ROOT / "images"
CACHE_ROOT = PROJECT_ROOT / "cache"
OLLAMA_ROOT = PROJECT_ROOT / "ollama"
TTS_ROOT = PROJECT_ROOT / "TTS"
WEBUI_ROOT = PROJECT_ROOT / "webUI"

WSL_PROJECT_ROOT = to_wsl_path(PROJECT_ROOT)
WSL_OLLAMA_ROOT = f"{WSL_PROJECT_ROOT.rstrip('/')}/ollama"
WSL_TTS_ROOT = f"{WSL_PROJECT_ROOT.rstrip('/')}/TTS"
WSL_WEBUI_ROOT = f"{WSL_PROJECT_ROOT.rstrip('/')}/webUI"


def ensure_runtime_folders(log_func=None) -> bool:
    """Create portable runtime folders beside ai_server_manager.py.

    These folders are intentionally not shipped in the zip. They are created
    at startup so the project remains portable when moved to another drive.
    """
    folders = [
        CACHE_ROOT,
        CACHE_ROOT / "manager_runtime",
        TTS_ROOT,
        WEBUI_ROOT,
        OLLAMA_ROOT,
        OLLAMA_ROOT / "models",
        OLLAMA_ROOT / "models" / "blobs",
        OLLAMA_ROOT / "models" / "manifests",
    ]
    ok = True
    made = []
    for folder in folders:
        try:
            if not folder.exists():
                folder.mkdir(parents=True, exist_ok=True)
                made.append(str(folder))
        except Exception as e:
            ok = False
            if log_func:
                try:
                    log_func(f"[SYSTEM] WARNING: failed to create runtime folder {folder}: {e}")
                except Exception:
                    pass
    if made and log_func:
        try:
            log_func("[SYSTEM] Created runtime folders: " + ", ".join(made))
        except Exception:
            pass
    return ok
