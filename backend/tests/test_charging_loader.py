'''
Unit tests for charging-session detection and the per-trip / per-session summaries:
the DetailedChargeState segmentation (the charging analogue of segment_trips), the
in-memory window energy, and the summary fields the TRIP_SUMMARY / CHARGING_SUMMARY
frames carry, computed over a fake InfluxDB.

Runs under pytest, or standalone: `uv run python tests/test_charging_loader.py`.
'''
import asyncio
import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import start_services as ss  # noqa: E402
from src.charging_service.charging_loader import (  # noqa: E402
    _window_energy,
    collapse_transitions,
    segment_sessions,
)
from src.charging_service.charging_session import ChargingSession  # noqa: E402
from src.trip_service.trip import Trip  # noqa: E402

CHARGING = "DetailedChargeStateCharging"
COMPLETE = "DetailedChargeStateComplete"
STOPPED = "DetailedChargeStateStopped"

T0 = 1_700_000_000_000
WINDOW_END = T0 + 120 * 60 * 1000
THRESHOLD_MS = 5 * 60 * 1000


def m(minutes: float) -> int:
    '''Window-relative timestamp: T0 + the given number of minutes, in epoch-ms.'''
    return T0 + int(minutes * 60 * 1000)


def test_collapse_removes_consecutive_duplicates():
    raw = [(m(0), STOPPED), (m(1), STOPPED), (m(2), CHARGING), (m(3), CHARGING), (m(4), COMPLETE)]
    assert collapse_transitions(raw) == [(m(0), STOPPED), (m(2), CHARGING), (m(4), COMPLETE)]


def test_single_session():
    transitions = [(m(10), CHARGING), (m(40), COMPLETE)]
    assert segment_sessions(transitions, STOPPED, T0, WINDOW_END, THRESHOLD_MS) == [(m(10), m(40), False)]


def test_short_pause_is_merged():
    transitions = [(m(10), CHARGING), (m(30), STOPPED), (m(33), CHARGING), (m(50), COMPLETE)]
    assert segment_sessions(transitions, STOPPED, T0, WINDOW_END, THRESHOLD_MS) == [(m(10), m(50), False)]


def test_long_pause_splits_sessions():
    transitions = [(m(10), CHARGING), (m(30), STOPPED), (m(50), CHARGING), (m(70), COMPLETE)]
    assert segment_sessions(transitions, STOPPED, T0, WINDOW_END, THRESHOLD_MS) == [
        (m(10), m(30), False), (m(50), m(70), False)]


def test_in_progress_session_reaches_window_end():
    assert segment_sessions([(m(10), CHARGING)], STOPPED, T0, WINDOW_END, THRESHOLD_MS) == [
        (m(10), WINDOW_END, True)]


def test_session_under_way_at_window_start():
    assert segment_sessions([(m(20), COMPLETE)], CHARGING, T0, WINDOW_END, THRESHOLD_MS) == [
        (T0, m(20), False)]


def test_nothing_held_before_is_not_charging():
    # No state before the window: a session cannot be assumed to be under way.
    assert segment_sessions([(m(20), COMPLETE)], None, T0, WINDOW_END, THRESHOLD_MS) == []
    assert segment_sessions([(m(10), CHARGING), (m(20), COMPLETE)], None, T0, WINDOW_END,
                            THRESHOLD_MS) == [(m(10), m(20), False)]


def test_charging_match_is_case_insensitive_substring():
    transitions = [(m(10), "charging"), (m(40), "Complete")]
    assert segment_sessions(transitions, "Stopped", T0, WINDOW_END, THRESHOLD_MS) == [(m(10), m(40), False)]


def test_empty_history_yields_no_sessions():
    assert segment_sessions([], STOPPED, T0, WINDOW_END, THRESHOLD_MS) == []


def _series(times_min: list, values: list) -> tuple:
    return (len(values), np.array([m(t) for t in times_min], dtype=np.int64),
            np.array(values, dtype=np.float64))


