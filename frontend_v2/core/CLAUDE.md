# `frontend_v2/core/` — the C++ core and QML singletons

`ServerClient` (the TLS session, the login and the frame demux), `protocol.hh` (the mirror of
`backend/src/utils/protocol.py` — change both together), `Logger`, `AppConfig`, `dotenv`, and the
singletons below; per-domain data models live in the subdirectories. Several singletons back
Options-view widgets whose QML notes are in `../items/settings/CLAUDE.md`.

**Wire shapes have one reader and one writer each, in `protocol.hh`** — reuse them rather than
parsing a header by hand: `jsonRequestBody()` / `readJsonReply()` (nothing for a short, truncated,
malformed or non-object reply), `writeString()` / `readString()` (len(2B) + UTF-8 ids),
`historyRequestBody()`, and `readSeries()` (the series block of `TESLA_HISTORY`, `CHARGER_HISTORY`
and `TRIP_SERIES`). A graph's axis bounds come from `seriesbounds.hh`: `seriesBounds()` for a static
series, `rollLiveWindow()` for a live one.

## `ServerClient` — `serverclient.{hh,cpp}`, `scram.{hh,cpp}`, `credentialstore.{hh,cpp}`

The one socket to the backend (QML `Server`), **TLS 1.3 with a login in front** (issue #64; the
exchange is `backend/src/auth_service/CLAUDE.md`). Until the backend answers `AUTH_RESULT ok`, every
frame is handled here and nothing is emitted — `connected` stays false, so no data model ever sees
a session that has not logged in, and none of them changed for it. Load-bearing:

- **The certificate is checked by hash, never by a CA.** `QueryPeer` takes it without validating
  it (it is self-signed by design; Qt still emits `sslErrors` for that, and nothing listens). Its
  SHA-256 is SCRAM's channel binding at a password login and, once that succeeds, the **pin**
  stored beside the token. A connection whose certificate is not the pinned one sends no token:
  the password is asked for again, and the SCRAM exchange proves the new certificate.
- **The login prompt is a state, not a dialog this class opens.** `authState` (`offline`,
  `authenticating`, `loginRequired`, `noPassword`, `authenticated`), `authMessage`, `loginBusy` and
  `loginPromptVisible` drive `items/settings/BackendLoginPrompt.qml`; `login(password)`,
  `dismissLoginPrompt()` and `showLoginPrompt()` are the whole API. **While a password is needed
  there is no reconnect loop**: `requireLogin()` closes the socket and `login()` opens the next one.
  With no password on the backend it keeps retrying every 10 s, since setting one restarts the
  backend, and logs that only once.
- **PBKDF2 runs on a `QtConcurrent` worker** (`scram::answer`, seconds on a Pi); the password is
  moved into the worker and dropped there. `scram.cpp` mirrors the backend's `scram.py` — change
  both together — and refuses a challenge under 100 000 rounds, so a man in the middle cannot ask
  for a cheap key.
- **A socket error aborts the socket.** A backend that ends the session cleanly (a revoked login, a
  shutdown) sends a TLS close_notify, which arrives as `RemoteHostClosedError` while the socket
  stays *connected* — nothing answers it, so `disconnected` never comes. `onError` aborts, and both
  signals end in the one `connectionLost()`.
