# AI Server Manager - Bootstrap Installer V3
# This bootstrap avoids the common PowerShell policy problem by launching the downloaded
# installer in a new PowerShell process with -ExecutionPolicy Bypass.

$ErrorActionPreference = "Stop"

$DefaultRepoRawBase = "https://raw.githubusercontent.com/YOUR_GITHUB_USERNAME/YOUR_REPO_NAME/main"
$RepoRawBase = $env:AI_SM_REPO_RAW_BASE
if ([string]::IsNullOrWhiteSpace($RepoRawBase)) {
    $RepoRawBase = $DefaultRepoRawBase
}

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

Clear-Host
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " AI Server Manager - First Time Windows Setup" -ForegroundColor Cyan
Write-Host " Bootstrap V3" -ForegroundColor DarkGray
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

if ($RepoRawBase -like "*YOUR_GITHUB_USERNAME*" -or $RepoRawBase -like "*YOUR_REPO_NAME*") {
    Write-Host "ERROR[SETUP-001]: GitHub repo URL has not been configured." -ForegroundColor Red
    Write-Host '$env:AI_SM_REPO_RAW_BASE="https://raw.githubusercontent.com/Jaymax15/Local_AI_Service_Manager/main"; irm "$env:AI_SM_REPO_RAW_BASE/setup/bootstrap.ps1" | iex' -ForegroundColor White
    throw "Repository URL not configured."
}

$InstallerUrl = "$RepoRawBase/setup/install_prereqs.ps1"
$WorkDir = Join-Path $env:TEMP "AI_Server_Manager_Setup"
$InstallerPath = Join-Path $WorkDir "install_prereqs.ps1"

New-Item -ItemType Directory -Force -Path $WorkDir | Out-Null

Write-Host "Repository raw base:" -ForegroundColor DarkGray
Write-Host "  $RepoRawBase" -ForegroundColor Gray
Write-Host ""
Write-Host "Downloading installer..." -ForegroundColor Cyan
Write-Host "  $InstallerUrl" -ForegroundColor Gray

try {
    # Add a cache buster so GitHub/raw/CDN does not serve an older installer during testing.
    $CacheBuster = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
    Invoke-WebRequest -Uri "$InstallerUrl`?v=$CacheBuster" -UseBasicParsing -OutFile $InstallerPath
} catch {
    Write-Host ""
    Write-Host "ERROR[SETUP-002]: Could not download install_prereqs.ps1" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    throw
}

if (-not (Test-Path $InstallerPath)) {
    Write-Host "ERROR[SETUP-003]: Installer file was not created." -ForegroundColor Red
    throw "Installer download failed."
}

# Remove Mark-of-the-Web if Windows added one.
try {
    Unblock-File -Path $InstallerPath -ErrorAction SilentlyContinue
} catch {}

Write-Host ""
Write-Host "Installer saved to:" -ForegroundColor DarkGray
Write-Host "  $InstallerPath" -ForegroundColor Gray

if (-not (Test-IsAdmin)) {
    Write-Host ""
    Write-Host "Administrator permission is required." -ForegroundColor Yellow
    Write-Host "A Windows UAC prompt should appear now. Click Yes to continue." -ForegroundColor Yellow
    Write-Host ""

    Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-File", "`"$InstallerPath`""
    )
    return
}

Write-Host ""
Write-Host "Running installer with ExecutionPolicy Bypass..." -ForegroundColor Cyan

Start-Process -FilePath "powershell.exe" -Wait -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy", "Bypass",
    "-File", "`"$InstallerPath`""
)
