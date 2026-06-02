"""Service registry and start/stop layer for AI Server Manager V71.

The manager reads this registry dynamically. For future community services,
add the service handler here and add its installer entry in components/installer.py.

Priority levels:
    0 = core backends such as Ollama
    1 = reserved for model loading / future preloads
    2 = TTS / voice services
    3 = reserved for image models / generation services
    4 = UI/frontends such as SillyTavern and Open WebUI
"""

import time
import sys
import os
import shlex
from pathlib import Path

# =====================================================
# Paths / service constants
# =====================================================

def _to_wsl_path(path):
    r"""Return a WSL-safe path for the folder containing this manager.

    V24 makes this deliberately defensive because the project is meant to be
    portable between PCs and drive letters. It handles:
      E:\AI_SERVER
      E:/AI_SERVER
      /mnt/e/AI_SERVER
      //wsl.localhost/Ubuntu/mnt/e/AI_SERVER
    """
    raw = str(path).strip()
    try:
        if os.name == "nt":
            raw = os.path.abspath(raw)
    except Exception:
        pass
    raw = raw.replace('\\', '/')
    if raw.startswith('//wsl.localhost/') or raw.startswith('//wsl$/'):
        marker = '/mnt/'
        idx = raw.lower().find(marker)
        if idx >= 0:
            return raw[idx:]
    if len(raw) >= 3 and raw[1] == ':' and raw[2] == '/':
        drive = raw[0].lower()
        return f"/mnt/{drive}{raw[2:]}"
    return raw

def _unique(items):
    out = []
    seen = set()
    for item in items:
        item = str(item).replace('\\', '/').rstrip('/')
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


# components.py lives in AI_SERVER/components, so parent.parent is AI_SERVER.
LOCAL_AI_DIR = Path(__file__).resolve().parent.parent

# WSL path candidates. The first item is used for commands, but installed-service
# detection checks all candidates so the manager survives drive-letter moves and
# odd launch locations.
_candidate_paths = [LOCAL_AI_DIR]
try:
    if sys.argv and sys.argv[0]:
        _candidate_paths.append(Path(sys.argv[0]).resolve().parent)
except Exception:
    pass
try:
    _candidate_paths.append(Path.cwd().resolve())
except Exception:
    pass

AI_DIR_CANDIDATES = _unique(_to_wsl_path(p) for p in _candidate_paths)
AI_DIR = AI_DIR_CANDIDATES[0]
TTS_DIR = f"{AI_DIR}/TTS"
WEBUI_DIR = f"{AI_DIR}/webUI"

# V31: canonical service layout. Runtime start/stop commands must use these
# folders only, otherwise Docker bind mounts can silently recreate old folders
# like AI_SERVER/xtts after the project has been reorganized. Legacy folders
# are still detected for migration/install visibility, but not preferred for
# launching when the canonical folder exists.
def _canonical_wsl_path(relative_path):
    return _to_wsl_path(LOCAL_AI_DIR / relative_path)


def _local_service_path(new_relative, legacy_relative=None):
    """Find the service folder from Python's local filesystem view."""
    rels = [new_relative]
    if legacy_relative:
        rels.append(legacy_relative)
    for rel in rels:
        try:
            p = LOCAL_AI_DIR / rel
            if p.exists():
                return p
        except Exception:
            pass
    return LOCAL_AI_DIR / new_relative


def _local_exists(relative_path):
    try:
        return (LOCAL_AI_DIR / relative_path).exists()
    except Exception:
        return False


def _service_dir(new_relative, legacy_relative):
    """Return the canonical WSL service folder, falling back only if needed.

    V31 fixes a relocation bug where legacy paths such as AI_SERVER/xtts could
    be reused or recreated after the new layout was introduced. If the new
    folder exists, it always wins.
    """
    try:
        canonical = LOCAL_AI_DIR / new_relative
        if canonical.exists():
            return _to_wsl_path(canonical)
        if legacy_relative:
            legacy = LOCAL_AI_DIR / legacy_relative
            if legacy.exists():
                return _to_wsl_path(legacy)
        return _to_wsl_path(canonical)
    except Exception:
        return _canonical_wsl_path(new_relative)


