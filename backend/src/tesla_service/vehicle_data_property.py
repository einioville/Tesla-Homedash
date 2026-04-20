import asyncio
import logging
from sympy import symbols, sympify
from influxdb_client import Point, WritePrecision
import datetime
from datetime import timezone
from json import dumps
import struct
from zoneinfo import ZoneInfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

logger = logging.getLogger("tesla_service.vehicle_data_property")


class VehicleDataProperty:
    def __init__(
        self,
        data_id: str,
        stream_id: int,
        category: str,
        vehicle,
        unit: str = None,
        formula: str = None,
        log: bool = False,
    ):
        self.__id = data_id
        self.__stream_id = stream_id
        self.__category = category
        self.__unit = unit
        self._value = None
        self.__timestamp = None
        self.__formula = formula
        if self.__formula is not None:
            self.__sympy_x = symbols("x")
            self.__sympy_expr = sympify(self.__formula)
        self.__log = log
        self._async_lock = asyncio.Lock()
        self._vehicle = vehicle
        self.__value_type = None

    async def update(self, value, timestamp) -> None:
        if value is None:
            return
        if self.__value_type is None:
            if isinstance(value, bool):
                self.__value_type = "value_bool"
            elif isinstance(value, int) or isinstance(value, float):
                self.__value_type = "value_float"
            elif isinstance(value, str):
                self.__value_type = "value_string"
            elif isinstance(value, dict):
                self.__value_type = "value_dict"
        async with self._async_lock:
            if self.__formula is not None:
                self._value = float(
                    self.__sympy_expr.subs(self.__sympy_x, value).evalf()
                )
            else:
                if self.__value_type == "value_float":
                    self._value = float(value)
                else:
                    self._value = value
            if timestamp is not None:
                self.__timestamp = timestamp
            logger.debug("Property updated: %s = %s", self.__id, self._value)

    async def get_value(self):
        async with self._async_lock:
            return self._value

    async def get_id(self):
        async with self._async_lock:
            return self.__id

    async def get_category(self):
        async with self._async_lock:
            return self.__category

    async def get_unit(self):
        async with self._async_lock:
            return self.__unit

    async def get_logging(self):
        async with self._async_lock:
            return self.__log

    async def get_value_type(self):
        async with self._async_lock:
            return self.__value_type

    async def get_influxdb_point(self) -> Point:
        async with self._async_lock:
            if self._value is None or self.__timestamp is None:
                return
            try:
                point = (
                    Point("tesla_data")
                    .tag("vin", self._vehicle.vin)
                    .tag("category", self.__category)
                    .tag("id", self.__id)
                    .time(
                        datetime.datetime.fromtimestamp(
                            self.__timestamp / 1000, tz=timezone.utc
                        ),
                        WritePrecision.MS,
                    )
                )
                if self.__value_type == "value_dict":
                    for key, value in self._value.items():
                        point = point.field(key, value)
                else:
                    point = point.field(self.__value_type, self._value)
                return point
            except Exception as e:
                logger.error("Failed to create InfluxDB point for %s: %s", self.__id, e)
                return

    async def get_as_json(self) -> str:
        async with self._async_lock:
            data = {
                "id": self.__id,
                "category": self.__category,
                "unit": self.__unit,
                "value": self._value,
                "value_type": self.__value_type,
                "timestamp": self.__timestamp,
            }
            return dumps(data)

    async def get_as_dict(self) -> dict:
        async with self._async_lock:
            data = {
                "id": self.__id,
                "category": self.__category,
                "unit": self.__unit,
                "value": self._value,
                "value_type": self.__value_type,
                "timestamp": self.__timestamp,
            }
            return data

    async def get_stream_data(self) -> bytes:
        async with self._async_lock:
            if (
                self.__stream_id is None
                or self.__timestamp is None
                or self.__value_type is None
                or self._value is None
            ):
                return None

            stream_id = struct.pack("!H", self.__stream_id)
            timestamp = struct.pack("!Q", self.__timestamp)

            if self.__value_type == "value_float":
                value_type = struct.pack("!B", 0)
                value = struct.pack("!d", self._value)
                return stream_id + value_type + value + timestamp

            if self.__value_type == "value_string":
                value_type = struct.pack("!B", 1)
                value = self._value.encode("utf-8")
                value_length = struct.pack("!H", len(value))
                return stream_id + value_type + value_length + value + timestamp

            if self.__value_type == "value_bool":
                value_type = struct.pack("!B", 2)
                value = struct.pack("!B", self._value)
                return stream_id + value_type + value + timestamp

            if self.__value_type == "value_dict":
                value_type = struct.pack("!B", 3)
                value = bytes()
                for entry in self._value.values():
                    value += struct.pack("!d", entry)
                return stream_id + value_type + value + timestamp