def test_window_energy_sums_positive_increments():
    # Carries 10 kWh in, resets at 30, ramps again: only the increments count.
    charger = _series([0, 10, 20, 30, 40, 50], [10.0, 12.0, 15.0, 0.5, 2.5, 99.0])
    assert _window_energy(charger, m(10), m(40)) == (3.0 + 0.0 + 2.0)


def test_window_energy_nan_cases():
    assert math.isnan(_window_energy(None, m(0), m(10)))
    assert math.isnan(_window_energy(_series([], []), m(0), m(10)))
    assert math.isnan(_window_energy(_series([0, 20], [1.0, 2.0]), m(5), m(15)))


class FakeInflux:
    '''Serves fixed series by property id; records which ids were read.'''

    def __init__(self, tesla: dict, charger: dict | None = None):
        self.tesla = tesla
        self.charger = charger or {}
        self.reads = []

    async def read_tesla_data_property(self, data_id, _start, _end):
        '''Returns the fixed series for a tesla property, or None.'''
        self.reads.append(data_id)
        return self.tesla.get(data_id)

    async def read_charger_data_property(self, data_id, _start, _end):
        '''Returns the fixed series for a charger property, or None.'''
        self.reads.append(data_id)
        return self.charger.get(data_id)

    async def read_location_endpoint(self, _start, _end, last=False):
        '''Returns a fixed GPS fix.'''
        self.reads.append("Location")
        return (61.5, 23.8) if last else (61.4, 23.7)


def _summary_values(summary: dict, fields: tuple) -> list:
    return [summary.get(f, float("nan")) for f in fields]


def _same(a: list, b: list) -> bool:
    return all((math.isnan(x) and math.isnan(y)) or x == y for x, y in zip(a, b)) and len(a) == len(b)


def test_trip_summary_fields():
    influx = FakeInflux({
        "Odometer": _series([0, 30], [1000.0, 1025.0]),
        "VehicleSpeed": _series([0, 10, 20], [0.0, 60.0, 90.0]),
        "LifetimeEnergyUsed": _series([0, 30], [500.0, 504.0]),
        "BatteryLevel": _series([0, 30], [80.0, 76.0]),
    })
    summary = asyncio.run(Trip(influx, m(0), m(30)).summary())
    assert _same(_summary_values(summary, ss._TRIP_SUMMARY_FIELDS),
                 [25.0, 50.0, 90.0, 4000.0, 160.0, 80.0, 76.0])


def test_trip_summary_missing_series_are_nan():
    summary = asyncio.run(Trip(FakeInflux({}), m(0), m(30)).summary())
    assert all(math.isnan(v) for v in _summary_values(summary, ss._TRIP_SUMMARY_FIELDS))


def test_charging_summary_fields():
    influx = FakeInflux(
        {
            "ACChargingEnergyIn": _series([0, 60], [100.0, 109.0]),
            "EnergyRemaining": _series([0, 60], [40.0, 48.0]),
            "BatteryLevel": _series([0, 60], [50.0, 60.0]),
        },
        {"ChargeAdded": _series([0, 30, 60], [0.0, 5.0, 10.0])},
    )
    session = ChargingSession(influx, m(0), m(60), flat_tariff=0.2)
    summary = asyncio.run(session.summary())
    assert _same(_summary_values(summary, ss._CHARGING_SUMMARY_FIELDS),
                 [10.0, 9.0, 8.0, 1.0, 1.0, 2.0, 20.0, 50.0, 60.0, 2.0, 0.2])


def test_charging_summary_without_pricing():
    summary = asyncio.run(ChargingSession(FakeInflux({}), m(0), m(60)).summary())
    assert all(math.isnan(v) for v in _summary_values(summary, ss._CHARGING_SUMMARY_FIELDS))


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for test in tests:
        try:
            test()
            print(f"PASS  {test.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {test.__name__}: {e}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
