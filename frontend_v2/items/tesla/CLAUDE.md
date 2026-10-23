# `items/tesla/` — Tesla cards and the map

## The HVAC button's switch wave — `ClimateStarter.qml`, `ClimateWave.qml`

A switch sends a wave of water out from the button across the dashboard's background, under the
cards, and the cover-coloured backdrop it passes turns yellow. While the car is asked, the button
sends the next wave each time the last one's tail has passed the view's farthest corner. On the
answer the background and the button take its colour together (green on, red off or failed), the
water calms and the background fades back to the cover's colours. `ClimateStarter.qml` holds the
timeline and the button (its header lists what is load-bearing — pending is the backend's state,
so every display waves; a press the backend silently refuses times out; colours move through hue,
not RGB). `ClimateWave.qml` (in `DashboardView`, between `MediaBackdrop` and the cards) runs the
water and draws it with the backdrop. Timings, colours and the water's constants are `Theme`
tokens (`hvac*`).

The water is simulated, as `jquery.ripples` does it: `resources/shaders/climatewater.frag` steps
the wave equation once a frame on a grid of `hvacWaterCell` px cells, in a layer that feeds back
into itself, and the wave fronts push it; `climatesurface.frag` unpacks it and `climatewave.frag`
draws it — crests glowing in the wave's colour, glints, shade, the backdrop bent through it, the
yellow paint. Load-bearing:
- **One step a frame, so the water's own speed is in px per frame**: 0.63 cells a step (the
  step's pull of 1.6; 2 is the scheme's stability limit), ≈ 380 px/s at 60 fps with 10 px cells.
  The fronts run at about that speed. A push much faster than the water outruns its own crest and
  raises none — the reason the waves run at an even speed; a display that renders slower slows
  the water but not the fronts, and the crests weaken.
- **The texture is 8-bit, with height and speed packed as 16 bits over two channels each.** Qt
  gives a layer a float format only on a GL 3+ context (`QRhiGles2`: `caps.floatFormats`), and the
  dev box's offscreen and WSLg contexts are older; asked for `RGBA16F` there, the layer warns
  (`unsupported texture format 8`) and falls back to 8-bit, where the water cannot go below zero.
  The packed texture is read unfiltered at cell centres; the surface pass turns it into plain
  values a filtered texture can blend.
- **A layer redraws only when its own item changes**, not when a texture it reads does, so the
  surface and screen passes take the running `clock` as a uniform they never read.
- **A live recursive layer renders the window every frame** (ShaderEffectSource docs), so the
  water runs only while a switch shows, from the press until the fade after the answer.
- **The push moves the height, not the speed**: an up-and-down push on the speed integrates to a
  raised surface for good. The ring's outer side is the longer, so the push is not quite level and
  the height is drawn back toward level each step.
- **Every wave draws its own look** (`ClimateStarter.reseed`: a turn of the pattern, its phases,
  lobe counts, wobble, breakup, one to three rings, their spacing, width and falloff, the push).
  The ranges keep the last ring within the tail, so it too has passed the farthest corner when the
  next wave sets off.

## Map tuning and follow modes — `TeslaMap.qml`

**Map tuning** is the *Kartta* card in **Datan visualisointi**, beside the *Kuvaajat* card whose
knobs it deliberately mirrors — its *Eleherkkyys* (`mapGestureSensitivity` → `Theme.mapSensitivity`)
uses the graph's levels through ONE table, `Theme.gestureSensitivityLevels`, so a level feels the
same on both, and `mapFollowResumeSec` sits where `graphSettleDelay` does. Seven schema entries plus
seven `Theme.map*` bindings, with **no protocol or C++ side**: everything is consumed by
`items/tesla/TeslaMap.qml` (the dashboard card AND the full-screen `MapView`, whose layers are
below).
`Theme.mapSensitivity` also reaches `items/trip/TripMap.qml`, which carries the same
pan/pinch/wheel handlers, and the Weather view's radar map, which carries them too and also returns
home after `mapFollowResumeSec` (`items/weather/WeatherRadarMap.qml`). The basemap
is not a setting either (*The basemap*, below); the card's one C++ side is its cache clear, an
action described there. Two facts verified against the Qt 6.11.1 sources
on disk, both load-bearing:
- **`Map.bearing` works here only because the OSM plugin opts in.** The docs say changing it on
  a plugin that does not support bearing "will have no effect" — silently — and
  `plugins/geoservices/osm/qgeotiledmappingmanagerengineosm.cpp` calls `setSupportsBearing(true)`,
  which is what makes *Ajosuunta ylös* possible at all. `setBearing` runs the value through
  `sanitizeBearing` (an fmod into `[0,360)`), so feeding it an unwrapped angle is safe.
