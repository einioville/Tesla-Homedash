'''
Unit tests for the trip-detection core (issue #5).

Covers the pure segmentation logic — collapse_transitions and segment_trips — with
synthetic Gear timelines: single trips, short-stop merging, long-stop splitting,
in-progress trips, boundary-spanning trips (driving at the window edge), reverse/neutral
counting as driving, and the all-parked and trailing-short-stop edge cases.

Runs under pytest, or standalone: `python backend/tests/test_trip_loader.py`.
'''
import math
import os
import sys

import numpy as np

# Make `src` importable whether run via pytest or directly (backend/ is the root, the
# same root run.py uses with `from src.tesla_service... import`).
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.trip_service.trip_loader import (  # noqa: E402
    _window_distance,
    collapse_transitions,
    segment_trips,
)

PARK = "ShiftStateP"
DRIVE = "ShiftStateD"
REVERSE = "ShiftStateR"

T0 = 1_700_000_000_000  # arbitrary epoch-ms base
WINDOW_END = T0 + 120 * 60 * 1000  # 2 h window
THRESHOLD_MS = 10 * 60 * 1000  # 10 min Park merge threshold


def m(minutes: int) -> int:
    '''Window-relative timestamp: T0 + the given number of minutes, in epoch-ms.'''
    return T0 + minutes * 60 * 1000


def test_collapse_removes_consecutive_duplicates():
    raw = [(m(0), PARK), (m(1), PARK), (m(2), DRIVE), (m(3), DRIVE), (m(4), PARK)]
    assert collapse_transitions(raw) == [(m(0), PARK), (m(2), DRIVE), (m(4), PARK)]


def test_single_completed_trip():
    # Parked, drive 10→40, then a long park to the window end.
    transitions = [(m(10), DRIVE), (m(40), PARK)]
    windows = segment_trips(transitions, PARK, T0, WINDOW_END, THRESHOLD_MS)
    assert windows == [(m(10), m(40), False)]


def test_short_stop_is_merged():
    # Drive 10→30, 5-min park (< 10), drive 35→50, long park.
    transitions = [(m(10), DRIVE), (m(30), PARK), (m(35), DRIVE), (m(50), PARK)]
    windows = segment_trips(transitions, PARK, T0, WINDOW_END, THRESHOLD_MS)
    assert windows == [(m(10), m(50), False)]  # one trip, stop absorbed


def test_long_stop_splits_into_two_trips():
    # Drive 10→30, 20-min park (>= 10), drive 50→70, long park.
    transitions = [(m(10), DRIVE), (m(30), PARK), (m(50), DRIVE), (m(70), PARK)]
    windows = segment_trips(transitions, PARK, T0, WINDOW_END, THRESHOLD_MS)
    assert windows == [(m(10), m(30), False), (m(50), m(70), False)]


def test_in_progress_trip_reaches_window_end():
    # Still driving when the window ends -> one in-progress trip to the end.
    transitions = [(m(10), DRIVE)]
    windows = segment_trips(transitions, PARK, T0, WINDOW_END, THRESHOLD_MS)
    assert windows == [(m(10), WINDOW_END, True)]


def test_boundary_spanning_trip_starts_at_window_start():
    # Already driving at the window start (held = DRIVE); parks at 20.
    transitions = [(m(20), PARK)]
    windows = segment_trips(transitions, DRIVE, T0, WINDOW_END, THRESHOLD_MS)
    assert windows == [(T0, m(20), False)]


def test_reverse_counts_as_driving():
    # Backing out (R) then driving (D) is one trip; any non-Park gear is "driving".
    transitions = [(m(10), REVERSE), (m(11), DRIVE), (m(40), PARK)]
    windows = segment_trips(transitions, PARK, T0, WINDOW_END, THRESHOLD_MS)
    assert windows == [(m(10), m(40), False)]


def test_all_parked_yields_no_trips():
    transitions = collapse_transitions([(m(5), PARK), (m(60), PARK)])
    windows = segment_trips(transitions, PARK, T0, WINDOW_END, THRESHOLD_MS)
    assert windows == []


def test_trailing_short_stop_closes_at_last_movement():
    # Window ends 5 min into a park (< threshold): the trip is completed at the last
    # movement, NOT marked in-progress.
    end = m(105)
    transitions = [(m(10), DRIVE), (m(100), PARK)]
    windows = segment_trips(transitions, PARK, T0, end, THRESHOLD_MS)
    assert windows == [(m(10), m(100), False)]


def test_empty_history_yields_no_trips():
    assert segment_trips([], PARK, T0, WINDOW_END, THRESHOLD_MS) == []


# --- _window_distance (in-memory Odometer delta over a trip window) --------------

def _odo(times_min: list, values_km: list) -> tuple:
    '''Builds a (count, timestamps_ms, values) Odometer read result from minute
    offsets + km values, matching read_tesla_data_property's numpy return.'''
    timestamps = np.array([m(t) for t in times_min], dtype=np.int64)
    values = np.array(values_km, dtype=np.float64)
    return len(values), timestamps, values


def test_window_distance_basic_delta():
    # Samples every 10 min; window m(10)..m(40) -> last-at/before minus first-at/after.
    odo = _odo([0, 10, 20, 30, 40, 50], [100, 101, 103, 106, 110, 111])
    assert _window_distance(odo, m(10), m(40)) == 110.0 - 101.0


def test_window_distance_none_or_empty_is_nan():
    assert math.isnan(_window_distance(None, m(0), m(10)))
    empty = (0, np.array([], dtype=np.int64), np.array([], dtype=np.float64))
    assert math.isnan(_window_distance(empty, m(0), m(10)))


def test_window_distance_no_sample_in_window_is_nan():
    # Samples only at the window's outside; nothing inside [m(10), m(40)] -> NaN.
    odo = _odo([0, 50], [100, 200])
    assert math.isnan(_window_distance(odo, m(10), m(40)))


def test_window_distance_single_sample_is_zero():
    # A window holding exactly one sample has a zero delta (matches the per-trip read).
    odo = _odo([0, 20, 50], [100, 150, 200])
    assert _window_distance(odo, m(15), m(25)) == 0.0


if __name__ == "__main__":
    # Standalone runner so the suite works without pytest installed.
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
