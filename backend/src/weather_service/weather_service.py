from __future__ import annotations

import asyncio
import logging
import math
import struct
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fmiopendata.wfs import download_stored_query

from ..tesla_service.tcp_server import TeslaDataServer
from ..utils.config_parser import ConfigUtils

logger = logging.getLogger(__name__)


class ForecastMeasurement:
    def __init__(self, name, value, unit: None):
        self.__name = name
        self.__value = value
        self.__unit = unit

    def get_name(self):
        return self.__name

    def get_value(self):
        '''
        Returns the float value of this measurement.
        Returns 0.0 for missing (None) or non-finite (NaN) values so the
        binary packer always receives a valid double.
        '''
        if self.__value is None:
            return 0.0
        try:
            v = float(self.__value)
            # FMI occasionally encodes missing data as NaN
            return v if not math.isnan(v) else 0.0
        except (TypeError, ValueError):
            return 0.0

    def get_unit(self):
        return self.__unit


class ForecastHour:
    def __init__(self, time: datetime, data: dict):
        '''
        Stores one hour's worth of weather measurements.
        Arguments:
            time (datetime): UTC-naive (or UTC-aware) datetime for this hour.
            data (dict): Mapping of field name → {"value": ..., "units": ...}.
        '''
        # Treat incoming time as UTC and convert to the display timezone
        self.__time = time.replace(tzinfo=ZoneInfo("UTC"))
        self.__time = self.__time.astimezone(ZoneInfo("Europe/Helsinki"))
        self.__hours = self.__time.hour
        self.__time = self.__time.strftime("%H")

        self.__data = {}
        for name, value in data.items():
            self.__data[name] = ForecastMeasurement(
                name=name, value=value["value"], unit=value["units"]
            )

    def get_value(self, key: str, default: float = 0.0) -> float:
        '''
        Returns the float value for the given field, or default if absent.
        Arguments:
            key (str): Field name (e.g. "Air temperature").
            default (float): Fallback when the field is missing in this hour.
        '''
        if key not in self.__data:
            return default
        return self.__data[key].get_value()

    def get_time(self) -> int:
        return self.__hours


