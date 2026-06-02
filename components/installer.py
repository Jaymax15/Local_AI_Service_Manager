r"""Installer window and service install catalog for AI Server Manager V77 Headless Docker.

V52 installs/uses headless Docker Engine inside WSL instead of Docker Desktop integration.
"""

import shlex
import re
import threading
import time
import tkinter as tk
from tkinter import messagebox
from pathlib import Path

from components import components as service_components
from components import uihelpers
from components import settings as settings_store

# ---------------------------------------------------------------------------
# Base folder bootstrap
# ---------------------------------------------------------------------------
# The manager is portable and may be placed directly in a drive root, for example
# F:\ai_server_manager.py + F:\components.
#
# WSL can sometimes throw drvfs/9p "Invalid argument" when a generated installer
# script tries to create first-level folders like /mnt/f/TTS. Creating these base
# folders from Windows/Python first is more reliable. Docker service installers
# can then create subfolders inside them from WSL.
def _project_root_windows():
    r"""Find the portable project root on Windows.

    Supports the manager living directly in a drive root, for example:
      F:\ai_server_manager.py
      F:\components\
    """
    candidates = []
    try:
        candidates.append(Path(__file__).resolve().parents[1])
    except Exception:
        pass
    try:
        import sys
        candidates.append(Path(sys.argv[0]).resolve().parent)
    except Exception:
        pass
    try:
        candidates.append(Path.cwd())
    except Exception:
        pass

    seen = set()
    for root in candidates:
        try:
            root = root.resolve()
            key = str(root).lower()
            if key in seen:
                continue
            seen.add(key)
            if (root / "components").exists() and ((root / "ai_server_manager.py").exists() or list(root.glob("*manager*.py"))):
                return root
        except Exception:
            continue

    try:
        return Path(__file__).resolve().parents[1]
    except Exception:
        return Path.cwd()


def ensure_base_install_folders(log_func=None):
    """Create stable project folders from Windows/Python side.

    This runs when installer.py is imported, when the Add Service window opens,
    and before install actions. It intentionally creates only broad category
    folders, not service folders.

    It must NOT create an "ollama" folder because a bare folder caused false
    installed detection. Ollama is checked via WSL command/systemd only.
    """
    root = _project_root_windows()
    folders = [
        "cache",
        "cache/manager_runtime",
        "TTS",
        "webUI",
    ]

    if log_func:
        try:
            log_func(f"[INSTALLER] DEBUG: Windows project root={root}")
        except Exception:
            pass

    made = []
    for folder in folders:
        path = root / folder
        try:
            if not path.exists():
                path.mkdir(parents=True, exist_ok=True)
                made.append(str(path))
        except Exception as e:
            if log_func:
                try:
                    log_func(f"[INSTALLER] DEBUG: failed to create base folder {path}: {e}")
                except Exception:
                    pass

    if made and log_func:
        try:
            log_func("[INSTALLER] DEBUG: created base folders: " + ", ".join(made))
        except Exception:
            pass
    return root


try:
    ensure_base_install_folders()
except Exception:
    pass



def _q(value):
    return shlex.quote(str(value or ""))


def _ai_root_debug():
    try:
        return getattr(service_components, "AI_DIR", "") or ""
    except Exception:
        return ""


def _wsl_join(*parts):
    """Join WSL paths without destroying a leading /mnt/... slash.

    V35 accidentally stripped the leading slash from /mnt/f paths, which made
    installers generate targets such as mnt/f/TTS/kokoro. V36 keeps absolute
    WSL paths absolute and prints useful debug when path detection fails.
    """
    clean = []
    absolute = False
    for i, part in enumerate(parts):
        if part is None:
            continue
        raw = str(part).replace("\\", "/").strip()
        if not raw:
            continue
        if i == 0 and raw.startswith("/"):
            absolute = True
        raw = raw.strip("/")
        if raw:
            clean.append(raw)
    if not clean:
        return ""
    joined = "/".join(clean)
    return "/" + joined if absolute else joined


def service_target_dir(key):
    """Return canonical WSL install directory for a service."""
    ai_dir = getattr(service_components, "AI_DIR", "") or ""
    if ai_dir and not str(ai_dir).startswith("/"):
        ai_dir = "/" + str(ai_dir).lstrip("/")
    tts_dir = getattr(service_components, "TTS_DIR", "") or _wsl_join(ai_dir, "TTS")
    if tts_dir and not str(tts_dir).startswith("/"):
        tts_dir = "/" + str(tts_dir).lstrip("/")
    webui_dir = getattr(service_components, "WEBUI_DIR", "") or _wsl_join(ai_dir, "webUI")
    if webui_dir and not str(webui_dir).startswith("/"):
        webui_dir = "/" + str(webui_dir).lstrip("/")

    mapping = {
        "kokoro": _wsl_join(tts_dir, "kokoro"),
        "piper": _wsl_join(tts_dir, "piper"),
        "xtts": _wsl_join(tts_dir, "xtts"),
        "openwebui": _wsl_join(webui_dir, "open-webui"),
        "silly": _wsl_join(webui_dir, "sillytavern"),
        "ollama": _wsl_join(ai_dir, "ollama"),
    }
    return mapping.get(key, "")


OPEN_WEBUI_COMPOSE = """services:
  open-webui:
    image: ghcr.io/open-webui/open-webui:main
    container_name: open-webui
    restart: unless-stopped
    ports:
      - "3000:8080"
    environment:
      - WEBUI_SECRET_KEY=ai-server-manager-change-me
      - OLLAMA_BASE_URL=http://host.docker.internal:11434
    volumes:
      - open-webui-data:/app/backend/data
    extra_hosts:
      - "host.docker.internal:host-gateway"

volumes:
  open-webui-data:
"""

KOKORO_COMPOSE = """services:
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
"""

PIPER_COMPOSE = """services:
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
      - piper-data:/data

volumes:
  piper-data:
"""



XTTS_COMPOSE = """services:
  xtts:
    image: daswer123/xtts-api-server:latest
    container_name: xtts-api-server
    restart: unless-stopped
    ports:
      - "8020:8020"
    environment:
      - COQUI_TOS_AGREED=1
      - DEVICE=cuda
    volumes:
      - ./voices:/app/voices
      - ./output:/app/output
      - xtts-models:/root/.local/share/tts
      - xtts-cache:/root/.cache

volumes:
  xtts-models:
  xtts-cache:
"""



