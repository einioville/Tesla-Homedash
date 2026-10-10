# `system_service/` — the maintenance dashboard (issue #39)

`system_metrics.py` is pure stdlib against `/proc` and `/sys` (no psutil: nothing here is worth an
ARM build and a pin); `system_history.py` reads it per sample, the status document for the host's
uptime. `SystemStatusService` serves
`SYSTEM_GET_STATUS` — the service cards — **request/response, not a broadcast, and deliberately NOT
`register_service`d**: the Options view is open a fraction of the time, and polling every service for
every client to feed a screen nobody is looking at is pure waste. The document is
`{services, sampled_ms, uptime_s, backend_uptime_s}` — the uptimes for the overview card; the host's
metrics are the history's. Details that matter:
- **The backend's uptime is monotonic** (since `SystemStatusService` was built, at startup), never
  "now minus the start time": the Pi has no RTC and steps its wall clock when NTP first answers.
- `/proc/net/dev` is parsed with `partition(":")`, not `split()` — a counter wide enough to touch the
  colon prints `eth0:1234567890` and shifts every column by one.
- Per-service health is duck-typed **`health()`**, the same pattern as `stream_everything()` and
  `apply_config()`, so each service answers from state it already keeps. A probe that raises or hangs
  is reported as one broken service, never as a failed request. Beside `state` (`ok`/`warn`/`error`/
  `off` — the cards' *Toiminnassa* / *Ongelmia* / *Ei toiminnassa* / *Ei käytössä*) and `detail`, a
  probe returns its **settings in effect** as `config: [[label, value]]` — a value is a display
  string, or `{time: ms}` / `{bytes: n}` / `{duration: s}` for the frontend to format in its own
  locale and zone — and optionally `items` (the server card's connected clients). The probes live on
  the services (`influx_handler.health`, `mm.radio_health`, `telemetry.health`, …) or, where the
  facts span services, in `start_services` (server, Spotify, *Laturi*, *Matkat*). **Probe order is
  card order.**
- **A card is a service with a standing, and a setting appears on one card only.** *Laturi* is the
  Zappi poll plus the Charging view's session detection (`myenergi.health()` + the session rows, as
  in the Options view's Sähkö › Laturi), built even without a Zappi; *Matkat* is trip detection
  alone. The app's version is a row of the *Palvelin* card (`updater.version_label()`), not a card —
  a version has no *Toiminnassa* to report, and `update_service`'s warnings are that card's.
  Config labels match the Options view's row labels.
- **Each probe claims the loggers whose warnings its card counts** (`register_probe(…, loggers=…)`,
  exact names or their dotted descendants — `media_service.spotify` would NOT match
  `media_service.spotify_player`, so list them). The server card is the **catch-all**: it also takes
  every logger no other card claims, so no warning is ever unlisted. Each row gets
  `errors: {warnings, errors}` from the persistent `ErrorLog` (`../utils/CLAUDE.md`), and
  **`SYSTEM_GET_LOG`** returns one card's entries, newest first, capped at 500.
- Warnings since the logs were last cleared in full — the store persists across restarts, so a count
  is not "since boot" any more. A level change is logged at INFO for that reason: a deliberate
  change is no problem to count.
- CPU jiffies sum only the first eight `/proc/stat` fields: `guest` / `guest_nice` are already inside
  `user` / `nice`, so summing all ten counts a VM host's guest time twice.

## `system_history.py` — the Järjestelmän tila graphs

`SystemHistory` is the one part of this service that **runs all the time**: a gathered task samples
the host every 2 s (`INTERVAL_SECONDS`) into a 10-minute ring buffer (`WINDOW_SECONDS`). A graph that
started empty whenever its section opened would answer nothing — its question is what the host *has
been* doing — and a tick is four small `/proc` reads. The samples still leave the process only on
request (`SYSTEM_GET_HISTORY`), and incrementally. Load-bearing:
- **A tick never raises.** The task is gathered with the rest of the backend, so an exception out of
  it would end the process over a graph; a failed tick is logged and skipped.
- **Incremental by `since_ms`, with `reset`.** A client sends the timestamp of the newest sample it
  holds and gets only newer ones. `reset` (drop, don't append) answers `since = 0` and a client
  holding samples newer than any here — the host clock went backwards.
- **The buffer is trimmed by time, not only by count**, from the newest sample: the Pi has no RTC and
  steps its clock forward when NTP first answers, which would otherwise leave "months-old" samples in
  the window. A clock that steps *back* clears the buffer, since the timeline is out of order.
- **Per-core CPU is keyed by the kernel's core number** (`read_cpu_core_samples()`), so an offline
  core leaves a hole (`null`) instead of shifting every later core onto the wrong line — and colour.
- **Disk I/O follows the device under `/`**, found once by matching its `st_dev` major:minor in
  `/proc/diskstats` (`block_device_for()`; the Pi's `mmcblk0p2`). A filesystem with no backing device
  of its own (btrfs, overlayfs) falls back to the sum over physical disks — `loop`, `ram`, `dm-`, `md`
  and friends are skipped there, being layers over the same disks. Disk *space* changes too slowly to
  graph, so it rides along once per reply rather than per sample.
- Any value it cannot compute is `null`, never `0` — the frontend draws a gap.
- **CPU temperature** rides in each sample (`cpu_temp_c`) from `system_metrics.cpu_thermal_zone()`,
  resolved once: the zone whose `type` best matches `cpu-thermal` / `x86_pkg_temp` / `soc_thermal`
  …, else zone 0. A host with no thermal zone (WSL2) reports `temp_available: false` beside the
  samples, so the graph says so instead of waiting for data that will never come.

## `log_files.py` — the app's own log files (Ylläpito > Lokit)

`LogFiles` serves `LOG_CLEAR` for the backend's half: `backend.log` with its rotated backups and the
`ErrorLog` store (both from `../utils/logger_configurator.py`). The journal is never touched — it is
the host's, and deletes nothing selectively. Two strengths:
- **everything** — truncates the active file, deletes the backups, clears the error store;
- **keep warnings and errors** — keeps the WARNING+ records **with their continuation lines** (a
  traceback stays with the record that logged it) and leaves the error store alone, since it IS the
  warnings and errors.

The active file is rewritten **in place under the handler's lock**, never replaced: the handler holds
it open in append mode, and a replaced file would leave it writing into a deleted inode. The work
runs in a worker thread; the result carries `freedBytes`. The frontend clears its own files itself
(`frontend_v2/core/CLAUDE.md`, `Logs`). The clear logs itself at INFO, so "everything" leaves no
warning behind.

## `log_level.py` — the log level (Ylläpito > Lokit)

`LogLevel` applies `logging.level` / `logging.debugMinutes` (hook `logging`) through
`utils.logger_configurator.set_log_level()`, and the frontend follows the same key out of the schema,
so **one dropdown covers both halves**. The journal follows it too but never below INFO, so DEBUG
detail reaches the app's log files only. **DEBUG is temporary** — it logs a line per telemetry
property, which fills the size-capped log file fast enough to rotate away the warnings from before:
- **Choosing it asks for the duration first.** The entry carries `onSelect: {debug: "debugDuration"}`,
  so choosing DEBUG opens a dialog instead of writing; the dialog writes the hidden
  `logging.debugMinutes` and then the level. Either order ends right, since a duration change while
  at DEBUG restarts the countdown. Choosing DEBUG again while on it re-opens the dialog.
- **It returns to the level it came from.** Switching into DEBUG writes `logging.levelBeforeDebug`
  (state, straight through `Config`, in no schema) — except on the first apply after a start, whose
  "previous" level is only the environment's, so a DEBUG kept across a restart still returns to what
  was chosen before it. Missing → the startup level.
- **The row shows when and to what.** `runtime_info()` is registered with
  `ConfigService.register_runtime`, so the entry carries `runtime: {until, returnTo}` while at DEBUG —
  the backend's, because the countdown restarts with the process and only it knows when that was.
- **Expiry writes the level back through `ConfigService.apply_write()`**, not by changing the loggers
  alone: the same validated path a tap takes, so `config.json`, every open Options view (the schema
  broadcast) and the frontend's level all change together. The write re-enters `apply_config()`,
  which is why the timer task drops its own reference before writing.
- **A restart does not end DEBUG, but cannot make a timed one permanent.** `start_services` calls
  `apply_config()` once, so DEBUG left on comes back for one more full duration — debugging a startup
  problem needs exactly that. Only a crash loop faster than the duration would keep it on.
- **Toistaiseksi** (`debugMinutes: 0`, for development) arms no timer at all: DEBUG stays, across
  restarts, until another level is chosen. `runtime` then carries `{indefinite: true}`.
- `spotipy` stays pinned at INFO or above whatever the level (`../utils/CLAUDE.md`).
- `health()` is the *Loki* card: `warn` while at DEBUG, with the level, when and to what it returns,
  the log files' size and their folder.
