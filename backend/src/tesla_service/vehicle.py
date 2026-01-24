import asyncio
from ..utils.config_parser import ConfigUtils
from .vehicle_data_property import VehicleDataProperty
from ..influxdb_service.influxdb_handler import InfluxDBHandler
from .server import TeslaDataServer
from json import dumps


class Vehicle:
    def __init__(self, vin: str, influx_db_handler: InfluxDBHandler, server: TeslaDataServer):
        self.__vin = vin
        self.__asleep = False
        self.__data = {}
        self.__async_lock = asyncio.Lock()
        self.__influx_handler = influx_db_handler
        self.__server = server
        self.__load_data_properties()

    def __load_data_properties(self) -> None:
        data_property_config = ConfigUtils.get_config()["tesla data"]
        for data_property_id, config in data_property_config.items():
            self.__data[data_property_id] = VehicleDataProperty(
                data_id=data_property_id,
                category=config["category"],
                vehicle=self,
                unit=config["unit"],
                formula=config["formula"],
                log=config["log"],
            )

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
            log = []
            for data_property_id, value in vehicle_data.items():
                if data_property_id not in self.__data:
                    continue
                data_property = self.__data[data_property_id]
                task = asyncio.create_task(
                    coro=data_property.update(value=value, timestamp=timestamp)
                )
                update_tasks.append(task)
                if await data_property.get_logging():
                    log.append(data_property)
            await asyncio.gather(*update_tasks)

            logging_tasks = []
            for data_property in log:
                task = asyncio.create_task(coro=data_property.get_influxdb_point())
                logging_tasks.append(task)
            log_points = await asyncio.gather(*logging_tasks)

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
