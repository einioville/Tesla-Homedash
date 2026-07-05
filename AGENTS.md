# Repository Guidelines

## Scope
Tesla-Homedash is a 1280x800 desktop dashboard (designed for an embedded display) combining live Tesla telemetry, media playback, weather forecasts, and HVAC climate controls. A Python async backend streams data over a custom binary TCP protocol to a Qt6 C++20 frontend.

## Project Structure

```
backend/
  src/
    start_services.py         # Entrypoint — wires ALL services (tesla, media, weather, trips, charging) and starts the event loop
    tesla_service/
      telemetry.py              # WebSocket stream from eu.teslemetry.com via teslemetry_stream
      tcp_server.py             # asyncio TCP server on 0.0.0.0:6969 — routes packets between frontend and services
      vehicle.py                # Vehicle state, telemetry event handler, Tesla REST commands (HVAC)
      vehicle_data_property.py  # VehicleDataProperty / CalculatedVehicleDataProperty — per-field state, formula eval, binary serialization
    media_service/
      base_media_player.py      # Abstract base for media players
      media_manager.py          # MediaManager orchestrator — routes controls between Spotify and Radio
      spotify_service.py        # Spotify Web API polling + playback controls via spotipy
      radio_player.py           # VLC-based internet radio playback (Nelonen Media stations)
    weather_service/
      weather_service.py        # FMI Open Data WFS polling for Tampere weather forecast
    influxdb_service/
      influxdb_handler.py       # Async InfluxDB client — telemetry write + historical reads (Flux queries)
    utils/
      config_parser.py          # ConfigUtils: loads config.json and .env values
    ui/plot/
      dataplot.py               # Optional PySide6/pyqtgraph interactive plot (standalone, not used at runtime)
  pyproject.toml                # Python package metadata + dependency pins
  requirements.txt              # Flat dependency list (mirrors pyproject.toml)

frontend/                       # Qt6 Widgets-based GUI (primary production frontend)
  CMakeLists.txt                # Build config — Qt6 Core/Gui/Widgets/Network/QuickWidgets/Location/Positioning/Quick/Svg/Graphs
  resources.qrc                 # Qt resource bundle manifest
  resources/
    fonts/                      # Gotham Rounded Medium OTF
    icons/                      # SVG/PNG icons for controls and climate indicators
    styles/                     # Per-widget QSS files (climatecontroller, spotifyplayer, weathercard, etc.)
    models/                     # Blender model files (tesla_3.blend)
  src/
    main.cpp                    # App entry — loads font, creates MainWindow
    mainwindow.{hh,cpp}        # MainWindow — 10x16 grid layout, wires all widgets and data handlers
    server_client/
      serverclient.{hh,cpp}    # QTcpSocket client — connects to backend:6969, demuxes binary packets to signals
    tesla/
      vehicle.{hh,cpp}        # Frontend-side TeslaDataProperty registry (stream_id -> data_id mapping)
      datahandler/
        tesladatahandler.{hh,cpp}  # Deserializes binary stream packets, emits per-property Qt signals, sends commands
      widgets/
        tesladatawidget.{hh,cpp}       # Abstract base: TeslaDataWidget / TeslaDataMultiWidget
        singletesladataentry.{hh,cpp}  # Single value display widget
        dataentrylist/
          tesladataentrylist.{hh,cpp}  # Grouped list of data entries
        map/
          teslamap.{hh,cpp}            # QML-based map widget (OpenStreetMap)
          map.qml
        climate/
          climatecontrollercard.{hh,cpp}  # Climate control panel
          temperaturecard.{hh,cpp}        # Temp display sub-widget
          teslaclimatestarter.{hh,cpp}    # HVAC on/off button with state glow
          teslaseatwidget.{hh,cpp}        # Seat heater indicator
          teslasteeringwidget.{hh,cpp}    # Steering wheel heater indicator
    mediaplayer/
      datahandler/
        mediaplayerdatahandler.{hh,cpp}  # Parses media packets, emits signals, sends control commands
      widgets/
        mediaplayercard.{hh,cpp}         # Album art, progress slider, playback controls
    weather/
      datahandler/
        weatherdatahandler.{hh,cpp}      # Parses weather forecast packets
      widgets/
        mainweather.{hh,cpp}             # Weather panel container
        currentweathercard.{hh,cpp}      # Current conditions display
        weatherforecastcard.{hh,cpp}     # Hourly forecast card

frontend_prototype/              # Qt Quick / QML rewrite (work in progress)
  CMakeLists.txt                 # Qt6 Core/Gui/Quick/QuickControls2/Location/Positioning
  src/
    main.cpp                     # Entry — registers BackendBridge, loads Main.qml
    backendbridge.{hh,cpp}      # Single C++ bridge class: TCP client + packet parser + Q_PROPERTY bindings
  qml/
    Main.qml                     # Root layout — same 10x16 grid as widget version
    components/
      MapCard.qml                # Map component
      DataEntryListCard.qml      # Telemetry data list card
      MusicCard.qml              # Media player card
      WeatherCard.qml            # Weather forecast card
      ClimateCard.qml            # Climate control card
      TeslaCard.qml              # Base card component

config.json                      # Telemetry field metadata (stream_id, unit, formula, log flag), radio stations, Spotify config, timezone
docs/images/                     # Screenshots for README
teknologiat.txt                  # Finnish-language technology summary for portfolio/interviews
```