class CalculatedVehicleDataProperty(VehicleDataProperty):
    def __init__(
        self,
        data_id,
        stream_id,
        category,
        vehicle,
        source_data_id,
        period,
        calculation_formula,
        unit=None,
        formula=None,
        log=False,
    ):
        super().__init__(data_id, stream_id, category, vehicle, unit, formula, log)

        self.__source_data_id = source_data_id

        self.__calculation_formula = calculation_formula
        self.__calculation_sympy_x = symbols("x")
        self.__calculation_sympy_y = symbols("y")
        self.__calculation_sympy_expr = sympify(self.__calculation_formula)
        self.__calculate_value = 0
        self.__unable_to_retrieve_value = False

        self.__period = period

    async def init_schedulers(self, scheduler: AsyncIOScheduler, timezone: str) -> None:
        '''
        Registers the periodic reset job on the provided scheduler.
        Must be called once after construction, before the first telemetry event.
        Arguments:
            scheduler (AsyncIOScheduler): The shared APScheduler instance from Vehicle.
            timezone (str): IANA timezone string (e.g. "Europe/Helsinki") used to
                anchor the cron reset to the correct local midnight.
        '''
        self.__scheduler = scheduler
        if self.__period == "month":
            self.__scheduler.add_job(
                self.update_calculate_value,
                trigger=CronTrigger(day=1, hour=0, minute=0, timezone=ZoneInfo(timezone)),
            )
        else:
            self.__scheduler.add_job(
                self.update_calculate_value,
                trigger=CronTrigger(hour=0, minute=0, timezone=ZoneInfo(timezone)),
            )
        logger.info("Scheduled %s reset for property: %s", self.__period, self._VehicleDataProperty__id)

    async def update_calculate_value(self) -> None:
        '''
        Fetches the period baseline from InfluxDB and resets the derived value.
        Called at midnight (daily) or on the 1st of the month, and once during
        startup via init_async_dependent().  I/O is performed outside the lock
        so telemetry updates are never blocked during the database roundtrip.
        '''
        # Fetch the period baseline OUTSIDE the lock — this is an async I/O
        # operation and must not hold _async_lock while it runs.
        if self.__period == "month":
            new_base = await self._vehicle.get_first_data_this_month(
                self.__source_data_id
            )
        else:
            new_base = await self._vehicle.get_first_data_today(
                self.__source_data_id
            )

        # If no historical data exists yet, fall back to the current live value.
        if new_base is None:
            data_property = await self._vehicle.get_data_property(
                self.__source_data_id
            )
            new_base = await data_property.get_value()

        async with self._async_lock:
            if new_base is None:
                # Still nothing — defer until the first telemetry reading arrives.
                self.__unable_to_retrieve_value = True
                logger.warning("Unable to retrieve baseline for %s, deferring", self._VehicleDataProperty__id)
                return

            self.__calculate_value = new_base
            self.__unable_to_retrieve_value = False
            # Derived value resets to zero at the period boundary
            # (e.g. DrivenToday = 0 at midnight): formula(base, base) = base - base = 0.
            self._value = float(
                self.__calculation_sympy_expr.subs(
                    {
                        self.__calculation_sympy_x: self.__calculate_value,
                        self.__calculation_sympy_y: self.__calculate_value,
                    }
                ).evalf()
            )

        await self._vehicle.stream_data_property(self)
        

    async def update(self, value, timestamp) -> None:
        '''
        Receives a new raw telemetry value, applies the input formula (via super),
        then applies the calculation formula under the lock to produce the derived
        value (e.g. km driven today = current_odometer - start_of_day_odometer).
        Arguments:
            value: Raw telemetry value from the Teslemetry stream.
            timestamp: Event timestamp in milliseconds (epoch).
        '''
        # super() stores the formula-converted raw value under its own lock.
        await super().update(value, timestamp)

        # Re-acquire the lock so the calculation formula application is atomic
        # with respect to concurrent get_value() / get_stream_data() calls.
        async with self._async_lock:
            if self.__unable_to_retrieve_value:
                # First live reading after startup — use it as the period baseline.
                self.__calculate_value = self._value
                self.__unable_to_retrieve_value = False

            self._value = float(
                self.__calculation_sympy_expr.subs(
                    {
                        self.__calculation_sympy_x: self.__calculate_value,
                        self.__calculation_sympy_y: self._value,
                    }
                ).evalf()
            )

        logger.debug(
            "Calculated property updated: id=%s, base=%s, raw=%s, derived=%s",
            self._VehicleDataProperty__id, self.__calculate_value, value, self._value
        )
