# `frontend_v2/core/` — the C++ core and QML singletons

The QML faces of several singletons here are noted in `../items/settings/CLAUDE.md`.

**Every QML type here is registered in `main.cpp`** (`qmlRegisterSingletonInstance`,
`qmlRegisterType`, `qmlRegisterUncreatableType`), not with `QML_ELEMENT`: the generated registration
includes the header by its bare name, which the `core/…` include path does not resolve.

## `GraphSeries` — `graphseries.{hh,cpp}`

The data half of every graph (`../items/history/HistoryGraph.qml`, #83): M4 decimation, the step or
linear path, its trace into plot pixels (a `QPolygonF`, which `PathPolyline` takes as it is), the y
envelope and the inspect lookups. QML keeps the gestures, axes, transforms and draw-in.

- **Series arrive as point lists, bound property to property.** `History.points`,
  `Trips.seriesPoints` and Charging's `points` are `QList<QPointF>`, which a binding hands over in
  O(1) (100 binds of 30 000 points: 0.2 ms); a JS array of `Qt.point`s converts point by point
  (4–9 ms for the same), so no source builds one — only the Järjestelmän tila graphs, ~300 points
  every 2 s.
- **`snapshot()` takes the bound list as what is drawn and answered for**, on a load or a live tick;
  a list bound in between changes nothing until then.
- **Bindings follow `revision`.** `valueAt()`, `extraValueAt()` and `fitY()` are invokables, which
  register no dependency, so HistoryGraph's wrappers read `revision` first. `rebuild()` bumps it
  before tracing, so the paths are traced in the axes the new y-fit chose.

## `SpectrumLevels` — `media/spectrumlevels.{hh,cpp}`

The data half of the spectrum (`../items/media/MediaSpectrum.qml`, #83), one per drawing — the Media
view's and the equalizer's. While `live` it retains `Media`'s spectrum — `MediaData` counts its
watchers, since one view's instance is going as the other's comes — and applies the rise and fall
(`Theme.spectrumRise` / `spectrumFall`) and the 1-2-1 blur. `Media.spectrum` is C++ only; no QML
reads the frames.

- **A list model, a row per band with its `level`**, so a frame updates each bar's own value and no
  list crosses into QML: at 120 frames a second, a quarter less GUI-thread time than bars indexing a
  list property.
- **The line is SVG cubics built in C++** (`path`, for `PathSvg`), not a sampled polyline: the Shape
  took half as long again on ~470 points as on the 39 cubics, and the polyline's joins speckled the
  translucent glow. Built only with `tracePath` (the line style), and again on a resize.

## `Media` — `media/mediadata.{hh,cpp}`

The now-playing state and its cover. The backend sends the cover's URL (`MEDIA_STREAM_IMAGE_URL`,
#84) and each display fetches it, so no download runs in the backend's Spotify poll or in a
connecting display's snapshot.

- **A disk cache keeps covers across restarts** (`<GenericCacheLocation>/Tesla-Homedash/covers`,
  50 MiB) and a request **prefers it** (`PreferCache`): a cover URL names one picture for good —
  Spotify's are content hashes, Nelonen's a file and a size — and both CDNs send lifetimes of months
  to years anyway.
- **Up to 10 decoded covers stay in memory** by URL (`m_covers`, served as `image://media/<hash>`),
  with their k-means colours, decoded together on a worker. A URL already there shows at once — the
  snapshot after a reconnect, the next track off the same album, a cover a skip was expected to
  bring. **A load is never cancelled**: one the backend has moved past lands in memory and is shown
  only if it is still the URL named last (`m_wantedCoverUrl`). A failed or stalled fetch (20 s
  without a byte) keeps the shown picture and logs a warning. Eviction is least recently used, never
  the shown, wanted or neighbour covers; a radio's lap of stations fits.
- **The covers either side are learnt and loaded ahead** (`learnNeighbours`): a cover named under a
  new item (title + artists, the same player) records the two items as neighbours, forward or back as
  `coverDirection` says; forward on Spotify, the queue's `nextImageUrl` wins over what followed last
  time. `coverAfterSkip(direction)` answers which cover a skip will bring when it is in memory — the
  current one for a skip back more than 5 s into a Spotify track, which the backend's
  `skip_backward` turns into a restart — so the Media view's swipe slides to it before the backend
  answers (`../items/media/MediaCover.qml`).
- **What plays next** (`nextTitle`, `nextArtists`, `nextImageUrl`) is asked for, not streamed:
  `requestNext()` sends `MEDIA_GET_NEXT`, answered to this display alone from Spotify's queue
  (`backend/src/media_service/CLAUDE.md`). Two asks a track, both only while the Media view is
  current, so a display elsewhere costs the backend nothing: the cover swipe's, 3 s into a Spotify
  track (the queue can lag a track change), and the *Seuraavaksi* card's
  (`../items/media/MediaUpNext.qml`), `askAheadMs` (6 s) before it is due at
  `Theme.mediaUpNextLeadMs` (20 s, fixed by choice: the card's only setting is its switch), catching
  a song queued meanwhile. **A new title or duration clears the answer** — what was next is now
  playing — so a failed ask leaves the card hidden rather than naming the track already playing. The
  card drops 1 s before the end, on a timer armed from each progress update, so it is gone before the
  next track arrives and the cover slides; it keeps its own copy while it drops, and loads its cover
  with a QML `Image`, outside the cache above.
- **`coverDirection`** is the way the cover slides in (`MediaCover.qml`, `slide`): -1 when
  `skipBackward()` (the back button, or a swipe right over the cover) was called within 8 s before
  the change — the backend's Spotify call and next poll, or the radio's stream fetch, then the
  cover's own fetch — and 1 otherwise, a skip from the phone included. Only a new picture slides.

## `QmlNetworkFactory` — `qmlnetworkfactory.hh`

The QML engine's network access, which every `XMLHttpRequest` and http(s) `Image` goes through (the
radar, the lightning, the road cameras): a 30 s transfer timeout, which Qt's default manager lacks,
so a stalled request ends as an error (an XHR's status 0) instead of hanging. Map tiles are not
covered — they go through the Qt Location plugin's own manager.

## `LightningLayer` — `weather/lightninglayer.{hh,cpp}`

The lightning over the radar loop (`../items/weather/RadarLayer.qml`, #83), drawn on the GPU: it
parses FMI's response (`load`) and keeps the strikes in `area`, the view the frames were fetched for.

- **Quads are built only when the strikes, the area or the loop change, and when `project` puts them
  in the camera of the moment** — RadarLayer's `placeStrikes()`, at each map rest and every 1.5 s
  while it moves; in between the item is carried with the map like a frame. 10 000 strikes rebuild in
  under a millisecond of scene-graph sync.
- **A loop step builds nothing.** One quad per strike serves four passes in drawing order — the
  earlier frames' outlines, their crosses, then the shown frame's — and a step only changes the frame
  the shaders (`resources/shaders/lightning.*`) compare each strike's slot with; a quad its pass does
  not draw collapses to a point. A pass's outlines all go down before its crosses, so a cluster's
  crosses do not cut each other. The cross is a distance field (two round-capped strokes) with a
  one-pixel soft edge.
- **A strike's slot is the frame whose 5 minutes end at or after it**; the newest frame also takes
  those since it, and one at or before the loop's start is in none. Earlier frames fade by their own
  age.

## `ServerClient` — `serverclient.{hh,cpp}`, `scram.{hh,cpp}`, `credentialstore.{hh,cpp}`

The one socket to the backend (QML `Server`), **TLS 1.3 with a login in front** (#64; the exchange
is `backend/src/auth_service/CLAUDE.md`). Until the backend answers `AUTH_RESULT ok`, every frame is
handled here and nothing is emitted — `connected` stays false, so no data model ever sees a session
that has not logged in.

- **The certificate is checked by hash, never by a CA.** `QueryPeer` takes it unvalidated (it is
  self-signed by design; Qt still emits `sslErrors`, and nothing listens). Its SHA-256 is SCRAM's
  channel binding at a password login and, once that succeeds, the **pin** stored beside the token. A
  connection whose certificate is not the pinned one sends no token: the password is asked for again,
  and the SCRAM exchange proves the new certificate.
- **The login prompt is a state, not a dialog this class opens.** `authState`, `authMessage`,
  `loginBusy` and `loginPromptVisible` drive `items/settings/BackendLoginPrompt.qml`; `login()`,
  `dismissLoginPrompt()` and `showLoginPrompt()` are the whole API. **While a password is needed
  there is no reconnect loop**: `requireLogin()` closes the socket and `login()` opens the next one.
  With no password on the backend it retries every 10 s, since setting one restarts the backend, and
  logs that once.
- **PBKDF2 runs on a `QtConcurrent` worker** (seconds on a Pi); the password is moved into the worker
  and dropped there. `scram.cpp` mirrors the backend's `scram.py` — change both together — and
  refuses a challenge under 100 000 rounds, so a man in the middle cannot ask for a cheap key.
- **A socket error aborts the socket.** A clean end of session (a revoked login, a shutdown) sends a
  TLS close_notify, which arrives as `RemoteHostClosedError` while the socket stays *connected* —
  `disconnected` never comes. `onError` aborts, and both paths end in the one `connectionLost()`.
- **`CredentialStore`** keeps `{deviceId, token, certSha256}` per `host:port` in
  `frontend_credentials.json`, 0600 from the first byte (the permissions go on `QSaveFile`'s temp
  file before the write). Not the settings file, which is not a secret, and not the OS keyring, which
  is never unlocked on a kiosk that logs in by itself. A refused token (revoked, expired, the password
  changed) is forgotten.

## `PairedDisplays` — `paireddisplays.{hh,cpp}`

The Ylläpito › Näytöt list (#64), with `revoke(id)`. It holds no copy it edits: the rows are the
backend's `AUTH_DISPLAYS`, broadcast after a login, a revoke and a display connecting or leaving.
Asked for when the card is built, and again on reconnect once asked. This display is the row whose
`id` is `Server.deviceId`; revoking it is how this display logs out.

## `Settings` — `settings.{hh,cpp}`

One QML singleton fronting **both** halves of the Options view:

- **Local settings** — schema from the bundled `:/config/settings.json`, overrides persisted with
  `QSaveFile` (atomic; the Pi loses power without a shutdown). `values` is a **`QQmlPropertyMap`**,
  whose per-key change notification is what makes `app/Theme.qml`'s bindings re-evaluate. Only
  *overridden* keys are written, so a default changed in a later release still reaches existing
  installs.
- **Backend settings** — the `CONFIG_SCHEMA` document, never edited optimistically: the backend
  re-broadcasts the authoritative schema after each accepted write.

`groups` merges both, tagging each subsection `origin: "local" | "backend"`, so one delegate family
renders everything. **Construction order in `main.cpp` matters**: `Settings` is built **before**
`AppConfig`, which reads `savedValue()` for `backendHost` / `backendPort` / `screensaverTimeoutMin`
— a user override must beat the environment. The socket does not exist yet then, so the `CONFIG_*`
wiring waits for `attachServer()`.

**The two schemas merge by group id** (`rebuildGroups()`), so one sidebar section can hold
subsections from both:
- **`config/settings.json` is the canonical section list** — order, label and icon come from it,
  which is why `electricity` and `tesla` appear there with empty `sections`: placeholders that place
  and name a backend-only section, hidden while it has no subsections.
- A backend group the local schema does not know is **appended**, not dropped.
- `origin` is per **subsection** (the *sovellus* / *palvelin* badge on each card), because a section
  can mix the two.
- `sectionsOf()` also reads a group with a bare `settings` array as one subsection, so mismatched
  halves still render.

**Two restart tiers, both derived, not latched.** `restartPending` covers restart-tier *backend*
settings, `appRestartPending` restart-tier *local* ones (`backendHost` / `backendPort`, read once by
`AppConfig`). They restart different processes, so the banner names which and has a button per
pending one. Each is "the current value differs from the **baseline** the running process consumed",
so reverting a value clears the banner. The backend baseline is seeded **insert-if-absent** — the
schema is re-broadcast after every accepted write, and taking its value as the baseline would erase
the difference the banner reports — and dropped only when the schema's **`startedAt`** changes: that
tells "the backend restarted" from "the socket reconnected", which the schema's content cannot, since
it reports `config.json`, not what each service read at construction.

An `action` row that `invokeAction` does not handle itself emits **`actionRequested(key)`**, which
`SettingsView` routes — so the backend owns the Spotify exchange while the consent UI stays a view
concern, with `Settings` knowing neither.

**`restartApp()` quits with exit code 42**, the backend's code, so the `Restart=on-failure` unit
relaunches it. It calls `QCoreApplication::exit()`: unwinding `exec()` closes the socket and flushes
cleanly. On the embedded target this is the only way to restart the dashboard (fullscreen, no
keyboard), which is also why no bare "quit" is offered. The Kartta card's `clearMapCache` ends in it,
after deleting the tile folder (`items/tesla/CLAUDE.md`, *The basemap*).

**A JS object written from QML arrives as a `QJSValue`** inside `setValue`'s `QVariant`, which
`QJsonValue::fromVariant` turns into null — the home location's write would clear it — so `setValue`
converts it to a `QVariantMap` first.

## `App` — `appconfig.{hh,cpp}`

Startup configuration from the environment / `.env` (its header lists the variables). It asks for no
particular OpenGL context: Qt's default (2.0; Mesa answers 2.1 on the dev box and on the Pi 4) serves
every item, and the climate wave is built for it (`../items/tesla/CLAUDE.md`).

## `Geocoder` — `map/geocoder.{hh,cpp}`

Address search and reverse lookup for the *Koti* dialog (`../items/settings/CLAUDE.md`). It is C++
because **Nominatim's usage policy wants a User-Agent naming the application**, which QML's
`XMLHttpRequest` may not set, and **at most one request a second**: a request waits its turn and a
newer one replaces any still waiting (`m_generation` drops a reply nobody wants). One result per
distinct address — Nominatim answers the building, its entrance and a shop in it separately.
Searches are limited to Finland, where the weather and the road cameras are. The home's timezone is
added by the backend (`backend/src/config_service/CLAUDE.md`, *Location and timezone*).

## `Probe` — `connectionprobe.{hh,cpp}`

Backend reachability for `items/settings/BackendProbeStatus.qml` (#36). **Deliberately not
`ServerClient`**, which owns the live session and reconnects forever — the opposite of what a
validation check may do. It connects, waits 3 s, reports `reachable` / `unreachable` with the
socket's own error text ("Connection refused" and "Host not found" are different problems) and
closes; a success aborts the instant it connects. Plain TCP: a connect to the TLS port answers the
question, and the backend drops the unfinished handshake silently.

## `Photos` — `screensaverphotos.{hh,cpp}`

The screensaver's photo folder, **fixed** at `<GenericConfigLocation>/Tesla-Homedash/screensaver`
and created at startup; the backend's `usb_import_service` copies into the same path
(`screensaver_dir()`), so neither half makes it configurable. `count` is kept live by a
`QFileSystemWatcher`, debounced 500 ms since a copy fires an event per file. `imageNameFilters` is
the one extension list: `ScreenSaver.qml` plays with it and the backend copies the same set.

## `UsbImport` — `usbimport.{hh,cpp}`

The photo import from a USB stick. The backend does every step
(`backend/src/usb_import_service/CLAUDE.md`); this side sends the user's choices and exposes the
`USB_IMPORT_STATE` document. Fenced like `SpotifyDevice`: every request carries `m_flowId`, a state
with any other value is dropped, and `close()` advances the epoch so a state in flight cannot reopen
the dialog. A lost connection ends the flow with an error rather than a dialog waiting forever.

## `Display` — `screenpower.{hh,cpp}`

Panel power-down (#35), a step beyond the screensaver, which keeps the backlight on for its photos.
**It runs no process**: this side owns only the countdown, being the only side that sees touch; the
`wlopm` call is `display_service`'s (`backend/src/display_service/CLAUDE.md`). `off` and `available`
are *reported* by the backend over `DISPLAY_POWER_STATE`, never assumed, so a host with no wlopm
answers `available=false` and the toggle has nothing to drive. It hangs off
**`IdleWatcher::activity()`** rather than a second event filter, so both timeouts share one
definition of "the user is here". Its settings are pushed from `Main.qml` (`Binding` on
`Display.enabled` / `.timeoutMs`), as the screensaver timeout is for `Idle`, which makes them live.

- **`DISPLAY_POWER_STATE`'s second byte is `on`**, the opposite sense of `m_off` — read the other way
  round, a lit panel looks dark forever (#44).
- **Wakes from activity are throttled to one per `kWakeRetryMs` (2 s)** while the panel is reported
  off: activity fires per input event, so a wake that keeps failing (wlopm blocked by a VNC server, a
  failed startup power-on) would otherwise send a request — and spawn a `wlopm` — per touch move. A
  working wake answers in milliseconds, so the throttle never delays one; `wake()` bypasses it.
- **`fault`** mirrors the backend's third state byte (a two-byte payload reads as none); while it is
  `OUTPUT_LOST` the countdown requests no power-off, and `items/settings/ScreenPowerStatus.qml`
  explains it in the Näytönsäästäjä card.

## `System` — `systemstatus.{hh,cpp}`

The service cards of `items/settings/SystemStatusSection.qml` (#39). It polls `SYSTEM_GET_STATUS`
every 5 s **only while retained**, and **retaining is reference-counted** (`retain()` / `release()`),
not a flag: a screen being built and one being torn down overlap (a section switch, a rebuilt
Loader), and a flag set by the newcomer was cleared by the one leaving. Each consumer retains while
visible and releases exactly once (`syncPoll()`). The document stays an opaque `QVariantMap` on
purpose — a dashboard, not a contract — so a metric, service or setting added on the backend needs no
C++ change. `openLog(service, label)` fetches one card's warning/error list (`SYSTEM_GET_LOG` →
`logEntries`, `logOpenSince`); a reply for another card, or for a list since closed, is dropped.

## `SystemHistory` — `systemhistory.{hh,cpp}`

The Järjestelmän tila graphs' data. The backend samples continuously
(`backend/src/system_service/CLAUDE.md`); this side fetches every 2 s **only while retained**
(reference-counted like `System`), sending the newest sample's timestamp so a poll moves a sample or
two and a return to the section fetches only what was missed; a `reset` reply replaces the buffer.
Samples are kept as **rows** and handed to QML as **columns** (`series`), because a polyline is built
from a column; `info` carries what changes too rarely to be one. A missing value is **NaN**, the
graph's gap. The buffer is trimmed to the window **plus three intervals**, because the graph slides
each sample in and during the slide its left edge shows what lies just past the window. Unlike
`System` it is typed: the graphs need named columns.

## `Logs` — `logcontrol.{hh,cpp}`

Clearing the app's log files (Ylläpito › Lokit). Each half clears its own: `clear(keepWarnings)`
empties this half's at once (`Logger::clearFiles`, local to wherever the frontend runs) and sends
`LOG_CLEAR` for the backend's. They come back as **one `finished(ok, message)`** with the bytes freed
summed; no backend, or no answer in 15 s, finishes with the frontend's half done and says so.
`ServerClient`'s `localAddress` / `localPort` are how the server card's client list marks
*tämä näyttö*.

## `CarTrack`, `CarMotion` — `tesla/cartrack.{hh,cpp}`, `tesla/carmotion.{hh,cpp}`

Where the maps draw the car (`../items/tesla/CLAUDE.md`). `TeslaData` owns the `CarTrack` and hands
it each fix and heading with the packet's car timestamp, and each speed as it arrives; it moves the
car along its fixes 1.5 s behind the car, at the speed reported then. Each `TeslaMap` reads it
through a `CarMotion` (`source: Tesla`), and `CurrentDrive` takes each fix into the drawn route once
the car has reached it (`fixAdded`, `reachedChanged`). More in `cartrack.hh`:

- **Neither the arrival nor the car's stamp says when a position was true** — some drives stamp a
  fifth of the fixes 2 s after the last with a second of road, others a second after with two — so
  the car moves at its reported speed along the path's shape, never by the stamps.
- **A correction holds the lag** (over 4 s, a 0.5 s deadband of road, 1 s while standing), the speed
  shown eases toward it over 0.4 s, and the car brakes into the newest fix instead of passing it.
  Replayed over three logged drives, it stalled in at most 0.4 % of the frames and never dashed,
  where a glide of a fixed second toward each new fix stalled in 7–34 % and dashed in up to 30 %.
- **`advance(now)` is the one clock**: every `CarMotion` asking in a frame gets the same place, and
  one asked after more than 2 s (no map was live) places the car at once.
- **`CarMotion` steps on a `QAbstractAnimation`** while `live`, so the steps fall on the frames; not
  live, it is placed at each arrival and nothing runs. Time is fractional milliseconds
  (`nsecsElapsed`): whole ones stepped the car 16 or 17 ms' worth per frame.

## `CurrentDrive`, `PlaceNames` — `trip/currentdrive.{hh,cpp}`, `map/placenames.{hh,cpp}`

The Kartta view's drive under way and the OSM place names, written up with the map's layers in
`../items/tesla/CLAUDE.md`.

## `RouteBands` — `trip/routebands.{hh,cpp}`

A route coloured by speed, as `items/tesla/SpeedRoute.qml` draws it (#83): `Trips.route` and
`CurrentDrive.route`, one each, owned by their model and registered uncreatable. It holds the fixes
and builds the Shapes' geometry, so no fix is ever a JavaScript value.

- **The geometry is GeoFrame's**: EPSG:3857 metres east and south of the first fix (`origin`), the
  projection `GeoFrame.local()` uses, so the frame carries it with the map. A segment goes to the
  band of its two fixes' mean speed; a band's consecutive segments are one run, a `QPolygonF`, and
  `PathMultiline` takes a `QList<QPolygonF>` as it is — O(1), where 30 000 points as JS arrays took
  1.7 ms. The band scheme is the drawer's (`bandCount`, `bandKmh` from `Theme.tripMaxSpeedKmh`);
  nothing is built until it is set.
- **It is a list model whose rows are chunks**, each a Shape in the drawer. A reset (a reply, a trip)
  puts all its fixes in one chunk; fixes appended after it go to chunks of at most 200 segments, a
  row inserted per new chunk — so a live fix has one short chunk processed again however long the
  drive, and a new chunk adds one Shape without rebuilding the others. A row's `revision` role
  changes with its geometry; `runs()` and `casing()` are invokables, so the drawer's bindings read
  `revision` too.
- **`positionAt(t)`** answers the fix nearest a time, with the bearing toward the next, for the Trips
  map's inspect arrow — the reason a fix keeps its `ts`.

## `TeslaFields` — `tesla/teslafieldeditor.{hh,cpp}`

The telemetry-field table (#29), the `teslaProperties` widget of the backend's *Tesla ›
Telemetriakentät* subsection — which is out of the backend's schema
(`backend/src/tesla_service/CLAUDE.md`), so the singleton sits idle. **It holds no copy it edits**:
`setField()` sends `TESLA_SET_PROPERTY` and the rows re-render from the table the backend broadcasts
after an accepted change, so two open panels can never disagree. A refusal comes back as
`lastError`, naming the view that needs a field's history. Requested when the card is built and on
reconnect once asked.

## `SpotifyAuth` — `spotifyauth.{hh,cpp}`

Spotify re-authorisation (#38): `SpotifyAuthPopup.qml` over the view, `SpotifyAuthDetails.qml` under
the *Tunnistaudu uudelleen* row. `phase` is a plain string (`idle`/`requesting`/`consent`/`done`/
`error`), so QML switches on it with no enum registration. The grant record's `authorizedAt` and
`validUntil` (`backend/src/media_service/CLAUDE.md`) are epoch **ms**, **0 = unknown** — a grant
issued before the record existed has neither date.

- **This side renders no browser and never touches a credential.** The backend opens the consent
  page in the host's real browser and catches the redirect on its own loopback listener; the
  singleton is `begin()`, `cancel()`, and turning `SPOTIFY_AUTH_URL` / `_RESULT` into a phase. The
  popup is a progress dialog that learns only "started" and "finished"; no code or token crosses the
  link. *Peruuta* stays available while the flow runs: a browser that never comes back would
  otherwise strand the dialog.
- **Qt WebEngine is not used, and an embedded `WebEngineView` is a dead end.** Making it pass for a
  real browser — `GALLIUM_DRIVER` for WebGL, `--disable-gpu-compositing`, a `Sec-CH-UA` rewritten
  together with `httpUserAgent` — all worked, and none of it got past Spotify's login gate: an
  embedded user-agent is not supposed to work (RFC 8252 §8.12).
- **The prompt and the progress dialog live in `Main.qml`, not `SettingsView`.** The grant can die
  while any view is on screen, so `SpotifyAuthAlert.qml` is raised over whatever view that is — and
  the flow it starts would have its progress dialog hidden in a settings screen nobody is looking at.
  Both sit **below the screensaver**: a dashboard asleep stays asleep for a prompt that will still be
  there on waking. `alertVisible` is derived in C++ from `needsReauth`, dismissed and
  `phase == "idle"`, so the prompt never stacks under the dialog. Dismissing is sticky until the
  grant works again and then fails afresh (a dashboard nobody can re-authorize right now must stay
  usable), and `begin()` counts as dismissing, so a failed flow does not re-raise the prompt the
  moment its error is closed.
- **`m_flowActive` fences late replies**: a `SPOTIFY_AUTH_URL` arriving after `cancel()` would flip
  the phase back to `consent` and reopen the dialog for an abandoned flow. Set in `begin()`, cleared
  in `cancel()` and on `SPOTIFY_AUTH_RESULT`; the `SPOTIFY_AUTH_STATUS` snapshot is unfenced on
  purpose — it must always apply.

## `SpotifyDevice` — `spotifydevice.{hh,cpp}`

Spotify device identification: `items/settings/SpotifyDevicePopup.qml`, from the *Tunnista laite*
row. The popup lives **inside `SettingsView`**, not `Main.qml`: unlike a grant dying, a scan is only
ever started from this screen.

- **A scan costs a Spotify request every 2 s and silences the radio**, so it must not outlive the
  screen: `SettingsView` cancels it when the view goes away, and `connectedChanged` ends it (phase
  `error`) when the socket drops — otherwise the dialog spins forever on a scan the backend dropped
  with the old `StreamWriter`, a stale device still selectable.
- **Two fences.** `m_flowActive` answers "is a flow running"; the `scanId` epoch
  (`backend/src/media_service/CLAUDE.md`) answers "is this packet THIS flow's". The epoch is
  incremented *before* the first send, so a missing field parsing as 0 never matches a live scan.
- **`configuredStatus` belongs to no flow and is never fenced** — the configured device's
  `SPOTIFY_DEVICE_STATUS`, an opaque `QVariantMap` for `SpotifyDeviceDetails.qml`, handled before the
  fence since the backend broadcasts it after any panel's select. `refreshStatus()` is **throttled to
  one request per 15 s** unless forced: each costs a Spotify device-list call, and the row asking is
  rebuilt whenever its section is shown. It re-asks on reconnect (forced) once anything has asked,
  and drops its pending flag on disconnect — that reply died with the socket, and a flag left set
  would refuse every later unforced refresh.
- **The button row's membership is constant** across a `hasDevice` change, and the guide and detail
  blocks share one container with a floor height: on a touch panel a control that moves between
  reach and tap mis-routes the tap — here onto *Peruuta*, which would kill the scan.

## `Updater` — `appupdate.{hh,cpp}`

In-place app updates: `items/settings/UpdatePanel.qml` as the `appUpdate` widget of a *Päivitys*
subsection, which is **out of `config/settings.json`** until the release-only rework (#56). The
singleton, the banner, the screensaver inhibit and the backend service stay wired, so restoring the
card is one schema entry — first in Ylläpito, which a local subsection gets for free since local
ones fold in first. **This side runs no process**: the backend does the git work, the sync and the
rebuild (`backend/src/update_service/CLAUDE.md`); the singleton picks a channel, shows the opaque
`UPDATE_STATE` map, and restarts the app when told.

- **The channel is `Settings.values.updateChannel`**, read and written by `UpdatePanel`'s own
  segmented control, because the channel decides the verdict beneath it. No schema declares the key,
  so the restored subsection must declare it a `hidden` local setting — otherwise
  `Settings.setValue` treats it as a backend key. #56 removes the channel.
- **The restart is a signal, not a call**: `restartRequested()` is connected in `Main.qml` to
  `Settings.restartApp()`, app-level because a rebuild takes minutes and the user may walk back to
  the dashboard meanwhile. It is fenced on the job's **`startedMs`** — the job keeps being broadcast
  after the flag is set — and NOT on the job id, a per-process counter that restarts at 1 with the
  backend and could swallow a later job's restart.
- **The screensaver and the panel blackout are inhibited while `Updater.busy`**
  (`ScreenSaver.inhibited`, the `Display.enabled` Binding), and `items/settings/UpdateBanner.qml`
  shows *"Älä katkaise virtaa"* over every view: a black screen mid-flash is precisely when a user
  reaches for the plug.
- **`SettingAction` is disabled while a run is in flight**: two of those buttons restart a process;
  the backend vetoes that anyway, but a button that silently does nothing is worse.
- **`UpdatePanel` indexes `Updater.state.channels` directly; there is no `channelInfo()`
  invokable** — a binding on one never re-evaluated, and the card froze on the state from when its
  Loader was built while the sibling bindings kept refreshing.
- **The build's commit is compiled in** as `Updater.buildCommit` (`FRONTEND_V2_BUILD_COMMIT`,
  resolved at each CMake configure, which the build script always runs, and scoped by
  `set_source_files_properties` to the one file that reads it — a target-wide definition would change
  every translation unit's command line per commit and make each update a full C++ rebuild on the
  Pi). HEAD and the running binary differ between a checkout and the restart, exactly when it
  matters; `restartPending` derives the mismatch and the card says so.