## Build, Run, and Validation Commands
- **Configure frontend**: `cmake -S frontend -B frontend/build -DCMAKE_PREFIX_PATH="<Qt6 path>"`
- **Build frontend**: `cmake --build frontend/build --config Release`
- **Run frontend**: `.\frontend\build\Release\gui.exe`
- **Configure prototype**: `cmake -S frontend_prototype -B frontend_prototype/build -DCMAKE_PREFIX_PATH="<Qt6 path>"`
- **Build prototype**: `cmake --build frontend_prototype/build --config Release`
- **Run backend**: `python -m backend` (from project root) or `python run.py` (from `backend/`)
- **Backend syntax check**: `python -m compileall backend/src`
- **Backend venv setup**: `cd backend && python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt`

## Required Local Configuration
Secrets and paths live in `.env` (root directory, gitignored). Required keys:
- `CONFIG_PATH` — absolute path to `config.json`
- `VIN` — Tesla vehicle identification number
- `API_KEY` — Teslemetry access token
- `INFLUX_TOKEN` — InfluxDB auth token
- `SPOTIFY_CLIENT_ID` — Spotify app client ID
- `SPOTIFY_CLIENT_SECRET` — Spotify app client secret

Runtime config in `config.json`:
- `spotifyDeviceId` — target Spotify Connect device ID
- `spotifyCachePath` — absolute path for spotipy OAuth token cache
- `spotifyRedirectUri` — OAuth callback (default `http://127.0.0.1:8080/callback`)
- `defaultRadioStation` — key from `radioMediaIds` map
- `timeZone` — IANA timezone (e.g. `Europe/Helsinki`)

External services:
- InfluxDB on `http://localhost:8086`, org `Tesla-Homedash`, bucket `data`
- Teslemetry WebSocket at `eu.teslemetry.com`

## Binary Protocol Reference

Frontend and backend communicate over TCP on port **6969** using a custom binary protocol.

### Packet structure
All multi-byte integers are **big-endian**.
```
[4 bytes: payload length N] [N bytes: payload]
payload[0] = message type byte
payload[1..N-1] = type-specific data
```

### Message types

| Byte | Name | Direction | Payload |
|------|------|-----------|---------|
| `0x01` | MSG_JSON | F->B | JSON body |
| `0x03` | MSG_TERMINATE | F->B | (empty) |
| `0x04` | MSG_STREAM | B->F | Tesla data: `stream_id(2B) + value_type(1B) + value + timestamp(8B)` |
| `0x14` | MEDIA_STREAM_IMAGE | B->F | Raw image bytes (JPEG/PNG) |
| `0x15` | MEDIA_STREAM_NAME | B->F | `length(2B) + UTF-8 string` |
| `0x16` | MEDIA_STREAM_PROGRESS | B->F | `progress_ms(4B)` |
| `0x17` | MEDIA_STREAM_DURATION | B->F | `duration_ms(4B)` |
| `0x18` | MEDIA_SKIP | F->B | (empty) |
| `0x19` | MEDIA_SKIP_BACKWARD | F->B | (empty) |
| `0x1A` | MEDIA_PAUSE_PLAY | F->B | (empty) |
| `0x1B` | MEDIA_IS_PLAYING | B->F | `bool(1B)` |
| `0x1C` | MEDIA_SET_PROGRESS | F->B | `progress_ms(4B)` |
| `0x1D` | MEDIA_STREAM_ARTISTS | B->F | `length(2B) + UTF-8 string` |
| `0x1E` | MEDIA_STREAM_TYPE | B->F | `media_type(1B)`: 0x01=radio, 0x02=spotify |
| `0x30` | WEATHER_FORECAST | B->F | Repeated: `sub_id(1B) + value` (see below) |
| `0x60` | TESLA_SWITCH_CLIMATE | F->B | (empty) |
| `0x61` | TESLA_MINUS_TEMP | F->B | (empty) |
| `0x62` | TESLA_PLUS_TEMP | F->B | (empty) |

