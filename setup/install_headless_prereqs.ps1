# AI Server Manager - Headless Docker WSL Setup Launcher
# Downloads the Linux installer script and runs it inside the default WSL distro.

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

Write-Step "Checking WSL"
wsl.exe --status | Out-Host

$defaultCheck = & wsl.exe -- bash -lc "cat /etc/os-release 2>/dev/null | grep '^PRETTY_NAME=' | cut -d= -f2- | tr -d '\"'"
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($defaultCheck)) {
    throw "Could not start the default WSL distro. Install Ubuntu or run: wsl --set-default Ubuntu-24.04"
}

Write-Host "Using WSL default distro: $defaultCheck" -ForegroundColor Green

Write-Step "Downloading Linux headless Docker installer"

$scriptUrl = "$repoRaw/setup/install_headless_prereqs.sh"
$tempSh = Join-Path $env:TEMP "ai-sm-headless-$PID.sh"

Write-Host "Downloading:"
Write-Host "  $scriptUrl"

Invoke-WebRequest -UseBasicParsing -Uri $scriptUrl -OutFile $tempSh

if (!(Test-Path $tempSh)) {
    throw "Failed to download Linux installer script."
}

Write-Step "Running installer inside WSL"

# Convert Windows temp path to WSL path using WSL itself.
$tempShEscaped = $tempSh.Replace("\", "\\")
$wslTempSh = & wsl.exe -- bash -lc "wslpath -a '$tempShEscaped'"

if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($wslTempSh)) {
    throw "Failed to convert temp script path to WSL path."
}

$wslTempSh = $wslTempSh.Trim()

# No sed, no PowerShell-hostile single-quote regex.
# Bash reads the downloaded .sh file, strips CR if present, writes it to /tmp, then runs it.
$cmd = "tr -d '\r' < ""$wslTempSh"" > /tmp/ai-sm-headless-install.sh; chmod +x /tmp/ai-sm-headless-install.sh; /tmp/ai-sm-headless-install.sh"

wsl.exe -- bash -lc $cmd

Write-Step "Finishing"
Write-Host "Now run this once so WSL reloads Docker/group/systemd changes:" -ForegroundColor Yellow
Write-Host "  wsl --shutdown" -ForegroundColor White
Write-Host "Then reopen AI Server Manager." -ForegroundColor Green