class WeatherService:
    FORECAST_TIME = 0x35
    FORECAST_TEMPERATURE = 0x31
    FORECAST_WIND_SPEED = 0x32
    FORECAST_PRECIPITATION = 0x33
    FORECAST_TOTAL_CLOUD_COVER = 0x34

    # Maps FMI observation field names to the forecast-compatible names used
    # throughout the rest of the service.  fmiopendata normally uses the same
    # human-readable labels for both query types, but having an explicit map
    # makes any future divergence easy to fix in one place.
    _OBS_FIELD_MAP = {
        "Air temperature": "Air temperature",
        "Wind speed": "Wind speed",
        "Precipitation amount": "Precipitation amount",
        "Total cloud cover": "Total cloud cover",
    }

    def __init__(self, server: TeslaDataServer):
        '''
        Initialises the service.  The scheduler is not started here; call
        get_run_task() to start the service as an asyncio Task.
        Arguments:
            server (TeslaDataServer): TCP server used to broadcast forecast data.
        '''
        self.__loop = asyncio.get_running_loop()
        self.__server = server
        self.__scheduler = AsyncIOScheduler()
        config = ConfigUtils.get_config()
        self.__timezone: str = config["timeZone"]
        # Observation and forecast place — configure via "weatherPlace" in config.json
        self.__place: str = config["weatherPlace"]

    async def run(self) -> None:
        '''
        Starts the weather service: performs an initial combined fetch (current-
        hour observation + upcoming forecast), then schedules periodic refreshes
        every 15 minutes.
        '''
        await self.__update_forecast()
        self.__scheduler.start()
        self.__scheduler.add_job(
            func=self.__update_forecast,
            trigger=CronTrigger(hour="*", minute="0,15,30,45", timezone=ZoneInfo(self.__timezone)),
        )

    def get_run_task(self) -> asyncio.Task:
        '''
        Returns an asyncio Task that starts the weather service.
        '''
        return asyncio.create_task(self.run())

    async def __update_forecast(self) -> None:
        '''
        Fetches the current-hour FMI observation and the following hours'
        harmonie forecast, then broadcasts the merged result to all clients.
        Current hour comes from real measurements; later hours from model data.
        '''
        tz = ZoneInfo(self.__timezone)
        now_local = datetime.now(tz)

        observation = await self.__fetch_observation(now_local)
        forecast_hours = await self.__fetch_forecast(now_local)

        forecasts: list[ForecastHour] = []
        if observation is not None:
            forecasts.append(observation)
        forecasts.extend(forecast_hours)

        if forecasts:
            await self.__server.update_forecast(await self.__get_stream_data(forecasts))

    async def __fetch_observation(self, now_local: datetime) -> ForecastHour | None:
        '''
        Fetches the most recent FMI surface observation within the current hour
        and returns it as a ForecastHour.  Returns None when the query fails or
        produces no usable data.
        Arguments:
            now_local (datetime): Timezone-aware current local time.
        '''
        current_hour_start = now_local.replace(minute=0, second=0, microsecond=0)
        # Request the full current-hour window; the API only returns data that
        # already exists, so requesting up to the next hour is safe.
        end_time = current_hour_start + timedelta(hours=1)

        start_str = current_hour_start.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        end_str = end_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

        try:
            # NOTE: confirmed stored query for 10-minute surface weather
            # observations; returns air temp, wind speed, precipitation, cloud cover.
            data = await self.__loop.run_in_executor(
                None,
                lambda: download_stored_query(
                    query_id="fmi::observations::weather::multipointcoverage",
                    args=[
                        f"starttime={start_str}",
                        f"endtime={end_str}",
                        f"place={self.__place}",
                    ],
                ),
            )
        except Exception:
            logger.debug("FMI observation fetch failed for place=%s", self.__place)
            return None

        if not data or not data.data:
            return None

        # Use the latest timestamp available in the response
        latest_time = max(data.data.keys())
        raw_location_data = next(iter(data.data[latest_time].values()))

        # Normalize field names and drop entries that are entirely absent
        normalized: dict = {}
        for obs_key, forecast_key in WeatherService._OBS_FIELD_MAP.items():
            entry = raw_location_data.get(obs_key)
            if entry is not None:
                normalized[forecast_key] = entry

        if not normalized:
            logger.debug(
                "FMI observation returned no usable fields for place=%s", self.__place
            )
            return None

        # ForecastHour expects a UTC-naive datetime; convert from local timezone
        current_hour_utc = current_hour_start.astimezone(timezone.utc).replace(tzinfo=None)
        return ForecastHour(current_hour_utc, normalized)

    async def __fetch_forecast(self, now_local: datetime) -> list[ForecastHour]:
        '''
        Fetches harmonie hourly forecasts for the 6 hours starting at the next
        full hour, excluding the current hour (covered by observation).
        Returns an empty list on failure.
        Arguments:
            now_local (datetime): Timezone-aware current local time.
        '''
        next_hour = (now_local + timedelta(hours=1)).replace(
            minute=0, second=0, microsecond=0
        )
        end_time = next_hour + timedelta(hours=5)

        next_hour_str = next_hour.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        end_str = end_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

        try:
            data = await self.__loop.run_in_executor(
                None,
                lambda: download_stored_query(
                    query_id="fmi::forecast::harmonie::surface::point::multipointcoverage",
                    args=[
                        f"starttime={next_hour_str}",
                        f"endtime={end_str}",
                        f"place={self.__place}",
                    ],
                ),
            )
        except Exception:
            logger.debug("FMI forecast fetch failed for place=%s", self.__place)
            return []

        if not data or not data.data:
            return []

        return [
            ForecastHour(time, next(iter(value.values())))
            for time, value in data.data.items()
        ]

    async def __get_stream_data(self, forecasts: list) -> bytes:
        '''
        Serialises a list of ForecastHour objects into the binary wire format
        expected by the frontend weather handler.
        Arguments:
            forecasts (list[ForecastHour]): Ordered list starting with the
                current-hour observation followed by future forecast hours.
        '''
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
