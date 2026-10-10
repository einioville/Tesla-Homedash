'''
Pins the composition root's wire work: the request/response frames the
History, Trips and Charging views read, the history range table, the request
parsing in the registered handlers, and the epoch-ms -> Flux time conversion.

Runs under pytest, or standalone: `uv run python tests/test_start_services.py`.
'''
import asyncio
import math
import os
import struct
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src import start_services as ss  # noqa: E402
from src.charging_service import charging_session  # noqa: E402
from src.influxdb_service import influxdb_handler  # noqa: E402
from src.trip_service import trip  # noqa: E402
from src.utils import protocol  # noqa: E402

NAN = float("nan")
SERIES = (2, [1_000, 2_000], [1.5, 2.5])


def _series_body(result) -> bytes:
    if result is None:
        return struct.pack("!BI", 0, 0)
    count, timestamps, values = result
    out = struct.pack("!BI", 1, count)
    for t, v in zip(timestamps, values):
        out += struct.pack("!qd", t, v)
    return out


def _id(text: str) -> bytes:
    raw = text.encode("utf-8")
    return struct.pack("!H", len(raw)) + raw


def _same(a: bytes, b: bytes) -> bool:
    # NaN doubles compare by bit pattern, so equal NaN-filled frames are equal bytes.
    return a == b


def test_history_frames():
    for build, msg_type in ((ss._build_history_frame, protocol.TESLA_HISTORY),
                            (ss._build_charger_history_frame, protocol.CHARGER_HISTORY)):
        for result in (None, SERIES):
            assert build("Speedä", result) == protocol.frame(msg_type, _id("Speedä") + _series_body(result))


def test_trip_series_frame():
    for result in (None, SERIES):
        expected = struct.pack("!q", 77) + _id("Odometer") + _series_body(result)
        assert ss._build_trip_series_frame(77, "Odometer", result) == protocol.frame(protocol.TRIP_SERIES, expected)


def test_list_frames():
    records = [(10, 20, 1.5), (30, 40, NAN)]
    expected = struct.pack("!qqH", 1, 2, 2) + struct.pack("!qqd", 10, 20, 1.5) + struct.pack("!qqd", 30, 40, NAN)
    assert _same(ss._build_trip_list_frame(1, 2, records), protocol.frame(protocol.TRIP_LIST, expected))
    assert _same(ss._build_charging_list_frame(1, 2, records), protocol.frame(protocol.CHARGING_LIST, expected))


def test_summary_frames():
    cases = (
        (ss._build_trip_summary_frame, protocol.TRIP_SUMMARY, ss._TRIP_SUMMARY_FIELDS),
        (ss._build_charging_summary_frame, protocol.CHARGING_SUMMARY, ss._CHARGING_SUMMARY_FIELDS),
    )
    for build, msg_type, fields in cases:
        summary = {fields[0]: 3.25, fields[-1]: -1.0, "ignored": 9.0}
        head = struct.pack("!qBqq", 5, 1, 5, 9)
        values = b"".join(struct.pack("!d", summary.get(f, NAN)) for f in fields)
        assert _same(build(5, 5, 9, summary), protocol.frame(msg_type, head + values))
        empty = struct.pack("!qBqq", 5, 0, 5, 9) + struct.pack("!d", NAN) * len(fields)
        assert _same(build(5, 5, 9, None), protocol.frame(msg_type, empty))


def test_month_frame():
    fields = ss._CHARGING_MONTH_FIELDS
    assert len(fields) == 13
    summary = {"km_month": 12.0}
    values = b"".join(struct.pack("!d", summary.get(f, NAN)) for f in fields)
    assert _same(ss._build_charging_month_frame(summary), protocol.frame(protocol.CHARGING_MONTH, b"\x01" + values))
    empty = b"\x00" + struct.pack("!d", NAN) * 13
    assert _same(ss._build_charging_month_frame(None), protocol.frame(protocol.CHARGING_MONTH, empty))


def test_history_range():
    assert ss._history_range(0, 0, 0) == ("-1h", "now()")
    assert ss._history_range(1, 0, 0) == ("-1d", "now()")
    assert ss._history_range(2, 0, 0) == ("-30d", "now()")
    assert ss._history_range(4, 0, 0) == ("-7d", "now()")
    assert ss._history_range(3, 1_700_000_000_000, 1_700_000_060_500) == (
        "2023-11-14T22:13:20Z", "2023-11-14T22:14:20.500000Z")
    for bad in ((3, 0, 5), (3, 10, 5), (3, 5, 5), (9, 1, 2)):
        assert ss._history_range(*bad) == ("-1h", "now()"), bad


