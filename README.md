# Tesla-Homedash
Tesla-Homedash is a desktop dashboard that combines Tesla telemetry, media playback controls, and weather forecast data into one UI.

## Features
- Live Tesla telemetry stream and dashboard widgets
- Tesla climate controls (toggle HVAC and target temperature changes)
- Spotify playback controls and track metadata display
- Web radio playback integration
- Hourly weather forecast cards (temperature, wind, precipitation, cloud cover)
- InfluxDB telemetry logging for historical metrics

## Architecture
- `frontend/`: Qt6 C++ GUI client (`gui`) with widgets for Tesla data, map, weather, media, and climate.
- `backend/src/`: Python async services:
  - Tesla telemetry stream + TCP server
  - Media orchestration (Spotify + radio)
  - Weather polling service
  - InfluxDB integration for data history
- Frontend and backend communicate using a custom binary protocol over TCP (`127.0.0.1:6969` by default).

## Repository Layout
- `frontend/src/`: main Qt application and widgets
- `frontend/resources/`: icons, fonts, QSS styles
- `backend/src/tesla_service/`: telemetry, vehicle logic, TCP server, startup
- `backend/src/media_player/`, `spotify_service/`, `radio_service/`, `weather_service/`
- `backend/src/influxdb_service/`: InfluxDB read/write layer
- `backend/pyproject.toml` and `backend/requirements.txt`: Python dependency definitions
- `config.json`: telemetry metadata and app settings
- `docs/images/`: screenshots used in docs

## Prerequisites
- Python 3.10+
- Qt 6 with components used in `frontend/CMakeLists.txt` (`Core`, `Gui`, `Widgets`, `Network`, `QuickWidgets`, `Location`, `Positioning`, `Quick`, `Svg`, `Graphs`)
- CMake 3.16+
- InfluxDB instance (default backend URL is `http://localhost:8086`)

## Configuration
Create a local `.env` file and define at least:
- `CONFIG_PATH` (absolute path to `config.json`)
- `VIN`
- `API_KEY` (Teslemetry access token)
- `INFLUX_TOKEN`
- `SPOTIFY_CLIENT_ID`
- `SPOTIFY_CLIENT_SECRET`

Adjust `config.json` as needed for:
- `spotifyDeviceId`
- `spotifyCachePath`
- `defaultRadioStation`
- weather timezone and other app defaults

## Run Backend
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
# Alternative installer from pyproject metadata:
# python -m pip install -e .
python -m src.tesla_service.start_tesla_services
```

## Build and Run Frontend
```powershell
cmake -S frontend -B frontend/build -DCMAKE_PREFIX_PATH="<Qt6 path>"
cmake --build frontend/build --config Release
.\frontend\build\Release\gui.exe
```

## Quick Validation
- Backend syntax check:
```powershell
python -m compileall backend/src
```
- Start backend, launch frontend, then verify:
  - telemetry widgets update
  - media controls send actions
  - weather cards refresh
  - climate controls trigger backend commands

## UI
![Main Screen](https://github.com/einioville/Tesla-Homedash/blob/main/docs/images/Screenshot%202026-01-29%20154107.png?raw=true)