SILLY_CONFIG = """listen: true
port: 8000
whitelistMode: true
enableForwardedWhitelist: true
whitelist:
  - 127.0.0.1
  - localhost
  - 172.16.0.0/12
basicAuthMode: false
enableUserAccounts: false
dataRoot: ./data
"""

SILLY_COMPOSE = """services:
  sillytavern:
    image: ghcr.io/sillytavern/sillytavern:latest
    container_name: sillytavern
    restart: unless-stopped
    network_mode: host
    environment:
      - NODE_ENV=production
    volumes:
      - ./config.yaml:/home/node/app/config.yaml
      - sillytavern-data:/home/node/app/data
      - sillytavern-plugins:/home/node/app/plugins
      - sillytavern-extensions:/home/node/app/public/scripts/extensions/third-party

volumes:
  sillytavern-data:
  sillytavern-plugins:
  sillytavern-extensions:
"""

def _silly_install_script():
    """Install SillyTavern as a headless Docker service.

    V66 change: the old source/npm install could install correctly but crash on
    start in WSL with EXIT_CODE 133 after config.yaml creation. Running the
    official container keeps the service portable, still places manager config
    under webUI/sillytavern, and avoids Node/node_modules issues on /mnt drives.
    """
    return _docker_install_script(
        "silly",
        "SillyTavern",
        SILLY_COMPOSE,
        data_dirs=[],
        image_hint="ghcr.io/sillytavern/sillytavern:latest",
    )

def _wsl_path_to_windows_path(wsl_path):
    r"""Convert /mnt/f/TTS/kokoro to F:\\TTS\\kokoro for Windows-side writes."""
    s = str(wsl_path or "").strip().replace("\\", "/")
    if s.startswith("/mnt/") and len(s) >= 6:
        drive = s[5]
        rest = s[6:].lstrip("/")
        return Path(f"{drive.upper()}:\\") / Path(*[p for p in rest.split("/") if p])
    return _project_root_windows() / s.strip("/")


def _docker_compose_for_key(key):
    if key == "xtts":
        return XTTS_COMPOSE, ["voices", "output"]
    if key == "kokoro":
        return KOKORO_COMPOSE, []
    if key == "piper":
        return PIPER_COMPOSE, ["piper-data"]
    if key == "openwebui":
        return OPEN_WEBUI_COMPOSE, ["data"]
    if key == "silly":
        return SILLY_COMPOSE, []
    return None, []


def finalize_docker_service_files(key, log_func=None):
    """Write final Docker service files from Windows/Python side.

    This avoids WSL drvfs/9p issues where mkdir -p /mnt/f/TTS can fail with
    "Invalid argument" inside manager-launched WSL scripts even though the same
    path exists and works from Windows/Python.
    """
    ensure_base_install_folders(log_func)
    compose_text, data_dirs = _docker_compose_for_key(key)
    if not compose_text:
        if log_func:
            log_func(f"[INSTALLER] DEBUG: no Python finalizer for {key}; skipping")
        return True

    target_wsl = service_target_dir(key)
    target = _wsl_path_to_windows_path(target_wsl)
    if log_func:
        log_func(f"[INSTALLER] DEBUG: Python finalizer target WSL={target_wsl}")
        log_func(f"[INSTALLER] DEBUG: Python finalizer target Windows={target}")

    target.mkdir(parents=True, exist_ok=True)
    compose_file = target / "docker-compose.yml"
    compose_file.write_text(compose_text.rstrip() + "\n", encoding="utf-8", newline="\n")

    if key == "silly":
        config_file = target / "config.yaml"
        config_file.write_text(SILLY_CONFIG.rstrip() + "\n", encoding="utf-8", newline="\n")

    for d in data_dirs:
        (target / d).mkdir(parents=True, exist_ok=True)

    if log_func:
        log_func(f"[INSTALLER] DEBUG: final compose exists={compose_file.exists()} path={compose_file}")
        if key == "silly":
            config_file = target / "config.yaml"
            log_func(f"[INSTALLER] DEBUG: final SillyTavern config exists={config_file.exists()} path={config_file}")
        for d in data_dirs:
            p = target / d
            log_func(f"[INSTALLER] DEBUG: final data dir exists={p.exists()} path={p}")
        log_func("[INSTALLER] DEBUG: Docker install note: image layers live inside Docker, not inside this service folder.")
        log_func("[INSTALLER] DEBUG: Named Docker volumes hold persistent app data; local data folders are not required.")

    return compose_file.exists()