- **`MapQuickItem.rotation` is SCREEN-space and does NOT turn with the map.** With the item's own
  `zoomLevel` unset, `updatePolish()` takes its "rendering screen-aligned" branch and applies an
  identity matrix. So the car arrow is `rotation: heading - map.bearing`: that is plain `heading`
  in north-up (bearing ~0, below) and ~0 in heading-up, where the map has already turned under
  it. Binding it to `heading` alone would double-rotate the arrow.
- **North-up is `bearing: 0.001`, never 0 — that is what makes the map glide.**
  `QGeoTiledMapScene::updateSceneParameters` uses Linear tile filtering only when the zoom is
  > 0.05 off a whole level or the camera `isTiltedOrRotated()` (`bearing() > 0.0`); at a whole
  zoom and bearing 0 it uses Nearest, so a following map moves in whole-pixel jumps under the
  sub-pixel car arrow. Measured: at bearing 0 the imagery steps 0 → 1 → 2 px while the centre
  moves 0.1 px at a time; at 0.001° it tracks to ~0.05 px. The tilt is invisible (~0.01 px).

Three details in the follow logic are load-bearing, and the first two are traps:
- **The lead offset is CLAMPED below the dead-zone half-extent** (`× 0.8`). Warp parks the car
  behind centre, and the dead zone's *exit* is what triggers the next re-centre — so a lead
  larger than the zone would park the car already outside it and re-trigger on the very next
  frame, forever. The levels genuinely allow that (*Katseluvara edessä* *Erittäin suuri* is 30 %,
  *Vapaa alue* *Erittäin pieni* 5 %), and a cross-setting bound is not expressible in the schema,
  so the clamp lives in QML.
