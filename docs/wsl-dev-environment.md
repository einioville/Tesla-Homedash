# Developing Tesla-Homedash in WSL

> Setup guide for moving the development environment from native Windows to WSL2.
> Written 2026-08-28, from the state of `feature/settings-options-view`.
>
> **Why bother:** the dashboard ships to a Raspberry Pi running Linux. Developing on
> Linux means the same Qt platform plugins, the same libVLC, the same POSIX paths and
> the same systemd units you deploy with — so "works on my machine" and "works on the
> Pi" stop being different questions. The only remaining gaps to the Pi are the CPU
> architecture (x86-64 vs aarch64) and the touchscreen.

> [!IMPORTANT]
> **This document supersedes the README's Setup chapter for development.** That chapter
> was written for the original Qt **Widgets** frontend in `frontend/`, which is frozen
> and end-of-life. Its Qt module list (`Widgets`, `QuickWidgets`), its build commands
> (`cmake -S frontend -B frontend/builddir`, producing `gui`) and its run instructions
> all describe the wrong target. **All current work is `frontend_v2/`** — a QML
> application with a different module set and a different binary. Everything below is
> written against `frontend_v2` and the services as they exist on this branch, and is
> self-contained: you should not need to cross-reference the README to follow it.

---

## 0. TL;DR — the five things that actually matter

1. **Clone into the WSL filesystem (`~/dev/Tesla-Homedash`), never `/mnt/p/`.** Building
   over the 9p mount is an order of magnitude slower and it fights you over line endings.
2. **Qt must be ≥ 6.11** — `frontend_v2/CMakeLists.txt` says so, and apt's Qt6 is far
   older. Use `aqtinstall`.
3. **`.env` and `config.json` are gitignored** — they do *not* arrive with `git pull`.
   Copy them by hand and rewrite the Windows paths inside them.
4. **`sudo apt install python-is-python3`**, or Claude Code's edit hook fails on every edit.
5. **Run the whole stack inside WSL** (InfluxDB included). Then `127.0.0.1:6969` and
   `localhost:8086` just work, exactly as on the Pi.

---

## 1. What changes, tool by tool

| Concern | Windows today | WSL equivalent |
|---|---|---|
| Compiler | MSVC 2022 (`vcvars64.bat` via `vswhere`) | `g++` from `build-essential` (C++20 — GCC 13 on 24.04 is fine) |
| Qt kit | `D:\Qt\6.11.1\msvc2022_64` | `~/Qt/6.11.1/gcc_64` (`aqt` or the online installer) |
| Frontend build | `scripts\build-frontend.ps1` | `scripts/build-frontend.sh` — **does not exist yet**, see §7 |
| Compiler cache | `sccache` | `ccache` (`apt install ccache`) — `CMakeLists.txt` already probes for both |
| Binary | `frontend_v2\build\appfrontend_v2.exe` | `frontend_v2/build/appfrontend_v2` |
| Display | native window | WSLg (Wayland/X11 forwarded to Windows automatically) |
| Backend runner | `uv run python run.py` | identical |
| InfluxDB | Windows service on `:8086` | `influxdb` apt package under WSL systemd |
| Spotify Connect target | Spotify desktop app | `spotifyd` (x86-64 build) on WSLg's PulseAudio |
| Session scripts | `new-session.ps1` / `finish-session.ps1` | not ported — plain `git worktree` (rarely needed, CLAUDE.md §8) |

Everything else — `uv`, `git`, `gh`, the Python source, the QML — is unchanged.

---

## 2. WSL itself

### 2.1 Install

From an elevated PowerShell on Windows:

```powershell
wsl --install -d Ubuntu-24.04
wsl --update
```

Ubuntu 24.04 LTS is the recommendation: it is the closest mainstream match to Raspberry
Pi OS Bookworm's toolchain generation, and it has current InfluxDB packages.

### 2.2 Enable systemd

InfluxDB — and optionally backend/frontend units mirroring the Pi's — want systemd.
Inside WSL:

