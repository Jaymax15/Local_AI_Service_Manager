# Version: 1.1
"""Log filtering, summarising, and severity handling for AI Server Manager."""

import re

INFO = "info"
GOOD = "good"
WARN = "warn"
ERROR = "error"
SYSTEM = "system"
BANNER = "banner"
ENDPOINT = "endpoint"

ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
OSC_RE = re.compile(r"\x1b\].*?(?:\x07|\x1b\\)")

NOISY_CONTAINS = [
    '/speakers HTTP/1.1" 200 OK',
    '"GET / HTTP/1.1" 200 OK',
    '"OPTIONS /set_tts_settings HTTP/1.1" 200 OK',
    "Extensions available for",
    "{ type: 'system'",
    "Chat Completion request:",
    "messages:",
    "role:",
    "content:",
    "prompt:",
    "temperature:",
    "max_tokens:",
    "max_completion_tokens:",
    "presence_penalty:",
    "frequency_penalty:",
    "top_p:",
    "top_k:",
    "logit_bias:",
    "top_logprobs:",
    "Container image Copyright",
    "NVIDIA Deep Learning Container License",
    "DEPRECATION NOTICE",
    "THIS IMAGE IS DEPRECATED",
    "support-policy.md",
    "Field \"model_name\" has conflict",
    "warnings.warn",
    "governed by the NVIDIA",
    "By pulling and using",
    "A copy of this license",
    "==========",
    "== CUDA ==",
    "Pulling fs layer",
    "Waiting",
    "Download complete",
    "Pull complete",
    "Digest: sha256",
    "Status: Downloaded newer image",
    "Status: Image is up to date",
    "GET /docs HTTP/1.1",
    "GET /openapi.json HTTP/1.1",
    "GET /health HTTP/1.1",
    "GET /v1/audio/voices HTTP/1.1",
    "HTTP/1.1\" 200 OK",
    "INFO:     127.0.0.1",
    "INFO:     172.",
    "INFO:     Started server process",
    "INFO:     Waiting for application startup",
    "INFO:     Shutting down",
    "GET /api/config HTTP/1.1",
    "GET /favicon.ico HTTP/1.1",
    "GET /static/",
    "GET /_app/",
    "POST /v1/audio/speech HTTP/1.1",
    "npm notice",
    "npm WARN",
    "webpack compiled",
    "webpack 5",
    "chunk",
    "asset ",
    "Pulling",
    "Extracting",
    "Verifying Checksum",
    "Already exists",
    "Creating",
    "Created",
    "Attaching to",
    "Gracefully stopping",
    "DEBUG: PATH=",
    "PATH=/usr/local/sbin:",
]

GOOD_CONTAINS = [
    "successfully",
    "Started ollama.service",
    "Ollama start command sent",
    "Ollama API ready",
    "Already running",
    "Model successfully loaded",
    "Application startup complete",
    "Uvicorn running",
    "SillyTavern is listening",
    "All services running",
    "Stopped after attempt",
    "Fully stopped",
    "Force stopped",
    "Stopped.",
    "XTTS warmup complete",
    "XTTS API reachable",
    "Sudo access installed successfully",
    "installed.",
    "installed at",
    "compose start is running",
    "Using compose file",
]

WARN_CONTAINS = [
    "warning",
    "warn",
    "failed to hydrate cloud model show cache",
    "context canceled",
    "warmup request failed",
    "did not become reachable",
    "not running. skipping stop",
    "disabled in services",
    "already has a manager process",
    "installer finished",
    "not have an automatic installer",
]

ERROR_CONTAINS = [
    "ERROR[",
    "EXIT_CODE:",
    "SUDO ACCESS NOT GIVEN",
    "ERROR:",
    "Traceback",
    "Exception",
    "could not launch",
    "could not stop",
    "returned non-zero exit status",
    "command exited with code",
    "docker command not found",
    "Docker is not reachable",
    "folder missing",
    "folder not found",
    "manifest unknown",
    "pull access denied",
    "no matching manifest",
]

