# `weather_service/weather_service.py` — FMI weather

`WeatherService` fetches the current-hour FMI observation + the next hours' harmonie forecast
(`fmiopendata`, run in an executor), serialises them into a `WEATHER_FORECAST` frame, broadcasts,
and caches the last frame to replay to new clients. Refreshes every 15 min via APScheduler. Only the
frozen `frontend/` reads that frame; `frontend_v2` reads `WEATHER_VIEW` (below) and ignores it.
The current-hour **banner** takes temperature + wind from the real observation, but the observation
station typically reports neither precipitation nor cloud cover — so those two are **backfilled from
the harmonie forecast's current-hour row** (the model retains the current hour, so no caching is
needed). `__fetch_observation` walks observation slots newest→oldest and uses the most recent one
with a valid air-temperature reading (avoiding the all-NaN padding slots fmiopendata returns).
**Talks to:** FMI open data, `Server`.

**The location is FMI query arguments** (`Config.weather_location`): the home's coordinates
(`{"latlon": "61.44970,23.85860"}`) once one is set in the Options view, else the `weatherPlace`
name (`{"place": "Tampere"}`). FMI takes coordinates as they are — the timeseries service, the
harmonie WFS forecast — and names the point after its nearest place (*Hervanta*), which becomes the
document's `meta.place`. The one exception is the WFS observation query, which answers coordinates
with nothing: with a home, that query is skipped and the frozen frontend's banner uses the
forecast's current hour, as it does whenever no observation arrives. The home's write runs
`apply_config()`, which refetches at once.

**The hour's rain needs its own query.** harmonie's default `PrecipitationAmount` is the rain
**accumulated since the model run started** — it only ever grows — not the hour's, so the forecast
is two queries run together: the default fields, and `parameters=Precipitation1h`, whose value
replaces the default's under the same name ("Precipitation amount"). Sent as the accumulation, the
cards showed a running total that rounding to whole mm mostly hid. If the second query fails, the
hours go out with no rain rather than the accumulated amount.

> **Load-bearing invariants — do not break:**
> - **Never call `fmiopendata.wfs.download_stored_query`.** Its fetch helper is `requests.get(url)`
>   with **no timeout** and no way to pass one. A stalled FMI response (connection accepted, partial
>   body, then silence — no FIN/RST) parks the caller in `read()` *forever*; in production that burned
>   an executor thread and killed weather for 16 days. `__download_stored_query` +
>   `__fetch_and_parse` replace it: the same URL (`STORED_QUERY_URL + query_id`, args as aiohttp
>   `params` so non-ASCII places like `Ryttylä` percent-encode) fetched with an explicit
>   `_FMI_TIMEOUT`, then handed to fmiopendata's own `MultiPoint` parser in an executor. Any failure
>   logs a WARNING and returns `None`. An `asyncio.wait_for(_FETCH_DEADLINE_SECONDS)` wraps both.
> - **Keep `max_instances` ≥ 2 + a real `misfire_grace_time` on the refresh job.** APScheduler's
>   default `max_instances=1` turns one wedged run into a permanent outage — every later tick is
>   refused with *"skipped: maximum number of running instances reached (1)"*.
> - **Schedule the job before the initial fetch** in `run()`, so a failed/slow first fetch can't
>   leave the service with no periodic refresh at all.
> - **A cycle with no future forecast hours is a failed cycle** — return without broadcasting or
>   caching. The frozen frontend replaces its whole forecast model per frame, so a banner-only frame blanks
>   all five cards *and* poisons `__last_forecast` for every later reconnect. Stale-but-complete
>   beats half-blank.

## `weather_view.py` — the Weather view's document (`WEATHER_VIEW`)

`frontend_v2`'s Weather view, and the dashboard panel that reuses its hourly card, read one JSON
document instead of `WEATHER_FORECAST`, which stays for the frozen frontend. `WeatherViewBuilder`
builds it on its own job, **every 10 minutes at :04, :14, …** — FMI's 10-minute observations land a
few minutes after their slot — under the same scheduler rules as the forecast job, with
`_VIEW_DEADLINE_SECONDS` around the whole build and `_FMI_TIMEOUT` on every request.

- **Source: FMI's `timeseries` service (JSON), not WFS**, so no fmiopendata parse. The parts, fetched
  in parallel: the place (name, coordinates, its own zone — cached per location), observations
  (`numberofstations=5`, `maxdistance=50 km`, each field from the nearest station reporting it — the
  place's own station rarely measures everything), the **edited** forecast (~230 h, what
  ilmatieteenlaitos.fi shows), HARMONIE's `RadiationGlobal` for the hour, sun and moon, and the CAP
  warnings feed, each tested against the place's coordinates (`appliesHere`).
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
- **A failed part keeps its last good value**; parts are dropped when the location changes. A forecast
  kept from an earlier cycle is trimmed to start at the current hour. No forecast hours at all → no
  frame, the previous one stays (the forecast job's rule). A build that finishes after the location
  changed is discarded.
- **The UV index is an estimate** — FMI publishes none: Madronich's clear-sky index from the sun's
  elevation × HARMONIE's radiation against a Haurwitz clear-sky model. Not radiation alone, which
  overstates a low spring or autumn sun two to three times.
- Times in the document are in the configured zone (`epochtime` converted; the astro rise/set strings
  are in the place's zone and converted too). `now.time` is the newest observation used — the view's
  *havainto* — or `null` when no observation has arrived yet.
