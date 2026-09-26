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

> Interface icons are from the [Dazzle Line Icons](https://www.svgrepo.com/collection/dazzle-line-icons/) collection by [Dazzle UI](https://www.svgrepo.com/author/Dazzle%20UI/), provided through [SVG Repo](https://www.svgrepo.com/) under the [Creative Commons Attribution License](https://creativecommons.org/licenses/by/4.0/). Thanks to Dazzle UI for the icons! ❤️

## Dependencies

### Needed subscriptions
- [Teslemetry](https://teslemetry.com) — paid Tesla Fleet API provider used as the live telemetry source.
- [Spotify Premium](https://www.spotify.com/premium/) — required for the built-in Spotify player; the Spotify Web API only permits remote playback control on Premium accounts.
- [Spotify Developer App](https://developer.spotify.com/dashboard) — free but mandatory: a registered app is what provides the `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` values used for OAuth. The Backend step in the Setup chapter walks through running the bundled helper (`python -m src.media_service.setup.spotify_setup`) that completes the OAuth handshake and looks up your Spotify Connect device ID.

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
- [Qt 6](https://www.qt.io/) — the frontend is a Qt 6 Quick (QML) application, using the `Quick`, `QuickControls2`, `Network`, `Concurrent`, `Svg`, `Location`, `Positioning`, `Graphs`, `Core5Compat`, `LabsFolderListModel` and `VirtualKeyboard` modules.
- [CMake](https://cmake.org/) 3.16 or newer — the frontend's build system.
- A C++20-capable compiler (MSVC 2019 16.10+, GCC 10+, or Clang 12+).

### Services
- [Spotifyd](https://github.com/Spotifyd/spotifyd) — turns the host machine into a Spotify Connect target so Spotify clients can hand playback to it.
- [InfluxDB](https://www.influxdata.com/) — stores logged telemetry fields for history-based calculations such as daily / monthly driving distance.

### System packages
- [VLC / libVLC](https://www.videolan.org/vlc/) — `python-vlc` is only the binding; the radio player won't produce sound unless the underlying VLC / libVLC runtime is installed on the host.

## Setup

I run the dashboard on a Raspberry Pi that has a touchscreen display wired to it, but any device meeting the dependency list will work. The next sections cover how I have set up my system.

### Raspberry Pi

- **Hardware** — any modern Raspberry Pi will work.
- **Operating system** — install Raspberry Pi OS 64-bit, complete the setup, and enable SSH.
- **Display** — any display should work. I used [this 10.1-inch display from Amazon](https://www.amazon.de/dp/B0BHHQLKPY).
- **Storage** — an external SSD is strongly recommended over an SD card for InfluxDB's data directory. The dashboard writes telemetry continuously, and SD cards wear out quickly under that kind of sustained write load.

### System packages

Once the Pi is up and SSH'd into, install the OS-level packages needed by both the backend (libVLC runtime) and the frontend (compiler + CMake) toolchain:

```bash
sudo apt update
sudo apt install -y git build-essential cmake vlc
```

- `git` — used to clone this repository.
- `build-essential` and `cmake` — the C++ compiler toolchain and build system used by the frontend. Raspberry Pi OS Bookworm ships a CMake recent enough to satisfy the 3.16 minimum.
- `vlc` — pulls in the libVLC runtime that the `python-vlc` binding talks to. Without it the radio player would launch but produce no sound.

Qt 6 is installed separately via the official Qt installer — see the next subsection.

### Qt 6

Install Qt 6 with the official [Qt online installer](https://www.qt.io/download-qt-installer) — a free Qt account is required. Pick a recent Qt 6 release.

In the installer's **Additional Libraries** step, make sure the following modules are checked:

- **Qt Location**
- **Qt Positioning**
- **Qt Graphs**
- **Qt 5 Compatibility Module** — `Qt5Compat.GraphicalEffects`, used by the icon tinting
- **Qt Virtual Keyboard** — the on-screen keyboard for typing into the Options view on the touch panel

The other Qt modules the frontend links against — `Core`, `Gui`, `Network`, `Quick`, `QuickControls2`, `Svg`, `Concurrent` and `LabsFolderListModel` — are part of the default Qt 6 install and don't need to be enabled separately.

All five of the modules above are `REQUIRED` in `frontend_v2/CMakeLists.txt`, so leaving one unchecked makes `cmake` fail at configure time rather than at build time.

Take note of the install path the installer reports when it finishes (for example `~/Qt/6.8.0/gcc_arm64/` on the Pi). You'll pass it to CMake when building the frontend later.

### InfluxDB

The dashboard logs telemetry to InfluxDB so calculated stats like daily and monthly driving distance have a baseline to compare against.

Install InfluxDB 2.x from InfluxData's apt repository — follow the current commands in the [InfluxDB Linux install guide](https://docs.influxdata.com/influxdb/v2/install/?t=Linux).

Enable InfluxDB to autostart at boot, and start the service now:

```bash
sudo systemctl enable --now influxdb
```

Open `http://localhost:8086`, complete the initial-setup wizard, and create:

- **Organization**: `Tesla-Homedash`
- **Bucket**: `data`

Then under **Load Data → API Tokens**, generate an **All Access** token (or scope one to the `data` bucket). Save the token — it goes into `.env` as `INFLUX_TOKEN` during the Backend step.

The backend connects to `http://localhost:8086` by default, so no further configuration is needed when InfluxDB runs on the same Pi.

### Spotifyd

Spotifyd turns the Pi into a Spotify Connect target so your phone or desktop Spotify can hand playback to it — the dashboard then picks up that stream and shows it on the media card.

No compilation is needed on the Pi. The Spotifyd project publishes prebuilt aarch64 Linux binaries on every release; download the latest one and put it on your `PATH`:

```bash
cd /tmp
wget https://github.com/Spotifyd/spotifyd/releases/latest/download/spotifyd-linux-aarch64-full.tar.gz
tar -xzf spotifyd-linux-aarch64-full.tar.gz
sudo mv spotifyd /usr/local/bin/
```

The `-full` variant includes both ALSA and PulseAudio audio backends; the `-default` variant is ALSA-only. Raspberry Pi OS Desktop runs PipeWire with a PulseAudio compatibility layer, so the PulseAudio backend works out of the box.

> **Optional, for the Options view's audio settings:** `sudo apt install pulseaudio-utils`.
> The backend controls the system volume and output device through whichever of
> `pactl`, `wpctl` or `amixer` it finds, in that order. `wpctl` is always present on
> Bookworm (WirePlumber ships it), so audio works without this — but `pactl` addresses
> sinks by a stable *name* rather than a session-scoped numeric id, which makes a saved
> output device survive reboots and hotplugs more reliably. `pipewire-pulse` only
> *suggests* the package, so it is not installed by default.

Create the config file at `~/.config/spotifyd/spotifyd.conf`:

```toml
[global]

device_name = "Tesla-Homedash"
device_type = "speaker"
cache_path = "~/spotifyd_cache"
max_cache_size = 2000000000
backend = "pulseaudio"
bitrate = 320
```

`device_name` is what appears in the Spotify client's device picker — feel free to change it.

Start Spotifyd manually to verify the install works:

```bash
spotifyd --no-daemon
```

Then open Spotify on your phone or desktop, tap the device picker, and select your Spotifyd device once — this links it to your Spotify account. You'll grab the **Spotify Connect device ID** during the Backend step to put in `config.json`. Autostart on boot is set up later in the **User services** subsection at the end of this chapter.

### Cloning the repository

Clone the repository onto the Pi:

```bash
git clone https://github.com/einioville/Tesla-Homedash.git
cd Tesla-Homedash
```

The remaining subsections assume you're running commands from inside this directory unless noted otherwise.

### Spotify Developer App

The Spotify player authenticates as your own registered Spotify app — that's what provides the
`SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` used during the Backend step. Creating one is free
but requires a Spotify account (playback control additionally requires **Premium**).

1. Sign in at the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard) and click
   **Create app**.
2. Give it any name and description. For **Redirect URI**, enter exactly:

   ```
   http://127.0.0.1:8080/callback
   ```

   This must match `spotifyRedirectUri` in `config.json` (the default shown above). The OAuth helper
   in the Backend step sends you to this URL after you approve access.
3. Under **Which API/SDKs are you planning to use?**, tick **Web API**. The dashboard controls
   playback through the Web API; you do *not* need the Web Playback SDK, because Spotifyd is the actual
   playback device.
4. Save, then open the app's **Settings**. Copy the **Client ID** and reveal/copy the **Client
   secret** — these go into `.env` as `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` in the next step.

You can add more than one redirect URI later if you change `spotifyRedirectUri`; the value in
`config.json` and the value registered here must always match, or the OAuth handshake fails.

### Backend

The backend is a Python asyncio application managed with [uv](https://docs.astral.sh/uv/).

**1. Install uv:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Open a new shell (or `source ~/.bashrc`) so the `uv` binary is on your `PATH`.

**2. Install Python dependencies:**

```bash
cd backend
uv sync
cd ..
```

`uv sync` creates an isolated virtualenv under `backend/.venv` from `pyproject.toml` and `uv.lock`.

**3. Create `.env`** at the repo root with these keys:

```env
CONFIG_PATH=/absolute/path/to/Tesla-Homedash/config.json
VIN=<your-tesla-vin>
API_KEY=<your-teslemetry-access-token>
INFLUX_TOKEN=<from-the-influxdb-step>
SPOTIFY_CLIENT_ID=<from-the-spotify-developer-app>
SPOTIFY_CLIENT_SECRET=<from-the-spotify-developer-app>
```

- `API_KEY` is the Teslemetry access token from your [Teslemetry](https://teslemetry.com) account dashboard.
- `SPOTIFY_CLIENT_ID` and `SPOTIFY_CLIENT_SECRET` come from the app you registered at the [Spotify Developer Dashboard](https://developer.spotify.com/dashboard).

**4. Create `config.json`** from the template at the repo root (the real `config.json` is gitignored so it can carry your personal values):

```bash
cp config_template.json config.json
```

Open `config.json` and adjust the fields you'll typically need to change:

- `spotifyDeviceId` — leave blank for now; fill in during step 5.
- `spotifyCachePath` — absolute path where spotipy will store its OAuth refresh token (e.g. `/home/<your-user>/spotify_cache`).
- `spotifyRedirectUri` — defaults to `http://127.0.0.1:8080/callback`; must match whatever you registered as a redirect URI in the Spotify Developer App.
- `timeZone` — IANA timezone (e.g. `Europe/Helsinki`).
- `weatherPlace` — city the FMI feed should report for.

**5. Run the Spotify setup helper:**

The repo ships a guided helper that handles both the OAuth handshake and the Spotify Connect device ID lookup in one go. Make sure Spotifyd is already running and that you've picked it once from a Spotify client so it's registered with your account, then run the helper from the Pi's desktop (it needs to open a browser window):

```bash
cd backend
uv run python -m src.media_service.setup.spotify_setup
```

The helper opens the Spotify authorization page in your browser. After approving, paste the full redirect URL (`http://127.0.0.1:8080/callback?code=...`) back into the terminal — spotipy then writes the OAuth refresh token to `spotifyCachePath`.

> **The authorization is not permanent.** Since Spotify's
> [refresh-token expiration change](https://developer.spotify.com/blog/2026-06-18-refresh-token-expiration)
> (new apps 2026-06-18, existing apps 2026-07-20), a refresh token
> [lives 6 months](https://developer.spotify.com/documentation/web-api/tutorials/refreshing-tokens)
> and **refreshing it does not extend that** — after six months the token endpoint answers
> `invalid_grant` and Spotify playback stops until you re-authorize. You do not have to come back
> to this helper: the dashboard's **Asetukset → Media → Spotify-tunnistautuminen** card renews it
> on the device, and previously approved scopes carry over as long as the app asks for the same
> ones. The 1-hour `expires_in` in the cache file is the *access* token and is refreshed
> automatically — it is not the number that matters here.

Next the helper prompts you to start playback on the Spotifyd device. Once Spotify is playing on it, press Enter and the helper prints the active device's name and ID. Copy that ID into `spotifyDeviceId` in `config.json`.

**6. Start the backend:**

```bash
uv run python run.py
```

It should now connect to Teslemetry, InfluxDB, and Spotify without further prompts.

### Frontend

The frontend is a Qt 6 Quick (QML) application built with CMake. `scripts/build-frontend.sh` does
the configure and the build in one command — it finds the Qt kit, picks Ninja when it is installed
(and CMake's default generator otherwise), and reuses object files through `ccache`/`sccache` if
either is present.

**1. Build:**

```bash
./scripts/build-frontend.sh --config Release
```

It looks for a Qt kit in `$QTDIR`, then in `~/Qt/*/gcc_64` and `~/Qt/*/gcc_arm64`. If your
installer put it somewhere else, point at it explicitly:

```bash
./scripts/build-frontend.sh --config Release --qt-prefix ~/Qt/6.8.0/gcc_arm64
```

This produces the `appfrontend_v2` binary at `frontend_v2/build/appfrontend_v2`. (The equivalent
raw CMake invocation is `cmake -S frontend_v2 -B frontend_v2/build -DCMAKE_PREFIX_PATH=<kit>
-DCMAKE_BUILD_TYPE=Release && cmake --build frontend_v2/build --target appfrontend_v2`.)

**2. Run:**

The frontend reads a few optional environment variables — the defaults already match a 1280×800 embedded display on the same Pi as the backend:

Most of these only supply a *default* for the matching setting in the dashboard's own **Asetukset**
view — a value saved there wins, so they matter on a fresh install and stop mattering afterwards.

- `TESLA_HOMEDASH_BACKEND_HOST` — backend TCP host (default `127.0.0.1`). Set this if the backend runs on a different machine.
- `TESLA_HOMEDASH_BACKEND_PORT` — backend TCP port (default `6969`).
- `TESLA_HOMEDASH_FULLSCREEN` — set to `1` to open fullscreen on the touchscreen.
- `TESLA_HOMEDASH_SCREENSAVER_TIMEOUT_MIN` — idle minutes before the screensaver (default `30`).
- `TESLA_HOMEDASH_SETTINGS_FILE` — override where the dashboard's own settings are written (default `~/.config/Tesla-Homedash/frontend_config.json`).
- `TESLA_HOMEDASH_LOG_LEVEL` — `debug` / `info` / `warning` / `error` / `critical` (default `info`).

Make sure the backend is already running (`cd backend && uv run python run.py`), then launch the frontend:

```bash
TESLA_HOMEDASH_FULLSCREEN=1 ./frontend_v2/build/appfrontend_v2
```

If everything is wired up correctly, the dashboard appears and starts streaming telemetry, weather, and media data from the backend.

### User services

Running all three processes by hand every boot gets old fast. I let systemd **user**
services bring them up automatically: one for Spotifyd, one for the backend, and one for
the dashboard itself. They run under your own login (`systemctl --user`), so no `sudo` and
no system-wide units to manage.

The dashboard service launches the Qt app *on top of the normal Raspberry Pi OS desktop* —
it is **not** a kiosk that replaces the desktop. If the dashboard is closed or crashes, the
full desktop is still right there as a fallback, which makes maintenance over VNC or a
keyboard far less painful.

A note on start order, because it has one non-obvious wrinkle. InfluxDB runs as a **system**
service that already autostarts at boot (you enabled it back in the InfluxDB step), whereas
these three run as **user** services. systemd cannot order a user service against a system
service — an `After=influxdb.service` line in a user unit silently refers to a non-existent
unit and does nothing. The backend reads its daily/monthly baselines from InfluxDB at
startup; it tolerates InfluxDB being down (it degrades gracefully rather than crashing),
but its unit still waits for InfluxDB's HTTP endpoint to answer before launching (the
`ExecStartPre` line below) so those baselines are correct from the first boot instead of
only after the next reset. Spotifyd has no dependency on anything else and can come up
whenever. The dashboard waits
for the backend — both live in the same user instance, so there a plain `After=` *does*
work — and for the graphical session. Every unit also carries `Restart=on-failure`, so any
remaining start-up race simply resolves itself on the next retry.

First, let user services keep running even when you're not logged in interactively, so the
headless services (Spotifyd and the backend) start at boot:

```bash
loginctl enable-linger $USER
```

All three unit files live under `~/.config/systemd/user/`. Create that directory if it
doesn't exist:

```bash
mkdir -p ~/.config/systemd/user
```

**1. Spotifyd** — `~/.config/systemd/user/spotifyd.service`. This replaces the manual
`spotifyd --no-daemon` you ran earlier:

```ini
[Unit]
Description=Spotifyd (Spotify Connect target for Tesla-Homedash)

[Service]
ExecStart=/usr/local/bin/spotifyd --no-daemon
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

**2. Backend** — `~/.config/systemd/user/tesla-homedash-backend.service`. `%h` expands to
your home directory, so the paths below assume the repo was cloned to `~/Tesla-Homedash`
and uv installed to `~/.local/bin` (both per the earlier steps). The `ExecStartPre`
health-check polls InfluxDB's `/health` endpoint with `curl` (already on the system — you
used it to install uv) and only then launches the backend:

```ini
[Unit]
Description=Tesla-Homedash backend

[Service]
WorkingDirectory=%h/Tesla-Homedash/backend
# Wait (up to 60 s) for the system-level InfluxDB to answer before starting, so the
# daily/monthly baselines read correctly. The backend tolerates InfluxDB being down
# too, but waiting avoids a degraded first boot.
ExecStartPre=/bin/sh -c 'for i in $(seq 1 60); do curl -sf http://localhost:8086/health >/dev/null && exit 0; sleep 1; done; exit 1'
ExecStart=%h/.local/bin/uv run python run.py
# The backend switches the panel on and off for the Options view's screen-off
# setting, which goes through wlopm and therefore needs the compositor's socket.
# XDG_RUNTIME_DIR is already in a --user unit's environment; WAYLAND_DISPLAY is
# not, because this unit is wanted by default.target rather than
# graphical-session.target. Drop this line if you do not use that setting.
Environment=WAYLAND_DISPLAY=wayland-1
# The Options view's update card rebuilds the dashboard from source, and this
# unit is what runs that build. A --user unit inherits none of your login shell's
# environment, so point it at the Qt kit you installed. Drop this line only if
# the kit is in ~/Qt/<version>/gcc_arm64, which is found automatically.
Environment=QTDIR=%h/Qt/6.8.0/gcc_arm64
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

> **The Options view's restart button works with this unit as written.** Some settings
> (the timezone, the Zappi serial, the spot-pricing master switch) are consumed once when
> a service is constructed and cannot be re-applied in place, so the dashboard offers a
> *Käynnistä uudelleen* button. It makes the backend exit with code **42** — deliberately
> non-zero, so `Restart=on-failure` above brings it straight back up. Switch to
> `Restart=always` only if you also want a clean `systemctl --user stop` to relaunch.
>
> A bad value cannot restart-loop the unit: settings are validated against the schema
> before being written, and `config.json` is snapshotted to `config.json.bak` before every
> write — a config that fails to load rolls back to the backup on the next start.
>
> **`RestartSec=5` is load-bearing — do not remove it.** systemd gives up on a unit that
> starts more than `StartLimitBurst=5` times in `StartLimitIntervalSec=10s` and leaves it
> `failed`, recoverable only with `systemctl --user reset-failed`. At the default
> `RestartSec` of 100 ms a crash-looping process trips that in about two seconds; at 5 s it
> never can, so the unit keeps retrying and heals itself once the cause is fixed.

> **Screen-off (the Options view's *Näytön sammutus*) is unreliable on current Raspberry Pi
> OS.** It is off by default; two things break it:
>
> - **labwc 0.20 / wlroots 0.20** (Raspberry Pi OS since September 2026): after a long blank the
>   output can disappear from the compositor and never come back — the panel stays black whatever
>   you touch. Recover with `sudo systemctl restart lightdm` (the backend survives it). The backend
>   detects this, refuses further power-offs until it is restarted, and the Options view says why.
>   A plain `swayidle` + `wlopm` setup wedges the same way; it is not specific to this app.
> - **A running VNC server (wayvnc)** blocks `wlopm` in both directions, so the panel simply never
>   blanks. Stop the VNC server to use screen-off; the Options view reports the refusal.

**3. Frontend** — `~/.config/systemd/user/tesla-homedash-frontend.service`. This one is
tied to the graphical session (it needs the desktop's display), and it starts after the
backend so there's data to show:

```ini
[Unit]
Description=Tesla-Homedash dashboard (Qt frontend)
After=graphical-session.target tesla-homedash-backend.service
PartOf=graphical-session.target

[Service]
Environment=TESLA_HOMEDASH_FULLSCREEN=1
ExecStart=%h/Tesla-Homedash/frontend_v2/build/appfrontend_v2
Restart=on-failure
RestartSec=5

[Install]
WantedBy=graphical-session.target
```

> **`Restart=on-failure` is what makes the dashboard's own restart button work.** The
> Options view has an *Ylläpito* section with *Käynnistä sovellus uudelleen*, which quits the
> app with exit code **42** so this unit relaunches it. That is the only way to apply the
> connection settings (or recover a wedged UI) on the Pi, where the dashboard runs fullscreen
> with no keyboard. The same section restarts the backend, and both buttons need a second
> tap to confirm.

### Updating from the dashboard

Once both units are running, the **Asetukset → Ylläpito → Päivitys** card updates the
installation in place, so a release does not need an SSH session. It has two channels:

- **Kehitys** — track the tip of `origin/main`.
- **Julkaisut** — track the newest `v*` release tag.

Both resolve to a *commit*, and the card compares it against the one that is checked out —
so moving between channels works in both directions, including back to an older release.
Pressing the button (twice, to confirm) fetches, checks the target out detached, rebuilds the
frontend, runs `uv sync --locked` and restarts both units. It refuses to start if
the working tree has modified tracked files, if the host is missing `uv`, a Qt kit or disk
space, or if the target version does not itself contain the update card — that last one
would be a one-way trip on a panel with no keyboard. Anything that fails after the checkout
puts the working tree back where it started.

`config.json`, `.env` and the dashboard's own settings file are all outside the repository
or gitignored, so an update never touches them.

### Rebooting the device from the dashboard (Laitteen uudelleenkäynnistys)

**Asetukset → Ylläpito → Uudelleenkäynnistys → Käynnistä laite uudelleen** reboots the whole
Raspberry Pi (twice, to confirm; refused while an update is running). The backend runs as your
user, so the host has to grant that one right. Either of these works — the backend tries
`systemctl reboot` first, then `sudo -n systemctl reboot`, and never asks for a password:

- **A polkit rule** (preferred). Create `/etc/polkit-1/rules.d/50-tesla-homedash-reboot.rules`,
  replacing `pi` with your user:

  ```js
  polkit.addRule(function (action, subject) {
      if ((action.id == "org.freedesktop.login1.reboot" ||
           action.id == "org.freedesktop.login1.reboot-multiple-sessions") &&
          subject.user == "pi") {
          return polkit.Result.YES;
      }
  });
  ```

- **A sudoers entry** for exactly that command: `sudo visudo -f /etc/sudoers.d/tesla-homedash-reboot`
  and add `pi ALL=(root) NOPASSWD: /usr/bin/systemctl reboot`. (A user that already has
  passwordless sudo — Raspberry Pi OS's default first user — needs nothing.)

Without either, the button reports that the backend lacks the right, and nothing happens.

### Screensaver photos (Näytönsäästäjä)

The screensaver shows the photos in `~/.config/Tesla-Homedash/screensaver` (JPEG, PNG, BMP, WebP,
GIF — subfolders are not shown). The folder is created on the dashboard's first start. There are
two ways to fill it:

- **Over the network:** `scp *.jpg pi@<pi>:~/.config/Tesla-Homedash/screensaver/`
- **From a USB stick:** put the photos in a folder named `tesla_homedash_screensaver` in the root
  of the stick, plug it into the Pi and open **Asetukset → Yleinen → Näytönsäästäjä → Kuvakansio →
  Tuo USB:ltä**. Pick the stick, check the photo count, and import. The dashboard mounts the stick,
  copies the photos and unmounts it again. Photos already in the folder are skipped, and a different
  photo with a clashing name is saved as `name (2).jpg` rather than replacing anything.

The screensaver switch stays unavailable until the folder holds at least one photo.

The backend mounts the stick with `udisksctl` as your user. The desktop session may already mount
sticks on its own, in which case nothing more is needed. If the import instead reports that the
backend has no right to mount the stick, allow it with a polkit rule. Create
`/etc/polkit-1/rules.d/50-tesla-homedash-usb.rules`, replacing `pi` with your user:

```js
polkit.addRule(function (action, subject) {
    if ((action.id == "org.freedesktop.udisks2.filesystem-mount" ||
         action.id == "org.freedesktop.udisks2.filesystem-mount-other-seat") &&
        subject.user == "pi") {
        return polkit.Result.YES;
    }
});
```

Reload the unit files, then enable and start everything:

```bash
systemctl --user daemon-reload
systemctl --user enable --now spotifyd.service tesla-homedash-backend.service
systemctl --user enable --now tesla-homedash-frontend.service
```

Check that they came up:

```bash
systemctl --user status tesla-homedash-backend.service
```

Then reboot and confirm the dashboard launches on its own and the desktop is still
reachable underneath it.

> **If the dashboard doesn't start with the desktop:** some Wayland compositors don't
> activate `graphical-session.target` for the systemd user instance, so the frontend
> service never triggers. In that case, skip the frontend service and use a plain XDG
> autostart entry instead — a `.desktop` file the desktop session runs automatically when
> the graphical session loads. Create `~/.config/autostart/tesla-homedash.desktop`:
>
> ```ini
> [Desktop Entry]
> Type=Application
> Name=Tesla-Homedash
> Exec=env TESLA_HOMEDASH_FULLSCREEN=1 /home/youruser/Tesla-Homedash/frontend_v2/build/appfrontend_v2
> ```
>
> (Replace `youruser` with your username.) The desktop session runs it on login, which
> also keeps the full desktop as a backup. Spotifyd and the backend still run as the
> systemd user services above.
