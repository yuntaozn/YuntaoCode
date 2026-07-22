param(
    [string]$Python = "python",
    [string]$TargetTriple = "x86_64-pc-windows-msvc",
    [ValidateSet("full", "lite")]
    [string]$Profile = "full",
    [switch]$ConsoleSidecar
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$desktopShell = Join-Path $root "desktop-shell"

function Assert-NativeCommandSucceeded {
    param([string]$Description)
    if ($LASTEXITCODE -ne 0) {
        throw "$Description failed with exit code $LASTEXITCODE"
    }
}

function Resolve-CommandPath {
    param([string[]]$Names)
    foreach ($name in $Names) {
        $command = Get-Command $name -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
    }
    throw "Command not found: $($Names -join ', ')"
}

Write-Host "Building YuntaoCode desktop package for $Profile profile..."
$sidecarArgs = @{
    Python = $Python
    TargetTriple = $TargetTriple
    Profile = $Profile
}
if (-not $ConsoleSidecar) {
    $sidecarArgs["Windowed"] = $true
}
& (Join-Path $PSScriptRoot "build_sidecar_windows.ps1") @sidecarArgs
Assert-NativeCommandSucceeded "Building the Python sidecar"

$npx = Resolve-CommandPath @("npx.cmd", "npx")
$previousProfile = $env:VITE_YUNTAOCODE_RUNTIME_PROFILE
$env:VITE_YUNTAOCODE_RUNTIME_PROFILE = $Profile

Push-Location $desktopShell
try {
    & $npx tauri build --verbose
    Assert-NativeCommandSucceeded "Building the Tauri desktop package"
}
finally {
    Pop-Location
    if ($null -eq $previousProfile) {
        Remove-Item Env:\VITE_YUNTAOCODE_RUNTIME_PROFILE -ErrorAction SilentlyContinue
    }
    else {
        $env:VITE_YUNTAOCODE_RUNTIME_PROFILE = $previousProfile
    }
}
