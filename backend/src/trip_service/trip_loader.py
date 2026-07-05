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

import numpy as np

from .trip import Trip, to_flux_time

logger = logging.getLogger("trip_service.trip_loader")

# The Gear value that means the car is parked. The teslemetry stream reports shift
# state as "ShiftState<P|R|N|D>"; anything other than Park counts as driving.
PARK_STATE = "ShiftStateP"


def collapse_transitions(history: list) -> list:
    '''
    Collapses consecutive identical Gear readings into transitions. Logged fields are
    written on every telemetry event (not only on change), so the raw history repeats
    the held value; only the points where it changes are real transitions. Pure logic
    (no I/O) — the testable core of detection.
    Arguments:
        history (list): [(timestamp_ms, gear_str), ...] ascending by time.
    Returns:
        list: The same shape, with runs of identical gear reduced to their first point.
    '''
    collapsed = []
    previous = None
    for timestamp_ms, gear in history:
        if gear != previous:
            collapsed.append((timestamp_ms, gear))
            previous = gear
    return collapsed


def segment_trips(
    transitions: list, held_before, start_ms: int, end_ms: int, threshold_ms: int
) -> list:
    '''
    Turns a collapsed Gear timeline into trip windows. Walks the timeline as contiguous
    [from, to) intervals per held gear, treating any non-Park gear as driving. A Park
    interval shorter than threshold_ms is absorbed into the surrounding trip; a longer
    one (or the window end) closes the trip. Pure logic (no I/O) — the testable core.
    Arguments:
        transitions (list): Collapsed [(timestamp_ms, gear_str), ...].
        held_before (str | None): The Gear held just before start_ms, or None if
            nothing was logged before the window. A non-Park held state captures a trip
            already under way at the window boundary.
        start_ms (int): Window start, epoch-ms UTC.
        end_ms (int): Window end, epoch-ms UTC.
        threshold_ms (int): Park duration at/above which a stop ends a trip.
    Returns:
        list: [(window_start_ms, window_end_ms, in_progress), ...].
    '''
    if not transitions:
        return []

    # State governing the timeline from the window start. If a value was held before
    # the window, use it; otherwise assume Park (don't fabricate a drive we can't bound).
    start_state = held_before if held_before is not None else PARK_STATE
    sequence = [(start_ms, start_state)]
    for timestamp_ms, gear in transitions:
        if timestamp_ms > start_ms:
            sequence.append((timestamp_ms, gear))
    # Re-collapse in case the synthetic start state equals the first transition.
    sequence = collapse_transitions(sequence)

    windows = []
    trip_start = None
    last_drive_end = None

    for index, (segment_start, gear) in enumerate(sequence):
        segment_end = sequence[index + 1][0] if index + 1 < len(sequence) else end_ms
        is_driving = gear != PARK_STATE

        if is_driving:
            if trip_start is None:
                trip_start = segment_start
            last_drive_end = segment_end
        elif trip_start is not None:
            # A Park interval while a trip is open.
            park_duration = segment_end - segment_start
            if park_duration >= threshold_ms:
                windows.append((trip_start, last_drive_end, False))
                trip_start = None
                last_drive_end = None
            # Shorter stop: leave the trip open; the next drive segment extends
            # last_drive_end across this absorbed stop.

    if trip_start is not None:
        # No long-enough closing Park was seen inside the window. If the last segment
        # was a drive reaching the window end, the car is still driving (in progress);
        # otherwise close at the last observed movement.
        in_progress = last_drive_end == end_ms
        windows.append((trip_start, last_drive_end, in_progress))

    return windows


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
    # First sample at/after the window start, last sample at/before the window end.
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

    def __init__(self, influx_handler, config):
        self.__influx = influx_handler
        trip_config = config.trip_config
        self.__min_stop_ms = int(trip_config["min_stop_minutes"]) * 60 * 1000
        self.__min_distance_km = float(trip_config["min_trip_distance_km"])
        logger.info(
            "TripLoader initialized: min_stop=%s min, min_distance=%.2f km",
            trip_config["min_stop_minutes"], self.__min_distance_km,
        )

    async def list_trips(
        self, start_ms: int, end_ms: int, park_threshold_s: int | None = None
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
            if not math.isnan(distance) and distance < self.__min_distance_km:
                logger.debug(
                    "Discarding sub-threshold trip (%.3f km < %.3f km): start=%s",
                    distance, self.__min_distance_km, window_start,
                )
                continue
            trip = Trip(self.__influx, window_start, window_end, in_progress)
            trip.seed_distance_km(distance)
            trips.append(trip)

        logger.info(
            "Detected %d trip(s) in [%s, %s]", len(trips), start_ms, end_ms
        )
        return trips

    async def load_route(self, start_ms: int, end_ms: int) -> list:
        '''
        Loads one trip's GPS path with per-fix speed, for the Trips-view map overlay.
        The frontend already knows the trip's [start_ms, end_ms] from a prior
        list_trips reply, so the detail request echoes that window verbatim rather than
        re-detecting: a Trip is constructed directly over it and asked for its route.
        Keeps all InfluxDB access behind the injected handler (Trip owns the reads).
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
        asked for its summary — no re-detection. Every metric degrades to NaN when its
        source series is missing, so a partial-data trip still yields a record.
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
