'''
TripLoader — detects trips from the database (issue #5).

Trips are not tracked live. They are derived on demand by reading the Gear /
ShiftState history over a window and segmenting it: a trip is a maximal run where the
car is out of Park, with short Park stops (< min_stop_minutes) merged in so one
journey is not split at traffic lights or quick drop-offs. Detection uses Gear alone;
every other per-trip value is read from the same stored telemetry by the Trip objects
returned. All InfluxDB access is delegated to the injected InfluxDBHandler.
'''
import logging
import math
from functools import partial

import numpy as np

from ..influxdb_service.influxdb_handler import to_flux_time
from ..utils.timeline import collapse_transitions, segment
from .trip import Trip

logger = logging.getLogger("trip_service.trip_loader")

# The Gear value that means the car is parked. The teslemetry stream reports shift
# state as "ShiftState<P|R|N|D>"; anything other than Park counts as driving.
PARK_STATE = "ShiftStateP"

# A trip is a run out of Park; with nothing logged before the window the car is
# assumed parked.
segment_trips = partial(segment, is_active=lambda gear: gear != PARK_STATE,
                        idle_state=PARK_STATE)


def _window_distance(odometer, window_start_ms: int, window_end_ms: int) -> float:
    '''
    Computes a trip window's distance (km) from an already-read Odometer series,
    without another query: the delta between the last Odometer sample at/before the
    window end and the first sample at/after the window start. Odometer is stored
    already converted to km, so the delta is kilometres directly. NaN when the series
    is missing or holds no sample inside the window (a data gap) — matching the
    per-trip read's NaN so sub-threshold filtering behaves identically.
    Arguments:
        odometer (tuple | None): (count, timestamps_ms, values) from
            read_tesla_data_property("Odometer", ...), ascending by time, or None.
        window_start_ms (int): Trip window start, epoch-ms UTC.
        window_end_ms (int): Trip window end, epoch-ms UTC.
    '''
    if odometer is None:
        return float("nan")
    count, timestamps, values = odometer
    if count == 0 or len(values) == 0:
        return float("nan")
    low = int(np.searchsorted(timestamps, window_start_ms, side="left"))
    high = int(np.searchsorted(timestamps, window_end_ms, side="right")) - 1
    if low > high or low >= count or high < 0:
        return float("nan")
    return float(values[high] - values[low])


