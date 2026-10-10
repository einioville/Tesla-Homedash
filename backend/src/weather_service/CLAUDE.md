# `weather_service/weather_service.py` — FMI weather

`WeatherService` fetches the current-hour FMI observation + the next hours' harmonie forecast
(`fmiopendata`, run in an executor), serialises them into a `WEATHER_FORECAST` frame, broadcasts,
and caches the last frame to replay to new clients. Refreshes every 15 min via APScheduler.
The current-hour **banner** takes temperature + wind from the real observation, but the observation
station typically reports neither precipitation nor cloud cover — so those two are **backfilled from
the harmonie forecast's current-hour row** (the model retains the current hour, so no caching is
needed). `__fetch_observation` walks observation slots newest→oldest and uses the most recent one
with a valid air-temperature reading (avoiding the all-NaN padding slots fmiopendata returns).
**Talks to:** FMI open data, `Server`.

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
>   caching. The frontend replaces its whole forecast model per frame, so a banner-only frame blanks
>   all five cards *and* poisons `__last_forecast` for every later reconnect. Stale-but-complete
>   beats half-blank.
