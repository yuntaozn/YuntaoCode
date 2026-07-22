param(
    [string]$TargetTriple = "x86_64-pc-windows-msvc",
    [ValidateSet("full", "lite")]
    [string]$Profile = "full",
    [switch]$Full
)

$ErrorActionPreference = "Stop"
$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$sidecarName = "local-runtime-$TargetTriple"
$profileSuffix = if ($Profile -eq "full") { "" } else { "-$Profile" }

function Remove-WorkspacePath {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    if (-not $resolved.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove build artifact outside the repository: $resolved"
    }
    Remove-Item -LiteralPath $resolved -Recurse -Force
    Write-Host "Removed $resolved"
}

$paths = @(
    (Join-Path $root "build\sidecar-$TargetTriple$profileSuffix"),
    (Join-Path $root "build\$sidecarName"),
    (Join-Path $root "dist\$sidecarName.exe"),
    (Join-Path $root "$sidecarName.spec"),
    (Join-Path $root "yuntaocode.egg-info"),
    (Join-Path $root "desktop-shell\src-tauri\binaries\$sidecarName.exe"),
    (Join-Path $root "desktop-shell\src-tauri\target\release\local-runtime.exe"),
    (Join-Path $root "desktop-shell\src-tauri\target\release\local-intelligent-terminal.exe"),
    (Join-Path $root "desktop-shell\src-tauri\target\release\yuntaocode.exe"),
    (Join-Path $root "desktop-shell\src-tauri\target\release\bundle")
)

if ($Full) {
    $paths += Join-Path $root ".venv-sidecar-build"
    $paths += Join-Path $root ".venv-sidecar-build-lite"
    $paths += Join-Path $root "desktop-shell\src-tauri\target"
}

foreach ($path in $paths) {
    Remove-WorkspacePath $path
}
