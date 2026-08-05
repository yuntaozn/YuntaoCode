param(
    [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"

$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$binariesDir = Join-Path $root "desktop-shell\src-tauri\binaries"
$binaryPath = Join-Path $binariesDir "local-runtime-$TargetTriple.exe"
$iconsDir = Join-Path $root "desktop-shell\src-tauri\icons"
$iconPath = Join-Path $iconsDir "icon.ico"

New-Item -ItemType Directory -Force -Path $binariesDir | Out-Null
New-Item -ItemType Directory -Force -Path $iconsDir | Out-Null

if (-not (Test-Path $binaryPath)) {
    # Tauri 构建脚本会在 cargo check 时校验 externalBin 是否存在。
    # 用于打包的真实 sidecar 由 build_sidecar_windows.ps1 生成。
    [System.IO.File]::WriteAllBytes($binaryPath, [byte[]](0x4D, 0x5A))
}

if (-not (Test-Path $iconPath)) {
    # 最小 1x1 ICO 回退图标。正式发布应将品牌 icon.ico
    # 保存在 desktop-shell/src-tauri/icons/ 中。
    [byte[]]$iconBytes = @(
        0x00,0x00,0x01,0x00,0x01,0x00,
        0x01,0x01,0x00,0x00,0x01,0x00,0x20,0x00,0x30,0x00,0x00,0x00,0x16,0x00,0x00,0x00,
        0x28,0x00,0x00,0x00,0x01,0x00,0x00,0x00,0x02,0x00,0x00,0x00,0x01,0x00,0x20,0x00,
        0x00,0x00,0x00,0x00,0x04,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
        0x00,0x00,0x00,0x00,0x00,0x00,0x00,0x00,
        0xD6,0x78,0x2A,0xFF,
        0x00,0x00,0x00,0x00
    )
    [System.IO.File]::WriteAllBytes($iconPath, $iconBytes)
}

Write-Host "Prepared Tauri check placeholder: $binaryPath"
Write-Host "Verified Tauri icon path: $iconPath"
