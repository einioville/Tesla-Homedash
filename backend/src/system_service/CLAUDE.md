# `system_service/` — the maintenance dashboard (issue #39)

`system_metrics.py` is pure stdlib against `/proc` (no psutil: nothing here is worth an ARM build and
a pin). `SystemStatusService` serves `SYSTEM_GET_STATUS` — **request/response, not a broadcast, and
deliberately NOT `register_service`d**: the Options view is open a fraction of the time, and sampling
`/proc` for every client to feed a screen nobody is looking at is pure waste. Details that matter:
- `/proc/net/dev` is parsed with `partition(":")`, not `split()` — a counter wide enough to touch the
  colon prints `eth0:1234567890` and shifts every column by one.
- CPU is a **delta**, so a sample older than 30 s is discarded and a fresh 250 ms window taken; a
  half-hour-old sample would report the average over that half hour.
- Per-service health is duck-typed **`health()`**, the same pattern as `stream_everything()` and
  `apply_config()`, so each service answers from state it already keeps. A probe that raises or hangs
  is reported as one broken service, never as a failed request.
- Error tallies come from **`ErrorCounter`**, a `logging.Handler` attached to the same
  `_SERVICE_LOGGERS` allow-list as the stdout handler (those loggers set `propagate = False`, which
  is what rules out double counting).
