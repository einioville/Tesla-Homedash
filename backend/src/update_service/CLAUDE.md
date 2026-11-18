# `update_service/` — installing releases (#56)

Serves `UPDATE_GET_STATE` / `UPDATE_APPLY` / `UPDATE_CANCEL` (`0xD0`–`0xD3`) and broadcasts
`UPDATE_STATE`; registered with `register_service`, so a connecting display gets the state —
including a run in flight — without asking. A device that is not a development machine moves
between **releases published on GitHub's Releases page** and never builds anything or touches git.
What a release carries and how one is made is `scripts/CLAUDE.md`, *Releases*; this file is the
device's half. The card is Ylläpito › *Päivitys* (`frontend_v2/core/CLAUDE.md`, under `Updater`).

## The device

`install.sh` (`scripts/`) lays it out, and this service and `guard.py` keep it:

```
~/.local/share/Tesla-Homedash/     the install root (utils/version.install_root)
  releases/<tag>/                  backend/ (with its own .venv), frontend/, manifest.json,
                                   .complete — written last, so a half-made folder is never used
  current -> releases/<tag>        what both systemd units start; moved with one rename
  guard.py                         the health gate's guard, outside every release folder
  switch.json                      the open health gate: {from, to, deadline, starts,
                                   restoredSnapshot, localDisplay}
  rollback.json                    the guard's record of a rollback, shown until a switch succeeds
  last-switch.json                 the last switch that passed the gate
  snapshots/<tag>/                 the state files as they were when <tag> was left (0700)
  downloads/<tag>/                 a run's downloads, removed when it ends
~/.config/Tesla-Homedash/.env      moved out of the checkout (utils/env_file)
```

- **Mode comes from where the code runs** (`utils/version`): a backend under
  `releases/<tag>/backend` with a `manifest.json` is an installed release, and anything else a
  development checkout, whose card shows the commit and says it is updated with git — nothing is
  listed, downloaded or switched there.
- **A local display** is one whose dashboard unit `install.sh` wrote
  (`~/.config/systemd/user/tesla-homedash-frontend.service`). Only then does a run download the
  frontend bundle, stop and restart the dashboard, check `arch`, `glibc` and `displayCommands`,
  and wait for the display to log in before the gate closes. **The updater updates only its own
  device**; a display elsewhere reports its version at login (`../auth_service/CLAUDE.md`).

## Listing

`GET /repos/einioville/Tesla-Homedash/releases`, a minute after start, every 6 h, and when a
card asks (`fetch: true`, throttled to one per 2 min **per attempt**, so an unreachable GitHub is
not asked again on every card open). Unauthenticated: 60 calls an hour, and an unchanged list
answers 304 to the ETag, which costs none. Drafts never appear, so a half-uploaded release is never
seen.

- **Each release's manifest is verified before the card sees it**: `SHA256SUMS` and its signature
  and `manifest.json` (three small downloads, cached per tag until the assets change), the signature
  checked with `ssh-keygen -Y verify` against **`release_signers` of the running release**, so a
  new key has to arrive in a release the old one signed. `ssh-keygen` reads the signed message on
  stdin (`utils/process.run(stdin=…)`).
- **Not installable, with the reason the card shows**: no manifest and checksums ("ei
  päivitystoimintoa" — **the trapdoor rule**: v1.0.0 and anything else from before this updater,
  since moving a keyboard-less panel onto one leaves no way back but SSH), a bad signature, and
  missing requirements ("Vaatii: wlr-randr, .env: VIN"). The requirements are the manifest's
  `commands` (PATH plus `~/.local/bin`), `env` (in the environment, which holds `.env` by then)
  and, with a local display, `arch`, `glibc` and `displayCommands`. The Python version is not
  checked: `uv sync` fetches the one `.python-version` names.
- **The order is the version's**, `vX.Y.Z` with `-rcN` before its release; `direction` is
  `current` / `update` / `downgrade` against the running release. Pre-releases are listed with
  `prerelease: true`; which ones a display shows is its own choice. A release with a snapshot here
  says so (`snapshot`), for the card's downgrade warning.

## A run

`UPDATE_APPLY {tag}`: the tag must match `_TAG` and be one this service listed as installable, and
the preflight (uv, 1 GB free, the backend running under its systemd unit) must pass. Steps:

