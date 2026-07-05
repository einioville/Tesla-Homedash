'''
ChargingSession — a single detected charging session and its loss breakdown.

A ChargingSession is a window [start_ms, end_ms] over telemetry already stored in
InfluxDB. Like Trip, it is a pure value object: it owns no detection logic
(ChargingLoader finds the window) and no protocol/serialization (the request handler
packs the summary). summary() reads the relevant series for the window through the
injected InfluxDBHandler and computes the per-session metrics on demand, caching the
result.

The loss model uses three energy readings over the same window:
  - charger_kwh  : energy the Zappi delivered this session (myenergi "ChargeAdded",
                   an accumulator that ramps from 0 — so the in-window MAX is the total)
  - ac_in_kwh    : AC energy the car's onboard charger took in (Tesla
                   "ACChargingEnergyIn", a lifetime counter — so the in-window DELTA)
  - battery_kwh  : energy that actually reached the pack (Tesla "EnergyRemaining"
                   delta over the window)
and derives:
  - loss_cable_kwh       = charger_kwh - ac_in_kwh        (Zappi<->car metering/cable)
  - loss_conversion_kwh  = ac_in_kwh   - battery_kwh      (onboard AC->DC conversion)
  - loss_total_kwh       = charger_kwh - battery_kwh      (wall -> battery)
  - loss_total_pct       = loss_total_kwh / charger_kwh * 100
Every metric degrades to float('nan') when its source series is missing, so a
partial-data session still yields a well-formed record.
'''
import logging
import math
from datetime import datetime, timezone

logger = logging.getLogger("charging_service.charging_session")

# InfluxDB "id" tags this module reads. The charger ids are written by
# MyEnergiService under the "myenergi_data" measurement; the tesla ids are logged by
# Vehicle under "tesla_data". Kept as constants so the writer and reader can't drift.
CHARGER_ENERGY_ID = "ChargeAdded"        # myenergi: kWh added this session (accumulator)
AC_ENERGY_IN_ID = "ACChargingEnergyIn"   # tesla: lifetime AC energy into the car (kWh)
DC_ENERGY_IN_ID = "DCChargingEnergyIn"   # tesla: lifetime DC energy into the car (kWh)
BATTERY_ENERGY_ID = "EnergyRemaining"    # tesla: energy currently in the pack (kWh)
SOC_ID = "BatteryLevel"                  # tesla: state of charge (%)


