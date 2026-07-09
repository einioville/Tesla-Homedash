'''
Unit tests for the spot-price cost math (issue #12): the pure, I/O-free helpers that turn
raw Nord Pool prices + logged energy into per-hour cost. These are the error-prone bits —
unit conversion, hourly bucketing, and hour-boundary integration — so they are pinned here.

Runnable two ways:
  - under pytest (test_* functions), once pytest is added as a dev dependency, or
  - standalone now: `uv run python tests/test_spot_price.py` (a __main__ runner executes each
    test and reports pass/fail), so the logic is validated without new dependencies.
'''
import math
import os
import sys

# Make the backend package importable whether run standalone or under pytest.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from types import SimpleNamespace  # noqa: E402

from src.charging_service.spot_price import (  # noqa: E402
    SpotPriceProvider,
    _hour_floor_ms,
    _parse_iso_z,
    price_hourly_energy,
)
from src.charging_service.charging_session import (  # noqa: E402
    bucket_positive_increments_by_hour,
)
from src.influxdb_service.influxdb_handler import (  # noqa: E402
    integrate_power_series_hourly,
)

HOUR = 3_600_000
# A clean UTC hour boundary to anchor the fixtures on (2023-11-14T22:00:00Z).
H0 = _hour_floor_ms(1_700_000_000_000)
H1 = H0 + HOUR
H2 = H0 + 2 * HOUR


def _provider(vat=25.5, margin_c=0.0, enabled=True):
    '''Builds a SpotPriceProvider over a stub config (no network is touched by the tests).'''
    config = SimpleNamespace(spot_price_config={
        "enabled": enabled,
        "vatPercent": vat,
        "marginCentsPerKwh": margin_c,
        "baseUrl": "https://example.invalid/prices",
    })
    return SpotPriceProvider(config)


def _ingest(provider, entries):
    '''Feeds a sähkötin-shaped response into the provider's cache (bypasses the network).'''
    # __ingest is name-mangled; reach it directly so the test needs no HTTP.
    provider._SpotPriceProvider__ingest({"prices": entries})


# ── _hour_floor_ms / _parse_iso_z ──────────────────────────────────────────────

def test_hour_floor_ms():
    assert _hour_floor_ms(H0) == H0
    assert _hour_floor_ms(H0 + 1) == H0
    assert _hour_floor_ms(H1 - 1) == H0
    assert _hour_floor_ms(H1) == H1


def test_parse_iso_z():
    assert _parse_iso_z("2026-07-07T00:00:00.000Z") == 1783382400000
    # No fractional part must also parse.
    assert _parse_iso_z("2026-07-07T01:00:00Z") == 1783386000000


# ── price_hourly_energy ────────────────────────────────────────────────────────

def test_price_pure_spot():
    # 2 kWh @ 0.10 + 3 kWh @ 0.20 = 0.80 €.
    cost = price_hourly_energy({H0: 2.0, H1: 3.0}, {H0: 0.10, H1: 0.20})
    assert math.isclose(cost, 0.80)


def test_price_flat_fallback_for_missing_hour():
    # H1 has no spot price -> flat 0.15 fallback. 2*0.10 + 3*0.15 = 0.65.
    cost = price_hourly_energy({H0: 2.0, H1: 3.0}, {H0: 0.10}, flat_fallback=0.15)
    assert math.isclose(cost, 0.65)


def test_price_no_spot_all_flat_equals_flat_times_total():
    # No spot at all + flat tariff == flat * total energy (the fallback path).
    cost = price_hourly_energy({H0: 2.0, H1: 3.0}, {}, flat_fallback=0.1)
    assert math.isclose(cost, 0.5)


def test_price_nan_when_nothing_priceable():
    assert math.isnan(price_hourly_energy({H0: 2.0}, {}, flat_fallback=None))


def test_price_skips_nan_energy():
    cost = price_hourly_energy({H0: float("nan"), H1: 3.0}, {H0: 0.10, H1: 0.20})
    assert math.isclose(cost, 0.60)


def test_price_drops_unpriceable_hour_but_keeps_rest():
    # H1 has neither spot nor flat -> its energy is dropped, H0 still counts.
    cost = price_hourly_energy({H0: 2.0, H1: 3.0}, {H0: 0.10}, flat_fallback=None)
    assert math.isclose(cost, 0.20)


# ── bucket_positive_increments_by_hour ─────────────────────────────────────────

def test_bucket_basic_two_increments_same_hour():
    ts = [H0, H0 + 10_000, H0 + 20_000]
    vals = [1.0, 1.5, 2.0]  # +0.5, +0.5 -> both attributed to H0
    assert bucket_positive_increments_by_hour(ts, vals) == {H0: 1.0}


def test_bucket_ignores_carry_in():
    # A large first value (carried in from a prior charge) is the baseline, not counted;
    # only in-window increments are summed.
    ts = [H0, H0 + 10_000]
    vals = [12.0, 12.4]  # +0.4
    assert math.isclose(bucket_positive_increments_by_hour(ts, vals)[H0], 0.4)