### Tesla stream value types
| Type byte | Format |
|-----------|--------|
| 0 (float) | `double(8B)` |
| 1 (string) | `length(2B) + UTF-8 bytes` |
| 2 (bool) | `uint8(1B)` |
| 3 (dict) | sequence of `double(8B)` values (used for Location: lat, lon) |

### Weather forecast sub-IDs
| Byte | Field | Format |
|------|-------|--------|
| `0x31` | Temperature | `double(8B)` |
| `0x32` | Wind speed | `double(8B)` |
| `0x33` | Precipitation | `double(8B)` |
| `0x34` | Cloud cover | `double(8B)` |
| `0x35` | Time (hour) | `uint8(1B)` |

### Adding a new telemetry field
When adding a new Tesla data property, **all four locations** must be updated in sync:
1. `config.json` — add entry under `"tesla data"` with unique `stream_id`, `category`, `unit`, `formula`, `log`
2. `backend/src/tesla_service/vehicle_data_property.py` — handled automatically via config (no change needed unless new value_type)
3. `frontend/src/tesla/vehicle.cpp` — add property to the `properties` map with matching `data_stream_id` and `value_type`
4. `frontend/src/tesla/datahandler/tesladatahandler.{hh,cpp}` — add signal declaration in `.hh`, add `case` in `processStreamData()` and both `connectToDataUpdateSignal()` overloads in `.cpp`

For the QML prototype, also update `frontend_prototype/src/backendbridge.{hh,cpp}` (add Q_PROPERTY, member, parser case).

### Adding a new command (frontend -> backend)
1. Define a new message type constant in `backend/src/tesla_service/tcp_server.py` (class attribute)
2. Add handler case in `TeslaDataServer.__handle_connection()`
3. In the frontend, send the packet via `QDataStream` (see `TeslaDataHandler::switchClimateState()` for example)

## Coding Conventions
- **Indentation**: 4 spaces everywhere (Python, C++, QML, QSS)
- **Python**: PEP 8 naming — `snake_case` functions/modules, `PascalCase` classes. Use `async`/`await` consistently (the entire backend is asyncio).
- **C++**: C++20 standard. `.hh` for headers, `.cpp` for sources. `PascalCase` for classes/widgets, `camelCase` for methods and members. Qt naming conventions for slots/signals (`onXxxUpdate`, `processXxx`).
- **QML**: `camelCase` properties and functions, `PascalCase` component names.
- **No committed formatter config** — match existing style in each file.
- **QSS files** are scoped per-widget in `frontend/resources/styles/`. Use object names (`#ClimateController`) for selectors.
- **UI language**: Widget labels use Finnish (e.g., "Nopeus", "Akun Varaus", "Ilmastointi", "Sisä", "Ulko").
- **struct packing**: All binary protocol code uses `struct.pack("!...")`/`QDataStream::BigEndian`. Always use network byte order (big-endian).

## Testing Expectations
No automated test suite exists yet. Validate changes manually:
- **Backend**: start services, confirm telemetry/media/weather flows, run `python -m compileall backend/src`
- **Frontend**: rebuild, launch, connect to backend, verify affected widgets plus data flow
- **Protocol changes**: test both directions — check backend logs and frontend `qInfo()` output
- New tests should go under `backend/tests/test_*.py` and `frontend/tests/` (CTest)

## PR and Commit Guidelines
- Use short imperative prefixes: `Add:`, `Fix:`, `Update:`, `Remove:`, `Create:`
- Keep commits focused to one purpose
- PRs should include: change summary, reason, manual verification steps, and screenshots for UI changes

