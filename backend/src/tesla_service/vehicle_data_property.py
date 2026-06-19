import asyncio
import inspect
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
    # Sentinel target for add_callback: a callback registered with ANY fires on
    # every value CHANGE, regardless of the new value (rather than only when the
    # value reaches one specific target).
    ANY = object()

    def __init__(
        self,
        data_id: str,
        stream_id: int,
        category: str,
        vehicle,
        unit: str = None,
        formula: str = None,
        log: bool = False,
        sleep_default=None,
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
        # Value this field reverts to when the vehicle goes to sleep (the stream
        # then goes silent, freezing the live value). None = field is left at its
        # last reading. The default is a FINAL value — the input formula is not
        # re-applied to it. See apply_sleep_default.
        self.__sleep_default = sleep_default
        self._async_lock = asyncio.Lock()
        self._vehicle = vehicle
        self.__value_type = None
        self.__locked_target = None
        self.__lock_timeout_task: asyncio.Task | None = None
        self.__lock_generation: int = 0
        # Value-callbacks: handle -> (target_value, callback). Fired when the
        # property's value transitions INTO target_value. See add_callback.
        self.__callbacks: dict[int, tuple] = {}
        self.__callback_next_handle: int = 0

    @staticmethod
    def __infer_value_type(value) -> str | None:
        if isinstance(value, bool):
            return "value_bool"
        if isinstance(value, int) or isinstance(value, float):
            return "value_float"
        if isinstance(value, str):
            return "value_string"
        if isinstance(value, dict):
            return "value_dict"
        return None

    async def update(self, value, timestamp) -> None:
        if value is None:
            return
        if self.__value_type is None:
            self.__value_type = self.__infer_value_type(value)
        async with self._async_lock:
            if self.__formula is not None:
                new_value = float(
                    self.__sympy_expr.subs(self.__sympy_x, value).evalf()
                )
            elif self.__value_type == "value_float":
                new_value = float(value)
            else:
                new_value = value

            if self.__locked_target is not None:
                if new_value != self.__locked_target:
                    # Lock active and incoming value isn't the awaited target —
                    # drop silently to preserve the placeholder (e.g. stale
                    # Teslemetry frame for HvacPower while waiting for the
                    # post-toggle confirmation).
                    logger.debug(
                        "Update dropped while locked: id=%s incoming=%s target=%s",
                        self.__id, new_value, self.__locked_target,
                    )
                    return
                # Target arrived — release lock and fall through to commit.
                if (
                    self.__lock_timeout_task is not None
                    and not self.__lock_timeout_task.done()
                ):
                    self.__lock_timeout_task.cancel()
                self.__lock_timeout_task = None
                self.__locked_target = None
                self.__lock_generation += 1

            previous_value = self._value
            self._value = new_value
            if timestamp is not None:
                self.__timestamp = timestamp
            logger.debug("Property updated: %s = %s", self.__id, self._value)

            # Edge-triggered callbacks: a value transitioning INTO a registered
            # target schedules its callbacks. They run as independent tasks
            # (never inline) so a callback can neither block the telemetry path
            # nor deadlock by re-entering a lock held further up the call stack.
            if self.__callbacks and new_value != previous_value:
                for target_value, callback in list(self.__callbacks.values()):
                    if target_value is VehicleDataProperty.ANY or new_value == target_value:
                        asyncio.create_task(
                            self.__fire_callback(callback, new_value, self.__timestamp)
                        )

    async def lock_value_until(
        self,
        placeholder_value,
        target_value,
        timeout_seconds: int = 60,
    ) -> None:
        '''
        Atomically sets the property's value to `placeholder_value` and engages
        an update-lock that drops subsequent update() calls whose post-formula
        value is not equal to `target_value`.  When a matching update arrives
        the lock releases and the update is applied normally.  If
        `timeout_seconds` elapses with no match, the lock auto-cancels.  The
        caller is responsible for streaming the placeholder to clients.
        Arguments:
            placeholder_value: The value to display while waiting for confirmation
                (e.g. "HvacPowerStatePending").
            target_value: The value that releases the lock when seen by update().
            timeout_seconds (int): Auto-cancel the lock after this many seconds.
        '''
        async with self._async_lock:
            # Re-engagement: cancel any prior timeout so the latest intent wins.
            if (
                self.__lock_timeout_task is not None
                and not self.__lock_timeout_task.done()
            ):
                self.__lock_timeout_task.cancel()
            self.__lock_generation += 1
            gen = self.__lock_generation
            self._value = placeholder_value
            if self.__value_type is None:
                self.__value_type = self.__infer_value_type(placeholder_value)
            self.__locked_target = target_value
            self.__lock_timeout_task = asyncio.create_task(
                self.__lock_timeout_handler(gen, timeout_seconds)
            )
        logger.debug(
            "Value lock engaged: id=%s placeholder=%s target=%s timeout=%ds",
            self.__id, placeholder_value, target_value, timeout_seconds,
        )

    async def __lock_timeout_handler(self, generation: int, seconds: int) -> None:
        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            return
        expired = False
        async with self._async_lock:
            # Generation guard: a newer lock may own the state already.
            if (
                self.__lock_generation == generation
                and self.__locked_target is not None
            ):
                logger.warning(
                    "Lock expired without target arriving: id=%s target=%s",
                    self.__id, self.__locked_target,
                )
                self.__locked_target = None
                self.__lock_timeout_task = None
                expired = True
        if expired:
            # Re-stream the committed value once the lock lifts. Without this a
            # client pinned to the placeholder (e.g. an HVAC button showing
            # "Pending") would stay there until the next telemetry frame for this
            # field — which may not arrive soon — so it must be pushed explicitly.
            await self._vehicle.stream_data_property(self)

    async def clear_value_lock(self, value=None) -> None:
        '''
        Cancels any active value lock so telemetry updates flow normally again,
        optionally committing `value` first. Used to abort a placeholder when the
        command it was waiting on fails. The caller is responsible for streaming.
        Arguments:
            value: Value to commit before clearing the lock, or None to leave the
                current value untouched.
        '''
        async with self._async_lock:
            if (
                self.__lock_timeout_task is not None
                and not self.__lock_timeout_task.done()
            ):
                self.__lock_timeout_task.cancel()
            self.__lock_timeout_task = None
            self.__locked_target = None
            self.__lock_generation += 1
            if value is not None:
                self._value = value

    async def apply_sleep_default(self, timestamp) -> bool:
        '''
        Forces the property to its configured sleep_default, stamped with the
        given timestamp, bypassing the input formula (the default is already a
        final value) and clearing any active value-lock — no confirming
        telemetry can arrive while the vehicle is asleep, so a pending
        placeholder (e.g. HvacPower "Pending") must not be allowed to survive.
        Returns True only when the stored value actually changed, so the caller
        can skip re-broadcasting fields that are already at their default.
        Arguments:
            timestamp: Epoch milliseconds to stamp the reset with (the time the
                vehicle went to sleep — i.e. the state event timestamp).
        '''
        if self.__sleep_default is None:
            return False
        async with self._async_lock:
            # Drop any in-flight value-lock (e.g. an HvacPower toggle still
            # showing "Pending"): it can never be confirmed while asleep.
            if (
                self.__lock_timeout_task is not None
                and not self.__lock_timeout_task.done()
            ):
                self.__lock_timeout_task.cancel()
            self.__lock_timeout_task = None
            self.__locked_target = None
            self.__lock_generation += 1

            if self.__value_type is None:
                self.__value_type = self.__infer_value_type(self.__sleep_default)

            changed = self._value != self.__sleep_default
            self._value = self.__sleep_default
            if changed:
                self.__timestamp = timestamp
        if changed:
            logger.debug("Sleep default applied: id=%s value=%s", self.__id, self.__sleep_default)
        return changed

    def add_callback(self, target_value, callback) -> int:
        '''
        Registers a callback fired when this property's value transitions INTO
        `target_value` (edge-triggered — it does not re-fire on later updates
        that keep the value at the target). Pass `VehicleDataProperty.ANY` as
        `target_value` to fire on every value CHANGE instead of one specific
        value. Multiple callbacks are allowed.
        Synchronous so it can be wired during construction. The callback runs as
        an independent task and is invoked as `callback(data_id, value, when)`,
        where `when` is a timezone-aware datetime of the value's timestamp (or
        None if unknown); it may be a coroutine function (it is awaited).
        Arguments:
            target_value: The value that triggers the callback when reached.
            callback: Callable(data_id, value, when) -> None | awaitable.
        Returns:
            int: A handle to pass to remove_callback.
        '''
        handle = self.__callback_next_handle
        self.__callback_next_handle += 1
        self.__callbacks[handle] = (target_value, callback)
        return handle

    def remove_callback(self, handle: int) -> None:
        '''
        Unregisters a callback previously added with add_callback. No-op if the
        handle is unknown.
        Arguments:
            handle (int): The value returned by add_callback.
        '''
        self.__callbacks.pop(handle, None)

    async def __fire_callback(self, callback, value, timestamp) -> None:
        # Runs in its own task; a failing callback must never break telemetry.
        try:
            when = (
                datetime.datetime.fromtimestamp(
                    timestamp / 1000, tz=self._vehicle.zone_info
                )
                if timestamp is not None
                else None
            )
            result = callback(self.__id, value, when)
            if inspect.isawaitable(result):
                await result
        except Exception as e:
            logger.error(
                "Callback for %s raised: %s: %s", self.__id, type(e).__name__, e
            )

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
            return self.__build_point_unlocked(self.__timestamp)

    async def get_snapshot_point(self, timestamp_ms: int) -> Point:
        '''
        Builds an InfluxDB point from the current value stamped with the given
        timestamp (ms since epoch, UTC) rather than the last telemetry event
        time.  Used by the midnight snapshot job so there is always a record
        at the start of the day/month for period-boundary queries.
        Arguments:
            timestamp_ms (int): Epoch milliseconds to tag the point with.
        '''
        async with self._async_lock:
            return self.__build_point_unlocked(timestamp_ms)

    def __build_point_unlocked(self, timestamp_ms) -> Point:
        # Caller must hold _async_lock.
        if self._value is None or timestamp_ms is None:
            return
        try:
            point = (
                Point("tesla_data")
                .tag("vin", self._vehicle.vin)
                .tag("category", self.__category)
                .tag("id", self.__id)
                .time(
                    datetime.datetime.fromtimestamp(
                        timestamp_ms / 1000, tz=timezone.utc
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
        except (ValueError, TypeError, AttributeError) as e:
            # Typical failures here: unsupported field type, None where not
            # expected, malformed timestamp.  Anything else should surface.
            logger.error("Failed to create InfluxDB point for %s: %s: %s", self.__id, type(e).__name__, e)
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
                # Coerce to int: formula evaluation stores self._value as float
                # even for bool fields, and struct.pack("!B", ...) rejects floats.
                value = struct.pack("!B", int(bool(self._value)))
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

    async def lock_value_until(self, *args, **kwargs):
        # Calculated properties overwrite _value after super().update() with the
        # calculation formula, which would defeat the lock.  No use case exists
        # for locking a derived value — fail loudly rather than silently.
        raise NotImplementedError(
            "lock_value_until is not supported on calculated properties"
        )

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