def _docker_install_script(key, display, compose_text, data_dirs=None, image_hint=None):
    """Build a Docker-service installer script.

    V43 diagnostic/stability change:
    - Stage compose files in /tmp, not inside the final /mnt/<drive> folder.
    - Only copy into the final project folder after docker compose pull succeeds.
    - Never use TARGET.installing on the Windows-mounted drive.
    """
    data_dirs = data_dirs or []
    target = service_target_dir(key)
    hint = (" " + image_hint) if image_hint else ""
    mkdirs = "\n".join(f'mkdir -p "$WORK/{d}"' for d in data_dirs)

    return f"""#!/usr/bin/env bash
set -u
TARGET={_q(target)}
WORK="/tmp/ai_manager_install_{key}_$$"
echo "DEBUG: AI_DIR={_q(_ai_root_debug())}"
echo "DEBUG: computed TARGET=$TARGET"
echo "DEBUG: path bytes=$(printf %s "$TARGET" | od -An -tx1 | tr -d '\\n')"
echo "DEBUG: work folder=$WORK"
echo "DEBUG: parent=$(dirname "$TARGET" 2>/dev/null || echo unknown)"
echo "DEBUG: whoami=$(whoami 2>/dev/null || echo unknown), pwd=$(pwd 2>/dev/null || echo unknown)"
if [ -z "$TARGET" ]; then
  echo "ERROR[INSTALL-PATH-001]: target install folder is empty. Manager path detection failed."
  exit 20
fi
if ! echo "$TARGET" | grep -q '^/mnt/'; then
  echo "ERROR[INSTALL-PATH-002]: target is not a WSL /mnt path: $TARGET"
  exit 20
fi
case "$TARGET" in
  *".."*) echo "ERROR[INSTALL-PATH-003]: target contains invalid parent path: $TARGET"; exit 20 ;;
esac

echo "PROGRESS:5:Preparing {display} installer workspace"
echo "DEBUG: final folder handling=Python/Windows"
printf 'DEBUG: TARGET shell-escaped=<%q>\\n' "$TARGET"

# V48:
# Do not stat, mkdir, ls, cp, or rm any final /mnt/<drive> service folders from
# this WSL script. On some Windows-mounted test drives, manager-launched WSL
# can fail with:
#   mkdir: cannot stat '/mnt/f/TTS': Invalid argument
# even though Windows/Python can see and create F:\\TTS.
# This script only verifies Docker and pulls the image from /tmp. Python writes
# final files after __AI_MANAGER_INSTALL_OK__.
rm -rf "$WORK" 2>/dev/null || true
mkdir -p "$WORK" || {{ echo "ERROR[INSTALL-WORK-001]: could not create work folder $WORK"; exit 20; }}
{mkdirs}
cd "$WORK" || exit 20

echo "PROGRESS:20:Writing docker-compose.yml"
cat > docker-compose.yml <<'EOF'
{compose_text.rstrip()}
EOF

echo "DEBUG: work listing after compose write:"
ls -la "$WORK" 2>&1 | sed 's/^/DEBUG: WORK: /'

echo "PROGRESS:25:Checking headless Docker Engine"
ACTIVE_DISTRO="${{WSL_DISTRO_NAME:-unknown}}"
[ -z "$ACTIVE_DISTRO" ] && ACTIVE_DISTRO="this WSL distro"
echo "DEBUG: WSL distro=$ACTIVE_DISTRO"
echo "DEBUG: docker command path=$(command -v docker 2>/dev/null || echo missing)"
echo "DEBUG: /usr/bin/docker link=$(readlink /usr/bin/docker 2>/dev/null || echo none)"
echo "DEBUG: /usr/bin/docker real=$(readlink -f /usr/bin/docker 2>/dev/null || echo none)"

headless_docker_ok() {{
  if sudo -n systemctl is-active docker >/dev/null 2>&1 || sudo -n service docker status >/dev/null 2>&1; then
    if docker info >/dev/null 2>&1; then
      os="$(docker info --format '{{{{.OperatingSystem}}}}' 2>/dev/null || true)"
      if echo "$os" | grep -qi "Docker Desktop"; then return 1; fi
      return 0
    fi
    if sudo -n docker info >/dev/null 2>&1; then
      os="$(sudo -n docker info --format '{{{{.OperatingSystem}}}}' 2>/dev/null || true)"
      if echo "$os" | grep -qi "Docker Desktop"; then return 1; fi
      return 0
    fi
  fi
  return 1
}}

install_headless_docker() {{
  echo "PROGRESS:26:Preparing headless Docker Engine"
  # Do not require unrestricted passwordless sudo.
  # AI Manager grants only specific commands, so "sudo -n true" is expected to fail.
  if ! sudo -n apt-get --version >/dev/null 2>&1; then
    echo "ERROR[DOCKER-SUDO-001]: Headless Docker install needs AI Manager sudo access for apt-get."
    echo "DEBUG: sudo -n true may fail by design; checking sudo -n apt-get instead."
    echo "FIX: Open Settings > Sudo Access, enter your WSL sudo password, then retry install."
    exit 86
  fi
  if ! sudo -n install --version >/dev/null 2>&1; then
    echo "ERROR[DOCKER-SUDO-002]: Headless Docker install needs AI Manager sudo access for install/chmod/tee."
    echo "FIX: Open Settings > Sudo Access, enter your WSL sudo password, then retry install."
    exit 86
  fi
  echo "DEBUG: AI Manager sudo access for apt/install commands: OK"
  if headless_docker_ok; then echo "DEBUG: Headless Docker Engine already available."; return 0; fi
  echo "DEBUG: Installing Docker Engine directly inside WSL/Ubuntu. Docker Desktop integration will not be used."
  if [ -L /usr/bin/docker ]; then
    link_target="$(readlink /usr/bin/docker 2>/dev/null || true)"
    real_target="$(readlink -f /usr/bin/docker 2>/dev/null || true)"
    echo "DEBUG: existing /usr/bin/docker symlink=$link_target real=$real_target"
    if echo "$link_target $real_target" | grep -qiE '/mnt/wsl/docker-desktop|/mnt/c/Program Files/Docker'; then
      echo "DEBUG: Removing Docker Desktop docker shim from /usr/bin/docker"
      sudo -n rm -f /usr/bin/docker
    fi
  fi
  echo "PROGRESS:27:Removing conflicting Ubuntu Docker packages"
  old_pkgs="$(dpkg-query -W -f='${{binary:Package}}\n' docker.io docker-compose docker-compose-v2 docker-doc podman-docker containerd runc 2>/dev/null | tr '\n' ' ' || true)"
  if [ -n "$old_pkgs" ]; then sudo -n apt-get remove -y $old_pkgs || true; else echo "DEBUG: No conflicting distro Docker packages found."; fi
  echo "PROGRESS:28:Adding Docker official apt repository"
  sudo -n apt-get update
  sudo -n apt-get install -y ca-certificates curl
  sudo -n install -m 0755 -d /etc/apt/keyrings
  sudo -n rm -f /etc/apt/keyrings/docker.asc
  sudo -n curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  sudo -n chmod a+r /etc/apt/keyrings/docker.asc
  codename="$(. /etc/os-release && echo "${{UBUNTU_CODENAME:-$VERSION_CODENAME}}")"
  arch="$(dpkg --print-architecture)"
  cat <<EOF | sudo -n tee /etc/apt/sources.list.d/docker.sources >/dev/null
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $codename
Components: stable
Architectures: $arch
Signed-By: /etc/apt/keyrings/docker.asc
EOF
  sudo -n apt-get update
  echo "PROGRESS:30:Installing Docker Engine packages"
  sudo -n apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  sudo -n groupadd -f docker || true
  sudo -n usermod -aG docker "$(whoami)" || true
  echo "PROGRESS:32:Starting Docker Engine service"
  sudo -n systemctl enable --now docker >/dev/null 2>&1 || sudo -n service docker start
  echo "PROGRESS:33:Verifying headless Docker Engine"
  if ! sudo -n docker info >/dev/null 2>&1; then
    echo "ERROR[DOCKER-HEADLESS-VERIFY]: Docker Engine installed but docker info failed."
    sudo -n docker info 2>&1 | sed 's/^/DEBUG: docker: /' || true
    exit 81
  fi
  echo "DEBUG: Headless Docker verified with sudo docker info."
}}

docker_cmd() {{ if docker info >/dev/null 2>&1; then docker "$@"; else sudo -n docker "$@"; fi; }}
install_headless_docker
echo "DEBUG: docker engine path=$(command -v docker 2>/dev/null || echo missing)"
echo "DEBUG: docker engine version=$(docker_cmd --version 2>&1 || true)"
echo "DEBUG: docker compose version=$(docker_cmd compose version 2>&1 || true)"
if ! docker_cmd compose version >/dev/null 2>&1; then echo "ERROR[DOCKER-004]: Headless Docker compose plugin missing/broken."; exit 81; fi

echo "PROGRESS:35:Pulling Docker image{hint}"
docker_cmd compose pull
rc=$?
if [ "$rc" != "0" ]; then echo "ERROR[DOCKER-003]: docker compose pull failed with code $rc"; exit 83; fi

echo "PROGRESS:75:Docker pull complete"
echo "DEBUG: Final service files will be written by Windows/Python finalizer."
echo "DEBUG: This avoids WSL /mnt drive mkdir/copy failures."

echo "PROGRESS:90:Ready to finalize service files"
echo "{display} Docker image ready"
"""