## Known Bugs and Hotspots

### Bugs
1. **Malformed Authorization header** in `backend/src/tesla_service/vehicle.py` lines 223-225 and 250-252. The header dict uses an f-string that embeds quotes incorrectly:
   ```python
   # BROKEN — produces key: 'Authorization"' value: '"Bearer xxx'
   headers={f'Authorization": "Bearer {self.__access_token}'}
   # SHOULD BE:
   headers={"Authorization": f"Bearer {self.__access_token}"}
   ```
   This affects `switch_climate_state()` and `update_temperature()` — API calls silently fail auth.

2. **Switch fall-through in `frontend/src/tesla/datahandler/tesladatahandler.cpp`**. Three `case` blocks are missing `break` statements:
   - Line 49: `case 3` (ChargeAmps) falls through to `case 5` (ChargeLimitSoc)
   - Line 177: `case 4` (BMSState) falls through to `case 9` (DetailedChargeState)
   - Line 236: `case 20` (Locked) falls through to `case 26` (VehicleOnline)

3. **HVAC state parsing in QML prototype** (`frontend_prototype/src/backendbridge.cpp` line 296). The code checks for `"on"/"true"/"1"` but the backend sends `"HvacPowerStateOn"/"HvacPowerStateOff"/"HvacPowerStatePending"` — HVAC will never show as enabled in the prototype.

### Fragile Patterns
- **`ConfigUtils.get_config()`** re-reads and re-parses `config.json` on every call. Same with `get_env()` calling `load_dotenv()` each time. Works but wasteful — consider caching if this becomes a bottleneck.
- **Weather service** (`weather_service.py`) runs on a cron schedule (every 15 min) but does **not push an initial forecast** on startup. New clients get no weather data until the next cron tick.
- **`TeslaDataServer` and `MediaManager`** both define identical `MEDIA_*` constants — keep them in sync or extract to a shared location.
- **InfluxDB Flux queries** in `influxdb_handler.py` use f-string interpolation for `data_property_id`. Currently safe (values come from config), but would be injection-vulnerable if user input ever reached these paths.
- **Spotify `_current_device_id` vs `_target_device_id`** comparison drives the claim/release logic. If the target device ID in `config.json` is wrong, Spotify controls will silently not work.
- **HVAC rate limiting** (`vehicle.py` `__requests_used`): the counter is in-memory and resets on process restart. The threshold check (`> 4`) blocks at request 5, while the scheduler is set at request 4 — the 5th request is blocked but never scheduled for reset.

## Architecture Notes

### Data flow
```
Teslemetry WS → TelemetryHandler → Vehicle.on_telemetry_event()
    → VehicleDataProperty.update() (formula eval, value store)
    → VehicleDataProperty.get_stream_data() (binary serialize)
    → TeslaDataServer.update_clients() (broadcast to all connected frontends)
    → Also: InfluxDBHandler.write_tesla_data() (persist loggable fields)

Frontend QTcpSocket → ServerClient.onReadyRead() (demux by packet type)
    → TeslaDataHandler.processStreamData() (deserialize, emit per-field signal)
    → TeslaDataWidget.updateDataXxx() (update UI)

User clicks control → build packet → ServerClient.onSendMessageRequest() → TCP → TeslaDataServer.__handle_connection() → Vehicle/MediaPlayer method
```

### Calculated properties
`CalculatedVehicleDataProperty` (e.g., DrivenToday, DrivenThisMonth) derives values from a source property using a formula like `y - x` where `x` is the first reading of the period (fetched from InfluxDB) and `y` is the latest value. APScheduler resets the base value at midnight / month start.

### Media player hierarchy
`MediaManager` orchestrates between `RadioPlayer` (default, VLC-based) and `SpotifyService`. Radio is loaded by default but does not auto-play. When Spotify detects playback on the target device, it calls `claim_media_control()` which stops radio, switches the active player, and auto-plays. When Spotify playback stops or moves to another device, it calls `release_playback()` which loads radio without starting playback.

### Frontend architecture
Both frontends (Widgets and QML prototype) use the same binary protocol. The Widgets version uses a signal/slot routing pattern: `ServerClient` emits packet-type signals → data handlers deserialize → data handlers emit per-field signals → widgets receive updates. The QML prototype collapses this into a single `BackendBridge` class with Q_PROPERTY bindings.