- **`CredentialStore`** keeps `{deviceId, token, certSha256}` per `host:port` in
  `frontend_credentials.json` beside `frontend_config.json`, 0600 from the first byte (the
  permissions go on `QSaveFile`'s temp file before the write), `TESLA_HOMEDASH_CREDENTIALS_FILE`
  overriding the path. Not in the settings file, which is not a secret, and not the OS keyring,
  which is never unlocked on a kiosk that logs in by itself. A refused token (`token` reason:
  revoked, expired, the password changed) is forgotten.

## `PairedDisplays` — `paireddisplays.{hh,cpp}`

The Ylläpito › Näytöt card's list (issue #64), rendered by `items/settings/PairedDisplaysPanel.qml`:
every display that has logged in, with `revoke(id)`. Like `TeslaFields` it holds no copy it edits —
the rows are the backend's `AUTH_DISPLAYS`, broadcast after a login, a revoke and a display
connecting or leaving. Asked for when the card is built and again on reconnect once asked. This
display is the row whose `id` is `Server.deviceId`; revoking it logs this display out, which is
how to do that.

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
files the Options view writes. No QML reads them at present; both paths also appear in the log.
`backendStoragePath` is empty until a schema arrives and is kept after a disconnect; a document
without the key never blanks a path already known.

**The two schemas merge by group id.** `Settings::rebuildGroups()` indexes the backend's groups by
id and folds each into the local group of the same id, so one sidebar section can hold subsections
from both. Consequences worth knowing:
- **`config/settings.json` is the canonical section list**: order, label and icon come from it,
  which is why `electricity` and `tesla` appear there with an empty `sections` array.
  Those placeholders exist only to place and name a backend-only section; a section that ends up
  with no subsections at all is hidden, so they cost nothing while disconnected.
- A backend group whose id the local schema does not know is **appended**, not dropped.
- `origin` is per **subsection** (the "sovellus"/"palvelin" badge sits on each card), because a
  section can legitimately mix the two.
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

An `action` row whose key `Settings::invokeAction` does not handle itself emits
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
backend just sees a connection open and close. It stays plain TCP: reachability is the question,
and a TCP connect to the TLS port answers it — the backend drops the unfinished handshake
silently.

## `Photos` — `screensaverphotos.{hh,cpp}`

The screensaver's photo folder, **fixed** at `<GenericConfigLocation>/Tesla-Homedash/screensaver`
(`~/.config/Tesla-Homedash/screensaver`, beside `frontend_config.json`) and created at startup.
The backend's `usb_import_service` copies into the same path (`screensaver_dir()`), so neither half
makes it configurable. `TESLA_HOMEDASH_SCREENSAVER_DIR` is not read; a deployment that sets it
gets a startup warning naming the folder to copy to. `count` is the number of images in the
folder, kept live by a `QFileSystemWatcher` (debounced 500 ms, since a copy fires an event per
file). It drives the *Kuvakansio* row's "N kuvaa löydetty" and the screensaver switch's
`relevantWhen` condition. `imageNameFilters` is the one extension list: `ScreenSaver.qml` plays with
it and the backend copies the same set.

## `UsbImport` — `usbimport.{hh,cpp}`

The Options view's photo import from a USB stick. The backend does every step
(`backend/src/usb_import_service/CLAUDE.md`); this side sends the user's choices and exposes the one
`USB_IMPORT_STATE` document it gets back (`phase`, `drives`, `device`, `found`, `count`, `copied`,
…). Fenced like `SpotifyDevice`: every request carries `m_flowId`, a state with any other value is
dropped, and `close()` advances the epoch so a state in flight cannot reopen the dialog. A lost
connection ends the flow with an error rather than a dialog waiting forever.

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
round, a lit panel looks dark forever (#44). **Wakes from activity are throttled to one per
`kWakeRetryMs` (2 s)** while the panel is reported off: activity fires per input event, touch moves
included, so a wake that keeps failing (wlopm blocked by a VNC server, a failed startup power-on)
would otherwise send a request — and spawn a `wlopm` — per event. A working wake is answered in
milliseconds, so the throttle never delays one. `wake()` is deliberate and bypasses it.
`fault` mirrors the backend's third state byte (`backend/src/display_service/CLAUDE.md`; a two-byte
payload reads as none); while it is `OUTPUT_LOST` the countdown does not request a power-off, and
`items/settings/ScreenPowerStatus.qml` explains it in the Näytönsäästäjä card.

## `System` — `systemstatus.{hh,cpp}`

**The maintenance dashboard** (issue #39) is `core/systemstatus.{hh,cpp}`, the QML singleton
**`System`**, rendered by the service cards of `items/settings/SystemStatusSection.qml`. Pull, not
push: it polls `SYSTEM_GET_STATUS` every 5 s **only while retained**. **Polling is reference-counted
(`retain()` / `release()`), not a flag**: a screen being built and one being torn down overlap (a
section switch, a rebuilt Loader), and a flag set by the newcomer was cleared by the one leaving. Each
consumer retains while visible and releases exactly once (`syncPoll()`). The document is handled as an opaque `QVariantMap` on
purpose: it is a dashboard, not a contract, and adding a metric — or a service, or a setting in one —
on the backend needs no C++ change to display it. It also carries **one card's warning/error list**:
`openLog(service, label)` sends `SYSTEM_GET_LOG` and fills `logEntries`; a reply for another card or
a list since closed is dropped. `SystemLogPopup` binds to it.

## `SystemHistory` — `systemhistory.{hh,cpp}`

**The Järjestelmän tila graphs' data**, the QML singleton **`SystemHistory`**, rendered by
`items/settings/SystemStatusSection.qml`. The backend samples continuously
(`backend/src/system_service/CLAUDE.md`); this side fetches every 2 s **only while retained**
(reference-counted like `System`), sending the timestamp of the newest sample it holds so each poll
moves a sample or two and a return to the section fetches only what was missed. A `reset` reply
replaces the buffer instead of appending. Samples are kept as **rows** and handed to QML as
**columns** (`series`: `t`, `cpu` — one array per core — `memUsed`, `diskRead`, `diskWrite`, `netRx`,
`netTx`, `cpuTemp`), because a polyline is built from a column; `info` carries what changes too
rarely to be one (memory total, disk space, `temp_available`, the sampling interval and window). A missing value is **NaN**, the graph's
gap. The buffer is trimmed from the newest sample to the window **plus three intervals**: the graph
slides each new sample in, and during the slide its left edge shows what lies just past the window.
Unlike `System`, this is typed — the graphs need named columns, not an opaque document.

## `Logs` — `logcontrol.{hh,cpp}`

**Clearing the app's log files** (Ylläpito › Lokit), the QML singleton **`Logs`**. Each half clears
its own: `clear(keepWarnings)` empties this half's files at once (`Logger::clearFiles`, local to
wherever the frontend runs — `frontend_v2/CLAUDE.md`, *Logging*) and sends `LOG_CLEAR` for the
backend's. The two come back as **one `finished(ok, message)`** with the bytes freed summed, which
`SettingsView` shows beside the *Tyhjennä lokit* row; no backend, or no answer in 15 s, finishes with
the frontend's half done and says so. `ServerClient` meanwhile exposes `localAddress` / `localPort`,
how the server card's client list marks *tämä näyttö*.

## `TeslaFields` — `tesla/teslafieldeditor.{hh,cpp}`

**The telemetry-field table** (issue #29) is `core/tesla/teslafieldeditor.{hh,cpp}`, the QML
singleton **`TeslaFields`**, rendered by `items/settings/TeslaFieldTable.qml` as the
`status: "teslaProperties"` widget of the backend's *Tesla → Telemetriakentät* subsection (a
settings-free subsection, so it exists only while the backend is connected). **That subsection is
out of the backend's schema for now** (`backend/src/tesla_service/CLAUDE.md`), so nothing builds
the table and the singleton sits idle until it returns. **It holds no copy it
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
turning `SPOTIFY_AUTH_URL` / `_RESULT` into a phase. An embedded `WebEngineView` is a dead end (see
below).

Two details are load-bearing:
- **There is no browser on this side at all.** `SpotifyAuthPopup.qml` is a small progress dialog —
  "Tunnistautuminen käynnissä…" → "Tunnistautuminen onnistui." with a close button — plus
  `DialogButton.qml`. It renders no page, holds no profile, and learns only "started" and
  "finished"; no code or token ever crosses the link. **Qt WebEngine is not used**: no
  `Qt::WebEngineQuick` in `CMakeLists.txt`, no `QtWebEngineQuick::initialize()` in `main.cpp`, no
  `WebEngineQuick` in the README's module list, and the binary links no WebEngine library. A *Peruuta*
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
- **`m_flowActive` fences late replies.** Without it a `SPOTIFY_AUTH_URL` arriving after `cancel()`
  would flip the phase back to `consent` and reopen the dialog for an abandoned flow. The flag is set
  in `begin()`, cleared in `cancel()` and on `SPOTIFY_AUTH_RESULT`; the
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
  that asks is rebuilt every time its section is shown or the schema's shape changes. It
  re-asks on reconnect (forced) once anything has asked, and drops its pending flag on disconnect:
  that reply died with the socket, and a flag left set would refuse every later unforced refresh.
- **The button row's membership is constant** across a `hasDevice` transition, and the guide and
  detail blocks share one container with a floor height. On a 10" touch panel a control that
  changes position between reach and tap mis-routes the tap — here, onto *Peruuta*, which would
  close the dialog and kill the scan. Same reasoning as `SettingAction.qml`'s arm-then-confirm.

## `Updater` — `appupdate.{hh,cpp}`

**In-place app updates** are `core/appupdate.{hh,cpp}`, the QML singleton **`Updater`**, rendered by
`items/settings/UpdatePanel.qml` as the `status: "appUpdate"` widget of a *Päivitys* subsection.
**That subsection is out of `config/settings.json` for now**: the updater is being reworked into a
release-only one that can install any release, with the development channel cut (#56). The
singleton, the banner, the screensaver inhibit and the backend service all stay wired, so
restoring the card is one schema entry — first in Ylläpito, which a local subsection gets for free
because local ones are folded in before backend ones. **This side runs no process**: the backend does the git work, the dependency
sync and the rebuild (`backend/src/update_service/CLAUDE.md`), and the singleton picks a channel,
shows what comes back, and restarts the app when told. The whole `UPDATE_STATE` document is carried
as an opaque `QVariantMap`, like `SystemStatus`'s, so a field added on the backend reaches the
screen with no C++ change. Five things are load-bearing:
- **The channel is `Settings.values.updateChannel`**, which `UpdatePanel` reads (an absent value
  falls to its default) and writes from its own segmented control, because the channel decides what
  the verdict beneath it says and so has to come *first*, in the panel, not in a row underneath. No
  schema declares the key at present, so the restored subsection must declare it as a `hidden` local
  setting — otherwise `Settings.setValue` treats it as a backend key. `hidden` keeps a setting out
  of the RENDERED rows while it is stored, coerced, persisted and readable through `Settings.values`
  / `valueOf()` like any other — filtered in `Settings::decorateSections`, the rendering boundary, so
  the empty-subsection drop still counts correctly and nothing that persists a value (all of which
  walks `m_localSchema`) is touched. #56 removes the channel.
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
