# Tesla-Homedash — Project Guide

> Guidance for working in this repository. These instructions override default behaviour;
> follow them exactly. Keep this document up to date (see §7.6) and bump the currency
> marker (§7.7) whenever you change behaviour the doc describes.
>
> **At the start of a work session, follow the worktree ritual in §8** — ask what we're doing
> and a name for it, then spin up an isolated worktree before changing any files.

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
TCP protocol** (port 6969) to a **Qt6 C++20 Widgets frontend**. The backend can fan out to
several frontends at once.

A second, exploratory **QML** frontend lives in `frontend_prototype/`. It is **out of scope
for this document** — all feature work and everything below concerns the production **Qt
Widgets** frontend in `frontend/`.

## 2. Project structure

```
backend/
  run.py                          # Entry shim: asyncio.run(main())
  pyproject.toml                  # Package metadata + dependency pins
  uv.lock                         # Authoritative dependency lockfile (uv)
  requirements.txt                # Reference only; uv.lock is authoritative
  src/
    start_services.py             # Entrypoint / composition root — builds EVERY service (tesla, media, weather, trips, charging + myenergi), registers handlers, gathers the event loop. NOT tesla-specific despite the neighbours.
    server/
      server.py                   # asyncio TCP server on 0.0.0.0:6969 — protocol-agnostic fan-out + handler routing
    tesla_service/
      telemetry.py                # Teslemetry stream client (teslemetry_stream) → Vehicle.on_telemetry_event
      vehicle.py                  # Vehicle state, telemetry handler, HVAC REST commands, rate limiting, snapshots
      vehicle_data_property.py    # VehicleDataProperty / CalculatedVehicleDataProperty — value store, formula eval, serialize
    media_service/
      base_media_player.py        # Abstract player interface
      media_manager.py            # Orchestrator — owns both players, routes controls, gates streaming to the active one
      spotify_player.py           # Spotify Web API polling + controls (spotipy); APScheduler poll loop
      radio_player.py             # libVLC internet radio (Nelonen Media stations)
      setup/
        spotify_setup.py          # Standalone OAuth + Connect-device-ID helper (run once during setup)
    weather_service/
      weather_service.py          # FMI WFS polling, forecast serialization, 15-min refresh
    trip_service/
      trip.py, trip_loader.py     # On-demand trip detection from stored telemetry (the Trips view)
    charging_service/
      charging_loader.py          # On-demand charging-session detection (DetailedChargeState segmentation)
      charging_session.py         # Per-session energy + loss breakdown (charger vs AC-in vs battery) + spot cost
      spot_price.py               # SpotPriceProvider — Nord Pool FI spot price fetch/cache/convert (sähkötin.fi) + pricing helpers
      spot_price_service.py       # SpotPriceService — hourly live spot-price broadcast (SPOT_PRICE_STREAM)
    myenergi_service/
      myenergi_service.py         # myenergi Zappi cloud poll → CHARGER_STREAM broadcast + myenergi_data logging
    audio_service/
      audio_backend.py            # AudioBackend adapters (pactl / wpctl / amixer) + detect_backend()
      audio_service.py            # AudioService — system volume + output device, applied from config.json
    display_service/
      display_service.py          # DisplayService — panel power via wlopm; the frontend decides when
    system_service/
      system_metrics.py           # Pure /proc readers (uptime, CPU, memory, network, disk, temp)
      system_status_service.py    # SystemStatusService — SYSTEM_GET_STATUS, per-service health probes
    config_service/
      config_service.py           # ConfigService — the Options view's backend half: SETTINGS_SCHEMA (the allow-list of
                                  #   runtime-editable config.json keys), validation, persistence, apply hooks, restart
    influxdb_service/
      influxdb_handler.py         # Async InfluxDB client — telemetry write + Flux history reads
    utils/
      config_parser.py            # Config (config.json) + get_env (.env)
      protocol.py                 # Binary protocol constants + frame() — single source of truth
      logger_configurator.py      # Shared stdout logging setup
    ui/plot/
      dataplot.py                 # Optional standalone PySide6/pyqtgraph plot (not used at runtime)

frontend/                         # Qt6 Widgets GUI (the production frontend)
  CMakeLists.txt                  # Qt6 Core/Gui/Widgets/Network/QuickWidgets/Location/Positioning/Quick/Svg/Graphs/Concurrent
  resources.qrc                   # Qt resource bundle manifest
  resources/
    fonts/                        # Gotham Rounded Medium OTF
    icons/                        # SVG/PNG control + climate + weather icons
    styles/                       # Per-widget QSS, selected by object name
  src/
    main.cpp                      # Entry — installs logger, global white-text default, loads font/AppConfig, builds MainWindow
    mainwindow.{hh,cpp}           # 10×16 grid layout; constructs widgets, datahandlers, ServerClient
    config/appconfig.{hh,cpp}     # AppConfig::load() — the one place that reads frontend env vars
    utils/logger.{hh,cpp}         # Logger — stdout sink byte-identical to the backend format
    server_client/serverclient.{hh,cpp}   # QTcpSocket client — frame reassembly, demux to per-type signals, reconnect
    tesla/
      vehicle.{hh,cpp}            # TeslaDataProperty registry (data_id ⇄ stream_id, unit, value_type)
      datahandler/tesladatahandler.{hh,cpp}  # kRoutes table: deserialize stream packets → per-property signals; outbound HVAC commands
      widgets/
        tesladatawidget.{hh,cpp}            # Abstract TeslaDataWidget / TeslaDataMultiWidget
        singletesladataentry.{hh,cpp}       # One labelled value
        dataentrylist/tesladataentrylist.{hh,cpp}  # Grouped list of entries
        map/teslamap.{hh,cpp} + map.qml     # QQuickView OSM map (location + heading)
        climate/
          climatecontrollercard.{hh,cpp}    # Climate panel container
          temperaturecard.{hh,cpp}          # Inside/outside/target temp readout
          teslaclimatestarter.{hh,cpp}      # HVAC on/off button + state glow
          teslaseatwidget.{hh,cpp}          # Seat heater level indicator
          teslasteeringwidget.{hh,cpp}      # Steering-wheel heater indicator
    mediaplayer/
      datahandler/mediaplayerdatahandler.{hh,cpp}  # Parse media packets (cover art decoded to QImage off-thread); outbound transport commands
      widgets/mediaplayercard.{hh,cpp}      # Album art, k-means dominant colour, gradient bg, progress, transport
    weather/
      datahandler/weatherdatahandler.{hh,cpp}  # Parse forecast packets → MainWeather
      widgets/
        mainweather.{hh,cpp}                # Weather panel container
        currentweathercard.{hh,cpp}         # Current-hour banner
        weatherforecastcard.{hh,cpp}        # One forecast-hour card (×5)

frontend_prototype/               # Exploratory QML rewrite — OUT OF SCOPE for this guide
config.json                       # Telemetry field metadata + radio/Spotify/weather/timezone config (gitignored; real values)
config_template.json              # Copy to config.json and fill in
docs/images/                      # README screenshots
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

For the active **`frontend_v2`**, prefer the build script for your platform (see §8) — each
finds the Qt kit and runs a Ninja configure + build in one command, with compiler-cache reuse.
The rest of this section covers the **frozen Widgets `frontend/`**.

> **WSL2 setup** — a full bootstrap guide (system packages, Qt, InfluxDB, spotifyd, WSLg
> troubleshooting) lives in **`docs/wsl-dev-environment.md`**. Two things bite hardest: Qt needs the
> OpenGL **-dev** packages (`libgl1-mesa-dev`), not just `libgl1`, or `find_package` fails
> misleadingly on the `Quick` component; and the repo must live on ext4, not `/mnt/`.
> A third bite is subtler, and has **two halves that must land together**. WSL2 exposes the GPU as
> `/dev/dxg` with **no `/dev/dri`**, so Mesa lands on llvmpipe and Chromium refuses every WebGL
> context — which breaks the Spotify consent page specifically. `GALLIUM_DRIVER=d3d12` reaches the
> real adapter. But once Chromium HAS a GPU it hands frames to Qt as **dma_buf native pixmaps**, and
> Mesa's d3d12 EGL driver does not expose `EGL_EXT_image_dma_buf_import` — so that fix alone trades
> "renders, no WebGL" for "WebGL, renders nothing": a black panel spamming *"Failed to get native
> pixmap due to dma_buf acquisition failure"*. `QTWEBENGINE_CHROMIUM_FLAGS=--disable-gpu-compositing`
> keeps the GPU process (and WebGL) while delivering frames through shared memory.
> `scripts/build-frontend.sh` exports **both** under `--run` when it sees that host shape. Measured
> on a 600×400 grab of a solid-colour page: plain d3d12 = 0 % of the expected colour, with the flag
> = 100 %, WebGL still on the real D3D12 adapter. The flag reaches only QtWebEngine's Chromium, not
> Qt Quick, so the dashboard keeps the hardware path — the scene graph moves off llvmpipe onto the
> real adapter, so the maps and graphs get *faster*, not slower.
>
> **Reading the log:** two lines persist in the healthy state and are not failure signals — the
> `libEGL warning: failed to get driver name` block (the Qt Quick window, not Chromium) and exactly
> ONE `EGL: EGL_EXT_image_dma_buf_import extension is not supported` (Qt's `EGLHelper` always probes
> for it). The discriminators are the **repeated** `Failed to get native pixmap due to dma_buf
> acquisition failure` lines and `WebGL1 blocklisted`; both must be absent. Measured: broken config
> = 1 EGL probe line + 3 native-pixmap failures; fixed = 1 EGL probe line + 0.
>
> Three switches that look plausible here are **no-ops**, so don't reach for them: `--in-process-gpu`
> is already set unconditionally by QtWebEngine, `--disable-gpu-memory-buffer-compositor-resources`
> is already false on Linux, and **SwiftShader is compiled out of the Qt binary build**
> (`enable_swiftshader=false` in `qtwebengine/src/core/CMakeLists.txt`, no `libvk_swiftshader*`
> shipped), so `--use-angle=swiftshader` silently falls through to ANGLE-on-llvmpipe.

**Linux / WSL2 — the frozen `frontend/`** (rarely needed; `frontend_v2` is the live target):

```bash
cmake -S frontend -B frontend/builddir -G Ninja -DCMAKE_PREFIX_PATH="$QTDIR"
cmake --build frontend/builddir --target all
./frontend/builddir/gui
```

**Windows — the frozen `frontend/`:**

- **Configure** (required once before the first build, and after CMakeLists changes):

  ```
  D:\Qt\Tools\CMake_64\bin\cmake.exe -S frontend -B frontend/builddir -G Ninja -DCMAKE_PREFIX_PATH=D:/Qt/6.11.1/msvc2022_64
  ```

- **Build**:

  ```
  D:\Qt\Tools\CMake_64\bin\cmake.exe --build frontend/builddir --target all
  ```

- **Run**: `.\frontend\builddir\gui.exe`
  (PowerShell with overrides: `$env:TESLA_HOMEDASH_FULLSCREEN=1; .\frontend\builddir\gui.exe`)

**Important (Windows only):** the Ninja generator does **not** set up the MSVC toolchain itself
(unlike the Visual Studio generator). Run the configure/build from an **"x64 Native Tools Command Prompt
for VS 2022"** (so `cl.exe` is on PATH), or let Qt Creator's configured kit drive it.
Single-config Ninja puts the binary directly at `frontend/builddir/gui.exe` (`gui` on Linux) —
there is no `Debug/` or `Release/` subfolder. On Linux `g++` is already on `PATH`, so there is no
environment to import.

### 3.3 Validation

No automated test suite exists yet. Validate manually:
- **Backend**: `python -m compileall backend/src`, then start the stack and confirm
  telemetry / media / weather / HVAC flows in the logs.
- **Frontend**: rebuild, launch, connect to the backend, exercise the affected widgets.
- **Protocol changes**: test both directions — backend logs + frontend `qt`/`*.data` logs.
- New tests, when added, go under `backend/tests/test_*.py` and `frontend/tests/` (CTest).

See the **Agent validation policy** (§7.3) for what the agent does vs. defers to the user.

## 4. Configuration files

### `.env` (repo root, gitignored)
Required secrets/paths, loaded by `utils/config_parser.get_env`:
- `CONFIG_PATH` — absolute path to the backend's config JSON. **Optional since the
  config relocation (issue #41)**: unset → `$XDG_CONFIG_HOME`(or `~/.config`)`/Tesla-Homedash/
  `backend_config.json`, via `config_parser.default_config_path()`. Set it only when the
  deployment keeps its config elsewhere.
- `VIN` — Tesla vehicle identification number
- `API_KEY` — Teslemetry access token
- `INFLUX_TOKEN` — InfluxDB auth token
- `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` — from your Spotify Developer App

