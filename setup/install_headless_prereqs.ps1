# AI Server Manager - Headless Docker WSL Setup Launcher
# PowerShell launcher only. The real Docker install runs inside WSL/Linux.

$ErrorActionPreference = "Stop"

function Write-Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

Write-Host "============================================================"
Write-Host " AI Server Manager - Headless Docker WSL Setup"
Write-Host "============================================================"

$repoRaw = $env:AI_SM_REPO_RAW_BASE
if ([string]::IsNullOrWhiteSpace($repoRaw)) {
    $repoRaw = "https://raw.githubusercontent.com/Jaymax15/Local_AI_Service_Manager/main"
}

$scriptUrl = "$repoRaw/setup/install_headless_prereqs.sh"

Write-Step "Checking WSL"
wsl.exe --status | Out-Host

$defaultCheck = & wsl.exe -- bash -lc "cat /etc/os-release 2>/dev/null | grep '^PRETTY_NAME=' | cut -d= -f2- | tr -d '""'"
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($defaultCheck)) {
    throw "Could not start the default WSL distro. Install Ubuntu or run: wsl --set-default Ubuntu-24.04"
}

Write-Host "Using WSL default distro: $defaultCheck" -ForegroundColor Green

Write-Step "Running Linux headless Docker installer inside WSL"
Write-Host "Linux installer:"
Write-Host "  $scriptUrl"

$bashCommand = @"
set -e
url='$scriptUrl'
echo "[HEADLESS] Downloading `$url"

if ! command -v curl >/dev/null 2>&1; then
  sudo apt-get update
  sudo apt-get install -y curl ca-certificates
fi

curl -fsSL "`$url" -o /tmp/ai-sm-headless-install.sh
chmod +x /tmp/ai-sm-headless-install.sh
/tmp/ai-sm-headless-install.sh
"@

wsl.exe -- bash -lc $bashCommand

if ($LASTEXITCODE -ne 0) {
    throw "Headless Docker installer failed inside WSL."
}

Write-Step "Finishing"
Write-Host "Now run this once so WSL reloads Docker/group/systemd changes:" -ForegroundColor Yellow
Write-Host "  wsl --shutdown" -ForegroundColor White
Write-Host "Then reopen AI Server Manager." -ForegroundColor Green
