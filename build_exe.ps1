# Builds the stand-alone Windows program (no Python needed to run it) with PyInstaller.
#
#   Double-click build_exe.bat   (needs Python 3.8+ and an internet connection once, to
#                                 fetch PyInstaller into a private folder)
#
# Result:  dist\AutoClicker\AutoClicker.exe   and   dist\AutoClicker-windows.zip
#
# It is built as a "one folder" program, not a single self-extracting file: one process,
# nothing unpacked into %TEMP%, and nothing left running after you close it.

param(
    [string]$EnvDir = (Join-Path $PSScriptRoot 'build_env'),    # throwaway virtual environment
    [string]$WorkDir = (Join-Path $PSScriptRoot 'build'),       # PyInstaller scratch files
    [string]$OutDir = (Join-Path $PSScriptRoot 'dist'),
    [switch]$NoPause
)

# (Not 'Stop': PyInstaller and pip write progress to stderr, which Windows PowerShell 5.1
# would treat as errors. Every step below is checked through its exit code instead.)
$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot

function Finish($code) {
    if (-not $NoPause) { Write-Host ''; Read-Host 'Press Enter to close' | Out-Null }
    exit $code
}

try {
    Write-Host '[1/4] Creating a private build environment ...' -ForegroundColor Cyan
    $py = if (Get-Command py -ErrorAction SilentlyContinue) { 'py' } else { 'python' }
    if ($py -eq 'py') { & py -3 -m venv $EnvDir } else { & python -m venv $EnvDir }
    if ($LASTEXITCODE -ne 0) { throw 'could not create the build environment (is Python installed?)' }
    $envPy = Join-Path $EnvDir 'Scripts\python.exe'

    Write-Host '[2/4] Installing PyInstaller into it (a few MB) ...' -ForegroundColor Cyan
    & $envPy -m pip install --quiet --disable-pip-version-check pyinstaller
    if ($LASTEXITCODE -ne 0) { throw 'pip could not install PyInstaller' }

    Write-Host '[3/4] Building AutoClicker.exe ...' -ForegroundColor Cyan
    # (absolute paths: PyInstaller resolves relative ones against the --specpath folder)
    $icon = Join-Path $PSScriptRoot 'autoclicker.ico'
    $fonts = Join-Path $PSScriptRoot 'fonts'
    & $envPy -m PyInstaller --noconfirm --clean --onedir --windowed `
        --name AutoClicker --icon $icon `
        --add-data "$fonts;fonts" --add-data "$icon;." `
        --distpath $OutDir --workpath $WorkDir --specpath $WorkDir `
        (Join-Path $PSScriptRoot 'autoclicker.py')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }

    Write-Host '[4/4] Making the zip ...' -ForegroundColor Cyan
    $zip = Join-Path $OutDir 'AutoClicker-windows.zip'
    if (Test-Path $zip) { Remove-Item $zip -Force }
    Compress-Archive -Path (Join-Path $OutDir 'AutoClicker') -DestinationPath $zip
    Write-Host ''
    Write-Host "Done: $OutDir\AutoClicker\AutoClicker.exe" -ForegroundColor Green
    Write-Host "      $zip"
    Finish 0
} catch {
    Write-Host ''
    Write-Host "Build failed: $($_.Exception.Message)" -ForegroundColor Red
    Finish 1
}
