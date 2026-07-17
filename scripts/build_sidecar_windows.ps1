param(
    [string]$Python = "python",
    [string]$TargetTriple = "x86_64-pc-windows-msvc",
    [switch]$KeepWork
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$runtimeEntry = Join-Path $root "runtime\sidecar.py"
$panelAssets = Join-Path $root "runtime\panel"
$binariesDir = Join-Path $root "desktop-shell\src-tauri\binaries"
$sidecarName = "local-runtime-$TargetTriple"
$buildEnvironment = Join-Path $root ".venv-sidecar-build"
$buildPython = Join-Path $buildEnvironment "Scripts\python.exe"
$workRoot = Join-Path $root "build\sidecar-$TargetTriple"
$workPath = Join-Path $workRoot "work"
$specPath = Join-Path $workRoot "spec"
$distPath = Join-Path $workRoot "dist"
$exePath = Join-Path $distPath "$sidecarName.exe"
$binaryPath = Join-Path $binariesDir "$sidecarName.exe"

Set-Location $root

function Assert-NativeCommandSucceeded {
    param([string]$Description)
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

if (-not (Test-Path -LiteralPath $buildPython)) {
    Write-Host "Creating isolated sidecar build environment..."
    & $Python -m venv $buildEnvironment
    Assert-NativeCommandSucceeded "Creating the sidecar build environment"
}

Write-Host "Synchronizing sidecar build dependencies..."
& $buildPython -m pip install --disable-pip-version-check ".[documents,web,build]"
Assert-NativeCommandSucceeded "Installing sidecar build dependencies"

& (Join-Path $PSScriptRoot "clean_desktop_build.ps1") -TargetTriple $TargetTriple | Out-Host

New-Item -ItemType Directory -Force -Path $workPath | Out-Null
New-Item -ItemType Directory -Force -Path $specPath | Out-Null
New-Item -ItemType Directory -Force -Path $distPath | Out-Null
New-Item -ItemType Directory -Force -Path $binariesDir | Out-Null

Write-Host "Checking PyInstaller..."
& $buildPython -m PyInstaller --version | Out-Host
Assert-NativeCommandSucceeded "Checking PyInstaller"

Write-Host "Building Python sidecar: $sidecarName"
& $buildPython -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name $sidecarName `
    --workpath $workPath `
    --specpath $specPath `
    --distpath $distPath `
    --hidden-import docx `
    --hidden-import pypdf `
    --hidden-import tkinter `
    --hidden-import tkinter.filedialog `
    --add-data "$panelAssets;runtime\panel" `
    $runtimeEntry
Assert-NativeCommandSucceeded "Building the Python sidecar"

if (-not (Test-Path -LiteralPath $exePath)) {
    throw "PyInstaller did not create expected sidecar: $exePath"
}

$sidecar = Get-Item -LiteralPath $exePath
if ($sidecar.Length -le 2) {
    throw "PyInstaller produced an invalid sidecar: $exePath"
}

Copy-Item -Force -LiteralPath $exePath -Destination $binaryPath
Write-Host ("Sidecar size: {0:N1} MB" -f ($sidecar.Length / 1MB))
Write-Host "Sidecar copied to desktop-shell\src-tauri\binaries\$sidecarName.exe"

if (-not $KeepWork) {
    Remove-Item -LiteralPath $workRoot -Recurse -Force
    Write-Host "Removed temporary PyInstaller work files."
}
