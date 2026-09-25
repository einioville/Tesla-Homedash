# `update_service/update_service.py` — in-place app updates

Serves `UPDATE_GET_STATE` / `UPDATE_APPLY` / `UPDATE_CANCEL` (`0xD0`–`0xD3`) and broadcasts
`UPDATE_STATE`; registered with `register_service`, so a connecting dashboard gets the state —
including a run already in flight — without asking. The dashboard runs from a git checkout, so
"update the app" is `git fetch` → `checkout --detach <sha>` → rebuild the frontend →
`uv sync --locked` → restart both halves, and every one of those is a system call, which is why
the whole thing lives here rather than in the UI. (The sync comes after the build on purpose —
see the step-order note below.)

**Two channels, one comparison.** `development` targets the tip of `origin/main`; `releases`
targets the newest `v*` tag (`--sort=-v:refname`, git's own version order, dereferenced with
`^{commit}` — a bare `rev-parse` on an annotated tag yields the TAG object and finds no ancestry
at all). Both resolve to a COMMIT and the verdict is a commit comparison, never a version-string
compare: `up_to_date` / `update` (target descends from HEAD) / `downgrade` (target is an ancestor)
/ `switch` (divergent), from two `merge-base --is-ancestor` calls (exit 0 = yes, 1 = no, anything
else = unknown, never guessed). That is what makes switching channels work in **both** directions;
development → releases normally reads `downgrade`, which is an ordinary outcome here.

Load-bearing details, most of them measured:
- **The trapdoor rule.** A target that does not itself contain `update_service.py` +
  `UpdatePanel.qml` (checked with `git cat-file -e <sha>:<path>`) is **refused whatever the
  verdict says**. Move a keyboard-less panel onto a commit with no updater and the only way back
  is SSH — and this project's only release tag is exactly such a commit. Downgrading between two
  versions that both carry the feature is the case the feature is for, and works.
- **`GIT_ASKPASS` set to the EMPTY STRING is what stops a fetch hanging forever.**
  `GIT_TERMINAL_PROMPT=0` alone only suppresses git's own tty prompt; git then falls through to an
  askpass helper — measured parking until the step timeout. Setting the variable at all (even
  empty) also suppresses the `SSH_ASKPASS` fallback, which matters because the Pi runs a full
  desktop, so `DISPLAY` is set. Also `GIT_CONFIG_NOSYSTEM`, `GIT_SSH_COMMAND` with `BatchMode` +
  `ConnectTimeout`, `GIT_OPTIONAL_LOCKS=0` and `LC_ALL=C`; `GIT_DIR`/`GIT_WORK_TREE` are scrubbed
  from every child, since an inherited value would silently redirect the checkout elsewhere.
- **git 2.43 has no `http.connectTimeout`** and the low-speed knobs do not cover the connect phase
  (measured against a black-holed address), so `asyncio.wait_for` around the subprocess is the ONLY
  bound — the same shape `../weather_service/CLAUDE.md` mandates for the FMI fetch.
- **Every child gets `start_new_session=True` and is killed by PROCESS GROUP.** git forks
  `git-remote-https`, and the build is a shell → cmake → ninja → one compiler per file; measured,
  killing the parent alone leaves the tree running AND leaves the inherited stdout pipe open, so
  the reader never sees EOF.
- **Output is read in CHUNKS, not with `readline()`.** `StreamReader.readline` raises past its
  64 KiB buffer and a deep C++ template diagnostic exceeds that; the exception would leave the job
  "running" forever, refusing every later request.
- **`uv sync --locked`, never a bare `uv sync`.** A bare sync silently re-resolves and rewrites
  `uv.lock` — a TRACKED file — so the write would make the tree dirty and permanently wedge this
  service's own dirty-tree refusal, pointing at a file the user never touched. (`--frozen` avoids
  the rewrite too but installs a stale lock silently.)
- **Nothing renames the frontend binary out of the way, and that is correct.** ld UNLINKS its
  output before creating it rather than truncating in place, so relinking a *running* executable
  succeeds and the live process keeps its old inode — measured, including that not-yet-paged-in
  code still faults in correctly afterwards. (`cp` and shell redirection DO fail with ETXTBSY,
  because they truncate; the linker is the exception.) A rename dance would only add a
  half-moved-binary failure mode.
