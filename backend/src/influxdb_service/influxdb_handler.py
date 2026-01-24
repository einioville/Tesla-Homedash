from influxdb_client.client.influxdb_client_async import InfluxDBClientAsync
import numpy as np
from datetime import datetime
from ..utils.config_parser import ConfigUtils


class InfluxDBHandler:
    def __init__(self, url: str, org: str):
        self.__url = url
        self.__token = ConfigUtils.get_env("INFLUX_TOKEN")
        self.__org = org
        self.__client = InfluxDBClientAsync(url=url, token=self.__token, org=org)
        self.__bucket = "data"

    async def connected(self) -> bool:
        return await self.__client.ping()

    async def close(self) -> None:
        await self.__client.close()

    async def restart(self) -> None:
        await self.close()
        self.__client = InfluxDBClientAsync(
            url=self.__url, token=self.__token, org=self.__org
        )

    async def read_tesla_data_property(
        self,
        data_property_id: str,
        relative_time: str = None,
        time_start: str = None,
        time_end: str = None,
        min_value: int = None,
        max_value: int = None,
    ) -> tuple:
        if (
            relative_time is not None
            and time_start is not None
            and time_end is not None
        ):
            raise ValueError(
                "relative_time must be None when time_start and time_end are not None or vise versa"
            )

        query = f'from(bucket:"{self.__bucket}")'

        if relative_time is not None:
            query += f"\n  |> range(start: -{relative_time}, stop: now())"

        if time_start is not None and time_end is not None:
            query += f"\n  |> range(start: {time_start}, stop: {time_end})"

        query += '\n  |> filter(fn: (r) => r["_measurement"] == "tesla_data")'

        query += f'\n  |> filter(fn: (r) => r["id"] == "{data_property_id}")'

        if min_value is not None:
            query += f"\n  |> filter(fn: (r) => r._value >= {min_value})"
        if max_value is not None:
            query += f"\n  |> filter(fn: (r) => r._value <= {max_value})"

        query += '\n  |> keep(columns: ["_time", "_value"])'

        result = await self.__client.query_api().query(query=query)

        if len(result) > 1:
            raise Exception("There was more than one table")
        
        if len(result) == 0:
            return None

        table = result[0]

        timestamps = np.array(
            [record.get_time().timestamp() * 1000 for record in table], dtype=np.int64
        )
        values = np.array([record.get_value() for record in table], dtype=np.float64)

        return len(values), timestamps, values

    async def write_tesla_data(self, points: list) -> bool:
        valid_points = [p for p in points if p is not None]
        if len(valid_points) == 0:
            return True
        return await self.__client.write_api().write(bucket="data", record=valid_points)
    
    async def read_first_value_day(self, data_property_id: str):
        current_day = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        
        query = f'from(bucket:"{self.__bucket}")'
        query += f'\n  |> range(start: {current_day})'
        query += '\n  |> filter(fn: (r) => r["_measurement"] == "tesla_data")'
        query += f'\n  |> filter(fn: (r) => r["id"] == "{data_property_id}")'
        query += '\n  |> keep(columns: ["_time", "_value"])'
        query += '\n  |> first()'
        
        result = await self.__client.query_api().query(query=query)
        
        if len(result) > 1:
            raise Exception("There was more than one table")
        
        if len(result) == 0:
            return None
        
        table = result[0]
        
        return table.records[0].get_value()
    
    async def read_first_value_month(self, data_property_id: str):
        current_day = datetime.now().astimezone().replace(day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
        
        query = f'from(bucket:"{self.__bucket}")'
        query += f'\n  |> range(start: {current_day})'
        query += '\n  |> filter(fn: (r) => r["_measurement"] == "tesla_data")'
        query += f'\n  |> filter(fn: (r) => r["id"] == "{data_property_id}")'
        query += '\n  |> keep(columns: ["_time", "_value"])'
        query += '\n  |> first()'
        
        result = await self.__client.query_api().query(query=query)
        
        if len(result) > 1:
            raise Exception("There was more than one table")
        
        if len(result) == 0:
            return None
        
        table = result[0]
        
        return table.records[0].get_value()