`start_services.main()` fails fast if any of these are missing. **Optional:** `MYENERGI_HUB_SERIAL`
/ `MYENERGI_API_KEY` (myenergi cloud digest-auth creds) — absent → the charger service is skipped
and the rest of the stack still runs. Also optional: `TESLA_HOMEDASH_LOG_LEVEL` —
`debug`/`info`/`warning`/`error`/`critical`, **default `info`** (invalid → `info` + a warning),
mirroring the frontend variable of the same name. Read by `configure_logging()`, which calls
`load_dotenv()` itself because `get_env`'s lazy load happens after logging is set up; a real
environment variable (systemd `Environment=`) still wins over `.env`. **Keep the deployment at
`info`** — `debug` logs a line per telemetry property and rotates the Pi's journal fast enough to
destroy incident history.

### `config.json` (copy from `config_template.json`)
Parsed once by `Config` and injected into every service. Keys:
- `tesla data` — per-field metadata map: `stream_id`, `category`, `unit`, `formula` (sympy
  string or null), `log` (bool), and optional `sleep_default` — the value the field reverts to
  when the vehicle goes to sleep (omit or `null` to leave it at its last reading; the default is
  a final value, the `formula` is **not** re-applied to it). Optional `line_mode` (issue #20) —
  the History-graph render mode for the field: `"step"` (hold the previous value, then jump — the
  default when absent; right for sampled/held signals like `VehicleSpeed` or setpoints) or
  `"linear"` (straight point-to-point line; right for accumulators / continuous quantities like
  `Odometer`, the energy counters, `OutsideTemp`). Display-only hint handed to the frontend over
  `TESLA_GRAPH_PROPERTIES`. A field is graphable (appears in the History dropdown) only if
  `log: true` **and** numeric — set `log: false` to keep a numeric field off the graph (e.g.
  `GpsHeading`, which wraps 0↔360 and isn't worth graphing).
- `calculated tesla data` — derived fields (`DrivenToday`, `DrivenThisMonth`): adds
  `source_data_property_id`, `period` (`day`/`month`), `calculation_formula` (e.g. `y - x`).
- `radioMediaIds` — station name → Nelonen Media id; `defaultRadioStation` — a key from it.
- `spotifyDeviceId` — target Spotify Connect device id; `spotifyRedirectUri`
  (default `http://127.0.0.1:8080/callback`, must match the Spotify app); `spotifyCachePath`
  — spotipy OAuth token cache; `spotifyMarket` — ISO-3166-1 alpha-2 (e.g. `FI`).
- `weatherPlace` — FMI place (e.g. `Tampere`); `timeZone` — IANA zone (e.g. `Europe/Helsinki`).
- `myenergi` (optional) — Zappi tunables: `zappiSerial` (`""` = auto-select the first Zappi),
  `pollIntervalIdleSeconds` / `pollIntervalActiveSeconds`, `minSessionEnergyKwh`, `sessionMergeMinutes`.
- `trip` (optional) — trip-detection tunables: `min_stop_minutes`, `min_trip_distance_km`.
- `electricityPriceEurPerKwh` (optional) — flat €/kWh tariff for the Charging view's cost tiles
  (`Latauskulut` = charging cost, `Sähkölasku` = total home electricity cost); `null`/absent → "—".
  Now a **fallback**: used per-hour when spot pricing is off or a given hour has no spot price.
- `spotPrice` (optional, issue #12) — Nord Pool FI hourly spot pricing for the cost tiles + the live
  price tile: `enabled` (master switch; `false` → flat-tariff pricing, no live service),
  `vatPercent` (Finnish electricity VAT, default `25.5`), `marginCentsPerKwh` (seller margin c/kWh
  added before VAT), `baseUrl` (the no-key sähkötin.fi range endpoint; swappable for another source).
  All-in €/kWh for an hour = `(spot + marginCentsPerKwh/100) × (1 + vatPercent/100)`. Prices are
  fetched on demand (no self-logging) — historical hours price past sessions retroactively.

> **`config.json` is now written at runtime.** The frontend's Options view can change the
> subset of keys listed in `config_service.SETTINGS_SCHEMA` (§5.2.8). `Config` gained
> `set(dotted_key, value)` + `save()`: the save snapshots the previous file to
> `config.json.bak`, then writes atomically (temp file in the same directory + `os.replace`,
> with an `fsync` first). `Config.__init__` rolls back to that `.bak` if the live file fails
> to parse or validate — which is what stops a restart-tier setting from restart-looping
> systemd. The structural parts (`tesla data`, `calculated tesla data`, `radioMediaIds`) are
> deliberately NOT in the schema: the frontend registry mirrors them, so editing them at
> runtime would desync the two halves (that's issue #29).

### Frontend environment variables (read only by `AppConfig::load()`)
All optional; defaults match the embedded target.
- `TESLA_HOMEDASH_BACKEND_HOST` (default `127.0.0.1`)
- `TESLA_HOMEDASH_BACKEND_PORT` (default `6969`)
- `TESLA_HOMEDASH_WINDOW_WIDTH` / `_HEIGHT` (default `1280` / `800`)
- `TESLA_HOMEDASH_FULLSCREEN` — `1`/`true`/`yes` for fullscreen (default off). Fullscreen
  skips the fixed-size lock; windowed mode locks to the configured size.
  **In `frontend_v2` this is the `fullscreen` SETTING's env default**, not a variable
  `AppConfig` reads — so a saved override in the Options view beats it, per the usual
  `schema default < env/.env < saved override` precedence. It did nothing at all until the
  setting existed: `Main.qml` was a hard-locked 1280×800 window and `scripts/build-frontend.sh
  --fullscreen` exported the variable to a binary that ignored it.
- `TESLA_HOMEDASH_LOG_LEVEL` — `debug`/`info`/`warning`/`error`/`critical` (default `info`;
  invalid → `info` + a startup warning).
- `TESLA_HOMEDASH_SETTINGS_FILE` — override the path of the frontend's writable settings
  file (default `<QStandardPaths::GenericConfigLocation>/Tesla-Homedash/frontend_config.json`
  — i.e. beside the backend's `backend_config.json`). A file at the pre-move
  `AppConfigLocation/settings.json` is copied over once on first run.
- `TESLA_HOMEDASH_SCREENSAVER_DIR` — no longer read by `AppConfig`; it now supplies the
  DEFAULT for the `screensaverDir` setting, which owns the value and can change it live.

**Frontend settings file.** `frontend_v2/config/settings.json` is the *bundled schema*
(defaults, types, bounds, Finnish labels) compiled into the binary; the user's overrides are
written to the writable file above via `QSaveFile`. A schema entry may name an `env` key,
making that environment variable supply the setting's **default** — so the precedence is
`schema default < env/.env < saved user override`, and an existing deployment's `.env` keeps
working until the user changes the setting on-device. `TESLA_HOMEDASH_BACKEND_HOST`, `_PORT`
and `_SCREENSAVER_TIMEOUT_MIN` are wired this way; `AppConfig` reads the resolved values from
`Settings` rather than the environment directly.

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

**Message types**

| Byte | Name | Dir | Payload |
|------|------|-----|---------|
| `0x01` | MSG_JSON | F→B | JSON body |
| `0x03` | MSG_TERMINATE | F→B | (empty) |
| `0x04` | MSG_STREAM | B→F | `stream_id(2B) + value_type(1B) + value + timestamp(8B)` |
| `0x14` | MEDIA_STREAM_IMAGE | B→F | Raw image bytes (JPEG/PNG) |
| `0x15` | MEDIA_STREAM_NAME | B→F | `length(2B) + UTF-8` |
| `0x16` | MEDIA_STREAM_PROGRESS | B→F | `progress_ms(4B)` |
| `0x17` | MEDIA_STREAM_DURATION | B→F | `duration_ms(4B)` |
| `0x18` | MEDIA_SKIP | F→B | (empty) |
| `0x19` | MEDIA_SKIP_BACKWARD | F→B | (empty) |
| `0x1A` | MEDIA_PAUSE_PLAY | F→B | (empty) |
| `0x1B` | MEDIA_IS_PLAYING | B→F | `bool(1B)` |
| `0x1C` | MEDIA_SET_PROGRESS | F→B | `progress_ms(4B)` |
| `0x1D` | MEDIA_STREAM_ARTISTS | B→F | `length(2B) + UTF-8` |
| `0x1E` | MEDIA_STREAM_TYPE | B→F | `media_type(1B)`: 0x01=radio, 0x02=spotify |
| `0x30` | WEATHER_FORECAST | B→F | repeated `sub_id(1B) + value` |
| `0x60` | TESLA_SWITCH_CLIMATE | F→B | (empty) |
| `0x61` | TESLA_MINUS_TEMP | F→B | (empty) |
| `0x62` | TESLA_PLUS_TEMP | F→B | (empty) |
| `0x70` | TESLA_GET_GRAPH_PROPERTIES | F→B | (empty) |
| `0x71` | TESLA_GRAPH_PROPERTIES | B→F | `count(2B)` + per property `id_len(2B)+id + unit_len(2B)+unit + cat_len(2B)+category + mode_len(2B)+line_mode` (UTF-8); `line_mode` = `step`/`linear` graph render hint |
| `0x72` | TESLA_GET_HISTORY | F→B | `range_code(1B)` (0=1h,1=1d,2=1M,3=custom,4=1week) + `id_len(2B)+id` + `start_ms(8B)` + `end_ms(8B)` |
| `0x73` | TESLA_HISTORY | B→F | `id_len(2B)+id` + `status(1B)` + `count(4B)` + count×(`ts_ms(8B)` + `value(8B double)`) |
| `0x50` | CHARGER_STREAM | B→F | myenergi charger live state: repeated `sub_id(1B) + value` (see charger sub-ids below) |
| `0x80` | CHARGING_GET_LIST | F→B | `start_ms(8B) + end_ms(8B)` |
| `0x81` | CHARGING_LIST | B→F | `req_start(8B)+req_end(8B)+count(2B)` + count×(`start(8B)+end(8B)+charger_kwh(8B double)`) |
| `0x82` | CHARGING_GET_SUMMARY | F→B | `start_ms(8B) + end_ms(8B)` |
| `0x83` | CHARGING_SUMMARY | B→F | `session_id(8B)+status(1B)+start(8B)+end(8B)` + 11×`double` (per-session losses + `cost_eur` + `avg_price_eur_per_kwh`) |
| `0x84` | CHARGING_GET_MONTH | F→B | (empty) |
| `0x85` | CHARGING_MONTH | B→F | `status(1B)` + 13×`double` (month aggregate — see below) |
| `0x86` | CHARGER_GET_HISTORY | F→B | `range_code(1B) + id_len(2B)+id + start_ms(8B) + end_ms(8B)` |
| `0x87` | CHARGER_HISTORY | B→F | `id_len(2B)+id + status(1B) + count(4B)` + count×(`ts_ms(8B)+value(8B double)`) — reads `myenergi_data` |
| `0x88` | SPOT_PRICE_STREAM | B→F | live spot price broadcast: `status(1B) + hour_start_ms(8B) + spot(8B double) + all_in(8B double)` (raw wholesale + VAT/margin all-in €/kWh; both NaN when status 0) |
| `0x90` | CONFIG_GET_SCHEMA | F→B | (empty) — request the editable-settings schema + values |
| `0x91` | CONFIG_SCHEMA | B→F | `status(1B) + len(4B) + UTF-8 JSON` — `{"path":<config path>,"startedAt":<epoch-ms of this backend process>,"groups":[{id,label,icon,sections:[{id,label,status?,settings:[…]}]}]}` |
| `0x92` | CONFIG_SET | F→B | `len(4B) + UTF-8 JSON` — `{"key": <dotted>, "value": <json>}` |
| `0x93` | CONFIG_SET_RESULT | B→F | `status(1B) + len(4B) + UTF-8 JSON` — `{key, value, applied, message}` |
| `0x94` | CONFIG_RESTART | F→B | (empty) — exit with code 42 so the service manager restarts |
| `0xA0` | SPOTIFY_AUTH_STATUS | B→F | `status(1B) + len(4B) + JSON` — `{authorized, needsReauth, scope, expiresAt, redirectUri, cachePath, reason}`; snapshot on connect, broadcast after an exchange **and the moment the player is refused**. `needsReauth` = a new authorization is the fix (expired / revoked / never stored / scope short) — NOT merely `!authorized`, since an unreadable config is unauthorized too and re-authorizing would not help it |
| `0xA1` | SPOTIFY_AUTH_GET_URL | F→B | (empty) — start a flow, replacing any pending one |
| `0xA2` | SPOTIFY_AUTH_URL | B→F | `status(1B) + len(4B) + JSON` — `{url, redirectUri, state}` on OK (informational only; the backend has already opened the page), or `{message}` on error |
| `0xA3` | *(retired)* | — | Carried the redirect URL back from the embedded WebView. The consent page now opens in the host's real browser and the backend catches the redirect on its own loopback listener, so nothing produces one |
| `0xA4` | SPOTIFY_AUTH_RESULT | B→F | `status(1B) + len(4B) + JSON` — `{ok, message, scope, expiresAt}` |
| `0xB0` | SYSTEM_GET_STATUS | F→B | (empty) — sample the host now |
| `0xB1` | SYSTEM_STATUS | B→F | `status(1B) + len(4B) + JSON` — host/backend metrics, per-service health, error tallies |
| `0xC0` | DISPLAY_SET_POWER | F→B | `on(1B)` — 1 wakes the panel, 0 powers it down |
| `0xC1` | DISPLAY_POWER_STATE | B→F | `available(1B) + on(1B)`; `available=0` = no wlopm on the host |

(Trip codes `0x74`–`0x7D` — the Trips view — are omitted from this table; they mirror the History
request/response shape. See the `frontend_v2` memory.)

The `0x70`–`0x73` pair is **request/response** (the History view): the backend replies to the
requesting client only (`send_to`), never a broadcast, and `TESLA_HISTORY` echoes the requested id so
a stale reply can be discarded. History values are returned **raw** (no downsampling); the frontend
renders them as a **step line** (`StepLeft`) so a value held between records still displays as held.
(`read_tesla_data_property` keeps an optional `aggregate_window` for capping very large ranges,
currently unused.) When a window logged **nothing** (the value stayed constant, so no record falls
inside it), the backend **boundary-fills**: it queries the last value before the window start and
returns two synthetic points (window-start + window-end at that held value) so the graph draws a
flat held line across the whole range instead of "no data". Only a genuinely absent prior value
(or an InfluxDB outage, where the boundary query also yields nothing) replies `status=0`.

**Config protocol (`0x90`–`0x94`)** — the Options view. Request/response like History/Trips
(the backend replies to the requesting client via `send_to`), with one exception: a successful
`CONFIG_SET` *also broadcasts* a fresh `CONFIG_SCHEMA` so a second frontend refreshes its
displayed values. Bodies are `len(4B) + UTF-8 JSON` (the `CHARGER_RAW_JSON` idiom) rather than
a packed layout — the schema is variable-shaped and these packets are rare. Keys are dotted
paths into `config.json` (`myenergi.pollIntervalIdleSeconds`). `CONFIG_SET_RESULT.applied` is
`hook` (a service re-snapshotted), `restart` (written but only live after a restart) or
`unchanged` (the value already matched, so nothing was written or broadcast).

**Tesla stream value types**: `0` float `double(8B)`; `1` string `length(2B)+UTF-8`;
`2` bool `uint8(1B)`; `3` dict — sequence of `double(8B)` (Location = lat, lon).

**Weather sub-IDs**: `0x31` temperature `int8` °C; `0x32` wind `uint8` m/s;
`0x33` precipitation `uint8` mm; `0x34` cloud cover `uint8` %; `0x35` hour `uint8`.

**Charger (myenergi) protocol** — the Charging view. `CHARGER_STREAM` (`0x50`) is a **broadcast** of
the Zappi's live state, a weather-style sequence of `sub_id(1B) + value` pairs: `0x51` status `uint8`,
`0x52` plug `uint8`, `0x53` mode `uint8`, `0x54` charge power `float64` W, `0x55` session energy
`float64` kWh, `0x56` supply voltage `uint16` V, `0x57` grid power `float64` W (+import/−export),
`0x58` generated power `float64` W, `0x59` frequency `float64` Hz, `0x5A` L1 phase `uint8`, and
`0x5F` the full raw pymyenergi payload as `len(4B)+UTF-8 JSON` (every field, most unused — the one
length-prefixed sub-id, so an unknown fixed-width sub-id can't be skipped and stops the parse). The
`0x80`–`0x87` codes are **request/response** (reply to the requesting client only), served by
`charging_service` from stored telemetry + `myenergi_data`; `0x88` (`SPOT_PRICE_STREAM`) is a
**broadcast** of the live hourly spot price (see §5.2.7). `CHARGING_MONTH`'s 13 doubles, in order:
charger_kwh, car_kwh, wasted_kwh, efficiency_pct, car_wh_per_km, charger_wh_per_km, driving_kwh,
km_month, session_count, total_charge_s, charging_cost_eur, home_grid_kwh, home_cost_eur (any → NaN → "—").
Both cost fields are now **spot-priced per hour** (flat-tariff fallback) — see §5.2.7.

**Adding a telemetry field** — update these in sync:
1. `config.json` `tesla data` — new entry with a unique `stream_id`.
2. `frontend/src/tesla/vehicle.cpp` — `properties[...]` with matching `data_stream_id` + `value_type`.
3. `frontend/src/tesla/datahandler/tesladatahandler.{hh,cpp}` — a signal in the `.hh` and a row in
   the `kRoutes` table (which both `processStreamData` and the `connectToDataUpdateSignal` overloads walk).
   `vehicle_data_property.py` needs no change unless a new value type is introduced.

**Adding a command (F→B)**:
1. Add the type constant in `utils/protocol.py`.
2. In `start_services._register_handlers`, `server.register_handler(protocol.<NAME>, <async callable>)`.
   The callable gets `(payload, writer)` — the raw payload (no length prefix / type byte) and the
   requesting client's `StreamWriter`. Fire-and-forget commands ignore the writer; request/response
   handlers reply to just that client via `server.send_to(writer, …)`. The server routes by integer only.
3. In the frontend, build + send the packet via `QDataStream` (see `TeslaDataHandler::switchClimateState`).

### 5.2 Backend services

The backend is entirely asyncio. `start_services.main()` constructs every service,
calls `_register_handlers` and `register_service` on the `Server`, runs
`vehicle.init_async_dependent()`, then **`asyncio.gather`s the run tasks**: telemetry, the TCP
server, `MediaManager.get_run_task()`, `WeatherService.get_run_task()`,
`ConfigService.get_run_task()` (the restart watch), and — when charger credentials are set —
`MyEnergiService.get_run_task()`. (`trip_service` / `charging_service` are stateless
request/response and have no run task.)

> **Orchestration note.** The media and weather `run()` coroutines schedule APScheduler jobs
> and then *return* — their ongoing work lives in those jobs, and APScheduler logs+swallows
> per-job exceptions, so polling is self-healing per tick. Telemetry and the server run
> forever. There is **no in-process supervisor**: an unhandled failure in either propagates
> out of `gather` and ends the process. Resilience is delegated to **systemd
> `Restart=on-failure`** in deployment (see README). Don't add a restart loop without a reason.

#### 5.2.1 `server/server.py` — the TCP server
`Server` owns the active-connection map and a `msg_type → handler` registry. Handlers are invoked
as `handler(payload, writer)` — the writer lets request/response handlers reply to just the
requesting client via `send_to`; passing it keeps the server protocol-agnostic (it still only moves
bytes + the connection). `broadcast` sends a pre-framed packet to all clients in parallel (one task
per client, gathered with `return_exceptions=True`); `send_to` targets one client.
`__handle_connection` runs the on-connect **snapshot** (each registered service's
`stream_everything(writer)`), then the read loop. **Communicates with:** every service, but only as
a dumb byte pipe — it never imports protocol constants or calls concrete service methods.

> **Load-bearing invariants — do not break:**
> - **No recv/inactivity timeout.** The frontend only sends on user interaction; idle is
>   normal. Never wrap `__recv_message()` in `asyncio.wait_for`. Dead peers surface as
>   `IncompleteReadError`/`ConnectionError`; use TCP keepalive if you must detect them.
> - **Broadcast never blocks on one slow client** — keep the per-client task fan-out.
> - **Snapshot `__active_connections` keys before iterating** (`list(...)`) — concurrent
>   disconnects pop entries.
> - **Enforce `MAX_MSG_SIZE`** (1 MB) in `__recv_message()`.
> - **Server stays protocol-agnostic** — route via `register_handler`, snapshot via
>   `register_service` (duck-typed `stream_everything`). No `if msg_type == ...` in the server.

#### 5.2.2 `tesla_service/` — telemetry & vehicle
- **`telemetry.py`** (`TelemetryHandler`) wraps `teslemetry_stream.TeslemetryStream`, registers
  `vehicle.on_telemetry_event` as the listener, and blocks on a close event. Reconnection is the
  library's job (exponential backoff). **Talks to:** Teslemetry stream → `Vehicle`.
- **`vehicle.py`** (`Vehicle`) loads a `VehicleDataProperty` per `config.json` field.
  `init_async_dependent` starts the APScheduler, builds the `CalculatedVehicleDataProperty`s and
  their period-reset jobs, and registers the **midnight snapshot** job (writes every logged
  property at 00:00 so first-of-day/month baseline queries always find a record).
  `on_telemetry_event → __update` applies formulas, broadcasts changed fields
  (`protocol.frame(MSG_STREAM, …)`), and writes logged fields to InfluxDB (a failed write never
  blocks the broadcast). Non-data **state** events carry `online`/`offline`/`asleep` (the car
  reports a sleeping vehicle as `offline`, never `asleep`); `__update` writes the synthesized
  `VehicleOnline` and nothing more. **Value-callbacks** (`add_callback`/`remove_callback`) drive
  the rest: `add_callback(criteria, cb)` fires `cb(matches)` when every property in `criteria`
  (`{id: target_value}`) simultaneously holds its target (edge-triggered, built on the per-property
  callbacks; `matches` is a list of `(id, value, when)`). The **sleep reset** is registered this
  way in `__init__` — `add_callback({"VehicleOnline": False}, __on_sleep)`; when the car goes
  offline `__on_sleep` runs `__apply_sleep_defaults`, forcing every field with a configured
  `sleep_default` to it and broadcasting only the ones that changed (never written to InfluxDB).
  Edge-triggered, so it fires once per online→offline transition (lock ordering still lands it
  after the reconnect burst).
  HVAC: `switch_climate_state` toggles via the Teslemetry REST API behind
  an in-memory **rate limiter** (reserve/refund/reset) and a **value lock** that pins the UI to
  `HvacPowerStatePending` until the confirming telemetry arrives; `plus_temp`/`minus_temp` adjust
  the local target and stream it (the **target temperature is a pre-conditioning setpoint** — it
  is pushed to the car via `update_temperature` only when climate is next toggled, by design).
  `stream_everything` snapshots all properties to a new client. History: `get_graphable_properties`
  lists the logged numeric (value_float) properties for the History view's dropdown; `get_data_history`
  reads one property's history and `get_value_before` reads the held value just before a window (the
  empty-window boundary-fill) — all served by request/response handlers that reply
  to the requesting client only. **Talks to:** `InfluxDBHandler`
  (write/read), `Server` (broadcast/send_to), Teslemetry REST (aiohttp).
- **`vehicle_data_property.py`**: `VehicleDataProperty` stores one field's value/timestamp,
  evaluates its sympy `formula`, serializes to the wire format (`get_stream_data`), builds Influx
  points, supports `lock_value_until` (the pending-state lock), `apply_sleep_default`
  (force-reset to the field's configured asleep value, bypassing the formula and clearing any
  active value-lock — a pending HVAC toggle can never confirm while asleep), and
  `add_callback(target_value, cb)`/`remove_callback(handle)` — edge-triggered value-callbacks run
  as independent tasks as `cb(data_id, value, when)` when the value transitions into `target_value`
  (`when` is a tz-aware datetime), or on every value change if `target_value` is the
  `VehicleDataProperty.ANY` sentinel; `Vehicle.add_callback` builds its combination callbacks on these.
  `CalculatedVehicleDataProperty`
  derives `calculation_formula(x=baseline, y=latest)`; the baseline is read from InfluxDB at period
  start (falls back to the live value), reset by an APScheduler cron job. **Talks to:** `Vehicle`
  (which owns Influx access).

#### 5.2.3 `media_service/` — media manager & players
- **`media_manager.py`** (`MediaManager`) constructs both players, holds the **active** one, and
  routes controls to it. `claim_media_control` (Spotify took over) stops radio, switches active,
  starts playback, streams media type + full state; `release_playback`/`load_default_media_player`
  return to radio without auto-play. `stream_data` drops packets from the non-active player.
  `get_run_task` starts Spotify polling then loads radio. **Talks to:** both players, `Server`.
- **`base_media_player.py`**: the abstract control/stream interface both players implement.
- **`spotify_player.py`** (`SpotifyPlayer`) polls the Spotify Web API via spotipy on an APScheduler
  interval (10 s idle / 2 s active). `_update_state` is **serialised by `self._state_lock`**: it
  runs both on the timer and inline after every control command, and `claim_media_control` re-enters
  it via `play()`, so the guard (`if self._state_lock.locked(): return`) prevents both a deadlock and
  double claim/release. On detecting playback on `spotifyDeviceId` it claims control and streams
  name/artists/duration/image/progress/play-state; controls call `start/pause/next/previous/seek`.
  **Talks to:** Spotify Web API (run in an executor), `MediaManager`. *(If `spotifyDeviceId` is
  wrong, controls silently no-op — the `_current_device_id` vs `_target_device_id` comparison drives
  claim/release.)*
- **`radio_player.py`** (`RadioPlayer`) plays Nelonen Media HLS streams through libVLC, fetching the
  stream + art URL per station, cycling stations on skip, and restarting on VLC error/end events
  (guarded by `__intentional_stop`). **Talks to:** Nelonen API (aiohttp), libVLC, `MediaManager`.
- **`setup/spotify_setup.py`**: a one-off helper (run during setup) that completes the OAuth
  handshake and prints the active Connect device id for `config.json`. Not part of the runtime.

#### 5.2.4 `weather_service/weather_service.py`
`WeatherService` fetches the current-hour FMI observation + the next hours' harmonie forecast
(`fmiopendata`, run in an executor), serialises them into a `WEATHER_FORECAST` frame, broadcasts,
and caches the last frame to replay to new clients. Refreshes every 15 min via APScheduler.
The current-hour **banner** takes temperature + wind from the real observation, but the observation
station typically reports neither precipitation nor cloud cover — so those two are **backfilled from
the harmonie forecast's current-hour row** (the model retains the current hour, so no caching is
needed). `__fetch_observation` walks observation slots newest→oldest and uses the most recent one
with a valid air-temperature reading (avoiding the all-NaN padding slots fmiopendata returns).
**Talks to:** FMI open data, `Server`.

> **Load-bearing invariants — do not break:**
> - **Never call `fmiopendata.wfs.download_stored_query`.** Its fetch helper is `requests.get(url)`
>   with **no timeout** and no way to pass one. A stalled FMI response (connection accepted, partial
>   body, then silence — no FIN/RST) parks the caller in `read()` *forever*; in production that burned
>   an executor thread and killed weather for 16 days. `__download_stored_query` +
>   `__fetch_and_parse` replace it: the same URL (`STORED_QUERY_URL + query_id`, args as aiohttp
>   `params` so non-ASCII places like `Ryttylä` percent-encode) fetched with an explicit
>   `_FMI_TIMEOUT`, then handed to fmiopendata's own `MultiPoint` parser in an executor. Any failure
>   logs a WARNING and returns `None`. An `asyncio.wait_for(_FETCH_DEADLINE_SECONDS)` wraps both.
> - **Keep `max_instances` ≥ 2 + a real `misfire_grace_time` on the refresh job.** APScheduler's
>   default `max_instances=1` turns one wedged run into a permanent outage — every later tick is
>   refused with *"skipped: maximum number of running instances reached (1)"*.
> - **Schedule the job before the initial fetch** in `run()`, so a failed/slow first fetch can't
>   leave the service with no periodic refresh at all.
> - **A cycle with no future forecast hours is a failed cycle** — return without broadcasting or
>   caching. The frontend replaces its whole forecast model per frame, so a banner-only frame blanks
>   all five cards *and* poisons `__last_forecast` for every later reconnect. Stale-but-complete
>   beats half-blank.

#### 5.2.5 `influxdb_service/influxdb_handler.py`
`InfluxDBHandler` wraps the async InfluxDB client: `write_tesla_data` (logged fields + midnight
snapshot), `read_first_value_day`/`_month` (calculated-field baselines), `read_tesla_data_property`
(history — the History path serves it **raw**; an optional `aggregate_window` arg can add
`aggregateWindow(fn: mean) + fill(usePrevious)` to downsample + forward-fill onto a regular grid,
dropping the leading null windows, but is currently unused), and `read_last_value_before` (a
`last()` query bounded by `stop` — the held value before an empty window, used to boundary-fill the
History graph with a flat line). For the myenergi charger it adds `write_charger_data` (the
`myenergi_data` measurement), `read_charger_data_property` (raw charger history), and
`read_grid_import_kwh_hourly` (reuses the raw `GridPower` read + the module-level pure
`integrate_power_series_hourly` — a trapezoidal per-UTC-hour integral, export clamped to 0 → a
`{utc_hour_ms: kwh}` map; the month home-import total is `sum(...)` and the spot-cost path dots it
with hourly prices). Read failures degrade to `None` rather than crashing the app. **Talks to:** InfluxDB,
`Vehicle`. *Flux queries interpolate `data_property_id` via f-strings gated by the `_SAFE_ID` regex
`^[A-Za-z0-9_\-]+$`, and `aggregate_window` by `_SAFE_WINDOW` (`^[1-9][0-9]*[smhd]$`) — keep both
guards; they're the only thing preventing injection if non-config input ever reaches these paths.*

#### 5.2.6 `utils/`
- **`config_parser.py`**: `Config` validates + exposes `config.json`; `get_env` loads `.env` once.
- **`protocol.py`**: every message-type byte, weather sub-id, `MAX_MSG_SIZE`, and `frame()`. The
  single source of truth — add new constants here, never on a class.
- **`logger_configurator.py`**: `configure_logging(level=None)` resolves the level from
  `TESLA_HOMEDASH_LOG_LEVEL` (default **INFO**, not DEBUG) and wires the shared stdout formatter
  (`LEVEL | YYYY-MM-DD | HH:MM:SS | name | message`) onto an allow-list of top-level loggers.
  **Every service's logger prefix must be in `_SERVICE_LOGGERS`** (`tesla_service`, `media_service`,
  `weather_service`, `influxdb_service`, `charging_service`, `myenergi_service`, `trip_service`,
  `config_service`, `audio_service`, `display_service`, `system_service`, `server`,
  `start_services`, `utils`) — an unlisted prefix propagates to a handler-less root and its
  INFO/DEBUG logs silently vanish. **`spotipy` gets the same handlers but a PINNED level**
  (`max(level, INFO)`): its "Couldn't write token to cache" warning is the only evidence that a
  re-authorisation silently lost the grant, but at DEBUG it prints the token POST body and the
  base64 `Authorization` header carrying `SPOTIFY_CLIENT_ID:SPOTIFY_CLIENT_SECRET`, the
  authorization code and the refresh token. Never add it to the tuple itself.

#### 5.2.7 `myenergi_service/` + `charging_service/` — charger + charging stats
- **`myenergi_service.py`** (`MyEnergiService`) polls a myenergi Zappi via `pymyenergi` (cloud
  digest auth), broadcasts its live state as `CHARGER_STREAM`, and logs to the `myenergi_data`
  measurement: `GridPower` + `ChargePower` **every poll** (gap-free for the past-hour graphs and the
  month home-import integral) and `ChargeAdded` (the session accumulator) **while charging**. Mirrors
  `WeatherService` (initial poll + APScheduler job, last frame cached for `stream_everything`), with
  two poll cadences (idle/active, config-driven — default **60 s idle / 20 s active** to stay under
  the myenergi cloud's rate limit; 10 s throttled us with 429s). `__apply_interval` is the single
  place that reschedules the job: it picks the active/idle base then stretches it by a **capped
  exponential backoff** (`2**consecutive_failures`, ≤ 5 min) whenever a poll fails, snapping back on
  the first success. This matters because every failed request flips pymyenergi's `do_query_asn` back
  on, so the next poll fires two requests (director + status) — polling a failing endpoint at full
  cadence deepens a throttle. Refresh/resolve failures are logged via the module helper
  `_describe_exception`, which surfaces the HTTP status a `MyenergiException` otherwise hides (its
  ctor stores it in `.code`/`.message` but stringifies to `""`, so the old `str(e)` logged a blank
  reason — issue #18). Optional — skipped when the `.env` creds are unset.
- **`charging_service/`** (`ChargingLoader` + `ChargingSession`) derives charging sessions **on
  demand** from stored `DetailedChargeState` history (segmentation like `trip_service`), joined to
  the logged charger energy — no live tracking. Serves `CHARGING_GET_LIST`/`_SUMMARY`/`_MONTH` +
  `CHARGER_GET_HISTORY`. **Per-session charger energy = the SUM OF POSITIVE `ChargeAdded` increments
  in the window** (NOT the in-window max: the myenergi accumulator can carry a value in from charging
  that predates the Tesla-detected session, so a max double-counts — this was a real bug). `month_summary`
  sums the sessions' charger/battery energy + the tesla month-counter deltas (`LifetimeEnergyUsed`,
  `Odometer`) for consumption/km. **Talks to:** `InfluxDBHandler`, `Server`.
- **Spot pricing (issue #12).** **`spot_price.py`** (`SpotPriceProvider`) fetches Nord Pool FI hourly
  spot prices from the no-key **sähkötin.fi** range endpoint (`?start&end`, raw €/MWh, UTC hours),
  converts to an all-in `(spot + margin) × (1 + VAT)` €/kWh, and caches immutable past hours — so a
  session from days ago is priced retroactively **without self-logging prices**. The module also holds
  the pure pricing helper `price_hourly_energy` (dot energy-by-hour with price, flat-tariff fallback).
  Cost now lives in the **loader/session** (not the month handler): `ChargingSession.summary()` buckets
  its `ChargeAdded` increments by UTC hour (`bucket_positive_increments_by_hour`) and prices each →
  `cost_eur`/`avg_price_eur_per_kwh`; `month_summary` sums session costs (`charging_cost_eur`) and
  prices the hourly home import (`home_cost_eur`), each falling back per-hour to the flat
  `electricityPriceEurPerKwh` tariff (→ NaN → "—" when neither is available). **`spot_price_service.py`**
  (`SpotPriceService`) is a thin always-on `WeatherService`-style broadcaster: it re-broadcasts the
  current hour's price as `SPOT_PRICE_STREAM` (`0x88`) hourly + snapshots it on connect. Always
  constructed (works with no Zappi); `run()` no-ops when `spotPrice.enabled` is false. **Talks to:**
  sähkötin.fi (aiohttp), `InfluxDBHandler`, `Server`.

#### 5.2.8a `audio_service/` — host audio (issue #37)
`audio_backend.py` holds one abstract `AudioBackend` plus four implementations, and
`detect_backend()` probes the host in the order **`pactl` → `wpctl` → `amixer`**, falling back to
`NullAudioBackend`. `pactl` goes first because it covers real PulseAudio *and* pipewire-pulse with
one adapter **and addresses sinks by a stable name** — `wpctl set-default` takes only a
session-scoped numeric id, so that path resolves the stored `node.name` against `pw-dump` on every
write. Bookworm ships PipeWire + WirePlumber + pipewire-pulse, but `pipewire-pulse` only *suggests*
`pulseaudio-utils`, so `pactl` is not guaranteed and `wpctl` is the always-present fallback.
Enumeration on that path uses `pw-dump`'s JSON, never `wpctl status`'s box-drawing tree.
`AudioService` applies `audio.volumePercent` / `audio.outputDevice` and refreshes the device list
every 15 s (HDMI and Bluetooth hotplug). Load-bearing details:
- **Device first, volume second, always.** A sink carries its *own* volume, so switching output
  without re-applying the volume makes the user's setting silently stop holding.
- **`wpctl` does not clamp** — `set-volume 150%` is accepted and overdrives the sink — and
  **`wpctl get-volume` exits 0 even for a missing node**, so the `Volume: ` prefix is the test, not rc.
- The feature needed **no protocol code and no frontend change**: two `config.json` keys, one hook,
  one schema subsection. Two generic additions to `ConfigService` carry it — `register_options(key,
  provider)` (a service owns its own dynamic enum) and `register_guard(name, guard)` (a pre-write
  veto that, unlike a hook, runs *before* anything is persisted and can honestly reject
  "this host cannot do that").

#### 5.2.8b `display_service/` — panel power (issue #35)
Runs `wlopm --on/--off <output>` (`*` = every output). The **frontend decides when** (it is the only
side that sees touch input) and **this side does the switching**, because system calls belong to the
backend. Reports `available=0` when wlopm is absent so the dashboard never arms a timeout that could
do nothing, and `run()` powers the panel on at startup so a backend restart cannot leave it dark.
Needs the compositor socket: `XDG_RUNTIME_DIR` is already in a `systemd --user` unit's environment,
`WAYLAND_DISPLAY` is not (the unit is wanted by `default.target`), so the README's unit sets it.

#### 5.2.8c `system_service/` — the maintenance dashboard (issue #39)
`system_metrics.py` is pure stdlib against `/proc` (no psutil: nothing here is worth an ARM build and
a pin). `SystemStatusService` serves `SYSTEM_GET_STATUS` — **request/response, not a broadcast, and
deliberately NOT `register_service`d**: the Options view is open a fraction of the time, and sampling
`/proc` for every client to feed a screen nobody is looking at is pure waste. Details that matter:
- `/proc/net/dev` is parsed with `partition(":")`, not `split()` — a counter wide enough to touch the
  colon prints `eth0:1234567890` and shifts every column by one.
- CPU is a **delta**, so a sample older than 30 s is discarded and a fresh 250 ms window taken; a
  half-hour-old sample would report the average over that half hour.
- Per-service health is duck-typed **`health()`**, the same pattern as `stream_everything()` and
  `apply_config()`, so each service answers from state it already keeps. A probe that raises or hangs
  is reported as one broken service, never as a failed request.
- Error tallies come from **`ErrorCounter`**, a `logging.Handler` attached to the same
  `_SERVICE_LOGGERS` allow-list as the stdout handler (those loggers set `propagate = False`, which
  is what rules out double counting).

#### 5.2.8d `media_service/spotify_auth_service.py` — re-authorisation (issue #38)
Serves `0xA0`–`0xA4` so the OAuth grant can be refreshed from the dashboard instead of by SSHing in
to run `setup/spotify_setup.py`. **Only the authorization code crosses the wire** — single-use,
~10-minute, and worthless without `SPOTIFY_CLIENT_SECRET`, which never leaves the backend. The
exchange passes `check_cache=False` (with the default `True` a stale-but-valid cache short-circuits
and the new code is never redeemed) and runs in an executor, since spotipy is blocking `requests`.

> **The consent page is opened in the HOST'S REAL BROWSER. There is no embedded
> browser any more — Qt WebEngine was removed from the project entirely.** `handle_get_url`
> stands up a one-shot `asyncio.start_server` on the redirect URI's own host/port
> (`127.0.0.1:8080`), launches the page with `xdg-open`, and catches Spotify's redirect itself —
> so nothing is pasted by hand and the authorization code never leaves loopback. This is RFC 8252
> §7.3 (Loopback Interface Redirection), and it is also why the redirect URI is allowed to be plain
> HTTP. The reason it is not embedded is RFC 8252 §8.12: native apps **MUST NOT** use an embedded
> user-agent for authorization — an embedded view can read the user's password keystrokes and lift
> session cookies, which is exactly why providers block it. Measured: with WebGL and rendering both
> fixed, the embedded `WebEngineView` still could not get past the login gate.
>
> **This does NOT reintroduce the `NonInteractiveSpotifyOAuth` hazard below.** That one is spotipy's
> loopback server blocking a worker thread forever on `handle_request()`. This is an asyncio server
> on the main loop, bound to loopback only, torn down on the first hit or at `_FLOW_TTL_SECONDS` by
> `__cancel_pending()` (which awaits `wait_closed()`, so a retry can rebind the port).
>
> **Two traps in the listener, both found the hard way, both silent:**
> - **A browser opens more than one connection to that port** — a speculative preconnect, and a
>   `/favicon.ico` fetch the moment the response page renders. Neither carries the redirect's
>   parameters. Treating "no code" as fatal cancelled the flow *while the real exchange was still
>   in flight*, so the dashboard reported a failure for an authorization that had already succeeded
>   and written its token. Only a request actually carrying `code` or `error` may decide anything;
>   everything else gets a `204` and is ignored. `pending["claimed"]` makes the first code win, so a
>   reload of the redirect URL cannot re-enter the exchange with a spent code.
> - **Never `await Server.wait_closed()` from inside the callback handler.** Since CPython 3.12.1 it
>   waits for every active connection to drop too — and the handler IS one of those connections, so
>   it deadlocks there. The exchange completes and the token lands on disk, but the success reply
>   never reaches the frontend. `close()` alone releases the listening socket, which is all a retry
>   needs.
>
> There is no fallback left to degrade to, so **either half failing is a hard error** replied as
> `SPOTIFY_AUTH_URL` + `SPOTIFY_AUTH_ERROR`: without a listener the code cannot be caught, without a
> browser the page cannot be reached, and a dialog waiting forever for a redirect nobody can produce
> is worse than a message. The target supports this natively — README §Pi notes the dashboard runs *on top of* the full
> Raspberry Pi OS desktop, not as a kiosk, and the pre-existing `spotify_setup.py` already told the
> user to run it "from the Pi's desktop (it needs to open a browser window)".
>
> **The grant EXPIRES — 6 months, absolute.** Verified against
> `developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens`: *"Refresh tokens issued
> to apps registered in the Developer Dashboard have a lifetime of 6 months … Refreshing an access
> token does not extend the refresh token's lifetime."* Announced 2026-06-18, enforced for existing
> apps **2026-07-20**, and it covers the authorization-code flow this app uses (PKCE or not). So
> re-authorization is not an incident-recovery tool — it is **routine maintenance roughly twice a
> year**, and the reason the Options view's card carries that warning in its `help`.
>
> Do not confuse the two expiries. The cache's `expires_in`/`expires_at` is the **access** token's
> ~1 hour, refreshed silently by spotipy before every request; the status packet's `expiresAt`
> carries that value and **must never be rendered as "authorization valid until"** — it would imply
> the grant dies within the hour while hiding the only expiry the user ever needs. Spotify does not
> expose the grant's issue date, so a real "valid until" would mean recording our own timestamp at
> each successful exchange.
>
> When it does expire the token endpoint returns **HTTP 400 `{"error": "invalid_grant"}`**, raised by
> spotipy as `SpotifyOauthError`. `SpotifyPlayer._call_spotify` catches that **before** the
> `SpotifyBaseException` arm it is a subclass of — only there can "the grant is gone" be told apart
> from "the API said no" — and `_note_auth_failure` latches the player off:
> - **Only terminal codes latch** (`invalid_grant`, `invalid_client`, `unauthorized_client`,
>   `invalid_scope`, plus `NonInteractiveSpotifyOAuth`'s message-only "No usable Spotify token
>   cache"). A 5xx from the token endpoint or a network blip is logged and ignored, or one bad
>   minute at Spotify would silence the dashboard until someone restarted it.
> - **While latched, `_call_spotify` and `_update_state` return before touching the network.**
>   spotipy does not clear its cache on rejection, so without this the poller retries a dead token
>   every 10 s forever, for nothing. `refresh_auth()` clears the latch and resumes.
> - `_auth_listener` (wired in `start_services` to `SpotifyAuthService.notify_auth_state_changed`)
>   re-broadcasts the status the instant the verdict changes, so the dashboard's prompt appears then
>   rather than at the next reconnect.
>
> **`build_status()` asks the player first.** A cached refresh token Spotify has stopped accepting
> still sits happily on disk, so cache presence proves nothing; only the player has actually tried
> to use it. Its verdict overrides, and sets `needsReauth`.
>
> **The gate on Spotify's login page is Google reCAPTCHA Enterprise, not Cloudflare.** Measured:
> `accounts.spotify.com` answers `server: envoy` with no `cf-*` header, and its CSP whitelists
> `google.com/recaptcha`. `challenge-orchestrator /v1/invoke-challenge-command` is Spotify's own
> wrapper around it. This matters because it scores the *execution environment* — a Chromium with
> no WebGL context cannot produce a solvable challenge, which is how the whole flow dead-ended on
> a WSL2 dev box (see §7.7). Earlier comments in this repo blamed Cloudflare; they were wrong.

`spotify_oauth.py` holds the **one canonical `SPOTIFY_SCOPE`** and `NonInteractiveSpotifyOAuth`.
Both are fixes for real hazards found while building this:
- The scope literal was **duplicated** between the player and the setup helper. spotipy stamps the
  *issuing* manager's scope onto the cached token and then refuses the cache unless the *reading*
  manager's scope is a subset, so a re-auth issued with a narrower scope silently kills playback with
  no error anywhere.
- Stock `SpotifyOAuth` falls back to an **interactive** handshake when the cache is unusable: for a
  `127.0.0.1` redirect it starts a local HTTP server and blocks forever *inside the player's executor
  thread*, after which APScheduler refuses every later poll. Exactly the failure shape §5.2.4 records
  for the weather service. The subclass raises instead, turning a silent hang into a logged error.
- **A successful exchange could leave nothing on disk and still report success.** spotipy's
  `CacheFileHandler` swallows every `OSError` from the token write and **never creates parent
  directories**, so a `spotifyCachePath` whose directory is missing loses the grant silently: a tick
  in the Options view, `authorized=false` in the status broadcast a line later, and the single-use
  code already spent. `build_oauth` now `makedirs` the parent (warn-only — it runs on every client
  connect via `build_status()`, so it must never crash a status read), and `handle_code` **verifies
  the cache afterwards** rather than assuming, replying with the path when it is empty.
- **The CSRF state check was a no-op.** The frontend round-tripped the backend's own nonce and the
  backend compared it with itself, because spotipy's `parse_response_code` discards the state
  Spotify echoes. `handle_code` now uses **`parse_auth_response_url`**, which returns `(state, code)`,
  and the comparison is **mandatory** — a missing state is a failed check, not a skipped one.

#### 5.2.8 `config_service/config_service.py` — runtime configuration (the Options view)
`ConfigService` serves `CONFIG_GET_SCHEMA` / `CONFIG_SET` / `CONFIG_RESTART` and snapshots the
schema to every new client (`register_service`). `SETTINGS_SCHEMA` is a literal list of groups
→ **subsections** → settings (issue #30), each group declaring `id` / `label` / `icon` and each
subsection `id` / `label` / optional `help`. **Group ids are shared with the frontend's own
bundled schema and a group present in both halves MERGES into one sidebar section** — which is
how `general` shows the frontend's screensaver card beside this file's location card. Every
setting declares `key` (dotted), `type` (`bool|int|float|string|enum`), Finnish
`label`/`help`, `unit`, numeric `min`/`max`/`step`, `nullable`, `options` (or the string
`"dynamic"`, resolved at schema-build time — `defaultRadioStation`'s choices are the configured
`radioMediaIds` keys), an optional `validator` name, and its **apply tier**. It is both the
write allow-list and the frontend's UI description, so adding a tunable is one entry here and
**no frontend change at all**.

> **Apply tiers — the load-bearing design point.** Every service snapshots the values it needs
> into instance attributes in its constructor and *never re-reads* `Config`, so mutating
> `Config` alone changes nothing at runtime. There is therefore no "live" tier:
> - **`hook`** — the owning service exposes **`apply_config()`**, which re-snapshots from
>   `Config` and does whatever else applying means (`MyEnergiService` reschedules through its
>   single `__apply_interval` point; `WeatherService` drops its cached frame and refetches).
>   Registered in `start_services` via `config_service.register_hook(name, svc.apply_config)`.
>   Implemented on: `WeatherService`, `MyEnergiService`, `TripLoader`, `ChargingLoader`,
>   `SpotPriceProvider`, and `MediaManager.apply_config_radio()` / `_spotify()` (which forward
>   to the two players). `SpotPriceProvider` needs no cache flush — it caches *raw* prices and
>   applies VAT/margin on read.
> - **`restart`** — the value builds something that cannot be rebuilt in place: `timeZone`
>   (APScheduler cron jobs), `myenergi.zappiSerial` (the Zappi resolved at connect),
>   `spotPrice.enabled` (whether `SpotPriceService` has a run task at all).
>
> A `hook` setting whose hooks are all **unregistered** (no Zappi → no `MyEnergiService`) is
> reported to the frontend as `restart`, because that is what it truly is for that deployment.

**Restart.** `CONFIG_RESTART` sets an `asyncio.Event`; `run()` awaits it, waits
`_RESTART_DRAIN_SECONDS` so the preceding reply flushes, then flushes the log handlers and
calls `os._exit(RESTART_EXIT_CODE)`. The code is **42 — deliberately non-zero**, so the
README's `Restart=on-failure` unit restarts it without needing `Restart=always`. `os._exit`
rather than `raise SystemExit`: asyncio does not store SystemExit on a task, it propagates it
through the runner's teardown and prints a full traceback plus *"Task exception was never
retrieved"* — misleading noise in the journal for an intentional restart.

**Safety.** Validation happens before any write (`_validate_timezone` is the important one —
an unresolvable zone makes `Config.__init__` raise, and since `timeZone` is restart-tier that
would be a restart *loop*). A failed `save()` rolls the in-memory value back so services and
disk never disagree. A hook that raises is logged and swallowed: the value is already saved,
so failing the write there would leave the reply and the disk disagreeing.
**Talks to:** `Config` (set/save), `Server` (send_to/broadcast), every hooked service.

### 5.3 Frontend

The Widgets frontend uses a signal/slot routing pattern: `ServerClient` emits one signal per
packet type → datahandlers deserialize → datahandlers emit per-field signals → widgets update.
`MainWindow` builds the 10×16 grid and wires widgets to their datahandlers and to the `ServerClient`.

#### 5.3.1 `server_client/serverclient.{hh,cpp}`
`QTcpSocket` client. `onReadyRead` reassembles framed packets out of the TCP byte stream
(4-byte length + 1-byte type + payload), **rejects implausible lengths** (16 MB cap, 64-bit-safe
size math) and demuxes each packet to a typed signal. Reconnects 10 s after disconnect/error.
Outbound control packets are written **non-blocking** — do not reintroduce
`flush()`/`waitForBytesWritten(...)` (it caused visible click latency; control packets are ≤6 bytes).

#### 5.3.2 `tesla/` — telemetry widgets + datahandler
- **`vehicle.{hh,cpp}`**: the `TeslaDataProperty` registry (`data_id` → `data_stream_id`, `unit`,
  `value_type`). Mirrors `config.json`.
- **`datahandler/tesladatahandler.{hh,cpp}`**: the **table-driven** core. `kRoutes` maps each
  `data_id` to its value type and Qt signal; `processStreamData` deserializes a `MSG_STREAM` packet
  (bounds-checking string payloads) and emits the matching signal; the two `connectToDataUpdateSignal`
  overloads wire widgets to signals by walking the same table. It also builds the outbound HVAC
  command packets. **A signal in the `.hh` with no `kRoutes` row (or vice versa) silently breaks that
  field** — keep them in sync with `vehicle.cpp` and `config.json`.
- **Widgets**: `tesladatawidget` (abstract `TeslaDataWidget` / `TeslaDataMultiWidget` bases);
  `singletesladataentry` + `dataentrylist` (the two stat lists); `map/teslamap` + `map.qml` (a
  `QQuickView` OSM map in a window container, driven by Location + GpsHeading — note: **never apply a
  `QGraphicsEffect` to the map**, it forces the whole QML scene through the software rasteriser);
  `climate/` (`climatecontrollercard` container + `temperaturecard`, `teslaclimatestarter` with
  on/off/pending glow, `teslaseatwidget`, `teslasteeringwidget` — per-state SVG pixmaps are rendered
  once at construction, the per-update path is just `setPixmap`).

#### 5.3.3 `mediaplayer/` — media widgets + datahandler
- **`datahandler/mediaplayerdatahandler.{hh,cpp}`**: parses media packets and builds outbound
  transport commands. Cover-art packets are deduped by content hash and **decoded to a `QImage` on a
  worker thread** (never a `QPixmap` — `QPixmap` is GUI-thread-only); an in-flight decode is dropped
  when a newer packet arrives.
- **`widgets/mediaplayercard.{hh,cpp}`**: converts the decoded `QImage` to a `QPixmap` **on the GUI
  thread**, then runs the **k-means dominant-colour** extraction on a worker (operating on the
  `QImage`). The k-means algorithm, hue/value gating and RNG seed (`69420`) define the dashboard's
  visual identity — move execution context freely but **do not change the inputs or scoring**. The
  gradient background is cached as a `QPixmap` (`m_background_dirty` invalidates it on resize / colour
  change). The "spotifyplayer" object name is kept for `mediaplayercard.qss` selector compatibility.

#### 5.3.4 `weather/` — weather widgets + datahandler
- **`datahandler/weatherdatahandler.{hh,cpp}`**: parses the repeated-sub-id `WEATHER_FORECAST` frame
  (bounds-checked) into vectors and emits one update.
- **`widgets/`**: `mainweather` (container; fans the update out to the banner + 5 cards by id),
  `currentweathercard` (current-hour banner, consumes the sentinel id), `weatherforecastcard`
  (one forecast hour ×5, each ignoring ids that aren't its own).

#### 5.3.5 `config/appconfig` + `utils/logger`
- **`AppConfig`** is the **only** place to read frontend env vars; `main.cpp` calls `AppConfig::load()`
  once before building `MainWindow`. Reading env elsewhere is a smell — extend `AppConfig` instead.
- **`Logger`** mirrors the backend format to stdout. Never call `qInfo/qWarning/qDebug/qCritical`
  directly — `Logger::install()` funnels Qt's own messages through the same formatter under the source
  `qt`. Worker-thread logs are serialised by a static mutex. Source names today: `app`, `config`,
  `server_client`, `tesla.data`, `media.data`, `media.card`, `weather.data`, `settings`, `qt`.
  `main.cpp` also sets a global `QLabel, QPushButton { color: #FFFFFF }` default so text stays white on
  platforms (e.g. Raspberry Pi OS) whose default palette renders near-black on the dark background;
  per-widget QSS still overrides it.

#### 5.3.6 `frontend_v2` settings (the Options view) — `core/settings.{hh,cpp}`
> Applies to **`frontend_v2`** (the active QML frontend), not the frozen Widgets `frontend/`.

`Settings` is one QML singleton (`Settings`) fronting **both** halves of the Options view:

- **Local settings** — schema from the bundled `:/config/settings.json`, user overrides
  persisted with `QSaveFile` (atomic; the Pi loses power without a shutdown). Exposed as
  `values`, a **`QQmlPropertyMap`** — that type is what makes `app/Theme.qml`'s bindings
  re-evaluate, since it emits per-key change notification. Only *overridden* keys are written
  to disk, so a default that changes in a later release still reaches existing installs.
- **Backend settings** — the `CONFIG_SCHEMA` document, never edited optimistically: the
  backend re-broadcasts the authoritative schema after each accepted write.

`groups` concatenates both, tagging each entry `origin: "local" | "backend"`, so one delegate
family renders everything. **Construction order in `main.cpp` matters**: `Settings` is built
**before** `AppConfig`, which consults `savedValue()` for `backendHost` / `backendPort` /
`screensaverTimeoutMin` — a user override must beat the environment. The socket does not exist
yet at that point, so the `CONFIG_*` wiring is deferred to `attachServer()` after
`ServerClient` is constructed. `core/dotenv.{hh,cpp}` holds the `.env` discovery/parsing that
used to be private to `appconfig.cpp`, because both readers now need it.

**`app/Theme.qml` is the façade.** Tokens that are user-tunable are bound
(`readonly property bool lunaEnabled: Settings.values.lunaEnabled`) instead of being literals;
everything else stays a `readonly` literal that qmlcachegen AOT-compiles. A property
initialiser is a *binding*, so all ~236 existing `Theme.x` call sites across 38 files keep
working unchanged and gain live updates for free. **Add a tunable = one schema entry + one
Theme binding**, no call-site edits.

The view's footer names **both** files the screen writes: `Settings.storagePath` (the local
override file) and `Settings.backendStoragePath` — the backend's `config.json`, taken from the
top-level `path` in its `CONFIG_SCHEMA` document (`Config.path`). The paths are
deployment-specific, so without them "where do I edit this by hand" is unanswerable from the
device. `backendStoragePath` is empty until a schema arrives (rendered as "—") and is kept
after a disconnect, like the backend groups themselves; a document without the key never
blanks a path already shown, so an older backend degrades quietly.

**Layout — master/detail, three levels deep.** `views/SettingsView.qml` is a sidebar + pane
split: `items/settings/SettingsSidebar.qml` lists the sections (one per schema group, its row
naming the subsections inside) and `SettingsPane.qml` renders the selected section as a stack
of **one card per subsection** (issue #30) — the same card the sidebar itself carries. The pane
is transparent; the cards are the containers, so nothing is nested inside a further border.
Sections are general (Yleinen, Media, Datan visualisointi, Sähkö, Tesla, Ylläpito) and the
subsections carry the detail.

**The two schemas merge by group id.** `Settings::rebuildGroups()` no longer concatenates the
local and backend halves — it indexes the backend's groups by id and folds each into the local
group of the same id, so one sidebar section can hold subsections from both. Consequences worth
knowing:
- **`config/settings.json` is the canonical section list**: order, label and icon come from it,
  which is why `media`, `electricity` and `tesla` appear there with an empty `sections` array.
  Those placeholders exist only to place and name a backend-only section; a section that ends up
  with no subsections at all is hidden, so they cost nothing while disconnected.
- A backend group whose id the local schema does not know is **appended**, not dropped.
- `origin` is per **subsection** now (the "sovellus"/"palvelin" badge sits on each card), because
  a section can legitimately mix the two.
- `sectionsOf()` tolerates the pre-#30 shape (a group with a bare `settings` array) by
  synthesizing one subsection, so mismatched halves still render.

Further schema keys the delegates understand: **`relevantWhen`** (`{key, equals|notEquals}` —
`SettingRow` fades a row whose controlling setting makes it meaningless **and sets
`enabled: false` on it**, since a control that changes a value with no effect is worse than one
that visibly cannot be used; `enabled` propagates down the item tree, so no editor needs to know
about relevance. A setting that is a *precondition* for its controller — the screensaver's photo
folder, without which the screensaver cannot run at all — must NOT carry a rule, or it becomes
unsettable exactly when it needs setting. Resolved through `Settings.valueOf()`, which reaches
**both** halves, with `Settings.valuesRevision` read purely to make the binding live),
**`maxLabel`** (`SettingSlider` shows this text
instead of the number at the slider's top stop — the graph point cap uses it for *rajoittamaton*,
which really does disable decimation) and **`warnBelow` / `warnAbove` + `warnMessage`** (issue
#34: `SettingRow` shows an inline caution while the value crosses the threshold; advisory only,
`min`/`max` remain the hard bounds — the myenergi idle poll interval is the first consumer).

Two details are load-bearing:
- **Two independent restart tiers, both DERIVED not latched.** `restartPending` tracks
  restart-tier *backend* settings, `appRestartPending` restart-tier *local* ones (`backendHost` /
  `backendPort`, consumed once by `AppConfig` at startup). They are fixed by restarting different
  processes, so the banner names which and shows a button per pending one. Each flag is "the
  current value differs from the **baseline** the running process consumed", so reverting a value
  clears the banner instead of latching it forever. The backend baseline is seeded
  **insert-if-absent** — the backend re-broadcasts its schema after every accepted write, and
  taking the new value as the baseline would erase the very difference the banner exists to
  report. It is dropped only when the schema's **`startedAt`** changes, which is what
  distinguishes "the backend restarted, so these values *are* the new baseline" from "the socket
  blipped and reconnected" — a distinction the schema's content cannot make, since it reports what
  is in `config.json`, not what each service snapshotted at construction.
- **Selection is a group ID, and it is sticky.** The section list grows from 3 entries to 8
  when the backend's schema arrives and shrinks again if the connection drops, so an index
  would silently select a different section. `currentSectionId` holds what the user *chose*
  and is never overwritten by a list change; `currentGroup` resolves it on read, falling back
  to the first section. That is what makes a backend section still be selected after a
  reconnect instead of the user being bounced to the first one.
- **Group `icon` is a SEMANTIC name** (`"charger"`, `"media"`, `"price"`, …), mapped to a
  resource by `SettingsSidebar.iconFor()`. The backend names icons without knowing anything
  about frontend assets; an unknown name falls back to the gear. Both schema builders copy
  *every* group-level key rather than an allow-list, so the next group field needs no code
  change (the icon was the first, and an allow-list is exactly what dropped it initially).

**Delegates** (`items/settings/`): `SettingRow` dispatches on `setting.type` to
`SettingSwitch` / `SettingNumber` / `SettingSlider` / `SettingText` / `SettingSelect` (the
last subclasses `TripComboBox`, inheriting the dark styling and the #9/#19 dropdown fixes).

> The **`screensaverDir`** setting (issue #33) is the pattern for a path: `string` + `nullable`,
defaulting from `TESLA_HOMEDASH_SCREENSAVER_DIR` through the schema's `env` key. `AppConfig` no
longer reads that variable at all — two readers would be two sources of truth, and the setting is
live. `ScreenSaver.qml` binds `FolderListModel.folder` to `Settings.toFileUrl(Theme.screensaverDir)`
(`QUrl::fromLocalFile`, empty in → empty out), and with no folder the model is empty, so the
screensaver never activates however the toggle is set. `coerceLocal` gained the matching rule:
an empty string is rejected unless the setting is `nullable`.

**Backend reachability** (issue #36) is `core/connectionprobe.{hh,cpp}`, the QML singleton
**`Probe`**, surfaced by `items/settings/BackendProbeStatus.qml`. It is deliberately NOT
`ServerClient`: that one owns the live session and reconnects forever, which is the opposite of
what a validation check may do. `Probe` opens a socket, waits 3 s, reports `reachable` /
`unreachable` (with the socket's own error text — "Connection refused" and "Host not found" are
different problems) and closes; a successful probe aborts the instant it connects, so the
backend just sees a connection open and close.

The hook is a **subsection-level `status` key**: a subsection may name a runtime status widget,
which `SettingsPane` renders in the card via a `Loader` above the rows, resolving the name against
a small component table (`backendProbe`, `systemStatus`, `spotifyAuth`). `active:` gates
construction, which is what keeps the probe from firing — and Chromium from starting — for a card
that did not ask for it. A subsection carrying a `status` but **no settings** is legitimate and is
exempted from the empty-section filter: the system-status card is entirely a status widget. It exists because not every fact about a section fits in a
setting row: *is that address reachable* belongs to the host and port **together**. The verdict
follows the SAVED values (what startup will actually use), debounced 400 ms so editing host then
port probes once against the final pair. Advisory only — the write is never blocked, since the
backend legitimately may not be up yet.

**Display power-down** (issue #35) is `core/screenpower.{hh,cpp}`, the QML singleton
**`Display`** — a step BEYOND the screensaver: the screensaver keeps the backlight on to show
photos, this cuts it. **It runs no process.** This side owns only the countdown, because it is
the only side that sees touch input; the `wlopm` call lives in `display_service` (§5.2.8b),
because talking to the system is the backend's job. `off` and `available` are *reported by* the
backend over `DISPLAY_POWER_STATE`, never assumed here, so a host with no wlopm answers
`available=false` and the toggle simply has nothing to drive. It hangs off the
**`IdleWatcher::activity()`** signal rather than installing a second event filter, so both
timeouts share one definition of "the user is here". Its settings are *pushed* from `Main.qml`
(`Binding` on `Display.enabled` / `.timeoutMs`), the same pattern the screensaver timeout uses
for `Idle`, which is what makes them live.

**The maintenance dashboard** (issue #39) is `core/systemstatus.{hh,cpp}`, the QML singleton
**`System`**, rendered by `items/settings/SystemStatusPanel.qml`. Pull, not push: it polls
`SYSTEM_GET_STATUS` every 5 s **only while `active`**, which the panel binds to its own
visibility — so a settings screen nobody has opened costs nothing on either side. The document is
handled as an opaque `QVariantMap` on purpose: it is a dashboard, not a contract, and adding a
metric on the backend should not need a C++ change to display it.

**Fullscreen** is the local `fullscreen` setting (`general` → *Näyttö*), read straight from
`Settings.values` by `Main.qml` rather than through `Theme` — it is a window mode, not a design
token. Two things hang off it. The **size lock is released in fullscreen**
(`minimumWidth == maximumWidth == 1280` otherwise): the compositor cannot size a surface whose
min and max are pinned. And the window **steps back to windowed for the duration of a Spotify
re-authorization** (`SpotifyAuth.phase !== "idle"`), because the consent page opens in the host's
own browser and must be reachable above the dashboard — on labwc, Raspberry Pi OS Bookworm's
compositor, squeekboard is hardcoded to the `top` layer and does not draw over a fullscreen
surface (labwc#2926), so a fullscreen dashboard would leave the on-screen keyboard unreachable and
the login untypeable on a keyboard-less panel.

**Spotify re-authorisation** (issue #38) is `core/spotifyauth.{hh,cpp}`, the QML singleton
**`SpotifyAuth`**, with `items/settings/SpotifyAuthPopup.qml` over the view and
`SpotifyAuthStatus.qml` in the card. `phase` is a plain string state machine
(`idle`/`requesting`/`consent`/`done`/`error`) so QML switches on it with no enum registration.

**This side renders no browser and never touches a credential.** The backend opens the consent page
in the host's real browser and catches the redirect on its own loopback listener (§5.2.8d); the
singleton's whole job is `begin()`, `cancel()`, and turning `SPOTIFY_AUTH_URL` / `_RESULT` into a
phase. It originally drove an embedded `WebEngineView` that aborted the redirect navigation to read
the code out of the URL — that design is **gone**, and with it Qt WebEngine (see below).

Two details are load-bearing:
- **There is no browser on this side at all.** `SpotifyAuthPopup.qml` is a small progress dialog —
  "Tunnistautuminen käynnissä…" → "Tunnistautuminen onnistui." with a close button — plus
  `DialogButton.qml`. It renders no page, holds no profile, and learns only "started" and
  "finished"; no code or token ever crosses the link. **`Qt::WebEngineQuick` is gone from
  `CMakeLists.txt`, `QtWebEngineQuick::initialize()` from `main.cpp`, and `WebEngineQuick` from the
  README's module list** — verified with `ldd`, the binary links no WebEngine library. A *Peruuta*
  button stays available while the flow runs: a browser that never comes back would otherwise
  strand the dialog on screen.
- **The prompt and the progress dialog live in `Main.qml`, not in `SettingsView`.** The grant can
  die while any view is on screen, so `SpotifyAuthAlert.qml` (z:250) has to be raised over whatever
  that view is — and its button starts a flow whose progress dialog (z:260) would be invisible if it
  still lived in a settings screen nobody was looking at. Both sit **below the screensaver** (z:300):
  a dashboard that has gone to sleep should stay asleep for a prompt that will still be there on
  waking. `alertVisible` is derived in C++ from three inputs — `needsReauth`, dismissed, and
  `phase == "idle"` — so the prompt never stacks under the dialog. Dismissing is sticky until the
  grant works again and then fails afresh (a dashboard nobody can re-authorize right now must stay
  usable), and `begin()` counts as dismissing, so a failed flow does not re-raise the prompt the
  moment its error is closed.
- **`m_flowActive` fences late replies.** `cancel()` only set the phase, so a `SPOTIFY_AUTH_URL`
  arriving afterwards flipped the phase back to `consent` and reopened the dialog for an abandoned
  flow. The flag is set in `begin()`, cleared in `cancel()` and on `SPOTIFY_AUTH_RESULT`; the
  `SPOTIFY_AUTH_STATUS` branch stays unfenced on purpose — that snapshot must always apply.

> **Dead end, recorded so nobody repeats it.** Before the flow moved to the host browser, a lot of
> work went into making the embedded `WebEngineView` look like a real browser: `GALLIUM_DRIVER`
> for WebGL, `--disable-gpu-compositing` for rendering, and a `WebEngineProfile` whose UA and
> `clientHints` were rewritten together (setting `httpUserAgent` alone leaves `Sec-CH-UA` reporting
> Chromium's real version, so the old hardcoded `Chrome/131` against Chromium 140 advertised two
> Chrome majors in one request — a *stronger* bot signal than not spoofing). All of it worked, and
> **none of it got past Spotify's login gate.** The lesson is the RFC's, not a tuning one: an
> embedded user-agent is not supposed to work, and no amount of fingerprint alignment changes that.

An `action` row whose key `Settings::invokeAction` does not handle itself now emits
**`actionRequested(key)`**, which `SettingsView` routes — that is how the backend owns the Spotify
exchange while the consent UI stays a view concern, with `Settings` knowing nothing about either.

**Numeric settings default to `SettingNumber` — a `[−] [typed value] [+]` stepper — and
> sliders are OPT-IN** via the schema's `editor: "slider"`. A slider only works when the exact
> number does not matter; most settings here are the opposite. Dispatching on `type` alone
> gave `backendPort` (1–65535) a slider whose 320px track is ~205 ports per pixel, and 13 of
> the 18 numeric settings were similarly undraggable. Only four are genuine coarse dials and
> carry the hint: `tripMaxSpeedKmh`, `graphBucketsPerPx`, `graphRenderMarginFrac`,
> `screensaverStackCount`. **Rule of thumb: if the user knows the number they want, it is not
> a slider.** `SettingNumber`'s ± buttons hold-to-repeat, and it accepts typing for big jumps.

> **`type: "action"` is a button, not a value.** `SettingAction.qml` renders it and calls
> `Settings::invokeAction(key)`; nothing is stored, persisted or sent as `CONFIG_SET`. Keeping
> actions in the schema is what lets the *Ylläpito* section — **restart the dashboard**,
> **restart the backend** — be ordinary sidebar rows instead of a widget bolted onto the view.
> Entries carry `actionLabel` and optionally `requiresConnection` (which greys the backend
> restart while disconnected). Both need a **second tap to confirm** (armed for 4 s, then it
> lapses) — a modal would need a Cancel button and a way to dismiss it, which a fullscreen
> keyboard-less panel does not have.
>
> **`Settings::restartApp()` quits with exit code 42**, the same non-zero code the backend
> uses, so the README's `Restart=on-failure` frontend unit relaunches it. It calls
> `QCoreApplication::exit()` rather than `os._exit`'s equivalent: unwinding `exec()` closes the
> socket and flushes cleanly, and unlike the backend there is no journal-traceback problem to
> avoid. On the embedded target this is the ONLY way to restart the dashboard — it runs
> fullscreen with no keyboard — which is also why no bare "quit" is offered.

Three write-rate / semantics rules matter:
- the **slider commits on release**, not per frame (otherwise a drag rewrites the settings
  file — or fires a `CONFIG_SET` the backend persists — dozens of times a second);
- **text and number fields commit on `editingFinished`**, not per keystroke (otherwise every
  prefix of a typed value gets sent and rejected);
- a **nullable setting that is null renders as "—" / an empty field, not as its minimum**, and
  can be cleared back to null. `electricityPriceEurPerKwh` null means "no flat tariff, show —"
  in the Charging view, which is not the same as pricing energy at 0.000 €/kWh.

## 6. Event flows

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
    → Settings.parseSetResult → writeSucceeded/writeFailed → SettingsView toast
  apply tier "restart": banner → CONFIG_RESTART → ConfigService.run → os._exit(42) → systemd
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
- **QSS**: scoped per widget in `frontend/resources/styles/`, selected by object name (`#ClimateController`).
  Use the `:/resources/...` resource prefix (note the leading slash).
- **UI language**: widget labels are **Finnish** (e.g. "Nopeus", "Akun Varaus", "Ilmastointi", "Sisä", "Ulko").
- **Binary code**: always network byte order — `struct.pack("!...")` / `QDataStream::BigEndian`.
- No committed formatter config — match the surrounding file.

### 7.2 Python docstrings
Every class and function gets a triple-quoted docstring. Functions document each argument:
```python
def calculate_range(distance_miles: float, efficiency: float) -> float:
    '''
    Converts distance from miles to kilometers and applies efficiency factor.
    Arguments:
        distance_miles (float): Raw distance value from the Tesla API in miles
        efficiency (float): Energy efficiency multiplier for the current drive mode
    '''
```
Add inline comments only for non-obvious logic (protocol packing, formula eval, state-machine
transitions, scheduling edge cases). Don't comment self-explanatory code.

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
- Format is byte-identical to the backend; stdout only, no files/rotation.
- Each `.cpp` gets a file-local `static const Logger logger = Logger::get("<name>");`.
- Threshold via `TESLA_HOMEDASH_LOG_LEVEL`; `Logger::install` is called twice from `main()`
  (INFO first so `AppConfig`'s own logs land, then the configured level).
- Outbound control commands → INFO; protocol problems (truncated/unknown/mismatched/socket) → WARNING;
  per-packet telemetry trace → DEBUG. New paths follow that convention.

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
  up. The agent still only commits/pushes when the user agrees; this is about offering at the right
  moment, not committing unprompted.
- **When creating an issue, always add a label and assign it to the maintainer.** Work is tracked as
  GitHub issues on `einioville/Tesla-Homedash`. Every issue you open must carry at least one label
  (`gh issue create --label "<label>"`; pick or create the fitting one — `bug`, `enhancement`, etc.)
  and be assigned to the maintainer (`--assignee "@me"`). Never open an unlabelled or unassigned issue.
- **After a feature/fix commit, ask about closing its issue.** When a commit resolves an open issue,
  automatically ask the user whether to also close that issue (and reference the issue number in the
  commit/PR). Don't close issues unprompted.

### 7.6 Keeping this document current
Update this `CLAUDE.md` whenever you change something it describes — a new telemetry field or command,
a new/renamed service or widget, a protocol change, a build-command change, or a new load-bearing
invariant. Treat the doc as part of the change, not an afterthought, and bump §7.7.

### 7.7 Documentation currency
This guide is current as of the **Options-view feature build-out** on
`feature/settings-options-view`, tracked as issues **#30–#41** (all but **#40**, host reboot,
which is deliberately deferred).

Landed in the latest pass: the **Spotify re-authorisation debug pass**. The consent flow
dead-ended on the WSL2 dev box: WSL2 exposes the GPU as `/dev/dxg` with **no `/dev/dri`**, Mesa
falls back to llvmpipe, Chromium ≥120 refuses a WebGL context on software GL, and Spotify's login
gate — **Google reCAPTCHA Enterprise, not Cloudflare**, as the original build assumed throughout —
cannot build a solvable challenge without one, so `challenge-orchestrator` answered 400 forever.
Measured both ways in a `WebEngineView`: `webgl1:false` + `WebGL1 blocklisted` by default,
`webgl1/webgl2:true` on `ANGLE (… D3D12 …)` with `GALLIUM_DRIVER=d3d12`. That alone then broke
rendering instead — no `EGL_EXT_image_dma_buf_import` on the d3d12 driver, so a black panel — and
needed `--disable-gpu-compositing` beside it; a seven-configuration matrix scored on *both* "does a
solid-colour page actually paint" and "does WebGL work" picked that pair as the only one winning
both. `scripts/build-frontend.sh` exports them under `--run` when it sees that host shape (inert on
the Pi, which has `/dev/dri`). **The dead-end itself is a dev-box artifact**; four defects found
alongside it are not. Backend: a failed cache write reported success (spotipy swallows the `OSError`
and never `makedirs`), and the CSRF state check compared our own nonce with itself — both fixed in
§5.2.8d, with `spotipy` now logging through the shared handlers at a pinned INFO. Frontend
(§5.3.6): `cancel()` did not fence late replies (now `m_flowActive`).

**Then the embedded browser was removed outright.** With WebGL, compositing and the UA/client-hint
mismatch all fixed, the `WebEngineView` still could not pass Spotify's reCAPTCHA gate — while the
same flow in a real browser succeeded on the first try (verified end to end: browser history shows
`authorize` → `login/otp` → the callback landing on the loopback listener, and a live API call
against the resulting grant). So `handle_get_url` now opens the page with `xdg-open` and catches the
redirect on a one-shot `asyncio.start_server` (RFC 8252 §7.3), `0xA3` is retired, and
**`Qt::WebEngineQuick` is gone from the build** — `ldd` confirms the binary links no WebEngine
library, which is also why `README.md` lists **Qt 5 Compatibility** but no longer WebEngine. The
popup is now a small progress dialog plus `DialogButton.qml`.

That raised a question with a surprising answer: **`frontend_v2` had no fullscreen support at
all** — `Main.qml` was a hard-locked 1280×800 window, `TESLA_HOMEDASH_FULLSCREEN` was read only by
the frozen Widgets `frontend/`, and `build-frontend.sh --fullscreen` exported it to a binary that
ignored it. So fullscreen is now a real local setting (§5.3.6) that releases the size lock, makes
`--fullscreen` work, and steps back to windowed while a re-authorization runs so the browser and
the on-screen keyboard stay reachable (labwc#2926). Deliberately deferred:
`build_status()` still reports "authorized" from cache presence alone, so it stays green after the
user revokes the app at spotify.com — that needs `SpotifyPlayer` to record its last auth failure.

Landed in the preceding pass: **host audio** (#37 — `audio_service/`, auto-detecting
`pactl`/`wpctl`/`amixer`, two `config.json` keys and no new protocol code, carried by two generic
`ConfigService` additions, `register_options` and `register_guard`); **Spotify re-authorisation**
(#38 — `0xA0`–`0xA4`, the backend holding the secret and the frontend showing the consent page in
the project's only `WebEngineView`, which aborts the redirect navigation so no loopback server is
needed; plus the two latent hazards that fixed — a duplicated OAuth scope literal, and spotipy's
interactive fallback that blocks the player's executor thread forever); the **maintenance
dashboard** (#39 — `system_service/`, stdlib `/proc` metrics, duck-typed `health()` probes and an
`ErrorCounter` log handler, served request/response so it costs nothing while unopened); and four
settings-UX changes — scroll bars removed, a real font ramp on the subsection cards, schema-driven
**`relevantWhen`** fading, and a restart banner that is now **derived from a startup baseline**
(with the new `startedAt` schema field distinguishing a backend restart from a reconnect) so
reverting a value clears it.

**#35 was rebuilt in the same pass to respect the service boundary**: `wlopm` no longer runs from
the frontend at all. The UI owns the idle countdown; `display_service` owns the process.

Predecessor work in this series — the **Options-view regrouping**. The settings schema gained a **subsection level** (#30): groups →
sections → settings in both halves, one card per subsection in the pane, and — the load-bearing
part — `Settings::rebuildGroups()` now **merges the local and backend schemas by group id** instead
of concatenating them, so one sidebar section holds subsections from both. On that, the settings
were regrouped into six general sections (#31: Yleinen, Media, Datan visualisointi, Sähkö, Tesla,
Ylläpito), with `config/settings.json` as the canonical section list (empty-`sections` placeholders
place the backend-only ones). Also landed: the graph tunables reworked (#32 — `tripMaxSpeedKmh` and
`graphMinZoomSpanMs` back to Theme literals, `graphBucketsPerPx` → `graphMaxPoints` with a
*rajoittamaton* top stop that really disables decimation, plus a new `graphSensitivity` multiplier
on pinch/wheel/drag); the screensaver photo folder as a live nullable setting (#33) with
`AppConfig` no longer reading `TESLA_HOMEDASH_SCREENSAVER_DIR`; advisory `warnBelow`/`warnAbove`
thresholds on numeric rows (#34); display power-down via `wlopm` (#35); the backend-address
reachability probe (#36, which added the subsection `status` hook); and **both config files
moved to `~/.config/Tesla-Homedash/`**
(#41 — `backend_config.json` + `frontend_config.json`, `CONFIG_PATH` demoted to an override, the
frontend migrating its old file once). Still open from that set: #37 system audio, #38 Spotify re-auth,
#39 system status, #40 host reboot.

Predecessor work — the **WSL2 development-environment migration**. Development moved from
native Windows to WSL2 (Ubuntu 24.04), and §3.2 + §8 now document **both** flows side by side rather
than Windows only — the Windows box still builds, so neither replaces the other. New on the Linux
side: `scripts/build-frontend.sh` (the counterpart of `build-frontend.ps1`; kit from `--qt-prefix`,
else `$QTDIR`, else newest `~/Qt/*/gcc_64`), `ccache` instead of `sccache` (the CMakeLists probes for
either), and `~/Tesla-Homedash` as the main checkout. `.claude/hooks/check-edit.py` now finds
`~/Qt/*/gcc_64/bin/qmllint` (`QT_SEARCH` replaces `QT_ROOTS`/`QT_GLOB`), so the QML half of the hook
no longer silently no-ops off Windows — it still skips rather than blocks when no Qt kit exists, and
`TESLA_HOMEDASH_QMLLINT` still wins. `.claude/settings.json` gained the Linux build invocations
alongside the PowerShell ones. **There is no Linux port of `new-session.ps1` / `finish-session.ps1`**
— use plain `git worktree` (§8). The full bootstrap guide is `docs/wsl-dev-environment.md`, corrected
in the same pass from a real run: Qt needs the OpenGL **-dev** packages (`libgl1-mesa-dev`), not just
`libgl1`, or `find_package` fails claiming the `Quick` component is missing when the real cause is
the absent `libGL.so`; and `http://localhost:8086` in a Windows browser reaches a *Windows* InfluxDB
if one exists, not WSL's.

Predecessor work — the **settings / Options-view** work on `feature/settings-options-view`.
The dashboard gained an **Asetukset** view (7th dock entry) that edits both frontend preferences
and the backend's `config.json` tunables at runtime, driven by *schemas* rather than hand-laid
rows — adding a tunable is one schema entry and no UI code.

Backend: new `config_service/` (§5.2.8) with `SETTINGS_SCHEMA` (16 settings in 5 groups) as the
write allow-list + UI description, served over new protocol codes `0x90`–`0x94` (§5.1).
`Config` gained `set()` / `save()` — atomic write with a `config.json.bak` snapshot, and a
`__init__` rollback to that backup when the live file fails to load, which is what keeps a
restart-tier setting from restart-looping systemd. **The key discovery that shaped the design:
no service re-reads `Config`** — every one snapshots its values in its constructor — so there
is no "live" apply tier. Seven services gained **`apply_config()`** (`WeatherService`,
`MyEnergiService`, `TripLoader`, `ChargingLoader`, `SpotPriceProvider`, `RadioPlayer`,
`SpotifyPlayer`, the last two via `MediaManager`), and settings with no such path are marked
restart-tier; a hook whose service is absent is honestly *downgraded* to restart. The restart
button exits with code **42** (non-zero, so the README's `Restart=on-failure` suffices) via
`os._exit` rather than `raise SystemExit`, which would print a spurious traceback.

Frontend (`frontend_v2`): new `core/settings.{hh,cpp}` singleton (§5.3.6) fronting local +
backend settings, `core/dotenv.{hh,cpp}` extracted from `appconfig.cpp` so both can read `.env`,
`views/SettingsView.qml` as a **master/detail** screen (`SettingsSidebar` + `SettingsPane`,
one sidebar section per schema group, sticky ID-based selection) with the `items/settings/`
delegates (numeric settings render as a `[−] value [+]` stepper; sliders are opt-in via the
schema's `editor: "slider"`, since only 4 of 18 numeric settings are coarse enough to drag;
a `type: "action"` button powers the *Ylläpito* section, which restarts the dashboard itself
with exit code 42 — the only way to do that on a fullscreen keyboard-less Pi), and
`app/Theme.qml` converted into a
**façade**: user-tunable tokens now bind to `Settings.values.*` while the ~236 existing
`Theme.x` call sites across 38 files are untouched. `AppConfig` now takes a `const Settings*`
and honours saved overrides for `backendHost`/`backendPort`/`screensaverTimeoutMin` over the
environment (`schema default < env/.env < saved override`). `HistoryGraph`'s LOD tunables
(`bucketsPerPx`, `settleMs`, `renderMarginFrac`, `minZoomSpanMs`) now default from Theme so
they are tunable per device.

Deliberately **out of scope**, tracked as **issue #29**: editing the `tesla data` /
`calculated tesla data` tables (47 properties × 6 keys). Their `stream_id`/`category`/`unit`
must stay in lockstep with the frontend registry and the `0x71` wire format, so only the
display-only `log` and `line_mode` fields are safely editable — a separate sub-view, not a
settings form.

Predecessor work — the **agent-builds-the-frontend policy change** (§7.3): the agent now runs
`scripts\build-frontend.ps1` itself after frontend changes instead of deferring every build to the
user, so compile errors surface in the session that caused them. Backing that up, `.claude/settings.json`
(committed) registers a `PostToolUse` hook on `Edit|Write` running `.claude/hooks/check-edit.py`,
which byte-compiles `backend/src` on Python edits and runs `qmllint` on QML edits — the latter gated to
`[syntax]`/`Error:` only, because `frontend_v2` carries ~750 pre-existing style diagnostics but zero
syntax warnings. Note for future edits: `QT_QML_GENERATE_QMLLS_INI` is **deprecated
since Qt 6.10** ("no replacement needed") — don't add it to `frontend_v2/CMakeLists.txt`.
Predecessor work — the **weather-service hang fix**: `WeatherService` had deadlocked on the
Pi for 16 days. `fmiopendata`'s fetch helper calls `requests.get()` with no timeout, so a stalled
FMI response parked an executor thread forever, and APScheduler's default `max_instances=1`
then refused every later tick. Fixed in three layers inside `backend/src`: the FMI GET is now
issued directly with aiohttp + `_FMI_TIMEOUT` and parsed with fmiopendata's own `MultiPoint`
(`__download_stored_query` / `__fetch_and_parse`) under an `asyncio.wait_for` deadline; the
refresh job gained `max_instances=2` / `misfire_grace_time=300` / `coalesce=True` and is now
scheduled *before* the initial fetch; and a cycle yielding no future forecast hours returns
without broadcasting or caching (see §5.2.4's invariants). Also `configure_logging` is env-driven
via `TESLA_HOMEDASH_LOG_LEVEL`, defaulting to **INFO**.
Predecessor work — the **per-property graph line mode** (issue #20, PR #23, merged `50500f6`):
a per-property `line_mode` (`step` default / `linear`) sourced from `config.json` metadata,
threaded through `VehicleDataProperty.get_line_mode()` and serialized as a **4th** per-property
field on `TESLA_GRAPH_PROPERTIES` `0x71`; `HistoryGraph.buildStepped()`/`valueAt()` branch on it.
`GpsHeading` was flipped to `log: false`.
Predecessor work — the **spot-price cost** (issue #12; `SpotPriceProvider` + `SpotPriceService`,
`SPOT_PRICE_STREAM` `0x88`, per-hour spot-valued Charging costs, `CHARGING_SUMMARY` `0x83` = 11
doubles), the **charging-stats** backend (`966a04a`; `CHARGER_STREAM` `0x50`, `CHARGING_*` /
`CHARGER_HISTORY` `0x80`–`0x87`, per-session energy = **sum of positive `ChargeAdded`
increments**), and the History **empty-window boundary-fill** (`1184b60`/`cc11bb8`) — still applies.
When you land changes that touch behaviour documented here, update this line to the new HEAD commit.

## 8. Session workflow — main checkout by default, worktree only for parallelism

The default is to **work in the main checkout** (`P:\Tesla-Homedash` on Windows,
`~/Tesla-Homedash` on WSL2). An isolated git worktree is
only worth its setup cost when you genuinely need **two sessions running at the same time** — reach
for one *only then*. Most sessions are sequential and stay in the main checkout with a warm build
dir and incremental builds. Pure Q&A / exploration that changes no files needs neither.

**Backend — run one, shared.** The frontend connects to whatever backend is on `127.0.0.1:6969`
(`TESLA_HOMEDASH_BACKEND_HOST` / `_PORT` default there), and port 6969 is fixed so only **one**
backend can run at a time. Start it **once** (from the main checkout: `cd backend; uv run python
run.py` — identical on both platforms) and leave it — every frontend, in any checkout, connects to it. Do **not** start a backend
per session. Only a session that actually edits backend code runs its own, and it stops the shared
one first.

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
2. **Windows:** `powershell -ExecutionPolicy Bypass -File scripts\new-session.ps1 -Type <type> -Name "<name>"`
   — **there is no Linux port of the session scripts**; on WSL2 use plain
   `git worktree add ../Tesla-Homedash-worktrees/<type>-<slug> -b <type>/<slug> origin/main`, then
   copy `.env` + `config.json` in by hand and repoint `CONFIG_PATH` at the copy.
   — makes branch `<type>/<slug>` off the freshest `origin/main`, adds a worktree under
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
