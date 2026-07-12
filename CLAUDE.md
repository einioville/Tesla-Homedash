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

### 3.2 Frontend (CMake / Qt Widgets)

Dev environment: **Ninja + Qt 6.11.1 MSVC2022**. CMake ships with Qt at
`D:\Qt\Tools\CMake_64\bin\cmake.exe`. The build directory is **`frontend/builddir`**.

> This section covers the frozen Widgets `frontend/`. For the active **`frontend_v2`**, prefer
> `scripts\build-frontend.ps1` — it imports the MSVC env, finds the Qt kit, and configures + builds
> (+ optionally runs) in one command, with sccache reuse. See §8.

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

**Important:** the Ninja generator does **not** set up the MSVC toolchain itself (unlike the
Visual Studio generator). Run the configure/build from an **"x64 Native Tools Command Prompt
for VS 2022"** (so `cl.exe` is on PATH), or let Qt Creator's configured kit drive it.
Single-config Ninja puts the binary directly at `frontend/builddir/gui.exe` — there is no
`Debug/` or `Release/` subfolder.

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
- `CONFIG_PATH` — absolute path to `config.json`
- `VIN` — Tesla vehicle identification number
- `API_KEY` — Teslemetry access token
- `INFLUX_TOKEN` — InfluxDB auth token
- `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` — from your Spotify Developer App

`start_services.main()` fails fast if any of these are missing. **Optional:** `MYENERGI_HUB_SERIAL`
/ `MYENERGI_API_KEY` (myenergi cloud digest-auth creds) — absent → the charger service is skipped
and the rest of the stack still runs.

### `config.json` (copy from `config_template.json`)
Parsed once by `Config` and injected into every service. Keys:
- `tesla data` — per-field metadata map: `stream_id`, `category`, `unit`, `formula` (sympy
  string or null), `log` (bool), and optional `sleep_default` — the value the field reverts to
  when the vehicle goes to sleep (omit or `null` to leave it at its last reading; the default is
  a final value, the `formula` is **not** re-applied to it).
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

### Frontend environment variables (read only by `AppConfig::load()`)
All optional; defaults match the embedded target.
- `TESLA_HOMEDASH_BACKEND_HOST` (default `127.0.0.1`)
- `TESLA_HOMEDASH_BACKEND_PORT` (default `6969`)
- `TESLA_HOMEDASH_WINDOW_WIDTH` / `_HEIGHT` (default `1280` / `800`)
- `TESLA_HOMEDASH_FULLSCREEN` — `1`/`true`/`yes` for fullscreen (default off). Fullscreen
  skips the fixed-size lock; windowed mode locks to the configured size.
- `TESLA_HOMEDASH_LOG_LEVEL` — `debug`/`info`/`warning`/`error`/`critical` (default `info`;
  invalid → `info` + a startup warning).

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
| `0x71` | TESLA_GRAPH_PROPERTIES | B→F | `count(2B)` + per property `id_len(2B)+id + unit_len(2B)+unit + cat_len(2B)+category` (UTF-8) |
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
server, `MediaManager.get_run_task()`, `WeatherService.get_run_task()`, and — when charger
credentials are set — `MyEnergiService.get_run_task()`. (`trip_service` / `charging_service` are
stateless request/response and have no run task.)

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
- **`logger_configurator.py`**: `configure_logging` wires the shared stdout formatter
  (`LEVEL | YYYY-MM-DD | HH:MM:SS | name | message`) onto an allow-list of top-level loggers.
  **Every service's logger prefix must be in `_SERVICE_LOGGERS`** (`tesla_service`, `media_service`,
  `weather_service`, `influxdb_service`, `charging_service`, `myenergi_service`, `trip_service`,
  `server`, `start_services`, `utils`) — an unlisted prefix propagates to a handler-less root and its
  INFO/DEBUG logs silently vanish.

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
  `server_client`, `tesla.data`, `media.data`, `media.card`, `weather.data`, `qt`.
  `main.cpp` also sets a global `QLabel, QPushButton { color: #FFFFFF }` default so text stays white on
  platforms (e.g. Raspberry Pi OS) whose default palette renders near-black on the dark background;
  per-widget QSS still overrides it.

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
The agent does **not** build or run the Qt frontend (no `cmake --build`, no launching `gui.exe`) —
the user verifies frontend builds and runtime behaviour locally. Validate frontend changes by reading
and reasoning about the code, and report what to look for at runtime. **Ignore clangd "file not found"
/ "unknown type" diagnostics on Qt headers** in the editor — the real CMake build resolves them. Same
for the backend: don't start long-running services; use `python -m compileall backend/src` for syntax
checks and let the user run the live stack.

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
- **Prompt to commit once work is verified.** This repo tends to accumulate uncommitted,
  manually-verified changes (the frontend isn't agent-built, so verification happens on the user's
  side). When the user confirms a feature works — i.e. they say a manual test passed — proactively
  prompt to commit it then, in focused commits per the above, rather than letting verified work pile
  up. The agent still only commits/pushes when the user agrees; this is about offering at the right
  moment, not committing unprompted.
- **After a feature/fix commit, ask about closing its issue.** Work is tracked as GitHub issues on
  `einioville/Tesla-Homedash`. When a commit resolves an open issue, automatically ask the user
  whether to also close that issue (and reference the issue number in the commit/PR). Don't close
  issues unprompted.

### 7.6 Keeping this document current
Update this `CLAUDE.md` whenever you change something it describes — a new telemetry field or command,
a new/renamed service or widget, a protocol change, a build-command change, or a new load-bearing
invariant. Treat the doc as part of the change, not an afterthought, and bump §7.7.