class TripLoader:
    '''
    Detects trips from stored Gear history.
    Arguments:
        influx_handler (InfluxDBHandler): Shared data-access layer. Never queries the
            client directly — only its typed read methods.
        config (Config): Provides trip_config (min_stop_minutes, min_trip_distance_km).
    '''

    GEAR_ID = "Gear"
    # How far back current_trip looks: a day first, which holds the drive under way (one
    # that started earlier is cut at the boundary, and none lasts that long), then a week
    # for the last trip of a car parked longer.
    CURRENT_LOOKBACK_MS = 24 * 60 * 60 * 1000
    LAST_TRIP_LOOKBACK_MS = 7 * 24 * 60 * 60 * 1000

    def __init__(self, influx_handler, config):
        self.__influx = influx_handler
        # Retained so apply_config() can re-read the tunables at runtime.
        self.__config = config
        trip_config = config.trip_config
        self.__min_stop_ms = int(trip_config["min_stop_minutes"]) * 60 * 1000
        self.__min_distance_km = float(trip_config["min_trip_distance_km"])
        logger.info(
            "TripLoader initialized: min_stop=%s min, min_distance=%.2f km",
            trip_config["min_stop_minutes"], self.__min_distance_km,
        )

    def apply_config(self) -> None:
        '''
        Re-reads the trip-detection tunables after the Options view writes them.
        Trips are detected on demand per request, so the next TRIP_GET_LIST already
        segments with the new thresholds -- nothing cached needs invalidating.
        '''
        trip_config = self.__config.trip_config
        self.__min_stop_ms = int(trip_config["min_stop_minutes"]) * 60 * 1000
        self.__min_distance_km = float(trip_config["min_trip_distance_km"])
        logger.info(
            "TripLoader reconfigured: min_stop=%s min, min_distance=%.2f km",
            trip_config["min_stop_minutes"], self.__min_distance_km,
        )

    async def list_trips(
        self, start_ms: int, end_ms: int, park_threshold_s: int | None = None,
        min_distance_km: float | None = None,
    ) -> list:
        '''
        Returns the trips whose driving falls within [start_ms, end_ms], in
        chronological order. Reads the Gear history for the window, collapses it to
        transitions, segments into trips (merging Park stops shorter than the
        threshold), and discards sub-min-distance shuffles.
        Arguments:
            start_ms (int): Window start, epoch-ms UTC.
            end_ms (int): Window end, epoch-ms UTC.
            park_threshold_s (int | None): Per-request override (seconds) for the Park
                merge threshold; falls back to the configured min_stop_minutes when
                None or non-positive.
            min_distance_km (float | None): Per-request override for the shortest trip
                kept; falls back to the configured min_trip_distance_km when None.
        Returns:
            list[Trip]: The detected trips (each computes its own summary on demand).
        '''
        if end_ms <= start_ms:
            return []

        threshold_ms = (
            park_threshold_s * 1000
            if park_threshold_s and park_threshold_s > 0
            else self.__min_stop_ms
        )
        minimum_km = self.__min_distance_km if min_distance_km is None else min_distance_km

        start_iso = to_flux_time(start_ms)
        end_iso = to_flux_time(end_ms)

        history = await self.__influx.read_value_string_history(
            self.GEAR_ID, start_iso, end_iso
        )
        if not history:
            return []

        transitions = collapse_transitions(history)
        # The held Gear just before the window: lets a trip already under way at the
        # window boundary be recognised (same idea as the History boundary-fill).
        held_before = await self.__influx.read_last_string_before(self.GEAR_ID, start_iso)

        windows = segment_trips(transitions, held_before, start_ms, end_ms, threshold_ms)
        if not windows:
            return []

        # Read the whole window's Odometer ONCE and compute each trip's distance from
        # the in-memory series — a single query regardless of trip count, so a wide
        # scan (e.g. the week-counts span across many weeks) stays cheap instead of one
        # Odometer read per candidate trip. Each Trip is seeded with its distance, so a
        # later distance_km()/summary() reuses it without another read.
        odometer = await self.__influx.read_tesla_data_property(
            "Odometer", start_iso, end_iso
        )

        trips = []
        for window_start, window_end, in_progress in windows:
            distance = _window_distance(odometer, window_start, window_end)
            # Drop sub-threshold shuffles (e.g. moving the car in the driveway). Keep a
            # trip whose distance can't be computed (NaN) rather than silently losing a
            # real trip on a data gap.
            if not math.isnan(distance) and distance < minimum_km:
                logger.debug(
                    "Discarding sub-threshold trip (%.3f km < %.3f km): start=%s",
                    distance, minimum_km, window_start,
                )
                continue
            trip = Trip(self.__influx, window_start, window_end, in_progress)
            trip.seed_distance_km(distance)
            trips.append(trip)

        logger.info(
            "Detected %d trip(s) in [%s, %s]", len(trips), start_ms, end_ms
        )
        return trips

    async def current_trip(self, now_ms: int) -> tuple[Trip | None, bool]:
        '''
        Returns the drive under way, or the last trip when the car is parked, by the same
        detection as list_trips. The newest trip is under way while the car is still
        driving or has been parked for less than the Park merge threshold (a stop that
        short would still be merged into it), and counts from the moment the car left
        Park — no minimum distance, so a map draws it from the first metres. A finished
        trip must pass min_trip_distance_km, so moving the car in the driveway does not
        stand in for the last real trip.
        Arguments:
            now_ms (int): The present moment, epoch-ms UTC.
        Returns:
            tuple[Trip | None, bool]: The trip and whether it is under way; (None, False)
                when the car has made no trip in a week.
        '''
        for lookback in (self.CURRENT_LOOKBACK_MS, self.LAST_TRIP_LOOKBACK_MS):
            trips = await self.list_trips(now_ms - lookback, now_ms, min_distance_km=0.0)
            if not trips:
                continue
            last = trips[-1]
            if last.in_progress or now_ms - last.end_ms < self.__min_stop_ms:
                return last, True
            for trip in reversed(trips):
                distance = await trip.distance_km()
                if math.isnan(distance) or distance >= self.__min_distance_km:
                    return trip, False
        return None, False

    async def load_route(self, start_ms: int, end_ms: int) -> list:
        '''
        Loads one trip's GPS path with per-fix speed, for the Trips-view map overlay.
        The frontend already knows the trip's [start_ms, end_ms] from a prior
        list_trips reply, so the detail request echoes that window verbatim rather than
        re-detecting: a Trip is constructed directly over it and asked for its route.
        Arguments:
            start_ms (int): The trip's start (its natural key), epoch-ms UTC.
            end_ms (int): The trip's end, epoch-ms UTC.
        Returns:
            list: [(timestamp_ms, latitude, longitude, speed_kmh), ...] ascending, or
                an empty list for an inverted window / a window with no logged fixes.
        '''
        if end_ms <= start_ms:
            return []
        trip = Trip(self.__influx, start_ms, end_ms)
        return await trip.route()

    async def load_summary(self, start_ms: int, end_ms: int) -> dict | None:
        '''
        Computes one trip's summary metrics (distance, energy, avg/max speed,
        consumption, SoC at the endpoints) for the Trips-view stats panel. Like
        load_route, the frontend already knows the trip's [start_ms, end_ms] from a
        prior list_trips reply, so a Trip is constructed directly over that window and
        asked for its summary — no re-detection.
        Arguments:
            start_ms (int): The trip's start (its natural key), epoch-ms UTC.
            end_ms (int): The trip's end, epoch-ms UTC.
        Returns:
            dict | None: Trip.summary() for the window, or None for an inverted window.
        '''
        if end_ms <= start_ms:
            return None
        trip = Trip(self.__influx, start_ms, end_ms)
        return await trip.summary()
