from fmiopendata.wfs import download_stored_query
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import asyncio
import struct
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from ..tesla_service.tcp_server import TeslaDataServer
from ..utils.config_parser import ConfigUtils


class ForecastMeasurement:
    def __init__(self, name, value, unit: None):
        self.__name = name
        self.__value = value
        self.__unit = unit

    def get_name(self):
        return self.__name

    def get_value(self):
        return float(self.__value)

    def get_unit(self):
        return self.__unit


class ForecastHour:
    def __init__(self, time: datetime, data: dict):
        # Time is received as UTC time
        self.__time = time
        self.__time = self.__time.replace(tzinfo=ZoneInfo("UTC"))
        self.__time = self.__time.astimezone(ZoneInfo("Europe/Helsinki"))
        self.__hours = self.__time.hour
        self.__time = self.__time.strftime("%H")

        self.__data = {}
        for name, value in data.items():
            self.__data[name] = ForecastMeasurement(
                name=name, value=value["value"], unit=value["units"]
            )

    def get_value(self, key) -> float:
        return self.__data[key].get_value()

    def get_time(self) -> int:
        return self.__hours


class WeatherService:
    FORECAST_TIME = 0x35
    FORECAST_TEMPERATURE = 0x31
    FORECAST_WIND_SPEED = 0x32
    FORECAST_PRECIPITATION = 0x33
    FORECAST_TOTAL_CLOUD_COVER = 0x34

    def __init__(self, server: TeslaDataServer):
        self.__loop = asyncio.get_running_loop()
        self.__server = server
        self.__scheduler = AsyncIOScheduler()
        self.__scheduler.start()
        self.__scheduler.add_job(
            func=self.__update_forecast,
            trigger=CronTrigger(hour="*", minute="0,15,30,45"),
        )
        self.__timezone = ConfigUtils.get_config()["timeZone"]

    async def __update_forecast(self) -> None:
        now = (
            datetime.now()
            .astimezone(timezone.utc)
            .replace(minute=30, second=0, microsecond=0)
        )
        offset = now + timedelta(hours=6)
        now_str = now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        offset_str = offset.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

        data = await self.__loop.run_in_executor(
            None,
            lambda: download_stored_query(
                query_id="fmi::forecast::harmonie::surface::point::multipointcoverage",
                args=[
                    f"starttime={now_str}",
                    f"endtime={offset_str}",
                    "place=Tampere",
                ],
            ),
        )
        data = data.data

        forecasts = []

        for time, value in data.items():
            forecasts.append(ForecastHour(time, next(iter(value.values()))))

        await self.__server.update_forecast(await self.__get_stream_data(forecasts))

    async def __get_stream_data(self, forecasts: list) -> bytes:
        data = []

        for forecast in forecasts:
            forecast_data = bytes()
            forecast_data += struct.pack("!B", WeatherService.FORECAST_TIME)
            forecast_data += struct.pack("!B", forecast.get_time())

            forecast_data += struct.pack("!B", WeatherService.FORECAST_TEMPERATURE)
            forecast_data += struct.pack("!d", forecast.get_value("Air temperature"))

            forecast_data += struct.pack("!B", WeatherService.FORECAST_WIND_SPEED)
            forecast_data += struct.pack("!d", forecast.get_value("Wind speed"))

            forecast_data += struct.pack("!B", WeatherService.FORECAST_PRECIPITATION)
            forecast_data += struct.pack(
                "!d", forecast.get_value("Precipitation amount")
            )

            forecast_data += struct.pack(
                "!B", WeatherService.FORECAST_TOTAL_CLOUD_COVER
            )
            forecast_data += struct.pack("!d", forecast.get_value("Total cloud cover"))

            data.append(forecast_data)

        return data