def to_flux_time(timestamp_ms: int) -> str:
    '''
    Converts an epoch-ms instant to the RFC3339 string Flux expects (matching the
    idiom the History and Trip paths use). InfluxDBHandler reads take Flux range
    strings, not raw ms.
    Arguments:
        timestamp_ms (int): Milliseconds since the Unix epoch (UTC).
    '''
    return (
        datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _series_values(result):
    '''
    Extracts the values array from a read result tuple (count, timestamps_ms,
    values), or None if the result is empty/missing.
    Arguments:
        result (tuple | None): The (count, timestamps, values) triple or None.
    '''
    if result is None:
        return None
    count, _timestamps, values = result
    if count == 0 or len(values) == 0:
        return None
    return values


def _delta(result) -> float:
    '''Last minus first value of a series (a lifetime-counter delta), or NaN.'''
    values = _series_values(result)
    if values is None:
        return float("nan")
    return float(values[-1] - values[0])


def _max(result) -> float:
    '''Maximum of a series (an accumulator's in-window peak), or NaN if empty.'''
    values = _series_values(result)
    return float(values.max()) if values is not None else float("nan")


def _first(result) -> float:
    '''First value of a series, or NaN if empty/missing.'''
    values = _series_values(result)
    return float(values[0]) if values is not None else float("nan")


def _last(result) -> float:
    '''Last value of a series, or NaN if empty/missing.'''
    values = _series_values(result)
    return float(values[-1]) if values is not None else float("nan")


def _diff(a: float, b: float) -> float:
    '''a - b, propagating NaN (either operand NaN -> NaN).'''
    if math.isnan(a) or math.isnan(b):
        return float("nan")
    return a - b


class ChargingSession:
    '''
    A single detected charging session over stored telemetry.

    The natural key is start_ms (epoch-ms): unique per session and re-derivable, so
    the frontend can request a session's detail by echoing it without server-side
    bookkeeping (identical convention to Trip).
    Arguments:
        influx_handler (InfluxDBHandler): The shared data-access layer. All InfluxDB
            access goes through it (never a direct client).
        start_ms (int): Session start (first moment the car reported charging),
            epoch-ms UTC.
        end_ms (int): Session end (charging stopped/completed, or the window end for a
            session still in progress), epoch-ms UTC.
        in_progress (bool): True if the car was still charging at the query-window end
            (no stop observed yet).
    '''

    def __init__(self, influx_handler, start_ms: int, end_ms: int, in_progress: bool = False):
        self.__influx = influx_handler
        self.__start_ms = int(start_ms)
        self.__end_ms = int(end_ms)
        self.__in_progress = in_progress
        self.__summary: dict | None = None
        self.__charger_kwh: float | None = None

    @property
    def session_id(self) -> int:
        '''Stable natural key for the session (== start_ms).'''
        return self.__start_ms

    @property
    def start_ms(self) -> int:
        return self.__start_ms

    @property
    def end_ms(self) -> int:
        return self.__end_ms

    @property
    def in_progress(self) -> bool:
        return self.__in_progress

    def seed_charger_kwh(self, value: float) -> None:
        '''
        Seeds the cached charger energy from a value computed elsewhere (ChargingLoader
        reads the whole span's ChargeAdded once and takes each window's in-memory max),
        so charger_kwh()/summary() don't re-read it per session. NaN when the window
        held no charger sample (a session at another charger).
        Arguments:
            value (float): The session's delivered energy in kWh (may be NaN).
        '''
        self.__charger_kwh = value

    async def charger_kwh(self) -> float:
        '''
        Computes (and caches) just the charger-delivered energy (kWh): the in-window
        MAX of the myenergi ChargeAdded accumulator (it ramps from 0 to the session
        total). Split out from summary() so the session-list path — which only needs
        this for its min-energy filter and the CHARGING_LIST record — can skip the
        other reads summary() performs. summary() reuses this value. NaN when no
        charger sample falls in the window.
        '''
        if self.__charger_kwh is not None:
            return self.__charger_kwh
        start_iso = to_flux_time(self.__start_ms)
        end_iso = to_flux_time(self.__end_ms)
        charger = await self.__influx.read_charger_data_property(
            CHARGER_ENERGY_ID, start_iso, end_iso
        )
        self.__charger_kwh = _max(charger)
        return self.__charger_kwh

    async def summary(self) -> dict:
        '''
        Computes (and caches) the session's loss breakdown. Charger energy is the
        in-window max of the myenergi accumulator; AC-in / DC-in / battery energies are
        deltas of the vehicle's in-window series; SoC is read at the window endpoints.
        Losses are simple differences, each NaN if either operand is missing — so a
        session with no charger data (charged elsewhere) reports NaN losses rather than
        a fabricated number. duration is wall-clock (start to end).
        '''
        if self.__summary is not None:
            return self.__summary

        start_iso = to_flux_time(self.__start_ms)
        end_iso = to_flux_time(self.__end_ms)

        charger_kwh = await self.charger_kwh()

        ac_in = await self.__influx.read_tesla_data_property(AC_ENERGY_IN_ID, start_iso, end_iso)
        dc_in = await self.__influx.read_tesla_data_property(DC_ENERGY_IN_ID, start_iso, end_iso)
        battery = await self.__influx.read_tesla_data_property(BATTERY_ENERGY_ID, start_iso, end_iso)
        soc = await self.__influx.read_tesla_data_property(SOC_ID, start_iso, end_iso)

        ac_in_kwh = _delta(ac_in)
        dc_in_kwh = _delta(dc_in)
        battery_kwh = _delta(battery)

        loss_cable_kwh = _diff(charger_kwh, ac_in_kwh)
        loss_conversion_kwh = _diff(ac_in_kwh, battery_kwh)
        loss_total_kwh = _diff(charger_kwh, battery_kwh)
        loss_total_pct = (
            loss_total_kwh / charger_kwh * 100.0
            if (not math.isnan(loss_total_kwh) and not math.isnan(charger_kwh) and charger_kwh > 0)
            else float("nan")
        )

        self.__summary = {
            "session_id": self.__start_ms,
            "start_ms": self.__start_ms,
            "end_ms": self.__end_ms,
            "duration_s": (self.__end_ms - self.__start_ms) / 1000.0,
            "charger_kwh": charger_kwh,
            "ac_in_kwh": ac_in_kwh,
            "dc_in_kwh": dc_in_kwh,
            "battery_kwh": battery_kwh,
            "loss_cable_kwh": loss_cable_kwh,
            "loss_conversion_kwh": loss_conversion_kwh,
            "loss_total_kwh": loss_total_kwh,
            "loss_total_pct": loss_total_pct,
            "start_soc": _first(soc),
            "end_soc": _last(soc),
            "in_progress": self.__in_progress,
        }
        logger.debug(
            "Computed charging summary: start=%s end=%s charger=%s kWh battery=%s kWh loss=%s%%",
            self.__start_ms, self.__end_ms,
            "n/a" if math.isnan(charger_kwh) else f"{charger_kwh:.2f}",
            "n/a" if math.isnan(battery_kwh) else f"{battery_kwh:.2f}",
            "n/a" if math.isnan(loss_total_pct) else f"{loss_total_pct:.1f}",
        )
        return self.__summary
