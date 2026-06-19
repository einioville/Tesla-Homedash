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

from ..server.server import Server
from ..utils import protocol
from ..utils.config_parser import Config

logger = logging.getLogger("weather_service.weather_service")


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
    def __init__(self, time: datetime, data: dict, display_tz: ZoneInfo):
        '''
        Stores one hour's worth of weather measurements.
        Arguments:
            time (datetime): UTC-naive (or UTC-aware) datetime for this hour.
            data (dict): Mapping of field name → {"value": ..., "units": ...}.
            display_tz (ZoneInfo): Timezone to express the forecast hour in,
                sourced from the configured `timeZone` in config.json.  Was
                previously hardcoded to Europe/Helsinki — would break for any
                non-Helsinki timezone in config.
        '''
        # Treat incoming time as UTC and convert to the configured display tz
        self.__time = time.replace(tzinfo=ZoneInfo("UTC"))
        self.__time = self.__time.astimezone(display_tz)
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

    def get_measurement(self, key: str):
        '''Returns the ForecastMeasurement for the given field, or None if absent.'''
        return self.__data.get(key)

    def set_measurement(self, key: str, measurement) -> None:
        '''
        Adds or replaces a measurement for the given field. Used to backfill the
        current-hour observation banner with precipitation + cloud cover from the
        model forecast, since the observation station does not report them.
        Arguments:
            key (str): Field name.
            measurement (ForecastMeasurement | None): Stored as-is; ignored if None.
        '''
        if measurement is not None:
            self.__data[key] = measurement