```bash
sudo tee /etc/wsl.conf >/dev/null <<'WSLCONF'
[boot]
systemd=true

[interop]
appendWindowsPath=true
WSLCONF
```

Then from Windows run `wsl --shutdown` and reopen the distro. Verify with
`systemctl is-system-running` (`running` or `degraded` are both fine).

> `appendWindowsPath=true` keeps Windows executables reachable from WSL. It also means
> a bare `python` could resolve to a Windows Python via the App Execution Alias —
> §9.1 covers why that specifically matters for the Claude Code hook.

### 2.3 Optional: `.wslconfig` tuning

On the Windows side, `C:\Users\ville\.wslconfig`:

```ini
[wsl2]
memory=8GB
processors=8
networkingMode=mirrored
```

`networkingMode=mirrored` (Windows 11 22H2+) makes `localhost` mean the same thing in
both Windows and WSL. You only need it if you keep some service on the Windows side —
follow §5 and run everything inside WSL and you can leave it out.

### 2.4 Put the repo on ext4 — this is not optional advice

```bash
mkdir -p ~/dev && cd ~/dev
git clone https://github.com/einioville/Tesla-Homedash.git
cd Tesla-Homedash
git checkout feature/settings-options-view
```

Do **not** work out of `/mnt/p/Tesla-Homedash`. Two independent reasons:

- **Speed.** Every file stat crosses the 9p protocol boundary. CMake configure,
  `git status`, ripgrep and Ninja's dependency scan all slow down noticeably; a full
  frontend rebuild is the worst case.
- **Line endings.** Windows git has `core.autocrlf=true` globally, so `P:\` holds CRLF
  working-tree files while the repository stores LF. WSL git defaults to
  `autocrlf=false`; pointed at that same directory it would report *every text file as
  modified*. A separate clone on ext4 checks out clean LF and sidesteps this entirely.
  (The repo has no `.gitattributes`, so nothing overrides this per file.)

---

## 3. System packages

```bash
sudo apt update
sudo apt install -y \
    build-essential cmake ninja-build ccache git curl \
    python3 python3-pip python-is-python3 \
    vlc \
    libgl1 libegl1 libfontconfig1 libdbus-1-3 libxkbcommon-x11-0 \
    libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
    libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-sync1 \
    libxcb-xfixes0 libxcb-xinerama0 libxcb-xkb1
```

Why each group:

- **`build-essential cmake ninja-build`** — the frontend toolchain. `ccache` is picked
  up automatically by the compiler-cache block in `frontend_v2/CMakeLists.txt` (it
  probes for `sccache` *or* `ccache`), so object reuse across rebuilds keeps working.
- **`python-is-python3`** — provides `/usr/bin/python`. Claude Code's `PostToolUse`
  hook is registered as `python "${CLAUDE_PROJECT_DIR}/.claude/hooks/check-edit.py"`,
  and Ubuntu ships only `python3`. Without this the hook errors on every Edit/Write.
- **`vlc`** — `python-vlc` is only a binding; `radio_player.py` is silent without the
  libVLC runtime. WSLg provides a PulseAudio server, so radio audio really does come
  out of your Windows speakers.
- **the `libxcb-*` / `libxkbcommon-x11-0` block** — Qt's `xcb` platform plugin links
  these at runtime, and Qt does *not* pull them in as package dependencies because you
  install Qt outside apt. Missing any one of them produces the classic and thoroughly
  unhelpful `qt.qpa.plugin: Could not load the Qt platform plugin "xcb"`.

Note there is no `qt6-*` package in that list, deliberately — see the next section.

---

## 4. Qt 6.11 (for `frontend_v2`)

**apt cannot be used.** `frontend_v2/CMakeLists.txt` declares
`qt_standard_project_setup(REQUIRES 6.11)`, while Ubuntu 24.04 packages Qt 6.4.x. The
project also needs **Qt Graphs**, which is not in Ubuntu's archives at all.

### 4.1 The modules `frontend_v2` actually needs

Taken from the `find_package` line in `frontend_v2/CMakeLists.txt` — note this differs
from the README's list, which describes the old Widgets frontend:

```cmake
find_package(Qt6 REQUIRED COMPONENTS
    Quick Network Concurrent Svg Location Positioning
    QuickControls2 Core5Compat Graphs LabsFolderListModel)
