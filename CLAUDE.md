# Tesla-Homedash — Project Guide

> Guidance for working in this repository. These instructions override default behaviour;
> follow them exactly. **This root file is always loaded; detail specific to one area lives in a
> nested `CLAUDE.md` beside the code** (★ in §2), which loads when you work in that directory —
> read the nearest one before changing code there. Keep all of them current (§7.6).
>
> **At the start of a work session, follow §8** — first check the branch against GitHub (new
> commits to bring in, or a branch already merged), then work in the main checkout by default, and
> set up an isolated worktree only when a second session has to run in parallel.

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

Architecture in one line: a **Python asyncio backend** streams data over a **custom binary
protocol on TLS 1.3** (port 6969, password login first) to a **Qt 6 frontend**. The backend can fan
out to several frontends at once. Beyond the live dashboard there are History, Trips, Charging
(myenergi Zappi + Nord Pool spot price) and Options (*Asetukset*) views.

The frontend is **`frontend_v2/`**: Qt Quick/QML over a C++20 core.

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
      server.py                   # asyncio TLS server on :6969 (all interfaces, or loopback: server.reachability) — login gate, fan-out + handler routing
    auth_service/                 # ★
      auth_service.py             # AuthService — the login every connection passes (0xF0-0xF8), paired displays, Ylläpito › Näytöt
      scram.py                    # SCRAM-SHA-256-PLUS, server half (RFC 5802/7677; mirror: frontend_v2/core/scram.cpp)
      tls.py                      # The self-signed TLS 1.3 certificate, created on first start, pinned by the displays
    tesla_service/                # ★
      telemetry.py                # Teslemetry stream client (teslemetry_stream) → Vehicle.on_telemetry_event
      vehicle.py                  # Vehicle state, telemetry handler, HVAC REST commands, rate limiting, snapshots
      vehicle_data_property.py    # VehicleDataProperty / CalculatedVehicleDataProperty — value store, formula eval, serialize
      property_editor.py          # The telemetry-field table: log / line_mode / zero_based (0x63-0x66); its Options card is out of the schema for now
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
      weather_service.py          # WeatherService — the 10-min refresh of the Weather view's document, its cache + health
      weather_view.py             # The Weather view's document (WEATHER_VIEW): stations, ~10 days, sun/moon, warnings
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
      audio_service.py            # AudioService — system volume + output device + equalizer, applied from config.json
      equalizer.py                # PipeWireEqualizer — the filter-chain sink (5 bands + bass shelf) it owns and retunes live
      spectrum.py                 # AudioSpectrum — the spectrum of what plays (Media view, equalizer): records it after the equalizer while watched (0x1F/0x20)
    display_service/              # ★
      display_service.py          # DisplayService — panel power via wlopm; the frontend decides when
    system_service/               # ★
      system_metrics.py           # Pure /proc readers (uptime, CPU per core, memory, network, disk space + I/O, temp)
      system_status_service.py    # SystemStatusService — SYSTEM_GET_STATUS / _LOG: the service cards' probes and error lists
      system_history.py           # SystemHistory — background 2 s sampler, 10-min window, SYSTEM_GET_HISTORY (the graphs)
      log_files.py                # LogFiles — LOG_CLEAR for the app's own log files (Ylläpito › Lokit)
      log_level.py                # LogLevel — the Options view's log level; DEBUG returns to the previous level by itself
    config_service/               # ★
      config_service.py           # ConfigService — the Options view's backend half: SETTINGS_SCHEMA (the allow-list of
                                  #   runtime-editable config.json keys), validation, persistence, apply hooks, restart
    update_service/               # ★
      update_service.py           # UpdateService — in-place app updates (0xD0-0xD3): git fetch/checkout, uv sync,
                                  #   frontend rebuild, restart of both halves; two channels (main tip / newest v* tag)
    usb_import_service/           # ★
      usb_import_service.py       # UsbImportService — screensaver photos from a USB stick (0xE0-0xE4): lsblk,
                                  #   udisksctl mount, copy into ~/.config/Tesla-Homedash/screensaver
    influxdb_service/             # ★
      influxdb_handler.py         # Async InfluxDB client — telemetry write + Flux history reads
      series.py                   # delta/first/last/positive_increment over a history read
    utils/                        # ★
      config_parser.py            # Config (config.json) + get_env (.env)
      protocol.py                 # Binary protocol constants + frame() — single source of truth
      process.py                  # run(): every run-to-completion subprocess, timeout kill + reap
      atomic_write.py             # write_atomic(): every whole-file rewrite (temp + fsync + replace)
      timeline.py                 # collapse_transitions() + segment(): trips and charging sessions
      logger_configurator.py      # Shared stdout logging setup

