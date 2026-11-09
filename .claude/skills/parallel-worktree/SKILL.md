---
name: parallel-worktree
description: Set up, work in, and clean up an isolated git worktree for a second Tesla-Homedash session
  that must run at the same time as the main checkout. Use only for genuinely parallel sessions;
  sequential work stays in the main checkout (root CLAUDE.md §8).
---

# A parallel session in a git worktree

The default is the main checkout (root `CLAUDE.md` §8). Everything there still applies in a worktree:
one shared backend, the platform build script, and landing through a GitHub PR, never a local merge.

## Setup

1. Ask the user **(a) what we're doing** and **(b) a short name**; choose the branch **type**
   (`feature` / `fix` / `chore` / `docs` / `refactor` / `test` / `perf`).
2. **Windows:** `powershell -ExecutionPolicy Bypass -File scripts\new-session.ps1 -Type <type> -Name
   "<name>"` — **there is no Linux port of the session scripts**; on WSL2 use plain `git worktree
   add ../Tesla-Homedash-worktrees/<type>-<slug> -b <type>/<slug> origin/main`, then copy `.env` +
   `config.json` in by hand and repoint `CONFIG_PATH` at the copy. — makes branch `<type>/<slug>`
   off the freshest `origin/main`, adds a worktree under
   `..\Tesla-Homedash-worktrees\<type>-<slug>`, copies the gitignored `.env` + `config.json` in, and
   repoints `CONFIG_PATH` at the worktree's copy. Final stdout line: `WORKTREE_PATH=<path>`.
3. Switch in with the **`EnterWorktree`** tool (`path:` = that `WORKTREE_PATH`). Build there with
   the platform's build script; connect to the already-running shared backend (don't start a second
   one).

## Cleanup after the PR has merged

`ExitWorktree` (action `keep`), then on **Windows**
`powershell -ExecutionPolicy Bypass -File scripts\finish-session.ps1 -Type <type> -Name "<name>"`
— refuses until the PR reads MERGED (via `gh`), then removes the worktree, pulls main, deletes the
merged local branch, and prunes. (`-Force` skips the merged check.) On **Linux/WSL2** there is no
port: `git worktree remove <path> && git checkout main && git pull && git branch -d <type>/<slug>
&& git worktree prune`, after checking the PR merged yourself.

## Memory

Memories load at session start from the main checkout, so their guidance stays in
context even after an `EnterWorktree`. But the memory *store* follows the working directory, so any
durable memory you write during a worktree session must target the **main checkout's** project-memory
dir, not the worktree's (which is deleted at cleanup).
