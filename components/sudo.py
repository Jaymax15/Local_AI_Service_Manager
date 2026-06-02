"""Sudo setup helper for AI Server Manager.

This module owns the /etc/sudoers.d/ai-manager setup so sudo fixes can be
tested by replacing only components/sudo.py after the manager delegates here.

Important bug fixed here:
When a script is run through `sudo bash script.sh`, `id -un` becomes `root`.
The real WSL user is stored in `$SUDO_USER`. Older manager versions wrote
sudoers rules for root by mistake, so `sudo -n` still failed for the real user.
"""

import base64
import subprocess
import threading
import time


CREATE_NO_WINDOW = 0x08000000


def _write_status(manager, on_status, message, color="#cccccc"):
    try:
        manager.write(f"[SETTINGS] {message}")
    except Exception:
        pass
    if on_status is not None:
        try:
            manager.safe_ui(lambda m=message, c=color: on_status(m, c))
        except Exception:
            try:
                on_status(message, color)
            except Exception:
                pass


def _wsl_run(command, timeout=12, input_text=None):
    return subprocess.run(
        ["wsl", "bash", "-lc", command],
        input=input_text,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=CREATE_NO_WINDOW,
        timeout=timeout,
    )


def _passwordless_check():
    """Check passwordless sudo as the normal WSL user, not as root."""
    cmd = (
        "sudo -k; "
        "sudo -n systemctl --version >/dev/null 2>&1 && "
        "sudo -n pkill --version >/dev/null 2>&1 && "
        "sudo -n apt-get --version >/dev/null 2>&1 && "
        "sudo -n rm --version >/dev/null 2>&1 && "
        "echo SUDO_PASSWORDLESS_OK || echo SUDO_PASSWORDLESS_FAILED"
    )
    try:
        result = _wsl_run(cmd, timeout=10)
        out = result.stdout or ""
        return result.returncode == 0 and "SUDO_PASSWORDLESS_OK" in out, out
    except Exception as e:
        return False, str(e)


