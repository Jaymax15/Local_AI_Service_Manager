#!/usr/bin/env bash
set -euo pipefail

echo "============================================================"
echo " AI Server Manager - Headless Docker Engine Installer"
echo "============================================================"

echo "[HEADLESS] distro=$(cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2- | tr -d '"')"
echo "[HEADLESS] user=$(whoami)"

echo "[HEADLESS] Checking for Docker Desktop WSL shim"
if [ -L /usr/bin/docker ]; then
  target="$(readlink /usr/bin/docker 2>/dev/null || true)"
  real="$(readlink -f /usr/bin/docker 2>/dev/null || true)"

  if echo "$target $real" | grep -qiE '/mnt/wsl/docker-desktop|/mnt/c/Program Files/Docker'; then
    echo "[HEADLESS] Removing Docker Desktop WSL shim: /usr/bin/docker -> $target"
    sudo rm -f /usr/bin/docker
  fi
fi

echo "[HEADLESS] Removing conflicting Ubuntu Docker packages if present"
old_pkgs="$(dpkg-query -W -f='${binary:Package}\n' docker.io docker-compose docker-compose-v2 docker-doc podman-docker containerd runc 2>/dev/null | tr '\n' ' ' || true)"

if [ -n "$old_pkgs" ]; then
  sudo apt-get remove -y $old_pkgs || true
else
  echo "[HEADLESS] No conflicting distro Docker packages found."
fi

echo "[HEADLESS] Updating apt and installing repo prerequisites"
sudo apt-get update
sudo apt-get install -y ca-certificates curl

echo "[HEADLESS] Adding Docker official apt repository"
sudo install -m 0755 -d /etc/apt/keyrings
sudo rm -f /etc/apt/keyrings/docker.asc
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

codename="$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")"
arch="$(dpkg --print-architecture)"

cat <<EOF | sudo tee /etc/apt/sources.list.d/docker.sources >/dev/null
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $codename
Components: stable
Architectures: $arch
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt-get update

echo "[HEADLESS] Installing Docker Engine packages"
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

echo "[HEADLESS] Enabling systemd in WSL if needed"
if ! grep -qi 'systemd=true' /etc/wsl.conf 2>/dev/null; then
  printf "[boot]\nsystemd=true\n" | sudo tee /etc/wsl.conf >/dev/null
  echo "[HEADLESS] Wrote /etc/wsl.conf systemd=true"
fi

echo "[HEADLESS] Starting Docker Engine"
sudo systemctl enable --now docker >/dev/null 2>&1 || sudo service docker start

echo "[HEADLESS] Adding current WSL user to docker group"
sudo groupadd -f docker || true
sudo usermod -aG docker "$(whoami)" || true

echo "[HEADLESS] Verifying Docker Engine"
sudo docker info >/dev/null
sudo docker compose version

echo "[HEADLESS] Docker Engine installed successfully."
echo "[HEADLESS] Run this from PowerShell now:"
echo "  wsl --shutdown"
echo "[HEADLESS] Then reopen WSL or AI Server Manager."