- **The artifact is verified before anything is told to restart**: exists, executable, newer than
  the run, not implausibly smaller than before. A build killed mid-link can leave a truncated file,
  and restarting a keyboard-less panel into a stub leaves no dashboard at all.
- **Anything that fails AFTER the checkout rolls the tree back** (`checkout --detach <previous>` +
  `uv sync --locked`). A new source tree beside an old virtualenv is the one genuinely
  unrecoverable state this feature can produce: the backend's unit re-syncs on every start, so the
  next restart fails, retries and fails again — with the Options view gone along with the backend.
- **Checkout is always DETACHED**, uniform across both channels. A release is a tag and can only be
  checked out detached anyway; detaching never discards a local branch; and — the case that decides
  it — a linked worktree *refuses* `checkout main` when main is checked out elsewhere, while
  `checkout --detach <sha>` always works. `advice.detachedHead=false` keeps the eight-line advice
  block out of the journal. No `-f`: a checkout aborted by a colliding untracked file is a clean
  refusal, and forcing past it would delete what the user put there.
- **`--prune --tags --force` on fetch, but NOT `--prune-tags`.** `--tags` uses a non-forced
  refspec, so a MOVED release tag is rejected with "would clobber existing tag" and the releases
  channel silently sticks to the old commit; `--prune-tags` is left off because it deletes local
  tags the remote lacks, which is right for a deployment and wrong for the maintainer's checkout.
- **Preflight in `tools`**, reported before the button is live: `uv` (PATH, else `~/.local/bin/uv`
  — a `systemd --user` unit's PATH has neither), the build script, a Qt kit (`$QTDIR` → newest
  `~/Qt/*/gcc_64`|`gcc_arm64` → `CMAKE_PREFIX_PATH` from an existing `CMakeCache.txt`) and disk
  headroom. The kit is passed to the script as `--qt-prefix` so the choice appears in the log.
- **Cancel is step-aware.** Allowed during fetch/deps/build (and then rolled back like any other
  failure); refused during the checkout, whose interruption is the half-written state everything
  here avoids. `job.cancellable` tells the frontend, so the button hides rather than being ignored.
- The state document is ~2 KB; the job log is capped at 80 lines × 240 chars and broadcasts are
  coalesced to 2 Hz, so a build's hundreds of ninja lines never approach the 1 MB frame cap.
- **The BUILD runs before the dependency sync**, which is not the obvious order. `uv sync`
  rewrites the virtualenv this interpreter is running from, and a build that followed it takes
  tens of minutes on a Pi — a lazily-imported submodule of a replaced package failing in that
  window ends a process with no supervisor, and systemd would restart it mid-build, destroying
  the run's own rollback. Syncing last shrinks that window to seconds.
- **The job is claimed synchronously.** `self.__job` is built in the handler before the task is
  created, because `Server` dispatches every packet as its own task and `handle_apply` awaits
  ~10 git queries before the run exists — two applies would otherwise both pass a guard that
  only looked at `__job`. A refusal likewise **never overwrites a live job**: it replaces the
  whole document, which would erase the running progress, re-arm the restart button and hand the
  step loop an empty `steps` list to index.
- **The run task closes the job out in a `finally`.** Every gate in the service reads
  `finished`, so an exception escaping the loop would leave the device unable to update, unable
  to refresh the card, and — through the restart veto — unable to restart. That veto is itself
  **bounded by a deadline**, so a wedged job can never trap a keyboard-less panel.
- **The artifact check is an absolute floor, not a ratio** against the previous binary: the
  first in-app update legitimately replaces the build script's default *Debug* binary with a
  *Release* one several times smaller, and a ratio test would reject that good build and roll a
  successful update back.
- **The job's fetch goes through the streaming runner, not the `__git` helper.** Only the runner
  registers the child on `self.__proc`, so only through it can a cancel or a timeout reach the
  process group — otherwise *Peruuta* is a button that visibly does nothing for up to three
  minutes. The read path's fetch keeps a much shorter timeout, since the card waits on its reply,
  and the throttle keys on the fetch ATTEMPT: keying on success means an unreachable remote is
  never throttled and every card open pays the full timeout again.

**Talks to:** `git`/`uv`/`bash` (subprocesses), `ConfigService` (restart + veto), `Server`
(broadcast/send_to), `SystemStatusService` (a `health()` probe).

**Deliberately deferred:** job state is not persisted across a backend restart, so an update
interrupted by a power cut is reported only by the journal, not by the card.
