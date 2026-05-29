param(
    [string]$Python = "python",
    [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$runtimeEntry = Join-Path $root "runtime\sidecar.py"
$binariesDir = Join-Path $root "desktop-shell\src-tauri\binaries"
$sidecarName = "local-runtime-$TargetTriple"

Set-Location $root

Write-Host "Checking PyInstaller..."
& $Python -m PyInstaller --version | Out-Host

Write-Host "Building Python sidecar: $sidecarName"
& $Python -m PyInstaller `
    --noconfirm `
    --clean `
    --onefile `
    --name $sidecarName `
    --hidden-import docx `
    --hidden-import PyPDF2 `
    --hidden-import tkinter `
    --hidden-import tkinter.filedialog `
    --add-data "runtime\panel;runtime\panel" `
    $runtimeEntry

New-Item -ItemType Directory -Force -Path $binariesDir | Out-Null
$exePath = Join-Path $root "dist\$sidecarName.exe"
if (-not (Test-Path $exePath)) {
    throw "PyInstaller did not create expected sidecar: $exePath"
}

Copy-Item -Force -LiteralPath $exePath -Destination (Join-Path $binariesDir "$sidecarName.exe")
Write-Host "Sidecar copied to desktop-shell\src-tauri\binaries\$sidecarName.exe"
