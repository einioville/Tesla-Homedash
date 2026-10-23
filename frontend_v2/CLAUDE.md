# `frontend_v2/` — the QML frontend

The dashboard: Qt 6.12 Quick/QML over a C++20 core, built with `scripts/build-frontend.sh` / `.ps1`
(root `CLAUDE.md` §3.2). The root `CLAUDE.md` is always loaded alongside this file, so nothing here
repeats it.

## Layout

```
Main.qml        # the window: view host, the menu's swipe-up strip, app-level overlays (see z-order below)
main.cpp        # construction order matters — Settings before AppConfig (core/CLAUDE.md)
app/            # Theme.qml (design tokens + the settings façade), ViewController.qml, Navigation.qml, Format.js
config/         # settings.json (bundled Options-view schema), notifications.json
core/           # C++: ServerClient, protocol.hh, Logger, AppConfig, dotenv, the QML singletons
  tesla/ media/ weather/ charging/ trip/ map/ notification/   # per-domain data models
items/          # QML components by domain (charging history luna media settings tesla trip util weather)
views/          # one screen per view: Dashboard Map Weather Media History Trips Charging Settings
resources/      # fonts, icons, styles, Luna, shaders (ShaderEffect .frag, LightningLayer's material; qt_add_shaders)
```

## Icons

Every UI icon is from the **Dazzle Line** set (svgrepo.com, Dazzle UI, CC BY 4.0 — credited in the
README): 24 px grid, 2 px round strokes, no fill, recoloured white in `resources/icons/` with the
source name in a comment, and tinted where needed with `items/util/TintedIcon.qml`. A button or
marker draws an icon, never a text glyph (▶, ✕, ⚠, ›). Where the set has nothing to fit, the icon is
drawn in its style and says so in its comment (`seat.svg`, `steering.svg`). The exceptions are the
weather symbols, FMI's SmartSymbols (`resources/icons/weather/smartsymbol/`), the car marker
`arrow.svg`, and the media transport's filled round buttons (`media_*.svg`, Spotify's look, kept by
choice). svgrepo refuses scripted downloads (a JavaScript checkpoint); the whole set is
mirrored on freeicons.org.

## Where the detailed notes live

| Working on | Read |
|---|---|
| The connection and the login — `ServerClient` (`Server`), `PairedDisplays` | `core/CLAUDE.md`; the exchange in `backend/src/auth_service/CLAUDE.md` |
| A `core/` singleton — `Media` (the cover fetch), `Settings`, `Geocoder`, `Probe`, `Photos`, `UsbImport`, `Display`, `System`, `SystemHistory`, `Logs`, `TeslaFields`, `SpotifyAuth`, `SpotifyDevice`, `Updater` | `core/CLAUDE.md` |
| The Options view's QML — layout, schema keys, delegates, status widgets, the USB photo import | `items/settings/CLAUDE.md` |
| The map — `items/tesla/TeslaMap.qml` (full-screen in `views/MapView.qml` with its layers: the radar, the drive under way — `CurrentDrive` — and OSM place names — `PlaceNames`; `items/trip/TripMap.qml` shares its gesture handlers) | `items/tesla/CLAUDE.md` |
| A graph — every one is `items/history/HistoryGraph.qml`; its multi-line additions (`extraSeries`, fixed range, `wheelZoom`) | `items/settings/CLAUDE.md`, *Järjestelmän tila*. How it draws is in the file's own comments: the x-axis is written only by `showWindow()`, never bound (#81), and the line, its glow and the extra lines are Shapes traced per data rebuild and moved by transforms in between — Qt Graphs draws only the axes and grid. Its data work is C++, `GraphSeries` (`core/CLAUDE.md`) |
| `items/util/ScreenSaver.qml` | `items/util/CLAUDE.md` |
| A new control or anything that moves — reuse `ToggleSwitch`, `Reveal`, `ElasticFlickable`, `WheelStepArea`, `HoldRepeatArea`, `ReleaseVelocity` (timings are `Theme` *Motion* tokens) | `items/util/CLAUDE.md` |
| The wire format of anything `ServerClient` parses | `backend/src/utils/CLAUDE.md` |
| Anything that might already exist — the shared helpers to reuse instead of copying | root `CLAUDE.md` §7.8 |

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
  `scripts/build-frontend.sh --run --fullscreen` sets it to `1`.
- `TESLA_HOMEDASH_LOG_LEVEL` — `debug`/`info`/`warning`/`error`/`critical` (default `info`;
  invalid → `info` + a startup warning).
