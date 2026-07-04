'''
Trip — a single detected trip and its computed summary.

A Trip is a window [start_ms, end_ms] over telemetry already stored in InfluxDB. It
is a pure value object: it owns no detection logic (TripLoader finds the window) and
no protocol/serialization (the request handler packs the summary). summary() reads the
relevant property series for the window through the injected InfluxDBHandler and
computes the per-trip metrics on demand, caching the result.
'''
import logging
import math
from datetime import datetime, timezone

logger = logging.getLogger("trip_service.trip")


def to_flux_time(timestamp_ms: int) -> str:
    '''
    Converts an epoch-ms instant to the RFC3339 string Flux expects, matching the
    idiom the History path uses (datetime.fromtimestamp(...).isoformat() with the
    "+00:00" suffix normalised to "Z"). InfluxDBHandler reads take Flux range
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
    Extracts the values array from a read_tesla_data_property result tuple
    (count, timestamps_ms, values), or None if the result is empty/missing.
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
    '''Last minus first value of a series (e.g. odometer/energy delta), or NaN.'''
    values = _series_values(result)
    if values is None:
        return float("nan")
    return float(values[-1] - values[0])


def _delta_scaled(result, scale: float) -> float:
    '''_delta multiplied by a scale factor (e.g. kWh -> Wh), preserving NaN.'''
    delta = _delta(result)
    return delta * scale if not math.isnan(delta) else float("nan")


def _mean(result) -> float:
    '''Mean of a series, or NaN if empty/missing.'''
    values = _series_values(result)
    return float(values.mean()) if values is not None else float("nan")


def _max(result) -> float:
    '''Maximum of a series, or NaN if empty/missing.'''
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


class Trip:
    '''
    A single detected trip over stored telemetry.

    The natural key is start_ms (epoch-ms): unique per trip and re-derivable, so the
    frontend can request a trip's detail by echoing it without server-side bookkeeping.
    Arguments:
        influx_handler (InfluxDBHandler): The shared data-access layer. All InfluxDB
            access goes through it (never a direct client).
        start_ms (int): Trip start (first moment out of Park), epoch-ms UTC.
        end_ms (int): Trip end (the moment it parked, or the window end for an open
            trip), epoch-ms UTC.
        in_progress (bool): True if the car was still driving at the query-window end
            (no closing Park observed yet).
    '''

    def __init__(self, influx_handler, start_ms: int, end_ms: int, in_progress: bool = False):
        self.__influx = influx_handler
        self.__start_ms = int(start_ms)
        self.__end_ms = int(end_ms)
        self.__in_progress = in_progress
        self.__summary: dict | None = None
        self.__distance_km: float | None = None

    @property
    def trip_id(self) -> int:
        '''Stable natural key for the trip (== start_ms).'''
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

    def seed_distance_km(self, value: float) -> None:
        '''
        Seeds the cached distance from a value computed elsewhere (TripLoader reads the
        whole span's Odometer once and computes each window's delta in-memory), so
        distance_km()/summary() don't re-read Odometer per trip. Idempotent-safe: a
        later distance_km() returns this without a query.
        Arguments:
            value (float): The trip's distance in km (may be NaN on a data gap).
        '''
        self.__distance_km = value

    async def distance_km(self) -> float:
        '''
        Computes (and caches) just the trip's distance in km: the Odometer delta over
        the window (Odometer is stored already converted to km). Split out from
        summary() so the trip-list path — which only needs the distance for its
        sub-threshold filter and the TRIP_LIST record — can avoid the six other
        InfluxDB reads summary() performs (7 sequential reads per candidate window is
        slow for a busy week). summary() reuses this value. NaN on a data gap.
        '''
        if self.__distance_km is not None:
            return self.__distance_km
        start_iso = to_flux_time(self.__start_ms)
        end_iso = to_flux_time(self.__end_ms)
        odometer = await self.__influx.read_tesla_data_property("Odometer", start_iso, end_iso)
        self.__distance_km = _delta(odometer)
        return self.__distance_km

    async def summary(self) -> dict:
        '''
        Computes (and caches) the trip's summary metrics. Every field degrades to
        float('nan') when its source series is missing, so a partial-data trip still
        yields a well-formed record. Distances/energies are deltas of the in-window
        series; speeds are aggregates; SoC is read at the window endpoints. duration
        is wall-clock (start to end, including any absorbed short stops).
        '''
        if self.__summary is not None:
            return self.__summary

        start_iso = to_flux_time(self.__start_ms)
        end_iso = to_flux_time(self.__end_ms)

        # Distance comes from the shared distance_km() (Odometer delta), so the list
        # path and summary don't each re-read Odometer.
        distance_km = await self.distance_km()

        # During a trip the car is active, so these logged fields have records inside
        # the window; first/last/mean/max come straight off the raw series.
        speed = await self.__influx.read_tesla_data_property("VehicleSpeed", start_iso, end_iso)
        energy_used = await self.__influx.read_tesla_data_property(
            "LifetimeEnergyUsed", start_iso, end_iso
        )
        battery = await self.__influx.read_tesla_data_property("BatteryLevel", start_iso, end_iso)
        # Optional regen field — only present once LifetimeEnergyGainedRegen is added
        # to config (an enhancement); until then this reads None -> NaN.
        regen = await self.__influx.read_tesla_data_property(
            "LifetimeEnergyGainedRegen", start_iso, end_iso
        )

        start_point = await self.__influx.read_location_endpoint(start_iso, end_iso, last=False)
        end_point = await self.__influx.read_location_endpoint(start_iso, end_iso, last=True)

        duration_s = (self.__end_ms - self.__start_ms) / 1000.0
        energy_wh = _delta_scaled(energy_used, 1000.0)
        regen_wh = _delta_scaled(regen, 1000.0)
        wh_per_km = (
            energy_wh / distance_km
            if (not math.isnan(energy_wh) and not math.isnan(distance_km) and distance_km > 0)
            else float("nan")
        )

        self.__summary = {
            "trip_id": self.__start_ms,
            "start_ms": self.__start_ms,
            "end_ms": self.__end_ms,
            "start_lat": start_point[0] if start_point else float("nan"),
            "start_lon": start_point[1] if start_point else float("nan"),
            "end_lat": end_point[0] if end_point else float("nan"),
            "end_lon": end_point[1] if end_point else float("nan"),
            "distance_km": distance_km,
            "duration_s": duration_s,
            "avg_speed": _mean(speed),
            "max_speed": _max(speed),
            "energy_wh": energy_wh,
            "regen_wh": regen_wh,
            "wh_per_km": wh_per_km,
            "start_soc": _first(battery),
            "end_soc": _last(battery),
            "in_progress": self.__in_progress,
        }
        logger.debug(
            "Computed trip summary: start=%s end=%s distance=%s km",
            self.__start_ms, self.__end_ms,
            "n/a" if math.isnan(distance_km) else f"{distance_km:.2f}",
        )
        return self.__summary

    async def route(self) -> list:
        '''
        Returns the trip's GPS path with a per-fix speed, for the coloured route the
        Trips-view map draws. Reads the full Location history for the window and joins
        the logged VehicleSpeed (km/h) onto each fix by nearest timestamp — Location
        and VehicleSpeed are separate telemetry signals logged at their own cadences,
        so their records rarely share a timestamp. Both series are ascending, so the
        join is a single forward pass (the nearest speed index is non-decreasing as the
        fix time advances). Missing speed degrades to 0.0; a fix is never dropped for
        lack of a speed sample. Not cached (called once per detail request).
        Returns:
            list: [(timestamp_ms (int), latitude (float), longitude (float),
                speed_kmh (float)), ...] ascending by time. Empty when the window
                logged no GPS fixes (or InfluxDB is unreachable).
        '''
        start_iso = to_flux_time(self.__start_ms)
        end_iso = to_flux_time(self.__end_ms)

        locations = await self.__influx.read_location_history(start_iso, end_iso)
        if not locations:
            return []

        speed_result = await self.__influx.read_tesla_data_property(
            "VehicleSpeed", start_iso, end_iso
        )
        speed_ts = speed_result[1] if speed_result is not None else []
        speed_val = speed_result[2] if speed_result is not None else []
        speed_count = len(speed_ts)

        route = []
        cursor = 0
        for timestamp_ms, latitude, longitude in locations:
            speed = 0.0
            if speed_count > 0:
                # Advance to the speed sample nearest this fix. Monotone: fixes ascend,
                # so the nearest speed index never moves backwards across the loop.
                while (
                    cursor + 1 < speed_count
                    and abs(int(speed_ts[cursor + 1]) - timestamp_ms)
                    <= abs(int(speed_ts[cursor]) - timestamp_ms)
                ):
                    cursor += 1
                speed = float(speed_val[cursor])
                if speed < 0.0:
                    speed = 0.0
            route.append((int(timestamp_ms), float(latitude), float(longitude), speed))

        logger.debug(
            "Computed trip route: start=%s points=%d", self.__start_ms, len(route)
        )
        return route