SUDO_INSTALL_SCRIPT = r"""#!/usr/bin/env bash
set -euo pipefail

# The script itself is run as root using: sudo -S bash script.sh
# Therefore id -un would be "root". The real user is SUDO_USER.
CALLER_USER="${SUDO_USER:-}"

if [ -z "$CALLER_USER" ] || [ "$CALLER_USER" = "root" ]; then
  CALLER_USER="$(logname 2>/dev/null || true)"
fi

if [ -z "$CALLER_USER" ] || [ "$CALLER_USER" = "root" ]; then
  echo "ERROR[SUDO-USER-001]: Could not detect the real WSL username. SUDO_USER='${SUDO_USER:-}'"
  exit 12
fi

CALLER_HOME="$(getent passwd "$CALLER_USER" | cut -d: -f6 || true)"
SUDOERS="/etc/sudoers.d/ai-manager"
TMP="/tmp/ai-manager-sudoers.$$"

SYSTEMCTL="$(command -v systemctl || echo /usr/bin/systemctl)"
PKILL="$(command -v pkill || echo /usr/bin/pkill)"
JOURNALCTL="$(command -v journalctl || echo /usr/bin/journalctl)"
DOCKER="$(command -v docker || true)"
APTGET="$(command -v apt-get || echo /usr/bin/apt-get)"
APT="$(command -v apt || echo /usr/bin/apt)"
DPKG="$(command -v dpkg || echo /usr/bin/dpkg)"
DPKGQUERY="$(command -v dpkg-query || echo /usr/bin/dpkg-query)"
CURL="$(command -v curl || echo /usr/bin/curl)"
TEE="$(command -v tee || echo /usr/bin/tee)"
INSTALL_CMD="$(command -v install || echo /usr/bin/install)"
CHMOD="$(command -v chmod || echo /usr/bin/chmod)"
CHOWN="$(command -v chown || echo /usr/bin/chown)"
RM="$(command -v rm || echo /usr/bin/rm)"
MKDIR="$(command -v mkdir || echo /usr/bin/mkdir)"
GROUPADD="$(command -v groupadd || echo /usr/sbin/groupadd)"
USERMOD="$(command -v usermod || echo /usr/sbin/usermod)"
SERVICE="$(command -v service || echo /usr/sbin/service)"
SH="$(command -v sh || echo /usr/bin/sh)"
BASH="$(command -v bash || echo /usr/bin/bash)"
PYTHON3="$(command -v python3 || echo /usr/bin/python3)"
GIT="$(command -v git || echo /usr/bin/git)"
NPM="$(command -v npm || echo /usr/bin/npm)"
NODE="$(command -v node || echo /usr/bin/node)"

echo "DEBUG: effective user=$(id -un)"
echo "DEBUG: real WSL user=$CALLER_USER"
echo "DEBUG: caller home=$CALLER_HOME"
echo "DEBUG: systemctl=$SYSTEMCTL"
echo "DEBUG: pkill=$PKILL"
echo "DEBUG: journalctl=$JOURNALCTL"
echo "DEBUG: apt-get=$APTGET"
echo "DEBUG: service=$SERVICE"
echo "DEBUG: chown=$CHOWN"
echo "DEBUG: sh=$SH"
echo "DEBUG: bash=$BASH"
echo "DEBUG: python3=$PYTHON3"
echo "DEBUG: git=$GIT"
echo "DEBUG: npm=$NPM"
echo "DEBUG: node=$NODE"
if [ -n "$DOCKER" ]; then
  echo "DEBUG: docker=$DOCKER"
else
  echo "DEBUG: docker not found yet; adding expected headless Docker sudo rules for /usr/bin/docker"
fi

cat > "$TMP" <<EOF
# AI Server Manager passwordless sudo rules
# Created by AI Server Manager Settings.
$CALLER_USER ALL=(root) NOPASSWD: $SYSTEMCTL
$CALLER_USER ALL=(root) NOPASSWD: $SYSTEMCTL *
$CALLER_USER ALL=(root) NOPASSWD: $PKILL
$CALLER_USER ALL=(root) NOPASSWD: $PKILL *
$CALLER_USER ALL=(root) NOPASSWD: $JOURNALCTL
$CALLER_USER ALL=(root) NOPASSWD: $JOURNALCTL *
$CALLER_USER ALL=(root) NOPASSWD: $APTGET
$CALLER_USER ALL=(root) NOPASSWD: $APTGET *
$CALLER_USER ALL=(root) NOPASSWD: $APT
$CALLER_USER ALL=(root) NOPASSWD: $APT *
$CALLER_USER ALL=(root) NOPASSWD: $DPKG
$CALLER_USER ALL=(root) NOPASSWD: $DPKG *
$CALLER_USER ALL=(root) NOPASSWD: $DPKGQUERY
$CALLER_USER ALL=(root) NOPASSWD: $DPKGQUERY *
$CALLER_USER ALL=(root) NOPASSWD: $CURL
$CALLER_USER ALL=(root) NOPASSWD: $CURL *
$CALLER_USER ALL=(root) NOPASSWD: $TEE
$CALLER_USER ALL=(root) NOPASSWD: $TEE *
$CALLER_USER ALL=(root) NOPASSWD: $INSTALL_CMD
$CALLER_USER ALL=(root) NOPASSWD: $INSTALL_CMD *
$CALLER_USER ALL=(root) NOPASSWD: $CHMOD
$CALLER_USER ALL=(root) NOPASSWD: $CHMOD *
$CALLER_USER ALL=(root) NOPASSWD: $CHOWN
$CALLER_USER ALL=(root) NOPASSWD: $CHOWN *
$CALLER_USER ALL=(root) NOPASSWD: $RM
$CALLER_USER ALL=(root) NOPASSWD: $RM *
$CALLER_USER ALL=(root) NOPASSWD: $MKDIR
$CALLER_USER ALL=(root) NOPASSWD: $MKDIR *
$CALLER_USER ALL=(root) NOPASSWD: $GROUPADD
$CALLER_USER ALL=(root) NOPASSWD: $GROUPADD *
$CALLER_USER ALL=(root) NOPASSWD: $USERMOD
$CALLER_USER ALL=(root) NOPASSWD: $USERMOD *
$CALLER_USER ALL=(root) NOPASSWD: $SERVICE
$CALLER_USER ALL=(root) NOPASSWD: $SERVICE *

# Manager install helpers and downloaded installers.
# This lets the manager run its own temporary installer scripts with sudo when needed.
# Scoped to /tmp/ai_manager_* and the official downloaded Ollama installer.
$CALLER_USER ALL=(root) NOPASSWD: $SH /tmp/ollama-install.sh
$CALLER_USER ALL=(root) NOPASSWD: $BASH /tmp/ollama-install.sh
$CALLER_USER ALL=(root) NOPASSWD: /bin/sh /tmp/ollama-install.sh
$CALLER_USER ALL=(root) NOPASSWD: /usr/bin/sh /tmp/ollama-install.sh
$CALLER_USER ALL=(root) NOPASSWD: /bin/bash /tmp/ollama-install.sh
$CALLER_USER ALL=(root) NOPASSWD: /usr/bin/bash /tmp/ollama-install.sh
$CALLER_USER ALL=(root) NOPASSWD: $SH /tmp/ai_manager_*.sh
$CALLER_USER ALL=(root) NOPASSWD: $BASH /tmp/ai_manager_*.sh
$CALLER_USER ALL=(root) NOPASSWD: /bin/sh /tmp/ai_manager_*.sh
$CALLER_USER ALL=(root) NOPASSWD: /usr/bin/sh /tmp/ai_manager_*.sh
$CALLER_USER ALL=(root) NOPASSWD: /bin/bash /tmp/ai_manager_*.sh
$CALLER_USER ALL=(root) NOPASSWD: /usr/bin/bash /tmp/ai_manager_*.sh

# Common install/build tools used by optional services.
$CALLER_USER ALL=(root) NOPASSWD: $PYTHON3
$CALLER_USER ALL=(root) NOPASSWD: $PYTHON3 *
$CALLER_USER ALL=(root) NOPASSWD: $GIT
$CALLER_USER ALL=(root) NOPASSWD: $GIT *
$CALLER_USER ALL=(root) NOPASSWD: $NPM
$CALLER_USER ALL=(root) NOPASSWD: $NPM *
$CALLER_USER ALL=(root) NOPASSWD: $NODE
$CALLER_USER ALL=(root) NOPASSWD: $NODE *
EOF

cat >> "$TMP" <<EOF
# Docker may not exist until the headless installer runs; grant expected paths now.
$CALLER_USER ALL=(root) NOPASSWD: /usr/bin/docker
$CALLER_USER ALL=(root) NOPASSWD: /usr/bin/docker *
$CALLER_USER ALL=(root) NOPASSWD: /usr/local/bin/docker
$CALLER_USER ALL=(root) NOPASSWD: /usr/local/bin/docker *
EOF

if [ -n "$DOCKER" ] && [ "$DOCKER" != "/usr/bin/docker" ] && [ "$DOCKER" != "/usr/local/bin/docker" ]; then
  cat >> "$TMP" <<EOF
$CALLER_USER ALL=(root) NOPASSWD: $DOCKER
$CALLER_USER ALL=(root) NOPASSWD: $DOCKER *
EOF
fi

chmod 440 "$TMP"

echo "DEBUG: generated sudoers file:"
sed 's/^/SUDOERS: /' "$TMP"

visudo -cf "$TMP" >/dev/null
install -o root -g root -m 0440 "$TMP" "$SUDOERS"
rm -f "$TMP"

echo "Installed sudoers file: $SUDOERS"
echo "Testing passwordless manager commands as $CALLER_USER..."

# Clear cached sudo auth for the caller, then test NOPASSWD.
sudo -u "$CALLER_USER" sudo -k || true

if sudo -u "$CALLER_USER" sudo -n systemctl --version >/dev/null 2>&1; then
  echo "systemctl sudo: OK"
else
  echo "systemctl sudo: FAILED"
  exit 10
fi

if sudo -u "$CALLER_USER" sudo -n pkill --version >/dev/null 2>&1; then
  echo "pkill sudo: OK"
else
  echo "pkill sudo: FAILED"
  exit 11
fi

if sudo -u "$CALLER_USER" sudo -n apt-get --version >/dev/null 2>&1; then
  echo "apt-get sudo: OK"
else
  echo "apt-get sudo: FAILED"
  exit 13
fi

echo "ollama installer shell sudo: rule prepared for /tmp/ollama-install.sh"
echo "manager temp installer sudo: rule prepared for /tmp/ai_manager_*.sh"

if [ -n "$DOCKER" ]; then
  if sudo -u "$CALLER_USER" sudo -n docker version >/dev/null 2>&1; then
    echo "docker sudo: OK"
  else
    echo "docker sudo: WARNING - Docker may not be running/reachable yet, but sudoers entry was written."
  fi
fi

echo "Sudo setup complete..."
"""