```

| CMake component | Comes from | Used by |
|---|---|---|
| `Quick`, `QuickControls2` | base install (qtdeclarative) | the whole QML UI |
| `LabsFolderListModel` | base install (qtdeclarative) | screensaver photo enumeration |
| `Network`, `Concurrent` | base install (qtbase) | `ServerClient`, off-thread image decode |
| `Svg` | base install (qtsvg) | every icon in `resources/icons/` |
| `Location`, `Positioning` | `-m qtlocation qtpositioning` | `TeslaMap`, `TripMap` |
| `Graphs` | `-m qtgraphs` | `HistoryGraph`, trip + charging graphs |
| `Core5Compat` | `-m qt5compat` | retained Qt5 APIs in `core/` |

`Widgets` and `QuickWidgets` are **not** needed — those belong to the frozen
`frontend/`. If you ever build that one too, add them.

### 4.2 Recommended: `aqtinstall` (scripted, no Qt account)

```bash
python3 -m pip install --user aqtinstall     # or: pipx install aqtinstall
python3 -m aqt install-qt linux desktop 6.11.1 linux_gcc_64 \
    -m qtlocation qtpositioning qtgraphs qt5compat qtwayland \
    -O ~/Qt
```

That lands the kit at `~/Qt/6.11.1/gcc_64`. Match the Windows side's **6.11.1** so both
environments compile against the same Qt.

`qtwayland` is not a CMake component — it supplies the Wayland *platform plugin* so the
app renders natively under WSLg instead of falling back to X11. If a CMake configure
ever reports a missing Qt6 component, re-run `aqt` with that module appended to `-m`.

### 4.3 Alternative: the official online installer

Pick Qt **6.11.1** and tick **Qt Location**, **Qt Positioning** and **Qt Graphs** under
Additional Libraries. Needs a free Qt account and a GUI (WSLg provides one). Slower,
but it also gives you Qt Creator, the debugger and the QML profiler.

### 4.4 Make the kit discoverable

```bash
echo 'export QTDIR=$HOME/Qt/6.11.1/gcc_64'  >> ~/.bashrc
echo 'export PATH=$QTDIR/bin:$PATH'         >> ~/.bashrc
echo 'export CMAKE_PREFIX_PATH=$QTDIR'      >> ~/.bashrc
source ~/.bashrc
qmake6 --version    # sanity check → 6.11.1
```

---

## 5. Services

Run all three inside WSL. The backend defaults (`localhost:8086` for InfluxDB,
`0.0.0.0:6969` for the TCP server) then need no configuration at all — which is also
exactly how they run on the Pi.

### 5.1 InfluxDB 2.x

Install from InfluxData's apt repository per the current
[InfluxDB Linux install guide](https://docs.influxdata.com/influxdb/v2/install/?t=Linux),
then:

```bash
sudo systemctl enable --now influxdb
systemctl status influxdb --no-pager
```

Open `http://localhost:8086` **in your Windows browser** (WSLg forwards it) and complete
the setup wizard, creating:

- **Organization**: `Tesla-Homedash`
- **Bucket**: `data`

Then under **Load Data → API Tokens** generate an All-Access token (or scope one to the
`data` bucket) — it becomes `INFLUX_TOKEN` in `.env`. The backend hardcodes
`http://localhost:8086` with org `Tesla-Homedash` and bucket `data`, so those three
names must match exactly.

> **You will start with an empty database.** The Windows instance's history does not
> come along. While developing that means: the History view has no data, `DrivenToday`
> / `DrivenThisMonth` baselines read zero, and the Trips and Charging views are empty
> until the backend has been logging a while. Nothing *requires* history — every read
> path in `influxdb_handler.py` degrades to `None` / `status=0` — so an empty start is
> safe, just visually bare. For continuity, export and replay:
>
> ```bash
> # on Windows
> influx query 'from(bucket:"data") |> range(start:-90d)' --raw > tesla_data.csv
> # in WSL
> influx write --bucket data --file tesla_data.csv
> ```

