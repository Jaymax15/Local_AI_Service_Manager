# AI Server Manager - Windows Prerequisite Installer
# Installs/checks only Windows prerequisites:
# - WSL / Virtual Machine Platform
# - Ubuntu WSL distro
# - Python
# - Docker Desktop
#
# This script does NOT install Ollama or AI services.
# Run this from an Administrator PowerShell window.

$ErrorActionPreference = "Continue"

$Script:TotalSteps = 9
$Script:CurrentStep = 0
$Script:NeedsReboot = $false
$Script:Warnings = New-Object System.Collections.Generic.List[string]
$Script:Errors = New-Object System.Collections.Generic.List[string]

$LogRoot = Join-Path $env:LOCALAPPDATA "AI_Server_Manager_Setup"
$LogDir = Join-Path $LogRoot ("logs_" + (Get-Date -Format "yyyyMMdd_HHmmss"))
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir "setup.log"

function Write-Log {
    param(
        [string]$Message,
        [string]$Level = "INFO",
        [ConsoleColor]$Color = [ConsoleColor]::Gray
    )
    $line = "[{0}] [{1}] {2}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Level, $Message
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
    Write-Host $Message -ForegroundColor $Color
}

function Step-Start {
    param([string]$Name)
    $Script:CurrentStep++
    $pct = [int](($Script:CurrentStep - 1) / $Script:TotalSteps * 100)
    Write-Progress -Activity "AI Server Manager setup" -Status $Name -PercentComplete $pct
    Write-Host ""
    Write-Host ("[{0}/{1}] {2}" -f $Script:CurrentStep, $Script:TotalSteps, $Name) -ForegroundColor Cyan
    Write-Host ("-" * 70) -ForegroundColor DarkGray
    Add-Content -Path $LogFile -Value ""
    Write-Log ("STEP {0}/{1}: {2}" -f $Script:CurrentStep, $Script:TotalSteps, $Name) "STEP" "Cyan"
}

function Step-Done {
    param([string]$Name)
    $pct = [int](($Script:CurrentStep) / $Script:TotalSteps * 100)
    Write-Progress -Activity "AI Server Manager setup" -Status $Name -PercentComplete $pct
}

function Add-Warning {
    param([string]$Message)
    $Script:Warnings.Add($Message) | Out-Null
    Write-Log $Message "WARN" "Yellow"
}

function Add-Error {
    param([string]$Message)
    $Script:Errors.Add($Message) | Out-Null
    Write-Log $Message "ERROR" "Red"
}

function Run-Command {
    param(
        [string]$File,
        [string[]]$Arguments,
        [string]$Label,
        [switch]$IgnoreFailure
    )

    $argLine = $Arguments -join " "
    Write-Log "Running: $File $argLine" "CMD" "DarkGray"

    try {
        $proc = Start-Process -FilePath $File -ArgumentList $Arguments -Wait -PassThru -NoNewWindow
        $code = $proc.ExitCode
        Write-Log "$Label exit code: $code" "CMD" "DarkGray"
        if ($code -ne 0 -and -not $IgnoreFailure) {
            Add-Error "ERROR[SETUP-CMD-$code]: $Label failed."
        }
        return $code
    } catch {
        if (-not $IgnoreFailure) {
            Add-Error "ERROR[SETUP-EXCEPTION]: $Label failed: $($_.Exception.Message)"
        } else {
            Add-Warning "$Label warning: $($_.Exception.Message)"
        }
        return 9999
    }
}

function Test-CommandExists {
    param([string]$Command)
    $cmd = Get-Command $Command -ErrorAction SilentlyContinue
    return $null -ne $cmd
}

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-FeatureState {
    param([string]$FeatureName)
    try {
        $info = Get-WindowsOptionalFeature -Online -FeatureName $FeatureName -ErrorAction Stop
        return $info.State
    } catch {
        return "Unknown"
    }
}