def install_sudo_permissions(manager, sudo_password, on_status=None):
    """Install AI Manager sudoers rules asynchronously.

    Called by AIManager.install_sudo_permissions_from_settings().
    """
    sudo_password = sudo_password or ""

    if not sudo_password.strip():
        _write_status(manager, on_status, "Enter your WSL/Linux sudo password first.", "#ff4444")
        return

    def worker():
        _write_status(manager, on_status, "Installing sudo access. Entered password is not saved.", "#ffaa00")

        script_name = f"/tmp/ai-manager-install-sudo-{int(time.time())}.sh"
        script_bytes = SUDO_INSTALL_SCRIPT.replace("\r\n", "\n").replace("\r", "\n").encode("utf-8")
        encoded = base64.b64encode(script_bytes).decode("ascii")

        try:
            write_cmd = (
                f"printf %s {encoded!r} | base64 -d > {script_name!r} && "
                f"chmod 700 {script_name!r} && "
                f"echo 'DEBUG: sudo installer script={script_name}'"
            )
            write_result = _wsl_run(write_cmd, timeout=12)
            for line in (write_result.stdout or "").splitlines():
                if line.strip():
                    try:
                        manager.write(f"[SETTINGS/SUDO] {line}")
                    except Exception:
                        pass

            if write_result.returncode != 0:
                _write_status(manager, on_status, "Sudo setup failed before install.", "#ff4444")
                return

            run_cmd = f"sudo -k; sudo -S -p '' bash {script_name!r}; rc=$?; rm -f {script_name!r}; exit $rc"
            proc = subprocess.Popen(
                ["wsl", "bash", "-lc", run_cmd],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
            )
            output, _ = proc.communicate(sudo_password + "\n", timeout=45)

            for line in output.splitlines():
                if line.strip():
                    try:
                        manager.write(f"[SETTINGS/SUDO] {line}")
                    except Exception:
                        pass

            ok, check_output = _passwordless_check()
            for line in str(check_output).splitlines():
                if line.strip():
                    try:
                        manager.write(f"[SETTINGS/SUDO] CHECK: {line}")
                    except Exception:
                        pass

            bad_markers = ["invalid option", "$'\\r'", "ERROR[SUDO-", "sudo: a password is required"]
            if any(marker in output for marker in bad_markers):
                _write_status(manager, on_status, "Sudo setup failed. Check terminal output.", "#ff4444")
            elif proc.returncode == 0 and ok:
                _write_status(manager, on_status, "Sudo access installed successfully.", "#00ff99")
            elif proc.returncode == 1:
                _write_status(manager, on_status, "Sudo setup failed. Wrong password or sudo denied.", "#ff4444")
            else:
                _write_status(manager, on_status, f"Sudo setup failed with code {proc.returncode}. Check terminal output.", "#ff4444")

        except subprocess.TimeoutExpired:
            _write_status(manager, on_status, "Sudo setup timed out. Check WSL/sudo prompt state.", "#ff4444")
        except Exception as e:
            _write_status(manager, on_status, f"Sudo setup error: {e}", "#ff4444")

    threading.Thread(target=worker, daemon=True).start()
