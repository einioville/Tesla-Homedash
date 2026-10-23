# `weather_service/` — FMI weather

`WeatherService` (`weather_service.py`) keeps one document current: the Weather view's
(`WEATHER_VIEW`), which `WeatherViewBuilder` (`weather_view.py`, below) builds from FMI open data. It
rebuilds it **every 10 minutes at :04, :14, …** — FMI's 10-minute observations land a few minutes
after their slot — broadcasts it, and caches the last frame to replay to new clients.
**Talks to:** FMI open data, `Server`.

**The location is FMI query arguments** (`Config.weather_location`): the home's coordinates
(`{"latlon": "61.44970,23.85860"}`) once one is set in the Options view, else the `weatherPlace`
name (`{"place": "Tampere"}`). FMI takes coordinates as they are and names the point after its
nearest place (*Hervanta*), which becomes the document's `meta.place`. The home's write runs
`apply_config()`, which drops the cached frame — it describes the old place — and refetches at once.
**`zone_at(lat, lon)`** answers the IANA zone FMI gives a point (`localtz`), or `None` when it could
not say; `ConfigService` awaits it for a home being written, before saving it
(`../config_service/CLAUDE.md`, *Location and timezone*).

> **Load-bearing invariants — do not break:**
> - **Every FMI request carries `_FMI_TIMEOUT`**, an explicit socket-level ceiling. A stalled FMI
>   response (connection accepted, partial body, then silence — no FIN/RST) otherwise parks the
>   request in `read()` *forever*: a library call with no timeout burned an executor thread in
>   production and killed weather for 16 days. `_VIEW_DEADLINE_SECONDS` around the whole build
>   covers anything the per-request ceiling does not.
> - **Keep `max_instances` ≥ 2 + a real `misfire_grace_time` on the refresh job.** APScheduler's
>   default `max_instances=1` turns one wedged run into a permanent outage — every later tick is
>   refused with *"skipped: maximum number of running instances reached (1)"*.
> - **Schedule the job before the initial fetch** in `run()`, so a failed/slow first fetch can't
>   leave the service with no periodic refresh at all.

## `weather_view.py` — the Weather view's document (`WEATHER_VIEW`)

`frontend_v2`'s Weather view, and the dashboard panel that reuses its hourly card, read this one JSON
document. `WeatherViewBuilder` builds it on `WeatherService`'s job (above), with
`_VIEW_DEADLINE_SECONDS` around the whole build and `_FMI_TIMEOUT` on every request.

- **Source: FMI's `timeseries` service (JSON).** The parts, fetched in parallel: the place (name,
  coordinates, its own zone — cached per location), observations (`numberofstations=5`,
  `maxdistance=50 km`, each field from the nearest station reporting it — the place's own station
  rarely measures everything), the **edited** forecast (~230 h, what ilmatieteenlaitos.fi shows),
  HARMONIE's `RadiationGlobal` for the hour, sun and moon, and the CAP warnings feed, each tested
  against the place's coordinates (`appliesHere`).
- **A warning names the areas that cover the place** (`hereAreas`, from each area's own polygons).
  The headline names the warning's whole region and can lead with one far away — *Keltainen
  liikennesää: Kainuu sekä paikoin maan keskiosa* covers Tampere through Pirkanmaa, its sixth area —
  so the Weather view's strip shows `hereAreas`, and a tap opens every warning that applies, whole
  (`frontend_v2/items/weather/WeatherWarningsPopup.qml`, which the dashboard's hour badges open
  too). `areas` keeps only the first four.
- **Only warnings still in force are sent.** The feed keeps one for a while after its `expires` (a
  *Liikennesää* that ended at 10.00 was still there at 11.27), so the builder drops those; the onset
  and expiry go as text (`onset`, `expires`), the times kept server-side for the hour marks below.
- **Each forecast hour a warning covering the place is in force in carries its colour** (`warning`:
  the strongest, yellow < orange < red; absent otherwise) — the dashboard's hourly card draws a badge
  on those hours (`frontend_v2/items/weather/WeatherChart.qml`, `warningBadges`). An hour counts if
  the warning overlaps any of it.
- **A warning carries its areas for the map** (`shapes`: rings of `[lat, lon]`), which the Kartta
  view draws (`frontend_v2/items/weather/WarningAreas.qml`). FMI's polygons run to ~16 000 points
  over seven warnings; Douglas–Peucker at ~0.5 km and rounding to ~100 m (`_simplify`,
  `_SHAPE_*`) leave ~4 000 points, ~70 KB of the document. The full polygons stay server-side for
  `hereAreas`.
- **The Sää status card reports the latest cycle** (`WeatherService.health`, #61): `warn` while the
  last view cycle timed out or produced no document, or left parts at their last good values
  (`WeatherViewBuilder.failed_parts`, named in Finnish by `_PART_NAMES`), `ok` again after the
  next good one. The old frames stay on screen meanwhile; *Päivitetty* says how old they are.
- **A failed part keeps its last good value**; parts are dropped when the location changes. A forecast
  kept from an earlier cycle is trimmed to start at the current hour. No forecast hours at all → no
  frame, the previous one stays: stale but complete beats half-blank. A build that finishes after
  the location changed is discarded.
- **Precipitation says what falls** (#68): each hour's `precipForm` — `rain`, `sleet` or `snow` —
  from FMI's `potentialprecipitationform` (drizzle, freezing rain and hail count as rain), each
  day's `snow` (the mm of water its snow hours bring, beside the day's total `precip`), and the now
  block's from the station's present-weather code when it says, else the forecast hour's. Amounts
  stay mm of water; the frontend shows snow as estimated cm (`WeatherUtil.js`, `SNOW_CM_PER_MM`,
  FMI's 1 mm ≈ 1 cm).
- **The UV index is an estimate** — FMI publishes none: Madronich's clear-sky index from the sun's
  elevation × HARMONIE's radiation against a Haurwitz clear-sky model. Not radiation alone, which
  overstates a low spring or autumn sun two to three times.
- Times in the document are in the configured zone (`epochtime` converted; the astro rise/set strings
  are in the place's zone and converted too). `now.time` is the newest observation used — the view's
  *havainto* — or `null` when no observation has arrived yet.