class WeatherService:
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

    def __init__(self, server: Server, config: Config):
        '''
        Initialises the service.  The scheduler is not started here; call
        get_run_task() to start the service as an asyncio Task.
        Arguments:
            server (Server): TCP server used to broadcast forecast data.
            config (Config): Shared in-memory configuration.
        '''
        self.__loop = asyncio.get_running_loop()
        self.__server = server
        self.__zone_info = config.zone_info
        self.__scheduler = AsyncIOScheduler(timezone=self.__zone_info)
        # Observation and forecast place — configure via "weatherPlace" in config.json
        self.__place: str = config.weather_place
        # Most recent framed forecast packet, replayed verbatim to any newly
        # connecting client so its weather UI populates immediately without
        # waiting for the next 15-minute cron tick.
        self.__last_forecast: bytes | None = None

    async def run(self) -> None:
        '''
        Starts the weather service: performs an initial combined fetch (current-
        hour observation + upcoming forecast), then schedules periodic refreshes
        every 15 minutes.
        '''
        logger.info("Weather service starting: place=%s", self.__place)
        logger.info("Performing initial weather fetch")
        await self.__update_forecast()
        self.__scheduler.start()
        self.__scheduler.add_job(
            func=self.__update_forecast,
            trigger=CronTrigger(hour="*", minute="0,15,30,45", timezone=self.__zone_info),
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
        logger.debug("Weather update cycle started")
        now_local = datetime.now(self.__zone_info)

        observation = await self.__fetch_observation(now_local)
        if observation is not None:
            logger.info("Observation fetched successfully")
        forecast_hours = await self.__fetch_forecast(now_local)
        if forecast_hours:
            logger.info("Forecast fetched: %d hours", len(forecast_hours))

        # The forecast now starts at the current hour. Split off its current-hour
        # row: it backfills the banner's precipitation + cloud cover (the
        # observation station reports neither), while temperature + wind stay from
        # the real observation. The remaining rows are the future forecast cards.
        current_hour = now_local.hour
        current_forecast: ForecastHour | None = None
        future_hours: list[ForecastHour] = []
        for forecast in forecast_hours:
            if current_forecast is None and forecast.get_time() == current_hour:
                current_forecast = forecast
            else:
                future_hours.append(forecast)

        if observation is not None and current_forecast is not None:
            for key in ("Precipitation amount", "Total cloud cover"):
                observation.set_measurement(key, current_forecast.get_measurement(key))

        forecasts: list[ForecastHour] = []
        if observation is not None:
            forecasts.append(observation)
        elif current_forecast is not None:
            # No live observation — fall back to the model's current-hour row.
            forecasts.append(current_forecast)
        forecasts.extend(future_hours)

        if forecasts:
            logger.info("Broadcasting weather forecast to clients")
            stream_data = await self.__get_stream_data(forecasts)
            self.__last_forecast = protocol.frame(
                protocol.WEATHER_FORECAST, b"".join(stream_data)
            )
            await self.__server.broadcast(self.__last_forecast)

    async def stream_everything(self, client) -> None:
        '''
        Sends the most recent cached forecast to a single newly connected
        client.  No-op until the first __update_forecast() cycle has run.
        Arguments:
            client: StreamWriter for the new connection.
        '''
        if self.__last_forecast is not None:
            await self.__server.send_to(client, self.__last_forecast)

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
        except (OSError, ValueError, KeyError) as e:
            # OSError covers network/HTTP failures from fmiopendata's urllib layer;
            # ValueError/KeyError catch malformed XML and unexpected response shapes.
            logger.warning(
                "FMI observation fetch failed for place=%s: %s: %s",
                self.__place, type(e).__name__, e,
            )
            return None

        if not data or not data.data:
            return None

        def _has_value(entry) -> bool:
            '''
            Returns True when an FMI field entry holds a finite numeric value.
            fmiopendata leaves the entry dict in place but stores NaN (or None)
            for slots it has not measured, so presence of the entry alone is not
            enough — the value itself must be checked.
            Arguments:
                entry: A {"value": ..., "units": ...} mapping, or None when the
                    field is absent for this slot.
            '''
            if entry is None:
                return False
            value = entry.get("value")
            if value is None:
                return False
            try:
                return not math.isnan(float(value))
            except (TypeError, ValueError):
                return False

        # fmiopendata's multipointcoverage pads the most recent 10-minute slot(s)
        # with NaN — the coverage grid reaches the query end even before an
        # observation exists. Blindly taking max(keys) then handed the current-
        # hour banner an all-NaN slot, which get_value() turns into zeros. Walk
        # the timestamps newest→oldest and use the most recent slot that actually
        # carries a valid air-temperature reading.
        normalized: dict = {}
        for timestamp in sorted(data.data.keys(), reverse=True):
            raw_location_data = next(iter(data.data[timestamp].values()))
            candidate: dict = {}
            for obs_key, forecast_key in WeatherService._OBS_FIELD_MAP.items():
                entry = raw_location_data.get(obs_key)
                if _has_value(entry):
                    candidate[forecast_key] = entry
            # A valid temperature signals a slot with real measurements.
            if "Air temperature" in candidate:
                normalized = candidate
                break

        if not normalized:
            logger.debug(
                "FMI observation returned no usable fields for place=%s", self.__place
            )
            return None

        # ForecastHour expects a UTC-naive datetime; convert from local timezone
        current_hour_utc = current_hour_start.astimezone(timezone.utc).replace(tzinfo=None)
        return ForecastHour(current_hour_utc, normalized, self.__zone_info)

    async def __fetch_forecast(self, now_local: datetime) -> list[ForecastHour]:
        '''
        Fetches harmonie hourly forecasts starting at the CURRENT hour. The model
        retains the current hour (and several past hours), so its current-hour row
        is used to backfill the banner's precipitation + cloud cover — fields the
        observation station does not report — while the following rows are the
        future forecast cards. The dashboard shows the current hour plus the next
        five forecast hours; we request a couple of extra hours as margin. The
        frontend displays the nearest five and ignores the surplus. Returns an
        empty list on failure.
        Arguments:
            now_local (datetime): Timezone-aware current local time.
        '''
        current_hour = now_local.replace(minute=0, second=0, microsecond=0)
        # Inclusive range with margin: current_hour .. current_hour+7 == up to 8
        # points (1 current-hour backfill row + future card hours with spare).
        end_time = current_hour + timedelta(hours=7)

        start_str = current_hour.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        end_str = end_time.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

        try:
            data = await self.__loop.run_in_executor(
                None,
                lambda: download_stored_query(
                    query_id="fmi::forecast::harmonie::surface::point::multipointcoverage",
                    args=[
                        f"starttime={start_str}",
                        f"endtime={end_str}",
                        f"place={self.__place}",
                    ],
                ),
            )
        except (OSError, ValueError, KeyError) as e:
            logger.warning(
                "FMI forecast fetch failed for place=%s: %s: %s",
                self.__place, type(e).__name__, e,
            )
            return []

        if not data or not data.data:
            return []

        # Sort by timestamp so the list is strictly chronological: the frontend
        # shows the first five forecast rows as "the nearest five", which only
        # holds if the rows are time-ordered (fmiopendata is normally ordered,
        # but sorting makes the guarantee independent of its iteration order).
        return [
            ForecastHour(time, next(iter(value.values())), self.__zone_info)
            for time, value in sorted(data.data.items())
        ]

    async def __get_stream_data(self, forecasts: list) -> list[bytes]:
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
            forecast_data += struct.pack("!B", protocol.FORECAST_TIME)
            forecast_data += struct.pack("!B", forecast.get_time())

            temp = max(-128, min(127, round(forecast.get_value("Air temperature"))))
            forecast_data += struct.pack("!B", protocol.FORECAST_TEMPERATURE)
            forecast_data += struct.pack("!b", temp)

            wind = max(0, min(255, round(forecast.get_value("Wind speed"))))
            forecast_data += struct.pack("!B", protocol.FORECAST_WIND_SPEED)
            forecast_data += struct.pack("!B", wind)

            precip = max(0, min(255, round(forecast.get_value("Precipitation amount"))))
            forecast_data += struct.pack("!B", protocol.FORECAST_PRECIPITATION)
            forecast_data += struct.pack("!B", precip)

            cloud = max(0, min(255, round(forecast.get_value("Total cloud cover"))))
            forecast_data += struct.pack("!B", protocol.FORECAST_TOTAL_CLOUD_COVER)
            forecast_data += struct.pack("!B", cloud)

            data.append(forecast_data)

        return data