def _ollama_install_script():
    ai_dir = getattr(service_components, "AI_DIR", "") or ""
    marker = _wsl_join(ai_dir, "ollama")
    model_dir = _wsl_join(marker, "models")
    return f"""#!/usr/bin/env bash
set -u

AI_DIR={_q(ai_dir)}
OLLAMA_BASE={_q(marker)}
OLLAMA_MODEL_DIR={_q(model_dir)}

echo "DEBUG: AI_DIR=$AI_DIR"
echo "DEBUG: OLLAMA_BASE=$OLLAMA_BASE"
echo "DEBUG: OLLAMA_MODEL_DIR=$OLLAMA_MODEL_DIR"
echo "PROGRESS:10:Checking sudo/curl prerequisites"

if ! sudo -n apt-get --version >/dev/null 2>&1; then
  echo "ERROR[OLLAMA-SUDO-001]: Ollama install needs AI Manager sudo access for apt-get/systemctl."
  echo "FIX: Open Settings > Sudo Access, enter your WSL sudo password, then retry install."
  exit 86
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "DEBUG: curl missing; installing curl"
  sudo -n apt-get update
  sudo -n apt-get install -y curl ca-certificates
fi

echo "PROGRESS:18:Repairing any stale Ollama reinstall state"
# Reinstall safety: after an uninstall, the Linux ollama user/group may still
# exist while its old home/data folders were removed. If the official service
# starts before these folders are recreated with the right owner, Ollama can
# fail with: mkdir /usr/share/ollama: permission denied.
sudo -n mkdir -p /usr/share/ollama /var/lib/ollama "$OLLAMA_MODEL_DIR" >/dev/null 2>&1 || true
if id ollama >/dev/null 2>&1; then
  sudo -n chown -R ollama:ollama /usr/share/ollama /var/lib/ollama "$OLLAMA_BASE" >/dev/null 2>&1 || true
fi
sudo -n systemctl stop ollama >/dev/null 2>&1 || true
sudo -n systemctl reset-failed ollama >/dev/null 2>&1 || true
sudo -n systemctl daemon-reload >/dev/null 2>&1 || true

echo "PROGRESS:20:Downloading Ollama Linux installer"
curl -fsSL https://ollama.com/install.sh -o /tmp/ollama-install.sh
if [ "$?" != "0" ] || [ ! -s /tmp/ollama-install.sh ]; then
  echo "ERROR[OLLAMA-CURL-001]: Could not download https://ollama.com/install.sh"
  exit 87
fi

echo "DEBUG: installer first line=$(head -n 1 /tmp/ollama-install.sh 2>/dev/null || true)"
chmod +x /tmp/ollama-install.sh 2>/dev/null || true

echo "PROGRESS:35:Running Ollama installer with sudo"
sudo -n sh /tmp/ollama-install.sh
rc=$?
if [ "$rc" != "0" ]; then
  echo "ERROR[OLLAMA-001]: Ollama installer exited with code $rc"
  echo "DEBUG: Try in WSL manually: curl -fsSL https://ollama.com/install.sh | sh"
  exit "$rc"
fi

echo "PROGRESS:60:Verifying Ollama command"
if ! command -v ollama >/dev/null 2>&1; then
  echo "ERROR[OLLAMA-087]: Ollama command was not found after install."
  echo "DEBUG: PATH=$PATH"
  ls -la /usr/local/bin/ollama /usr/bin/ollama 2>&1 || true
  exit 87
fi
echo "DEBUG: ollama path=$(command -v ollama)"
echo "DEBUG: ollama version=$(ollama --version 2>&1 || true)"

echo "PROGRESS:70:Configuring Ollama model folder"
mkdir -p "$OLLAMA_MODEL_DIR" >/dev/null 2>&1 || true
sudo -n mkdir -p /etc/systemd/system/ollama.service.d /usr/share/ollama /var/lib/ollama "$OLLAMA_MODEL_DIR"
cat >/tmp/ai-manager-ollama-override.conf <<EOF
[Service]
Environment="HOME=/usr/share/ollama"
Environment="OLLAMA_MODELS=$OLLAMA_MODEL_DIR"
Environment="OLLAMA_KEEP_ALIVE=-1"
Environment="OLLAMA_HOST=0.0.0.0:11434"
EOF
sudo -n install -m 0644 /tmp/ai-manager-ollama-override.conf /etc/systemd/system/ollama.service.d/override.conf
rm -f /tmp/ai-manager-ollama-override.conf
# Make reinstall idempotent. The official installer may leave/create these as
# root-owned if the ollama user already existed from a previous install.
sudo -n chown -R ollama:ollama /usr/share/ollama /var/lib/ollama "$OLLAMA_BASE" >/dev/null 2>&1 || true
sudo -n chmod 755 /usr/share/ollama /var/lib/ollama >/dev/null 2>&1 || true

echo "DEBUG: service user=$(id ollama 2>/dev/null || echo missing)"
echo "DEBUG: /usr/share/ollama=$(ls -ld /usr/share/ollama 2>&1 || true)"
echo "DEBUG: /var/lib/ollama=$(ls -ld /var/lib/ollama 2>&1 || true)"
echo "DEBUG: model folder=$(ls -ld "$OLLAMA_MODEL_DIR" 2>&1 || true)"

echo "PROGRESS:82:Starting Ollama service"
sudo -n systemctl daemon-reload
sudo -n systemctl enable ollama >/dev/null 2>&1 || true
sudo -n systemctl restart ollama
rc=$?
if [ "$rc" != "0" ]; then
  echo "ERROR[OLLAMA-SYSTEMD-001]: systemctl restart ollama failed with code $rc"
  sudo -n systemctl status ollama --no-pager 2>&1 | tail -n 40 || true
  journalctl -u ollama -n 60 --no-pager 2>&1 || true
  exit "$rc"
fi

echo "PROGRESS:90:Waiting for Ollama API"
ready=0
for i in $(seq 1 90); do
  if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done

if [ "$ready" != "1" ]; then
  echo "ERROR[OLLAMA-API-001]: Ollama service started but API did not respond."
  sudo -n systemctl status ollama --no-pager 2>&1 | tail -n 40 || true
  journalctl -u ollama -n 80 --no-pager 2>&1 || true
  exit 94
fi

echo "PROGRESS:100:Ollama installed and running"
echo "Ollama API ready at http://127.0.0.1:11434"
echo "Ollama models folder: $OLLAMA_MODEL_DIR"
"""


