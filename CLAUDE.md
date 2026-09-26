# Tesla-Homedash — Project Guide

> Guidance for working in this repository. These instructions override default behaviour;
> follow them exactly. **This root file is always loaded; detail specific to one area lives in a
> nested `CLAUDE.md` beside the code** (★ in §2), which loads when you work in that directory —
> read the nearest one before changing code there. Keep all of them current (§7.6).
>
> **At the start of a work session, follow §8** — work in the main checkout by default, and set up
> an isolated worktree only when a second session has to run in parallel.

## 1. What this project is

Tesla-Homedash is a **1280×800 desktop dashboard** built for an embedded touchscreen (the
reference deployment is a Raspberry Pi wired to a 10" display). It pulls four live data
sources into one glanceable surface:

- **Tesla telemetry** — speed, battery, range, odometer, charging and climate state, plus
  values derived from history (distance driven today / this month).
- **Media** — Nelonen Media internet radio by default; automatically hands over to Spotify
  (track, artist, album art, scrubbable progress, transport controls) the moment Spotify
  starts playing on the configured Spotify Connect device, then falls back to radio.
- **Weather** — current conditions plus the next five hours from the Finnish Meteorological
  Institute (FMI) open-data feed.
- **HVAC** — start/stop climate and adjust the target (pre-conditioning) temperature.

Architecture in one line: a **Python asyncio backend** streams data over a **custom binary TCP
protocol** (port 6969) to a **Qt 6 frontend**. The backend can fan out to several frontends at
once. Beyond the live dashboard there are History, Trips, Charging (myenergi Zappi + Nord Pool
spot price) and Options (*Asetukset*) views.

There are two frontends. **`frontend_v2/`** (Qt Quick/QML over a C++20 core) is the live target and
gets all feature work. **`frontend/`** (Qt Widgets) is the frozen predecessor — kept building,
rarely changed.

## 2. Project structure

★ = the directory has its own `CLAUDE.md`.

```
backend/                          # ★ orchestration, service contracts, .env + config.json keys
  run.py                          # Entry shim: asyncio.run(main())
  pyproject.toml                  # Package metadata + dependency pins
  uv.lock                         # Authoritative dependency lockfile (uv)
  requirements.txt                # Reference only; uv.lock is authoritative
  src/
    start_services.py             # Entrypoint / composition root — builds EVERY service (tesla, media, weather, trips, charging + myenergi), registers handlers, gathers the event loop. NOT tesla-specific despite the neighbours.
    server/                       # ★
      server.py                   # asyncio TCP server on 0.0.0.0:6969 — protocol-agnostic fan-out + handler routing
    tesla_service/                # ★
      telemetry.py                # Teslemetry stream client (teslemetry_stream) → Vehicle.on_telemetry_event
      vehicle.py                  # Vehicle state, telemetry handler, HVAC REST commands, rate limiting, snapshots
      vehicle_data_property.py    # VehicleDataProperty / CalculatedVehicleDataProperty — value store, formula eval, serialize
      property_editor.py          # The Options view's telemetry-field table: log / line_mode / zero_based (0x63-0x66)
    media_service/                # ★
      base_media_player.py        # Abstract player interface
      media_manager.py            # Orchestrator — owns both players, routes controls, gates streaming to the active one
      spotify_player.py           # Spotify Web API polling + controls (spotipy); APScheduler poll loop
      radio_player.py             # libVLC internet radio (Nelonen Media stations)
      setup/
        spotify_setup.py          # Standalone OAuth + Connect-device-ID helper (run once during setup)
      spotify_auth_service.py     # Re-authorisation from the Options view (0xA0-0xA4)
      spotify_device_service.py   # Device identification — scan playback, confirm, write spotifyDeviceId (0xA5-0xAB)
      spotify_oauth.py            # The one canonical SPOTIFY_SCOPE, the grant record + NonInteractiveSpotifyOAuth
    weather_service/              # ★
      weather_service.py          # FMI WFS polling, forecast serialization, 15-min refresh
    trip_service/
      trip.py, trip_loader.py     # On-demand trip detection from stored telemetry (the Trips view)
    charging_service/             # ★
      charging_loader.py          # On-demand charging-session detection (DetailedChargeState segmentation)
      charging_session.py         # Per-session energy + loss breakdown (charger vs AC-in vs battery) + spot cost
      spot_price.py               # SpotPriceProvider — Nord Pool FI spot price fetch/cache/convert (sähkötin.fi) + pricing helpers
      spot_price_service.py       # SpotPriceService — hourly live spot-price broadcast (SPOT_PRICE_STREAM)
    myenergi_service/             # ★
      myenergi_service.py         # myenergi Zappi cloud poll → CHARGER_STREAM broadcast + myenergi_data logging
    audio_service/                # ★
      audio_backend.py            # AudioBackend adapters (pactl / wpctl / amixer) + detect_backend()
      audio_service.py            # AudioService — system volume + output device, applied from config.json
    display_service/              # ★
      display_service.py          # DisplayService — panel power via wlopm; the frontend decides when
    system_service/               # ★
      system_metrics.py           # Pure /proc readers (uptime, CPU, memory, network, disk, temp)
      system_status_service.py    # SystemStatusService — SYSTEM_GET_STATUS, per-service health probes
      debug_logging.py            # DebugLogging — the Options view's temporary DEBUG log, self-clearing
    config_service/               # ★
      config_service.py           # ConfigService — the Options view's backend half: SETTINGS_SCHEMA (the allow-list of
                                  #   runtime-editable config.json keys), validation, persistence, apply hooks, restart
    update_service/               # ★
      update_service.py           # UpdateService — in-place app updates (0xD0-0xD3): git fetch/checkout, uv sync,
                                  #   frontend rebuild, restart of both halves; two channels (main tip / newest v* tag)
    influxdb_service/             # ★
      influxdb_handler.py         # Async InfluxDB client — telemetry write + Flux history reads
    utils/                        # ★
      config_parser.py            # Config (config.json) + get_env (.env)
      protocol.py                 # Binary protocol constants + frame() — single source of truth
      logger_configurator.py      # Shared stdout logging setup
    ui/plot/
      dataplot.py                 # Optional standalone PySide6/pyqtgraph plot (not used at runtime)

frontend_v2/                      # ★ Qt Quick/QML frontend — the live target (Main.qml, main.cpp)
  app/                            # Theme.qml (design tokens + settings façade), ViewController.qml
  config/                         # settings.json (bundled Options-view schema), notifications.json
  core/                           # ★ C++: ServerClient, protocol.hh, Logger, AppConfig, Settings + QML singletons
    tesla/ media/ weather/ charging/ trip/ notification/   # per-domain data models
  items/                          # QML components by domain
    settings/                     # ★ the Options view
    tesla/                        # ★ Tesla cards + the map
    util/                         # ★ dock, screensaver, shared widgets
    charging/ history/ luna/ media/ trip/ weather/
  views/                          # one screen per dock entry
  resources/                      # fonts, icons, styles, Luna

frontend/                         # ★ frozen Qt Widgets frontend (file layout in its CLAUDE.md)
scripts/                          # ★ build-frontend.{sh,ps1,cmd}; Windows-only new-/finish-session
docs/                             # wsl-dev-environment.md (WSL2 bootstrap), images/ (README screenshots)
.claude/                          # settings.json (permissions + edit hook), hooks/check-edit.py (§7.3)
config.json                       # Telemetry field metadata + radio/Spotify/weather/timezone config (gitignored; real values)
config_template.json              # Copy to config.json and fill in
```

## 3. Build, run & validation

### 3.1 Backend (uv)

The backend is an asyncio app managed with [uv](https://docs.astral.sh/uv/). Run from `backend/`.

- **Install uv (Windows)**: `winget install astral-sh.uv`
- **Sync deps**: `uv sync` (creates `backend/.venv` from `pyproject.toml` + `uv.lock`)
- **Run**: `uv run python run.py`
- **Syntax check**: `python -m compileall backend/src`
- **Add a package**: `uv add <package>`
- **Update everything**: `uv lock --upgrade && uv sync`

### 3.2 Frontend (CMake)

**Two dev environments are supported, both on Qt 6.11.1.** Use whichever box you are on:

| | Windows | Linux / WSL2 |
|---|---|---|
| Toolchain | MSVC 2022 (`vcvars64.bat` via `vswhere`) | `g++` from `build-essential` |
| Qt kit | `D:\Qt\6.11.1\msvc2022_64` | `~/Qt/6.11.1/gcc_64` |
| CMake | ships with Qt: `D:\Qt\Tools\CMake_64\bin\cmake.exe` | `cmake` from apt |
| `frontend_v2` script | `scripts\build-frontend.ps1` | `scripts/build-frontend.sh` |
| Compiler cache | `sccache` | `ccache` (CMakeLists probes for either) |
| `frontend_v2` binary | `frontend_v2\build\appfrontend_v2.exe` | `frontend_v2/build/appfrontend_v2` |

For **`frontend_v2`**, use the build script for your platform (see §8) — each finds the Qt kit and
runs the configure + build in one command (Ninja when installed), with compiler-cache reuse. The
frozen `frontend/` has its own commands in `frontend/CLAUDE.md`.

> **WSL2 setup** — a full bootstrap guide (system packages, Qt, InfluxDB, spotifyd, WSLg
> troubleshooting) lives in **`docs/wsl-dev-environment.md`**. Two things bite hardest: Qt needs the
> OpenGL **-dev** packages (`libgl1-mesa-dev`), not just `libgl1`, or `find_package` fails
> misleadingly on the `Quick` component; and the repo must live on ext4, not `/mnt/`.
>
> A third, subtler WSL2 bite — the GPU environment `build-frontend.sh --run` exports — is
> documented in `scripts/CLAUDE.md`.

### 3.3 Validation

No automated test suite exists yet. Validate manually:
- **Backend**: `python -m compileall backend/src`, then start the stack and confirm
  telemetry / media / weather / HVAC flows in the logs.
- **Frontend**: rebuild, launch, connect to the backend, exercise the affected widgets.
- **Protocol changes**: test both directions — backend logs + frontend `qt`/`*.data` logs.
- New tests, when added, go under `backend/tests/test_*.py` and `frontend/tests/` (CTest).

See the **Agent validation policy** (§7.3) for what the agent does vs. defers to the user.

## 4. Configuration files

| File | Read by | Documented in |
|---|---|---|
| `.env` (repo root, gitignored) — secrets (`VIN`, `API_KEY`, `INFLUX_TOKEN`, Spotify, myenergi), `CONFIG_PATH`, log level | backend `get_env`; `frontend_v2`'s `core/dotenv` for env-backed setting defaults | `backend/CLAUDE.md` |
| The backend config — called `config.json` throughout these docs; by default `~/.config/Tesla-Homedash/backend_config.json`, or `CONFIG_PATH`. Template: `config_template.json`. **Written at runtime** by the Options view | backend `Config` | `backend/CLAUDE.md`, `backend/src/config_service/CLAUDE.md` |
| `frontend_config.json` beside it — the frontend's saved setting overrides over the bundled schema `frontend_v2/config/settings.json` | `frontend_v2` `Settings` | `frontend_v2/CLAUDE.md` |
| `TESLA_HOMEDASH_*` environment variables | the frontend (`AppConfig`, setting defaults); `TESLA_HOMEDASH_LOG_LEVEL` in both halves | `frontend_v2/CLAUDE.md` |

External services: InfluxDB at `http://localhost:8086` (org `Tesla-Homedash`, bucket `data`);
Teslemetry stream at `eu.teslemetry.com`.

## 5. Architecture

### 5.1 Binary protocol

Frontend and backend speak a custom binary protocol over TCP port **6969**. All multi-byte
integers are **big-endian**. `utils/protocol.py` is the single source of truth for every
constant and the `frame()` helper; services build packets with `protocol.frame(...)` and the
server only ships bytes.

**Packet framing**
```
[4 bytes: payload length N] [N bytes: payload]
payload[0]      = message type byte
payload[1..N-1] = type-specific data
```

**Tesla stream value types**: `0` float `double(8B)`; `1` string `length(2B)+UTF-8`;
`2` bool `uint8(1B)`; `3` dict — sequence of `double(8B)` (Location = lat, lon).

The full message-type table, sub-ids and per-feature conventions are in
**`backend/src/utils/CLAUDE.md`**; `frontend_v2/core/protocol.hh` mirrors `protocol.py` and must
change with it. A reply to a request goes to the requesting client only (`send_to`), live state is
broadcast to every client, and a newly connected client receives each registered service's
snapshot.

**Adding a telemetry field** — update these in sync:
1. `config.json` `tesla data` — new entry with a unique `stream_id` (keys: `backend/CLAUDE.md`).
2. `frontend_v2/core/tesla/tesla_properties.json` — the matching registry entry, then regenerate
   `tesladata_gen.{hh,cpp}` with the `regen_tesla_data` CMake target. The generated files are
   committed; never edit them by hand.
3. The frozen `frontend/` only if it should show the field too — steps in `frontend/CLAUDE.md`.
   `vehicle_data_property.py` needs no change unless a new value type is introduced.

**Adding a command (F→B)**:
1. Add the type constant in `utils/protocol.py`.
2. In `start_services._register_handlers`, `server.register_handler(protocol.<NAME>, <async callable>)`.
   The callable gets `(payload, writer)` — the raw payload (no length prefix / type byte) and the
   requesting client's `StreamWriter`. Fire-and-forget commands ignore the writer; request/response
   handlers reply to just that client via `server.send_to(writer, …)`. The server routes by integer
   only.
3. In `frontend_v2`, add the constant to `core/protocol.hh` and build the packet with
   `protocol::frame()`.

### 5.2 Backend services

`backend/src/start_services.py` is the composition root: it constructs every service, registers
their handlers and snapshot providers on the `Server`, and `asyncio.gather`s the long-running
tasks. The server itself is a protocol-agnostic byte pipe. Orchestration, the duck-typed service
contracts and the `.env` / `config.json` keys are in `backend/CLAUDE.md`; each service's own
invariants are in its directory's `CLAUDE.md`.

### 5.3 Frontend

In `frontend_v2`, `core/serverclient` reassembles frames and hands each packet to a per-domain C++
data model or singleton that QML binds to, and user-tunable design tokens flow through
`app/Theme.qml` — see `frontend_v2/CLAUDE.md`. The frozen `frontend/` routes packets through Qt
Widgets datahandlers instead (`frontend/CLAUDE.md`).

## 6. Event flows

Frontend class names in the telemetry, control and weather flows are the frozen `frontend/`'s; in
`frontend_v2` the same packets land in the `core/` data models.

**Live telemetry → UI**
```
Teslemetry stream → TelemetryHandler → Vehicle.on_telemetry_event → Vehicle.__update
  → VehicleDataProperty.update (formula) + get_stream_data (serialize)
  → protocol.frame(MSG_STREAM, …) → Server.broadcast → (every client)
  → ServerClient.onReadyRead → TeslaDataHandler.processStreamData → per-field signal
  → TeslaDataWidget.updateDataXxx
  (logged fields are also written via InfluxDBHandler.write_tesla_data)
```

**User control (HVAC ± / toggle, media transport)**
```
Widget click → handler builds packet (QDataStream) → ServerClient.onSendMessageRequest → TCP
  → Server.__read_loop → registered handler → Vehicle / MediaManager method
  → (effect streams back over MSG_STREAM / MEDIA_* and updates the UI)
```

**Vehicle sleeps (default reset)**
```
Teslemetry state event (state != "online") → Vehicle.__update → VehicleOnline.update(False)
  → (edge) VehicleOnline value-callback → Vehicle.__on_sleep → Vehicle.__apply_sleep_defaults
  → each property with a sleep_default: apply_sleep_default (force value+timestamp, clear lock)
  → broadcast changed-only via MSG_STREAM   (no InfluxDB write — display-only)
```

**New client connects (snapshot)**
```
Server.__handle_connection → for each registered service: service.stream_everything(writer)
  → protocol.frame(...) per packet → Server.send_to(writer, …)   (delivered to the new client only)
```

**Settings write (the Options view)**
```
SettingRow delegate → Settings.setValue(key, value)
  local key:   coerce → QQmlPropertyMap.insert → QSaveFile → Theme binding re-evaluates (live)
  backend key: protocol::frame(CONFIG_SET) → Server.__read_loop → ConfigService.handle_set
    → validate against SETTINGS_SCHEMA → Config.set + Config.save (bak + atomic replace)
    → apply tier "hook": run the registered service apply_config()s
    → CONFIG_SET_RESULT → send_to(requesting client)   [+ CONFIG_SCHEMA broadcast to all]
    → Settings.parseSetResult → writeSucceeded/writeFailed → result beside the row's title
      (a keyless result → the notification pill)
  apply tier "restart": banner → CONFIG_RESTART → ConfigService.run → os._exit(42) → systemd
```

**App update (the Options view's Päivitys card)**
```
UpdatePanel opens → Updater.active → UPDATE_GET_STATE{fetch:true}
  → UpdateService.__refresh → git fetch (throttled) → resolve both channels
  → verdict per channel (merge-base --is-ancestor ×2) + eligibility (cat-file -e)
  → UPDATE_STATE broadcast → card renders current / target / verdict / blockers
second tap on the button → UPDATE_APPLY{channel, commit}
  → validate (channel enum, 40-hex sha, clean tree, tools, commit still current)
  → fetch → checkout --detach → build-frontend.sh → verify artifact → uv sync --locked
     (each step: own process group, streamed output, UPDATE_STATE broadcast ≤2 Hz)
  → job.restartFrontend → Updater.restartRequested → Settings.restartApp() (exit 42)
  → ConfigService.request_restart(force=True) → os._exit(42) → systemd restarts both
  any failure after the checkout → git checkout --detach <previous> + uv sync --locked
     (the job stays `running` across the rollback, so the banner and the restart veto hold)
```

**Weather refresh**
```
APScheduler (15 min) → WeatherService.__update_forecast → FMI fetch (executor)
  → serialize → protocol.frame(WEATHER_FORECAST, …) → Server.broadcast
  → WeatherDataHandler.onMainForecastUpdate → MainWeather → banner + 5 cards
```

**Spotify claim / release**
```
SpotifyPlayer poll → _update_state (under _state_lock) → device == target?
  claim:  MediaManager.claim_media_control → stop radio, set active, play, stream media type + state
  release: MediaManager.release_playback → load_default_media_player (radio, no auto-play)
```

## 7. Conventions

### 7.1 Style
- **Indentation**: 4 spaces everywhere (Python, C++, QML, QSS).
- **Python**: PEP 8 — `snake_case` functions/modules, `PascalCase` classes; `async`/`await`
  throughout (the whole backend is asyncio).
- **C++**: C++20; `.hh` headers / `.cpp` sources; `PascalCase` types, `camelCase` methods/members;
  Qt slot/signal naming (`onXxxUpdate`, `processXxx`).
- **QSS**: scoped per widget in `frontend/resources/styles/`, selected by object name
  (`#ClimateController`). Use the `:/resources/...` resource prefix (note the leading slash).
- **UI language**: widget labels are **Finnish** (e.g. "Nopeus", "Akun Varaus", "Ilmastointi",
  "Sisä", "Ulko").
- **Binary code**: always network byte order — `struct.pack("!...")` / `QDataStream::BigEndian`.
- No committed formatter config — match the surrounding file.

### 7.2 Python docstrings
Every class and function gets a triple-quoted docstring documenting each argument — format and
example in `backend/CLAUDE.md`.

### 7.3 Agent validation policy
**The agent builds the frontend** — compile errors should surface in the session that caused them, not
on the user's next manual build. Use `scripts\build-frontend.ps1` (§8) after frontend changes; it is
incremental and sccache-backed, so a rebuild after a small edit is cheap. Report build failures with
the compiler output. Running the built binary is still the user's call (it needs the 1280×800 display
and a live backend), so report what to look for at runtime rather than launching `gui.exe`.
**Ignore clangd "file not found" / "unknown type" diagnostics on Qt headers** in the editor — the real
CMake build resolves them. For the backend: don't start long-running services; `python -m compileall
backend/src` is the syntax check and the user runs the live stack.

**Automated pre-build checks.** `.claude/hooks/check-edit.py` runs on every agent Edit/Write and is the
first line of defence, catching syntax breakage without a full build:
- `backend/src/**.py` → `python -m compileall backend/src`
- `**.qml` → `qmllint` (newest installed Qt kit; `TESLA_HOMEDASH_QMLLINT` overrides the path)

The QML check is deliberately gated to `[syntax]` warnings and `Error:` lines. qmllint reports ~750
style diagnostics across `frontend_v2` (mostly `unqualified` access and `missing-property`) but **zero**
syntax warnings — blocking on that backlog would fire on untouched code, so the hook matches
`compileall`'s contract: catch syntax, leave style alone. A machine with no Qt kit skips the QML check
rather than blocking edits. The hook is a fast filter, not a substitute for the build.

### 7.4 Frontend logging
Byte-identical to the backend's format, stdout only — conventions in `frontend_v2/CLAUDE.md`.

### 7.5 Other conventions (git / PR)
- Commit subjects use short imperative prefixes: `Add:`, `Fix:`, `Update:`, `Remove:`, `Create:`.
- Keep each commit focused on one purpose.
- PRs include: change summary, reason, manual verification steps, and screenshots for UI changes.
- **When opening a PR, check whether the branch resolves any open issue(s).** Before writing the PR
  body, scan the open issues (`gh issue list`) against what the branch actually changes and, for every
  issue the work fixes, add a GitHub closing keyword (`Closes #N` / `Fixes #N`, one per issue) to the
  PR body so the issue auto-closes on merge instead of being left open after it's really fixed. If a
  branch touches an issue only partially, reference it (`Refs #N`) without a closing keyword. Don't
  invent a link — only tie a PR to an issue the change genuinely resolves.
- **Prompt to commit once work is verified.** This repo tends to accumulate uncommitted,
  manually-verified changes (the agent builds, but *runtime* verification happens on the user's
  side). When the user confirms a feature works — i.e. they say a manual test passed — proactively
  prompt to commit it then, in focused commits per the above, rather than letting verified work pile
  up. The agent still only commits when the user agrees; this is about offering at the right
  moment, not committing unprompted.
- **Push every commit as soon as it is made.** After each `git commit`, `git push` the branch right
  away (`git push -u origin <branch>` the first time) rather than letting local commits pile up.
- **When creating an issue, always add a label and assign it to the maintainer.** Work is tracked as
  GitHub issues on `einioville/Tesla-Homedash`. Every issue you open must carry at least one label
  (`gh issue create --label "<label>"`; pick or create the fitting one — `bug`, `enhancement`, etc.)
  and be assigned to the maintainer (`--assignee "@me"`). Never open an unlabelled or unassigned issue.
- **Close an issue as soon as a commit fixes it.** When a commit directly fixes an open issue — or the
  work it lands would resolve one — reference it in the commit (`Closes #N`) and close the issue with
  `gh issue close <N> --reason completed` and a short comment naming the commit, without asking first.
  An issue the work only partly addresses gets `Refs #N` and stays open.

### 7.6 Keeping these documents current
Documentation is part of the change, not an afterthought. Update the `CLAUDE.md` **nearest the code
you changed** — a service's own file for its invariants, `frontend_v2/core/CLAUDE.md` for a
singleton, and so on — and this root file only for what is cross-cutting: project structure,
build commands, the protocol overview, conventions, workflow. A new service or area with
load-bearing details gets its own `CLAUDE.md` in its directory and a ★ in §2. A feature spanning
directories is written up once, beside the file holding most of its facts, with pointers from the
others.

Keep this root file lean: it loads in every session, so detail that only matters inside one
directory belongs in that directory, and nested files never repeat what is here. Describe the
*current* behaviour and why it is that way; history belongs in commits, issues and PRs.

### 7.7 Documentation currency
Current as of the **issue sweep** on `feature/settings-options-view` — the Options-view series
(#30–#41, host reboot #40 included), the telemetry-field table (#29), the zero-based graph axis
(#42), the screen-off fixes (#43–#47), hold-to-repeat (#48) and the on-screen keyboard (#49) —
after the map-tuning pass and the split of this guide into per-directory `CLAUDE.md` files — plus the
second Options-view batch: navigation/home return, night mode, notification toggles, radio
autoplay/resume, the temporary debug log, map imagery, and the self-closing Spotify consent window — plus
the Media section's Spotify card redesign (per-row details, the grant record, device status, section
order), the radio remembering its last station in place of a default-station setting, inline
write results and the issues box with its fix spotlight — plus the Yleinen wording pass and the
screensaver switch that stays unavailable until a photo folder is set. When you land a change that touches documented behaviour, update this line.

## 8. Session workflow — main checkout by default, worktree only for parallelism

The default is to **work in the main checkout** (`P:\Tesla-Homedash` on Windows, `~/Tesla-Homedash`
on WSL2). An isolated git worktree is only worth its setup cost when you genuinely need **two
sessions running at the same time** — reach for one *only then*. Most sessions are sequential and
stay in the main checkout with a warm build dir and incremental builds. Pure Q&A / exploration that
changes no files needs neither.

**Backend — run one, shared.** The frontend connects to whatever backend is on `127.0.0.1:6969`
(`TESLA_HOMEDASH_BACKEND_HOST` / `_PORT` default there), and port 6969 is fixed so only **one**
backend can run at a time. Start it **once** (from the main checkout: `cd backend; uv run python
run.py` — identical on both platforms) and leave it — every frontend, in any checkout, connects to
it. Do **not** start a backend per session. Only a session that actually edits backend code runs its
own, and it stops the shared one first.

**Frontend — build from the CLI, no Qt Creator needed.** Build + run `frontend_v2` with the script
for your platform; both configure + build `appfrontend_v2` into `frontend_v2/build` and work from
the main checkout or any worktree.

- **Windows:** `powershell -ExecutionPolicy Bypass -File scripts\build-frontend.ps1 -Run`
  (add `-Clean`, `-Config Release`, `-Fullscreen`). From **cmd.exe** use the `.cmd` shim:
  `scripts\build-frontend.cmd -Run` (same for `new-session.cmd` / `finish-session.cmd`).
  It imports the MSVC env and finds the newest Qt `msvc2022_64` kit.
- **Linux / WSL2:** `./scripts/build-frontend.sh --run` (add `--clean`, `--config Release`,
  `--fullscreen`; `--help` lists everything). No MSVC environment to import — it takes the kit from
  `--qt-prefix`, else `$QTDIR`, else the newest `~/Qt/*/gcc_64`. A cold build is 163 targets; an
  incremental re-run is ~6s.

Open Qt Creator only when you need the debugger / QML profiler / designer. A **compiler cache** is
wired into `frontend_v2/CMakeLists.txt` — it probes for `sccache` *or* `ccache` and auto-enables
whichever is on PATH — so object files are reused across rebuilds *and across worktrees*; a fresh
worktree's "clean" build is mostly cache hits. Inspect with `sccache --show-stats` / `ccache
--show-stats`. (Per §7.3 the agent runs this script itself after frontend changes; the user still
runs the built binary.)

**When you *do* need a parallel session (worktree).**
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

**Finish — land via GitHub, never a local merge** (applies whether you used a branch or a worktree).
1. Commit per §7.5 (only once the user confirms the work is verified), then
   `git push -u origin <type>/<slug>`.
2. Open the PR with a proper body (summary, reason, manual verification, UI screenshots) per §7.5.
3. Merge **on GitHub**: `gh pr merge --squash --delete-branch`. GitHub is the single source of
   truth — **do not** merge into `main` locally (it diverges local `main` from `origin/main`). Then
   update the main checkout: `git checkout main && git pull`.
4. If a worktree was used: `ExitWorktree` (action `keep`), then on **Windows**
   `powershell -ExecutionPolicy Bypass -File scripts\finish-session.ps1 -Type <type> -Name "<name>"`
   — refuses until the PR reads MERGED (via `gh`), then removes the worktree, pulls main, deletes the
   merged local branch, and prunes. (`-Force` skips the merged check.) On **Linux/WSL2** there is no
   port: `git worktree remove <path> && git checkout main && git pull && git branch -d <type>/<slug>
   && git worktree prune`, after checking the PR merged yourself.

**Memory caveat.** Memories load at session start from the main checkout, so their guidance stays in
context even after an `EnterWorktree`. But the memory *store* follows the working directory, so any
durable memory you write during a worktree session must target the **main checkout's** project-memory
dir, not the worktree's (which is deleted at cleanup).
