# `utils/` — config, protocol, logging

- **`config_parser.py`**: `Config` validates + exposes `config.json`; `get_env` loads `.env` once.
- **`protocol.py`**: every message-type byte, weather sub-id, `MAX_MSG_SIZE`, and `frame()`. The
  single source of truth — add new constants here, never on a class. Every JSON-bodied code goes
  through `json_frame()` (a `status(1B) + len(4B) + UTF-8 JSON` reply, raw UTF-8) and
  `parse_json_body()` (a `len(4B) + UTF-8 JSON` object request; raises `ValueError` with the
  Finnish message the Options view shows).
- **`process.py`**: `run(argv, timeout, …)` — the one way a service runs a command to completion
  (audio, display, USB import, git queries, host reboot). stdin is `/dev/null`; a timeout kills
  and **reaps** the child (the whole process group with `new_session=True`) and raises
  `asyncio.TimeoutError`, which callers must catch **before** `OSError` — it is a subclass since
  Python 3.11. The updater's streaming build runner is the exception: it reads output live.
- **`atomic_write.py`**: `write_atomic(path, text, mode)` — every whole-file rewrite (`config.json`,
  the Spotify grant record, the error store, kept log backups): a temp file in the same directory,
  fsynced, then `os.replace`d, and removed on any failure. `mode` is applied through the umask;
  pass `0o600` for anything private.
- **`timeline.py`**: `collapse_transitions()` + `segment()` — the one segmentation of a logged state
  timeline into activity windows. Trips (`Gear` out of Park) and charging sessions
  (`DetailedChargeState` charging) bind their own `is_active` and idle state with `partial`; a new
  "detect runs of X in stored telemetry" feature does the same.
- **`logger_configurator.py`**: `configure_logging()` resolves the level from
  `TESLA_HOMEDASH_LOG_LEVEL` (default **INFO**, not DEBUG) and wires the shared stdout formatter
  (`LEVEL | YYYY-MM-DD | HH:MM:SS | name | message`) onto an allow-list of top-level loggers.
  **Every service's logger prefix must be in `_SERVICE_LOGGERS`** (the tuple in
  `logger_configurator.py`) — an unlisted prefix propagates to a handler-less root and its
  INFO/DEBUG logs silently vanish. **`spotipy` gets the same handlers but a PINNED level**
  (`max(level, INFO)`): its "Couldn't write token to cache" warning is the only evidence that a
  re-authorisation silently lost the grant, but at DEBUG it prints the token POST body and the
  base64 `Authorization` header carrying `SPOTIFY_CLIENT_ID:SPOTIFY_CLIENT_SECRET`, the
  authorization code and the refresh token. Never add it to the tuple itself.
  `set_log_level(name)` applies the Options view's level (`LEVEL_CHOICES`) to the `_SERVICE_LOGGERS`
  and the file, keeps `spotipy` at INFO or above for the same reason, and sets the journal's handler
  to the level **but never below INFO** (unless the process was started at DEBUG) — its caller is
  `system_service/log_level.py`. `default_level_name()` is the variable's level, the setting's default.
  **Three handlers per logger.** The stdout handler never drops below INFO, so DEBUG never reaches the
  journal; a `RotatingFileHandler` (`backend.log`, 5 MB × 3) takes
  whatever the loggers pass; and **`ErrorLog`** keeps every WARNING+ record — time, level, full logger
  name, text with any traceback — in memory and in `backend-errors.jsonl`, bounded to 2000 and
  reloaded at startup, for the Järjestelmän tila counts and lists (`../system_service/CLAUDE.md`). All
  live in `log_dir()`: `TESLA_HOMEDASH_LOG_DIR`, else `$XDG_STATE_HOME` (`~/.local/state`)
  `/Tesla-Homedash/logs`, the frontend's rule too. A directory that cannot be created leaves stdout
  alone working, with a warning.

## Binary protocol reference