def _has_compose_file_local(path):
    try:
        p = Path(path)
        return any((p / name).exists() for name in ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml"))
    except Exception:
        return False


def local_installed_snapshot():
    """Fast local installed-service check used by the manager UI.

    This is intentionally not based on WSL commands, so the Services window can
    populate even when Docker/WSL is slow. Runtime health is checked separately.
    """
    xtts = _local_service_path("TTS/xtts", "xtts")
    kokoro = _local_service_path("TTS/kokoro", "kokoro")
    piper = _local_service_path("TTS/piper", "piper")
    silly = _local_service_path("webUI/sillytavern", "sillytavern")
    openwebui = _local_service_path("webUI/open-webui", "open-webui")
    return {
        # Do not treat a bare local "ollama" folder as installed.
        # Ollama is installed system-wide in WSL; the real check is command/systemd.
        "ollama": False,
        "xtts": _has_compose_file_local(xtts),
        "kokoro": _has_compose_file_local(kokoro),
        "piper": _has_compose_file_local(piper),
        "silly": bool((silly / "package.json").exists()) or silly.exists(),
        "openwebui": _has_compose_file_local(openwebui),
    }


SILLY_DIR = _service_dir("webUI/sillytavern", "sillytavern")
XTTS_DIR = _service_dir("TTS/xtts", "xtts")
OPEN_WEBUI_DIR = _service_dir("webUI/open-webui", "open-webui")
KOKORO_DIR = _service_dir("TTS/kokoro", "kokoro")
PIPER_DIR = _service_dir("TTS/piper", "piper")

SUDO_ERROR_TEXT = "SUDO ACCESS NOT GIVEN! Go to settings to fix."

# =====================================================
# Small shared helpers
# =====================================================


def _q(value):
    return shlex.quote(str(value))


def _gpu_value(manager, kind):
    try:
        gpu = getattr(manager, "gpu_settings", {}) or {}
        key = "llm_gpu" if kind == "llm" else "tts_gpu"
        return str(gpu.get(key, "")).strip()
    except Exception:
        return ""


def _gpu_prefix(manager, kind):
    value = _gpu_value(manager, kind)
    if not value:
        return ""
    if kind == "tts":
        return f'export CUDA_VISIBLE_DEVICES="{value}"; export NVIDIA_VISIBLE_DEVICES="{value}"; '
    return f'export CUDA_VISIBLE_DEVICES="{value}"; '


def _docker_compose_up_command(display, service_tag, folder):
    """Return a quick, detached compose start command using headless Docker Engine."""
    return f'''
echo "[{service_tag}] Starting {display} using headless Docker compose..."
cd {_q(folder)} || {{ echo "[{service_tag}] ERROR[20]: folder missing: {folder}"; exit 20; }}

docker_cmd() {{
  if docker info >/dev/null 2>&1; then docker "$@"; elif sudo -n docker info >/dev/null 2>&1; then sudo -n docker "$@"; else
    echo "[{service_tag}] ERROR[81]: Headless Docker Engine is not reachable from WSL."; exit 81;
  fi
}}

if [ ! -f docker-compose.yml ] && [ ! -f docker-compose.yaml ] && [ ! -f compose.yml ] && [ ! -f compose.yaml ]; then
  echo "[{service_tag}] ERROR[82]: No docker compose file found in {folder}."; exit 82;
fi
echo "[{service_tag}] DEBUG: using folder: $(pwd)"
echo "[{service_tag}] DEBUG: compose services: $(docker_cmd compose config --services 2>/dev/null | paste -sd ' ' -)"
if ! docker_cmd compose up -d --remove-orphans; then rc=$?; echo "[{service_tag}] ERROR[83]: docker compose up failed with exit code $rc."; exit $rc; fi
echo "[{service_tag}] Compose start command complete. Waiting for live health check..."
'''

def _compose_down(manager, display, folder, container_patterns=None, force=False):
    """Stop a compose service hard enough to release VRAM.

    V30 uses the compose project itself first, then force-removes any matching
    leftover containers. This is intentionally stronger than a normal down
    because TTS containers can keep CUDA memory allocated after a soft stop.
    It does not remove volumes, so downloaded models/data are preserved.
    """
    manager.write(f'[{display}] Stopping docker compose stack...')
    container_patterns = container_patterns or []
    pat = "|".join(container_patterns) if container_patterns else ""
    qfolder = _q(folder)

    # Disable restart policies on containers from this compose project.
    manager.run_shell(
        f"cd {qfolder} && sudo -n docker compose ps -q 2>/dev/null | "
        "xargs -r sudo -n docker update --restart=no >/dev/null 2>&1 || true",
        timeout=12,
    )
    if pat:
        manager.run_shell(
            f"sudo -n docker ps -a --format '{{{{.Names}}}}' | grep -E {shlex.quote(pat)} | "
            "xargs -r sudo -n docker update --restart=no >/dev/null 2>&1 || true",
            timeout=12,
        )

    # Kill first for GPU/TTS services: stop can wait while CUDA context remains alive.
    manager.run_shell(
        f"cd {qfolder} && sudo -n docker compose ps -q 2>/dev/null | "
        "xargs -r sudo -n docker kill >/dev/null 2>&1 || true",
        timeout=15,
    )
    manager.run_shell(f"cd {qfolder} && sudo -n docker compose stop -t 2 >/dev/null 2>&1 || true", timeout=18)
    manager.run_shell(f"cd {qfolder} && sudo -n docker compose down --remove-orphans --timeout 2 >/dev/null 2>&1 || true", timeout=35)

    # Force-remove anything left behind from the project or by known names.
    manager.run_shell(
        f"cd {qfolder} && sudo -n docker compose ps -aq 2>/dev/null | "
        "xargs -r sudo -n docker rm -f >/dev/null 2>&1 || true",
        timeout=15,
    )
    if pat:
        manager.run_shell(
            f"sudo -n docker ps -a --format '{{{{.Names}}}}' | grep -E {shlex.quote(pat)} | "
            "xargs -r sudo -n docker rm -f >/dev/null 2>&1 || true",
            timeout=20,
        )

    # Give Docker/NVIDIA a moment to release the CUDA context.
    time.sleep(2)

    still_running = False
    if pat:
        check = manager.run_capture(
            f"sudo -n docker ps --format '{{{{.Names}}}}' | grep -E {shlex.quote(pat)} || true",
            timeout=8,
        )
        still_running = bool(str(check).strip())

    if still_running:
        manager.write(f'[{display}] WARNING: Container still running after force stop.', 'warn')

def _docker_container_running(manager, pattern):
    return manager.docker_ok(f"ps --format '{{{{.Names}}}}' | grep -E '{pattern}' >/dev/null 2>&1")


def _folder_has_compose(manager, folder):
    return manager.service_ok(
        f"[ -d {folder!r} ] && "
        f"([ -f {folder!r}/docker-compose.yml ] || [ -f {folder!r}/docker-compose.yaml ] || "
        f"[ -f {folder!r}/compose.yml ] || [ -f {folder!r}/compose.yaml ])"
    )


def _folder_exists(manager, folder):
    return manager.service_ok(f"[ -d {folder!r} ]")


def _rm_folder(manager, display, folder):
    manager.write(f'[{display}] Removing folder: {folder}')
    manager.run_shell(f"rm -rf {folder!r}", timeout=30)


# =====================================================
# Ollama service - priority 0
# =====================================================

OLLAMA_RUN = "\nOLLAMA_BASE=" + _q(AI_DIR + "/ollama") + """
echo "[OLLAMA] Checking Ollama..."
echo "[OLLAMA] DEBUG: command=$(command -v ollama 2>/dev/null || echo missing)"
echo "[OLLAMA] DEBUG: WSL pwd=$(pwd), user=$(whoami)"
# Reinstall/self-heal safety. If Ollama was uninstalled and reinstalled in the
# same WSL session, the ollama user can exist while /usr/share/ollama was
# removed or recreated as root. Fix ownership before starting systemd.
if id ollama >/dev/null 2>&1; then
  sudo -n mkdir -p /usr/share/ollama /var/lib/ollama "$OLLAMA_BASE/models" >/dev/null 2>&1 || true
  sudo -n chown -R ollama:ollama /usr/share/ollama /var/lib/ollama "$OLLAMA_BASE" >/dev/null 2>&1 || true
fi
sudo -n systemctl reset-failed ollama >/dev/null 2>&1 || true
if ! command -v curl >/dev/null 2>&1; then echo "[OLLAMA] ERROR[87]: curl executable not found."; exit 87; fi
if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
  echo "[OLLAMA] Already running."
  exit 0
fi

if ! command -v systemctl >/dev/null 2>&1; then echo "[OLLAMA] ERROR[87]: systemctl executable not found."; exit 87; fi
if ! command -v sudo >/dev/null 2>&1; then echo "[OLLAMA] ERROR[87]: sudo executable not found."; exit 87; fi

echo "[OLLAMA] Starting Ollama with systemd..."
sudo -n systemctl start ollama
rc=$?
if [ "$rc" != "0" ]; then
  echo "[OLLAMA] ERROR[86]: sudo/systemctl start failed with exit code $rc. Check Settings > Sudo Access."
  sudo -n systemctl status ollama --no-pager 2>&1 | tail -n 20 || true
  exit 86
fi

for i in {1..90}; do
  if curl -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1; then
    echo "[OLLAMA] Ollama API ready."
    exit 0
  fi
  sleep 0.5
done

echo "[OLLAMA] ERROR[94]: Ollama service started but API did not answer in time."
sudo -n systemctl status ollama --no-pager 2>&1 | tail -n 30 || true
journalctl -u ollama -n 30 --no-pager 2>&1 || true
exit 94
"""



def start_ollama(manager):
    return manager.run_logged("OLLAMA", _gpu_prefix(manager, "llm") + OLLAMA_RUN)


def running_ollama(manager):
    # V29: monitor uses simple API checks. If the endpoint responds, the service is usable.
    return manager.service_ok("curl -m 0.8 -fsS http://127.0.0.1:11434/api/tags >/dev/null 2>&1")
def installed_ollama(manager):
    # V59: systemctl list-unit-files can return success even when no matching
    # unit is listed, so grep for the actual unit name. A bare ollama folder
    # must never count as installed.
    return manager.service_ok("command -v ollama >/dev/null 2>&1 || systemctl list-unit-files ollama.service --no-legend 2>/dev/null | grep -q '^ollama.service'")


def stop_ollama(manager, force=False):
    return manager.stop_ollama(force=force)


def force_stop_ollama(manager):
    return manager.stop_ollama(force=True)


def ollama_uninstall_script():
    """Return the real Ollama uninstall script used by Add Service and service handlers.

    V59: removes the old placeholder. The script uses only manager-approved
    sudo commands (systemctl, pkill, rm) and prints PROGRESS markers so the
    Add/remove service window can update its status label during uninstall.
    """
    base = _q(f"{AI_DIR}/ollama")
    return f"""#!/usr/bin/env bash
set +e

OLLAMA_BASE={base}
API_URL="http://127.0.0.1:11434/api/tags"

echo "[OLLAMA] DEBUG: uninstall base=$OLLAMA_BASE"
echo "PROGRESS:5:Checking sudo permissions"

need_sudo=0
if ! sudo -n systemctl --version >/dev/null 2>&1; then
  echo "[OLLAMA] ERROR[UNINSTALL-SUDO-001]: sudo systemctl is not allowed. Open Settings > Sudo Access and run setup again."
  need_sudo=1
fi
if ! sudo -n rm --version >/dev/null 2>&1; then
  echo "[OLLAMA] ERROR[UNINSTALL-SUDO-002]: sudo rm is not allowed. Open Settings > Sudo Access and run setup again."
  need_sudo=1
fi
if [ "$need_sudo" != "0" ]; then
  exit 86
fi

echo "PROGRESS:12:Stopping Ollama service"
sudo -n systemctl stop ollama >/dev/null 2>&1 || true
sudo -n systemctl kill ollama >/dev/null 2>&1 || true
sudo -n pkill -TERM -f '/usr/local/bin/ollama' >/dev/null 2>&1 || true
sudo -n pkill -TERM -f '/usr/bin/ollama' >/dev/null 2>&1 || true
sudo -n pkill -TERM -f 'ollama runner' >/dev/null 2>&1 || true
sudo -n pkill -TERM -f 'ollama serve' >/dev/null 2>&1 || true
sleep 1
if curl -m 0.8 -fsS "$API_URL" >/dev/null 2>&1; then
  echo "[OLLAMA] DEBUG: API still answered after TERM; using SIGKILL."
  sudo -n pkill -9 -f '/usr/local/bin/ollama' >/dev/null 2>&1 || true
  sudo -n pkill -9 -f '/usr/bin/ollama' >/dev/null 2>&1 || true
  sudo -n pkill -9 -f 'ollama runner' >/dev/null 2>&1 || true
  sudo -n pkill -9 -f 'ollama serve' >/dev/null 2>&1 || true
  sleep 1
fi

echo "PROGRESS:25:Disabling Ollama autostart"
sudo -n systemctl disable ollama >/dev/null 2>&1 || true

echo "PROGRESS:38:Removing systemd service files"
sudo -n systemctl disable --now ollama >/dev/null 2>&1 || true
sudo -n rm -f /etc/systemd/system/ollama.service >/dev/null 2>&1 || true
sudo -n rm -rf /etc/systemd/system/ollama.service.d >/dev/null 2>&1 || true
sudo -n rm -f /etc/systemd/system/multi-user.target.wants/ollama.service >/dev/null 2>&1 || true
sudo -n rm -f /etc/systemd/user/ollama.service >/dev/null 2>&1 || true
sudo -n rm -rf /etc/systemd/user/ollama.service.d >/dev/null 2>&1 || true
sudo -n systemctl daemon-reload >/dev/null 2>&1 || true
sudo -n systemctl reset-failed ollama >/dev/null 2>&1 || true

echo "PROGRESS:52:Removing Ollama binaries"
sudo -n rm -f /usr/local/bin/ollama >/dev/null 2>&1 || true
sudo -n rm -f /usr/bin/ollama >/dev/null 2>&1 || true
sudo -n rm -f /bin/ollama >/dev/null 2>&1 || true
hash -r 2>/dev/null || true

echo "PROGRESS:68:Removing Ollama libraries and service data"
sudo -n rm -rf /usr/local/lib/ollama >/dev/null 2>&1 || true
sudo -n rm -rf /usr/share/ollama >/dev/null 2>&1 || true
sudo -n rm -rf /var/lib/ollama >/dev/null 2>&1 || true
sudo -n rm -f /tmp/ollama-install.sh >/dev/null 2>&1 || true

echo "PROGRESS:82:Removing portable Ollama model folder"
if [ -n "$OLLAMA_BASE" ] && [ "$OLLAMA_BASE" != "/" ] && [ "$OLLAMA_BASE" != "/mnt" ]; then
  case "$OLLAMA_BASE" in
    *".."*) echo "[OLLAMA] ERROR[UNINSTALL-PATH-001]: refusing unsafe path: $OLLAMA_BASE"; exit 20 ;;
    /mnt/*/ollama|*/ollama) rm -rf "$OLLAMA_BASE" >/dev/null 2>&1 || sudo -n rm -rf "$OLLAMA_BASE" >/dev/null 2>&1 || true ;;
    *) echo "[OLLAMA] DEBUG: portable folder path did not look like an ollama folder; skipped: $OLLAMA_BASE" ;;
  esac
fi

echo "PROGRESS:92:Verifying removal"
fail=0
if command -v ollama >/dev/null 2>&1; then
  echo "[OLLAMA] ERROR[UNINSTALL-VERIFY-001]: ollama command still exists at $(command -v ollama)."
  fail=1
fi
if systemctl list-unit-files ollama.service --no-legend 2>/dev/null | grep -q '^ollama.service'; then
  echo "[OLLAMA] ERROR[UNINSTALL-VERIFY-002]: ollama.service is still registered."
  fail=1
fi
if curl -m 0.8 -fsS "$API_URL" >/dev/null 2>&1; then
  echo "[OLLAMA] ERROR[UNINSTALL-VERIFY-003]: Ollama API is still responding."
  fail=1
fi
if [ -d "$OLLAMA_BASE" ]; then
  echo "[OLLAMA] ERROR[UNINSTALL-VERIFY-004]: portable folder still exists: $OLLAMA_BASE"
  fail=1
fi
if [ -e /usr/share/ollama ] || [ -e /var/lib/ollama ] || [ -e /usr/local/lib/ollama ]; then
  echo "[OLLAMA] ERROR[UNINSTALL-VERIFY-005]: one or more Ollama data/library folders still exist."
  ls -ld /usr/share/ollama /var/lib/ollama /usr/local/lib/ollama 2>&1 || true
  fail=1
fi

if [ "$fail" != "0" ]; then
  echo "PROGRESS:100:Ollama removal needs attention"
  echo "[OLLAMA] Uninstall incomplete. Check the errors above."
  exit 91
fi

echo "PROGRESS:100:Ollama removed"
echo "[OLLAMA] Fully uninstalled."
echo "__AI_MANAGER_UNINSTALL_OK__"
exit 0
"""


def uninstall_ollama(manager):
    manager.write("[OLLAMA] Starting full Ollama uninstall...")
    script = ollama_uninstall_script()
    try:
        output = manager.run_capture(script, timeout=120)
    except Exception as e:
        manager.write(f"[OLLAMA] Uninstall failed before script output: {e}", "error")
        return False
    text = str(output or "")
    for raw in text.splitlines():
        line = raw.strip()
        if not line or "Command [" in line:
            continue
        if line.startswith("PROGRESS:"):
            parts = line.split(":", 2)
            if len(parts) >= 3:
                manager.write(f"[OLLAMA] {parts[2]} ({parts[1]}%)")
            continue
        manager.write(line if line.startswith("[OLLAMA]") else f"[OLLAMA] {line}")
    ok = "__AI_MANAGER_UNINSTALL_OK__" in text and not installed_ollama(manager)
    if ok:
        manager.write("[OLLAMA] Full uninstall verified.", "good")
    else:
        manager.write("[OLLAMA] Full uninstall did not verify cleanly.", "warn")
    return ok


# =====================================================
# XTTS2 service - priority 2
# =====================================================


def _xtts_compose_repair_prefix():
    r"""Shell preflight that prevents Docker from recreating AI_SERVER/xtts.

    V32 hardens the V31 repair. The previous repair could be broken by Python
    string escaping and could still allow Docker to create the old root xtts
    folder. This preflight repairs obvious legacy bind mounts, then refuses to
    start XTTS if a root-level AI_SERVER/xtts bind path is still present.
    """
    canonical = _q(XTTS_DIR)
    legacy_root = _q(f"{AI_DIR}/xtts")
    return fr"""
XTTS_CANONICAL={canonical}
XTTS_LEGACY={legacy_root}
mkdir -p "$XTTS_CANONICAL/voices" "$XTTS_CANONICAL/output" "$XTTS_CANONICAL/models" "$XTTS_CANONICAL/cache" >/dev/null 2>&1 || true
cd "$XTTS_CANONICAL" || {{ echo "[XTTS] ERROR[20]: folder missing: {XTTS_DIR}"; exit 20; }}
compose_file=""
for f in docker-compose.yml docker-compose.yaml compose.yml compose.yaml; do
  if [ -f "$f" ]; then compose_file="$f"; break; fi
done

if [ -n "$compose_file" ]; then
  echo "[XTTS] DEBUG: compose file: $compose_file"
  cp "$compose_file" "$compose_file.v32-last-check" 2>/dev/null || true
  python3 - "$compose_file" "$XTTS_CANONICAL" "$XTTS_LEGACY" <<'PYFIX'
from pathlib import Path
import re
import sys
path = Path(sys.argv[1])
canonical = sys.argv[2].rstrip('/')
legacy = sys.argv[3].rstrip('/')
text = path.read_text(encoding='utf-8', errors='replace')
original = text

replacements = {{
    '../../xtts': '.',
    '..\\..\\xtts': '.',
    '../AI_SERVER/xtts': '.',
    legacy: canonical,
    legacy.replace('/', '\\'): canonical,
}}
for old, new in replacements.items():
    text = text.replace(old, new)

text = re.sub(r'/mnt/([A-Za-z])/AI_SERVER/xtts', canonical, text)
text = re.sub(r'[A-Za-z]:[\\/]+AI_SERVER[\\/]+xtts', canonical, text)
text = text.replace('${{AI_DIR}}/xtts', canonical)
text = text.replace('$AI_DIR/xtts', canonical)
text = text.replace('${{AI_SERVER}}/xtts', canonical)
text = text.replace('$AI_SERVER/xtts', canonical)

text = text.replace('\\r\\n', '\\n').replace('\\r', '\\n')
if text != original:
    backup = path.with_name(path.name + '.v32-backup')
    try:
        backup.write_text(original.replace('\\r\\n', '\\n').replace('\\r', '\\n'), encoding='utf-8')
    except Exception:
        pass
    path.write_text(text, encoding='utf-8')
    print(f"[XTTS] DEBUG: repaired legacy XTTS compose paths in {{path.name}}. Backup: {{backup.name}}")
PYFIX

  if grep -nE '(\.\./\.\./xtts|/AI_SERVER/xtts|/mnt/[a-zA-Z]/AI_SERVER/xtts|[A-Za-z]:[\/]+AI_SERVER[\/]+xtts|\$\{{0,1\}}AI_DIR\}}?/xtts|\$\{{0,1\}}AI_SERVER\}}?/xtts)' "$compose_file" >/tmp/ai-manager-xtts-legacy-lines.txt 2>/dev/null; then
    echo "[XTTS] ERROR[97]: compose file still references old root-level AI_SERVER/xtts path. XTTS start blocked to prevent recreating that folder."
    sed 's/^/[XTTS] ERROR[97] compose line: /' /tmp/ai-manager-xtts-legacy-lines.txt | head -20
    echo "[XTTS] Fix the compose volume paths to use ./voices, ./output, ./models, ./cache, or the canonical folder: $XTTS_CANONICAL"
    exit 97
  fi
fi

if [ -d "$XTTS_LEGACY" ] && [ "$XTTS_LEGACY" != "$XTTS_CANONICAL" ]; then
  echo "[XTTS] WARNING: old root-level XTTS folder exists but will not be used: $XTTS_LEGACY"
fi
"""

XTTS_RUN = _xtts_compose_repair_prefix() + _docker_compose_up_command("XTTS2", "XTTS", XTTS_DIR)

_XTTS_Q = _q(XTTS_DIR)
WARMUP_XTTS = f"""
echo "[WARMUP] Waiting briefly for XTTS model..."
mkdir -p {_XTTS_Q}/output >/dev/null 2>&1 || true

ready=0
for i in {{1..45}}; do
  if curl -fsS http://127.0.0.1:8020/speakers >/dev/null 2>&1; then
    ready=1
    break
  fi
  if curl -fsS http://127.0.0.1:8020/docs >/dev/null 2>&1; then
    ready=1
    break
  fi
  if curl -fsS http://127.0.0.1:8020/openapi.json >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 1
done

if [ "$ready" != "1" ]; then
  echo "[WARMUP] WARNING: XTTS API did not become reachable for warmup. Startup will continue."
  exit 0
fi

echo "[WARMUP] XTTS API reachable."
echo "[WARMUP] Pre-loading XTTS voice/model..."
if ! curl -s -X POST "http://127.0.0.1:8020/tts_to_audio/" \
  -H "Content-Type: application/json" \
  -d '{{"text":"Ready.","speaker_wav":"Female_v3","language":"en"}}' \
  --output {_XTTS_Q}/output/warmup.wav >/dev/null 2>&1; then
  echo "[WARMUP] WARNING: XTTS API reachable, but warmup request failed."
else
  echo "[WARMUP] XTTS warmup complete."
fi
"""

def start_xtts(manager):
    proc = manager.run_logged("XTTS", _gpu_prefix(manager, "tts") + XTTS_RUN)
    if proc is None:
        manager.write("[XTTS2] Start command could not be launched. Warmup skipped.")
        return None

    def warmup_later():
        # Background warmup only; never blocks the launch queue.
        time.sleep(6)
        try:
            out = manager.run_capture(WARMUP_XTTS, timeout=70)
            for line in str(out).splitlines():
                stripped = line.strip()
                if stripped and "Command [" not in stripped:
                    manager.write(stripped)
        except Exception as e:
            manager.write(f"[WARMUP] WARNING: XTTS warmup helper did not finish cleanly: {e}", "warn")

    try:
        import threading
        threading.Thread(target=warmup_later, daemon=True).start()
    except Exception:
        pass
    return proc


def running_xtts(manager):
    return (
        manager.service_ok("curl -m 0.8 -fsS http://127.0.0.1:8020/speakers >/dev/null 2>&1") or
        manager.service_ok("curl -m 0.8 -fsS http://127.0.0.1:8020/docs >/dev/null 2>&1") or
        manager.service_ok("curl -m 0.8 -fsS http://127.0.0.1:8020/openapi.json >/dev/null 2>&1")
    )
def installed_xtts(manager):
    return _folder_has_compose(manager, XTTS_DIR)


def stop_xtts(manager, force=False):
    return _compose_down(manager, "XTTS2", XTTS_DIR, ["xtts|xtts-api-server|xtts2|tts"], force=force)


def force_stop_xtts(manager):
    return stop_xtts(manager, force=True)


def uninstall_xtts(manager):
    stop_xtts(manager, force=True)
    _rm_folder(manager, "XTTS2", XTTS_DIR)


# =====================================================
# Kokoro service - priority 2
# =====================================================

KOKORO_RUN = _docker_compose_up_command("Kokoro", "KOKORO", KOKORO_DIR)


def start_kokoro(manager):
    return manager.run_logged("KOKORO", _gpu_prefix(manager, "tts") + KOKORO_RUN)


def running_kokoro(manager):
    return (
        manager.service_ok("curl -m 0.8 -fsS http://127.0.0.1:8880/docs >/dev/null 2>&1") or
        manager.service_ok("curl -m 0.8 -fsS http://127.0.0.1:8880/openapi.json >/dev/null 2>&1") or
        manager.service_ok("curl -m 0.8 -fsS http://127.0.0.1:8880/v1/audio/voices >/dev/null 2>&1")
    )
def installed_kokoro(manager):
    return _folder_has_compose(manager, KOKORO_DIR)


def stop_kokoro(manager, force=False):
    return _compose_down(manager, "KOKORO", KOKORO_DIR, ["kokoro|kokoro-fastapi|kokoro-api"], force=force)


def force_stop_kokoro(manager):
    return stop_kokoro(manager, force=True)


def uninstall_kokoro(manager):
    stop_kokoro(manager, force=True)
    _rm_folder(manager, "KOKORO", KOKORO_DIR)


# =====================================================
# Piper service - priority 2
# =====================================================

PIPER_RUN = _docker_compose_up_command("Piper", "PIPER", PIPER_DIR)


def start_piper(manager):
    return manager.run_logged("PIPER", _gpu_prefix(manager, "tts") + PIPER_RUN)


def running_piper(manager):
    return (
        manager.service_ok("curl -m 0.8 -fsS http://127.0.0.1:5000/docs >/dev/null 2>&1") or
        manager.service_ok("curl -m 0.8 -fsS http://127.0.0.1:5000/openapi.json >/dev/null 2>&1") or
        manager.service_ok("curl -m 0.8 -fsS http://127.0.0.1:5000/v1/audio/speech -o /dev/null >/dev/null 2>&1")
    )
def installed_piper(manager):
    return _folder_has_compose(manager, PIPER_DIR)


def stop_piper(manager, force=False):
    return _compose_down(manager, "PIPER", PIPER_DIR, ["piper-openai-tts|piper|piper-api|piper-tts"], force=force)


def force_stop_piper(manager):
    return stop_piper(manager, force=True)


def uninstall_piper(manager):
    stop_piper(manager, force=True)
    _rm_folder(manager, "PIPER", PIPER_DIR)


# =====================================================
# SillyTavern service - priority 4
# =====================================================

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
    ports:
      - "8000:8000"
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

SILLY_RUN = f"""
echo "[SILLYTAVERN] Starting SillyTavern..."
echo "[SILLYTAVERN] V71 uses the headless Docker container path with root config.yaml repair."
cd {_q(SILLY_DIR)} || {{ echo "[SILLYTAVERN] ERROR[20]: folder not found: {SILLY_DIR}"; exit 20; }}

# Self-heal older source installs from V65: if package.json exists but compose
# does not, write a compose file into the same webUI/sillytavern folder.
if [ ! -f docker-compose.yml ] && [ -f package.json ]; then
  echo "[SILLYTAVERN] DEBUG: legacy source install detected; writing Docker compose wrapper."
  cat > docker-compose.yml <<'EOF'
services:
  sillytavern:
    image: ghcr.io/sillytavern/sillytavern:latest
    container_name: sillytavern
    restart: unless-stopped
    ports:
      - "8000:8000"
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
EOF
fi

if [ -f docker-compose.yml ] || [ -f docker-compose.yaml ] || [ -f compose.yml ] || [ -f compose.yaml ]; then
  docker_cmd() {{
    if docker info >/dev/null 2>&1; then docker "$@"; elif sudo -n docker info >/dev/null 2>&1; then sudo -n docker "$@"; else
      echo "[SILLYTAVERN] ERROR[81]: Headless Docker Engine is not reachable from WSL."; exit 81;
    fi
  }}
  echo "[SILLYTAVERN] Checking SillyTavern Docker compose/config repair..."
  rewrite_needed=0
  if [ ! -f config.yaml ]; then
    echo "[SILLYTAVERN] DEBUG: config.yaml missing; will write safe local config."
    rewrite_needed=1
  elif ! grep -q "^whitelistMode: true" config.yaml 2>/dev/null || ! grep -q "^enableForwardedWhitelist: true" config.yaml 2>/dev/null || ! grep -q "172.16.0.0/12" config.yaml 2>/dev/null || ! grep -q "^listen: true" config.yaml 2>/dev/null; then
    echo "[SILLYTAVERN] DEBUG: config.yaml is missing required local/Docker whitelist settings; will repair config."
    rewrite_needed=1
  fi
  if ! grep -q "./config.yaml:/home/node/app/config.yaml" docker-compose.yml 2>/dev/null; then
    echo "[SILLYTAVERN] DEBUG: compose missing root config.yaml bind mount; will repair compose."
    rewrite_needed=1
  fi
  if grep -Eq "SILLYTAVERN_WHITELIST=false|SILLYTAVERN_LISTEN=true|/home/node/app/config$|sillytavern-config" docker-compose.yml 2>/dev/null; then
    echo "[SILLYTAVERN] DEBUG: old/insecure compose settings detected; will repair compose."
    rewrite_needed=1
  fi

  if [ "$rewrite_needed" = "1" ]; then
    echo "[SILLYTAVERN] Repairing compose/config before start..."
    docker_cmd compose down >/dev/null 2>&1 || true
    cat > config.yaml <<'EOF'
listen: true
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
EOF
    cat > docker-compose.yml <<'EOF'
services:
  sillytavern:
    image: ghcr.io/sillytavern/sillytavern:latest
    container_name: sillytavern
    restart: unless-stopped
    ports:
      - "8000:8000"
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
EOF
  fi

  echo "[SILLYTAVERN] Starting using Docker compose..."
  echo "[SILLYTAVERN] DEBUG: compose services: $(docker_cmd compose config --services 2>/dev/null | paste -sd ' ' -)"
  if ! docker_cmd compose up -d --remove-orphans; then rc=$?; echo "[SILLYTAVERN] ERROR[83]: docker compose up failed with exit code $rc."; exit $rc; fi

  # Wait until the container is actually running and not restarting, then confirm port 8000 is reachable.
  restart_note=0
  for i in $(seq 1 60); do
    state=$(docker_cmd inspect sillytavern --format 'status={{.State.Status}} restarting={{.State.Restarting}} exit={{.State.ExitCode}}' 2>/dev/null || true)
    case "$state" in
      *"status=running"*"restarting=false"*)
        code=$(curl -m 1.5 -s -o /dev/null -w "%{{http_code}}" http://127.0.0.1:8000/ 2>/dev/null || true)
        if [ -n "$code" ] && [ "$code" != "000" ]; then
          echo "[SILLYTAVERN] HTTP ready with status $code."
          echo "[SILLYTAVERN] Compose start command complete. Waiting for live health check..."
          exit 0
        fi
        ;;
      *"restarting=true"*)
        if [ "$restart_note" = "0" ] || [ $((i - restart_note)) -ge 10 ]; then
          restart_note=$i
          echo "[SILLYTAVERN] WARNING: container is restarting; waiting before checking logs."
        fi
        ;;
    esac
    sleep 1
  done

  echo "[SILLYTAVERN] ERROR[94]: container did not become healthy on port 8000."
  docker_cmd compose ps 2>/dev/null || true
  docker_cmd compose logs --tail=80 2>/dev/null || true
  exit 94
fi

echo "[SILLYTAVERN] DEBUG: no compose file found; falling back to legacy npm start."
if ! command -v npm >/dev/null 2>&1; then echo "[SILLYTAVERN] ERROR[87]: npm executable not found in WSL."; exit 87; fi
npm run start
"""


def start_silly(manager):
    return manager.run_logged("SILLYTAVERN", SILLY_RUN)


def running_silly(manager):
    return manager.service_ok(
        "curl -m 0.8 -sS -o /dev/null http://127.0.0.1:8000 >/dev/null 2>&1 "
        "&& docker inspect sillytavern --format '{{.State.Status}} {{.State.Restarting}}' 2>/dev/null | grep -qx 'running false'"
    )
def installed_silly(manager):
    return _folder_has_compose(manager, SILLY_DIR) or (_folder_exists(manager, SILLY_DIR) and manager.service_ok(f"[ -f {SILLY_DIR!r}/package.json ]"))


def stop_silly(manager, force=False):
    if _folder_has_compose(manager, SILLY_DIR):
        return _compose_down(manager, "SILLYTAVERN", SILLY_DIR, ["sillytavern"], force=force)
    return manager.stop_silly()


def force_stop_silly(manager):
    return stop_silly(manager, force=True)


def uninstall_silly(manager):
    stop_silly(manager, force=True)
    _rm_folder(manager, "SILLYTAVERN", SILLY_DIR)


# =====================================================
# Open WebUI service - priority 4
# =====================================================

OPEN_WEBUI_RUN = _docker_compose_up_command("Open WebUI", "OPENWEBUI", OPEN_WEBUI_DIR)


def start_openwebui(manager):
    return manager.run_logged("OPENWEBUI", OPEN_WEBUI_RUN)


def running_openwebui(manager):
    return (
        manager.service_ok("curl -m 0.8 -fsS http://127.0.0.1:3000 >/dev/null 2>&1") or
        manager.service_ok("curl -m 0.8 -fsS http://127.0.0.1:3000/api/config >/dev/null 2>&1")
    )
def installed_openwebui(manager):
    return _folder_has_compose(manager, OPEN_WEBUI_DIR)


def stop_openwebui(manager, force=False):
    return _compose_down(manager, "OPENWEBUI", OPEN_WEBUI_DIR, ["open-webui"], force=force)


def force_stop_openwebui(manager):
    return stop_openwebui(manager, force=True)


def uninstall_openwebui(manager):
    stop_openwebui(manager, force=True)
    _rm_folder(manager, "OPENWEBUI", OPEN_WEBUI_DIR)


# =====================================================
# Service registry
# =====================================================

SERVICE_HANDLERS = {
    "ollama": {
        "display": "Ollama",
        "url": "127.0.0.1:11434",
        "priority": 0,
        "default_enabled": True,
        "process_names": ["OLLAMA"],
        "ready_timeout": 120,
        "gpu_kind": "llm",
        "supports_gpu": True,
        "start": start_ollama,
        "running": running_ollama,
        "installed": installed_ollama,
        "stop": stop_ollama,
        "force_stop": force_stop_ollama,
        "uninstall": uninstall_ollama,
    },
    "xtts": {
        "display": "XTTS2",
        "url": "127.0.0.1:8020",
        "priority": 2,
        "default_enabled": True,
        "process_names": ["XTTS"],
        "ready_timeout": 180,
        "gpu_kind": "tts",
        "supports_gpu": True,
        "start": start_xtts,
        "running": running_xtts,
        "installed": installed_xtts,
        "stop": stop_xtts,
        "force_stop": force_stop_xtts,
        "uninstall": uninstall_xtts,
    },
    "kokoro": {
        "display": "Kokoro",
        "url": "127.0.0.1:8880",
        "priority": 2,
        "default_enabled": False,
        "process_names": ["KOKORO"],
        "ready_timeout": 120,
        "gpu_kind": "tts",
        "supports_gpu": True,
        "start": start_kokoro,
        "running": running_kokoro,
        "installed": installed_kokoro,
        "stop": stop_kokoro,
        "force_stop": force_stop_kokoro,
        "uninstall": uninstall_kokoro,
    },
    "piper": {
        "display": "Piper",
        "url": "127.0.0.1:5000",
        "priority": 2,
        "default_enabled": False,
        "process_names": ["PIPER"],
        "ready_timeout": 90,
        "gpu_kind": "tts",
        "supports_gpu": False,
        "start": start_piper,
        "running": running_piper,
        "installed": installed_piper,
        "stop": stop_piper,
        "force_stop": force_stop_piper,
        "uninstall": uninstall_piper,
    },
    "silly": {
        "display": "SillyTavern",
        "url": "127.0.0.1:8000",
        "priority": 4,
        "default_enabled": True,
        "process_names": ["SILLYTAVERN"],
        "ready_timeout": 120,
        "supports_gpu": False,
        "start": start_silly,
        "running": running_silly,
        "installed": installed_silly,
        "stop": stop_silly,
        "force_stop": force_stop_silly,
        "uninstall": uninstall_silly,
    },
    "openwebui": {
        "display": "Open WebUI",
        "url": "127.0.0.1:3000",
        "priority": 4,
        "default_enabled": False,
        "process_names": ["OPENWEBUI"],
        "ready_timeout": 120,
        "supports_gpu": False,
        "start": start_openwebui,
        "running": running_openwebui,
        "installed": installed_openwebui,
        "stop": stop_openwebui,
        "force_stop": force_stop_openwebui,
        "uninstall": uninstall_openwebui,
    },
}


def get_default_priorities():
    return {key: int(handler.get("priority", 99)) for key, handler in SERVICE_HANDLERS.items()}


def service_sort_key(key, priorities=None):
    handler = SERVICE_HANDLERS[key]
    priorities = priorities or {}
    priority = int(priorities.get(key, handler.get("priority", 99)))
    return (priority, handler.get("display", key).lower())


def get_default_service_enabled():
    return {key: bool(handler.get("default_enabled", True)) for key, handler in SERVICE_HANDLERS.items()}


def enabled_service_keys(service_enabled=None):
    service_enabled = service_enabled or get_default_service_enabled()
    return [
        key for key in SERVICE_HANDLERS
        if bool(service_enabled.get(key, SERVICE_HANDLERS[key].get("default_enabled", True)))
    ]


def start_order(service_enabled=None, priorities=None):
    return sorted(enabled_service_keys(service_enabled), key=lambda k: service_sort_key(k, priorities))


def stop_order(service_enabled=None, include_disabled=False, priorities=None):
    if include_disabled:
        keys = list(SERVICE_HANDLERS.keys())
    else:
        keys = enabled_service_keys(service_enabled)
    return sorted(keys, key=lambda k: service_sort_key(k, priorities), reverse=True)


def is_installed(manager, key):
    handler = SERVICE_HANDLERS.get(key, {})
    checker = handler.get("installed")
    if checker is None:
        return True
    try:
        return bool(checker(manager))
    except Exception:
        return False


def uninstall_service(manager, key):
    handler = SERVICE_HANDLERS.get(key)
    if not handler:
        manager.write(f"[SERVICES] Unknown service: {key}", "error")
        return False
    uninstaller = handler.get("uninstall")
    if not uninstaller:
        manager.write(f"[SERVICES] {handler.get('display', key)} does not have an uninstall action yet.", "warn")
        return False
    try:
        uninstaller(manager)
        manager.set_service_enabled(key, False)
        manager.write(f"[SERVICES] {handler.get('display', key)} uninstall action complete.")
        return True
    except Exception as e:
        manager.write(f"[SERVICES] {handler.get('display', key)} uninstall failed: {e}", "error")
        return False


def get_service_config(priorities=None):
    """Return tuples used by the Services menu and main status display."""
    return [
        (
            handler.get("display", key),
            key,
            handler.get("url", ""),
            int((priorities or {}).get(key, handler.get("priority", 99))),
        )
        for key, handler in sorted(SERVICE_HANDLERS.items(), key=lambda item: service_sort_key(item[0], priorities))
    ]

# Backwards-compatible names for older manager builds.
START_ORDER = start_order()
STOP_ORDER = stop_order(include_disabled=True)
