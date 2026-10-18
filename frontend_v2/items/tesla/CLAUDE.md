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
is not a setting: `AppConfig` picks MML's orthophoto when
`TESLA_HOMEDASH_MAP_API_KEY` is in the environment or `.env`, else EOX Sentinel-2
(`frontend_v2/CLAUDE.md`). Two facts verified against the Qt 6.11.1 sources on disk, both
load-bearing:
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

`warpStep()` is driven off latitude/longitude changes (which the position Behaviors smooth to
per-frame ticks) and NOT off heading — a bend would otherwise re-centre continuously, and a
turning car is a moving one anyway. The `warpAnim.running` guard is what stops a 700 ms ease
being restarted on each of the ~42 frames it spans, and a car more than one viewport away (a
first fix, a reconnect, a telemetry jump) is snapped rather than eased across half of Finland.

## The Kartta view's layers — `views/MapView.qml`

The full-screen map carries four layers, each switched from the menu behind the round button in
the bottom-right corner (`MapLayerMenu.qml`; a press outside the open menu closes it and goes no
further). Their states are **hidden local settings** in the Kartta card (`mapLayerStats`,
`mapLayerRadar`, `mapLayerRoute`, `mapLayerPlaces`), written straight from the menu, so a choice
outlasts a restart without a row in the Options view. The dashboard's card shows none of them —
`TeslaMap`'s `showRadar` / `showRoute` / `showPlaceNames` default off.

- **Ajotiedot** — `MapLiveStats.qml` in the bottom-left: speed, battery, range and outside
  temperature on frosted glass, read straight off `Tesla`.
- **Sadetutka** — `items/weather/RadarLayer.qml`, the Weather view's radar loop and lightning, over
  this map too, undimmed, with `WeatherRadarControls` upright on the left edge above the data card.
  The loop is the last quarter hour (four frames, 1.5 s each, the newest held 3.5 s) rather than the
  Weather card's hour. Its header is the reference; two more things differ from the Weather card. This map turns heading-up, so each frame is fetched for the
  bounding box of all four screen corners and turned with the map (`Image.rotation`), and the
  lightning is painted in screen pixels and carried the same way. And it keeps moving while it
  follows the car, so it fetches a 25 % margin round the view, no finer than 150 m a pixel
  (the composite's cells are about 500 m) and at most 1024 px a side — all thirteen frames stay
  decoded, so the size is the memory.
- **Ajettu reitti** — the drive under way, from `CurrentDrive` (`core/trip/currentdrive.hh`): the
  backend's `TRIP_GET_CURRENT` finds it with the Trips view's own detection (the last trip of the
  past day, unless parked longer than `min_stop_minutes`), and each live fix is added to it. It is
  **drawn as two `MapPolyline`s**: `path`, which ends at the fix before the newest, and a two-point
  tail from there to the car arrow's eased position. The arrow takes a second to glide to each new
  fix, so a single line through the newest fix would run ahead of the car. A `MapPolyline` is
  rebuilt (projected, clipped to the view, triangulated) on every camera change
  (`QDeclarativePolylineMapItemPrivateCPU::afterViewportChanged`), which is why the tail — the part
  that changes every frame — is its own two-point line.
- **Paikannimet** — `PlaceLabels.qml` over the `PlaceNames` store (below), issue #54's first step.

**Inside the `Map`, the layers are ordered by `z`**: the radar's Loader 1, the route 2, the names
3, the car arrow 10. Plain items declared inside a `Map` are its children and draw over the tiles,
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
drops a tile no view has wanted for two minutes. A failed request moves on to the next of three
public servers (`kServers`; maps.mail.ru answered the same tile in 15 s), and only when all three
have failed in a row does the queue pause, 30 s doubling to 10 min. Requests are GETs because
overpass.kumi.systems answers a POST with a 500. A new area's names therefore appear within a
minute or so of the map first showing it.

`PlaceLabels` asks the store for the area a little beyond the screen when the map rests, every 2 s
while it moves and when a tile arrives (`PlaceNames.revision` — a `Q_INVOKABLE` binds to nothing),
then places names most important first and leaves out one whose box would overlap a name already
placed, 40 at most. Each is a `MapQuickItem` with no `zoomLevel`, so it stays upright when the map
turns heading-up (the car arrow's fact above) — the reason for drawing names rather than laying a
label tile layer over the imagery. Not done yet (#54): the Trips map, water and road names, and an
OSM credit somewhere (the map hides its copyright notice).
