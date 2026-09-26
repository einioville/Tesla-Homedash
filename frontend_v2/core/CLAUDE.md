# `frontend_v2/core/` — the C++ core and QML singletons

`ServerClient` (socket + frame demux), `protocol.hh` (the mirror of `backend/src/utils/protocol.py`
— change both together), `Logger`, `AppConfig`, `dotenv`, and the singletons below; per-domain data
models live in the subdirectories. Several singletons back Options-view widgets whose QML notes are
in `../items/settings/CLAUDE.md`.

## `Settings` — `settings.{hh,cpp}`

`Settings` is one QML singleton (`Settings`) fronting **both** halves of the Options view:

- **Local settings** — schema from the bundled `:/config/settings.json`, user overrides
  persisted with `QSaveFile` (atomic; the Pi loses power without a shutdown). Exposed as
  `values`, a **`QQmlPropertyMap`** — that type is what makes `app/Theme.qml`'s bindings
  re-evaluate, since it emits per-key change notification. Only *overridden* keys are written
  to disk, so a default that changes in a later release still reaches existing installs.
- **Backend settings** — the `CONFIG_SCHEMA` document, never edited optimistically: the
  backend re-broadcasts the authoritative schema after each accepted write.

`groups` combines both halves (merged by group id, below), tagging each subsection
`origin: "local" | "backend"`, so one delegate family renders everything. **Construction order in
`main.cpp` matters**: `Settings` is built
**before** `AppConfig`, which consults `savedValue()` for `backendHost` / `backendPort` /
`screensaverTimeoutMin` — a user override must beat the environment. The socket does not exist
yet at that point, so the `CONFIG_*` wiring is deferred to `attachServer()` after
`ServerClient` is constructed. `core/dotenv.{hh,cpp}` holds the `.env` discovery/parsing both
readers share.

