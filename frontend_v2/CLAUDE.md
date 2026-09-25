# `frontend_v2/` — the QML frontend (live target)

The production dashboard: Qt 6.11 Quick/QML over a C++20 core, built with
`scripts/build-frontend.sh` / `.ps1` (root `CLAUDE.md` §3.2). All feature work happens here;
`frontend/` is the frozen Widgets predecessor. The root `CLAUDE.md` is always loaded alongside this
file, so nothing here repeats it.

## Layout

```
Main.qml        # the window: view host, dock, app-level overlays (see z-order below)
main.cpp        # construction order matters — Settings before AppConfig (core/CLAUDE.md)
app/            # Theme.qml (design tokens + the settings façade), ViewController.qml
config/         # settings.json (bundled Options-view schema), notifications.json
core/           # C++: ServerClient, protocol.hh, Logger, AppConfig, dotenv, the QML singletons
  tesla/ media/ weather/ charging/ trip/ notification/   # per-domain data models
items/          # QML components by domain (charging history luna media settings tesla trip util weather)
views/          # one screen per dock entry: Dashboard Map Media History Trips Charging Settings
resources/      # fonts, icons, styles, Luna
```

## Where the detailed notes live

| Working on | Read |
|---|---|
| A `core/` singleton — `Settings`, `Probe`, `Display`, `System`, `SpotifyAuth`, `SpotifyDevice`, `Updater` | `core/CLAUDE.md` |
| The Options view's QML — layout, schema keys, delegates, status widgets, folder picker | `items/settings/CLAUDE.md` |
| The map — `items/tesla/TeslaMap.qml` (full-screen in `views/MapView.qml`; `items/trip/TripMap.qml` shares its gesture handlers) | `items/tesla/CLAUDE.md` |
| `items/util/ScreenSaver.qml` | `items/util/CLAUDE.md` |
| The wire format of anything `ServerClient` parses | `backend/src/utils/CLAUDE.md` |

A feature that spans C++ and QML is documented once, beside the file holding most of its
load-bearing facts, with a pointer from the other side. Add new notes the same way.

## Settings file and environment variables

All optional; defaults match the embedded target.
- `TESLA_HOMEDASH_BACKEND_HOST` (default `127.0.0.1`)
- `TESLA_HOMEDASH_BACKEND_PORT` (default `6969`)
- `TESLA_HOMEDASH_WINDOW_WIDTH` / `_HEIGHT` (default `1280` / `800`)
- `TESLA_HOMEDASH_FULLSCREEN` — `1`/`true`/`yes` for fullscreen (default off). Fullscreen skips the
  fixed-size lock; windowed mode locks to the configured size. **In `frontend_v2` this is the
  `fullscreen` SETTING's env default**, not a variable `AppConfig` reads — so a saved override in
  the Options view beats it, per the usual `schema default < env/.env < saved override` precedence.
  It did nothing at all until the setting existed: `Main.qml` was a hard-locked 1280×800 window and
  `scripts/build-frontend.sh --fullscreen` exported the variable to a binary that ignored it.
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

## `app/Theme.qml` — the settings façade

Tokens that are user-tunable are bound (`readonly property bool
lunaEnabled: Settings.values.lunaEnabled`) instead of being literals; everything else stays a
`readonly` literal that qmlcachegen AOT-compiles. A property initialiser is a *binding*, so all ~236
existing `Theme.x` call sites across 38 files keep working unchanged and gain live updates for free.
**Add a tunable = one schema entry + one Theme binding**, no call-site edits.

## Fullscreen

