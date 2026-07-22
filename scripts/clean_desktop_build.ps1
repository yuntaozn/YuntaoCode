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
$cleanupFailures = New-Object System.Collections.Generic.List[object]

function Remove-WorkspacePath {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    $resolved = (Resolve-Path -LiteralPath $Path).Path
    if (-not $resolved.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove build artifact outside the repository: $resolved"
    }
    try {
        Remove-Item -LiteralPath $resolved -Recurse -Force
        Write-Host "Removed $resolved"
    } catch {
        $cleanupFailures.Add([pscustomobject]@{
            Path = $resolved
            Error = $_.Exception.Message
        }) | Out-Null
        Write-Warning "Failed to remove $resolved`: $($_.Exception.Message)"
    }
}

$paths = @(
    (Join-Path $root "build\sidecar-$TargetTriple$profileSuffix"),
    (Join-Path $root "build\$sidecarName"),
    (Join-Path $root "dist\$sidecarName.exe"),
    (Join-Path $root "$sidecarName.spec"),
    (Join-Path $root "yuntaocode.egg-info"),
    (Join-Path $root "desktop-shell\dist"),
    (Join-Path $root "desktop-shell\src-tauri\binaries\$sidecarName.exe"),
    (Join-Path $root "desktop-shell\src-tauri\target\release\local-runtime.exe"),
    (Join-Path $root "desktop-shell\src-tauri\target\release\local-intelligent-terminal.exe"),
    (Join-Path $root "desktop-shell\src-tauri\target\release\yuntaocode.exe"),
    (Join-Path $root "desktop-shell\src-tauri\target\release\bundle")
)

if ($Full) {
    $paths += Join-Path $root "build"
    $paths += Join-Path $root "desktop-shell\src-tauri\target"
    $paths += Join-Path $root ".venv-sidecar-build-lite"
    $paths += Join-Path $root ".venv-sidecar-build"
}

foreach ($path in $paths) {
    Remove-WorkspacePath $path
}

if ($cleanupFailures.Count -gt 0) {
    Write-Warning "Cleanup completed with $($cleanupFailures.Count) failure(s). Close any process using these files and rerun the script."
    foreach ($failure in $cleanupFailures) {
        Write-Warning "$($failure.Path): $($failure.Error)"
    }
    exit 1
}
