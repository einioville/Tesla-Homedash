# `tesla_service/` — telemetry & vehicle

- **`telemetry.py`** (`TelemetryHandler`) wraps `teslemetry_stream.TeslemetryStream`, registers
  `vehicle.on_telemetry_event` as the listener, and blocks on a close event. Reconnection is the
  library's job (exponential backoff). **Talks to:** Teslemetry stream → `Vehicle`.
- **`vehicle.py`** (`Vehicle`) loads a `VehicleDataProperty` per `config.json` field.
  `init_async_dependent` starts the APScheduler, builds the `CalculatedVehicleDataProperty`s and
  their period-reset jobs, and registers the **midnight snapshot** job (writes every logged property
  at 00:00 so first-of-day/month baseline queries always find a record). `on_telemetry_event →
  __update` applies formulas, broadcasts changed fields (`protocol.frame(MSG_STREAM, …)`), and
  writes logged fields to InfluxDB (a failed write never blocks the broadcast). Non-data **state**
  events carry `online`/`offline`/`asleep` (the car reports a sleeping vehicle as `offline`, never
  `asleep`); `__update` writes the synthesized `VehicleOnline` and nothing more. **Value-callbacks**
  (`add_callback`/`remove_callback`) drive the rest: `add_callback(criteria, cb)` fires
  `cb(matches)` when every property in `criteria` (`{id: target_value}`) simultaneously holds its
  target (edge-triggered, built on the per-property callbacks; `matches` is a list of `(id, value,
  when)`). The **sleep reset** is registered this way in `__init__` —
  `add_callback({"VehicleOnline": False}, __on_sleep)`; when the car goes offline `__on_sleep` runs
  `__apply_sleep_defaults`, forcing every field with a configured `sleep_default` to it and
  broadcasting only the ones that changed (never written to InfluxDB). Edge-triggered, so it fires
  once per online→offline transition (lock ordering still lands it after the reconnect burst). HVAC:
  `switch_climate_state` toggles via the Teslemetry REST API behind an in-memory **rate limiter**
  (reserve/refund/reset) and a **value lock** that pins the UI to `HvacPowerStatePending` until the
  confirming telemetry arrives; `plus_temp`/`minus_temp` adjust the local target and stream it (the
  **target temperature is a pre-conditioning setpoint** — it is pushed to the car via
  `update_temperature` only when climate is next toggled, by design). `stream_everything` snapshots
  all properties to a new client. History: `get_graphable_properties` lists the logged numeric
  (value_float) properties for the History view's dropdown; `get_data_history` reads one property's
  history and `get_value_before` reads the held value just before a window (the empty-window
  boundary-fill) — all served by request/response handlers that reply to the requesting client only.
  **Talks to:** `InfluxDBHandler` (write/read), `Server` (broadcast/send_to), Teslemetry REST
  (aiohttp).
- **`vehicle_data_property.py`**: `VehicleDataProperty` stores one field's value/timestamp,
  evaluates its sympy `formula`, serializes to the wire format (`get_stream_data`), builds Influx
  points, supports `lock_value_until` (the pending-state lock), `apply_sleep_default` (force-reset
  to the field's configured asleep value, bypassing the formula and clearing any active value-lock —
  a pending HVAC toggle can never confirm while asleep), and `add_callback(target_value,
  cb)`/`remove_callback(handle)` — edge-triggered value-callbacks run as independent tasks as
  `cb(data_id, value, when)` when the value transitions into `target_value` (`when` is a tz-aware
  datetime), or on every value change if `target_value` is the `VehicleDataProperty.ANY` sentinel;
  `Vehicle.add_callback` builds its combination callbacks on these. `CalculatedVehicleDataProperty`
  derives `calculation_formula(x=baseline, y=latest)`; the baseline is read from InfluxDB at period
  start (falls back to the live value), reset by an APScheduler cron job. **Talks to:** `Vehicle`
  (which owns Influx access).