frontend_v2/                      # ★ the Qt Quick/QML frontend (Main.qml, main.cpp)
  app/                            # Theme.qml (design tokens + settings façade), ViewController.qml, Navigation.qml, Format.js
  config/                         # settings.json (bundled Options-view schema), notifications.json
  core/                           # ★ C++: ServerClient, protocol.hh, Logger, AppConfig, Settings + QML singletons
    tesla/ media/ weather/ charging/ trip/ map/ notification/   # per-domain data models
  items/                          # QML components by domain
    settings/                     # ★ the Options view
    tesla/                        # ★ Tesla cards + the map
    util/                         # ★ screensaver, notifications, shared widgets and motion pieces
    charging/ history/ luna/ media/ trip/ weather/
  views/                          # one screen per view on the switcher
  resources/                      # fonts, icons, styles, Luna, shaders (ShaderEffect and material, compiled by qt_add_shaders)

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

**Two dev environments are supported, both on Qt 6.12.0** (the build requires 6.12). Use whichever box you are on:

| | Windows | Linux / WSL2 |
|---|---|---|
| Toolchain | MSVC 2022 (`vcvars64.bat` via `vswhere`) | `g++` from `build-essential` |
| Qt kit | `D:\Qt\6.12.0\msvc2022_64` | `~/Qt/6.12.0/gcc_64` |
| CMake | ships with Qt: `D:\Qt\Tools\CMake_64\bin\cmake.exe` | `cmake` from apt |
| `frontend_v2` script | `scripts\build-frontend.ps1` | `scripts/build-frontend.sh` |
| Compiler cache | `sccache` | `ccache` (CMakeLists probes for either) |
| `frontend_v2` binary | `frontend_v2\build\appfrontend_v2.exe` | `frontend_v2/build/appfrontend_v2` |

For **`frontend_v2`**, use the build script for your platform (see §8) — each finds the Qt kit and
runs the configure + build in one command (Ninja when installed), with compiler-cache reuse.

> **WSL2 setup** — a full bootstrap guide (system packages, Qt, InfluxDB, spotifyd, WSLg
> troubleshooting) lives in **`docs/wsl-dev-environment.md`**. Two things bite hardest: Qt needs the
> OpenGL **-dev** packages (`libgl1-mesa-dev`), not just `libgl1`, or `find_package` fails
> misleadingly on the `Quick` component; and the repo must live on ext4, not `/mnt/`.
>
> A third, subtler WSL2 bite — the GPU environment `build-frontend.sh --run` exports — is
> documented in `scripts/CLAUDE.md`.

### 3.3 Validation

There is no test suite beyond three standalone backend scripts (`backend/tests/test_spot_price.py`,
`test_trip_loader.py`, `test_auth.py`; run one with `uv run python tests/<file>` from `backend/`). Validate manually:
- **Backend**: `python -m compileall backend/src`, then start the stack and confirm
  telemetry / media / weather / HVAC flows in the logs.
- **Frontend**: rebuild, launch, connect to the backend, exercise the affected widgets.
- **Protocol changes**: test both directions — backend logs + frontend `qt`/`*.data` logs.
- New tests, when added, go under `backend/tests/test_*.py` and `frontend_v2/tests/` (Qt Test, CTest).

See the **Agent validation policy** (§7.3) for what the agent does vs. defers to the user.

## 4. Configuration files