### 7.7 Documentation currency
This guide and `README.md` are current as of the **spot-price cost** work on
`feature/spot-price-cost` (issue #12), which builds on the charging-stats backend: **hourly Nord Pool
FI spot pricing** for the Charging view's cost tiles + a live current-price tile. New backend modules
`charging_service/spot_price.py` (`SpotPriceProvider` — no-key sähkötin.fi fetch/cache/convert, all-in
`(spot + margin) × (1 + VAT)`, retroactive/historical) and `spot_price_service.py` (`SpotPriceService`
— hourly `SPOT_PRICE_STREAM` `0x88` broadcast). Cost moved from the `CHARGING_GET_MONTH` handler into
the loader/session: sessions bucket `ChargeAdded` by UTC hour and price each hour; `month_summary`
sums session costs + prices the hourly home import (new `read_grid_import_kwh_hourly` +
`integrate_power_series_hourly`, replacing `read_grid_import_kwh_month`). The flat
`electricityPriceEurPerKwh` is now a per-hour fallback. `CHARGING_SUMMARY` `0x83` grew to **11 doubles**
(+`cost_eur`, +`avg_price_eur_per_kwh`); `CHARGING_MONTH` `0x85` unchanged (13 doubles, now spot-valued).
New `spotPrice` config block. Pure cost math is unit-tested in `backend/tests/test_spot_price.py`.
Predecessor work — the **charging-stats** backend (`966a04a`; myenergi `CHARGER_STREAM` `0x50`,
`CHARGING_*`/`CHARGER_HISTORY` `0x80`–`0x87`, per-session energy = **sum of positive `ChargeAdded`
increments**), the History **empty-window boundary-fill** (`1184b60`/`cc11bb8`), and the `0x70`–`0x73`
request/response + `(payload, writer)` handler signature (`827824d`) — still applies.
When you land changes that touch behaviour documented here, update this line to the new HEAD commit.

## 8. Session workflow — main checkout by default, worktree only for parallelism

The default is to **work in the main checkout** (`P:\Tesla-Homedash`). An isolated git worktree is
only worth its setup cost when you genuinely need **two sessions running at the same time** — reach
for one *only then*. Most sessions are sequential and stay in the main checkout with a warm build
dir and incremental builds. Pure Q&A / exploration that changes no files needs neither.

**Backend — run one, shared.** The frontend connects to whatever backend is on `127.0.0.1:6969`
(`TESLA_HOMEDASH_BACKEND_HOST` / `_PORT` default there), and port 6969 is fixed so only **one**
backend can run at a time. Start it **once** (from the main checkout: `cd backend; uv run python
run.py`) and leave it — every frontend, in any checkout, connects to it. Do **not** start a backend
per session. Only a session that actually edits backend code runs its own, and it stops the shared
one first.

**Frontend — build from the CLI, no Qt Creator needed.** Build + run `frontend_v2` with
`powershell -ExecutionPolicy Bypass -File scripts\build-frontend.ps1 -Run` (add `-Clean` for a full
rebuild, `-Config Release`, `-Fullscreen`). From **cmd.exe** use the `.cmd` shim instead:
`scripts\build-frontend.cmd -Run` (same for `new-session.cmd` / `finish-session.cmd`). It imports the MSVC env, finds the newest Qt
`msvc2022_64` kit, and runs a Ninja configure + build of `appfrontend_v2` into `frontend_v2\build`
— works from the main checkout or any worktree. Open Qt Creator only when you need the debugger /
QML profiler / designer. **sccache** is wired into `frontend_v2/CMakeLists.txt` (auto-enabled when
on PATH), so object files are reused across rebuilds *and across worktrees* — a fresh worktree's
"clean" build is mostly cache hits. Inspect with `sccache --show-stats`. (Per §7.3 the agent still
doesn't build; it reasons about the code and the user runs the script.)

**When you *do* need a parallel session (worktree).**
1. Ask the user **(a) what we're doing** and **(b) a short name**; choose the branch **type**
   (`feature` / `fix` / `chore` / `docs` / `refactor` / `test` / `perf`).
2. `powershell -ExecutionPolicy Bypass -File scripts\new-session.ps1 -Type <type> -Name "<name>"`
   — makes branch `<type>/<slug>` off the freshest `origin/main`, adds a worktree under
   `..\Tesla-Homedash-worktrees\<type>-<slug>`, copies the gitignored `.env` + `config.json` in, and
   repoints `CONFIG_PATH` at the worktree's copy. Final stdout line: `WORKTREE_PATH=<path>`.
3. Switch in with the **`EnterWorktree`** tool (`path:` = that `WORKTREE_PATH`). Build there with
   `build-frontend.ps1`; connect to the already-running shared backend (don't start a second one).

**Finish — land via GitHub, never a local merge** (applies whether you used a branch or a worktree).
1. Commit per §7.5 (only once the user confirms the work is verified), then
   `git push -u origin <type>/<slug>`.
2. Open the PR with a proper body (summary, reason, manual verification, UI screenshots) per §7.5.
3. Merge **on GitHub**: `gh pr merge --squash --delete-branch`. GitHub is the single source of
   truth — **do not** merge into `main` locally (it diverges local `main` from `origin/main`). Then
   update the main checkout: `git checkout main && git pull`.
4. If a worktree was used: `ExitWorktree` (action `keep`), then
   `powershell -ExecutionPolicy Bypass -File scripts\finish-session.ps1 -Type <type> -Name "<name>"`
   — refuses until the PR reads MERGED (via `gh`), then removes the worktree, pulls main, deletes the
   merged local branch, and prunes. (`-Force` skips the merged check.)

**Memory caveat.** Memories load at session start from the main checkout, so their guidance stays in
context even after an `EnterWorktree`. But the memory *store* follows the working directory, so any
durable memory you write during a worktree session must target the **main checkout's** project-memory
dir, not the worktree's (which is deleted at cleanup).
