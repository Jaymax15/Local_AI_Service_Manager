# Version: 1.1
"""Lightweight GitHub updater for AI Server Manager managed files.

V84 introduces components/update list.txt as a simple manifest. The updater
checks the remote manifest, compares versions, downloads only newer managed
files, writes the remote manifest locally after successful updates, and asks the
user to reopen the manager so changed Python files load cleanly.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

REPO_RAW_BASE = "https://raw.githubusercontent.com/Jaymax15/Local_AI_Service_Manager/main"
PROJECT_ROOT = Path(__file__).resolve().parent.parent
UPDATE_LIST_NAME = "update list.txt"
UPDATE_LIST_PATH = Path(__file__).with_name(UPDATE_LIST_NAME)
MAX_DOWNLOAD_BYTES = 2_500_000

# Files that contain user choices or machine-local state should be listed in the
# manifest for version visibility, but should not be overwritten by auto-update.
LOCAL_ONLY_PATHS = {
    "components/settings.txt",
}

TEXT_FILE_EXTENSIONS = {".py", ".txt", ".md", ".ps1", ".sh", ".json", ".yml", ".yaml"}


@dataclass
class ManifestEntry:
    path: str
    version: str
    mode: str = "update"
    description: str = ""

    @property
    def is_local_only(self) -> bool:
        return self.mode.lower() in {"local", "local-only", "preserve", "skip"} or self.path in LOCAL_ONLY_PATHS


def _normalise_path(value: str) -> str:
    value = str(value or "").strip().replace("\\", "/").lstrip("/")
    while "//" in value:
        value = value.replace("//", "/")
    return value


def _safe_project_path(rel_path: str) -> Path:
    rel = _normalise_path(rel_path)
    if not rel or rel.startswith("../") or "/../" in rel or rel == "..":
        raise ValueError(f"Unsafe update path: {rel_path!r}")
    target = (PROJECT_ROOT / rel).resolve()
    root = PROJECT_ROOT.resolve()
    try:
        target.relative_to(root)
    except Exception:
        raise ValueError(f"Update path escapes project folder: {rel_path!r}")
    return target


def _version_tuple(value: str):
    raw = str(value or "").strip().lower().replace("version", "").replace("v", "").strip()
    parts = re.findall(r"\d+", raw)
    if not parts:
        return (0,)
    return tuple(int(p) for p in parts[:6])


def is_newer(remote_version: str, local_version: str) -> bool:
    return _version_tuple(remote_version) > _version_tuple(local_version)


def parse_manifest(text: str):
    entries = []
    manifest_version = "unknown"
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("#"):
            marker = line.lstrip("#").strip()
            lower = marker.lower()
            if lower.startswith("version:"):
                manifest_version = marker.split(":", 1)[1].strip() or "unknown"
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) < 2:
            continue
        rel_path = _normalise_path(parts[0])
        version = parts[1] or "0"
        mode = parts[2] if len(parts) >= 3 and parts[2] else "update"
        description = parts[3] if len(parts) >= 4 else ""
        if rel_path:
            entries.append(ManifestEntry(rel_path, version, mode, description))
    # Keep only the last entry for duplicate paths so the manifest can override.
    deduped = {}
    for entry in entries:
        deduped[entry.path] = entry
    return manifest_version, list(deduped.values())


def _download_text(rel_path: str, timeout=25) -> str:
    rel = _normalise_path(rel_path)
    encoded = quote(rel, safe="/")
    url = f"{REPO_RAW_BASE}/{encoded}"
    req = Request(url, headers={"User-Agent": "AI-Server-Manager-Updater"})
    with urlopen(req, timeout=timeout) as resp:
        data = resp.read(MAX_DOWNLOAD_BYTES + 1)
    if len(data) > MAX_DOWNLOAD_BYTES:
        raise ValueError(f"Downloaded file too large: {rel}")
    return data.decode("utf-8", errors="replace")


def download_remote_manifest(timeout=25):
    text = _download_text(f"components/{UPDATE_LIST_NAME}", timeout=timeout)
    if "|" not in text or "ai_server_manager.py" not in text:
        raise ValueError("Downloaded update list did not look valid.")
    version, entries = parse_manifest(text)
    if not entries:
        raise ValueError("Downloaded update list contained no valid entries.")
    return text, version, entries


def read_local_manifest():
    if not UPDATE_LIST_PATH.exists():
        return "", "unknown", []
    text = UPDATE_LIST_PATH.read_text(encoding="utf-8", errors="ignore")
    version, entries = parse_manifest(text)
    return text, version, entries


def read_file_version(rel_path: str) -> str:
    """Read a file's own version marker, falling back to the local manifest."""
    try:
        target = _safe_project_path(rel_path)
        if not target.exists():
            return "missing"
        if target.suffix.lower() not in TEXT_FILE_EXTENSIONS:
            return "unknown"
        text = target.read_text(encoding="utf-8", errors="ignore")
        if target.name == "settings.txt":
            try:
                data = json.loads(text)
                value = data.get("file_version") or data.get("version")
                if value:
                    return str(value)
            except Exception:
                pass
        for raw in text.splitlines()[:30]:
            line = raw.strip()
            line = line.replace("<!--", "").replace("-->", "").strip()
            line = line.lstrip("#").strip()
            lower = line.lower()
            if lower.startswith("version:"):
                return line.split(":", 1)[1].strip() or "unknown"
            if lower.startswith("file version:"):
                return line.split(":", 1)[1].strip() or "unknown"
        return "unknown"
    except Exception:
        return "unknown"


