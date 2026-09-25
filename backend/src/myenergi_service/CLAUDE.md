# `myenergi_service/` — the Zappi charger

The `CHARGER_STREAM` sub-ids are in `../utils/CLAUDE.md`; the sessions and costs built on this data
are in `../charging_service/CLAUDE.md`.

- **`myenergi_service.py`** (`MyEnergiService`) polls a myenergi Zappi via `pymyenergi` (cloud
  digest auth), broadcasts its live state as `CHARGER_STREAM`, and logs to the `myenergi_data`
  measurement: `GridPower` + `ChargePower` **every poll** (gap-free for the past-hour graphs and the
  month home-import integral) and `ChargeAdded` (the session accumulator) **while charging**. Mirrors
  `WeatherService` (initial poll + APScheduler job, last frame cached for `stream_everything`), with
  two poll cadences (idle/active, config-driven — default **60 s idle / 20 s active** to stay under
  the myenergi cloud's rate limit; 10 s throttled us with 429s). `__apply_interval` is the single
  place that reschedules the job: it picks the active/idle base then stretches it by a **capped
  exponential backoff** (`2**consecutive_failures`, ≤ 5 min) whenever a poll fails, snapping back on
  the first success. This matters because every failed request flips pymyenergi's `do_query_asn` back
  on, so the next poll fires two requests (director + status) — polling a failing endpoint at full
  cadence deepens a throttle. Refresh/resolve failures are logged via the module helper
  `_describe_exception`, which surfaces the HTTP status a `MyenergiException` otherwise hides (its
  ctor stores it in `.code`/`.message` but stringifies to `""`, so the old `str(e)` logged a blank
  reason — issue #18). Optional — skipped when the `.env` creds are unset.