- `TESLA_HOMEDASH_LOG_DIR` — where `frontend.log` goes, beside the backend's files (default
  `<GenericStateLocation>/Tesla-Homedash/logs`, i.e. `~/.local/state/…`; the backend's rule).
- `TESLA_HOMEDASH_SETTINGS_FILE` — override the path of the frontend's writable settings
  file (default `<QStandardPaths::GenericConfigLocation>/Tesla-Homedash/frontend_config.json`
  — i.e. beside the backend's `backend_config.json`). With no override, while that file does not
  exist yet, a legacy `AppConfigLocation/settings.json` (`~/.config/appfrontend_v2/`) is copied
  (not moved) to it (`Settings::migrateLegacyStorage`).
- `TESLA_HOMEDASH_CREDENTIALS_FILE` — override the path of this display's backend login (default
  `<GenericConfigLocation>/Tesla-Homedash/frontend_credentials.json`, 0600; `core/CLAUDE.md`,
  *ServerClient*). Point it at a scratch file to test without touching the real login.
- `TESLA_HOMEDASH_NOTIFICATIONS_CONFIG` — path to a notification-rules file used instead of the
  bundled `config/notifications.json`, read once at startup by `NotificationHandler::loadConfig`.
  Process environment only (not `.env`). A file that cannot be opened falls back to the bundled
  rules with a warning; one that is not a JSON object disables notifications with a warning.
- `TESLA_HOMEDASH_SCREENSAVER_DIR` — not read: the screensaver's photos live in a fixed folder
  (`core/CLAUDE.md`, under `Photos`), and a startup warning names that folder if this is set.
- `TESLA_HOMEDASH_MAP_API_KEY` — the MML open-data key, read by `AppConfig` straight from the
  environment / `.env` (a deployment secret, not an Options-view setting). With it the maps use
  MML's 0.5 m orthophoto within Finland and the keyless EOX Sentinel-2 imagery outside it
  (`items/tesla/CLAUDE.md`, *The basemap*); without it, EOX everywhere plus a startup warning.
  Takes a restart — the OSM plugin reads its tile host once.

**Frontend settings file.** `frontend_v2/config/settings.json` is the *bundled schema*
(defaults, types, bounds, Finnish labels) compiled into the binary; the user's overrides are
written to the writable file above via `QSaveFile`. A schema entry may name an `env` key,
making that environment variable supply the setting's **default** — so the precedence is
`schema default < env/.env < saved user override`, and an existing deployment's `.env` keeps
working until the user changes the setting on-device. `TESLA_HOMEDASH_BACKEND_HOST`, `_PORT`
and `_SCREENSAVER_TIMEOUT_MIN` are wired this way. `AppConfig`, which consumes those three at
startup, applies the same precedence itself: the saved override from `Settings::savedValue()`,
else the environment / `.env` (`core/dotenv`), else its own default.

## QML live preview — the QmlPreview MCP server (Qt 6.12+)