| File | Read by | Documented in |
|---|---|---|
| `.env` (repo root, gitignored) — secrets (`VIN`, `API_KEY`, `INFLUX_TOKEN`, Spotify, myenergi, `TESLA_HOMEDASH_PASSWORD`), `CONFIG_PATH`, log level | backend `get_env`; `frontend_v2`'s `core/dotenv` for env-backed setting defaults | `backend/CLAUDE.md` |
| The backend config — called `config.json` throughout these docs; by default `~/.config/Tesla-Homedash/backend_config.json`, or `CONFIG_PATH`. Template: `config_template.json`. **Written at runtime** by the Options view | backend `Config` | `backend/CLAUDE.md`, `backend/src/config_service/CLAUDE.md` |
| `frontend_config.json` beside it — the frontend's saved setting overrides over the bundled schema `frontend_v2/config/settings.json` | `frontend_v2` `Settings` | `frontend_v2/CLAUDE.md` |
| Login state, not settings: the backend's `paired_displays.json` (the password's verifier + the displays) and `tls/` (its certificate) beside `config.json`; each display's `frontend_credentials.json` (token + certificate pin, 0600) beside `frontend_config.json` | `AuthService`; `ServerClient`'s `CredentialStore` | `backend/src/auth_service/CLAUDE.md`, `frontend_v2/core/CLAUDE.md` |
| `TESLA_HOMEDASH_*` environment variables | the frontend (`AppConfig`, setting defaults); `TESLA_HOMEDASH_LOG_LEVEL` and `_LOG_DIR` in both halves | `frontend_v2/CLAUDE.md` |
| The app's own log files — `backend.log`, `backend-errors.jsonl` (the warning/error store) and `frontend.log`, in `~/.local/state/Tesla-Homedash/logs` or `TESLA_HOMEDASH_LOG_DIR`. Written beside the journal; the temporary DEBUG log goes only here | both halves' loggers; cleared from Ylläpito › Lokit | `backend/src/utils/CLAUDE.md`, `frontend_v2/CLAUDE.md` |

External services: InfluxDB at `http://localhost:8086` (org `Tesla-Homedash`, bucket `data`);
Teslemetry stream at `eu.teslemetry.com`.

## 5. Architecture

### 5.1 Binary protocol

Frontend and backend speak a custom binary protocol over **TLS 1.3** on port **6969**, and a
display must log in (a SCRAM password login once, a remembered token after that) before anything
else crosses it — `backend/src/auth_service/CLAUDE.md`. All multi-byte integers are
**big-endian**. `utils/protocol.py` is the single source of truth for every constant and the
`frame()` helper; services build packets with `protocol.frame(...)` and the server only ships bytes.

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
`app/Theme.qml` — see `frontend_v2/CLAUDE.md`.

### 5.4 Where fetching happens

