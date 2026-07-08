<#
.SYNOPSIS
    Configure + build (and optionally run) frontend_v2 from a plain PowerShell,
    without opening Qt Creator. Builds the frontend_v2 of whichever checkout you
    run it from — main checkout or a worktree.

.DESCRIPTION
    Imports the MSVC x64 environment (vcvars64.bat, located via vswhere), detects
    the newest Qt 6 msvc2022_64 kit, then runs a Ninja CMake configure + build of
    the appfrontend_v2 target into <repo>\frontend_v2\build. Object files are
    reused via sccache automatically when it is installed (see the compiler-cache
    block in frontend_v2/CMakeLists.txt).

.PARAMETER Config
    CMake build type: Debug (default), Release, or RelWithDebInfo.

.PARAMETER QtPrefix
    Qt kit path. Default: newest D:\Qt\6.*.*\msvc2022_64.

.PARAMETER Run
    Launch appfrontend_v2.exe after a successful build.

.PARAMETER Fullscreen
    With -Run, start the frontend fullscreen (TESLA_HOMEDASH_FULLSCREEN=1).

.PARAMETER Clean
    Delete the build directory first (forces a full reconfigure + rebuild).

.EXAMPLE
    .\scripts\build-frontend.ps1 -Run
.EXAMPLE
    .\scripts\build-frontend.ps1 -Config Release -Clean
#>
[CmdletBinding()]
param(
    [ValidateSet('Debug', 'Release', 'RelWithDebInfo')]
    [string]$Config = 'Debug',
    [string]$QtPrefix,
    [switch]$Run,
    [switch]$Fullscreen,
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'

# Refresh PATH from the machine + user environment so a freshly-installed sccache
# is visible without opening a new terminal.
$env:PATH = [System.Environment]::GetEnvironmentVariable('PATH', 'Machine') + ';' +
            [System.Environment]::GetEnvironmentVariable('PATH', 'User')

# --- Locate the checkout we are building (main or worktree) ---
$repoRoot = (git rev-parse --show-toplevel).Trim()
$src   = Join-Path $repoRoot 'frontend_v2'
$build = Join-Path $src 'build'
if (-not (Test-Path (Join-Path $src 'CMakeLists.txt'))) {
    throw "No frontend_v2\CMakeLists.txt under $repoRoot"
}

# --- Detect the Qt kit ---
if (-not $QtPrefix) {
    $qtRoot = 'D:\Qt'
    $kit = Get-ChildItem $qtRoot -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '^6\.\d+\.\d+$' -and (Test-Path (Join-Path $_.FullName 'msvc2022_64')) } |
        Sort-Object { [version]$_.Name } -Descending | Select-Object -First 1
    if (-not $kit) { throw "No Qt 6 msvc2022_64 kit found under $qtRoot. Pass -QtPrefix." }
    $QtPrefix = Join-Path $kit.FullName 'msvc2022_64'
}
Write-Host "Qt kit:  $QtPrefix" -ForegroundColor Cyan

# --- Import the MSVC x64 build environment (puts cl.exe on PATH) ---
$pf86    = [System.Environment]::GetEnvironmentVariable('ProgramFiles(x86)')
$vswhere = Join-Path $pf86 'Microsoft Visual Studio\Installer\vswhere.exe'
if (-not (Test-Path $vswhere)) { throw "vswhere not found at $vswhere" }
$vsPath = (& $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath).Trim()
$vcvars = Join-Path $vsPath 'VC\Auxiliary\Build\vcvars64.bat'
if (-not (Test-Path $vcvars)) { throw "vcvars64.bat not found at $vcvars" }
cmd /c "`"$vcvars`" && set" | ForEach-Object {
    if ($_ -match '^([^=]+)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable($matches[1], $matches[2])
    }
}
Write-Host "MSVC:    $vsPath" -ForegroundColor DarkGray

# --- Pick cmake + ninja (Qt bundles both) ---
$cmake = 'D:\Qt\Tools\CMake_64\bin\cmake.exe'
if (-not (Test-Path $cmake)) { $cmake = (Get-Command cmake -ErrorAction SilentlyContinue).Source }
if (-not $cmake) { throw 'cmake not found (install it or put it on PATH).' }
$ninja = (Get-Command ninja -ErrorAction SilentlyContinue).Source
if (-not $ninja) { $ninja = 'D:\Qt\Tools\Ninja\ninja.exe' }

if ($Clean -and (Test-Path $build)) {
    Write-Host "Cleaning $build" -ForegroundColor Yellow
    Remove-Item -Recurse -Force $build
}

# --- Configure (CMake no-ops if already configured and unchanged) ---
$cfgArgs = @('-S', $src, '-B', $build, '-G', 'Ninja',
             "-DCMAKE_PREFIX_PATH=$QtPrefix", "-DCMAKE_BUILD_TYPE=$Config")
if (Test-Path $ninja) { $cfgArgs += "-DCMAKE_MAKE_PROGRAM=$ninja" }
Write-Host "Configuring ($Config) ..." -ForegroundColor Cyan
& $cmake @cfgArgs
if ($LASTEXITCODE -ne 0) { throw 'CMake configure failed.' }

# --- Build ---
Write-Host 'Building appfrontend_v2 ...' -ForegroundColor Cyan
& $cmake --build $build --target appfrontend_v2
if ($LASTEXITCODE -ne 0) { throw 'Build failed.' }

$exe = Join-Path $build 'appfrontend_v2.exe'
Write-Host ''
Write-Host "Build OK -> $exe" -ForegroundColor Green

# --- sccache stats, if present ---
$scc = (Get-Command sccache -ErrorAction SilentlyContinue).Source
if ($scc) { & $scc --show-stats 2>$null | Select-String 'Compile requests|Cache hits|Cache misses' }

# --- Optional run ---
if ($Run) {
    if (-not (Test-Path $exe)) { throw "Executable not found: $exe" }
    $env:PATH = "$QtPrefix\bin;$env:PATH"            # so the exe finds Qt6*.dll
    if ($Fullscreen) { $env:TESLA_HOMEDASH_FULLSCREEN = '1' }
    Write-Host "Launching $exe" -ForegroundColor Cyan
    & $exe
}