SERVICE_CATALOG = [
    {"key": "ollama", "display": "Ollama", "version_label": "latest", "version_command": "curl -fsSL https://api.github.com/repos/ollama/ollama/releases/latest 2>/dev/null | grep -m1 '\"tag_name\"' | sed -E 's/.*\"([^\"]+)\".*/\\1/' || echo latest", "install_command": _ollama_install_script, "uninstall_command": service_components.ollama_uninstall_script},
    {"key": "xtts", "display": "XTTS2", "version_label": "latest", "version_command": "docker manifest inspect daswer123/xtts-api-server:latest >/dev/null 2>&1 && echo latest || echo latest", "install_command": lambda: _docker_install_script("xtts", "XTTS2", XTTS_COMPOSE, data_dirs=["voices", "output"], image_hint="daswer123/xtts-api-server:latest")},
    {"key": "kokoro", "display": "Kokoro", "version_label": "v0.2.1 GPU", "version_command": "docker manifest inspect ghcr.io/remsky/kokoro-fastapi-gpu:v0.2.1 >/dev/null 2>&1 && echo v0.2.1 || echo v0.2.1", "install_command": lambda: _docker_install_script("kokoro", "Kokoro", KOKORO_COMPOSE, image_hint="ghcr.io/remsky/kokoro-fastapi-gpu:v0.2.1")},
    {"key": "piper", "display": "Piper", "version_label": "master", "version_command": "docker manifest inspect kamilkrawiec/piper-openai-tts:master >/dev/null 2>&1 && echo master || echo master", "install_command": lambda: _docker_install_script("piper", "Piper", PIPER_COMPOSE, data_dirs=[], image_hint="kamilkrawiec/piper-openai-tts:master")},
    {"key": "silly", "display": "SillyTavern", "version_label": "main", "version_command": "git ls-remote --heads https://github.com/SillyTavern/SillyTavern.git main >/dev/null 2>&1 && echo main || echo main", "install_command": _silly_install_script},
    {"key": "openwebui", "display": "Open WebUI", "version_label": "main", "version_command": "docker manifest inspect ghcr.io/open-webui/open-webui:main >/dev/null 2>&1 && echo main || echo main", "install_command": lambda: _docker_install_script("openwebui", "Open WebUI", OPEN_WEBUI_COMPOSE, data_dirs=[], image_hint="ghcr.io/open-webui/open-webui:main")},
]


def _status_color(installed):
    colors = settings_store.get_theme_colors()
    return colors["good"] if installed else colors["warn"]