### 5.2 Spotifyd

Spotifyd makes the machine a Spotify Connect target; `spotify_player.py` then detects
playback on it and claims the media card. Take the **x86-64** release asset:

```bash
cd /tmp
wget https://github.com/Spotifyd/spotifyd/releases/latest/download/spotifyd-linux-x86_64-full.tar.gz
tar -xzf spotifyd-linux-x86_64-full.tar.gz
sudo mv spotifyd /usr/local/bin/
```

Create `~/.config/spotifyd/spotifyd.conf`:

```toml
[global]

device_name = "Tesla-Homedash-WSL"
device_type = "speaker"
cache_path = "~/spotifyd_cache"
max_cache_size = 2000000000
backend = "pulseaudio"
bitrate = 320
```

The `-full` asset includes the PulseAudio backend, and WSLg runs a PulseAudio server,
so audio works unchanged. Start it with `spotifyd --no-daemon`, then pick the device
once from a Spotify client so it registers with your account.

Because this is a *new* Connect device, its ID differs from the one in your current
`config.json`. Get the new one:

```bash
cd backend && uv run python -m src.media_service.setup.spotify_setup
```

and paste it into `spotifyDeviceId`. If that ID is wrong the media controls silently
no-op — there is no error, the `_current_device_id` vs `_target_device_id` comparison
simply never matches.

### 5.3 The backend

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
source ~/.bashrc
cd backend && uv sync && cd ..
```

`uv.lock` is cross-platform, so this resolves the same dependency versions as Windows.
Run it with `cd backend && uv run python run.py`.

Services constructed at startup, as of this branch: telemetry, the TCP server, media
(radio + Spotify), weather, trips, charging, spot price, `config_service` (new — the
Options view's backend half), and myenergi *only if* `MYENERGI_HUB_SERIAL` /
`MYENERGI_API_KEY` are set. Missing myenergi credentials are fine — that service is
skipped and the rest of the stack runs.

---

## 6. The two gitignored files

`git pull` will **not** bring these. Copy them from the Windows checkout, then edit —
they contain absolute Windows paths that are meaningless in WSL.

```bash
cp /mnt/p/Tesla-Homedash/.env         ~/dev/Tesla-Homedash/.env
cp /mnt/p/Tesla-Homedash/config.json  ~/dev/Tesla-Homedash/config.json
```

### 6.1 `.env` — three values to rewrite

| Key | Windows value today | WSL value |
|---|---|---|
| `CONFIG_PATH` | `P:\Tesla-Homedash\config.json` | `/home/<you>/dev/Tesla-Homedash/config.json` |
| `TESLA_HOMEDASH_SCREENSAVER_DIR` | `E:/Luna` | `/mnt/e/Luna`, or copy the photos into WSL |
| `INFLUX_TOKEN` | Windows InfluxDB token | the new token from §5.1 |

The secrets — `API_KEY`, `VIN`, `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`,
`MYENERGI_HUB_SERIAL`, `MYENERGI_API_KEY`, `TESLA_HOMEDASH_MAP_API_KEY` — carry over
unchanged. `start_services.main()` fails fast if any required key is missing, so a
half-copied `.env` surfaces immediately rather than at first use.

> The screensaver directory may stay on `/mnt/e` — it is read once per slide, not in a
> hot loop, so 9p latency is irrelevant there. Only the *build tree* must live on ext4.

### 6.2 `config.json` — one path to rewrite

`spotifyCachePath` is currently `P:\\Tesla-Homedash\\backend\\src\\media_service\\.cache`.
Point it at a POSIX path such as `/home/<you>/.cache/tesla-homedash/spotify`. Also
update `spotifyDeviceId` per §5.2.

> As of this branch `config.json` is **written at runtime** by the new `config_service`
> (the Options view): it snapshots to `config.json.bak`, then writes atomically via a
> temp file plus `os.replace`. Nothing there is Windows-specific — `os.replace` is
> atomic on both platforms — but it does mean the live file can drift from
> `config_template.json`, so copy the live file rather than regenerating from the
> template.

---

## 7. Building `frontend_v2`

There is no Linux counterpart to `scripts/build-frontend.ps1` yet — that script is MSVC
specific end to end (`vswhere`, `vcvars64.bat`, `D:\Qt` kit globbing). Writing one is
the natural first task of the first WSL session. It is deliberately not written from
Windows: it cannot be tested here, and an untested build script is worse than none.

### 7.1 Manual build — works immediately

```bash
cd ~/dev/Tesla-Homedash
cmake -S frontend_v2 -B frontend_v2/build -G Ninja \
      -DCMAKE_PREFIX_PATH="$QTDIR" -DCMAKE_BUILD_TYPE=Debug
