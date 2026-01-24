import asyncio
from ..utils.config_parser import ConfigUtils
from .vehicle_data_property import VehicleDataProperty, CalculatedVehicleDataProperty
from ..influxdb_service.influxdb_handler import InfluxDBHandler
from .tcp_server import TeslaDataServer
from json import dumps
from apscheduler.schedulers.asyncio import AsyncIOScheduler
import aiohttp
from datetime import datetime, timedelta


class Vehicle:
    def __init__(
        self, vin: str, influx_db_handler: InfluxDBHandler, server: TeslaDataServer
    ):
        self.__vin = vin
        self.__data = {}
        self.__calculated_data_ids = {}
        self.__async_lock = asyncio.Lock()
        self.__influx_handler = influx_db_handler
        self.__server = server
        self.__scheduler = None
        self.__load_data_properties()
        self.__temperature_updated = False
        self.__requests_used = 0

    def __load_data_properties(self) -> None:
        data_property_config = ConfigUtils.get_config()["tesla data"]
        for data_property_id, config in data_property_config.items():
            self.__data[data_property_id] = VehicleDataProperty(
                data_id=data_property_id,
                stream_id=config["stream_id"],
                category=config["category"],
                vehicle=self,
                unit=config["unit"],
                formula=config["formula"],
                log=config["log"],
            )

    async def init_async_dependent(self) -> None:
        self.__scheduler = AsyncIOScheduler()
        self.__scheduler.start()
        calculated_data_property_config = ConfigUtils.get_config()[
            "calculated tesla data"
        ]
        for data_property_id, config in calculated_data_property_config.items():
            if config["source_data_property_id"] not in self.__calculated_data_ids:
                self.__calculated_data_ids[config["source_data_property_id"]] = []
            self.__data[data_property_id] = CalculatedVehicleDataProperty(
                data_id=data_property_id,
                stream_id=config["stream_id"],
                category=config["category"],
                vehicle=self,
                unit=config["unit"],
                formula=config["formula"],
                log=False,
                calculation_formula=config["calculation_formula"],
                period=config["period"],
                source_data_id=config["source_data_property_id"],
            )
            self.__calculated_data_ids[config["source_data_property_id"]].append(
                self.__data[data_property_id]
            )
            await self.__data[data_property_id].init_schedulers(self.__scheduler)
            await self.__data[data_property_id].update_calculate_value()

    def on_telemetry_event(self, data) -> None:
        asyncio.create_task(coro=self.__update(data=data))

    async def __update(self, data) -> None:
        if data["vin"] != self.__vin:
            return

        if "timestamp" not in data:
            return
        timestamp = data["timestamp"]

        if "data" not in data:
            if "state" in data:
                online = data["state"] == "online"
                await self.__data["VehicleOnline"].update(
                    value=online, timestamp=timestamp
                )
            return

        async with self.__async_lock:
            vehicle_data = data["data"]
            update_tasks = []
            stream_tasks = []
            log = []
            for data_property_id, value in vehicle_data.items():
                if data_property_id not in self.__data:
                    continue

                print(f"{data_property_id} - {value}")

                data_property = self.__data[data_property_id]

                update_task = asyncio.create_task(
                    coro=data_property.update(value=value, timestamp=timestamp)
                )
                update_tasks.append(update_task)

                stream_task = asyncio.create_task(coro=data_property.get_stream_data())
                stream_tasks.append(stream_task)

                if await data_property.get_logging():
                    log.append(data_property)

                if data_property_id in self.__calculated_data_ids.keys():
                    for data_property in self.__calculated_data_ids[data_property_id]:
                        update_task = asyncio.create_task(
                            coro=data_property.update(value=value, timestamp=timestamp)
                        )
                        update_tasks.append(update_task)

                        stream_task = asyncio.create_task(
                            coro=data_property.get_stream_data()
                        )
                        stream_tasks.append(stream_task)

                        if await data_property.get_logging():
                            log.append(data_property)

            await asyncio.gather(*update_tasks)

            logging_tasks = []
            for data_property in log:
                update_task = asyncio.create_task(
                    coro=data_property.get_influxdb_point()
                )
                logging_tasks.append(update_task)
            log_points = await asyncio.gather(*logging_tasks)

            await self.__influx_handler.write_tesla_data(log_points)

            stream_data = await asyncio.gather(*stream_tasks)

            if len(stream_data) > 0:
                await self.__server.update_clients(
                    [data for data in stream_data if data is not None]
                )

    async def stream_data_property(self, data_property: VehicleDataProperty) -> None:
        stream_data = await data_property.get_stream_data()
        if stream_data is not None:
            await self.__server.update_clients([stream_data])

    async def get_vin(self) -> str:
        async with self.__async_lock:
            return self.__vin

    @property
    def vin(self) -> str:
        return self.__vin

    async def get_data_property(self, id: str) -> VehicleDataProperty:
        async with self.__async_lock:
            return self.__data[id]

    async def get_data_properties(self, ids: list) -> list:
        data_properties = []
        for id in ids:
            data_properties.append(await self.get_data_property(id))
        return data_properties

    async def get_data_property_as_json(self, id: str) -> str:
        async with self.__async_lock:
            return self.__data[id].as_json()

    async def get_data_properties_as_json(self, ids: list) -> str:
        async with self.__async_lock:
            data = []
            for id in ids:
                data.append(await self.__data[id].get_as_dict())
            return dumps(data)

    async def get_first_data_this_month(self, data_property_id: str) -> None:
        return await self.__influx_handler.read_first_value_month(data_property_id)

    async def get_first_data_today(self, data_property_id: str) -> None:
        return await self.__influx_handler.read_first_value_day(data_property_id)

    async def get_data_history(
        self,
        data_property_id: str,
        relative_time: str = None,
        time_start: str = None,
        time_end: str = None,
        min_value: int = None,
        max_value: int = None,
    ):
        return await self.__influx_handler.read_tesla_data_property(
            data_property_id, relative_time, time_start, time_end, min_value, max_value
        )

    async def switch_climate_state(self) -> None:
        if self.__requests_used > 4:
            return

        data_property = await self.get_data_property("HvacPower")
        value = await data_property.get_value()
        await data_property.update("HvacPowerStatePending", 1)
        await self.stream_data_property(data_property)
        print(value)
        operation = ""

        if value == "HvacPowerStateOn":
            operation = "auto_conditioning_stop"
        elif value == "HvacPowerStateOff":
            operation = "auto_conditioning_start"
        else:
            return

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url=f"https://api.teslemetry.com/api/1/vehicles/{self.__vin}/command/{operation}",
                headers={
                    "Authorization": "Bearer qga3fppats-urn4kvwniy-dtc0dc70qo-anu0nfev2z"
                },
            ) as response:
                if response.status == 200:
                    self.__requests_used += 1

        if self.__temperature_updated:
            await self.update_temperature()

        if self.__requests_used == 4:
            self.__scheduler.add_job(
                func=self.__reset_requests,
                trigger="date",
                run_date=datetime.now() + timedelta(minutes=5),
            )

    async def __reset_requests(self) -> None:
        self.__requests_used = 0

    async def update_temperature(self) -> None:
        data_property = await self.get_data_property("HvacLeftTemperatureRequest")
        value = await data_property.get_value()

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url=f"https://api.teslemetry.com/api/1/vehicles/{self.__vin}/command/set_temps",
                headers={
                    "Authorization": "Bearer qga3fppats-urn4kvwniy-dtc0dc70qo-anu0nfev2z"
                },
                json={"driver_temp": float(value), "passenger_temp": float(value)},
            ) as response:
                if response.status == 200:
                    self.__requests_used += 1

        self.__temperature_updated = False

    async def minus_temp(self) -> None:
        left = await self.get_data_property("HvacLeftTemperatureRequest")
        right = await self.get_data_property("HvacRightTemperatureRequest")

        value_left = await left.get_value()
        value_left -= 0.5

        if value_left < 15.0:
            return

        await left.update(value_left, None)
        await right.update(value_left, None)
        await self.stream_data_property(left)
        await self.stream_data_property(right)

        self.__temperature_updated = True

    async def plus_temp(self) -> None:
        left = await self.get_data_property("HvacLeftTemperatureRequest")
        right = await self.get_data_property("HvacRightTemperatureRequest")

        value_left = await left.get_value()
        value_left += 0.5

        if value_left > 28.0:
            return

        await left.update(value_left, None)
        await right.update(value_left, None)
        await self.stream_data_property(left)
        await self.stream_data_property(right)

        self.__temperature_updated = True
