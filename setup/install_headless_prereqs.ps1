# AI Server Manager - Headless WSL Docker Setup
# Installs Docker Engine directly inside the default WSL Ubuntu distro.
# Does NOT install or require Docker Desktop.

$ErrorActionPreference = "Stop"

function Write-Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

Write-Host "============================================================"
Write-Host " AI Server Manager - Headless Docker WSL Setup"
Write-Host "============================================================"

Write-Step "Checking WSL"
wsl.exe --status | Out-Host

# Use the default WSL distro directly instead of parsing `wsl -l -q`.
# Some Windows PowerShell/WSL setups return hidden/null characters in distro names.
# The name looks correct but `wsl -d <name>` can fail with WSL_E_DISTRO_NOT_FOUND.
$defaultCheck = & wsl.exe -- bash -lc "cat /etc/os-release 2>/dev/null | grep '^PRETTY_NAME=' | cut -d= -f2- | tr -d '\"'"
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($defaultCheck)) {
    throw "Could not start the default WSL distro. Install Ubuntu or run: wsl --set-default Ubuntu-24.04"
}

Write-Host "Using WSL default distro: $defaultCheck" -ForegroundColor Green

Write-Step "Optional Docker Desktop removal"
$dockerDesktop = winget list --id Docker.DockerDesktop --accept-source-agreements 2>$null

if ($LASTEXITCODE -eq 0 -and $dockerDesktop -match "Docker") {
    Write-Host "Docker Desktop appears to be installed."
    $answer = Read-Host "Uninstall Docker Desktop now? Type YES to uninstall"

    if ($answer -eq "YES") {
        winget uninstall --id Docker.DockerDesktop -e --accept-source-agreements
        Write-Host "Docker Desktop uninstall requested. A reboot may be needed later." -ForegroundColor Yellow
    } else {
        Write-Host "Skipped Docker Desktop uninstall." -ForegroundColor Yellow
    }
} else {
    Write-Host "Docker Desktop not found by winget, continuing."
}

Write-Step "Installing headless Docker Engine inside WSL"

$bash = @'
set -euo pipefail

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
echo "[HEADLESS] Run 'wsl --shutdown' from PowerShell, then reopen WSL/AI Server Manager."
'@

# Windows PowerShell 5.1 does not support Bash-style "< file" redirection.
# Send the Bash installer to WSL as base64 instead.
$bashNormalized = $bash.Replace("`r`n", "`n").Replace("`r", "`n")
$encoded = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($bashNormalized))
$wslCommand = "printf '%s' '$encoded' | base64 -d > /tmp/ai-sm-headless-install.sh && chmod +x /tmp/ai-sm-headless-install.sh && /tmp/ai-sm-headless-install.sh"

wsl.exe -- bash -lc $wslCommand

Write-Step "Finishing"
Write-Host "Now run this once so WSL reloads Docker/group/systemd changes:" -ForegroundColor Yellow
Write-Host "  wsl --shutdown" -ForegroundColor White
Write-Host "Then reopen AI Server Manager." -ForegroundColor Green
