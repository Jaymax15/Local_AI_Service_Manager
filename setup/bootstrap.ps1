# AI Server Manager - Bootstrap Installer
# This tiny script downloads and runs setup/install_prereqs.ps1 from the GitHub repo.
# Recommended user command:
#   $env:AI_SM_REPO_RAW_BASE="https://raw.githubusercontent.com/YOUR_GITHUB_USERNAME/YOUR_REPO_NAME/main"; irm "$env:AI_SM_REPO_RAW_BASE/setup/bootstrap.ps1" | iex

$ErrorActionPreference = "Stop"

# Fallback only. Prefer setting AI_SM_REPO_RAW_BASE in the one-line command.
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

function Write-SetupHeader {
    Clear-Host
    Write-Host ""
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host " AI Server Manager - First Time Windows Setup" -ForegroundColor Cyan
    Write-Host "============================================================" -ForegroundColor Cyan
    Write-Host ""
}

Write-SetupHeader

if ($RepoRawBase -like "*YOUR_GITHUB_USERNAME*" -or $RepoRawBase -like "*YOUR_REPO_NAME*") {
    Write-Host "ERROR[SETUP-001]: GitHub repo URL has not been configured." -ForegroundColor Red
    Write-Host ""
    Write-Host "Set AI_SM_REPO_RAW_BASE before running bootstrap.ps1, for example:" -ForegroundColor Yellow
    Write-Host '$env:AI_SM_REPO_RAW_BASE="https://raw.githubusercontent.com/YOUR_NAME/YOUR_REPO/main"; irm "$env:AI_SM_REPO_RAW_BASE/setup/bootstrap.ps1" | iex' -ForegroundColor White
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
    Invoke-WebRequest -Uri $InstallerUrl -UseBasicParsing -OutFile $InstallerPath
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

if (-not (Test-IsAdmin)) {
    Write-Host ""
    Write-Host "Administrator permission is required." -ForegroundColor Yellow
    Write-Host "A Windows UAC prompt should appear now. Click Yes to continue." -ForegroundColor Yellow
    Write-Host ""

    $encodedCommand = @"
`$env:AI_SM_REPO_RAW_BASE = '$RepoRawBase'
& '$InstallerPath'
Write-Host ''
Write-Host 'Setup window can now be closed.' -ForegroundColor Green
Read-Host 'Press Enter to close'
"@

    $bytes = [System.Text.Encoding]::Unicode.GetBytes($encodedCommand)
    $encoded = [Convert]::ToBase64String($bytes)

    Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList @(
        "-NoProfile",
        "-ExecutionPolicy", "Bypass",
        "-EncodedCommand", $encoded
    )
    return
}

& $InstallerPath