def _center_on_services(manager, win, width=900, height=560):
    manager.root.update_idletasks()
    anchor = manager.overlay if getattr(manager, "overlay", None) is not None else manager.root
    x = anchor.winfo_rootx() + max(0, (anchor.winfo_width() - width) // 2)
    y = anchor.winfo_rooty() + max(0, (anchor.winfo_height() - height) // 2)
    win.geometry(f"{width}x{height}+{x}+{y}")


def open_installer_window(manager):
    ensure_base_install_folders(manager.write)
    colors = settings_store.get_theme_colors()
    backdrop = uihelpers.show_modal_backdrop(manager)
    win = tk.Toplevel(manager.root)
    win.overrideredirect(True)
    win.configure(bg=colors["text_bg"])
    _center_on_services(manager, win)
    win.transient(manager.root)
    # Keep the service manager above the main manager while it is open.
    # This is intentionally limited to this installer window.
    try:
        win.wm_attributes("-topmost", 1)
    except Exception:
        pass
    win.grab_set()

    def close_installer():
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

    try:
        win.bind("<Escape>", lambda _e: close_installer())
    except Exception:
        pass

    outer = tk.Frame(win, bg=colors["text_bg"], highlightbackground=colors["border"], highlightthickness=1)
    outer.pack(fill=tk.BOTH, expand=True)
    header = tk.Frame(outer, bg=colors["header_bg"])
    header.pack(fill=tk.X)
    tk.Label(header, text="Service manager", bg=colors["header_bg"], fg=colors["fg"], font=("Segoe UI", 14, "bold"), anchor="w", padx=12, pady=10).pack(side=tk.LEFT, fill=tk.X, expand=True)
    uihelpers.rounded_button(header, "CLOSE", close_installer, bg=colors["button_bad"], width=92, height=32).pack(side=tk.RIGHT, padx=10, pady=8)

    body = tk.Frame(outer, bg=colors["root_bg"])
    body.pack(fill=tk.BOTH, expand=True, padx=14, pady=12)
    tk.Label(body, text="Install or remove services. Installs are verified before they are enabled.", bg=colors["root_bg"], fg=colors["muted_fg"], font=("Segoe UI", 10), anchor="w").pack(fill=tk.X, pady=(0, 12))

    list_wrap = tk.Frame(body, bg=colors["panel_bg"])
    list_wrap.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
    canvas = tk.Canvas(list_wrap, bg=colors["panel_bg"], highlightthickness=0)
    scrollbar = tk.Scrollbar(list_wrap, orient="vertical", command=canvas.yview, bg="#2a2a2a", troughcolor=colors["root_bg"])
    rows = tk.Frame(canvas, bg=colors["panel_bg"], padx=10, pady=10)
    rows_id = canvas.create_window((0, 0), window=rows, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)
    canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
    rows.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
    canvas.bind("<Configure>", lambda e: canvas.itemconfigure(rows_id, width=e.width))

    status_labels = {}
    version_labels = {}
    action_buttons = {}
    progress_values = {}
    progress_last_line_bump = {}

    def widget_alive(widget):
        try:
            return bool(widget is not None and widget.winfo_exists())
        except Exception:
            return False

    def installed_for(key):
        try:
            return manager.is_service_installed(key)
        except Exception:
            return service_components.is_installed(manager, key)

    def set_progress(key, text, pct=None, color=None):
        # Keep the visible percent monotonic during a single install/uninstall.
        # Generic PROGRESS markers, Docker output, and parsed download percentages
        # can all update the same row without the bar jumping backwards.
        if pct is not None:
            try:
                pct = max(0, min(100, int(float(pct))))
                old = int(progress_values.get(key, 0))
                if pct < old and old < 100:
                    pct = old
                progress_values[key] = pct
            except Exception:
                pct = None
        label_text = text if pct is None else f"{text} {pct}%"

        def apply():
            label = status_labels.get(key)
            if widget_alive(label):
                try:
                    label.config(text=label_text, fg=color or colors["warn"])
                except tk.TclError:
                    pass

        try:
            manager.safe_ui(apply)
        except Exception:
            pass

    def bump_active_progress(key, text, cap):
        # Small generic activity bump for long commands with no real percent.
        # It is capped below the next known phase marker.
        now = time.time()
        if now - float(progress_last_line_bump.get(key, 0)) < 1.2:
            return
        progress_last_line_bump[key] = now
        cur = int(progress_values.get(key, 0))
        if cur < cap:
            set_progress(key, text, min(cap, cur + 1))

    def refresh_row(item):
        key = item["key"]
        if not widget_alive(version_labels.get(key)) or not widget_alive(status_labels.get(key)):
            return
        installed = installed_for(key)
        cached_versions = settings_store.get_service_versions()
        version_labels[key].config(text=f"V{cached_versions.get(key, item.get('version_label', 'latest'))}")
        status_labels[key].config(text="Installed" if installed else "Not installed", fg=_status_color(installed))
        install_cmd = item.get("install_command")
        btn = action_buttons.get(key)
        if btn is None:
            return
        if installed:
            btn.set_enabled(True, text="Uninstall", bg=colors["button_bad"])
            btn.command = lambda i=item: uninstall_item(i)
        elif not install_cmd:
            btn.set_enabled(False, text="Manual", bg=colors["accent"])
            btn.command = lambda: None
        else:
            btn.set_enabled(True, text="Install", bg=colors["button_good"])
            btn.command = lambda i=item: install_item(i)

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
                    manager.safe_ui(lambda k=key, v=first: version_labels[k].config(text=f"V{v}") if widget_alive(version_labels.get(k)) else None)
                except Exception:
                    pass
        threading.Thread(target=worker, daemon=True).start()

    def install_item(item):
        key = item["key"]
        display = item["display"]
        cmd_factory = item.get("install_command")
        if not cmd_factory:
            messagebox.showinfo("Manual install", f"{display} does not have an automatic installer yet.", parent=win)
            return
        action_buttons[key].set_enabled(False, text="Installing", bg=colors["button_warn"])
        set_progress(key, "Installing", 0)
        manager.write(f"[INSTALLER] Installing {display}...")

        def worker():
            try:
                ensure_base_install_folders(manager.write)
                cmd = cmd_factory() if callable(cmd_factory) else str(cmd_factory)
                manager.write(f"[INSTALLER] DEBUG: service={key}, target={service_target_dir(key)}", "system")
                wrapped = cmd.replace("\r\n", "\n").replace("\r", "\n") + "\necho __AI_MANAGER_INSTALL_OK__\nexit 0\n"
                # V40: Do NOT run installer scripts from /mnt/<drive>/cache.
                # Some Windows-mounted test drives can return: bash: ... Invalid argument.
                # Instead, send the script into WSL as base64, write it to /tmp on the
                # Linux filesystem, and execute it there. This avoids /mnt drive script
                # execution/read quirks while keeping useful debug output.
                # V41: avoid $tmp variables completely. On some Windows/WSL handoffs
                # the previous $tmp runner arrived blank, producing:
                #   bash: : No such file or directory
                # Write the script to a fixed explicit /tmp path with a quoted heredoc,
                # then run that explicit path. This keeps the script off /mnt/f and
                # removes the fragile variable expansion layer.
                import os, time, base64
                tmp_path = f"/tmp/ai_manager_installer_{key}_{os.getpid()}_{int(time.time())}.sh"
                # V42: write the script to /tmp through base64 instead of a heredoc.
                # The heredoc runner still allowed some $TARGET-style lines to be
                # eaten before the temp script ran on some Windows/WSL handoffs.
                # Base64 makes the script content opaque until it is inside WSL.
                encoded = base64.b64encode(wrapped.encode("utf-8")).decode("ascii")
                runner = (
                    f"printf %s {shlex.quote(encoded)} | base64 -d > {shlex.quote(tmp_path)}\n"
                    f"sed -i 's/\\r$//' {shlex.quote(tmp_path)} 2>/dev/null || true\n"
                    f"chmod 700 {shlex.quote(tmp_path)} 2>/dev/null || true\n"
                    f"echo '[INSTALLER_{key}] DEBUG: temp script={tmp_path}'\n"
                    f"bash {shlex.quote(tmp_path)}\n"
                    f"rc=$?\n"
                    f"if [ \"$rc\" = \"0\" ]; then rm -f {shlex.quote(tmp_path)} 2>/dev/null || true; else echo \"[INSTALLER_{key}] DEBUG: preserved failed temp script={tmp_path}\"; fi\n"
                    f"exit $rc\n"
                )
                manager.write(f"[INSTALLER] DEBUG: script={tmp_path}", "system")
                text_lines = []
                saw_pct = False
                last_download_pct = None

                def handle_install_line(raw):
                    nonlocal saw_pct, last_download_pct
                    line = str(raw).strip()
                    if not line or "Command [" in line:
                        return
                    text_lines.append(line)

                    if line.startswith("PROGRESS:"):
                        parts = line.split(":", 2)
                        if len(parts) >= 3:
                            try:
                                pct = int(float(parts[1]))
                            except Exception:
                                pct = None
                            msg = parts[2]
                            saw_pct = True
                            set_progress(key, msg, pct)
                        return

                    # Ollama's official installer prints its own download percent.
                    # Map it into the download phase instead of treating it as the
                    # whole install, so verify/config/start/API checks still show.
                    m = re.search(r'(?<![A-Za-z0-9_.-])(\d{1,3}(?:\.\d+)?)%\s*$', line)
                    if key == "ollama" and m:
                        try:
                            pct_float = max(0.0, min(100.0, float(m.group(1))))
                            mapped = 35 + int(round(pct_float * 0.23))  # 35..58
                            if last_download_pct != mapped:
                                last_download_pct = mapped
                                saw_pct = True
                                set_progress(key, "Downloading Ollama", mapped)
                        except Exception:
                            pass
                    elif key in ("xtts", "kokoro", "piper", "openwebui"):
                        cur = int(progress_values.get(key, 0))
                        if 30 <= cur < 74:
                            bump_active_progress(key, "Pulling Docker image", 74)
                        elif 25 <= cur < 34:
                            bump_active_progress(key, "Checking Docker", 34)

                    # Keep the terminal useful: show milestones, warnings, errors, and
                    # actionable debug lines, but hide noisy Docker layer/download/npm spam.
                    lower = line.lower()
                    noisy_fragments = (
                        " downloading ", " extracting ", " pulling fs layer", " waiting",
                        " already exists", " pull complete", " verifying checksum",
                        " download complete", " npm warn deprecated", "added ",
                    )
                    important_prefixes = (
                        "DEBUG:", "ERROR", "WARNING", "WARN", "__AI_MANAGER_INSTALL_OK__",
                        "Ollama", "XTTS", "Kokoro", "Piper", "Open WebUI", "SillyTavern",
                        "Image ", "Cloning ", "Installing ", "Creating ", "Enabling ",
                    )
                    important_contains = (
                        "installed successfully", "docker image ready", "api ready",
                        "compose", "final", "ready", "pulled", "pulling",
                    )
                    should_log = (
                        line.startswith(important_prefixes)
                        or any(token in lower for token in important_contains)
                    )
                    if any(token in lower for token in noisy_fragments) and not ("pulled" in lower or "error" in lower or "warning" in lower):
                        should_log = False
                    if line.startswith(f"[INSTALLER_{key}] SCRIPT:"):
                        should_log = False
                    if should_log:
                        manager.write(f"[INSTALLER] {line}")

                rc, text = manager.run_stream(runner, on_line=handle_install_line, timeout=1200)
                text = text or "\n".join(text_lines)
                if not saw_pct:
                    set_progress(key, "Verifying", 90)
                ok_marker = "__AI_MANAGER_INSTALL_OK__" in text and rc == 0
                if ok_marker and key in ("xtts", "kokoro", "piper", "openwebui", "silly"):
                    set_progress(key, "Writing files", 95)
                    try:
                        finalize_ok = finalize_docker_service_files(key, manager.write)
                        if not finalize_ok:
                            manager.write(f"[INSTALLER] ERROR[FINALIZE-001]: Python finalizer did not create compose file for {key}", "error")
                            ok_marker = False
                    except Exception as e:
                        manager.write(f"[INSTALLER] ERROR[FINALIZE-EXCEPTION]: {e}", "error")
                        ok_marker = False
                try:
                    manager.refresh_installed_services()
                    installed = manager.is_service_installed(key)
                except Exception:
                    installed = service_components.is_installed(manager, key)
                if ok_marker and installed:
                    enabled_default = service_components.SERVICE_HANDLERS.get(key, {}).get("default_enabled", True)
                    settings_store.set_service_enabled(key, enabled_default)
                    try:
                        manager.service_enabled[key] = bool(enabled_default)
                        manager.installed_services[key] = True
                        manager.last_service_snapshot = ""
                    except Exception:
                        pass
                    set_progress(key, "Installed", 100, colors["good"])
                    if key == "ollama":
                        manager.write(f"[INSTALLER] {display} installed successfully and API is ready.", "good")
                    elif key == "silly":
                        manager.write(f"[INSTALLER] {display} installed successfully in the webUI folder.", "good")
                    else:
                        manager.write(f"[INSTALLER] {display} installed successfully. Headless Docker image is pulled; service folder contains compose/config files.", "good")
                else:
                    settings_store.set_service_enabled(key, False)
                    try:
                        manager.service_enabled[key] = False
                        manager.installed_services[key] = False
                        manager.last_service_snapshot = ""
                    except Exception:
                        pass
                    set_progress(key, "Install failed", None, colors["error"])
                    manager.write(f"[INSTALLER] {display} install incomplete. Check Docker/WSL output above. Service was not enabled.", "warn")
            except Exception as e:
                settings_store.set_service_enabled(key, False)
                set_progress(key, "Install error", None, colors["error"])
                manager.write(f"[INSTALLER] ERROR[INSTALLER-EXCEPTION]: {e}", "error")
            try:
                manager.refresh_installed_services()
            except Exception:
                pass
            try:
                manager.schedule_global_refresh(2000, log=False)
            except Exception:
                pass
            manager.safe_ui(lambda i=item: refresh_row(i))
        threading.Thread(target=worker, daemon=True).start()

    def _run_script_with_progress(key, display, script, ok_marker, action_name, timeout=1200):
        """Run a WSL shell script from /tmp and stream PROGRESS markers to the row label."""
        import os, time, base64
        tmp_path = f"/tmp/ai_manager_{action_name}_{key}_{os.getpid()}_{int(time.time())}.sh"
        wrapped = script.replace("\r\n", "\n").replace("\r", "\n")
        encoded = base64.b64encode(wrapped.encode("utf-8")).decode("ascii")
        runner = (
            f"printf %s {shlex.quote(encoded)} | base64 -d > {shlex.quote(tmp_path)}\n"
            f"sed -i 's/\\r$//' {shlex.quote(tmp_path)} 2>/dev/null || true\n"
            f"chmod 700 {shlex.quote(tmp_path)} 2>/dev/null || true\n"
            f"echo '[INSTALLER_{key}] DEBUG: temp {action_name} script={tmp_path}'\n"
            f"bash {shlex.quote(tmp_path)}\n"
            f"rc=$?\n"
            f"if [ \"$rc\" = \"0\" ]; then rm -f {shlex.quote(tmp_path)} 2>/dev/null || true; else echo \"[INSTALLER_{key}] DEBUG: preserved failed temp script={tmp_path}\"; fi\n"
            f"exit $rc\n"
        )
        lines = []
        saw_progress = False

        def handle_uninstall_line(raw):
            nonlocal saw_progress
            line = str(raw).strip()
            if not line or "Command [" in line:
                return
            lines.append(line)
            if line.startswith("PROGRESS:"):
                parts = line.split(":", 2)
                if len(parts) >= 3:
                    try:
                        pct = int(float(parts[1]))
                    except Exception:
                        pct = None
                    saw_progress = True
                    set_progress(key, parts[2], pct)
                return
            lower = line.lower()
            if (
                line.startswith(("DEBUG:", "ERROR", "WARNING", "WARN", "__AI_MANAGER_UNINSTALL_OK__", "[OLLAMA]", "[XTTS", "[KOKORO", "[PIPER", "[OPENWEBUI", "[SILLY"))
                or "uninstalled" in lower
                or "removed" in lower
                or "verified" in lower
            ):
                manager.write(f"[INSTALLER] {line}")

        rc, text = manager.run_stream(runner, on_line=handle_uninstall_line, timeout=timeout)
        text = text or "\n".join(lines)
        if not saw_progress:
            set_progress(key, "Verifying", 90)
        return (ok_marker in text and rc == 0), text

    def uninstall_item(item):
        key = item["key"]
        display = item["display"]
        action_buttons[key].set_enabled(False, text="Uninstalling", bg=colors["button_warn"])
        set_progress(key, "Removing", 0)
        manager.write(f"[INSTALLER] Uninstalling {display}...")

        def worker():
            ok_marker = False
            try:
                uninstall_factory = item.get("uninstall_command")
                if uninstall_factory:
                    set_progress(key, "Preparing uninstall", 3)
                    script = uninstall_factory() if callable(uninstall_factory) else str(uninstall_factory)
                    ok_marker, _text = _run_script_with_progress(key, display, script, "__AI_MANAGER_UNINSTALL_OK__", "uninstaller", timeout=360)
                else:
                    set_progress(key, "Stopping", 20)
                    ok_marker = bool(service_components.uninstall_service(manager, key))
                set_progress(key, "Disabling", 65)
                settings_store.set_service_enabled(key, False)
                try:
                    manager.service_enabled[key] = False
                    manager.installed_services[key] = False
                    manager.last_service_snapshot = ""
                except Exception:
                    pass
                set_progress(key, "Refreshing", 85)
                try:
                    manager.refresh_installed_services()
                except Exception:
                    pass
                still_installed = installed_for(key)
                if ok_marker and not still_installed:
                    set_progress(key, "Removed", 100, colors["good"])
                    manager.write(f"[INSTALLER] {display} uninstall verified.", "good")
                elif not still_installed:
                    set_progress(key, "Removed", 100, colors["good"])
                    manager.write(f"[INSTALLER] {display} removed. No installed marker remains.", "good")
                else:
                    set_progress(key, "Remove failed", None, colors["error"])
                    manager.write(f"[INSTALLER] {display} uninstall did not verify. Check output above.", "warn")
            except Exception as e:
                set_progress(key, "Remove error", None, colors["error"])
                manager.write(f"[INSTALLER] ERROR[UNINSTALLER-EXCEPTION]: {e}", "error")
            try:
                manager.refresh_installed_services()
            except Exception:
                pass
            try:
                manager.schedule_global_refresh(2000, log=False)
            except Exception:
                pass
            manager.safe_ui(lambda i=item: refresh_row(i))
        threading.Thread(target=worker, daemon=True).start()

    header_row = tk.Frame(rows, bg=colors["header_bg"])
    header_row.pack(fill=tk.X, pady=(0, 6))
    # Wider status/action area keeps the titles centered over their controls.
    for col, weight in enumerate((3, 2, 3, 2)):
        header_row.grid_columnconfigure(col, weight=weight, uniform="install")
    for col, text in enumerate(("Service", "Version", "Status", "Action")):
        pad = (22, 6) if col == 3 else 6
        tk.Label(header_row, text=text, bg=colors["header_bg"], fg=colors["muted_fg"], font=("Segoe UI", 9, "bold"), anchor="center").grid(row=0, column=col, sticky="nsew", padx=pad, pady=6)

    for index, item in enumerate(SERVICE_CATALOG):
        row_bg = uihelpers.soft_row_bg(colors, index)
        row = tk.Frame(rows, bg=row_bg, highlightbackground=colors.get("border", "#303030"), highlightthickness=1)
        row.pack(fill=tk.X, pady=4)
        for col, weight in enumerate((3, 2, 3, 2)):
            row.grid_columnconfigure(col, weight=weight, uniform="install")
        tk.Label(row, text=item["display"], bg=row_bg, fg=colors["fg"], font=("Segoe UI", 11, "bold"), anchor="center").grid(row=0, column=0, sticky="nsew", padx=6, pady=4)
        version_labels[item["key"]] = tk.Label(row, text=f"V{item.get('version_label', 'latest')}", bg=row_bg, fg=colors["muted_fg"], font=("Consolas", 10), anchor="center")
        version_labels[item["key"]].grid(row=0, column=1, sticky="nsew", padx=6, pady=4)
        status_labels[item["key"]] = tk.Label(row, text="Checking", bg=row_bg, fg=colors["warn"], font=("Segoe UI", 10, "bold"), anchor="center")
        status_labels[item["key"]].grid(row=0, column=2, sticky="nsew", padx=6, pady=4)
        action_cell = tk.Frame(row, bg=row_bg)
        action_cell.grid(row=0, column=3, sticky="nsew", padx=(22, 6), pady=4)
        action_buttons[item["key"]] = uihelpers.rounded_button(action_cell, "Install", bg=colors["button_good"], width=128, height=32, font=("Segoe UI", 9, "bold"))
        action_buttons[item["key"]].pack(anchor="center")
        refresh_row(item)