Framing, byte order and the Tesla stream value types are in the root `CLAUDE.md` §5.1. The whole
stream is TLS 1.3, and until a display has logged in only the `0xF0`–`0xF5` exchange crosses it,
with inbound messages capped at `MAX_PREAUTH_MSG_SIZE` (4 KB) — `../auth_service/CLAUDE.md`.
`frontend_v2/core/protocol.hh` mirrors `protocol.py` — change both together.

**Message types**

| Byte | Name | Dir | Payload |
|------|------|-----|---------|
| `0x03` | MSG_TERMINATE | F→B | (empty) |
| `0x04` | MSG_STREAM | B→F | `stream_id(2B) + value_type(1B) + value + timestamp(8B)` |
| `0x14` | MEDIA_STREAM_IMAGE | B→F | Raw image bytes (JPEG/PNG) |
| `0x15` | MEDIA_STREAM_NAME | B→F | `length(2B) + UTF-8` |
| `0x16` | MEDIA_STREAM_PROGRESS | B→F | `progress_ms(4B)` |
| `0x17` | MEDIA_STREAM_DURATION | B→F | `duration_ms(4B)` |
| `0x18` | MEDIA_SKIP | F→B | (empty) |
| `0x19` | MEDIA_SKIP_BACKWARD | F→B | (empty) |
| `0x1A` | MEDIA_PAUSE_PLAY | F→B | (empty) |
| `0x1B` | MEDIA_IS_PLAYING | B→F | `bool(1B)` |
| `0x1C` | MEDIA_SET_PROGRESS | F→B | `progress_ms(4B)` |
| `0x1D` | MEDIA_STREAM_ARTISTS | B→F | `length(2B) + UTF-8` |
| `0x1E` | MEDIA_STREAM_TYPE | B→F | `media_type(1B)`: 0x01=radio, 0x02=spotify |
| `0x1F` | MEDIA_SPECTRUM_WATCH | F→B | `on(1B)` — 1 while the display shows the spectrum, 0 when it stops; sent again after a reconnect (`../audio_service/CLAUDE.md`) |
| `0x20` | MEDIA_SPECTRUM | B→F | `count(1B) + count × level(1B, 0–255)`, low to high frequency, ~30 a second to each watching display only, one flat frame when the sound stops |
| `0x30` | WEATHER_FORECAST | B→F | repeated `sub_id(1B) + value` |
| `0x36` | WEATHER_VIEW | B→F | `status(1B, always OK) + len(4B) + JSON` — `{meta, now, hourly, daily, astro, warnings}`, the Weather view's document (`../weather_service/CLAUDE.md`); **broadcast** every 10 min and in the on-connect snapshot |
| `0x60` | TESLA_SWITCH_CLIMATE | F→B | (empty) |
| `0x61` | TESLA_MINUS_TEMP | F→B | (empty) |
| `0x62` | TESLA_PLUS_TEMP | F→B | (empty) |
| `0x63` | TESLA_GET_PROPERTY_TABLE | F→B | (empty) — the Options view's telemetry-field table (#29) |
| `0x64` | TESLA_PROPERTY_TABLE | B→F | `status(1B) + len(4B) + JSON` — `{properties: [{id, category, unit, log, line_mode, zero_based, numeric, requiredBy}]}`; to the requester, and **broadcast** after an accepted change |
| `0x65` | TESLA_SET_PROPERTY | F→B | `len(4B) + JSON` — `{id, field, value}`; `field` ∈ `log`/`line_mode`/`zero_based` |
| `0x66` | TESLA_SET_PROPERTY_RESULT | B→F | `status(1B) + len(4B) + JSON` — `{ok, id, field, value, message}`; to the requester only |
| `0x70` | TESLA_GET_GRAPH_PROPERTIES | F→B | (empty) |
| `0x71` | TESLA_GRAPH_PROPERTIES | B→F | `count(2B)` + per property `id_len(2B)+id + unit_len(2B)+unit + cat_len(2B)+category + mode_len(2B)+line_mode` (UTF-8) `+ zero_based(1B)`; `line_mode` = `step`/`linear` graph render hint, `zero_based` = 1 pins the graph's y-axis bottom to 0 |
| `0x72` | TESLA_GET_HISTORY | F→B | `range_code(1B)` (0=1h,1=1d,2=1M,3=custom,4=1week) + `id_len(2B)+id` + `start_ms(8B)` + `end_ms(8B)` |
| `0x73` | TESLA_HISTORY | B→F | `id_len(2B)+id` + `status(1B)` + `count(4B)` + count×(`ts_ms(8B)` + `value(8B double)`) |
| `0x50` | CHARGER_STREAM | B→F | myenergi charger live state: repeated `sub_id(1B) + value` (see charger sub-ids below) |
| `0x80` | CHARGING_GET_LIST | F→B | `start_ms(8B) + end_ms(8B)` |
| `0x81` | CHARGING_LIST | B→F | `req_start(8B)+req_end(8B)+count(2B)` + count×(`start(8B)+end(8B)+charger_kwh(8B double)`) |
| `0x82` | CHARGING_GET_SUMMARY | F→B | `start_ms(8B) + end_ms(8B)` |
| `0x83` | CHARGING_SUMMARY | B→F | `session_id(8B)+status(1B)+start(8B)+end(8B)` + 11×`double` (per-session losses + `cost_eur` + `avg_price_eur_per_kwh`) |
| `0x84` | CHARGING_GET_MONTH | F→B | (empty) |
| `0x85` | CHARGING_MONTH | B→F | `status(1B)` + 13×`double` (month aggregate — see below) |
| `0x86` | CHARGER_GET_HISTORY | F→B | `range_code(1B) + id_len(2B)+id + start_ms(8B) + end_ms(8B)` |
| `0x87` | CHARGER_HISTORY | B→F | `id_len(2B)+id + status(1B) + count(4B)` + count×(`ts_ms(8B)+value(8B double)`) — reads `myenergi_data` |
| `0x88` | SPOT_PRICE_STREAM | B→F | live spot price broadcast: `status(1B) + hour_start_ms(8B) + spot(8B double) + all_in(8B double)` (raw wholesale + VAT/margin all-in €/kWh; both NaN when status 0) |
| `0x90` | CONFIG_GET_SCHEMA | F→B | (empty) — request the editable-settings schema + values |
| `0x91` | CONFIG_SCHEMA | B→F | `status(1B) + len(4B) + UTF-8 JSON` — `{"path":<config path>,"startedAt":<epoch-ms of this backend process>,"groups":[{id,label,icon,sections:[{id,label,status?,settings:[…]}]}]}` |
| `0x92` | CONFIG_SET | F→B | `len(4B) + UTF-8 JSON` — `{"key": <dotted>, "value": <json>}` |
| `0x93` | CONFIG_SET_RESULT | B→F | `status(1B) + len(4B) + UTF-8 JSON` — `{key, value, applied, message}` |
| `0x94` | CONFIG_RESTART | F→B | (empty) — exit with code 42 so the service manager restarts |
| `0x95` | HOST_REBOOT | F→B | (empty) — reboot the host (#40); nothing is replied when it starts, a refusal comes back as `CONFIG_SET_RESULT` |
| `0xA0` | SPOTIFY_AUTH_STATUS | B→F | `status(1B) + len(4B) + JSON` — `{authorized, needsReauth, scope, expiresAt, redirectUri, cachePath, reason, authorizedAt, validUntil, email, displayName}` (the last four from the grant record; the dates are epoch seconds or `null`, and `expiresAt` is the ACCESS token's hour — never a grant expiry); snapshot on connect, broadcast after an exchange **and the moment the player is refused**. `needsReauth` = a new authorization is the fix (expired / revoked / never stored / scope short) — NOT merely `!authorized`, since an unreadable config is unauthorized too and re-authorizing would not help it |
| `0xA1` | SPOTIFY_AUTH_GET_URL | F→B | (empty) — start a flow, replacing any pending one |
| `0xA2` | SPOTIFY_AUTH_URL | B→F | `status(1B) + len(4B) + JSON` — `{url, redirectUri, state}` on OK (informational only; the backend has already opened the page), or `{message}` on error |
| `0xA3` | *(retired)* | — | Carried the redirect URL back from the embedded WebView. The consent page now opens in the host's real browser and the backend catches the redirect on its own loopback listener, so nothing produces one |
| `0xA4` | SPOTIFY_AUTH_RESULT | B→F | `status(1B) + len(4B) + JSON` — `{ok, message, scope, expiresAt}` |
| `0xA5` | SPOTIFY_DEVICE_SCAN_START | F→B | `len(4B) + UTF-8 JSON` — `{scanId}`; begins a device scan, replacing any live one |
| `0xA6` | SPOTIFY_DEVICE_SCAN_STOP | F→B | (empty) — ends the requesting client's own scan |
| `0xA7` | SPOTIFY_DEVICE_STATE | B→F | `status(1B) + len(4B) + JSON` — `{scanId, scanning, message, device, track, current}`; sent to the scanning client only |
| `0xA8` | SPOTIFY_DEVICE_SELECT | F→B | `len(4B) + UTF-8 JSON` — `{deviceId, scanId}` |
| `0xA9` | SPOTIFY_DEVICE_RESULT | B→F | `status(1B) + len(4B) + JSON` — `{ok, message, deviceId, deviceName, scanId}` |
| `0xAA` | SPOTIFY_DEVICE_GET_STATUS | F→B | (empty) — ask for the configured device's standing |
| `0xAB` | SPOTIFY_DEVICE_STATUS | B→F | `status(1B, always OK) + len(4B) + JSON` — `{configured, id, name, type, detected, isRestricted, reason}`; `detected` is `null` when Spotify's device list could not be read. Replied to the requester, **broadcast** after a successful select; no `scanId` — it describes `config.json`, not a flow |
| `0xB0` | SYSTEM_GET_STATUS | F→B | (empty) — poll the service probes now |
| `0xB1` | SYSTEM_STATUS | B→F | `status(1B) + len(4B) + JSON` — `{services[{id, label, state, detail, config, items, errors{warnings, errors}}], sampled_ms, uptime_s, backend_uptime_s}`; the host's metrics are `SYSTEM_HISTORY`'s |
| `0xB2` | SYSTEM_GET_HISTORY | F→B | `since_ms(8B, signed)` — the samples newer than this; `0` (or an empty payload) = everything |
| `0xB3` | SYSTEM_HISTORY | B→F | `status(1B) + len(4B) + JSON` — `{interval_s, window_s, reset, mem_total_b, cpu_count, temp_available, disk{path, device, total_b, used_b, free_b, used_pct}, samples[{t, cpu[], mem_used_b, disk_read_bps, disk_write_bps, net_rx_bps, net_tx_bps, cpu_temp_c}]}`; to the requester only. `reset` = drop what you hold rather than append (asked for everything, or the host clock went backwards). A value that could not be computed is `null` (`../system_service/CLAUDE.md`) |
| `0xB4` | SYSTEM_GET_LOG | F→B | `len(4B) + JSON` — `{service}`: one status card's probe id |
| `0xB5` | SYSTEM_LOG | B→F | `status(1B) + len(4B) + JSON` — `{service, label, entries[{t, level, logger, message}]}`, newest first, ≤ 500; to the requester only |
| `0xB6` | LOG_CLEAR | F→B | `len(4B) + JSON` — `{keep: "warnings" \| "none"}`; clears the backend's own log files (the journal is never touched) |
| `0xB7` | LOG_CLEAR_RESULT | B→F | `status(1B) + len(4B) + JSON` — `{ok, freedBytes, message}`; to the requester only |
| `0xC0` | DISPLAY_SET_POWER | F→B | `on(1B)` — 1 wakes the panel, 0 powers it down |
| `0xC1` | DISPLAY_POWER_STATE | B→F | `available(1B) + on(1B) + fault(1B)`; `available=0` = no wlopm on the host; `fault` 0 none, 1 wlopm refused the change, 2 output lost after a wake (sticky, power-off refused until restart). The frontend reads a 2-byte payload as fault 0 |
| `0xD0` | UPDATE_GET_STATE | F→B | `len(4B) + UTF-8 JSON` — `{"fetch": <bool>}`; `fetch` contacts the remote (backend-throttled to one per 2 min) |
| `0xD1` | UPDATE_STATE | B→F | `status(1B) + len(4B) + JSON`, **broadcast** — `{available, reason, repoPath, remoteUrl, branch, dirty, dirtyFiles, fetchedMs, current{…}, channels{development{…},releases{…}}, tools{…}, job}`. `job` is `null` when idle and the whole progress report while a run is in flight, so there is no second progress code and a client connecting mid-update sees it in its snapshot |
| `0xD2` | UPDATE_APPLY | F→B | `len(4B) + UTF-8 JSON` — `{"channel": "development"\|"releases", "commit": <40-hex>}`; the commit **fences** the request (a target that moved since the check is refused) |
| `0xD3` | UPDATE_CANCEL | F→B | (empty) — kill the running step's process group; honoured only during fetch/deps/build (`job.cancellable`) |
| `0xE0` | USB_IMPORT_LIST | F→B | `len(4B) + UTF-8 JSON` — `{flowId}`; takes the flow over and lists the USB drives |
| `0xE1` | USB_IMPORT_SCAN | F→B | `len(4B) + UTF-8 JSON` — `{flowId, device}`; mount if needed, count the photos in `tesla_homedash_screensaver` |
| `0xE2` | USB_IMPORT_START | F→B | `len(4B) + UTF-8 JSON` — `{flowId, device}`; copy them into the screensaver folder |
| `0xE3` | USB_IMPORT_CLOSE | F→B | `len(4B) + UTF-8 JSON` — `{flowId}`; stop a copy after the current file, unmount what was mounted; nothing replied |
| `0xE4` | USB_IMPORT_STATE | B→F | `status(1B, always 1) + len(4B) + JSON` — `{flowId, phase, message, drives[{device,label,size,fstype,model,mountpoint}], device, found, count, bytes, copied, skipped, total, unmounted}`; to the flow's client only. Every request carries the frontend's `flowId` and every state echoes it (`../usb_import_service/CLAUDE.md`) |
| `0xF0` | AUTH_HELLO | B→F | `status(1B, always OK) + len(4B) + JSON` — `{passwordSet}`; the first frame on every connection, before login |
| `0xF1` | AUTH_TOKEN | F→B | `len(4B) + JSON` — `{deviceId, token}`: a remembered login |
| `0xF2` | AUTH_SCRAM_START | F→B | `len(4B) + JSON` — `{message}`: the SCRAM client-first-message (`p=tls-server-end-point,,n=homedash,r=…`) |
| `0xF3` | AUTH_SCRAM_CHALLENGE | B→F | `status(1B, always OK) + len(4B) + JSON` — `{message}`: the server-first-message |
| `0xF4` | AUTH_SCRAM_PROOF | F→B | `len(4B) + JSON` — `{message, name}`: the client-final-message and the display's name |
| `0xF5` | AUTH_RESULT | B→F | `status(1B) + len(4B) + JSON` — `{ok, reason, message, retryAfter?}`, plus `serverFinal, deviceId, token, name` after a password login; `reason` is an `AUTH_REASON_*` (`token`, `password`, `noPassword`, `throttled`, `binding`, `protocol`). Only `ok` is followed by the snapshot |
| `0xF6` | AUTH_GET_DISPLAYS | F→B | (empty) — the Ylläpito › Näytöt list |
| `0xF7` | AUTH_DISPLAYS | B→F | `status(1B, always OK) + len(4B) + JSON` — `{displays[{id, name, address, created, lastSeen, connected}]}`; to the requester, and **broadcast** on any change |
| `0xF8` | AUTH_REVOKE | F→B | `len(4B) + JSON` — `{id}`; forgets that login and closes its connections |

(Trip codes `0x74`–`0x7F` — the Trips view, and `TRIP_GET_CURRENT`/`TRIP_CURRENT` for the Kartta
view's route layer — are omitted from this table; they mirror the History request/response shape and
their layouts are in `protocol.py`. `TRIP_CURRENT` carries the maps' route: the drive under way up to
now (`live` 1) or, once the car has been parked longer than `min_stop_minutes`, the last trip whole,
trip id 0 when there is none in a week — `TripLoader.current_trip`. A drive counts from the first
metres; a finished trip only past `min_trip_distance_km`, so a driveway shuffle does not stand in
for the last real trip.)

The `0x70`–`0x73` pair is **request/response** (the History view): the backend replies to the
requesting client only (`send_to`), never a broadcast, and `TESLA_HISTORY` echoes the requested id so
a stale reply can be discarded. History values are returned **raw** (no downsampling); the frontend
renders them as a **step line** (`StepLeft`) so a value held between records still displays as held.
When a window logged **nothing** (the value stayed constant, so no record falls
inside it), the backend **boundary-fills**: it queries the last value before the window start and
returns two synthetic points (window-start + window-end at that held value) so the graph draws a
flat held line across the whole range instead of "no data". Only a genuinely absent prior value
(or an InfluxDB outage, where the boundary query also yields nothing) replies `status=0`.

**Config protocol (`0x90`–`0x95`)** — the Options view. Request/response like History/Trips
(the backend replies to the requesting client via `send_to`), with one exception: a successful
`CONFIG_SET` *also broadcasts* a fresh `CONFIG_SCHEMA` so a second frontend refreshes its
displayed values. Bodies are `len(4B) + UTF-8 JSON` (the `CHARGER_RAW_JSON` idiom) rather than
a packed layout — the schema is variable-shaped and these packets are rare. Keys are dotted
paths into `config.json` (`myenergi.pollIntervalSeconds`). `CONFIG_SET_RESULT.applied` is
`hook` (a service re-snapshotted), `restart` (written but only live after a restart) or
`unchanged` (the value already matched, so nothing was written or broadcast).

**Weather sub-IDs**: `0x31` temperature `int8` °C; `0x32` wind `uint8` m/s;
`0x33` precipitation `uint8` mm; `0x34` cloud cover `uint8` %; `0x35` hour `uint8`.

**Charger (myenergi) protocol** — the Charging view. `CHARGER_STREAM` (`0x50`) is a **broadcast** of
the Zappi's live state, a weather-style sequence of `sub_id(1B) + value` pairs: `0x51` status
`uint8`, `0x52` plug `uint8`, `0x53` mode `uint8`, `0x54` charge power `float64` W, `0x55` session
energy `float64` kWh, `0x56` supply voltage `uint16` V, `0x57` grid power `float64` W
(+import/−export), `0x58` generated power `float64` W, `0x59` frequency `float64` Hz, `0x5A` L1
phase `uint8`, and `0x5F` the full raw pymyenergi payload as `len(4B)+UTF-8 JSON` (every field, most
unused — the one length-prefixed sub-id, so an unknown fixed-width sub-id can't be skipped and stops
the parse). The `0x80`–`0x87` codes are **request/response** (reply to the requesting client only),
served by `charging_service` from stored telemetry + `myenergi_data`; `0x88` (`SPOT_PRICE_STREAM`)
is a **broadcast** of the live hourly spot price (see `../charging_service/CLAUDE.md`).
`CHARGING_MONTH`'s 13 doubles, in order: charger_kwh, car_kwh, wasted_kwh, efficiency_pct,
car_wh_per_km, charger_wh_per_km, driving_kwh, km_month, session_count, total_charge_s,
charging_cost_eur, home_grid_kwh, home_cost_eur (any → NaN → "—"). Both cost fields are now
**spot-priced per hour** (flat-tariff fallback) — see `../charging_service/CLAUDE.md`.
