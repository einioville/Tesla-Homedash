# `items/tesla/` — Tesla cards and the map

## Map tuning and follow modes — `TeslaMap.qml`

**Map tuning** is the *Kartta* card in **Datan visualisointi**, beside the *Graafit* card whose
knobs it deliberately mirrors — `mapSensitivity` is `graphSensitivity`'s twin, and
`mapFollowResumeSec` sits where `graphSettleMs` does. Seven schema entries plus seven
`Theme.map*` bindings; **no protocol change and no C++ change at all**, since everything is
consumed by `items/tesla/TeslaMap.qml` (the dashboard card AND the full-screen `MapView`).
`mapSensitivity` alone also reaches `items/trip/TripMap.qml`, which carries the same
pan/pinch/wheel handlers. Two facts verified against the Qt 6.11.1 sources on disk, both
load-bearing:
- **`Map.bearing` works here only because the OSM plugin opts in.** The docs say changing it on
  a plugin that does not support bearing "will have no effect" — silently — and
  `plugins/geoservices/osm/qgeotiledmappingmanagerengineosm.cpp` calls `setSupportsBearing(true)`,
  which is what makes *Ajosuunta ylös* possible at all. `setBearing` runs the value through
  `sanitizeBearing` (an fmod into `[0,360)`), so feeding it an unwrapped angle is safe.
- **`MapQuickItem.rotation` is SCREEN-space and does NOT turn with the map.** With the item's own
  `zoomLevel` unset, `updatePolish()` takes its "rendering screen-aligned" branch and applies an
  identity matrix. So the car arrow is `rotation: heading - map.bearing`: that is plain `heading`
  at bearing 0 (north-up — exactly the original behaviour) and ~0 in heading-up, where the map
  has already turned under it. Binding it to `heading` alone would double-rotate the arrow.

Three details in the follow logic are load-bearing, and the first two are traps:
- **The lead offset is CLAMPED below the dead-zone half-extent** (`× 0.8`). Warp parks the car
  behind centre, and the dead zone's *exit* is what triggers the next re-centre — so a lead
  larger than the zone would park the car already outside it and re-trigger on the very next
  frame, forever. The schema ranges genuinely allow that (lead up to 30 %, zone down to 5 %), and
  a cross-setting bound is not expressible in the schema, so the clamp lives in QML.
- **Warp has to TAKE map.center away from the Map's own `center:` binding.** That binding tracks
  the car exactly — which *is* lock behaviour — so warp looks completely inert until some
  unrelated assignment happens to break it (historically, the user's first pan).
  `claimCenterForWarp()` assigns the current value imperatively, which is what drops a QML
  binding; it runs on `mapReadyChanged`, on entering warp, and on becoming current, because the
  projection does not exist before `mapReady`. The lock `Binding` at the bottom of the file
  excludes warp mode for the same reason: the two must never both own `center`.
- **The snap-back after a gesture returns to the EXACT car position in both modes**, not to the
  lead point. `returnAnim` eases the zoom back to `mapDefaultZoom` in parallel, so an offset
  computed in pixels at the old zoom would land wrong in geo terms; warp re-applies its own
  offset a moment later, the first time the car leaves the zone.

`warpStep()` is driven off latitude/longitude changes (which the existing Behaviors smooth to
per-frame ticks) and NOT off heading — a bend would otherwise re-centre continuously, and a
turning car is a moving one anyway. The `warpAnim.running` guard is what stops a 700 ms ease
being restarted on each of the ~42 frames it spans, and a car more than one viewport away (a
first fix, a reconnect, a telemetry jump) is snapped rather than eased across half of Finland.
