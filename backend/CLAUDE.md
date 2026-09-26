# `backend/` — the asyncio services

The root `CLAUDE.md` is always loaded alongside this file, so nothing here repeats it. Each service
directory under `src/` carries its own `CLAUDE.md` with that service's load-bearing details — read
it before changing the service.

## Service orchestration

The backend is entirely asyncio. `start_services.main()` constructs every service,
calls `_register_handlers` and `register_service` on the `Server`, runs
`vehicle.init_async_dependent()`, then **`asyncio.gather`s the run tasks**: telemetry, the TCP
server, `MediaManager.get_run_task()`, `WeatherService.get_run_task()`,
`ConfigService.get_run_task()` (the restart watch), and — when charger credentials are set —
`MyEnergiService.get_run_task()`. (`trip_service` / `charging_service` are stateless
request/response and have no run task.)

> **Orchestration note.** The media and weather `run()` coroutines schedule APScheduler jobs
> and then *return* — their ongoing work lives in those jobs, and APScheduler logs+swallows
> per-job exceptions, so polling is self-healing per tick. Telemetry and the server run
> forever. There is **no in-process supervisor**: an unhandled failure in either propagates
> out of `gather` and ends the process. Resilience is delegated to **systemd
> `Restart=on-failure`** in deployment (see README). Don't add a restart loop without a reason.
> The README's units also set **`RestartSec=5`, which is load-bearing**: at systemd's 100 ms default a
> crash loop trips `StartLimitBurst` in about two seconds and leaves the unit permanently `failed`,
> recoverable only over SSH.

## Service contracts

Services plug into the server, and into each other, through duck-typed methods — the server never
imports a service:

- **`server.register_handler(msg_type, handler)`** — called as `handler(payload, writer)`.
  Request/response handlers reply to that client only with `server.send_to(writer, …)`;
  fire-and-forget commands ignore the writer.
- **`stream_everything(writer)`** — the on-connect snapshot, via `server.register_service(svc)`.
- **`apply_config()`** — re-snapshot tunables after an Options-view write, via
  `config_service.register_hook(name, svc.apply_config)`. No service re-reads `Config` on its own
  (`src/config_service/CLAUDE.md`).
- **`health()`** — a per-service probe for the maintenance dashboard (`src/system_service/CLAUDE.md`).
- **Logging** — a new service's top-level logger name must be added to `_SERVICE_LOGGERS`, or its
  INFO/DEBUG output silently vanishes (`src/utils/CLAUDE.md`).
- **Wiring** — every service is constructed, hooked, registered and gathered in
  `src/start_services.py`, the composition root.

## Configuration

