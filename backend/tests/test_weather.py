'''
Pins the weather forecast's per-hour values: the hour it is labelled with in the
configured display timezone, and how missing or non-numeric FMI values read.

Runs under pytest, or standalone: `uv run python tests/test_weather.py`.
'''
import math
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.weather_service.weather_service import ForecastHour  # noqa: E402


def _hour(data):
    return ForecastHour(datetime(2026, 7, 1, 21, 0), data, ZoneInfo("Europe/Helsinki"))


def test_hour_is_shown_in_the_display_timezone():
    assert _hour({}).get_time() == 0          # 21:00 UTC is 00:00 EEST
    winter = ForecastHour(datetime(2026, 1, 1, 21, 0), {}, ZoneInfo("Europe/Helsinki"))
    assert winter.get_time() == 23


def test_values_and_their_fallbacks():
    hour = _hour({
        "Air temperature": {"value": 12.5, "units": "degC"},
        "Wind speed": {"value": float("nan"), "units": "m/s"},
        "Total cloud cover": {"value": None, "units": "%"},
        "Precipitation amount": {"value": "x", "units": "mm"},
    })
    assert hour.get_value("Air temperature") == 12.5
    assert hour.get_value("Wind speed") == 0.0
    assert hour.get_value("Total cloud cover") == 0.0
    assert hour.get_value("Precipitation amount") == 0.0
    assert hour.get_value("Humidity", default=-1.0) == -1.0
    assert hour.get_measurement("Humidity") is None
    assert not math.isnan(hour.get_measurement("Wind speed").get_value())


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
