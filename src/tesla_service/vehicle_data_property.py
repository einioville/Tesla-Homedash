import asyncio
from sympy import symbols, sympify
from influxdb_client import Point, WritePrecision
import datetime
from datetime import timezone
from json import dumps
import struct
from apscheduler.schedulers.asyncio import AsyncIOScheduler


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
                print(e)
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

        self.__period = period

    async def init_schedulers(self, scheduler: AsyncIOScheduler) -> None:
        self.__unable_to_retrieve_value = False
        self.__scheduler = scheduler
        if self.__period == "month":
            self.__scheduler.add_job(
                self.update_calculate_value, trigger="cron", day=1, hour=0, minute=0
            )
        else:
            self.__scheduler.add_job(
                self.update_calculate_value, trigger="cron", hour=0, minute=0
            )

    async def update_calculate_value(self) -> None:
        async with self._async_lock:
            if self.__period == "month":
                self.__calculate_value = await self._vehicle.get_first_data_this_month(
                    self.__source_data_id
                )
            else:
                self.__calculate_value = await self._vehicle.get_first_data_today(
                    self.__source_data_id
                )

            print(f"\n\n{self.__calculate_value}\n\n")

            if self.__calculate_value is None:
                data_property = await self._vehicle.get_data_property(
                    self.__source_data_id
                )
                self.__calculate_value = await data_property.get_value()

                if self.__calculate_value is None:
                    self.__unable_to_retrieve_value = True
        
        if not self.__unable_to_retrieve_value:
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
        await super().update(value, timestamp)

        if self.__unable_to_retrieve_value:
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
        

        print(
            f"\n\nCalculate value: {self.__calculate_value}\nOg value: {value}\nValue: {self._value}\n\n"
        )
