# AI Server Manager - Headless Docker WSL Setup Launcher
# PowerShell launcher only. Downloads the Linux installer, sends it to WSL as base64, then runs it.

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

# Avoid Bash quoting here. Run cat directly through WSL.
$osRelease = & wsl.exe -- cat /etc/os-release 2>$null
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace(($osRelease -join "`n"))) {
    throw "Could not start the default WSL distro. Install Ubuntu or run: wsl --set-default Ubuntu-24.04"
}

$prettyName = ($osRelease | Where-Object { $_ -like "PRETTY_NAME=*" } | Select-Object -First 1)
$prettyName = $prettyName -replace '^PRETTY_NAME=', ''
$prettyName = $prettyName -replace '"', ''

if ([string]::IsNullOrWhiteSpace($prettyName)) {
    $prettyName = "WSL Linux"
}

Write-Host "Using WSL default distro: $prettyName" -ForegroundColor Green

Write-Step "Downloading Linux headless Docker installer"
Write-Host "Linux installer:"
Write-Host "  $scriptUrl"

$shText = (Invoke-WebRequest -UseBasicParsing -Uri $scriptUrl).Content

if ([string]::IsNullOrWhiteSpace($shText)) {
    throw "Downloaded Linux installer is empty."
}

if ($shText -notmatch "Headless Docker Engine Installer") {
    Write-Host "WARNING: Downloaded Linux installer did not contain expected header." -ForegroundColor Yellow
}

# Normalize line endings and encode so Bash receives exact script text.
$shText = $shText.Replace("`r`n", "`n").Replace("`r", "`n")
$encoded = [Convert]::ToBase64String([System.Text.Encoding]::UTF8.GetBytes($shText))

Write-Step "Running Linux installer inside WSL"

$bashCommand = "set -e; printf '%s' '$encoded' | base64 -d > /tmp/ai-sm-headless-install.sh; chmod +x /tmp/ai-sm-headless-install.sh; /tmp/ai-sm-headless-install.sh"

wsl.exe -- bash -lc $bashCommand

if ($LASTEXITCODE -ne 0) {
    throw "Headless Docker installer failed inside WSL."
}

Write-Step "Finishing"
Write-Host "Now run this once so WSL reloads Docker/group/systemd changes:" -ForegroundColor Yellow
Write-Host "  wsl --shutdown" -ForegroundColor White
Write-Host "Then reopen AI Server Manager." -ForegroundColor Green
