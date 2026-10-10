# `charging_service/` — charging stats & spot pricing

The live charger feed these sessions join against is `../myenergi_service/CLAUDE.md`; the
`0x80`–`0x88` wire formats are in `../utils/CLAUDE.md`.

- **`charging_service/`** (`ChargingLoader` + `ChargingSession`) derives charging sessions **on
  demand** from stored `DetailedChargeState` history (segmentation like `trip_service`), joined to
  the logged charger energy — no live tracking. Serves `CHARGING_GET_LIST`/`_SUMMARY`/`_MONTH` +
  `CHARGER_GET_HISTORY`. **Per-session charger energy = the SUM OF POSITIVE `ChargeAdded` increments
  in the window** (NOT the in-window max: the myenergi accumulator can carry a value in from
  charging that predates the Tesla-detected session, so a max double-counts — this was a real bug).
  `month_summary` sums the sessions' charger/battery energy + the tesla month-counter deltas
  (`LifetimeEnergyUsed`, `Odometer`) for consumption/km. **Talks to:** `InfluxDBHandler`, `Server`.
- **Spot pricing (issue #12).** **`spot_price.py`** (`SpotPriceProvider`) fetches Nord Pool FI
  hourly spot prices from the no-key **sähkötin.fi** range endpoint (`?start&end`, raw €/MWh, UTC
  hours), converts to an all-in `(spot + margin) × (1 + VAT)` €/kWh, and caches immutable past hours
  — so a session from days ago is priced retroactively **without self-logging prices**. The module
  also holds the pure pricing helper `price_hourly_energy` (dot energy-by-hour with price,
  flat-tariff fallback). Cost now lives in the **loader/session** (not the month handler):
  `ChargingSession.summary()` buckets its `ChargeAdded` increments by UTC hour
  (`bucket_positive_increments_by_hour`) and prices each → `cost_eur`/`avg_price_eur_per_kwh`;
  `month_summary` sums session costs (`charging_cost_eur`) and prices the hourly home import
  (`home_cost_eur`), each falling back per-hour to the flat `electricityPriceEurPerKwh` tariff (→
  NaN → "—" when neither is available). **`spot_price_service.py`** (`SpotPriceService`) is a thin
  always-on `WeatherService`-style broadcaster: it re-broadcasts the current hour's price as
  `SPOT_PRICE_STREAM` (`0x88`) hourly + snapshots it on connect. Always constructed (works with no
  Zappi); `run()` no-ops when `spotPrice.enabled` is false. **Talks to:** sähkötin.fi (aiohttp),
  `InfluxDBHandler`, `Server`.
