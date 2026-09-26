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

## `debug_logging.py` — the temporary debug log (Ylläpito > Vianetsintä)

`DebugLogging` applies `logging.debugEnabled` / `logging.debugMinutes` (hook `logging`) through
`utils.logger_configurator.set_debug_logging()`, and the frontend follows the same key out of the
schema, so **one switch covers both halves**. It is temporary on purpose — at DEBUG the backend logs a
line per telemetry property and rotates the Pi's journal fast enough to destroy the history the log
was turned on to collect:
- **Expiry writes the key back through `ConfigService.apply_write()`**, not by lowering the level
  alone: the same validated path a tap takes, so `config.json`, every open Options view (the schema
  broadcast) and the frontend's level all change together. The write re-enters `apply_config()`,
  which is why the timer task drops its own reference before writing.
- **A restart does not end it, but cannot make it permanent.** `start_services` calls
  `apply_config()` once, so a log left on comes back on for one more full duration — debugging a
  startup problem needs exactly that. Only a crash loop faster than the duration would keep it on.
- `spotipy` stays pinned at INFO or above even while everything else is at DEBUG
  (`../utils/CLAUDE.md`).
- `health()` reports the log as `warn` while it is on, so the Järjestelmän tila card shows it.