function Ensure-Feature {
    param(
        [string]$FeatureName,
        [string]$FriendlyName
    )

    $state = Get-FeatureState $FeatureName
    if ($state -eq "Enabled") {
        Write-Log "$FriendlyName is already enabled." "OK" "Green"
        return
    }

    Write-Log "$FriendlyName is not enabled. Enabling..." "INFO" "Yellow"
    $code = Run-Command -File "dism.exe" -Arguments @(
        "/online",
        "/enable-feature",
        "/featurename:$FeatureName",
        "/all",
        "/norestart"
    ) -Label "Enable $FriendlyName" -IgnoreFailure

    if ($code -eq 0) {
        Write-Log "$FriendlyName enabled." "OK" "Green"
        $Script:NeedsReboot = $true
    } elseif ($code -eq 3010) {
        Write-Log "$FriendlyName enabled. Reboot required." "OK" "Yellow"
        $Script:NeedsReboot = $true
    } else {
        Add-Error "ERROR[FEATURE-$FeatureName]: Could not enable $FriendlyName. Exit code: $code"
    }
}

function Winget-InstallOrUpgrade {
    param(
        [string]$PackageId,
        [string]$DisplayName,
        [string[]]$ExtraInstallArgs = @()
    )

    if (-not (Test-CommandExists "winget")) {
        Add-Error "ERROR[WINGET-001]: winget is not available. Install App Installer from Microsoft Store, then rerun setup."
        return
    }

    Write-Log "Checking $DisplayName with winget..." "INFO" "Gray"
    $listOutput = & winget list --id $PackageId -e --accept-source-agreements 2>&1
    $installed = ($LASTEXITCODE -eq 0 -and ($listOutput -join "`n") -match [regex]::Escape($PackageId))

    if ($installed) {
        Write-Log "$DisplayName is already installed. Trying upgrade..." "INFO" "Yellow"
        & winget upgrade --id $PackageId -e --silent --accept-package-agreements --accept-source-agreements 2>&1 | Tee-Object -FilePath $LogFile -Append
        if ($LASTEXITCODE -eq 0) {
            Write-Log "$DisplayName is installed/up to date." "OK" "Green"
        } else {
            Add-Warning "$DisplayName upgrade was skipped or failed. It may already be current. winget exit code: $LASTEXITCODE"
        }
        return
    }

    Write-Log "$DisplayName is not installed. Installing..." "INFO" "Yellow"
    $args = @(
        "install",
        "--id", $PackageId,
        "-e",
        "--silent",
        "--accept-package-agreements",
        "--accept-source-agreements"
    ) + $ExtraInstallArgs

    & winget @args 2>&1 | Tee-Object -FilePath $LogFile -Append
    if ($LASTEXITCODE -eq 0) {
        Write-Log "$DisplayName installed." "OK" "Green"
    } else {
        Add-Error "ERROR[WINGET-$PackageId]: Failed to install $DisplayName. winget exit code: $LASTEXITCODE"
    }
}

function Install-PythonBestAvailable {
    # Prefer newer versions, but fall back cleanly if a package is not available.
    # You can adjust this list later as Python versions change.
    $pythonIds = @(
        "Python.Python.3.14",
        "Python.Python.3.13",
        "Python.Python.3.12"
    )

    foreach ($id in $pythonIds) {
        Write-Log "Trying Python package: $id" "INFO" "Gray"
        $search = & winget show --id $id -e --accept-source-agreements 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Log "$id not available from winget on this machine/source." "INFO" "DarkGray"
            continue
        }

        Winget-InstallOrUpgrade -PackageId $id -DisplayName $id -ExtraInstallArgs @("--scope", "machine")
        return
    }

    Add-Error "ERROR[PYTHON-001]: Could not find a supported Python package in winget."
}