`Settings.storagePath` (the local override file) and `Settings.backendStoragePath` (the
backend's `config.json`, from the top-level `path` in its `CONFIG_SCHEMA` document) name the two
files the Options view writes. **The view no longer displays them** — its footer is gone — but the
properties stay for logging and diagnostics. `backendStoragePath` is empty until a schema arrives
and is kept after a disconnect; a document without the key never blanks a path already known.

**The two schemas merge by group id.** `Settings::rebuildGroups()` indexes the backend's groups by
id and folds each into the local group of the same id, so one sidebar section can hold subsections
from both. Consequences worth knowing:
- **`config/settings.json` is the canonical section list**: order, label and icon come from it,
  which is why `media`, `electricity` and `tesla` appear there with an empty `sections` array.
  Those placeholders exist only to place and name a backend-only section; a section that ends up
  with no subsections at all is hidden, so they cost nothing while disconnected.
- A backend group whose id the local schema does not know is **appended**, not dropped.
- `origin` is per **subsection** now (the "sovellus"/"palvelin" badge sits on each card), because
  a section can legitimately mix the two.
- `sectionsOf()` tolerates the pre-#30 shape (a group with a bare `settings` array) by
  synthesizing one subsection, so mismatched halves still render.

Load-bearing:

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

An `action` row whose key `Settings::invokeAction` does not handle itself now emits
**`actionRequested(key)`**, which `SettingsView` routes — that is how the backend owns the Spotify
exchange while the consent UI stays a view concern, with `Settings` knowing nothing about either.

**`Settings::restartApp()` quits with exit code 42**, the same non-zero code the backend
uses, so the README's `Restart=on-failure` frontend unit relaunches it. It calls
`QCoreApplication::exit()` rather than `os._exit`'s equivalent: unwinding `exec()` closes the
socket and flushes cleanly, and unlike the backend there is no journal-traceback problem to
avoid. On the embedded target this is the ONLY way to restart the dashboard — it runs
fullscreen with no keyboard — which is also why no bare "quit" is offered.

## `Probe` — `connectionprobe.{hh,cpp}`

**Backend reachability** (issue #36) is `core/connectionprobe.{hh,cpp}`, the QML singleton
**`Probe`**, surfaced by `items/settings/BackendProbeStatus.qml`. It is deliberately NOT
`ServerClient`: that one owns the live session and reconnects forever, which is the opposite of
what a validation check may do. `Probe` opens a socket, waits 3 s, reports `reachable` /
`unreachable` (with the socket's own error text — "Connection refused" and "Host not found" are
different problems) and closes; a successful probe aborts the instant it connects, so the
backend just sees a connection open and close.

## `Folders` — `folderbrowser.{hh,cpp}`

Backs the screensaver folder picker. Its notes — plain-path navigation state, `parentOf()`,
`isBrowsable()` and the shared image-extension list — sit with the picker in
`../items/settings/CLAUDE.md`, because most of what they guard is `FolderListModel` behaviour.

## `Display` — `screenpower.{hh,cpp}`

**Display power-down** (issue #35) is `core/screenpower.{hh,cpp}`, the QML singleton **`Display`** —
a step BEYOND the screensaver: the screensaver keeps the backlight on to show photos, this cuts it.
**It runs no process.** This side owns only the countdown, because it is the only side that sees
touch input; the `wlopm` call lives in `display_service` (`backend/src/display_service/CLAUDE.md`),
because talking to the system is the backend's job. `off` and `available` are *reported by* the
backend over `DISPLAY_POWER_STATE`, never assumed here, so a host with no wlopm answers
`available=false` and the toggle simply has nothing to drive. It hangs off the
**`IdleWatcher::activity()`** signal rather than installing a second event filter, so both timeouts
share one definition of "the user is here". Its settings are *pushed* from `Main.qml` (`Binding` on
`Display.enabled` / `.timeoutMs`), the same pattern the screensaver timeout uses for `Idle`, which
is what makes them live.

`DISPLAY_POWER_STATE`'s second byte is **`on`**, the opposite sense of `m_off` — read the other way
round, a lit panel looked dark forever (#44). **Wakes from activity are throttled to one per
`kWakeRetryMs` (2 s)** while the panel is reported off: activity fires per input event, touch moves
included, so a wake that keeps failing (wlopm blocked by a VNC server, a failed startup power-on)
would otherwise send a request — and spawn a `wlopm` — per event. A working wake is answered in
milliseconds, so the throttle never delays one. `wake()` is deliberate and bypasses it.
`fault` mirrors the backend's third state byte (`backend/src/display_service/CLAUDE.md`; a two-byte
payload from an older backend reads as none); while it is `OUTPUT_LOST` the countdown no longer
requests a power-off, and `items/settings/ScreenPowerStatus.qml` explains it in the
Näytönsäästäjä card.

## `System` — `systemstatus.{hh,cpp}`

**The maintenance dashboard** (issue #39) is `core/systemstatus.{hh,cpp}`, the QML singleton
**`System`**, rendered by `items/settings/SystemStatusPanel.qml`. Pull, not push: it polls
`SYSTEM_GET_STATUS` every 5 s **only while `active`**, which the panel binds to its own
visibility — so a settings screen nobody has opened costs nothing on either side. The document is
handled as an opaque `QVariantMap` on purpose: it is a dashboard, not a contract, and adding a
metric on the backend should not need a C++ change to display it.

## `TeslaFields` — `tesla/teslafieldeditor.{hh,cpp}`

**The telemetry-field table** (issue #29) is `core/tesla/teslafieldeditor.{hh,cpp}`, the QML
singleton **`TeslaFields`**, rendered by `items/settings/TeslaFieldTable.qml` as the
`status: "teslaProperties"` widget of the backend's *Tesla → Telemetriakentät* subsection (a
settings-free subsection, so it exists only while the backend is connected). **It holds no copy it
edits**: `setField()` sends `TESLA_SET_PROPERTY` and the rows re-render from the table the backend
broadcasts after an accepted change, so two open panels can never disagree. A refusal comes back as
`lastError` — the backend names the view that needs a field's history. The table is requested when
the card is built and again on reconnect once it has been asked for. Backend side:
`backend/src/tesla_service/CLAUDE.md`.

## `SpotifyAuth` — `spotifyauth.{hh,cpp}`

**Spotify re-authorisation** (issue #38) is `core/spotifyauth.{hh,cpp}`, the QML singleton
**`SpotifyAuth`**, with `items/settings/SpotifyAuthPopup.qml` over the view and
`SpotifyAuthDetails.qml` under the *Tunnistaudu uudelleen* row. `phase` is a plain string state
machine (`idle`/`requesting`/`consent`/`done`/`error`) so QML switches on it with no enum
registration. Beside the grant verdict it carries `email`, `displayName`, `authorizedAt` and
`validUntil` from the backend's grant record (`backend/src/media_service/CLAUDE.md`) — epoch **ms**,
**0 = unknown**, since a grant issued before the record existed has neither date.

**This side renders no browser and never touches a credential.** The backend opens the consent page
in the host's real browser and catches the redirect on its own loopback listener
(`backend/src/media_service/CLAUDE.md`); the singleton's whole job is `begin()`, `cancel()`, and
turning `SPOTIFY_AUTH_URL` / `_RESULT` into a phase. It originally drove an embedded `WebEngineView`
that aborted the redirect navigation to read the code out of the URL — that design is **gone**, and
with it Qt WebEngine (see below).

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

## `SpotifyDevice` — `spotifydevice.{hh,cpp}`

**Spotify device identification** is `core/spotifydevice.{hh,cpp}`, the QML singleton
**`SpotifyDevice`**, rendered by `items/settings/SpotifyDevicePopup.qml`. The *Tunnista laite*
action row sits under *Tunnistaudu uudelleen* in the same card; the popup is a scrim + dialog
**inside `SettingsView`**, not in `Main.qml` — unlike the re-auth prompt, which is app-level
because a grant can die while any view is on screen, a device scan is only ever started from this
screen. Four things are load-bearing:
- **A scan costs a Spotify request every 2 s and silences the radio**, so it must not outlive the
  screen. `SettingsView`'s `onIsCurrentChanged` cancels it when the view goes away, and
  `connectedChanged` clears it (phase `error`) when the socket drops — otherwise the dialog spins
  forever on a scan the backend destroyed with the old `StreamWriter`, with a stale device still
  selectable.
- **Two fences, not one.** `m_flowActive` answers "is a flow running at all"; the `scanId` epoch
  (`backend/src/media_service/CLAUDE.md`) answers "does this packet belong to THIS flow". The epoch
  is incremented *before* the first send, so a missing field parsing as 0 can never match a live
  scan.
- **`configuredStatus` is not part of any flow and is never fenced.** It is the configured
  device's `SPOTIFY_DEVICE_STATUS` document, carried as an opaque `QVariantMap` for
  `SpotifyDeviceDetails.qml`, and is handled *before* the `m_flowActive` fence — the backend
  broadcasts it after any panel's successful select. `refreshStatus()` is **throttled to one
  request per 15 s** unless forced: each costs the backend a Spotify device-list call, and the row
  that asks is rebuilt on every settings write, since `Settings.groups` is replaced wholesale. It
  re-asks on reconnect (forced) once anything has asked, and clears `statusPending` on disconnect
  so the row does not read "checking" forever.
- **The button row's membership is constant** across a `hasDevice` transition, and the guide and
  detail blocks share one container with a floor height. On a 10" touch panel a control that
  changes position between reach and tap mis-routes the tap — here, onto *Peruuta*, which would
  close the dialog and kill the scan. Same reasoning as `SettingAction.qml`'s arm-then-confirm.

## `Updater` — `appupdate.{hh,cpp}`

**In-place app updates** are `core/appupdate.{hh,cpp}`, the QML singleton **`Updater`**, rendered by
`items/settings/UpdatePanel.qml` as the `status: "appUpdate"` widget of the *Päivitys* subsection —
**first in the Ylläpito group**, which it gets for free because local subsections are folded in
before backend ones. **This side runs no process**: the backend does the git work, the dependency
sync and the rebuild (`backend/src/update_service/CLAUDE.md`), and the singleton picks a channel,
shows what comes back, and restarts the app when told. The whole `UPDATE_STATE` document is carried
as an opaque `QVariantMap`, like `SystemStatus`'s, so a field added on the backend reaches the
screen with no C++ change. Five things are load-bearing:
- **`updateChannel` is a `hidden` schema entry** — a new per-setting key that keeps a setting out
  of the RENDERED rows while it is stored, coerced, persisted and readable through
  `Settings.values` / `valueOf()` exactly like any other. Filtered in `Settings::decorateSections`,
  the rendering boundary, so the empty-subsection drop still counts correctly and nothing that
  persists a value (all of which walks `m_localSchema`) is touched. It exists because the channel
  decides what the verdict beneath it says — it has to come *first*, not in a row underneath — and
  a two-way choice on a touch panel is a segmented control, not a dropdown.
- **The restart is routed through a signal, not a call.** `restartRequested()` is connected in
  `Main.qml` to `Settings.restartApp()` — the `actionRequested` idiom, and app-level for the
  `SpotifyAuthAlert` reason: a rebuild takes minutes and the user is free to walk back to the
  dashboard while it runs. It is fenced on the job's **`startedMs`**, because the job keeps being
  broadcast after the flag is set and re-emitting would fire the restart repeatedly — and NOT on
  the job id, which is a per-process counter that restarts at 1 with the backend and could
  therefore repeat, silently swallowing a later job's restart.
- **The screensaver and the panel blackout are both inhibited while `Updater.busy`**
  (`ScreenSaver.inhibited`, and the `Display.enabled` Binding), and `items/settings/UpdateBanner.qml`
  puts an *"Älä katkaise virtaa"* strip at z:270 over every view. An update runs for minutes with
  nobody touching the panel, so without this the photo pile fades in over a live rebuild and the
  backlight follows it off — a black screen mid-flash is precisely when a user reaches for the plug.
- **`SettingAction` is disabled outright while a run is in flight.** Two of those buttons restart a
  process; the backend vetoes that anyway, but a button that silently does nothing is worse than
  one that visibly cannot be used.
- **`UpdatePanel` indexes `Updater.state.channels` directly and there is no `channelInfo()`
  invokable.** A `Q_INVOKABLE` registers no property dependency, so a binding built on one never
  re-evaluates: the card froze on the state that existed when its Loader was constructed, while
  the sibling bindings reading `Updater.state` kept refreshing — a live check time above a stale
  version. The same trap as `Settings.valuesRevision`, solved by not reaching for an invokable.
- **The build's commit is compiled in** (`FRONTEND_V2_BUILD_COMMIT`, resolved at CMake configure
  time, which the build script runs every time — and scoped with `set_source_files_properties` to
  the single file that reads it, because a target-wide definition changes every translation unit's
  command line on every commit and would make each update a full C++ rebuild on the Pi) and exposed
  as `Updater.buildCommit`. The repository's HEAD and the running binary are different questions —
  between a checkout and the app restarting they genuinely differ — so reporting HEAD as "the
  running version" would be a lie exactly when it matters. `restartPending` derives the mismatch and
  the card says so.
