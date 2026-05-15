# Tesla-Homedash 1.0

## Features

Tesla-Homedash is a desktop dashboard that brings live vehicle telemetry, music, weather, and HVAC controls into a single glanceable surface. The Python asyncio backend is designed so you can have multiple frontend instances running across your network. The 1.0 frontend is built with C++ and Qt6; the following version will provide a QML-powered approach.

- **Live Tesla telemetry** — tracks every stat available in the Tesla Fleet API. The dashboard displays six of them at a time, including values calculated from history such as daily and monthly driving distance.
- **Map** — shows where the car is.
- **HVAC controls** — start the climate system and adjust target temperatures from the dashboard.
- **Media player with automatic source switching** — Nelonen Media internet radio plays by default. The moment Spotify starts playing on the configured Spotify Connect device, the dashboard takes over and shows track, artist, album art, scrubbable progress, and play/skip controls. When Spotify stops, radio resumes.
- **Weather forecast** — current conditions plus the next five hours (temperature, wind, precipitation, cloud cover) for any location the Finnish Meteorological Institute's open data feed supports.
- **Optional stat logging** — telemetry can be written to a local InfluxDB database for historical analysis.

![Main Screen](docs/images/Screenshot%202026-01-29%20154107.png)

## Dependencies

### Needed subscriptions
- [Teslemetry](https://teslemetry.com) — paid Tesla Fleet API provider used as the live telemetry source.
- [Spotify Premium](https://www.spotify.com/premium/) — required for the built-in Spotify player; the Spotify Web API only permits remote playback control on Premium accounts.
- [Spotify Developer App](https://developer.spotify.com/dashboard) — free but mandatory: a registered app is what provides the `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` values used for OAuth. There is currently no automated helper for fetching the Spotify access token, so you'll need to complete the OAuth handshake yourself once and place the resulting token cache at the path configured in `config.json`.

### Python libraries
- [APScheduler](https://apscheduler.readthedocs.io/) — periodic and cron-style jobs.
- [aiohttp](https://docs.aiohttp.org/) — async HTTP client.
- [aiocsv](https://github.com/MKuranowski/aiocsv) — async CSV reader.
- [fmiopendata](https://github.com/pnuu/fmiopendata) — Finnish Meteorological Institute open-data client.
- [influxdb-client](https://github.com/influxdata/influxdb-client-python) — InfluxDB read / write client.
- [numpy](https://numpy.org/) — numerics for cover-art processing.
- [python-dotenv](https://github.com/theskumar/python-dotenv) — loads `.env` secrets.
- [python-vlc](https://wiki.videolan.org/Python_bindings/) — Python bindings to libVLC for the radio player.
- [spotipy](https://spotipy.readthedocs.io/) — Spotify Web API client.
- [sympy](https://www.sympy.org/) — formula evaluation for telemetry conversions.
- [teslemetry-stream](https://pypi.org/project/teslemetry-stream/) — Teslemetry WebSocket client.

### C++
- [Qt 6](https://www.qt.io/) — the frontend is built on Qt 6 Widgets, using the `Core`, `Gui`, `Widgets`, `Network`, `QuickWidgets`, `Location`, `Positioning`, `Quick`, `Svg`, `Graphs`, and `Concurrent` modules.
- [CMake](https://cmake.org/) 3.16 or newer — the frontend's build system.
- A C++20-capable compiler (MSVC 2019 16.10+, GCC 10+, or Clang 12+).

### Services
- [Spotifyd](https://github.com/Spotifyd/spotifyd) — turns the host machine into a Spotify Connect target so Spotify clients can hand playback to it.
- [InfluxDB](https://www.influxdata.com/) — stores logged telemetry fields for history-based calculations such as daily / monthly driving distance.

### System packages
- [VLC / libVLC](https://www.videolan.org/vlc/) — `python-vlc` is only the binding; the radio player won't produce sound unless the underlying VLC / libVLC runtime is installed on the host.
