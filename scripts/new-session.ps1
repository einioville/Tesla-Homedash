<#
.SYNOPSIS
    Spin up an isolated git worktree for a work session so parallel Claude Code
    (or manual) sessions never collide.

.DESCRIPTION
    Creates a new branch  <Type>/<slug-of-Name>  off the freshest main, adds a git
    worktree for it in a sibling folder, and copies the gitignored runtime config
    (.env, config.json) into the worktree so the backend can run there standalone.
    The copied .env has its CONFIG_PATH rewritten to the worktree's own config.json,
    so each worktree is fully self-contained.

    Prints the worktree path on the final line as  WORKTREE_PATH=<path>  so the
    caller (Claude via EnterWorktree, or you via cd) can switch into it.

.PARAMETER Name
    Session name. Becomes the part after the slash in the branch name. It is
    slugified: lowercased, spaces/underscores -> dashes, other characters stripped.

.PARAMETER Type
    Branch category prefix. One of: feature, fix, chore, docs, refactor, test, perf.
    Default: feature.

.PARAMETER Base
    Start point for the new branch. Default 'auto' -> origin/main if present
    (after a fetch), else local main. Pass an explicit ref to override.

.EXAMPLE
    .\scripts\new-session.ps1 -Type fix -Name "trip map crash"
    # -> branch  fix/trip-map-crash
    #    worktree ..\Tesla-Homedash-worktrees\fix-trip-map-crash
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Name,

    [Parameter(Position = 1)]
    [ValidateSet('feature', 'fix', 'chore', 'docs', 'refactor', 'test', 'perf')]
    [string]$Type = 'feature',

    [string]$Base = 'auto'
)

$ErrorActionPreference = 'Stop'

# --- Locate the main repo root (this script lives in <repo>/scripts) ---
$repoRoot = (git rev-parse --show-toplevel)
if (-not $repoRoot) { throw 'Not inside a git repository.' }
$repoRoot = $repoRoot.Trim()

# --- Slugify the session name for the branch + folder ---
$slug = $Name.ToLowerInvariant()
$slug = $slug -replace '[\s_]+', '-'      # whitespace/underscores -> dash
$slug = $slug -replace '[^a-z0-9\-]', ''  # strip anything not [a-z0-9-]
$slug = $slug -replace '-{2,}', '-'       # collapse repeats
$slug = $slug.Trim('-')
if (-not $slug) { throw "Session name '$Name' slugified to empty. Use letters/digits." }

$branch = "$Type/$slug"

# --- Worktree location: <repo-parent>\<repo-name>-worktrees\<type>-<slug> ---
$parent   = Split-Path $repoRoot -Parent
$repoName = Split-Path $repoRoot -Leaf
$wtRoot   = Join-Path $parent "$repoName-worktrees"
$wtPath   = Join-Path $wtRoot "$Type-$slug"

if (Test-Path $wtPath) { throw "Worktree path already exists: $wtPath" }

git -C $repoRoot show-ref --verify --quiet "refs/heads/$branch"
if ($LASTEXITCODE -eq 0) { throw "Branch '$branch' already exists." }

# --- Pick the freshest base for the new branch ---
if ($Base -eq 'auto') {
    Write-Host 'Fetching origin/main ...' -ForegroundColor Cyan
    git -C $repoRoot fetch origin main --quiet   # best-effort; offline is non-fatal
    git -C $repoRoot show-ref --verify --quiet 'refs/remotes/origin/main'
    $Base = if ($LASTEXITCODE -eq 0) { 'origin/main' } else { 'main' }
}

# --- Create the worktree + branch ---
New-Item -ItemType Directory -Force -Path $wtRoot | Out-Null
Write-Host "Creating worktree: $wtPath  (branch $branch off $Base)" -ForegroundColor Cyan
git -C $repoRoot worktree add -b $branch $wtPath $Base
if ($LASTEXITCODE -ne 0) { throw 'git worktree add failed.' }

# --- Copy gitignored runtime config into the worktree ---
foreach ($f in @('.env', 'config.json')) {
    $src = Join-Path $repoRoot $f
    if (Test-Path $src) {
        Copy-Item $src (Join-Path $wtPath $f)
        Write-Host "  copied $f" -ForegroundColor DarkGray
    }
    else {
        Write-Warning "$f not found in main checkout — skipped (worktree may not run until you add it)."
    }
}

# --- Point the worktree's .env CONFIG_PATH at its own config.json (no-BOM write) ---
$wtEnv    = Join-Path $wtPath '.env'
$wtConfig = Join-Path $wtPath 'config.json'
if ((Test-Path $wtEnv) -and (Test-Path $wtConfig)) {
    [string[]]$envLines = Get-Content $wtEnv
    if ($envLines -match '^\s*CONFIG_PATH\s*=') {
        $envLines = $envLines -replace '^\s*CONFIG_PATH\s*=.*$', "CONFIG_PATH=$wtConfig"
        $utf8NoBom = New-Object System.Text.UTF8Encoding($false)
        [System.IO.File]::WriteAllLines($wtEnv, $envLines, $utf8NoBom)
        Write-Host "  rewrote CONFIG_PATH -> $wtConfig" -ForegroundColor DarkGray
    }
}

# --- Report ---
Write-Host ''
Write-Host 'Worktree ready.' -ForegroundColor Green
Write-Host "  Branch: $branch"
Write-Host "  Path:   $wtPath"
Write-Host '  Note:   frontend_v2 needs a fresh CMake configure in the worktree before building.'
Write-Host ''
# Machine-readable final line for the caller to parse:
Write-Host "WORKTREE_PATH=$wtPath"