cmake --build frontend_v2/build --target appfrontend_v2
./frontend_v2/build/appfrontend_v2
```

There is no MSVC environment to import — GCC is already on `PATH` — which is why the
Linux script below is a third the length of the PowerShell one.

### 7.2 `scripts/build-frontend.sh` — create this on the WSL side

```bash
#!/usr/bin/env bash
# Configure + build (and optionally run) frontend_v2. Linux counterpart of
# scripts/build-frontend.ps1 — no MSVC environment to import, so it is mostly
# kit detection plus the same Ninja configure + build.
set -euo pipefail

CONFIG=Debug
RUN=0
FULLSCREEN=0
CLEAN=0
QT_PREFIX="${QTDIR:-}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        -c|--config)     CONFIG="$2"; shift 2 ;;
        -q|--qt-prefix)  QT_PREFIX="$2"; shift 2 ;;
        -r|--run)        RUN=1; shift ;;
        -f|--fullscreen) FULLSCREEN=1; shift ;;
        --clean)         CLEAN=1; shift ;;
        *) echo "unknown option: $1" >&2; exit 1 ;;
    esac
done

REPO_ROOT="$(git rev-parse --show-toplevel)"
SRC="$REPO_ROOT/frontend_v2"
BUILD="$SRC/build"
[[ -f "$SRC/CMakeLists.txt" ]] || { echo "No frontend_v2/CMakeLists.txt under $REPO_ROOT" >&2; exit 1; }

# Newest ~/Qt/6.*/gcc_64 unless QTDIR or --qt-prefix says otherwise.
if [[ -z "$QT_PREFIX" ]]; then
    QT_PREFIX="$(find "$HOME/Qt" -maxdepth 2 -type d -name gcc_64 2>/dev/null | sort -V | tail -1)"
fi
[[ -n "$QT_PREFIX" ]] || { echo "No Qt kit found; pass --qt-prefix or export QTDIR." >&2; exit 1; }
echo "Qt kit:  $QT_PREFIX"

(( CLEAN )) && rm -rf "$BUILD"

cmake -S "$SRC" -B "$BUILD" -G Ninja \
      -DCMAKE_PREFIX_PATH="$QT_PREFIX" \
      -DCMAKE_BUILD_TYPE="$CONFIG"
cmake --build "$BUILD" --target appfrontend_v2

EXE="$BUILD/appfrontend_v2"
echo "Build OK -> $EXE"
command -v ccache >/dev/null && ccache --show-stats | head -5 || true

if (( RUN )); then
    (( FULLSCREEN )) && export TESLA_HOMEDASH_FULLSCREEN=1
    exec "$EXE"