def test_history_bounds():
    hour = 3_600_000
    for code, width in ((0, hour), (1, 24 * hour), (4, 7 * 24 * hour), (2, 30 * 24 * hour)):
        now = int(time.time() * 1000)
        start, end = ss._history_bounds_ms(code, 0, 0)
        assert end - start == width and abs(end - now) < 5_000, code
    assert ss._history_bounds_ms(3, 100, 200) == (100, 200)
    for bad in ((3, 0, 5), (3, 10, 5), (9, 1, 2)):
        start, end = ss._history_bounds_ms(*bad)
        assert end - start == hour, bad


def test_flux_time():
    cases = {1_700_000_000_000: "2023-11-14T22:13:20Z",
             1_700_000_000_123: "2023-11-14T22:13:20.123000Z"}
    for convert in (trip.to_flux_time, charging_session.to_flux_time, influxdb_handler._ms_to_flux_z):
        for ms, text in cases.items():
            assert convert(ms) == text


class FakeServer:
    '''Collects registered handlers and the replies they send.'''

    def __init__(self):
        self.handlers = {}
        self.sent = []

    def register_handler(self, msg_type, handler):
        '''Records one handler.'''
        self.handlers[msg_type] = handler

    async def send_to(self, _writer, data):
        '''Records one reply.'''
        self.sent.append(data)


class Recorder:
    '''Stands in for a service; records each awaited call and returns `result`.'''

    def __init__(self, result=None):
        self.calls = []
        self.result = result

    def __getattr__(self, name):
        async def call(*args):
            self.calls.append((name, args))
            return self.result
        return call


def _handlers(vehicle, trips, charging):
    server = FakeServer()
    ss._register_handlers(server, Recorder(), vehicle, trips, charging, None, Recorder())
    return server


def _history_request(code, prop, start, end):
    return bytes((code,)) + _id(prop) + struct.pack("!qq", start, end)


def test_history_handlers():
    for msg_type, reply_type, owner in ((protocol.TESLA_GET_HISTORY, protocol.TESLA_HISTORY, "vehicle"),
                                       (protocol.CHARGER_GET_HISTORY, protocol.CHARGER_HISTORY, "charging")):
        service = Recorder(SERIES)
        server = _handlers(service if owner == "vehicle" else Recorder(),
                           Recorder(), service if owner == "charging" else Recorder())
        handler = server.handlers[msg_type]
        asyncio.run(handler(_history_request(3, "Pä", 1_700_000_000_000, 1_700_000_060_000), None))
        name, args = service.calls[0]
        assert args == ("Pä", "2023-11-14T22:13:20Z", "2023-11-14T22:14:20Z"), args
        assert server.sent[-1] == protocol.frame(reply_type, _id("Pä") + _series_body(SERIES))
        # Truncated requests are dropped without a reply.
        for short in (b"\x00\x00", _history_request(0, "Pä", 0, 0)[:-1]):
            sent = len(server.sent)
            asyncio.run(handler(short, None))
            assert len(server.sent) == sent


def test_window_handlers():
    window = struct.pack("!qq", 100, 200)
    trips = Recorder([])
    charging = Recorder([])
    server = _handlers(Recorder(), trips, charging)
    for msg_type in (protocol.TRIP_GET_LIST, protocol.TRIP_GET_DETAIL, protocol.TRIP_GET_SUMMARY,
                     protocol.CHARGING_GET_LIST, protocol.CHARGING_GET_SUMMARY):
        sent = len(server.sent)
        asyncio.run(server.handlers[msg_type](window[:15], None))
        assert len(server.sent) == sent, msg_type
        asyncio.run(server.handlers[msg_type](window, None))
        assert len(server.sent) == sent + 1, msg_type
    assert [c for c in trips.calls] == [("list_trips", (100, 200)), ("load_route", (100, 200)),
                                        ("load_summary", (100, 200))]
    assert [c for c in charging.calls] == [("list_sessions", (100, 200)), ("load_summary", (100, 200))]


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
