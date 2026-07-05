<#
.SYNOPSIS
    Tear down a finished session worktree AFTER its pull request has been merged
    on GitHub. GitHub is the single source of truth — this never merges locally.

.DESCRIPTION
    Run from the main checkout (or anywhere in the repo). By default it refuses to
    act until GitHub reports the branch's PR as MERGED (checked via `gh`), then:
      1. removes the worktree,
      2. brings the main checkout's main up to date (checkout main; pull),
      3. deletes the now-merged local branch,
      4. prunes stale worktree metadata.

    This matches the chosen policy: open a PR, merge it on GitHub
    (`gh pr merge --squash --delete-branch`), then pull — no local merge to main.

.PARAMETER Name
    Session name used with new-session.ps1 (slugified the same way).

.PARAMETER Type
    Branch category prefix used with new-session.ps1. Default: feature.

.PARAMETER Force
    Clean up even if the PR is not detected as merged (or `gh` is unavailable).
    Use only when you are certain the work has landed on origin/main.

.EXAMPLE
    .\scripts\finish-session.ps1 -Type fix -Name "trip map crash"
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Name,

    [Parameter(Position = 1)]
    [ValidateSet('feature', 'fix', 'chore', 'docs', 'refactor', 'test', 'perf')]
    [string]$Type = 'feature',

    [switch]$Force
)

$ErrorActionPreference = 'Stop'

# --- Resolve the MAIN worktree (first entry of `git worktree list`) so we never
#     operate from inside the worktree we are about to remove. ---
$mainWt = ((git worktree list --porcelain) |
    Where-Object { $_ -like 'worktree *' } |
    Select-Object -First 1) -replace '^worktree ', ''
if (-not $mainWt) { throw 'Could not resolve the main worktree.' }
$mainWt = $mainWt.Trim()

# --- Re-derive slug/branch/path exactly as new-session.ps1 does ---
$slug = $Name.ToLowerInvariant()
$slug = $slug -replace '[\s_]+', '-'
$slug = $slug -replace '[^a-z0-9\-]', ''
$slug = $slug -replace '-{2,}', '-'
$slug = $slug.Trim('-')
if (-not $slug) { throw "Session name '$Name' slugified to empty." }

$branch   = "$Type/$slug"
$parent   = Split-Path $mainWt -Parent
$repoName = Split-Path $mainWt -Leaf
$wtPath   = Join-Path (Join-Path $parent "$repoName-worktrees") "$Type-$slug"

# --- Safety gate: require the PR to be merged unless -Force ---
if (-not $Force) {
    $state = $null
    try {
        $json = gh pr view $branch --json 'state,mergedAt' 2>$null
        if ($json) { $state = ($json | ConvertFrom-Json).state }
    }
    catch { $state = $null }

    if ($state -ne 'MERGED') {
        $shown = if ($state) { $state } else { 'unknown / gh unavailable' }
        throw "PR for '$branch' is not merged (state: $shown). Merge it on GitHub first, or re-run with -Force."
    }
    Write-Host "PR for '$branch' is merged on GitHub." -ForegroundColor Green
}

# --- 1. Remove the worktree (refuses if it has uncommitted changes) ---
if (Test-Path $wtPath) {
    Write-Host "Removing worktree: $wtPath" -ForegroundColor Cyan
    git -C $mainWt worktree remove $wtPath
    if ($LASTEXITCODE -ne 0) {
        throw "git worktree remove failed. Resolve uncommitted changes in $wtPath, or use: git worktree remove --force"
    }
}
else {
    Write-Warning "Worktree path not found: $wtPath (already removed?)"
}

# --- 2. Update main from origin ---
Write-Host 'Updating main from origin ...' -ForegroundColor Cyan
git -C $mainWt checkout main
if ($LASTEXITCODE -ne 0) { throw 'Could not checkout main.' }
git -C $mainWt pull
if ($LASTEXITCODE -ne 0) { throw 'git pull failed.' }

# --- 3. Delete the merged local branch (force: squash-merge is not a fast-forward) ---
git -C $mainWt show-ref --verify --quiet "refs/heads/$branch"
if ($LASTEXITCODE -eq 0) {
    Write-Host "Deleting local branch: $branch" -ForegroundColor Cyan
    git -C $mainWt branch -D $branch
}

# --- 4. Prune stale worktree metadata ---
git -C $mainWt worktree prune

Write-Host ''
Write-Host "Session '$branch' cleaned up. main is up to date." -ForegroundColor Green
