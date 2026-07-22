param(
    [string]$Python = "python",
    [string]$TargetTriple = "x86_64-pc-windows-msvc",
    [ValidateSet("full", "lite")]
    [string]$Profile = "full",
    [switch]$Windowed,
    [switch]$KeepWork
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$runtimeEntry = Join-Path $root "runtime\sidecar.py"
$panelAssets = Join-Path $root "runtime\panel"
$binariesDir = Join-Path $root "desktop-shell\src-tauri\binaries"
$sidecarName = "local-runtime-$TargetTriple"
$profileSuffix = if ($Profile -eq "full") { "" } else { "-$Profile" }
$buildEnvironment = Join-Path $root ".venv-sidecar-build$profileSuffix"
$buildPython = Join-Path $buildEnvironment "Scripts\python.exe"
$workRoot = Join-Path $root "build\sidecar-$TargetTriple$profileSuffix"
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
    Write-Host "Creating isolated sidecar build environment for $Profile profile..."
    & $Python -m venv $buildEnvironment
    Assert-NativeCommandSucceeded "Creating the sidecar build environment"
}

Write-Host "Checking sidecar build pip..."
& $buildPython -m pip --version | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "Bootstrapping pip in sidecar build environment..."
    & $buildPython -m ensurepip --upgrade
    Assert-NativeCommandSucceeded "Bootstrapping sidecar build pip"
}

Write-Host "Synchronizing sidecar build dependencies..."
$dependencySpec = if ($Profile -eq "lite") { ".[build]" } else { ".[documents,web,build]" }
& $buildPython -m pip install --disable-pip-version-check $dependencySpec
Assert-NativeCommandSucceeded "Installing sidecar build dependencies"

& (Join-Path $PSScriptRoot "clean_desktop_build.ps1") -TargetTriple $TargetTriple -Profile $Profile | Out-Host

New-Item -ItemType Directory -Force -Path $workPath | Out-Null
New-Item -ItemType Directory -Force -Path $specPath | Out-Null
New-Item -ItemType Directory -Force -Path $distPath | Out-Null
New-Item -ItemType Directory -Force -Path $binariesDir | Out-Null

Write-Host "Checking PyInstaller..."
& $buildPython -m PyInstaller --version | Out-Host
Assert-NativeCommandSucceeded "Checking PyInstaller"

Write-Host "Building Python sidecar: $sidecarName"
$coreHiddenImports = @(
    "tiktoken_ext.openai_public",
    "runtime.skills.attachments",
    "runtime.skills.filesystem",
    "runtime.skills.code",
    "runtime.skills.shell",
    "runtime.skills.git",
    "runtime.skills.memory"
)
$fullHiddenImports = @(
    "runtime.skills.document",
    "runtime.skills.spreadsheet",
    "runtime.skills.desktop",
    "runtime.skills.web",
    "runtime.skills.preview",
    "runtime.skills.docx_parser",
    "runtime.skills.pdf_parser",
    "docx",
    "pypdf",
    "tkinter",
    "tkinter.filedialog"
)
$hiddenImports = if ($Profile -eq "lite") { $coreHiddenImports } else { $coreHiddenImports + $fullHiddenImports }
$pyinstallerArgs = @(
    "--noconfirm",
    "--clean",
    "--onefile",
    "--name", $sidecarName,
    "--workpath", $workPath,
    "--specpath", $specPath,
    "--distpath", $distPath
)
if ($Windowed) {
    $pyinstallerArgs += @("--noconsole")
}
foreach ($module in $hiddenImports) {
    $pyinstallerArgs += @("--hidden-import", $module)
}
$pyinstallerArgs += @("--add-data", "$panelAssets;runtime\panel", $runtimeEntry)
& $buildPython -m PyInstaller @pyinstallerArgs
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