def test_bucket_clamps_reset():
    # Accumulator reset (drop) contributes 0, not a negative.
    ts = [H0, H0 + 10_000, H0 + 20_000]
    vals = [5.0, 0.0, 0.3]  # -5.0 (clamped to 0), +0.3
    assert math.isclose(bucket_positive_increments_by_hour(ts, vals)[H0], 0.3)


def test_bucket_splits_across_hours_by_later_sample():
    # Increment recorded just after the hour boundary lands in the later hour.
    ts = [H1 - 5_000, H1 + 5_000]
    vals = [2.0, 2.6]  # +0.6, later sample is in H1
    result = bucket_positive_increments_by_hour(ts, vals)
    assert set(result.keys()) == {H1}
    assert math.isclose(result[H1], 0.6)


def test_bucket_too_short():
    assert bucket_positive_increments_by_hour([H0], [1.0]) == {}
    assert bucket_positive_increments_by_hour([], []) == {}


# ── integrate_power_series_hourly ──────────────────────────────────────────────

def test_integrate_constant_power_one_hour():
    # 1000 W held across exactly one hour = 1.0 kWh in that hour.
    result = integrate_power_series_hourly([H0, H1], [1000.0, 1000.0])
    assert set(result.keys()) == {H0}
    assert math.isclose(result[H0], 1.0)


def test_integrate_splits_at_hour_boundary():
    # 1000 W constant, sampled 40 min before to 20 min after the H1 boundary:
    # 0.6667 kWh into H0, 0.3333 kWh into H1.
    result = integrate_power_series_hourly([H1 - 40 * 60_000, H1 + 20 * 60_000],
                                           [1000.0, 1000.0])
    assert math.isclose(result[H0], 1000.0 * (40 / 60) / 1000.0)
    assert math.isclose(result[H1], 1000.0 * (20 / 60) / 1000.0)


def test_integrate_clamps_export_to_zero():
    # Negative power (grid export) is clamped to 0 -> no imported energy.
    result = integrate_power_series_hourly([H0, H1], [-2000.0, -2000.0])
    assert result.get(H0, 0.0) == 0.0


def test_integrate_trapezoid_ramp():
    # Power ramps 0 -> 3600 W over one hour: mean 1800 W -> 1.8 kWh.
    result = integrate_power_series_hourly([H0, H1], [0.0, 3600.0])
    assert math.isclose(result[H0], 1.8)


def test_integrate_too_short():
    assert integrate_power_series_hourly([H0], [1000.0]) == {}


# ── SpotPriceProvider conversion (no network) ──────────────────────────────────

def test_provider_mwh_to_kwh_and_all_in():
    p = _provider(vat=25.5, margin_c=0.5)  # margin 0.5 c/kWh = 0.005 €/kWh
    _ingest(p, [{"date": "2023-11-14T22:00:00.000Z", "value": 100.0}])  # 100 €/MWh
    raw = p.raw_price_at(H0)
    assert raw is not None
    assert math.isclose(raw, 0.10)  # 100 €/MWh -> 0.10 €/kWh
    # all_in = (0.10 + 0.005) * 1.255
    assert math.isclose(p._all_in(raw), (0.10 + 0.005) * 1.255)


def test_provider_averages_subhour_entries():
    p = _provider()
    _ingest(p, [
        {"date": "2023-11-14T22:00:00.000Z", "value": 100.0},
        {"date": "2023-11-14T22:15:00.000Z", "value": 200.0},
        {"date": "2023-11-14T22:30:00.000Z", "value": 300.0},
        {"date": "2023-11-14T22:45:00.000Z", "value": 400.0},
    ])
    # mean(100,200,300,400)=250 €/MWh -> 0.25 €/kWh
    raw = p.raw_price_at(H0)
    assert raw is not None
    assert math.isclose(raw, 0.25)


def test_provider_skips_nan_and_bad_entries():
    p = _provider()
    _ingest(p, [
        {"date": "2023-11-14T22:00:00.000Z", "value": float("nan")},
        {"date": "bogus", "value": 100.0},
        {"value": 100.0},  # missing date
        {"date": "2023-11-14T23:00:00.000Z", "value": 50.0},
    ])
    assert p.raw_price_at(H0) is None       # NaN entry dropped
    raw = p.raw_price_at(H1)
    assert raw is not None
    assert math.isclose(raw, 0.05)


def test_provider_disabled_raw_none():
    p = _provider(enabled=False)
    assert p.enabled is False


if __name__ == "__main__":
    tests = [(name, obj) for name, obj in sorted(globals().items())
             if name.startswith("test_") and callable(obj)]
    failures = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as exc:  # noqa: BLE001 — standalone runner surfaces any failure
            failures += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    sys.exit(1 if failures else 0)