KEEP_BY_SERVICE = {
    "SILLYTAVERN": [
        "DEBUG:",
        "EXIT_CODE:",
        "SillyTavern is listening",
        "Available models:",
        "Streaming request in progress",
        "Streaming request finished",
        "Instantiated the tokenizer",
        "webpack",
        "ERROR",
        "Error",
        "Traceback",
    ],
    "XTTS": [
        "DEBUG:",
        "EXIT_CODE:",
        "[XTTS]",
        "[WARMUP]",
        "Model successfully loaded",
        "Uvicorn running",
        "Application startup complete",
        "Processing time",
        "ERROR",
        "Error",
        "Traceback",
        "Exception",
    ],
    "OLLAMA": [
        "DEBUG:",
        "EXIT_CODE:",
        "[OLLAMA]",
        "Started",
        "Stopped",
        "ollama.service",
        "error",
        "Error",
        "failed",
        "Failed",
        "WARN",
    ],
    "OPENWEBUI": [
        "DEBUG:",
        "EXIT_CODE:",
        "[OPENWEBUI]",
        "Application startup complete",
        "Uvicorn running",
        "Running on",
        "ERROR",
        "Error",
        "Traceback",
        "failed",
        "Failed",
    ],
    "KOKORO": [
        "DEBUG:",
        "EXIT_CODE:",
        "[KOKORO]",
        "Application startup complete",
        "Uvicorn running",
        "Kokoro",
        "Loaded",
        "ERROR",
        "Error",
        "Traceback",
        "failed",
        "Failed",
    ],
    "PIPER": [
        "DEBUG:",
        "EXIT_CODE:",
        "[PIPER]",
        "Application startup complete",
        "Uvicorn running",
        "Piper",
        "Downloading voice",
        "Loaded",
        "ERROR",
        "Error",
        "Traceback",
        "failed",
        "Failed",
    ],
    "INSTALLER": [
        "[INSTALLER]",
        "installed",
        "ERROR",
        "Error",
        "failed",
        "Failed",
    ],
}


def clean_ansi(text):
    text = OSC_RE.sub("", text or "")
    text = ANSI_RE.sub("", text)
    return text.replace("\r", "").strip("\n")


def strip_duplicate_prefix(text):
    # Turns "[OLLAMA] [OLLAMA] Starting..." into "[OLLAMA] Starting...".
    return re.sub(r"^(\[[^\]]+\])\s+\1\s+", r"\1 ", text)


def summarize(text):
    text = clean_ansi(text).strip()
    if not text:
        return ""
    text = strip_duplicate_prefix(text)

    lower = text.lower()

    if "failed to hydrate cloud model show cache" in lower:
        service = "[OLLAMA] " if text.startswith("[OLLAMA]") else ""
        return service + "Warning! failed to hydrate cloud model show cache"

    if "debug: path=" in lower or "path=/usr/local/sbin:" in lower:
        return ""

    if "pulling fs layer" in lower or "download complete" in lower or "pull complete" in lower:
        return ""

    if "http/1.1\" 200 ok" in lower and ("127.0.0.1" in lower or "172." in lower):
        return ""

    if "returned non-zero exit status 83" in lower or "xtts did not become reachable" in lower:
        return "[WARMUP] Warning! XTTS warmup timed out or failed. XTTS may still be running."

    if "returned non-zero exit status" in lower:
        m = re.search(r"returned non-zero exit status\s+(-?\d+)", text)
        code = m.group(1) if m else "unknown"
        return f"[SYSTEM] Command failed with exit code {code}."

    if "command exited with code 15" in lower:
        return ""  # normal when the manager intentionally terminates an attached process

    if "command exited with code 1" in lower and "OLLAMA" in text:
        return ""  # journalctl/process tail often exits when service is intentionally stopped

    if "processing time:" in lower:
        m = re.search(r"Processing time:\s*([0-9.]+)", text)
        if m:
            return f"[XTTS] Processing complete in {float(m.group(1)):.1f}s"

    return text


def should_show(service, text):
    text = clean_ansi(text)
    if not text.strip():
        return False

    lowered = text.lower()
    if any(x.lower() in lowered for x in ERROR_CONTAINS + WARN_CONTAINS):
        return True
    if any(x.lower() in lowered for x in NOISY_CONTAINS):
        return False

    keep = KEEP_BY_SERVICE.get(service, None)
    if keep is None:
        return True
    return any(x in text for x in keep)


def classify(text):
    text = clean_ansi(text)
    lower = text.lower()

    if text.startswith("==========") and text.endswith("=========="):
        return BANNER
    if "http://" in text or "https://" in text or "127.0.0.1:" in text or "localhost:" in text:
        if text.startswith(("SillyTavern:", "Ollama API:", "XTTS2 API:", "Open WebUI:", "Kokoro:", "Piper:")):
            return ENDPOINT
    if any(x.lower() in lower for x in ERROR_CONTAINS):
        # Warmup timeout is non-critical if XTTS is already up.
        if "warmup" in lower and ("timed out" in lower or "failed" in lower):
            return WARN
        return ERROR
    if any(x.lower() in lower for x in WARN_CONTAINS):
        return WARN
    if any(x.lower() in lower for x in GOOD_CONTAINS):
        return GOOD
    if text.startswith("[SYSTEM]") or text.startswith("[SETTINGS]") or text.startswith("[SERVICES]"):
        return SYSTEM
    return INFO


def process_line(service, text):
    if not should_show(service, text):
        return None, INFO
    out = summarize(text)
    if not out:
        return None, INFO
    return out, classify(out)