- **Warp has to TAKE map.center away from the Map's own `center:` binding.** That binding tracks
  the car exactly — which *is* lock behaviour — so left in place it keeps warp inert until some
  unrelated assignment (the user's first pan, say) happens to break it.
  `claimCenterForWarp()` assigns the current value imperatively, which is what drops a QML
  binding; it runs on `mapReadyChanged`, on entering warp, and on becoming current, because the
  projection does not exist before `mapReady`. The lock `Binding` at the bottom of the file
  excludes warp mode for the same reason: the two must never both own `center`.
- **The snap-back after a gesture returns to the EXACT car position in both modes**, not to the
  lead point. `returnAnim` eases the zoom back to `mapDefaultZoom` in parallel, so an offset
  computed in pixels at the old zoom would land wrong in geo terms; warp re-applies its own
  offset a moment later, the first time the car leaves the zone.

Two more ways back to the car, both ending in that snap-back (#55):
- **A view switch in the idle window is an unfinished gesture.** Leaving keeps `userControlled`;
  on return the snap-back runs at once if `returnDueMs` passed while away, else after a fresh
  *Keskitysviive*. Dropping back to follow on leaving instead left Lukittu's zoom where the user
  put it and Liukuva's centre too — a parked car sends no position tick to wake `warpStep()`.
- **Liukuva centres a stopped car.** A timer runs while the car's speed is not above 0 (unknown
  counts as stopped — speed, because a parked car's GPS jitters), the map is current and nobody
  is touching it; after *Keskitysviive* it starts the snap-back. It runs once per stop: a
  `running` binding restarts it only when a condition changes.
- `handleGestureActive(true)` stops the snap-back **before** it sets `userControlled`: the
  animation's `onStopped` clears it, and a wheel turn has no active handler to keep it.

`warpStep()` is driven off latitude/longitude changes (which the position Behaviors smooth to
per-frame ticks) and NOT off heading — a bend would otherwise re-centre continuously, and a
turning car is a moving one anyway. The `warpAnim.running` guard is what stops a 700 ms ease
being restarted on each of the ~42 frames it spans, and a car more than one viewport away (a
first fix, a reconnect, a telemetry jump) is snapped rather than eased across half of Finland.

## The basemap — `BasemapPlugin.qml`, `BasemapSwitch.qml`, `MapCoverage.js` (#59)

Every imagery map — both `TeslaMap`s, the Trips map, the *Koti* dialog's and the Weather view's
radar map — is built on `BasemapPlugin`, an OSM plugin with two map types: **MML's 0.5 m
orthophoto as the custom type** (`App.mapTilesUrl`, with the key from `TESLA_HOMEDASH_MAP_API_KEY`;
empty without one) and **EOX's Sentinel-2 cloudless as the satellite type**, from the provider file
`config/map-providers/satellite` that the plugin reads through `qrc:` (keyless, the whole world,
zoom 18 at most). The plugin looks for every built-in type's file there; the six missing ones fall
back to Qt's built-in servers (openstreetmap.org and others), so those types stay valid but are
never picked. The two types' tiles are cached apart, since the plugin names a cached tile by its
type's id, but in one folder (`App.mapTileCacheDir`, below) that every map's cache reads
whole when it starts and deletes down to its own size, first in name order. EOX's files (type 2)
sort ahead of MML's (8), so at Qt's default 50 MiB the MML imagery deleted EOX's tiles on every
start; the plugin sets 300 MiB.

**Qt never expires a cached tile, so the Kartta card has *Tyhjennä karttavälimuisti*** (`clearMapCache`,
an action that asks for a second tap). A tile is kept under its type's id whatever server sent it,
so imagery from a type's earlier server stays on screen until it is deleted: a build that served
EOX as the custom type left blurry 10 m tiles among MML's 0.5 m ones. `Settings::clearMapCache`
deletes the folder and restarts the app, because each map reads the folder once, when its plugin
starts, and keeps the tiles it has shown in memory. The folder holds no index to go stale
(`QGeoFileTileCache` writes its queue files only in code Qt disabled for QTBUG-60581), so an empty
folder is a clean cache. The folder is `App.mapTileCacheDir` — Qt's own default,
`~/.cache/QtLocation/5.8/tiles/osm` — passed to the plugin as `osm.mapping.cache.directory`, so the
maps and the clear name one path.

**A Qt Location bug can leave a tile blank, and `BasemapSwitch` works around it** (report drafted
upstream; no QTBUG number yet). When the satellite type is chosen before its provider file has
loaded (always on the radar map, and on any other map that starts on EOX), the type changes as
the file loads, Qt puts the map on its first type (Street) and `choose()` puts it back. That cancels
the tiles in flight and requests them again, and `QGeoTileFetcher::finished()` matches a reply to
its tile, not to its request: a cancelled reply that arrives late completes the new request with
no data, and the real tile is thrown away. The tile stays blank until the camera next moves (on
the radar map, the tile under the place, on every start). So when `choose()` changes the type in
answer to `supportedMapTypesChanged`, a second later `refetch` pans the map a pixel and back,
which requests any tile left out. The brief Street fetches nothing: its tiles are cancelled before
the fetcher sends them.

`BasemapSwitch` picks the type: **MML while all of the view lies inside MML's coverage, EOX
otherwise.** MML answers outside it with an opaque blank white tile (exactly 668 bytes; tiles off
its grid entirely are a transparent PNG), so no map underneath could show through — the choice has
to be made from where the map is looking. The view is tested as a 6 × 6 grid of points against
`MapCoverage.js`, when the camera rests and every 2 s while it moves (a new type reloads every tile
on screen). Before the map can project, MML is assumed. The radar map sets `allowMml: false`.

`MapCoverage.js` is generated by `scripts/gen-map-coverage.py` from Natural Earth: Finland and Åland
widened 3 km out to sea and kept 3 km back from the land borders, measured to sit inside MML's
coverage — sampled at zoom 14 along the outline, every point had imagery, where at 5 km out the
Ostrobothnian coast and west of Åland already had blanks, and MML's imagery stops at the borders.
So a town right on a land border (Tornio, Utsjoki, Vaalimaa) is shown on EOX. A point tests only
the edges in its 0.05° latitude band: 0.014 ms for the 36 points on the dev box, against 0.9 ms
testing every edge.

## The Kartta view's layers — `views/MapView.qml`

The full-screen map carries five layers, each switched from the menu behind the round button in
the bottom-right corner (`MapLayerMenu.qml`; a press outside the open menu closes it and goes no
further). Their states are **hidden local settings** in the Kartta card (`mapLayerStats`,
`mapLayerRadar`, `mapLayerRoute`, `mapLayerCameras`, `mapLayerWarnings`), written straight from the
menu, so a choice outlasts a restart without a row in the Options view. **The dashboard's card has
its own** menu and switches (`homeMapLayer*`) for the radar, the route and the cameras — not the warnings or
the data card, which need the full screen — with no radar timeline (its minimap carries the time),
and a camera's tap opens the same dialog over the dashboard. Each view names its rows
(`MapLayerMenu.layers`); the menu sits in its map's corner, full-screen or the card. A row can carry
options nested under it while it is on — the ways the layer shows (`modes`, switches) and one
`choice` — and the layer is on only with one of its modes on: switched on with all of them off it
shows the first, and the last one switched off switches it off. `TeslaMap`'s `show*` default off.
OSM's place names are no layer: the imagery has no labels of its own, so every map draws them
(*Place names*, below).

- **Ajotiedot** — `MapLiveStats.qml` in the bottom-left: speed, battery, range and outside
  temperature on frosted glass, read straight off `Tesla`. The car reports the outside temperature
  only while it is awake, so an hour after it went offline (`Tesla.asleepSince`, the backend's state
  event time, which a repeated offline event does not move) the temperature is FMI's for the place —
  the weather document's `now.temp`, under the same *ULKONA* caption — until the car is back
  online. The backend sends `VehicleOnline` on every change, so the card follows the car's sleep
  and waking with no reconnect (`backend/src/tesla_service/CLAUDE.md`).
- **Sadetutka** — `items/weather/RadarLayer.qml`, the Weather view's radar loop and lightning, on
  both maps in two ways, either or both, nested under the row (#86): *Minikartta* (on by default)
  and *Kartan päällä* (`mapRadarInset` / `mapRadarOverlay`, the dashboard's `homeMapRadar*`). Laid
  over a map at the dashboard card's zoom, one of the composite's ~500 m cells is a third of the
  card, and a light shower turns all of it green — hence the minimap.
  - **The minimap** (`items/weather/RadarInset.qml`, its header the reference) is a small north-up
    map in a corner — the card's bottom-left, clear of the controls and, heading-up, of the road
    ahead; Kartta's top-right, larger — three zoom levels out from the big map and never closer
    than zoom 8, where a cell is about two pixels. It is centred on the big map's centre in whole
    pixels of its own, so a following map redraws it about once in ten seconds at highway speed;
    it outlines the big map's view once that is 16 px a side, and marks the car at each fix. The
    frame's time is in its corner and the loop's ticks along its bottom edge, so the dashboard's
    card needs no timeline. A tap opens the Weather view (`Navigation`, `../../CLAUDE.md`).
  - **The overlay** lies under every other layer at 55 % opacity (`RadarLayer.frameOpacity`; the
    lightning stays opaque), undimmed. With the minimap on too it plays in step with it
    (`RadarLayer.follow`: the minimap's frame list, frame and fade), so the two never show
    different times. This map turns heading-up, so each frame is fetched for the bounding box of all four
    screen corners and turned with the map (`Image.rotation`), and the lightning is drawn in screen
    pixels (`LightningLayer`, `core/CLAUDE.md`) and carried the same way. And it keeps moving while
    it follows the car, so it fetches a 25 % margin round the view, no finer than 150 m a pixel and
    at most 1024 px a side — every frame of the loop stays decoded, so the size is the memory.
  - **Historia** (`mapRadarHistory` / `homeMapRadarHistory`, minutes: *Uusin*, 15, 30 or 60, the
    choices in `Theme.radarHistoryChoices`; 15 by default) is how far back both loop, at FMI's
    5-minute steps. The steps share about 4.5 s, so 15 minutes plays 1.5 s a frame and an hour
    never faster than the Weather card's 600 ms; the newest frame holds 3.5 s. *Uusin* is
    `RadarLayer.latestOnly`: no loop, no older frame fetched, and only the frame's time on the bar.
  - **Each step crossfades** into the next over 400 ms (`RadarLayer.fadeMs`), the Weather card's
    loop too; the wrap back to the oldest frame and a seek are cuts. It blends the two pictures
    pixel by pixel in one draw (`resources/shaders/radarfade.frag`), because FMI draws light rain
    translucent (alpha 38–204): two Images laid over each other would brighten it mid-fade, a
    pulse on every step. The frames' Images are hidden and only hand their pictures to the
    shader; a step to a frame of another box (one fetched for a new view) is a cut. A blend
    shows real frames only — it does not guess where the rain was between them.
  `WeatherRadarControls` stands upright on Kartta's left edge above the data card, working the
  minimap's loop while it shows (`TeslaMap.radar`), else the overlay's. The Weather card's
  *Vain uusin* checkbox on its own bar (`weatherRadarLatestOnly`) is that card's alone.
- **Ajettu reitti** — the drive under way, or while the car is parked the last trip, whole (no
  tail), from `CurrentDrive` (`core/trip/currentdrive.hh`),
  which asks the backend only while a map on screen draws it — each `TeslaMap` holds it with
  `retain()` / `release()`, since the dashboard's and the Kartta view's overlap while one view is
  built and the other left. The backend's `TRIP_GET_CURRENT` finds it with the Trips view's own
  detection, a drive counting from the first metres (no minimum distance), and each live fix is
  added to a drive with the speed of the moment; the car leaving Park clears the last trip for
  the next drive. It is **coloured by speed** (`Theme.speedColor`), drawn by `SpeedRoute.qml` as
  the Trips map's trip is, and in two parts: `CurrentDrive.route`, which ends at the fix before the
  newest, and a two-point `MapPolyline` tail from there to the car arrow's eased position, in the
  current speed's colour. The arrow takes a second to glide to each new fix, so a line through the
  newest fix would run ahead of the car. **The route is not a `MapPolyline`**: one is rebuilt
  (projected, clipped to the view, triangulated) on every camera change
  (`QDeclarativePolylineMapItemPrivateCPU::afterViewportChanged`), which a following map makes
  every frame, and colouring would take a line per speed band. `SpeedRoute` is Shapes in a
  `GeoFrame` (below) — a `ShapePath` per 15 km/h band holding that band's runs — moved, scaled and
  turned with the map, so a frame costs one projection. Their geometry is C++'s, `RouteBands`
  (`../../core/CLAUDE.md`), in chunks: a reply builds the whole route once, and a live fix extends
  the last chunk of at most 200 segments, which alone is processed again. The strokes are
  `cosmeticStroke`, the same width on screen at every zoom with no path processed again, and the
  Shapes are `asynchronous`, so a long trip is processed off the GUI thread. The Trips map gives it
  a dark casing under the line (`casingColor: Theme.tripRouteCasing`): all of the casing goes under
  all of the colour, or a chunk's casing would cover the end of the one before.
- **Kelikamerat** — Fintraffic's road weather cameras (Digitraffic, CC BY 4.0, credited in the README
  and the dialog), `RoadCameras.qml`: the station list (`RoadCameraStations.qml`, ~800 cameras, 37 kB
  gzipped), a QML singleton so each display holds one for both maps and the Weather view, fetched
  straight from `tie.digitraffic.fi` (`ensure()`) when a layer or the view comes live and the list is
  missing or six hours old; and a marker for each camera in view from zoom 9 — at most 60, none within
  30 px of another. A tap opens `RoadCameraPopup.qml`:
  the station's pictures, one per direction it looks (a tab each), and the nearest road weather
  station's readings (`nearestWeatherStationId`: road condition, road and air temperature, wind,
  rain, visibility, humidity), all fetched when it opens. Pictures are taken every ten minutes; the
  time is in the image URL so a new one is not served from the cache. Requests carry the
  `Digitraffic-User` header Digitraffic asks for. The dialog is centred, on frosted glass over its
  view (the dashboard frosts all of itself, `surface`, through a FrostLayer made while the dialog
  shows; Kartta's dialog has one of its own beside the panels' shared one, since a dialog's frost
  is stronger), and the map under it takes no gesture while it is open (`interactive`).
  The Weather view's *Nyt* card has a *Kelikamerat* button that opens the same dialog on the ten
  cameras nearest the weather document's place (`RoadCameraStations.nearest`, great-circle
  distance), nearest first, stepped through with the arrows in its corner and each one's distance
  under its name; the view holds that list and the dialog (`views/WeatherView.qml`), frosting the
  whole dashboard, whose radar map takes no gesture meanwhile. Above the readings, wherever it is
  opened, `RoadCameraMap.qml` shows where the camera is: a still north-up map centred on it (the
  reply's `geometry`) at zoom 12 — where suburbs are named — with the place names and the home, and
  the camera's marker in the accent over the home. It takes no input. Each view's dialog builds its
  map the first time it opens and then keeps it, holding its tiles.
- **Säävaroitukset** (a demo, on by default) — FMI's warnings in force as areas,
  `items/weather/WarningAreas.qml`: each warning's regions from the weather document's `shapes`
  (`backend/src/weather_service/CLAUDE.md`), filled faintly in its colour and outlined, in a
  `GeoFrame` from the middle of Finland. `WarningLegend.qml` in the top-left corner names them, and
  a tap opens them whole in `WeatherWarningsPopup` — the dialog the Weather view's strip and the
  dashboard's hour badges open too, each view hosting its own on frosted glass as the camera dialog
  is, but at reading height (centred on 40 % of the height) rather than centred.

**`GeoFrame.qml` carries drawing in metres with the map.** Its coordinates are EPSG:3857 metres from
an origin; it is moved, scaled and turned with the camera, so a `Shape` in it is triangulated once
and then only transformed — a frame costs one projection, where a `MapPolyline` is rebuilt every
camera change. A stroke keeps its width on screen as a `cosmeticStroke`, never processed again
(`SpeedRoute`), or by taking `px / pixelsPerMetre`, processed again on every zoom change
(`WarningAreas`).

**Zoom buttons** — `MapZoomButtons.qml`, + over − on a glass pill, over the layer button on both
maps. On the dashboard's card the two are out of sight until the map is touched (`MapTouchReveal`:
`TeslaMap.touched` comes from a passive `PointHandler`, so a press that never moves counts too and
the pan still gets the gesture), fading 4 s after the last touch — held while the layer menu is
open. A step is `TeslaMap.stepZoom`: a whole level from where the map is, **written as
`mapDefaultZoom`**, so the snap-back after a gesture returns there and the other map follows
(`onDefaultZoomChanged`: eased if it is on screen, set if hidden, left alone mid-gesture). Steps
stay within the setting's 10–19.

**Inside the `Map`, the layers are ordered by `z`**: the radar overlay's Loader 1, the warnings 1
(declared after it), the route 2, the names 3, the cameras 4, the home 5, the car arrow 10. The
radar's minimap is no child of the `Map`: it lies over all of it, under the card's corners.

**The home** — `HomeMarker.qml`, the home icon in a dark disc with *Koti* under it, at the
*Yleinen › Sijainti › Koti* location (`Settings.valueOf("home")`, a backend setting), on both
`TeslaMap`s and the Trips map, always, while a home is set. It is no layer: there is one of it.

**`MapCameraWatch.qml` is the one cue to redo work that depends on the view**: it fires once the
map has rested and every so often while it keeps moving (RadarLayer 0.4 s / 1.5 s, PlaceLabels and
RoadCameras 0.5 s / 2 s), so a map that follows the car does not refetch or re-choose every frame. Plain items declared inside a `Map` are its children and draw over the tiles,
but `PlaceLabels` (a `MapItemView`) adds its items after everything declared, so declaration order
alone would put the names over the car.

### Place names — `core/map/placenames.{hh,cpp}`, `PlaceLabels.qml`

The imagery has no labels, so OSM's `place=*` names are fetched from the Overpass API (keyless,
ODbL) **per slippy-map tile at three tile zooms** — cities and towns per z6 tile, villages, suburbs
and islands per z9, hamlets, neighbourhoods and smaller per z12 — each kind labelled from its own
map zoom (`kKinds`). A tile is one request, ever: it is kept on disk
(`~/.cache/Tesla-Homedash/place-names/<z>-<x>-<y>.json`, an empty tile too) and refreshed after half
a year, so a daily route costs nothing after the first drive. **Overpass is slow and shared** —
measured 30–60 s for one tile from overpass-api.de, which answers a second request soon after with
a 502 — so the store asks one tile at a time, two seconds apart, the newest view's tiles first, and
drops a tile no view has wanted for two minutes. A failed request moves on to the other of two
public servers (`kServers`), and only when both have failed in a row does the queue pause, 30 s
doubling to 10 min. **Don't add maps.mail.ru back**: it is VK's (Russian-operated) mirror, and every
query hands it the area being viewed — around the home and the car — plus the IP; the user had it
removed. Requests are GETs because overpass.kumi.systems answers a POST with a 500. A new area's
names therefore appear within a minute or so of the map first showing it.

`PlaceLabels` asks the store for the area a little beyond the screen when the map rests, every 2 s
while it moves and when a tile arrives (`PlaceNames.revision` — a `Q_INVOKABLE` binds to nothing),
then places names most important first and leaves out one whose box would overlap a name already
placed, 40 at most. Each is a `MapQuickItem` with no `zoomLevel`, so it stays upright when the map
turns heading-up (the car arrow's fact above) — the reason for drawing names rather than laying a
label tile layer over the imagery. The Trips map draws them too, always, under its route and pins
(`items/trip/TripMap.qml`). OSM is credited in the README, not on the map: OSMF's attribution
guidelines ask for it only where a map is used publicly, and the dashboard is a private display.
Water and road names are not drawn.
