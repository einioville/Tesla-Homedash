import asyncio
import logging
from ..utils import protocol
from ..utils.config_parser import ConfigUtils
from .vehicle_data_property import VehicleDataProperty, CalculatedVehicleDataProperty
from ..influxdb_service.influxdb_handler import InfluxDBHandler
from ..server.server import Server
from json import dumps
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import aiohttp
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

logger = logging.getLogger("tesla_service.vehicle")


class Vehicle:
    def __init__(
        self,
        vin: str,
        influx_db_handler: InfluxDBHandler,
        server: Server,
        access_token: str,
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
        # HVAC rate-limit state. Reset is armed once per cooldown window: when
        # any successful command increments the counter and no reset is
        # currently scheduled, schedule one and set the flag.  __reset_requests
        # clears the flag after firing.  This is order-independent and survives
        # any interleaving — pre-fix, the equality check missed when the
        # counter stepped past 4 and the limiter latched permanently.
        self.__requests_used = 0
        self.__reset_scheduled = False
        self.__rate_limit_lock = asyncio.Lock()
        self.__access_token = access_token

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
        logger.debug("Loaded %d vehicle data properties", len(self.__data))

    async def init_async_dependent(self) -> None:
        timezone_name = ConfigUtils.get_config()["timeZone"]
        # Pin the scheduler to the configured timezone so naive run_dates we
        # build with `datetime.now(self.__timezone)` line up with how the
        # scheduler interprets them — and so the codebase is no longer
        # implicitly dependent on the host OS timezone.
        self.__timezone = ZoneInfo(timezone_name)
        self.__scheduler = AsyncIOScheduler(timezone=self.__timezone)
        self.__scheduler.start()
        logger.info(
            "Vehicle async dependencies initialized, scheduler started (tz=%s)",
            timezone_name,
        )
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
            await self.__data[data_property_id].init_schedulers(
                self.__scheduler,
                timezone=timezone_name,
            )
            await self.__data[data_property_id].update_calculate_value()

        # Midnight snapshot of every logged property. Without this, a new
        # calendar day (or month) can start with no InfluxDB record inside the
        # first-of-period window, which would make CalculatedVehicleDataProperty
        # reset queries return None and force a fallback to the live value.
        self.__scheduler.add_job(
            func=self.__snapshot_logged_properties,
            trigger=CronTrigger(hour=0, minute=0, timezone=self.__timezone),
        )
        logger.info("Scheduled midnight snapshot for logged data properties")

    async def __snapshot_logged_properties(self) -> None:
        """
        Writes the current value of every logged data property to InfluxDB
        with the current timestamp.  Runs daily at 00:00 in the configured
        timezone so the first-of-day / first-of-month baseline queries used
        by CalculatedVehicleDataProperty always find a record.
        """
        # Stamp explicitly in UTC: InfluxDB stores absolute UTC moments, and
        # the configured `timeZone` is only used at query time / for cron
        # boundaries — never to shift the stored value.
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        points = []
        for data_property in self.__data.values():
            if not await data_property.get_logging():
                continue
            point = await data_property.get_snapshot_point(now_ms)
            if point is not None:
                points.append(point)

        if not points:
            logger.debug("Midnight snapshot: no logged properties with values to write")
            return

        try:
            await self.__influx_handler.write_tesla_data(points)
            logger.info("Midnight snapshot: wrote %d points", len(points))
        except Exception as e:
            logger.error("Midnight snapshot write failed: %s", e)

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

                logger.debug("Telemetry update: %s = %s", data_property_id, value)

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

            # Telemetry logging is a side concern — a failing InfluxDB write
            # must not prevent the frontend broadcast below.
            try:
                await self.__influx_handler.write_tesla_data(log_points)
            except Exception as e:
                logger.error("Failed to write telemetry to InfluxDB: %s", e)

            stream_data = await asyncio.gather(*stream_tasks)

            framed = b"".join(
                protocol.frame(protocol.MSG_STREAM, entry)
                for entry in stream_data
                if entry is not None
            )
            if framed:
                await self.__server.broadcast(framed)

    async def stream_data_property(self, data_property: VehicleDataProperty) -> None:
        stream_data = await data_property.get_stream_data()
        if stream_data is not None:
            await self.__server.broadcast(
                protocol.frame(protocol.MSG_STREAM, stream_data)
            )

    async def stream_everything(self, client) -> None:
        """
        Sends the full current state of every telemetry property to a
        single freshly connected client.  Properties without a value yet
        return None from get_stream_data() and are skipped automatically.
        Arguments:
            client: StreamWriter for the new connection.
        """
        async with self.__async_lock:
            properties = list(self.__data.values())
        stream_data = await asyncio.gather(*(p.get_stream_data() for p in properties))
        framed = b"".join(
            protocol.frame(protocol.MSG_STREAM, entry)
            for entry in stream_data
            if entry is not None
        )
        if framed:
            await self.__server.send_to(client, framed)

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
        time_start: str,
        time_end: str,
    ):
        return await self.__influx_handler.read_tesla_data_property(
            data_property_id, time_start, time_end
        )

    async def __rate_limit_reserve(self) -> bool:
        '''
        Atomically checks the rate-limit window and, if a slot is available,
        reserves it (increments the counter and arms the cooldown reset job
        if it isn't already armed).  Returns True on reserve, False if the
        window is full.  The caller MUST refund the slot via
        __rate_limit_refund() if the subsequent API call does not succeed,
        otherwise a transient network error would burn rate-limit budget.

        The flag-guarded scheduling makes the reset order-independent:
        regardless of which command (switch / temperature) opens the window,
        exactly one reset is scheduled per cooldown.
        '''
        async with self.__rate_limit_lock:
            if self.__requests_used > 4:
                logger.warning(
                    "Climate control rate limited: %d requests used",
                    self.__requests_used,
                )
                return False
            self.__requests_used += 1
            if not self.__reset_scheduled:
                self.__scheduler.add_job(
                    func=self.__reset_requests,
                    trigger="date",
                    run_date=datetime.now(self.__timezone) + timedelta(minutes=5),
                )
                self.__reset_scheduled = True
                logger.debug(
                    "Rate-limit cooldown armed: 5 minutes from %s",
                    datetime.now(self.__timezone).isoformat(),
                )
            return True

    async def __rate_limit_refund(self) -> None:
        '''
        Refunds a slot reserved by __rate_limit_reserve when the API call
        does not succeed.  The reset job remains armed; it will fire and
        clear the counter regardless.
        '''
        async with self.__rate_limit_lock:
            if self.__requests_used > 0:
                self.__requests_used -= 1

    async def __reset_requests(self) -> None:
        async with self.__rate_limit_lock:
            self.__requests_used = 0
            self.__reset_scheduled = False
        logger.debug("Rate-limit counter reset")

    async def switch_climate_state(self) -> None:
        # Pre-flight check: figure out target operation before reserving a
        # rate-limit slot, so an HVAC field in transient/unknown state does
        # not burn a slot it never spends.
        data_property = await self.get_data_property("HvacPower")
        value = await data_property.get_value()
        logger.debug("HVAC state value: %s", value)

        if value == "HvacPowerStateOn":
            operation = "auto_conditioning_stop"
            target_state = "HvacPowerStateOff"
        elif value == "HvacPowerStateOff":
            operation = "auto_conditioning_start"
            target_state = "HvacPowerStateOn"
        else:
            return

        if not await self.__rate_limit_reserve():
            return

        # Engage the lock BEFORE issuing the REST command so a stale
        # Teslemetry frame (common on vehicle wake-up) cannot snap the UI
        # back to the previous state while we wait for confirmation.
        await data_property.lock_value_until(
            "HvacPowerStatePending", target_state, timeout_seconds=300
        )
        await self.stream_data_property(data_property)

        logger.info("Climate switch requested: %s", operation)
        success = False
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url=f"https://api.teslemetry.com/api/1/vehicles/{self.__vin}/command/{operation}",
                headers={"Authorization": f"Bearer {self.__access_token}"},
            ) as response:
                if response.status == 200:
                    success = True
                else:
                    logger.error("Climate API call failed: status %d", response.status)

        if not success:
            await self.__rate_limit_refund()

        if self.__temperature_updated:
            await self.update_temperature()

    async def update_temperature(self) -> None:
        if not await self.__rate_limit_reserve():
            return

        data_property = await self.get_data_property("HvacLeftTemperatureRequest")
        value = await data_property.get_value()
        logger.info("Temperature update requested: driver=%.1f°C", float(value))

        success = False
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url=f"https://api.teslemetry.com/api/1/vehicles/{self.__vin}/command/set_temps",
                headers={"Authorization": f"Bearer {self.__access_token}"},
                json={"driver_temp": float(value), "passenger_temp": float(value)},
            ) as response:
                if response.status == 200:
                    success = True
                else:
                    logger.error(
                        "Temperature API call failed: status %d", response.status
                    )

        if not success:
            await self.__rate_limit_refund()

        self.__temperature_updated = False

    async def minus_temp(self) -> None:
        left = await self.get_data_property("HvacLeftTemperatureRequest")
        right = await self.get_data_property("HvacRightTemperatureRequest")

        value_left = await left.get_value()
        value_left -= 0.5

        if value_left < 15.0:
            logger.warning("Temperature decrease blocked: minimum 15.0°C reached")
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
            logger.warning("Temperature increase blocked: maximum 28.0°C reached")
            return

        await left.update(value_left, None)
        await right.update(value_left, None)
        await self.stream_data_property(left)
        await self.stream_data_property(right)

        self.__temperature_updated = True