### `.env` (repo root, gitignored)
Required secrets/paths, loaded by `utils/config_parser.get_env`:
- `CONFIG_PATH` — absolute path to the backend's config JSON. **Optional since the
  config relocation (issue #41)**: unset → `$XDG_CONFIG_HOME`(or `~/.config`)`/Tesla-Homedash/
  `backend_config.json`, via `config_parser.default_config_path()`. Set it only when the
  deployment keeps its config elsewhere.
- `VIN` — Tesla vehicle identification number
- `API_KEY` — Teslemetry access token
- `INFLUX_TOKEN` — InfluxDB auth token
- `SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET` — from your Spotify Developer App

`start_services.main()` fails fast if any of these are missing. **Optional:** `MYENERGI_HUB_SERIAL`
/ `MYENERGI_API_KEY` (myenergi cloud digest-auth creds) — absent → the charger service is skipped
and the rest of the stack still runs. Also optional: `TESLA_HOMEDASH_LOG_LEVEL` —
`debug`/`info`/`warning`/`error`/`critical`, **default `info`** (invalid → `info` + a warning),
mirroring the frontend variable of the same name. Read by `configure_logging()`, which calls
`load_dotenv()` itself because `get_env`'s lazy load happens after logging is set up; a real
environment variable (systemd `Environment=`) still wins over `.env`. **Keep the deployment at
`info`** — `debug` logs a line per telemetry property and rotates the Pi's journal fast enough to
destroy incident history.

### `config.json` (copy from `config_template.json`)
Parsed once by `Config` and injected into every service. Keys:
- `tesla data` — per-field metadata map: `stream_id`, `category`, `unit`, `formula` (sympy
  string or null), `log` (bool), and optional `sleep_default` — the value the field reverts to
  when the vehicle goes to sleep (omit or `null` to leave it at its last reading; the default is
  a final value, the `formula` is **not** re-applied to it). Optional `line_mode` (issue #20) —
  the History-graph render mode for the field: `"step"` (hold the previous value, then jump — the
  default when absent; right for sampled/held signals like `VehicleSpeed` or setpoints) or
  `"linear"` (straight point-to-point line; right for accumulators / continuous quantities like
  `Odometer`, the energy counters, `OutsideTemp`). Display-only hint handed to the frontend over
  `TESLA_GRAPH_PROPERTIES`. Optional `zero_based` (bool, issue #42) — the History graph pins its
  y-axis bottom to 0 and pads only the top, for a field that cannot go negative (speed, power,
  battery level/range, session energy); a fitted axis would show impossible values and blow a
  2-point drift up to full height. Leave it off for signed fields (`OutsideTemp`) **and for the
  lifetime counters** (`Odometer`, `LifetimeEnergyUsed`), whose month of change is too small
  against their size to see from zero. Data that dips below 0 anyway falls back to the ordinary
  fit. Absent → false, so an existing `config.json` keeps today's axes until the key is added.
  A field is graphable (appears in the History dropdown) only if
  `log: true` **and** numeric — set `log: false` to keep a numeric field off the graph (e.g.
  `GpsHeading`, which wraps 0↔360 and isn't worth graphing).
- `calculated tesla data` — derived fields (`DrivenToday`, `DrivenThisMonth`): adds
  `source_data_property_id`, `period` (`day`/`month`), `calculation_formula` (e.g. `y - x`).
- `radioMediaIds` — station name → Nelonen Media id; `defaultRadioStation` — a key from it.
- `spotifyDeviceId` — target Spotify Connect device id (**now runtime-editable**, both as a text row
  and via the Options view's *Tunnista laite* flow — `src/media_service/CLAUDE.md`);
  `spotifyRedirectUri` (default `http://127.0.0.1:8080/callback`, must match the Spotify app);
  `spotifyCachePath` — spotipy OAuth token cache; `spotifyMarket` — ISO-3166-1 alpha-2 (e.g. `FI`).
- `weatherPlace` — FMI place (e.g. `Tampere`); `timeZone` — IANA zone (e.g. `Europe/Helsinki`).
- `myenergi` (optional) — Zappi tunables: `zappiSerial` (`""` = auto-select the first Zappi),
  `pollIntervalIdleSeconds` / `pollIntervalActiveSeconds`, `minSessionEnergyKwh`, `sessionMergeMinutes`.
- `trip` (optional) — trip-detection tunables: `min_stop_minutes`, `min_trip_distance_km`.
- `electricityPriceEurPerKwh` (optional) — flat €/kWh tariff for the Charging view's cost tiles
  (`Latauskulut` = charging cost, `Sähkölasku` = total home electricity cost); `null`/absent → "—".
  Now a **fallback**: used per-hour when spot pricing is off or a given hour has no spot price.
- `spotPrice` (optional, issue #12) — Nord Pool FI hourly spot pricing for the cost tiles + the live
  price tile: `enabled` (master switch; `false` → flat-tariff pricing, no live service),
  `vatPercent` (Finnish electricity VAT, default `25.5`), `marginCentsPerKwh` (seller margin c/kWh
  added before VAT), `baseUrl` (the no-key sähkötin.fi range endpoint; swappable for another source).
  All-in €/kWh for an hour = `(spot + marginCentsPerKwh/100) × (1 + vatPercent/100)`. Prices are
  fetched on demand (no self-logging) — historical hours price past sessions retroactively.
- `media` (optional) — `autoplayRadio` (start the default station at backend start) and
  `resumeRadioAfterSpotify` (`src/media_service/CLAUDE.md`). Both default off, which is the
  pre-existing behaviour.
- `logging` (optional) — `debugEnabled` / `debugMinutes`: the Options view's temporary DEBUG log for
  both halves, which clears itself (`src/system_service/CLAUDE.md`). It raises the level above
  `TESLA_HOMEDASH_LOG_LEVEL` for a while and returns to it; it does not replace the variable.

> **`config.json` is now written at runtime.** The frontend's Options view can change the subset of
> keys listed in `config_service.SETTINGS_SCHEMA` (`src/config_service/CLAUDE.md`). `Config` gained
> `set(dotted_key, value)` + `save()`: the save snapshots the previous file to `config.json.bak`,
> then writes atomically (temp file in the same directory + `os.replace`, with an `fsync` first).
> `Config.__init__` rolls back to that `.bak` if the live file fails to parse or validate — which is
> what stops a restart-tier setting from restart-looping systemd. The structural parts (`tesla
> data`, `calculated tesla data`, `radioMediaIds`) are deliberately NOT in the schema: the frontend
> registry mirrors them, so editing them at runtime would desync the two halves. The one exception
> is the display/logging flags of `tesla data` (`log`, `line_mode`, `zero_based`), which the
> Telemetriakentät card edits through its own codes (`src/tesla_service/CLAUDE.md`, issue #29).

## Python docstrings

Every class and function gets a triple-quoted docstring. Functions document each argument:
```python
def calculate_range(distance_miles: float, efficiency: float) -> float:
    '''
    Converts distance from miles to kilometers and applies efficiency factor.
    Arguments:
        distance_miles (float): Raw distance value from the Tesla API in miles
        efficiency (float): Energy efficiency multiplier for the current drive mode
    '''
```
Add inline comments only for non-obvious logic (protocol packing, formula eval, state-machine
transitions, scheduling edge cases). Don't comment self-explanatory code.