For tuning how a screen looks or moves — layout, sizes, colours, states, animation, a `Theme`
token — a live preview beats the rebuild-and-relaunch loop. Qt's **QmlPreview MCP server**
(Qt installer: *Agentic Development Tools › QmlPreview MCP Server*, a binary in the kit's `bin`)
gives an agent one tool, **`run_qmlPreview(executable_path)`**: it launches the built app under
`qmlpreview`, and every QML file saved to disk is patched into the running app — no rebuild, no
relaunch, no finding the view again. Qt's `qt-qml` agent skill knows the workflow.

- **The build has to allow it**: `scripts/build-frontend.sh --qml-preview` (`-QmlPreview` in the
  PowerShell script) sets `FRONTEND_V2_QML_PREVIEW`, which defines `QT_QML_DEBUG` on
  `appfrontend_v2`. That opens the QML debug service, which can load arbitrary QML into the process,
  so it is off unless asked for on that very build — not tied to Debug, the scripts' default and
  what a manual build on the Pi gets — and **a build for the Pi never has it**. Switching it
  recompiles everything once.
- **Register the server once per machine** with Claude Code — the binary is `QmlPreviewMcpServer` in
  the kit's `bin` (`QmlPreviewMcpServer.exe` under `msvc2022_64\bin` on Windows):
  `claude mcp add --scope user qml-preview -- ~/Qt/6.12.0/gcc_64/bin/QmlPreviewMcpServer`. The path
  names the Qt version, so a new kit means registering it again; a new session picks it up.
- **Offer it, never start it unasked**: it opens the app's window on the user's desktop (WSLg on the
  dev box) and connects to the shared backend like any run (root `CLAUDE.md` §8). On a yes, start it
  once per session with the binary's absolute path (`<checkout>/frontend_v2/build/appfrontend_v2`),
  then edit and save; say what changed and let the user say what they see — the agent cannot see that
  window, so never claim the UI updated. Restart it only when edits stop appearing.
- **What patches live**: edits to existing QML and JS files. **What needs a rebuild** — say so before
  editing: any C++; `CMakeLists.txt`; a new QML or JS file (the module compiles QML into its
  resources); importing a module the binary does not link; `qmldir` and singleton registration.
  Turning a value into a binding, or moving a binding to another property, may apply but lose state.
- **It needs one QML engine and QML from a module**, which the app has: one `QQmlApplicationEngine`
  in `main.cpp`, loading `Main` from the `frontend_v2` module. A second engine, or QML loaded on a
  worker thread, would make the preview unreliable.
- **It does not replace the offscreen screenshots.** Those are how the agent sees a result itself
  and hands the user pictures; the preview is for tuning together, live.
- **Go through the server, not `qmlpreview` by hand.** The server starts `qmlpreview` and the app
  and relays the app's output; run by hand on the dev box, `qmlpreview` often never got the app
  past startup, for no reason found. Through the server it works: a title edited in
  `WeatherHourlyCard.qml` showed in the running app within seconds, compiled QML module and all.

## `app/Theme.qml` — the settings façade

Tokens that are user-tunable are bound (`readonly property bool
lunaEnabled: Settings.values.lunaEnabled`) instead of being literals; everything else stays a
`readonly` literal that qmlcachegen AOT-compiles. A property initialiser is a *binding*, so every
`Theme.x` call site gets live updates with no change of its own.
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
  beneath it (QTBUG-145896).
- **Enter closes it too, but keeps focus** (`onAccepted: Qt.inputMethod.hide()` in the field
  delegates). Clearing focus there would emit `editingFinished` a second time and send the write
  twice. Tapping the still-focused field reopens it.
- The settings pane makes room and scrolls the focused field above it — `items/settings/CLAUDE.md`.

## View switching (`app/ViewController.qml`)

The views stand round a cylinder whose rotation is one number, `center` (in views; positions wrap,
so the dashboard's left neighbour is the last view). Every switch — edge swipe, menu pick, home
return — is a `glide` of it: the current view backs away until its neighbours show tilted at
the edges, the cylinder turns, and the new view comes forward. The phases overlap (`Theme`
*Motion*: `viewBackDuration`, `viewTurnDuration`, `viewForwardDuration`, `viewPhaseOverlap`); the
geometry and gesture constants sit at the top of the file. Under the screensaver (the host is
invisible) a switch is instant and an open menu closes.

- **A jump turns the short way round, past every view between** — the dashboard to Sää passes
  the map, Asetukset to the dashboard is one step, the two ends being neighbours. Halfway round
  either way is as short, so a tie turns forward to a later view and back to an earlier one. A view the turn passes that is not
  built yet shows its icon (below). Each step past the first adds 40 % of `viewTurnDuration`, so a
  four-step jump is not four turns long.
- **Edge swipes turn under the finger.** A horizontal drag starting within `swipeEdge` of a side
  edge backs the view away over its first `swipeBackDistance` and turns the cylinder one step per
  `stepPx` — the on-screen distance between neighbours — so the next view follows the finger into
  the centre. Let go past half a step (or flicked), it lands there; short of that, it turns back.
  Drags anywhere else stay with the view, so the map, graphs, radar and sliders keep their own
  horizontal drags.
- **The swipe strips lie under the views.** A DragHandler on top accepts the press and starves the
  item beneath (QTBUG-145896, as with the keyboard's outside-press catcher below); underneath, it
  still gets the press as a pointer handler and takes the drag over once it turns horizontal.
  Checked with touch and mouse: a tap or a vertical scroll that starts in a strip stays with the
  view, and an edge swipe wins over the map's own DragHandler.
- **The menu** is the cylinder held further back (`menuZoom`) with each view's name below it — the
  only way to pick a view by name. A swipe up from the strip over the home
  indicator (`Main.qml`, 360 × 72 px at the bottom centre) draws it out under the finger, the
  indicator giving way to the names, and it opens if let go past 60 % of `menuPullDistance` (or
  flicked). The strip is a DragHandler, so a tap in it reaches the view beneath.
  Open, a horizontal drag spins it and the release stops it square on the view nearest the front —
  unless it is a flick, which runs on (up to three views) first; a
  tap opens the view tapped (the front one for a tap on the space round them), and a drag down
  opens the front one. Left still for `menuAutoPickSec` (Yleinen › Navigointi, default 4 s; a press
  or a spin starts the wait over), it opens the front one by itself. Its input is one `MouseArea` over the views, which only swallows input
  while a turn plays.
- **Moving, each view on screen is a layer** drawn through a perspective `Matrix4x4` built in
  `poseAt` (z flattened to 0). Live views under a perspective matrix cannot be batched — a draw call
  per item, for every view in sight — while a still layer renders once. `Rotation.distanceToPlane`
  (Qt 6.11+) would do the perspective as well. Views out of sight are hidden,
  because Qt Quick does not cull.
- **One view is live** — its `isCurrent` on, so the map follows the car, the media ticker runs and
  the live graphs feed: the current view, and in the menu the one settled at the front for
  `menuLiveDelay` (400 ms), so a spin does not wake each view it passes. Coming live a view does
  what it does on being opened — History, Charging and Trips fetch fresh data — and going off,
  what it does on being left (Settings closes its dialogs and any Spotify device scan). A pick
  makes the picked view live at once. The live view still renders through its layer, which
  redraws whenever the view changes.
- **Backed away (or warming), a view only shows.** No input reaches it, hover included — a graph would draw
  its inspect line, a touch would start one. Presses are stopped by a gate round each view: press
  delivery skips a clipping item, children and all, whose shape (`containmentMask`) contains no
  point — the menu's `MouseArea` alone is not enough, since pointer handlers beneath an item that
  accepted a press still see it. Hover delivery tests only an item's bounds, so a blocking
  `HoverHandler` above the views stops it. `enabled: false` would block both, but restyle the
  controls that follow it (sliders, text fields, History's LIVE button). Checked: the History
  graph's hover and touch handlers stay off in the menu and come back after it.
- **The frame** — rounded corners and a light edge — grows in over the first backing away, so a
  full-screen view stays square. The corners are covered, not masked: a ring in the space's colour
  (black) whose inner edge is the rounded frame, so the layer stays a plain texture and nothing
  needs a shader.
- **Release speeds come from `items/util/ReleaseVelocity.qml`** — the menu's spin, the edge swipe
  and the pull alike — measured over only the last 100 ms of movement. A speed kept from the last
  move event would spin a finger that stops on a view and then lifts on to the next one.
- **Every view is built in the background after startup** (`prebuildNext`), so the menu and the
  turns show real content from the first swipe. From 3 s after start, one view at a time is built
  asynchronously (the current view keeps its frames), then drawn for a second beneath the current
  one — every view root is opaque — so it renders once: the map fetches its tiles and the GPU
  compiles the view's pipelines then, not on its first glimpse (all seven are done about 10 s
  after start on the dev box). A view needed meanwhile finishes at once (`Loader.asynchronous` turned
  off), and until a view is built it shows its icon. Building runs what a view does on
  construction: Trips requests this week's trips (as opening it does) and the radar fetches its
  frame list from FMI. Warming views stay frozen (`isCurrent` false) and behind the input
  gate below.
- **Another view is opened with `Navigation.open(key)`** (`app/Navigation.qml`, a singleton), the
  key from `Main.viewModel`: the dashboard's weather card and a map's radar minimap open the Weather
  view so. `Main.qml` makes the switch, as the menu's pick does, so a view need not know where the
  other stands on the cylinder.
- **The target is built before the motion starts** — a swipe's at drag start, a home return's one
  event-loop pass before the animation (`Qt.callLater`), a menu pick's before its glide — so a slow
  view build delays the turn rather than skipping frames of it.

## Overlays and z-order

- **A modal inside a view cannot cover the menu's swipe-up strip.** The strip lives in `Main.qml`
  and is declared *after* the view host, so it lies over the whole view whatever `z` the modal sets
  — `z` orders siblings within one parent only — and takes any upward drag that starts in it
  whenever the views are still (not mid-turn or in the menu, *View switching*). Taps go through, so
  a button there still works, but a list scrolled from there opens the menu instead: a tall modal is
  anchored and sized to end above the bottom 72 px (`ModalDialog`'s `cardTopMargin`;
  `items/settings/CLAUDE.md`, *USB photo import*, is a case).
- **App-level layers in `Main.qml`:** notifications z:200, the Spotify re-auth prompt z:250 and its
  progress dialog z:260, the backend login prompt z:265, the update banner z:270, the keyboard's outside-press catcher z:280 and the
  keyboard itself z:290, the screensaver z:300. Something that must be seen
  whichever view is current belongs here, not inside a view.

## Motion that keeps running

While any QML `Animation` runs — a `Behavior`, a `NumberAnimation`, a sprite — Qt Quick renders
the whole window on every vsync, the map and every card with it: the threaded render loop asks for
a frame per animation tick and always presents it (`qsgthreadedrenderloop.cpp`). A running `Timer`
does not; the window is redrawn only when a tick changes the scene. Measured on 6.11: an item moved
by a 50 ms `Timer`, 20 frames a second; by a `NumberAnimation`, 60. So motion that goes on for
minutes steps on a `Timer`, and animations are kept to moments. The cover-coloured backdrop of the
dashboard and the Media view (`items/media/MediaBackdrop.qml`) is the case: 22 frames a second
while music plays (its 20 and the seek bar's tick), none once paused. The spectrum
(`items/media/MediaSpectrum.qml`, bars or line, in the Media view and behind the equalizer) redraws
per frame the backend sends, about 30 a second: 34 with the backdrop on the dev box (measured with
the line), with the per-frame work in C++ (`SpectrumLevels`, `core/CLAUDE.md`). The climate switch's water
(`items/tesla/CLAUDE.md`) renders every frame while a switch shows, and only then. A media title
too long for its place (`items/util/MarqueeText.qml`) renders every frame for the few seconds it
scrolls, once every `marqueeRestDuration` while the music plays. A radar loop's crossfade
(`items/weather/RadarLayer.qml`) steps on a 50 ms `Timer` for 400 ms of each step: about 8 redraws
a step, none between.

## QML ↔ C++ traps

- **A `Q_INVOKABLE` registers no property dependency**, so a binding built on one never
  re-evaluates. Read a `Q_PROPERTY` (or index into one) instead — `core/CLAUDE.md` records the
  `Updater` card that froze this way, and `Settings.valuesRevision` exists for the same reason.
- **A bare read is no dependency in a binding qmlcachegen compiles.** `frames.count;` as a
  statement, or `const revision = Settings.valuesRevision` left unused, is dropped from a binding
  compiled to C++, and the dependency with it: RadarLayer's shown frame stayed empty with *Vain
  uusin* until its count was read in the result. The interpreter keeps such reads, so the idiom
  holds in the bindings that use it now — none compiles, each reading an untyped property or
  calling a JS function — but one made compilable loses them. Use the value in the result. A
  binding is compiled if `build/.rcc/qmlcache/*_<File>_qml.cpp` has `// expression for <name> at
  line N`.
- `QT_QML_GENERATE_QMLLS_INI` is **deprecated since Qt 6.10** ("no replacement needed") — don't add
  it to `CMakeLists.txt`.

## Notifications

`core/notification/notificationhandler.{hh,cpp}` (`Notifications`) turns the rules in
`config/notifications.json` into `notify(id, message)`; `items/util/NotificationLayer.qml` shows
every one, each held for `Theme.notificationDurationMs`, so the file holds rules only. The Options
view has no notification settings; a notifications section of their own is #51.

## Logging (`core/logger.{hh,cpp}`)

- Format is byte-identical to the backend. Two destinations: stdout (the journal) and the app's own
  `frontend.log` (`Logger::openFile`, 5 MB × 3 backups) in the shared log directory, beside the
  backend's — which is what the Options view's *Lokit* card clears.
- Each `.cpp` gets a file-local `const Logger logger = Logger::get("<name>");`.
- Threshold via `TESLA_HOMEDASH_LOG_LEVEL`; `Logger::install` is called twice from `main()`
  (INFO first so `AppConfig`'s own logs land, then the configured level), setting both destinations.
- **The log level is one backend setting for both halves.** `main()` follows `logging.level` out of
  the backend's schema (`Settings::groupsChanged`): the file takes the level as it is, stdout (the
  journal) the same but never below INFO unless the app was started at DEBUG — the backend's rule
  (`Logger::setLevels`). DEBUG returns by itself when the backend's duration is up
  (`backend/src/system_service/CLAUDE.md`); with no backend schema the configured level applies. Both
  thresholds are atomic because they change while worker threads log.
- `Logger::clearFiles(keepWarnings)` rewrites this half's files under the write mutex — empty, or
  only the WARNING+ records with their continuation lines (the backend's filter, line for line) —
  and reopens the active one. `Logs` (`core/CLAUDE.md`) calls it.
- Outbound control commands → INFO; protocol problems (truncated/unknown/mismatched/socket) → WARNING;
  per-packet telemetry trace → DEBUG. New paths follow that convention.