1. **download** — the checksums, signature and manifest are fetched **and verified again**, never
   trusted from the listing; then each bundle streams to disk and is hashed on the way.
2. **unpack** — into `releases/<tag>` in a worker thread, tarfile's `data` filter refusing links and
   paths out of the folder, and nothing but `backend/` and `frontend/` allowed.
3. **deps** — `uv sync --locked --no-install-project` in the new folder: its own venv, so a failed
   sync never touches the running one. `--locked` fails loudly on a lock that does not match;
   `--no-install-project` skips building the backend as a package, which `run.py` does not need.
   `VIRTUAL_ENV` and the like are scrubbed, or uv would aim at the running release's venv. Then
   `.complete`.
4. **snapshot** — `config.json`, `paired_displays.json`, `tls/` and the frontend's
   `frontend_config.json` and `frontend_credentials.json` copied to `snapshots/<the version being
   left>` with `snapshot.json` mapping each to where it lives, replacing an older snapshot of it.
5. **switch** — stops the local dashboard, restores the target's snapshot on a downgrade that has
   one, writes `switch.json` **before** moving `current` (a power cut between the two leaves a marker
   the guard undoes, never a moved link nothing watches), arms the guard's 5-minute timer and
   restarts both units with `systemctl --user --no-block restart` — which ends this process.

A release folder that is already `.complete` (the one before is kept) is switched to after only
the small files are checked. **Nothing before the switch touches the running release**, so a
failure or a cancel (allowed in steps 1–3) only removes the half-made folder and the downloads.

**The state files are additive** (root `CLAUDE.md`): an older release ignores keys a newer one
added, which is what lets a snapshot-less downgrade run on today's files, and a version field
arrives only with the first change that cannot be additive.

## The health gate

The new backend reads `switch.json` at start. When the gate is its own (`to` is this release), it
closes once the display on this device logs in to it (`AuthService.add_login_listener`, a login from
loopback) — at once with no local display. Closing removes the marker and stops the timer,
installs **this release's** `guard.py` beside the releases (a release must pass the gate before its
guard is trusted), writes `last-switch.json`, and removes every release folder but this one and the
one before it. Until then `guard.py` — the backend unit's `ExecStartPre` and the timer — rolls
`current` back on a crash loop or once the 5 minutes are up, restoring the previous release's
snapshot when the switch restored one, and leaves `rollback.json` (`guard.py`'s docstring). The
guard runs under the system `python3`, never a release's venv.

## Kept from the git updater, on purpose

- **The slot is claimed synchronously**: `handle_apply` sets `__starting` before its first await
  and `__job` before the task exists, since `Server` dispatches every packet as its own task.
- **A refusal never overwrites a live job**, and the run closes its job out in a `finally`: every
  gate reads `finished`, the restart veto included, and the veto stands down past a deadline so a
  wedged job cannot leave a device that never restarts.
- **Every child runs in its own process group** and is killed by group; output is read in chunks,
  not `readline()`, which raises past 64 KiB. The document stays small: the log is 80 × 240 chars,
  notes are cut at 4000 chars, the list at 20 releases, and broadcasts are coalesced to 2 Hz.

**Talks to:** GitHub (aiohttp), `ssh-keygen`, `uv`, `systemctl` / `systemd-run`, `ConfigService`
(the veto, and its restart as the fallback), `AuthService` (logins), `Server`, the *Palvelin*
status card (`version_label()`).

## Event flow

```
UpdatePanel opens → UPDATE_GET_STATE{fetch:true} → __check (throttled) → GitHub's list
  → per release: SHA256SUMS + .sig + manifest → ssh-keygen -Y verify → requirements
  → UPDATE_STATE → the card lists them
a tap → UPDATE_APPLY{tag} → listed + installable + preflight
  → download (verify again) → unpack → uv sync → snapshot → switch.json + current + timer
  → systemctl --user --no-block restart backend [frontend]
guard.py (ExecStartPre) → starts++ → new backend → the local display logs in
  → switch.json removed, timer stopped, guard.py installed, old releases pruned → UPDATE_STATE
  (a crash loop or 5 min without that login → guard.py points current back, rollback.json)
```