Fullscreen is the local `fullscreen` setting (`general` → *Näyttö*), read straight from
`Settings.values` by `Main.qml` rather than through `Theme` — it is a window mode, not a design
token. Two things hang off it. The **size lock is released in fullscreen** (`minimumWidth ==
maximumWidth == 1280` otherwise): the compositor cannot size a surface whose min and max are pinned.
And the window **steps back to windowed for the duration of a Spotify re-authorization**
(`SpotifyAuth.phase !== "idle"`), because the consent page opens in the host's own browser and must
be reachable above the dashboard — on labwc, Raspberry Pi OS Bookworm's compositor, squeekboard is
hardcoded to the `top` layer and does not draw over a fullscreen surface (labwc#2926), so a
fullscreen dashboard would leave the on-screen keyboard unreachable and the login untypeable on a
keyboard-less panel. (The app's own keyboard, below, cannot help there: the browser is a separate
window.)

## On-screen keyboard

Qt Virtual Keyboard, drawn **inside the app window** (`InputPanel` in `Main.qml`) rather than the
host's squeekboard, which cannot draw over a fullscreen surface on labwc (above). `main.cpp` forces
`QT_IM_MODULE=qtvirtualkeyboard` before the `QGuiApplication` is built — forced, not defaulted, so an
inherited value can never leave the fields untypeable on the device. `VirtualKeyboard` is a
`REQUIRED` CMake component, so every kit (Windows, WSL, the Pi's) needs the Qt Virtual Keyboard
module installed. The only locale is `fi_FI`, which drops the language-switch key.

- **It shows itself** whenever a text field takes focus; nothing opens it explicitly.
- **Closing it commits.** `Main.qml`'s `dismissKeyboard()` moves focus off the field, which fires
  its `editingFinished`; `Qt.inputMethod.hide()` alone would close the panel and strand the edit in
  a field nobody can see. It runs on a press outside the field, on a view switch (the views stay
  resident, so focus would too) and when the screensaver comes on.
- **Outside-press detection is a `MouseArea` that never accepts the press**, ending at the
  keyboard's top edge, so the press still reaches the button or field under it (and a drag still
  scrolls — the keyboard just goes first). A passive-grab `TapHandler` would be the natural fit
  (dismiss on tap, not press) but in Qt 6.11 it still accepts a *mouse* press and starves every item
  beneath it (QTBUG-145896); the touch half of that fix may be missing from the Pi's 6.10.
- **Enter closes it too, but keeps focus** (`onAccepted: Qt.inputMethod.hide()` in the field
  delegates). Clearing focus there would emit `editingFinished` a second time and send the write
  twice. Tapping the still-focused field reopens it.
- The settings pane makes room and scrolls the focused field above it — `items/settings/CLAUDE.md`.

## Overlays, z-order and the dock

- **A modal inside a view cannot cover the dock.** The dock lives in `Main.qml` and is declared
  *after* the view host, so it floats over the whole view whatever `z` the modal sets — `z` orders
  siblings within one parent only — and a scrim's tap-swallowing `MouseArea` is equally powerless
  against it. The reveal handler sits above the views too, so the dock can be swiped up at any
  moment. On the 1280×800 target it occupies **y 684–780**: a tall modal must be anchored and sized
  to end above that band, or its buttons land under the dock (`items/settings/CLAUDE.md`, folder
  browser, is the measured case).
- **App-level layers in `Main.qml`:** notifications z:200, the Spotify re-auth prompt z:250 and its
  progress dialog z:260, the update banner z:270, the keyboard's outside-press catcher z:280 and the
  keyboard itself z:290, the screensaver z:300. Something that must be seen
  whichever view is current belongs here, not inside a view.

## QML ↔ C++ traps

- **A `Q_INVOKABLE` registers no property dependency**, so a binding built on one never
  re-evaluates. Read a `Q_PROPERTY` (or index into one) instead — `core/CLAUDE.md` records the
  `Updater` card that froze this way, and `Settings.valuesRevision` exists for the same reason.
- `QT_QML_GENERATE_QMLLS_INI` is **deprecated since Qt 6.10** ("no replacement needed") — don't add
  it to `CMakeLists.txt`.

## Logging (`core/logger.{hh,cpp}`)

- Format is byte-identical to the backend; stdout only, no files/rotation.
- Each `.cpp` gets a file-local `const Logger logger = Logger::get("<name>");`.
- Threshold via `TESLA_HOMEDASH_LOG_LEVEL`; `Logger::install` is called twice from `main()`
  (INFO first so `AppConfig`'s own logs land, then the configured level).
- Outbound control commands → INFO; protocol problems (truncated/unknown/mismatched/socket) → WARNING;
  per-packet telemetry trace → DEBUG. New paths follow that convention.