function Wait-Short {
    param([int]$Seconds, [string]$Message)
    for ($i = 1; $i -le $Seconds; $i++) {
        $pct = [int](($i / $Seconds) * 100)
        Write-Progress -Activity $Message -Status "$i / $Seconds seconds" -PercentComplete $pct
        Start-Sleep -Seconds 1
    }
    Write-Progress -Activity $Message -Completed
}

Clear-Host
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " AI Server Manager - Windows Prerequisite Setup" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "This installs/checks: WSL, Ubuntu, Python, and Docker Desktop." -ForegroundColor Gray
Write-Host "Log file: $LogFile" -ForegroundColor DarkGray
Write-Host ""

if (-not (Test-IsAdmin)) {
    Add-Error "ERROR[ADMIN-001]: This installer must run as Administrator. Close this window, open PowerShell as Administrator, and run the one-line setup command again."
    exit 1
}

Step-Start "Checking Windows and PowerShell"
try {
    $os = Get-CimInstance Win32_OperatingSystem
    Write-Log ("Windows: {0} build {1}" -f $os.Caption, $os.BuildNumber) "OK" "Green"
    Write-Log ("PowerShell: {0}" -f $PSVersionTable.PSVersion) "OK" "Green"
} catch {
    Add-Warning "Could not read Windows version: $($_.Exception.Message)"
}
Step-Done "Windows check complete"

Step-Start "Checking winget"
if (Test-CommandExists "winget") {
    $wingetVersion = (& winget --version 2>$null)
    Write-Log "winget found: $wingetVersion" "OK" "Green"
} else {
    Add-Error "ERROR[WINGET-001]: winget not found. Install 'App Installer' from Microsoft Store, then run this setup again."
}
Step-Done "winget check complete"

Step-Start "Enabling WSL Windows features"
Ensure-Feature -FeatureName "Microsoft-Windows-Subsystem-Linux" -FriendlyName "Windows Subsystem for Linux"
Ensure-Feature -FeatureName "VirtualMachinePlatform" -FriendlyName "Virtual Machine Platform"
Step-Done "Windows features checked"

Step-Start "Installing/updating WSL"
if (Test-CommandExists "wsl.exe") {
    Write-Log "wsl.exe found." "OK" "Green"
    Run-Command -File "wsl.exe" -Arguments @("--update") -Label "WSL update" -IgnoreFailure | Out-Null
    Run-Command -File "wsl.exe" -Arguments @("--set-default-version", "2") -Label "Set WSL default version 2" -IgnoreFailure | Out-Null
} else {
    Add-Warning "wsl.exe not found yet. Running wsl --install."
    Run-Command -File "wsl.exe" -Arguments @("--install", "--no-launch") -Label "WSL install" -IgnoreFailure | Out-Null
    $Script:NeedsReboot = $true
}
Step-Done "WSL install/update complete"

Step-Start "Checking/installing Ubuntu WSL distro"
$distroText = ""
try {
    $distroText = (& wsl.exe -l -q 2>$null) -join "`n"
} catch {
    $distroText = ""
}

if ($distroText -match "Ubuntu") {
    Write-Log "Ubuntu WSL distro appears to be installed." "OK" "Green"
} else {
    Write-Log "Ubuntu WSL distro not found. Installing Ubuntu..." "INFO" "Yellow"
    Run-Command -File "wsl.exe" -Arguments @("--install", "-d", "Ubuntu", "--no-launch") -Label "Install Ubuntu WSL" -IgnoreFailure | Out-Null
    Add-Warning "Ubuntu may need first-run setup after reboot/opening Ubuntu. The user may be asked to create a Linux username/password."
    $Script:NeedsReboot = $true
}
Step-Done "Ubuntu check complete"

