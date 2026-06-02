# Version: 1.1
"""Processor discovery and service capability filtering for AI Server Manager.

V81 experimental: fixes XTTS Docker GPU enforcement by requesting Docker GPU access
and routing the selected NVIDIA card with CUDA_VISIBLE_DEVICES.
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple


@dataclass(frozen=True)
class ProcessorOption:
    """Normalised processor option used by the UI and settings storage."""

    id: str
    label: str
    kind: str
    vendor: str = ""
    index: Optional[int] = None


# Capability metadata is intentionally small and declarative. This is not a
# custom runtime handler per service; it is only the list of processor classes
# that the UI should offer for each service.
SERVICE_PROCESSOR_CAPABILITIES: Dict[str, Dict[str, object]] = {
    "ollama": {
        "allowed": ["auto", "cpu", "gpu"],
        "backend": "systemd",
        "note": "LLM runtime. GPU routing will be enforced later.",
    },
    "xtts": {
        "allowed": ["auto", "cpu", "gpu"],
        "backend": "docker",
        "note": "TTS runtime. Supports --device cpu/cuda:N and Docker GPU routing.",
    },
    "kokoro": {
        "allowed": ["auto", "cpu", "gpu"],
        "backend": "docker",
        "note": "TTS runtime. GPU support depends on installed image/runtime.",
    },
    "piper": {
        "allowed": ["auto", "cpu"],
        "backend": "docker",
        "note": "Piper is treated as CPU-only.",
    },
    "silly": {
        "allowed": ["auto", "cpu"],
        "backend": "docker",
        "note": "SillyTavern is a UI/front-end; the model runner uses its own processor.",
    },
    "openwebui": {
        "allowed": ["auto", "cpu"],
        "backend": "docker",
        "note": "Open WebUI is a UI/front-end; Ollama handles model processing.",
    },
}


_DETECTION_CACHE: Dict[str, object] = {"stamp": 0.0, "options": None}


def service_capability(service_key: str) -> Dict[str, object]:
    return dict(SERVICE_PROCESSOR_CAPABILITIES.get(str(service_key), {"allowed": ["auto", "cpu"], "backend": "unknown"}))


def service_allows_gpu(service_key: str) -> bool:
    allowed = service_capability(service_key).get("allowed", [])
    return "gpu" in set(str(x).lower() for x in allowed)


def _cpu_label(manager=None) -> str:
    try:
        cpu = getattr(manager, "cpu_status_cache", {}) or {}
        name = str(cpu.get("name") or "CPU").strip()
        return f"CPU - {name}" if name and name != "CPU" else "CPU"
    except Exception:
        return "CPU"


def _gpu_rows_from_manager(manager=None) -> List[Tuple[str, str]]:
    rows = []
    try:
        for row in getattr(manager, "gpu_rows_cache", []) or []:
            if len(row) >= 2:
                idx, name = str(row[0]).strip(), str(row[1]).strip()
                if idx and name:
                    rows.append((idx, name))
    except Exception:
        pass
    return rows


def _gpu_rows_from_nvidia_smi() -> List[Tuple[str, str]]:
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=index,name", "--format=csv,noheader,nounits"],
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1.5,
        ).strip()
    except Exception:
        return []
    rows = []
    for line in out.splitlines():
        parts = [p.strip() for p in line.split(",", 1)]
        if parts and parts[0].isdigit():
            rows.append((parts[0], parts[1] if len(parts) > 1 and parts[1] else f"NVIDIA GPU {parts[0]}"))
    return rows


def _normalise_gpu_vendor(name: str) -> str:
    lower = str(name or "").lower()
    if "nvidia" in lower or "geforce" in lower or "rtx" in lower or "gtx" in lower or "quadro" in lower:
        return "nvidia"
    if "amd" in lower or "radeon" in lower:
        return "amd"
    if "intel" in lower or "arc" in lower or "iris" in lower:
        return "intel"
    return "gpu"


def detect_processors(manager=None) -> List[ProcessorOption]:
    """Return available processor choices using stable IDs.

    V83: cached briefly so Settings/Services can open instantly. The live GPU
    monitor already maintains manager.gpu_rows_cache, so this function should
    not call nvidia-smi repeatedly on the Tk UI path.
    """
    try:
        now = time.time()
        mgr_rows = tuple(_gpu_rows_from_manager(manager))
        cpu_name = _cpu_label(manager)
        cache_key = (mgr_rows, cpu_name)
        if (_DETECTION_CACHE.get("options") is not None
                and _DETECTION_CACHE.get("key") == cache_key
                and now - float(_DETECTION_CACHE.get("stamp", 0.0) or 0.0) < 8.0):
            return list(_DETECTION_CACHE.get("options") or [])
    except Exception:
        now = time.time()
        cache_key = None

    options: List[ProcessorOption] = [
        ProcessorOption("auto", "Auto", "auto"),
        ProcessorOption("cpu", _cpu_label(manager), "cpu"),
    ]

    # Prefer the manager monitor cache. Only fall back to nvidia-smi if the
    # monitor has not populated yet, because nvidia-smi can stall UI opening.
    rows = _gpu_rows_from_manager(manager)
    if not rows:
        try:
            if _DETECTION_CACHE.get("options") is not None and time.time() - float(_DETECTION_CACHE.get("stamp", 0.0) or 0.0) < 30.0:
                cached = list(_DETECTION_CACHE.get("options") or [])
                if cached:
                    return cached
        except Exception:
            pass
        rows = _gpu_rows_from_nvidia_smi()

    seen = set()
    for raw_idx, raw_name in rows:
        try:
            idx = int(str(raw_idx).strip())
        except Exception:
            continue
        name = str(raw_name or f"GPU {idx}").strip()
        vendor = _normalise_gpu_vendor(name)
        # Use stable vendor/index IDs. Display names can change; IDs should not.
        pid = f"gpu:{vendor}:{idx}"
        if pid in seen:
            continue
        seen.add(pid)
        clean_name = name
        if vendor == "nvidia" and "nvidia" not in clean_name.lower():
            clean_name = f"NVIDIA {clean_name}"
        options.append(ProcessorOption(pid, f"GPU {idx} - {clean_name}", "gpu", vendor=vendor, index=idx))

    try:
        _DETECTION_CACHE["options"] = list(options)
        _DETECTION_CACHE["stamp"] = time.time()
        _DETECTION_CACHE["key"] = cache_key
    except Exception:
        pass
    return options


def option_pairs_for_service(service_key: str, manager=None) -> List[Tuple[str, str]]:
    """Return (label, stable_id) pairs filtered by service capability."""
    allowed = set(str(x).lower() for x in service_capability(service_key).get("allowed", ["auto", "cpu"]))
    pairs = []
    for opt in detect_processors(manager):
        if opt.kind in allowed:
            pairs.append((opt.label, opt.id))
    if not pairs:
        pairs = [("Auto", "auto")]
    return pairs


def normalise_selection(service_key: str, selected_id: str, manager=None) -> str:
    """Return a valid stable processor ID for this service."""
    selected = str(selected_id or "auto").strip()
    valid = {value for _label, value in option_pairs_for_service(service_key, manager)}
    if selected in valid:
        return selected
    # Backwards compatibility for old V77 values like gpu:0.
    if selected.startswith("gpu:") and service_allows_gpu(service_key):
        suffix = selected.split(":")[-1]
        for value in valid:
            if value.startswith("gpu:") and value.endswith(f":{suffix}"):
                return value
    return "auto"


def describe_selection(service_key: str, selected_id: str, manager=None) -> str:
    selected = normalise_selection(service_key, selected_id, manager)
    for label, value in option_pairs_for_service(service_key, manager):
        if value == selected:
            return label
    return "Auto"


def detection_summary(manager=None) -> str:
    labels = [opt.label for opt in detect_processors(manager)]
    return ", ".join(labels) if labels else "Auto"


def log_startup_summary(manager, enabled_services: Optional[Iterable[str]] = None) -> None:
    """Write useful processor debug lines to the manager terminal."""
    try:
        manager.write(f"[PROCESSOR] Detected processor options: {detection_summary(manager)}", "system")
        service_keys = list(enabled_services or [])
        if not service_keys:
            return
        selections = getattr(manager, "service_processors", {}) or {}
        for key in service_keys:
            caps = service_capability(key)
            label = describe_selection(key, selections.get(key, "auto"), manager)
            allowed = "/".join(str(x).upper() for x in caps.get("allowed", []))
            manager.write(f"[PROCESSOR] {key}: selected={label}; allowed={allowed}; backend={caps.get('backend', 'unknown')}", "system")
    except Exception as e:
        try:
            manager.write(f"[PROCESSOR] Detection warning: {e}", "warn")
        except Exception:
            pass

# =====================================================
# Runtime enforcement helpers - V81 experimental
# =====================================================

def _selection_option(manager, service_key: str) -> ProcessorOption:
    """Return the selected processor option for a service, defaulting to Auto."""
    try:
        selections = getattr(manager, "service_processors", {}) or {}
        selected = normalise_selection(service_key, selections.get(service_key, "auto"), manager)
    except Exception:
        selected = "auto"
    for opt in detect_processors(manager):
        if opt.id == selected:
            return opt
    return ProcessorOption("auto", "Auto", "auto")


def selected_summary(manager, service_key: str) -> str:
    opt = _selection_option(manager, service_key)
    return f"{opt.label} [{opt.id}]"


def _systemd_environment_lines(opt: ProcessorOption) -> List[str]:
    """Return systemd Environment= lines for a selected processor."""
    if opt.kind == "cpu":
        return [
            'Environment="CUDA_VISIBLE_DEVICES=-1"',
            'Environment="NVIDIA_VISIBLE_DEVICES=none"',
            'Environment="HIP_VISIBLE_DEVICES=-1"',
            'Environment="ROCR_VISIBLE_DEVICES=-1"',
            'Environment="OLLAMA_NO_GPU=1"',
        ]
    if opt.kind == "gpu" and opt.vendor == "nvidia" and opt.index is not None:
        return [
            f'Environment="CUDA_VISIBLE_DEVICES={opt.index}"',
            f'Environment="NVIDIA_VISIBLE_DEVICES={opt.index}"',
            'Environment="NVIDIA_DRIVER_CAPABILITIES=compute,utility"',
        ]
    if opt.kind == "gpu" and opt.vendor == "amd" and opt.index is not None:
        return [
            f'Environment="HIP_VISIBLE_DEVICES={opt.index}"',
            f'Environment="ROCR_VISIBLE_DEVICES={opt.index}"',
            f'Environment="GPU_DEVICE_ORDINAL={opt.index}"',
        ]
    if opt.kind == "gpu" and opt.vendor == "intel" and opt.index is not None:
        return [f'Environment="ONEAPI_DEVICE_SELECTOR=level_zero:gpu:{opt.index}"']
    return []


def _docker_environment_items(opt: ProcessorOption) -> List[str]:
    """Return docker-compose environment list items for a selected processor."""
    if opt.kind == "cpu":
        return [
            "CUDA_VISIBLE_DEVICES=-1",
            "NVIDIA_VISIBLE_DEVICES=none",
            "HIP_VISIBLE_DEVICES=-1",
            "ROCR_VISIBLE_DEVICES=-1",
            "DEVICE=cpu",
        ]
    if opt.kind == "gpu" and opt.vendor == "nvidia" and opt.index is not None:
        return [
            f"CUDA_VISIBLE_DEVICES={opt.index}",
            f"NVIDIA_VISIBLE_DEVICES={opt.index}",
            "NVIDIA_DRIVER_CAPABILITIES=compute,utility",
            "DEVICE=cuda",
        ]
    if opt.kind == "gpu" and opt.vendor == "amd" and opt.index is not None:
        return [
            f"HIP_VISIBLE_DEVICES={opt.index}",
            f"ROCR_VISIBLE_DEVICES={opt.index}",
            f"GPU_DEVICE_ORDINAL={opt.index}",
            "DEVICE=rocm",
        ]
    if opt.kind == "gpu" and opt.vendor == "intel" and opt.index is not None:
        return [
            f"ONEAPI_DEVICE_SELECTOR=level_zero:gpu:{opt.index}",
            "DEVICE=xpu",
        ]
    return []


def ollama_processor_repair_script(manager) -> str:
    """Shell preflight that rewrites Ollama's systemd override for the selected processor."""
    opt = _selection_option(manager, "ollama")
    label = opt.label.replace('"', "'")
    env_lines = "\n".join(_systemd_environment_lines(opt))
    # Auto intentionally writes no processor env lines. This clears stale CPU/GPU
    # forcing while preserving the required model/host settings.
    return f'''
echo "[PROCESSOR] Ollama processor selection: {label}"
sudo -n mkdir -p /etc/systemd/system/ollama.service.d >/dev/null 2>&1 || true
existing_models=$(grep -E '^Environment="OLLAMA_MODELS=' /etc/systemd/system/ollama.service.d/override.conf 2>/dev/null | sed 's/^Environment="OLLAMA_MODELS=//; s/"$//' || true)
[ -n "$existing_models" ] || existing_models="$OLLAMA_BASE/models"
cat >/tmp/ai-manager-ollama-override.conf <<'EOF'
[Service]
Environment="HOME=/usr/share/ollama"
Environment="OLLAMA_MODELS=__AI_MANAGER_OLLAMA_MODELS__"
Environment="OLLAMA_KEEP_ALIVE=-1"
Environment="OLLAMA_HOST=0.0.0.0:11434"
{env_lines}
EOF
python3 - "$existing_models" <<'PYFIX'
from pathlib import Path
import sys
p = Path('/tmp/ai-manager-ollama-override.conf')
text = p.read_text()
text = text.replace('__AI_MANAGER_OLLAMA_MODELS__', sys.argv[1])
p.write_text(text)
PYFIX
if [ ! -f /etc/systemd/system/ollama.service.d/override.conf ] || ! cmp -s /tmp/ai-manager-ollama-override.conf /etc/systemd/system/ollama.service.d/override.conf; then
  echo "[PROCESSOR] Applying Ollama processor/systemd override."
  sudo -n install -m 0644 /tmp/ai-manager-ollama-override.conf /etc/systemd/system/ollama.service.d/override.conf >/dev/null 2>&1 || true
  sudo -n systemctl daemon-reload >/dev/null 2>&1 || true
  if sudo -n systemctl is-active --quiet ollama >/dev/null 2>&1; then
    echo "[PROCESSOR] Restarting Ollama to apply processor selection."
    sudo -n systemctl restart ollama >/dev/null 2>&1 || true
  fi
else
  echo "[PROCESSOR] Ollama processor override already current."
fi
rm -f /tmp/ai-manager-ollama-override.conf
'''