fi
```

```bash
chmod +x scripts/build-frontend.sh
./scripts/build-frontend.sh --run
```

Per CLAUDE.md §7.3 the agent runs this after frontend changes; you run the binary.

---

## 8. Running the GUI under WSLg

WSLg gives WSL2 a Wayland compositor and an X server whose windows appear as ordinary
Windows windows. No VcXsrv, no `DISPLAY` juggling. The app opens at its configured
1280×800.

```bash
./frontend_v2/build/appfrontend_v2
TESLA_HOMEDASH_FULLSCREEN=1 ./frontend_v2/build/appfrontend_v2   # fullscreen test
```

Runtime environment variables (all optional, read via `Settings` → `AppConfig`):
`TESLA_HOMEDASH_BACKEND_HOST` / `_PORT`, `_WINDOW_WIDTH` / `_HEIGHT`, `_FULLSCREEN`,
`_LOG_LEVEL`, `_SETTINGS_FILE`, `_SCREENSAVER_DIR` / `_SCREENSAVER_TIMEOUT_MIN`.
Precedence on this branch is `schema default < env/.env < saved user override`, so a
setting you change in the Asetukset view wins over `.env` from then on.

### Troubleshooting, in the order things usually break

| Symptom | Cause / fix |
|---|---|
| `Could not load the Qt platform plugin "xcb"` | A missing `libxcb-*` from §3. Diagnose precisely with `QT_DEBUG_PLUGINS=1`. |
| Window never appears, no error | Force a platform: `QT_QPA_PLATFORM=wayland` or `=xcb`. Wayland needs the `qtwayland` module from §4.2. |
| Black or garbled QML, GPU crashes | WSLg's OpenGL goes through Mesa's d3d12 driver. Fall back with `LIBGL_ALWAYS_SOFTWARE=1`, or `QSG_RHI_BACKEND=software` for Qt Quick specifically. Slower, but it renders. |
| Map tiles blank | Qt Location networking, not WSL — check `TESLA_HOMEDASH_MAP_API_KEY` and connectivity. |
| No radio audio | libVLC present? WSLg PulseAudio running? `pactl info` should answer. |
| Frontend connects to nothing | Backend running in the *same* WSL distro? `ss -ltnp \| grep 6969`. |

The map, the `Graphs` history view and the screensaver are the three surfaces worth
eyeballing after the first successful build — they are the GPU-heaviest and the most
likely to expose a WSLg rendering difference from the Pi.

---

## 9. Claude Code in WSL

Install inside the distro (not the Windows copy reaching across), so it sees POSIX
paths and the Linux toolchain:

```bash
curl -fsSL https://claude.ai/install.sh | bash
cd ~/dev/Tesla-Homedash && claude
```

### 9.1 The edit hook — the one thing that will bite you

`.claude/settings.json` (committed) registers:

```json
"command": "python \"${CLAUDE_PROJECT_DIR}/.claude/hooks/check-edit.py\""
```

Two failure modes on a fresh Ubuntu:

1. **No `python` at all** → the hook fails on every Edit/Write. Fixed by
   `python-is-python3` in §3.
2. **`python` resolves to the *Windows* Python** via the App Execution Alias, because
   `appendWindowsPath=true` puts Windows directories on `PATH`. Then a Windows
   interpreter tries to byte-compile a Linux path and fails confusingly. Check with
   `which python` — it must print `/usr/bin/python`. Installing `python-is-python3`
   puts `/usr/bin` ahead of the Windows entries and resolves this too.

### 9.2 The QML half of the hook skips silently

`check-edit.py` looks for qmllint at `QT_ROOTS = ("D:/Qt", "C:/Qt")` using the glob
`*/msvc2022_64/bin/qmllint.exe` — Windows-only, both of them. In WSL it finds nothing
and, by design, **skips the check rather than blocking edits**. You lose QML syntax
validation with no message saying so.

Re-enable it with no code change — the hook honours an explicit override:

```bash
echo 'export TESLA_HOMEDASH_QMLLINT=$QTDIR/bin/qmllint' >> ~/.bashrc
```

Teaching `find_qmllint()` about `~/Qt/*/gcc_64/bin/qmllint` is a good small first commit
from WSL, but the environment variable works today.

### 9.3 Permissions

`.claude/settings.json` allow-lists the PowerShell build invocation:

```
"Bash(powershell -ExecutionPolicy Bypass -File scripts/build-frontend.ps1 *)"
```

which never matches in WSL. Once §7.2's script exists, add its Linux siblings:

```
"Bash(scripts/build-frontend.sh *)",
"Bash(./scripts/build-frontend.sh *)",
"Bash(cmake:*)"
```

`.claude/settings.local.json` is per-machine and unversioned, so the WSL side starts
with its own — including `outputStyle`.

### 9.4 Git and gh identity

Neither `~/.gitconfig` nor the `gh` auth token crosses into WSL:

```bash
git config --global user.name  "Hanzanka"
git config --global user.email "ville.einio@gmail.com"
git config --global core.autocrlf false     # correct on Linux; do NOT copy true from Windows
gh auth login
```

`core.autocrlf false` is the Linux default and the right value — the repository stores
LF, and the Windows-side `true` exists only to hand CRLF to Windows editors.

### 9.5 Memory directory

Claude Code's project-memory store is keyed by working directory, so the WSL checkout
gets a **fresh, empty** one — the Windows store at
`C:\Users\ville\.claude\projects\P--Tesla-Homedash\memory\` does not follow. Copy it if
you want the accumulated context (`MEMORY.md` plus the individual memory files).
Confirm the exact destination directory name from a running WSL session rather than
guessing the slug — Claude Code derives it from the working directory path.

---

## 10. Windows-only leftovers

Not blockers, listed so they don't surprise you:

| File | Status in WSL | Action |
|---|---|---|
| `scripts/build-frontend.ps1` / `.cmd` | unusable | keep for the Windows box; add `build-frontend.sh` (§7.2) |
| `scripts/new-session.ps1`, `finish-session.ps1` | unusable | port only if you actually use worktrees — per CLAUDE.md §8 the default is the main checkout |
| `.claude/hooks/check-edit.py` | Python check works; QML check skips | `TESLA_HOMEDASH_QMLLINT` now, patch `QT_ROOTS` later |
| `CLAUDE.md` §3.2, §8 | describe MSVC / Ninja / PowerShell only | update once the Linux flow is proven (§7.6 requires it) |
| `README.md` Setup chapter | describes the **frozen Widgets `frontend/`** | out of date for development; this document replaces it |
| `frontend/` (Qt Widgets) | builds on Linux, but frozen | ignore — all work is `frontend_v2` |

---

## 11. Verification checklist

You are fully migrated when all of these pass in WSL:

```bash
# 1. toolchain
which python && python --version          # /usr/bin/python, 3.x
cmake --version && ninja --version && g++ --version
qmake6 --version                          # 6.11.1

# 2. backend syntax gate (CLAUDE.md §3.3)
cd ~/dev/Tesla-Homedash && python -m compileall backend/src

# 3. backend deps + run
cd backend && uv sync && uv run python run.py
#    expect: telemetry connected, InfluxDB reachable, no missing-env fail-fast

# 4. frontend build
cd ~/dev/Tesla-Homedash
cmake -S frontend_v2 -B frontend_v2/build -G Ninja -DCMAKE_PREFIX_PATH="$QTDIR"
cmake --build frontend_v2/build --target appfrontend_v2

# 5. frontend run — window appears, dock shows 7 entries including Asetukset
./frontend_v2/build/appfrontend_v2

# 6. the round trip this branch is about:
#    Asetukset → change a backend setting → toast confirms → config.json updated
```

Step 6 is the real end-to-end test for `feature/settings-options-view`: it exercises
`CONFIG_GET_SCHEMA` → `CONFIG_SET` → `Config.save()` → apply hook → `CONFIG_SET_RESULT`,
spanning both halves of the stack plus the new atomic-write path.

---

## 12. Continuing the settings branch

The branch is pushed with the full Options-view work committed. On the WSL side:

```bash
cd ~/dev/Tesla-Homedash
git fetch origin
git checkout feature/settings-options-view
```

What is outstanding on it: the Options view **compiles but has never been runtime
verified** — it has not been exercised against a live backend. Work through §11 step 6
first, then per CLAUDE.md §7.5 commit and open the PR. Related deferred work is tracked
as **issue #29** (editing the `tesla data` / `calculated tesla data` tables, which must
stay in lockstep with the frontend registry and the `0x71` wire format).
