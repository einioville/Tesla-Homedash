'''
Pins InfluxDBHandler's reads against a fake client: the exact Flux each read
sends, how records become the returned value, and what an unreachable database,
an empty result and an unexpected second table do.

Runs under pytest, or standalone: `uv run python tests/test_influxdb_handler.py`.
'''
import asyncio
import os
import sys
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.influxdb_service.influxdb_handler import InfluxDBHandler  # noqa: E402

UTC = timezone.utc
T1 = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
T2 = datetime(2026, 1, 2, 3, 4, 6, tzinfo=UTC)


class Record:
    '''A FluxRecord stand-in.'''

    def __init__(self, time, value=None, **values):
        self.time, self.value, self.values = time, value, values

    def get_time(self):
        '''The record's _time.'''
        return self.time

    def get_value(self):
        '''The record's _value.'''
        return self.value


class Table:
    '''A FluxTable stand-in: iterable, with .records.'''

    def __init__(self, records):
        self.records = records

    def __iter__(self):
        return iter(self.records)


class Client:
    '''Records each query; answers with `tables`, or raises `error`.'''

    def __init__(self, tables=None, error=None):
        self.tables, self.error, self.queries = tables or [], error, []

    def query_api(self):
        '''Returns itself as the query API.'''
        return self

    async def query(self, query):
        '''Records the query and answers it.'''
        self.queries.append(query)
        if self.error:
            raise self.error
        return self.tables


def handler(client) -> InfluxDBHandler:
    h = InfluxDBHandler.__new__(InfluxDBHandler)
    h._InfluxDBHandler__client = client
    h._InfluxDBHandler__bucket = "data"
    h._InfluxDBHandler__timezone = ZoneInfo("UTC")
    return h


def run(coro):
    return asyncio.run(coro)


def outcomes(call, good_tables, check_good):
    '''Runs one read four ways: unreachable, no table, two tables, data.'''
    assert run(call(handler(Client(error=OSError("down"))))) is None
    assert run(call(handler(Client([])))) is None
    try:
        run(call(handler(Client([Table([]), Table([])]))))
        raise AssertionError("two tables did not raise")
    except Exception as e:  # noqa: BLE001 - the read raises a bare Exception
        assert str(e) == "There was more than one table"
    client = Client(good_tables)
    check_good(run(call(handler(client))))
    return client.queries[0]


def _series_check(result):
    count, ts, values = result
    assert count == 2
    assert ts.dtype == np.int64 and list(ts) == [int(T1.timestamp() * 1000), int(T2.timestamp() * 1000)]
    assert values.dtype == np.float64 and list(values) == [1.5, 2.5]


SERIES = [Table([Record(T1, 1.5), Record(T2, None), Record(T2, 2.5)])]


def test_read_tesla_data_property():
    query = outcomes(lambda h: h.read_tesla_data_property("Odometer", "-1h", "now()"), SERIES, _series_check)
    assert query == ('from(bucket:"data")\n  |> range(start: -1h, stop: now())'
                     '\n  |> filter(fn: (r) => r["_measurement"] == "tesla_data")'
                     '\n  |> filter(fn: (r) => r["id"] == "Odometer")'
                     '\n  |> filter(fn: (r) => r["_field"] == "value_float")'
                     '\n  |> keep(columns: ["_time", "_value"])')
    assert run(handler(Client([Table([Record(T1, None)])])).read_tesla_data_property("X", "a", "b")) is None


def test_read_charger_data_property():
    query = outcomes(lambda h: h.read_charger_data_property("GridPower", "a", "b"), SERIES, _series_check)
    assert query == ('from(bucket:"data")\n  |> range(start: a, stop: b)'
                     '\n  |> filter(fn: (r) => r["_measurement"] == "myenergi_data")'
                     '\n  |> filter(fn: (r) => r["id"] == "GridPower")'
                     '\n  |> filter(fn: (r) => r["_field"] == "value_float")'
                     '\n  |> keep(columns: ["_time", "_value"])'
                     '\n  |> sort(columns: ["_time"])')


