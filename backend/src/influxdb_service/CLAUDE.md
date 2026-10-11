# `influxdb_service/influxdb_handler.py` — InfluxDB access

`InfluxDBHandler` wraps the async InfluxDB client: `write_tesla_data` (logged fields + midnight
snapshot), `read_first_value_day`/`_month` (calculated-field baselines), `read_tesla_data_property`
(raw history — the History path serves it as it was logged), and `read_last_value_before` (a
`last()` query bounded by `stop` — the held value before an empty window, used to boundary-fill the
History graph with a flat line). For the myenergi charger it adds `write_charger_data` (the
`myenergi_data` measurement), `read_charger_data_property` (raw charger history), and
`read_grid_import_kwh_hourly` (reuses the raw `GridPower` read + the module-level pure
`integrate_power_series_hourly` — a trapezoidal per-UTC-hour integral, export clamped to 0 → a
`{utc_hour_ms: kwh}` map; the month home-import total is `sum(...)` and the spot-cost path dots it
with hourly prices). Read failures degrade to `None` rather than crashing the app. **Talks to:**
InfluxDB, `Vehicle`. *Flux queries interpolate `data_property_id` via f-strings gated by the
`_SAFE_ID` regex `^[A-Za-z0-9_\-]+$` — keep the guard; it is the only thing preventing injection if
non-config input ever reaches these paths.*

Every read goes through `__single_table()` (run, log a failure, degrade to `None`, refuse a second
table) and the numeric ones through `__as_series()`; a new read should too.

`series.py` holds the reductions over a read's `(count, timestamps_ms, values)` result —
`delta`, `first`, `last`, `positive_increment` — each NaN on a missing series. The trip and charging
summaries share them; use them rather than re-deriving a series delta.
