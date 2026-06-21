import asyncio
import inspect
import logging
from ..utils import protocol
from ..utils.config_parser import Config
from .vehicle_data_property import VehicleDataProperty, CalculatedVehicleDataProperty
from ..influxdb_service.influxdb_handler import InfluxDBHandler
from ..server.server import Server
from json import dumps
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import aiohttp
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("tesla_service.vehicle")


class Vehicle:
    def __init__(
        self,
        vin: str,
        influx_db_handler: InfluxDBHandler,
        server: Server,
        access_token: str,
        config: Config,
    ):
        self.__vin = vin
        self.__config = config
        self.__timezone = config.zone_info
        self.__data = {}
        self.__calculated_data_ids = {}
        self.__async_lock = asyncio.Lock()
        self.__influx_handler = influx_db_handler
        self.__server = server
        self.__scheduler = None
        # Combined value-callbacks: handle -> {criteria, callback, property_handles}.
        # See add_callback.
        self.__condition_callbacks: dict[int, dict] = {}
        self.__condition_next_handle: int = 0
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

        # Reset volatile fields to their sleep defaults whenever the vehicle goes
        # offline. Wired through the general value-callback mechanism rather than
        # an inline hook in __update: VehicleOnline transitioning to False trips
        # __on_sleep. Guarded so a config without VehicleOnline still starts.
        if "VehicleOnline" in self.__data:
            self.add_callback({"VehicleOnline": False}, self.__on_sleep)

    def __load_data_properties(self) -> None:
        for data_property_id, prop_cfg in self.__config.tesla_data.items():
            self.__data[data_property_id] = VehicleDataProperty(
                data_id=data_property_id,
                stream_id=prop_cfg["stream_id"],
                category=prop_cfg["category"],
                vehicle=self,
                unit=prop_cfg["unit"],
                formula=prop_cfg["formula"],
                log=prop_cfg["log"],
                sleep_default=prop_cfg.get("sleep_default"),
            )
        logger.debug("Loaded %d vehicle data properties", len(self.__data))

    async def init_async_dependent(self) -> None:
        # Scheduler is pinned to the configured timezone so naive run_dates
        # we build with `datetime.now(self.__timezone)` line up with how the
        # scheduler interprets them.
        self.__scheduler = AsyncIOScheduler(timezone=self.__timezone)
        self.__scheduler.start()
        logger.info(
            "Vehicle async dependencies initialized, scheduler started (tz=%s)",
            self.__config.timezone,
        )
        timezone_name = self.__config.timezone
        calculated_data_property_config = self.__config.calculated_tesla_data
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
        # Some stream frames (connectivity/keepalive) arrive without a "vin"
        # key; .get avoids a KeyError that would crash this task — the
        # exception is otherwise swallowed as an un-retrieved task result.
        if data.get("vin") != self.__vin:
            if "vin" not in data:
                logger.debug(
                    "Stream frame without vin ignored: keys=%s", list(data.keys())
                )
            return

        if "timestamp" not in data:
            return
        timestamp = data["timestamp"]

        if "data" not in data:
            if "state" in data:
                # Raw state is one of online / offline / asleep (teslemetry
                # State enum). In practice the car reports a sleeping vehicle as
                # "offline" and never emits "asleep". Updating VehicleOnline to
                # False trips the sleep-default reset via the value-callback
                # registered in __init__ (see __on_sleep).
                state = data["state"]
                logger.info("Vehicle state event: state=%s", state)
                online = state == "online"
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

    async def __apply_sleep_defaults(self, timestamp) -> None:
        '''
        Forces every property that defines a sleep_default to its asleep value
        (clearing any pending value-lock) and broadcasts the ones that actually
        changed.  Invoked when a state event reports the vehicle is no longer
        online: the Teslemetry stream stops sending on sleep, so without this
        volatile fields (speed, gear, HVAC, charging power) stay frozen at their
        last live reading.  Safe to call on every offline event — properties
        already at their default report no change and are not re-broadcast, and
        the periodic offline events also self-heal a reset that lost a race with
        a replayed telemetry frame on (re)connect.  Logged fields are NOT
        written to InfluxDB here by design — the reset is display-only and must
        not fabricate history points.
        Arguments:
            timestamp: Epoch milliseconds of the state (sleep) event.
        '''
        async with self.__async_lock:
            properties = list(self.__data.values())
        changed = [p for p in properties if await p.apply_sleep_default(timestamp)]
        if not changed:
            return
        stream_data = await asyncio.gather(*(p.get_stream_data() for p in changed))
        framed = b"".join(
            protocol.frame(protocol.MSG_STREAM, entry)
            for entry in stream_data
            if entry is not None
        )
        if framed:
            await self.__server.broadcast(framed)
        logger.info("Applied sleep defaults to %d field(s) on sleep", len(changed))

    def add_callback(self, criteria: dict, callback) -> int:
        '''
        Registers a callback fired when EVERY property in `criteria` simultaneously
        holds its target value. `criteria` maps data-property id -> target value;
        use `VehicleDataProperty.ANY` as a target to mean "this property has any
        value" (i.e. re-evaluate whenever it changes).
        Built on the per-property edge-triggered callbacks: the combined callback
        fires whenever a member property reaches its target and, at that instant,
        all members are at their targets. Synchronous so it can be wired during
        construction. The callback runs as an independent task and is invoked as
        `callback(matches)`, where `matches` is a list of `(data_id, value, when)`
        tuples (one per criterion); it may be a coroutine function (it is awaited).
        Arguments:
            criteria (dict): {data_property_id: target_value, ...}.
            callback: Callable(list) -> None | awaitable.
        Returns:
            int: A handle to pass to remove_callback.
        '''
        for property_id in criteria:
            if property_id not in self.__data:
                raise ValueError(f"Unknown data property in criteria: {property_id}")
        handle = self.__condition_next_handle
        self.__condition_next_handle += 1
        property_handles = {}
        for property_id, target_value in criteria.items():
            property_handles[property_id] = self.__data[property_id].add_callback(
                target_value,
                lambda data_id, value, when, h=handle: self.__on_condition_member(h),
            )
        self.__condition_callbacks[handle] = {
            "criteria": criteria,
            "callback": callback,
            "property_handles": property_handles,
        }
        return handle

    def remove_callback(self, handle: int) -> None:
        '''
        Unregisters a combined callback added with add_callback, including the
        per-property callbacks it created. No-op if the handle is unknown.
        Arguments:
            handle (int): The value returned by add_callback.
        '''
        condition = self.__condition_callbacks.pop(handle, None)
        if condition is None:
            return
        for property_id, property_handle in condition["property_handles"].items():
            self.__data[property_id].remove_callback(property_handle)

    async def __on_condition_member(self, handle: int) -> None:
        '''
        Re-evaluates a combined-callback condition after one of its member
        properties reached its target, firing the user callback only when ALL
        members currently hold their target values.
        Arguments:
            handle (int): The condition whose member property just changed.
        '''
        condition = self.__condition_callbacks.get(handle)
        if condition is None:
            return
        matches = []
        for property_id, target_value in condition["criteria"].items():
            info = await self.__data[property_id].get_as_dict()
            if (
                target_value is not VehicleDataProperty.ANY
                and info["value"] != target_value
            ):
                return  # Not all members satisfied — do not fire.
            ts = info["timestamp"]
            when = (
                datetime.fromtimestamp(ts / 1000, tz=self.__timezone)
                if ts is not None
                else None
            )
            matches.append((property_id, info["value"], when))
        # A failing callback must never break the telemetry update path.
        try:
            result = condition["callback"](matches)
            if inspect.isawaitable(result):
                await result
        except Exception as e:
            logger.error(
                "Vehicle callback (handle=%s) raised: %s: %s",
                handle, type(e).__name__, e,
            )

    async def __on_sleep(self, matches) -> None:
        '''
        Sleep-default callback: fired when VehicleOnline becomes False. Derives
        the sleep timestamp from the match and resets every field that defines a
        sleep_default.
        Arguments:
            matches (list): [(data_id, value, when)] for the criteria — here just
                the VehicleOnline entry.
        '''
        when = matches[0][2] if matches else None
        if when is not None:
            timestamp = int(when.timestamp() * 1000)
        else:
            timestamp = int(datetime.now(timezone.utc).timestamp() * 1000)
        await self.__apply_sleep_defaults(timestamp)

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

    @property
    def zone_info(self):
        '''Configured timezone as a ZoneInfo, used to build local datetimes.'''
        return self.__timezone

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

    async def get_graphable_properties(self) -> list:
        '''
        Returns the metadata for every property that can be drawn on the History
        graph: those that are logged to InfluxDB and whose value is numeric
        (value_type "value_float").  Enums, bools, strings and the Location dict
        are excluded, as are the calculated properties (they are not logged, so
        they have no stored history).  Sorted by category then id for a stable
        dropdown order.
        Note: value_type is inferred lazily on a property's first telemetry
        update, so a logged numeric field that has not streamed since startup is
        omitted until it next updates — the frontend re-requests this list each
        time the view is opened, so it fills in as the session runs.
        Returns:
            list[dict]: [{"id", "unit", "category"}, ...].
        '''
        async with self.__async_lock:
            properties = list(self.__data.values())
        result = []
        for data_property in properties:
            if not await data_property.get_logging():
                continue
            if await data_property.get_value_type() != "value_float":
                continue
            result.append({
                "id": await data_property.get_id(),
                "unit": await data_property.get_unit(),
                "category": await data_property.get_category(),
            })
        result.sort(key=lambda entry: (entry["category"] or "", entry["id"]))
        return result

    async def get_data_history(
        self,
        data_property_id: str,
        time_start: str,
        time_end: str,
        aggregate_window: str | None = None,
    ):
        return await self.__influx_handler.read_tesla_data_property(
            data_property_id, time_start, time_end, aggregate_window
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

        previous_state = value

        if not await self.__rate_limit_reserve():
            return

        # Show a "Pending" placeholder while the command is in flight. The lock
        # also drops stale Teslemetry frames (common on vehicle wake-up) that
        # would otherwise snap the UI back to the previous state.
        await data_property.lock_value_until(
            "HvacPowerStatePending", target_state, timeout_seconds=300
        )
        await self.stream_data_property(data_property)

        logger.info("Climate switch requested: %s", operation)
        success = False
        # A network error or timeout must NOT escape: it would skip both branches
        # below and strand the property on "Pending" (+ leak a rate-limit slot).
        # The explicit timeout also resolves a hung request well before the 300s
        # lock timeout. Any failure leaves success False → the failure branch runs.
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
                async with session.post(
                    url=f"https://api.teslemetry.com/api/1/vehicles/{self.__vin}/command/{operation}",
                    headers={"Authorization": f"Bearer {self.__access_token}"},
                ) as response:
                    # Teslemetry proxies the Tesla Fleet API: a 200 carries
                    # {"response": {"result": <bool>, "reason": <str>}} and `result`
                    # is the real success signal — a 200 with result=false is a
                    # rejection. Parse defensively for both wrapped/unwrapped shapes.
                    if response.status == 200:
                        try:
                            body = await response.json()
                            inner = body.get("response", body) if isinstance(body, dict) else {}
                            if isinstance(inner, dict):
                                success = bool(inner.get("result", False))
                                if not success:
                                    logger.error(
                                        "Climate command rejected by vehicle: %s",
                                        inner.get("reason", "unknown"),
                                    )
                        except (aiohttp.ContentTypeError, ValueError) as e:
                            logger.error("Climate command response parse failed: %s", e)
                    else:
                        logger.error("Climate API call failed: status %d", response.status)
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error("Climate API call errored: %s: %s", type(e).__name__, e)

        if success:
            # Command accepted — optimistically show the target state now instead
            # of waiting for telemetry to confirm (which may lag). Keep the lock so
            # stale frames are still dropped until a confirming frame (== target)
            # arrives or the timeout lifts it.
            await data_property.lock_value_until(
                target_state, target_state, timeout_seconds=300
            )
            await self.stream_data_property(data_property)
            logger.info("Climate switch accepted: now %s", target_state)
        else:
            # Abort the placeholder, restore the previous state and refund the slot.
            await data_property.clear_value_lock(previous_state)
            await self.stream_data_property(data_property)
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
        # As with switch_climate_state, a network error/timeout must not escape —
        # it would skip the refund below and strand __temperature_updated set.
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=30)) as session:
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
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.error("Temperature API call errored: %s: %s", type(e).__name__, e)

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