def test_read_last_value_before():
    def check(value):
        assert value == 7.0 and isinstance(value, float)
    query = outcomes(lambda h: h.read_last_value_before("Odometer", "2026-01-01T00:00:00Z"),
                     [Table([Record(T1, 7)])], check)
    assert query == ('from(bucket:"data")\n  |> range(start: 0, stop: 2026-01-01T00:00:00Z)'
                     '\n  |> filter(fn: (r) => r["_measurement"] == "tesla_data")'
                     '\n  |> filter(fn: (r) => r["id"] == "Odometer")'
                     '\n  |> filter(fn: (r) => r["_field"] == "value_float")'
                     '\n  |> keep(columns: ["_time", "_value"])'
                     '\n  |> last()')
    assert run(handler(Client([Table([])])).read_last_value_before("X", "s")) is None
    assert run(handler(Client([Table([Record(T1, None)])])).read_last_value_before("X", "s")) is None


def test_read_value_string_history():
    def check(value):
        assert value == [(int(T1.timestamp() * 1000), "ShiftStateP"), (int(T2.timestamp() * 1000), "ShiftStateD")]
    query = outcomes(lambda h: h.read_value_string_history("Gear", "a", "b"),
                     [Table([Record(T1, "ShiftStateP"), Record(T2, None), Record(T2, "ShiftStateD")])], check)
    assert query == ('from(bucket:"data")\n  |> range(start: a, stop: b)'
                     '\n  |> filter(fn: (r) => r["_measurement"] == "tesla_data")'
                     '\n  |> filter(fn: (r) => r["id"] == "Gear")'
                     '\n  |> filter(fn: (r) => r["_field"] == "value_string")'
                     '\n  |> keep(columns: ["_time", "_value"])'
                     '\n  |> sort(columns: ["_time"])')


def test_read_last_string_before():
    query = outcomes(lambda h: h.read_last_string_before("Gear", "s"),
                     [Table([Record(T1, "ShiftStateD")])], lambda v: v == "ShiftStateD" or 1 / 0)
    assert query == ('from(bucket:"data")\n  |> range(start: 0, stop: s)'
                     '\n  |> filter(fn: (r) => r["_measurement"] == "tesla_data")'
                     '\n  |> filter(fn: (r) => r["id"] == "Gear")'
                     '\n  |> filter(fn: (r) => r["_field"] == "value_string")'
                     '\n  |> keep(columns: ["_time", "_value"])'
                     '\n  |> last()')


def test_read_location_history():
    def check(value):
        assert value == [(int(T1.timestamp() * 1000), 61.0, 23.0)]
    query = outcomes(lambda h: h.read_location_history("a", "b"),
                     [Table([Record(T1, latitude=61, longitude=23), Record(T2, latitude=None, longitude=1)])],
                     check)
    assert query == ('from(bucket:"data")\n  |> range(start: a, stop: b)'
                     '\n  |> filter(fn: (r) => r["_measurement"] == "tesla_data")'
                     '\n  |> filter(fn: (r) => r["id"] == "Location")'
                     '\n  |> filter(fn: (r) => r["_field"] == "latitude" or r["_field"] == "longitude")'
                     '\n  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")'
                     '\n  |> keep(columns: ["_time", "latitude", "longitude"])'
                     '\n  |> sort(columns: ["_time"])')


def test_read_first_values():
    for read, day in (("read_first_value_day", None), ("read_first_value_month", 1)):
        now = datetime.now(ZoneInfo("UTC"))
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        if day:
            start = start.replace(day=day)
        query = outcomes(lambda h: getattr(h, read)("Odometer"), [Table([Record(T1, 12)])],
                         lambda v: v == 12 or 1 / 0)
        assert query == (f'from(bucket:"data")\n  |> range(start: {start.isoformat()})'
                         '\n  |> filter(fn: (r) => r["_measurement"] == "tesla_data")'
                         '\n  |> filter(fn: (r) => r["id"] == "Odometer")'
                         '\n  |> keep(columns: ["_time", "_value"])'
                         '\n  |> first()'), read


def test_unsafe_ids_are_refused():
    h = handler(Client())
    for call in (lambda: h.read_tesla_data_property('x") or (r', "a", "b"),
                 lambda: h.read_charger_data_property("x y", "a", "b"),
                 lambda: h.read_last_value_before("x;", "s"),
                 lambda: h.read_value_string_history("", "a", "b"),
                 lambda: h.read_last_string_before("ä", "s"),
                 lambda: h.read_first_value_day("x)"),
                 lambda: h.read_first_value_month("x)")):
        try:
            run(call())
            raise AssertionError("unsafe id accepted")
        except ValueError:
            pass


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
