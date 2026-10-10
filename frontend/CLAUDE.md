# `frontend/` — the frozen Qt Widgets frontend

**Frozen.** `frontend_v2/` (QML) is the live target and gets all feature work; this directory is
kept building but rarely changes. Its environment variables are listed in `frontend_v2/CLAUDE.md`.
The root `CLAUDE.md` is always loaded alongside this file, so nothing here repeats it.

## Build

**Linux / WSL2 — the frozen `frontend/`** (rarely needed; `frontend_v2` is the live target):

```bash
cmake -S frontend -B frontend/builddir -G Ninja -DCMAKE_PREFIX_PATH="$QTDIR"
cmake --build frontend/builddir --target all
./frontend/builddir/gui
```

**Windows — the frozen `frontend/`:**

- **Configure** (required once before the first build, and after CMakeLists changes):

  ``` D:\Qt\Tools\CMake_64\bin\cmake.exe -S frontend -B frontend/builddir -G Ninja
  -DCMAKE_PREFIX_PATH=D:/Qt/6.11.1/msvc2022_64 ```

- **Build**:

  ``` D:\Qt\Tools\CMake_64\bin\cmake.exe --build frontend/builddir --target all ```

- **Run**: `.\frontend\builddir\gui.exe` (PowerShell with overrides:
  `$env:TESLA_HOMEDASH_FULLSCREEN=1; .\frontend\builddir\gui.exe`)

**Important (Windows only):** the Ninja generator does **not** set up the MSVC toolchain itself
(unlike the Visual Studio generator). Run the configure/build from an **"x64 Native Tools Command Prompt
for VS 2022"** (so `cl.exe` is on PATH), or let Qt Creator's configured kit drive it.
Single-config Ninja puts the binary directly at `frontend/builddir/gui.exe` (`gui` on Linux) —
there is no `Debug/` or `Release/` subfolder. On Linux `g++` is already on `PATH`, so there is no
environment to import.

## Source layout

```
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
```

## Architecture

The Widgets frontend uses a signal/slot routing pattern: `ServerClient` emits one signal per
packet type → datahandlers deserialize → datahandlers emit per-field signals → widgets update.
`MainWindow` builds the 10×16 grid and wires widgets to their datahandlers and to the `ServerClient`.

### `server_client/serverclient.{hh,cpp}`
`QTcpSocket` client. `onReadyRead` reassembles framed packets out of the TCP byte stream
(4-byte length + 1-byte type + payload), **rejects implausible lengths** (16 MB cap, 64-bit-safe
size math) and demuxes each packet to a typed signal. Reconnects 10 s after disconnect/error.
Outbound control packets are written **non-blocking** — do not reintroduce
`flush()`/`waitForBytesWritten(...)` (it caused visible click latency; control packets are ≤6 bytes).

### `tesla/` — telemetry widgets + datahandler
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

### `mediaplayer/` — media widgets + datahandler
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

### `weather/` — weather widgets + datahandler
- **`datahandler/weatherdatahandler.{hh,cpp}`**: parses the repeated-sub-id `WEATHER_FORECAST` frame
  (bounds-checked) into vectors and emits one update.
- **`widgets/`**: `mainweather` (container; fans the update out to the banner + 5 cards by id),
  `currentweathercard` (current-hour banner, consumes the sentinel id), `weatherforecastcard`
  (one forecast hour ×5, each ignoring ids that aren't its own).

### `config/appconfig` + `utils/logger`
- **`AppConfig`** is the **only** place to read frontend env vars; `main.cpp` calls `AppConfig::load()`
  once before building `MainWindow`. Reading env elsewhere is a smell — extend `AppConfig` instead.
- **`Logger`** mirrors the backend format to stdout. Never call `qInfo/qWarning/qDebug/qCritical`
  directly — `Logger::install()` funnels Qt's own messages through the same formatter under the source
  `qt`. Worker-thread logs are serialised by a static mutex. Source names today: `app`, `config`,
  `server_client`, `tesla.data`, `media.data`, `media.card`, `weather.data`, `settings`, `qt`.
  `main.cpp` also sets a global `QLabel, QPushButton { color: #FFFFFF }` default so text stays white on
  platforms (e.g. Raspberry Pi OS) whose default palette renders near-black on the dark background;
  per-widget QSS still overrides it.

## Adding a telemetry field here

Only when the frozen frontend should show the field too (the cross-cutting steps are in the root
`CLAUDE.md` §5.1):

1. `src/tesla/vehicle.cpp` — `properties[...]` with matching `data_stream_id` + `value_type`.
2. `src/tesla/datahandler/tesladatahandler.{hh,cpp}` — a signal in the `.hh` and a row in the
   `kRoutes` table (which both `processStreamData` and the `connectToDataUpdateSignal` overloads
   walk).
