'''
Pins Vehicle's and VehicleDataProperty's behaviour: the MSG_STREAM batches sent
on connect and on sleep, the climate target steps and their bounds, the value
lock (placeholder, drop, release, clear, sleep reset) and the calculated-field
formula.  The vehicle is built from config_template.json with a fake server and
no InfluxDB.

Runs under pytest, or standalone: `uv run python tests/test_vehicle.py`.
'''
import asyncio
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.tesla_service.vehicle import Vehicle  # noqa: E402
from src.tesla_service.vehicle_data_property import (  # noqa: E402
    CalculatedVehicleDataProperty,
    VehicleDataProperty,
)
from src.utils import protocol  # noqa: E402
from src.utils.config_parser import Config  # noqa: E402

TEMPLATE = os.path.join(os.path.dirname(__file__), "..", "..", "config_template.json")


class FakeServer:
    '''Records what the vehicle sends.'''

    def __init__(self):
        self.sent = []
        self.broadcasts = []

    async def send_to(self, _writer, data):
        '''Records one reply.'''
        self.sent.append(data)

    async def broadcast(self, data):
        '''Records one broadcast.'''
        self.broadcasts.append(data)


def _vehicle():
    directory = tempfile.mkdtemp()
    path = os.path.join(directory, "backend_config.json")
    shutil.copyfile(TEMPLATE, path)
    server = FakeServer()
    vehicle = Vehicle("VIN", influx_db_handler=None, server=server, access_token="t",
                      config=Config(path))
    return vehicle, server


async def _batch(properties) -> bytes:
    parts = [await p.get_stream_data() for p in properties]
    return b"".join(protocol.frame(protocol.MSG_STREAM, part) for part in parts if part is not None)


def test_stream_everything_batches_every_valued_field():
    async def run():
        vehicle, server = _vehicle()
        speed = await vehicle.get_data_property("VehicleSpeed")
        gear = await vehicle.get_data_property("Gear")
        await speed.update(10, 1_000)
        await gear.update("ShiftStateD", 2_000)
        await vehicle.stream_everything("client")
        return server.sent, await _batch([gear, speed])
    sent, expected = asyncio.run(run())
    # Gear precedes VehicleSpeed in config_template.json's field order.
    assert sent == [expected]


def test_sleep_defaults_broadcast_changed_fields_once():
    async def run():
        vehicle, server = _vehicle()
        speed = await vehicle.get_data_property("VehicleSpeed")
        await speed.update(10, 1_000)
        await vehicle._Vehicle__apply_sleep_defaults(5_000)
        first = list(server.broadcasts)
        await vehicle._Vehicle__apply_sleep_defaults(6_000)
        defaults = [p for p in vehicle._Vehicle__data.values()
                    if p._VehicleDataProperty__sleep_default is not None]
        return first, server.broadcasts, await _batch(defaults), await speed.get_value()
    first, after_second, expected, speed = asyncio.run(run())
    assert first == [expected]
    assert after_second == first  # nothing changed the second time
    assert speed == 0


def test_climate_target_steps_and_bounds():
    async def run():
        vehicle, server = _vehicle()
        left = await vehicle.get_data_property("HvacLeftTemperatureRequest")
        right = await vehicle.get_data_property("HvacRightTemperatureRequest")
        results = []
        for start, step, expected in ((20.0, "plus", 20.5), (20.0, "minus", 19.5),
                                      (28.0, "plus", 28.0), (15.0, "minus", 15.0),
                                      (30.0, "minus", 29.5), (14.0, "plus", 14.5)):
            await left.update(start, 1_000)
            await right.update(start, 1_000)
            vehicle._Vehicle__temperature_updated = False
            server.broadcasts.clear()
            await getattr(vehicle, f"{step}_temp")()
            moved = expected != start
            results.append((
                await left.get_value(), await right.get_value(),
                server.broadcasts == ([protocol.frame(protocol.MSG_STREAM, await left.get_stream_data()),
                                       protocol.frame(protocol.MSG_STREAM, await right.get_stream_data())]
                                      if moved else []),
                vehicle._Vehicle__temperature_updated == moved,
                expected,
            ))
        return results
    for left, right, broadcasts_ok, flag_ok, expected in asyncio.run(run()):
        assert (left, right) == (expected, expected)
        assert broadcasts_ok and flag_ok, expected


def test_value_lock():
    async def run():
        p = VehicleDataProperty("HvacPower", 1, "Climate", None, sleep_default="Off")
        await p.update("Off", 1)
        await p.lock_value_until("Pending", "On", 60)
        seen = [await p.get_value()]
        await p.update("Off", 2)            # not the target: dropped
        seen.append(await p.get_value())
        await p.update("On", 3)             # the target: released and applied
        seen.append(await p.get_value())
        await p.update("Off", 4)            # lock gone: applied
        seen.append(await p.get_value())

        await p.lock_value_until("Pending", "On", 60)
        await p.clear_value_lock("Manual")
        seen.append(await p.get_value())
        await p.update("Off", 5)
        seen.append(await p.get_value())

        await p.update("On", 6)
        await p.lock_value_until("Pending", "Off", 60)
        changed = await p.apply_sleep_default(7)
        await p.update("On", 8)             # the sleep reset dropped the lock
        seen += [changed, await p.get_value()]
        return seen
    assert asyncio.run(run()) == ["Pending", "Pending", "On", "Off", "Manual", "Off", True, "On"]


class StubVehicle:
    '''What a calculated property asks its vehicle for.'''

    def __init__(self, baseline):
        self.baseline = baseline
        self.streamed = 0

    async def get_first_data_today(self, _data_id):
        '''The day's stored baseline.'''
        return self.baseline

    async def get_first_data_this_month(self, _data_id):
        '''The month's stored baseline.'''
        return self.baseline

    async def stream_data_property(self, _prop):
        '''Counts streams.'''
        self.streamed += 1


def test_calculated_property():
    async def run():
        vehicle = StubVehicle(baseline=5.0)
        p = CalculatedVehicleDataProperty("DrivenToday", 27, "Driving", vehicle, "Odometer",
                                          "day", "y - x", formula="x * 2")
        values = []
        await p.update(10, 1)               # baseline still 0: 20 - 0
        values.append(await p.get_value())
        await p.update_calculate_value()    # baseline 5: formula(5, 5)
        values.append(await p.get_value())
        await p.update(10, 2)               # 20 - 5
        values.append(await p.get_value())
        return values, vehicle.streamed
    assert asyncio.run(run()) == ([20.0, 0.0, 15.0], 1)


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
