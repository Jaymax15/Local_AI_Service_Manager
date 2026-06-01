# AI Server Manager - Headless Docker WSL Setup Launcher
# Downloads the Linux installer script and runs it inside the default WSL distro.

$ErrorActionPreference = "Stop"

function Write-Step($msg) {
    Write-Host ""
    Write-Host "==> $msg" -ForegroundColor Cyan
}

function Convert-ToWslPath($windowsPath) {
    $full = [System.IO.Path]::GetFullPath($windowsPath)

    if ($full -match '^([A-Za-z]):\\(.*)$') {
        $drive = $matches[1].ToLower()
        $rest = $matches[2] -replace '\\', '/'
        return "/mnt/$drive/$rest"
    }

    throw "Could not convert Windows path to WSL path: $windowsPath"
}

function Quote-Bash($text) {
    return "'" + ($text.Replace("'", "'\''")) + "'"
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

$wslTempSh = Convert-ToWslPath $tempSh
$quotedWslTempSh = Quote-Bash $wslTempSh

Write-Step "Running installer inside WSL"
$cmd = "sed 's/\r$//' $quotedWslTempSh > /tmp/ai-sm-headless-install.sh && chmod +x /tmp/ai-sm-headless-install.sh && /tmp/ai-sm-headless-install.sh"

wsl.exe -- bash -lc $cmd

Write-Step "Finishing"
Write-Host "Now run this once so WSL reloads Docker/group/systemd changes:" -ForegroundColor Yellow
Write-Host "  wsl --shutdown" -ForegroundColor White
Write-Host "Then reopen AI Server Manager." -ForegroundColor Green