def _atomic_write_text(target: Path, text: str):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=target.name + ".", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp_name, target)
    finally:
        try:
            if os.path.exists(tmp_name):
                os.remove(tmp_name)
        except Exception:
            pass


def apply_manager_updates_from_github(log_callback=None):
    """Update changed manager files from GitHub according to update list.txt."""
    def log(message, tag=None):
        if log_callback:
            try:
                log_callback(str(message), tag)
                return
            except TypeError:
                try:
                    log_callback(str(message))
                    return
                except Exception:
                    pass
            except Exception:
                pass

    log("Checking GitHub update list...", "info")
    local_manifest_text, local_manifest_version, local_entries = read_local_manifest()
    remote_manifest_text, remote_manifest_version, remote_entries = download_remote_manifest(timeout=25)
    log(f"Local update list version: {local_manifest_version}", "muted")
    log(f"GitHub update list version: {remote_manifest_version}", "muted")

    local_by_path = {entry.path: entry for entry in local_entries}
    to_update = []
    skipped_local = []

    for remote_entry in remote_entries:
        if remote_entry.is_local_only:
            skipped_local.append(remote_entry)
            continue
        actual_version = read_file_version(remote_entry.path)
        local_entry = local_by_path.get(remote_entry.path)
        local_manifest_file_version = local_entry.version if local_entry else "missing"
        local_version = actual_version if actual_version not in {"unknown", "missing"} else local_manifest_file_version
        if actual_version == "missing" or is_newer(remote_entry.version, local_version):
            to_update.append((remote_entry, local_version, actual_version))

    if not to_update:
        # Still keep the local manifest in sync when only the manifest notes/list changed.
        if remote_manifest_text.strip() != local_manifest_text.strip() and is_newer(remote_manifest_version, local_manifest_version):
            _atomic_write_text(UPDATE_LIST_PATH, remote_manifest_text)
            log("Update list refreshed. No program files needed updating.", "success")
        else:
            log("No program updates found.", "muted")
        if skipped_local:
            log("User settings are preserved and not overwritten by auto-update.", "warn")
        return {"ok": True, "changed": False, "updated": [], "skipped_local": skipped_local}

    log(f"Program updates found: {len(to_update)}", "success")

    downloaded = []
    for entry, local_version, actual_version in to_update:
        log(f"Downloading {entry.path} ({local_version} → {entry.version})...", "info")
        file_text = _download_text(entry.path, timeout=30)
        if not file_text.strip():
            raise ValueError(f"Downloaded empty file: {entry.path}")
        downloaded.append((entry, file_text))

    for entry, file_text in downloaded:
        target = _safe_project_path(entry.path)
        _atomic_write_text(target, file_text)
        log(f"Updated {entry.path} to {entry.version}", "success")

    # Write the remote manifest last so a partial failed update does not make the
    # local install think it is already current.
    _atomic_write_text(UPDATE_LIST_PATH, remote_manifest_text)
    log("Local update list updated.", "success")
    if skipped_local:
        log("User settings were preserved and not overwritten.", "warn")
    log("Update complete. AI Server Manager will close; reopen it to load updated files.", "success")
    return {"ok": True, "changed": True, "updated": [entry.path for entry, _text in downloaded], "skipped_local": skipped_local}