Step-Start "Installing/updating Python"
if (Test-CommandExists "winget") {
    Install-PythonBestAvailable
} else {
    Add-Error "ERROR[PYTHON-002]: Python install skipped because winget is missing."
}
try {
    $pyVersion = (& py --version 2>$null)
    if ($pyVersion) {
        Write-Log "Python launcher check: $pyVersion" "OK" "Green"
    } else {
        Add-Warning "Python launcher was not detected in this PowerShell session. Open a new terminal after install."
    }
} catch {
    Add-Warning "Python check failed. Open a new terminal after install."
}
Step-Done "Python check complete"

Step-Start "Installing/updating Docker Desktop"
if (Test-CommandExists "winget") {
    Winget-InstallOrUpgrade -PackageId "Docker.DockerDesktop" -DisplayName "Docker Desktop"
} else {
    Add-Error "ERROR[DOCKER-001]: Docker Desktop install skipped because winget is missing."
}
Step-Done "Docker Desktop install/update complete"

Step-Start "Starting Docker Desktop if available"
$dockerDesktopCandidates = @(
    "$env:ProgramFiles\Docker\Docker\Docker Desktop.exe",
    "${env:ProgramFiles(x86)}\Docker\Docker\Docker Desktop.exe",
    "$env:LOCALAPPDATA\Docker\Docker Desktop.exe"
)

$dockerDesktopExe = $null
foreach ($candidate in $dockerDesktopCandidates) {
    if ($candidate -and (Test-Path $candidate)) {
        $dockerDesktopExe = $candidate
        break
    }
}

if ($dockerDesktopExe) {
    Write-Log "Starting Docker Desktop: $dockerDesktopExe" "INFO" "Yellow"
    try {
        Start-Process -FilePath $dockerDesktopExe
        Wait-Short -Seconds 8 -Message "Waiting briefly for Docker Desktop"
        Write-Log "Docker Desktop start requested." "OK" "Green"
    } catch {
        Add-Warning "Could not start Docker Desktop automatically: $($_.Exception.Message)"
    }
} else {
    Add-Warning "Docker Desktop executable not found yet. It may appear after reboot or installer completion."
}
Step-Done "Docker Desktop start step complete"

Step-Start "Final checks"
try {
    $wslStatus = (& wsl.exe --status 2>&1) -join "`n"
    Write-Log "WSL status:`n$wslStatus" "INFO" "Gray"
} catch {
    Add-Warning "Could not read WSL status."
}

try {
    $pyVersion = (& py --version 2>&1) -join "`n"
    Write-Log "Python: $pyVersion" "INFO" "Gray"
} catch {
    Add-Warning "Python not visible in current session yet."
}

try {
    $dockerVersion = (& docker --version 2>&1) -join "`n"
    Write-Log "Docker CLI: $dockerVersion" "INFO" "Gray"
} catch {
    Add-Warning "Docker CLI not visible in current session yet. This may be fixed after opening a new terminal or rebooting."
}

Step-Done "Final checks complete"
Write-Progress -Activity "AI Server Manager setup" -Completed

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " Setup Summary" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

if ($Script:Errors.Count -eq 0) {
    Write-Host "No fatal setup errors were recorded." -ForegroundColor Green
} else {
    Write-Host "Errors:" -ForegroundColor Red
    foreach ($err in $Script:Errors) {
        Write-Host " - $err" -ForegroundColor Red
    }
}

if ($Script:Warnings.Count -gt 0) {
    Write-Host ""
    Write-Host "Warnings / user actions:" -ForegroundColor Yellow
    foreach ($warn in $Script:Warnings) {
        Write-Host " - $warn" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "Log saved to:" -ForegroundColor Gray
Write-Host "  $LogFile" -ForegroundColor White

if ($Script:NeedsReboot) {
    Write-Host ""
    Write-Host "A reboot is recommended before running AI Server Manager." -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Next steps:" -ForegroundColor Cyan
Write-Host "  1. Reboot if requested." -ForegroundColor White
Write-Host "  2. Open Docker Desktop once and complete its first-run setup if asked." -ForegroundColor White
Write-Host "  3. Run AI Server Manager." -ForegroundColor White
Write-Host ""