**The backend fetches what backend state decides** — playback, the car, the home location, a
schedule — and anything that needs a secret or whose failure belongs on a Ylläpito status card:
telemetry, Spotify, the radio's stations, the weather document, spot prices, the Zappi, the home's
timezone. **A display fetches what its own screen decides** — what a map shows, what a tap opens —
above all binary content Qt loads and caches natively: map tiles, radar frames and lightning, road
cameras, place names, address search. Routing those through the backend would only copy bytes to
every display. **Where the backend decides *what* and the display *when*, the backend sends a URL**
and each display fetches and caches it: the album cover (#84).

Every frontend fetch has a timeout (the C++ fetchers set their own; QML's come from
`core/qmlnetworkfactory.hh`), logs a failure to `frontend.log` — the Ylläpito cards never see it —
and says beside its code why it is not the backend's. Every display therefore needs internet
access, not just a route to the backend.

## 6. Event flows

**Live telemetry → UI**
```
Teslemetry stream → TelemetryHandler → Vehicle.on_telemetry_event → Vehicle.__update
  → VehicleDataProperty.update (formula) + get_stream_data (serialize)
  → protocol.frame(MSG_STREAM, …) → Server.broadcast → (every client)
  → ServerClient.onReadyRead → packetReceived → TeslaData.onPacket → applyValue
  → the registry property's NOTIFY signal → QML bindings on the Tesla singleton
  (logged fields are also written via InfluxDBHandler.write_tesla_data)
```

**User control (HVAC ± / toggle, media transport)**
```
QML tap (e.g. Tesla.switchClimate()) → protocol::frame(…) → ServerClient.sendPacket → TLS
  → Server.__read_loop → registered handler → Vehicle / MediaManager method
  → (effect streams back over MSG_STREAM / MEDIA_* and updates the UI)
```

**Vehicle sleeps (default reset)**
```
Teslemetry state event (state != "online") → Vehicle.__update → VehicleOnline.update(False)
  + broadcast via MSG_STREAM   (on a change only, waking the same way; repeats are dropped)
  → (edge) VehicleOnline value-callback → Vehicle.__on_sleep → Vehicle.__apply_sleep_defaults
  → each property with a sleep_default: apply_sleep_default (force value+timestamp, clear lock)
  → broadcast changed-only via MSG_STREAM   (no InfluxDB write — display-only)
```

**New client connects (login, then snapshot)**
```
TLS 1.3 handshake → Server.__handle_connection → AuthService.authenticate → AUTH_HELLO
  remembered:  AUTH_TOKEN → token hash + expiry checked
  first time:  AUTH_SCRAM_START → CHALLENGE → PROOF (bound to the certificate) → new token
  → AUTH_RESULT ok → ServerClient: pin/token stored, connected = true
  (refused → AUTH_RESULT reason → connection closed → BackendLoginPrompt)
→ for each registered service: service.stream_everything(writer)
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

**App update (the Options view's Päivitys card — out of the schema until the release-only rework, #56)**
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
APScheduler (10 min) → WeatherService.__update_view → WeatherViewBuilder.build (FMI timeseries
  JSON + CAP warnings, parts in parallel) → protocol.frame(WEATHER_VIEW, JSON) → Server.broadcast
  → Weather.view (frontend_v2) → the Weather view + the dashboard's hourly panel
```

**Spotify claim / release**
```
SpotifyPlayer poll → _update_state (under _state_lock) → device == target?
  claim:  MediaManager.claim_media_control → stop radio, set active, play, stream media type + state
  release: MediaManager.release_playback → load_default_media_player (radio, no auto-play)
```

## 7. Conventions

### 7.1 Style
- **Indentation**: 4 spaces everywhere (Python, C++, QML).
- **Python**: PEP 8 — `snake_case` functions/modules, `PascalCase` classes; `async`/`await`
  throughout (the whole backend is asyncio).
- **C++**: C++20; `.hh` headers / `.cpp` sources; `PascalCase` types, `camelCase` methods/members;
  Qt slot/signal naming (`onXxxUpdate`, `processXxx`).
- **UI language**: widget labels are **Finnish** (e.g. "Nopeus", "Akun Varaus", "Ilmastointi",
  "Sisä", "Ulko").
- **Binary code**: always network byte order — `struct.pack("!...")` / `QDataStream::BigEndian`.
- No committed formatter config — match the surrounding file.

### 7.2 Python docstrings
Every class and function gets a triple-quoted docstring documenting each argument — format and
example in `backend/CLAUDE.md`.

### 7.3 Agent validation policy
**The agent builds the frontend** — compile errors should surface in the session that caused them, not
on the user's next manual build. Use the platform's build script (§8) after frontend changes; it is
incremental and compiler-cached, so a rebuild after a small edit is cheap. Report build failures with
the compiler output. Running the built binary is still the user's call (it needs the 1280×800 display
and a live backend), so report what to look for at runtime rather than launching it.
**For visual QML work — layout, sizes, colours, states, motion — offer the QML live preview**: Qt's
QmlPreview MCP server patches saved QML into the running app with no rebuild, with the user watching
(`frontend_v2/CLAUDE.md`, *QML live preview*). It launches the app, so it is offered and started only
on a yes.
**Ignore clangd "file not found" / "unknown type" diagnostics on Qt headers** in the editor — the real
CMake build resolves them. For the backend: don't start long-running services; `python -m compileall
backend/src` is the syntax check and the user runs the live stack.

**Automated pre-build checks.** `.claude/hooks/check-edit.py` runs on every agent Edit/Write and is the
first line of defence, catching syntax breakage without a full build:
- `backend/src/**.py` → `python -m compileall backend/src`
- `**.qml` → `qmllint` (newest installed Qt kit; `TESLA_HOMEDASH_QMLLINT` overrides the path)

The QML check is deliberately gated to `[syntax]` warnings and `Error:` lines. qmllint reports hundreds of
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
write results and the issues box with its fix spotlight — plus the Yleinen wording pass, the
screensaver's fixed photo folder with its USB import (the in-app folder browser is gone, #50), and
the screensaver switch that stays unavailable until that folder holds photos — plus the removal of
the Yleinen › Ilmoitukset card pending its own section (#51), the Luna card (formerly
Lisäasetukset) at the bottom of Yleinen, and the timezone as a list defaulting to the host's zone —
plus the Kuvaajat card as named-level dropdowns (resolution, gesture sensitivity, redraw delay,
render margin; the gesture settings' Qt Graphs follow-up is #53), the map's Eleherkkyys and warp
settings as named levels too, whole-step default zoom, and the map imagery choice and MML key out of
the Options view (the key is `.env`-only) — plus the north-up map's 0.001° bearing bias that makes
it glide instead of stepping in whole pixels — plus the sidebar's section rows reduced to icon and title, and dependent settings nested under the
setting they belong to, hidden while it is off — plus the Sähkö section: the tariff as a
*Kiinteä* / *Pörssi* dropdown with each tariff's rows nested under it, one Zappi poll interval, and
the price source and Zappi serial out of the Options view (`config.json`-only) — plus the Tesla
section reduced to *Matkojen tunnistus* (the Telemetriakentät card is out of the schema until a later
update's fuller Tesla options; its plumbing stays) with the trip distance stepping 0.5 km — plus
Ylläpito: the *Päivitys* card out of the schema pending a release-only updater (#56), the port as a
plain typed field, the help lines cut from the connection and restart cards, and restart badges that
name the half (*sovelluksen* / *palvelimen uudelleenkäynnistys*) — plus the shared motion pieces in
`items/util/` (stretching `ToggleSwitch`, domino `Reveal` for nested rows, `ElasticFlickable`,
`WheelStepArea`) and settings rows that survive a write — plus the *Järjestelmän tila* sidebar section:
a group `view` that replaces the cards with four rolling graphs (CPU per core, memory, disk I/O,
network) fed by the backend's always-on sampler — plus its second round: a card per backend service
(standing, settings in effect, connected displays, warning/error counts with a dated list), mouse
hover on the graphs and a CPU temperature card; and Ylläpito's *Vianetsintä* replaced by *Lokit*: a
DEBUG switch that asks how long, and a clear with a keep-warnings option, both over the app's own log
files, to which the DEBUG detail now goes instead of the journal — plus the third round: the switch
became a *Lokitaso* dropdown (DEBUG asks how long and returns to the previous level), the old status
card retired from Ylläpito, every dialog swallowing the mouse wheel, and the system graphs rebuilt
on the app's own `HistoryGraph`, which can now draw several lines over one set of axes — plus its
fourth round: an overview card on top (healthy or not, the issues behind it, host and backend
uptime), the *Versio* card folded into *Palvelin* as a row, the charging rows on *Laturi* only with
trips on a *Matkat* card of their own, and service-card values that wrap instead of eliding — plus
Media › *Taajuuskorjain*: a five-band equalizer and a bass shelf on a PipeWire filter-chain the
audio service runs only while the curve is not flat, drawn as knobs on a curve by `EqualizerPanel`
— plus the Weather view (*Sää*) on live FMI data: the backend's `WEATHER_VIEW` document
(`weather_service/weather_view.py`) and a pannable, zoomable radar map — plus the pre-release
cleanup: the shared helpers listed in §7.8 in place of their copies, the dead code and stale
comments gone, and the rules in §7.8 that keep them out; its second round took the equalizer and
the Weather view through the same pass (the view's files out of `prototype/`, `frontend_v2`'s unread
`WEATHER_FORECAST` path removed) and added the settings check of §7.9 — plus the encrypted
connection (#64): TLS 1.3 on 6969 with a SCRAM password login, remembered per-display tokens and a
pinned certificate, and Ylläpito › Näytöt to list and revoke displays — plus the carousel view
switch: every switch a 3D turn the short way round past the views between, edge swipes that turn
them under the finger, and a swipe up from the bottom that opens them as a menu to spin and pick
from (left still, it picks the front view itself), which replaces the dock (its screensaver tile and auto-hide setting gone with it) — plus
the first step of the UI modernization: the home screen's cards on the Weather view's card
(`items/util/Card.qml`), with the map and the media card taking its corners (the map's painted from
the background under it, `TeslaMap.background`) and the album art
rounded to match (`RoundedImage` now honours its radius, smoothly); and the climate button's
switch as simulated water rippling across the dashboard's background, a new wave each time the
last has passed the farthest corner until the car answers, every wave drawn at random, the
background yellow and then the answer's colour before it fades back to the cover's
(`items/tesla/CLAUDE.md`; Qt Shader Tools a new build dependency); and a backdrop of the cover's
colours (`Media.palette`) drifting behind the dashboard's cards and the Media view and resting
while the music is paused (`items/media/MediaBackdrop.qml`); and the Media view's spectrum along
its bottom edge, pill bars or a line (Media › Spektri), drawn from what the host is playing
(`backend/src/audio_service/CLAUDE.md`), and the same spectrum behind Media › *Taajuuskorjain*'s
curve, recorded after the equalizer so a knob shows what it does to the sound; and the Weather
view's warning strip naming the area that covers the place, a tap opening the warnings whole, and
its radar refreshing the moment the view opens — plus the Kartta view's layers (#76), switched from
a menu in its corner: a live data card, the radar (the Weather card's loop, now a shared
`RadarLayer` that also turns with a heading-up map), the drive under way drawn behind the car
(`TRIP_GET_CURRENT`, the Trips view's detection) and OSM place names fetched from Overpass and kept
on disk per tile (#54's first step; `items/tesla/CLAUDE.md`) — then its second round: the drive
coloured by speed (a `GeoFrame` Shape carried with the map), FMI's warnings as areas (a demo, the
document's simplified `shapes`), Fintraffic's road cameras with their pictures and road weather,
the radar timeline upright on the left with a 15-minute loop, and zoom buttons that set the default
zoom (on the dashboard's map shown on a touch); and every UI icon from the Dazzle Line set, text
glyphs included (`frontend_v2/CLAUDE.md`, *Icons*); then the road camera dialog centred on frosted
glass with the maps still under any dialog (`TeslaMap.interactive`), Kartta's outside temperature
from FMI an hour into the car's sleep (`Tesla.asleepSince`), the Weather view's *Kelikamerat* button
on the cameras nearest the place, and the home location — *Yleinen › Sijainti › Koti*, an address or
a point on a map (`Geocoder`, Nominatim) — that the weather and the timezone follow, in place of the
place and timezone rows — plus the dashboard's hourly card marking each hour a warning covering the
place is in force in with a badge on its symbol, a tap opening the warnings, whose dialog is frosted
glass at reading height in every view, and the warnings that have ended left out of the document —
plus the map back on the car after a view switch and a stopped car centred in Liukuva (#55) —
plus snow and sleet in the weather charts and cards, snow in estimated cm (#68), the Sää status
card reporting a failed or partly stale refresh (#61), and the OSM place names on the Trips map with
the home marked on every map (#54), and EOX's imagery wherever a map looks past MML's coverage
in place of its blank white tiles (#59) — plus map tiles a Qt Location bug left blank requested
again (`BasemapSwitch`), with the shared tile cache at 300 MiB, room for EOX's tiles beside MML's —
and Qt 6.12 — plus the Qt Widgets `frontend/` removed from the
source tree (#65), `frontend_v2` the one frontend, and with it the backend's `WEATHER_FORECAST` frame
and its FMI WFS fetch, which only it read — plus the Kartta card's *Tyhjennä karttavälimuisti*,
which deletes the map tile cache and restarts the app (`items/tesla/CLAUDE.md`) — plus the media
seek bar's times in hours from an hour up, and a media title or artist line too long for its place
scrolling every so often while the music plays (`items/util/MarqueeText.qml`) — plus the graphs'
data work in C++ (#83 A, `GraphSeries`): the series bound as point lists and decimated, stepped and
traced with no per-point JavaScript, and the extra lines drawn as Shapes — and the Trips map's route
drawn as the Kartta view's drive is (#83 B, `SpeedRoute`), its geometry built in C++ (`RouteBands`)
in chunks, so a pan or zoom runs no per-point JavaScript and a live fix processes one short chunk;
with nothing left drawing with Canvas2D, Qt's default OpenGL context and no `CanvasPainter` module —
and the spectrum's per-frame work in C++ (#83 C, `SpectrumLevels`): the smoothing, the blur and the
line's path, with each bar fed its own level by a list model — and the radar's lightning on the GPU
(#83 D, `LightningLayer`): parsed and grouped by frame in C++, its quads built when the map rests,
so a loop step redraws nothing on the CPU — plus the fetch split (#79, #84; the rule in §5.4): the
album cover fetched by each display from the URL the backend sends (`MEDIA_STREAM_IMAGE_URL`),
through a disk cache, the home's timezone found by the backend when the home is written, one
road-camera list per display, and a timeout on every QML fetch — plus the car's sleep and waking
sent to the displays as they happen (#85), so Kartta's outside temperature returns to the car's
when it wakes, under one *ULKONA* caption whichever source it is — plus the Järjestelmän tila
cards' warnings and errors split into open ones, logged since a failing service last worked, and
past ones, muted (#82; `backend/src/system_service/CLAUDE.md`) — plus the dashboard weather card's
*Sää* pill, which opens the Weather view (`Navigation`), and the maps' radar redesign (#86): a
minimap in a corner (`RadarInset`) whose tap opens the Weather view too, the overlay translucent and
in step with it, both chosen and the loop's history set under the layer menu's *Sadetutka* — and
every radar loop's steps crossfading in a shader (`radarfade.frag`) — plus a still map of where the
camera is in the road camera dialog (`RoadCameraMap`: movable, with the home and the car), the
dialog stepping round every camera in Finland from the home outwards, its own map flying from one
to the next and the map it was opened over held on each, and the place names on every
map always rather than a layer — and Kartta's radar timeline only for the overlay alone, the minimap
carrying the time itself — plus the Media view's *Seuraavaksi* card: what Spotify plays next, asked
for by a display near a track's end (`MEDIA_GET_NEXT`) and risen on frosted glass into the
bottom-right corner 20 s before it, dropping again just before the track ends, a new cover
sliding in from the right (from the left after the back button), and a swipe over the cover
skipping either way — and Spotify's takeover opening the Media view on a panel nobody has touched
for 30 s (*Yleinen › Navigointi*) — plus the radio's libVLC calls on a thread of their own, so a
stop stuck inside VLC stalls only the radio, and a burst of skips tuning once to where it ends
(`backend/src/media_service/CLAUDE.md`).
When you land a change that touches documented behaviour, update this line.

### 7.8 Keeping the code clean
Four kinds of debris do not belong in this codebase; review your own diff for them before committing.

- **Comments say why, not what.** Keep a comment only if a first-time reader would lose information
  without it: the reason for a non-obvious choice (and the alternative rejected), an invariant, a
  unit or valid range, a protocol, timing or hardware constraint, a workaround with its ticket
  (QTBUG-…, labwc#…, #N). Don't restate the next line, narrate steps, or put section banners in a
  short file. A rationale lives once, at the definition; elsewhere a pointer at most.
- **Describe the present.** No "now", "no longer", "used to", "originally", "was previously", "until
  now" or "in later stages", in comments or in any `CLAUDE.md`; history is in git. A change fixes the
  comments and the nearest `CLAUDE.md` it makes wrong in the same commit, and a pointer to a section,
  function or file that no longer exists is a bug.
- **No dead code.** Delete what nothing uses — functions, parameters, flags, `Q_PROPERTY`s and
  `Q_INVOKABLE`s no QML reads, `Theme` tokens, whole files — instead of keeping it for later; git has
  it. Commented-out code is never committed. Don't add a parameter, option or extension point that
  no caller needs yet.
- **Reuse before you copy.** Check for a helper before writing a second copy of anything:
  - Wire format: `utils/protocol.py` (`frame`, `json_frame`, `parse_json_body`, `request_epoch`) and
    its mirror `frontend_v2/core/protocol.hh` (`frame`, `jsonRequestBody`, `readJsonReply`,
    `readString` / `writeString`, `readSeries`, `historyRequestBody`).
  - Backend: `utils/process.run` for any command run to completion, `utils/atomic_write.write_atomic`
    for any whole-file rewrite, `utils/timeline` for trip/charging segmentation,
    `influxdb_service/series.py` and `influxdb_handler.to_flux_time` for history reads,
    `BaseMediaPlayer._send*` for media packets.
  - Frontend: `items/history/HistoryGraph.qml` for any graph (its data work is
    `core/graphseries.hh`), `items/tesla/SpeedRoute.qml` for a route coloured by speed on a map
    (its geometry is `core/trip/routebands.hh`), `core/seriesbounds.hh` for graph bounds, `TeslaData::qmlName` for a
    registry id's property name, `app/Format.js` for displayed values ("—" for a missing one),
    `items/util/Card.qml` for a card (the dashboard's and the Weather view's look; its colours
    are `Theme`'s *card* tokens), `items/util/GlowBorder.qml` for a card's rim lit from inside,
    `items/settings/ModalDialog.qml` for a dialog, `SettingDetails.qml` for a status line with its
    dot, `DialogButton.qml` for a button, and the motion pieces in `items/util/`.

  Two copies that behave differently are merged only once you know which behaviour is right — ask
  when it is not obvious.

### 7.9 Settings for a new feature
Every feature you build or change ends with a **settings check**: list what in it a user could want
to set on the device — the feature's own on/off, intervals and timings, thresholds, a source or
device choice — above all the values the change hard-codes or reads only from `config.json`. Propose
each candidate to the user (key, type, default, range, which half owns it, its section and card) and
add the agreed ones on the same branch: a frontend tunable is a `config/settings.json` entry plus a
`Theme` binding (`frontend_v2/CLAUDE.md`), a backend one a `SETTINGS_SCHEMA` entry plus an
`apply_config()` hook (`backend/src/config_service/CLAUDE.md`). Protocol and hardware constraints
stay constants, and secrets stay in `.env`.

## 8. Session workflow — main checkout by default, worktree only for parallelism

The default is to **work in the main checkout** (`P:\Tesla-Homedash` on Windows, `~/Tesla-Homedash`
on WSL2). An isolated git worktree is only worth its setup cost when you genuinely need **two
sessions running at the same time** — reach for one *only then*. Most sessions are sequential and
stay in the main checkout with a warm build dir and incremental builds. Pure Q&A / exploration that
changes no files needs neither.

**Start — check the branch against GitHub before anything new.** A session that may change files
begins with `git fetch origin --prune` and settles two things first, telling the user what it found
and did:
1. **The branch has commits on the remote it lacks** (`git status -sb` reads `behind N`). Bring them
   in before any edit: `git merge --ff-only @{u}`. With uncommitted changes in the way, `git stash`,
   fast-forward, `git stash pop`, resolve any conflict keeping both sides' content, and drop the
   stash only once it is resolved. With local commits too (`ahead M, behind N`), `git pull
   --rebase`. When the incoming commits touch `frontend_v2/`, rebuild before relying on the binary.
   A branch with no upstream has nothing to bring in.
2. **The branch is already merged.** PRs are squash-merged, so `git branch --merged` cannot tell;
   ask GitHub (`gh pr list --head <branch> --state merged`) — an upstream that `git status -sb`
   reports `[gone]` after the prune is the same sign. Do not build on it: a commit added to a
   merged branch reaches `main` only through a new PR. `git checkout main && git pull`, and for new
   work branch off it with a `<type>/<slug>` name (types as in the worktree steps below), carrying
   any uncommitted changes across in a stash. Delete the merged local branch (`git branch -D`: a
   squash merge leaves it unmerged by ancestry) only when its tip is the PR's head
   (`gh pr view <branch> --json headRefOid`); commits past it never landed, so ask the user what
   becomes of them before deleting anything.

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
  (add `-Clean`, `-Config Release`, `-Fullscreen`, `-QmlPreview`). From **cmd.exe** use the `.cmd` shim:
  `scripts\build-frontend.cmd -Run` (same for `new-session.cmd` / `finish-session.cmd`).
  It imports the MSVC env and finds the newest Qt `msvc2022_64` kit.
- **Linux / WSL2:** `./scripts/build-frontend.sh --run` (add `--clean`, `--config Release`,
  `--fullscreen`, `--qml-preview` for the live preview; `--help` lists everything). No MSVC environment to import — it takes the kit from
  `--qt-prefix`, else `$QTDIR`, else the newest `~/Qt/*/gcc_64`, each only when it is at least the Qt
  version `CMakeLists.txt` requires (`scripts/CLAUDE.md`). A cold build is 163 targets; an
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
