# Auto Clicker installer (Windows 10/11). Run it by double-clicking install.bat.
#
# What it does, in plain terms:
#   1. Finds Python 3.8+ (with tkinter). If missing, installs it with winget,
#      or opens the Python download page if winget isn't available.
#   2. Copies the app to %LOCALAPPDATA%\AutoClicker
#   3. Creates "Auto Clicker" shortcuts on the Desktop and in the Start menu
#   4. Launches it.
# Nothing is downloaded except Python itself (from winget), and nothing outside
# your user profile is changed.  Run uninstall.bat to remove everything.

param(
    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'AutoClicker'),
    [string]$DesktopDir = [Environment]::GetFolderPath('Desktop'),
    [string]$StartMenuDir = (Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'),
    [switch]$Uninstall,
    [switch]$NoLaunch,
    [switch]$NoPause
)

$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$appName = 'Auto Clicker'
$shortcuts = @((Join-Path $DesktopDir "$appName.lnk"), (Join-Path $StartMenuDir "$appName.lnk"))

function Finish($code) {
    if (-not $NoPause) { Write-Host ''; Read-Host 'Press Enter to close' | Out-Null }
    exit $code
}

function Test-Python($exe, $prefixArgs) {
    # Returns the real python.exe path if this candidate is Python 3.8+ with tkinter.
    try {
        $out = & $exe @prefixArgs -c "import sys, tkinter; assert sys.version_info >= (3, 8); print(sys.executable)" 2>$null
        if ($LASTEXITCODE -eq 0 -and $out) { return ($out | Select-Object -Last 1).ToString().Trim() }
    } catch { }
    return $null
}

function Find-Python {
    $candidates = @(@('py', @('-3')), @('python', @()), @('python3', @()))
    foreach ($c in $candidates) {
        if (Get-Command $c[0] -ErrorAction SilentlyContinue) {
            $p = Test-Python $c[0] $c[1]
            if ($p) { return $p }
        }
    }
    # Per-user install folders (PATH may not be refreshed right after an install)
    $roots = @((Join-Path $env:LOCALAPPDATA 'Programs\Python'), (Join-Path $env:LOCALAPPDATA 'Python'))
    foreach ($r in $roots) {
        $dirs = Get-ChildItem $r -Directory -ErrorAction SilentlyContinue | Sort-Object Name -Descending
        foreach ($d in $dirs) {
            $exe = Join-Path $d.FullName 'python.exe'
            if (Test-Path $exe) {
                $p = Test-Python $exe @()
                if ($p) { return $p }
            }
        }
    }
    return $null
}

# ---------------------------------------------------------------- uninstall
if ($Uninstall) {
    Write-Host "Removing $appName..."
    foreach ($s in $shortcuts) { if (Test-Path $s) { Remove-Item $s -Force; Write-Host "  removed $s" } }
    if (Test-Path $InstallDir) { Remove-Item $InstallDir -Recurse -Force; Write-Host "  removed $InstallDir" }
    Write-Host 'Done. (Python itself was left installed.)'
    Finish 0
}

# ------------------------------------------------------------------ install
Write-Host "Installing $appName..." -ForegroundColor Cyan
foreach ($f in 'autoclicker.py', 'autoclicker.ico') {
    if (-not (Test-Path (Join-Path $here $f))) {
        Write-Host "Missing $f next to the installer. Unzip the whole download first." -ForegroundColor Red
        Finish 1
    }
}
try { Get-ChildItem $here -File | Unblock-File } catch { }

Write-Host '[1/4] Looking for Python 3.8+ ...'
$py = Find-Python
if (-not $py) {
    Write-Host '      Python not found.' -ForegroundColor Yellow
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host '      Installing Python with winget (this can take a minute) ...'
        & winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-source-agreements
        $py = Find-Python
    }
    if (-not $py) {
        Write-Host ''
        Write-Host 'Could not install Python automatically.' -ForegroundColor Red
        Write-Host 'Install it from https://www.python.org/downloads/ (tick "Add python.exe to PATH"),'
        Write-Host 'then run install.bat again.'
        Start-Process 'https://www.python.org/downloads/'
        Finish 1
    }
}
Write-Host "      Using $py"
$pyw = Join-Path (Split-Path $py) 'pythonw.exe'
if (-not (Test-Path $pyw)) { $pyw = $py }

Write-Host "[2/4] Copying files to $InstallDir ..."
New-Item -ItemType Directory -Force $InstallDir | Out-Null
foreach ($f in 'autoclicker.py', 'autoclicker.ico') {
    Copy-Item (Join-Path $here $f) (Join-Path $InstallDir $f) -Force
}
$script = Join-Path $InstallDir 'autoclicker.py'
$icon = Join-Path $InstallDir 'autoclicker.ico'

Write-Host '[3/4] Creating shortcuts ...'
$ws = New-Object -ComObject WScript.Shell
foreach ($s in $shortcuts) {
    New-Item -ItemType Directory -Force (Split-Path $s) | Out-Null
    $l = $ws.CreateShortcut($s)
    $l.TargetPath = $pyw
    $l.Arguments = "`"$script`""
    $l.WorkingDirectory = $InstallDir
    $l.IconLocation = "$icon,0"
    $l.Description = "$appName (F6 start/stop, F7 quit)"
    $l.Save()
    Write-Host "      $s"
}

Write-Host '[4/4] Done.' -ForegroundColor Green
if (-not $NoLaunch) {
    Start-Process $pyw -ArgumentList "`"$script`"" -WorkingDirectory $InstallDir
    Write-Host '      Launched. Next time, use the "Auto Clicker" shortcut on your Desktop.'
}
Finish 0