def docker_compose_processor_repair_script(manager, service_key: str, service_tag: str, compose_service_names: Iterable[str]) -> str:
    """Return shell/Python preflight that patches a manager-owned compose file.

    V81 notes:
    - XTTS needs Docker GPU access (`gpus: all`) before CUDA is visible.
    - For XTTS, selected NVIDIA card is routed with CUDA_VISIBLE_DEVICES while
      NVIDIA_VISIBLE_DEVICES remains all. This mirrors the WSL terminal test
      that made torch report cuda available with one visible selected GPU.
    - Auto restores the manager base compose and applies no special routing.
    """
    opt = _selection_option(manager, service_key)
    label = opt.label.replace('"', "'")
    mode = opt.kind
    vendor = opt.vendor or ""
    index = "" if opt.index is None else str(opt.index)

    env_items = _docker_environment_items(opt)
    if service_key == "xtts" and opt.kind == "gpu" and opt.vendor == "nvidia" and opt.index is not None:
        env_items = [
            f"CUDA_VISIBLE_DEVICES={opt.index}",
            "NVIDIA_VISIBLE_DEVICES=all",
            "NVIDIA_DRIVER_CAPABILITIES=compute,utility",
            "DEVICE=cuda",
        ]
    env_joined = "|".join(env_items)
    names = ",".join(str(x) for x in compose_service_names)
    return f'''
echo "[PROCESSOR] {service_tag} processor selection: {label}"
python3 - <<'PYPROC'
from pathlib import Path

service_key = {service_key!r}
service_names = {names!r}.split(',')
mode = {mode!r}
vendor = {vendor!r}
index = {index!r}
env_items = [x for x in {env_joined!r}.split('|') if x]
service_tag = {service_tag!r}

compose = None
for name in ('docker-compose.yml', 'docker-compose.yaml', 'compose.yml', 'compose.yaml'):
    p = Path(name)
    if p.exists():
        compose = p
        break
if compose is None:
    print(f"[PROCESSOR] {{service_tag}} compose processor patch skipped: no compose file.")
    raise SystemExit(0)

base = Path('.ai-manager-base-compose.yml')
current = compose.read_text(encoding='utf-8', errors='replace')
if not base.exists():
    base.write_text(current, encoding='utf-8')

# Always start from the base compose so switching CPU/GPU/Auto is reversible.
text = base.read_text(encoding='utf-8', errors='replace')

if mode == 'auto':
    if current != text:
        compose.write_text(text, encoding='utf-8')
        print(f"[PROCESSOR] {{service_tag}} restored Auto/default compose settings.")
    else:
        print(f"[PROCESSOR] {{service_tag}} using Auto/default compose settings.")
    raise SystemExit(0)

lines = text.splitlines()
PROC_ENV_PREFIXES = (
    'CUDA_VISIBLE_DEVICES=', 'NVIDIA_VISIBLE_DEVICES=', 'NVIDIA_DRIVER_CAPABILITIES=',
    'HIP_VISIBLE_DEVICES=', 'ROCR_VISIBLE_DEVICES=', 'GPU_DEVICE_ORDINAL=',
    'ONEAPI_DEVICE_SELECTOR=', 'DEVICE=',
)


def indent_count(line):
    return len(line) - len(line.lstrip(' '))


def find_service_block(lines, names):
    for i, line in enumerate(lines):
        stripped = line.strip()
        if indent_count(line) == 2 and stripped.endswith(':') and stripped[:-1] in names:
            j = i + 1
            while j < len(lines):
                if lines[j].strip() and indent_count(lines[j]) <= 2 and lines[j].strip().endswith(':'):
                    break
                j += 1
            return i, j
    return None, None


def remove_top_subsection(block, key):
    out = []
    i = 0
    target = '    ' + key + ':'
    while i < len(block):
        line = block[i]
        if line.startswith(target):
            i += 1
            while i < len(block) and (not block[i].strip() or indent_count(block[i]) > 4):
                i += 1
            continue
        out.append(line)
        i += 1
    return out


def clean_environment_items(block):
    out = []
    for line in block:
        stripped = line.strip()
        if stripped.startswith('- '):
            item = stripped[2:].strip().strip('"').strip("'")
            if any(item.startswith(prefix) for prefix in PROC_ENV_PREFIXES):
                continue
        out.append(line)
    return out


def ensure_environment_items(block, items):
    if not items:
        return block
    env_idx = None
    for i, line in enumerate(block):
        if line.startswith('    environment:'):
            env_idx = i
            break
    insert_lines = ['      - ' + item for item in items]
    if env_idx is None:
        return block[:1] + ['    environment:'] + insert_lines + block[1:]
    return block[:env_idx + 1] + insert_lines + block[env_idx + 1:]


def add_gpu_block(block):
    if mode == 'gpu' and vendor == 'nvidia' and index != '':
        if service_key == 'xtts':
            # Verified in WSL: XTTS requires Docker GPU access. CUDA_VISIBLE_DEVICES
            # chooses the physical GPU, while Docker exposes the NVIDIA runtime.
            block += ['    gpus: all']
        else:
            block += [
                '    gpus:',
                '      - driver: nvidia',
                '        device_ids:',
                f'          - "{{index}}"',
                '        capabilities:',
                '          - gpu',
                '    deploy:',
                '      resources:',
                '        reservations:',
                '          devices:',
                '            - driver: nvidia',
                '              device_ids:',
                f'                - "{{index}}"',
                '              capabilities:',
                '                - gpu',
            ]
    return block


start, end = find_service_block(lines, service_names)
if start is None:
    print(f"[PROCESSOR] {{service_tag}} compose processor patch skipped: service name not found.")
    raise SystemExit(0)

before = lines[:start]
block = lines[start:end]
after = lines[end:]
block = remove_top_subsection(block, 'command')
block = remove_top_subsection(block, 'deploy')
block = remove_top_subsection(block, 'gpus')
block = clean_environment_items(block)
block = ensure_environment_items(block, env_items)
block = add_gpu_block(block)
new_text = '\\n'.join(before + block + after).rstrip() + '\\n'
if new_text != current:
    compose.write_text(new_text, encoding='utf-8')
    if mode == 'cpu':
        print(f"[PROCESSOR] {{service_tag}} compose set to CPU-only mode.")
    elif mode == 'gpu':
        if service_key == 'xtts':
            print(f"[PROCESSOR] {{service_tag}} compose set to GPU mode: {{vendor}} {{index}} using Docker gpus: all + CUDA_VISIBLE_DEVICES={{index}}.")
        else:
            print(f"[PROCESSOR] {{service_tag}} compose set to GPU mode: {{vendor}} {{index}}.")
else:
    print(f"[PROCESSOR] {{service_tag}} compose processor settings already current.")
PYPROC
'''
