'''
MyEnergiService — polls a myenergi Zappi charger, streams its live state to the
frontends, and logs the session-energy accumulator to InfluxDB.

Structurally this mirrors WeatherService: run() performs an initial poll then schedules
a periodic one on APScheduler and returns; the ongoing work lives in the job, whose
per-tick exceptions APScheduler logs and swallows (self-healing). Like weather, the
last broadcast frame is cached and replayed to any newly connected client via
stream_everything so its charger UI populates immediately.

Two cadences (config-driven): a slow idle poll and a faster one while a session is
active, switched by rescheduling the job — the same idea as SpotifyPlayer's 10s/2s.
All myenergi cloud access is through pymyenergi; all InfluxDB access is through the
injected InfluxDBHandler.
'''
import asyncio
import json
import logging
import struct
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from influxdb_client import Point, WritePrecision
from pymyenergi.client import MyenergiClient
from pymyenergi.connection import Connection
from pymyenergi.zappi import Zappi

from ..server.server import Server
from ..utils import protocol
from ..utils.config_parser import Config

logger = logging.getLogger("myenergi_service.myenergi_service")

# pymyenergi reports these enums as human-readable strings; map them to the single-byte
# wire codes in protocol.py. Anything unrecognised degrades to the UNKNOWN (0) code
# rather than dropping the field, so a firmware wording change never breaks the stream.
_STATUS_MAP = {
    "Paused": protocol.CHARGER_STATUS_PAUSED,
    "Charging": protocol.CHARGER_STATUS_CHARGING,
    "Completed": protocol.CHARGER_STATUS_COMPLETED,
}
_PLUG_MAP = {
    "EV Disconnected": protocol.CHARGER_PLUG_DISCONNECTED,
    "EV Connected": protocol.CHARGER_PLUG_CONNECTED,
    "Waiting for EV": protocol.CHARGER_PLUG_WAITING,
    "EV Ready to charge": protocol.CHARGER_PLUG_READY,
    "Charging": protocol.CHARGER_PLUG_CHARGING,
    "Fault": protocol.CHARGER_PLUG_FAULT,
}
_MODE_MAP = {
    "Fast": protocol.CHARGER_MODE_FAST,
    "Eco": protocol.CHARGER_MODE_ECO,
    "Eco+": protocol.CHARGER_MODE_ECO_PLUS,
    "Stopped": protocol.CHARGER_MODE_STOPPED,
}

# InfluxDB ids the charger logs under the "myenergi_data" measurement. ChargeAdded is
# the one the loss calc requires (charging_service reads it back by this exact id);
# ChargePower is logged for a charger history graph; GridPower is the household grid
# exchange logged alongside them.
_CHARGE_ADDED_ID = "ChargeAdded"
_CHARGE_POWER_ID = "ChargePower"
_GRID_POWER_ID = "GridPower"

# When a poll fails the myenergi cloud has almost always throttled us (429) or hiccuped
# (5xx), and every failure also flips pymyenergi's do_query_asn back on, so the *next*
# poll fires two requests (director ASN + status) instead of one — polling a failing
# endpoint at the normal cadence therefore deepens a throttle. On consecutive failures the
# interval is stretched by 2**failures (capped), snapping back to the normal idle/active
# cadence on the first poll that succeeds.
_BACKOFF_FACTOR_CAP = 4         # cap the multiplier at 2**4 = 16x the base interval
_BACKOFF_MAX_INTERVAL_S = 300   # ...and never back off slower than once every 5 minutes


def _describe_exception(e: Exception) -> str:
    '''
    Renders an exception for a log line, surfacing the HTTP status pymyenergi otherwise
    hides. A pymyenergi MyenergiException stringifies to '' — its constructor stores the
    status in .code / .message but never forwards code to the base Exception — so str(e)
    alone logs a blank reason (the "MyenergiException:" with nothing after it). This pulls
    .code and .message off the exception instead (e.g. "MyenergiException 429
    TOO_MANY_REQUESTS"), falling back to str(e) for ordinary exceptions.
    Arguments:
        e (Exception): The caught exception to describe.
    '''
    parts = [type(e).__name__]
    code = getattr(e, "code", None)
    if code is not None:
        parts.append(str(code))
    message = getattr(e, "message", "") or str(e)
    if message:
        parts.append(message)
    return " ".join(parts)


class MyEnergiService:
    def __init__(
        self,
        server: Server,
        config: Config,
        influx_handler,
        hub_serial: str,
        api_key: str,
    ):
        '''
        Initialises the service. The scheduler and cloud connection are not started
        here; call get_run_task() to start the service as an asyncio Task.
        Arguments:
            server (Server): TCP server used to broadcast charger data.
            config (Config): Shared in-memory configuration (provides myenergi_config).
            influx_handler (InfluxDBHandler): Data-access layer for charger writes.
            hub_serial (str): myenergi hub serial — the digest-auth username.
            api_key (str): myenergi API key — the digest-auth password.
        '''
        self.__server = server
        self.__influx = influx_handler
        self.__hub_serial = hub_serial
        self.__api_key = api_key
        # Retained so apply_config() can re-read the poll cadence at runtime.
        self.__config = config

        myenergi_config = config.myenergi_config
        # Blank zappiSerial -> auto-select the first Zappi discovered on the account.
        self.__zappi_serial = myenergi_config["zappiSerial"] or None
        self.__idle_interval = int(myenergi_config["pollIntervalIdleSeconds"])
        self.__active_interval = int(myenergi_config["pollIntervalActiveSeconds"])

        self.__scheduler = AsyncIOScheduler(timezone=config.zone_info)
        self.__connection: Connection | None = None
        self.__zappi: Zappi | None = None
        self.__job = None
        self.__current_interval: int | None = None
        # Cadence inputs for __apply_interval: whether the last successful poll saw the
        # charger charging (active vs idle base), and how many polls have failed in a row
        # (drives the backoff). Reset to 0 on the first poll that succeeds.
        self.__is_charging = False
        self.__consecutive_failures = 0

        # Most recent framed CHARGER_STREAM packet, replayed verbatim to a newly
        # connecting client (same idea as WeatherService.__last_forecast).
        self.__last_frame: bytes | None = None
        # (charge_added_kwh, when) from the previous poll, used to derive an
        # instantaneous charge power for the live display (pymyenergi exposes no direct
        # charge-power field). Display-only: the loss calc uses the logged accumulator.
        self.__last_energy: tuple[float, datetime] | None = None

    async def run(self) -> None:
        '''
        Starts the service: opens the pymyenergi connection, performs an initial poll,
        then schedules the periodic poll at the idle cadence and returns (the job owns
        the ongoing work). Digest auth needs no async handshake — director discovery
        happens on the first request inside the poll.
        '''
        logger.info(
            "MyEnergi service starting: zappi_serial=%s idle=%ds active=%ds",
            self.__zappi_serial or "<auto>", self.__idle_interval, self.__active_interval,
        )
        self.__connection = Connection(username=self.__hub_serial, password=self.__api_key)
        logger.info("Performing initial charger poll")
        await self.__poll()
        self.__scheduler.start()
        self.__job = self.__scheduler.add_job(
            func=self.__poll,
            trigger=IntervalTrigger(seconds=self.__idle_interval),
        )
        self.__current_interval = self.__idle_interval

    def health(self) -> dict:
        '''
        Reports charger-poll health.  Needs no new state: the consecutive-failure
        count already drives the backoff, and the interval in force is already
        tracked for the same reason.
        '''
        if self.__consecutive_failures >= 3:
            state = "error"
        elif self.__consecutive_failures or self.__last_frame is None:
            state = "warn"
        else:
            state = "ok"
        detail = f"{self.__current_interval} s" if self.__current_interval else ""
        if self.__consecutive_failures:
            detail += f" · {self.__consecutive_failures} epäonnistunutta kyselyä"
        elif self.__is_charging:
            detail += " · lataa"
        return {"state": state, "detail": detail}

    def get_run_task(self) -> asyncio.Task:
        '''Returns an asyncio Task that starts the MyEnergi service.'''
        return asyncio.create_task(self.run())

    async def stream_everything(self, client) -> None:
        '''
        Sends the most recent cached charger frame to a single newly connected client.
        No-op until the first successful poll has produced a frame.
        Arguments:
            client: StreamWriter for the new connection.
        '''
        if self.__last_frame is not None:
            await self.__server.send_to(client, self.__last_frame)

    async def __ensure_zappi(self) -> bool:
        '''
        Resolves the Zappi device to poll, once. With a configured serial the Zappi is
        addressed directly; otherwise the account is queried and the first Zappi is
        auto-selected. Returns True when a Zappi is available, False (logged) otherwise
        so the poll can retry on the next tick rather than raising.
        '''
        if self.__zappi is not None:
            return True
        try:
            if self.__zappi_serial:
                self.__zappi = Zappi(self.__connection, self.__zappi_serial)
            else:
                client = MyenergiClient(self.__connection)
                zappis = await client.get_devices("zappi")
                if not zappis:
                    logger.warning("No Zappi found on the myenergi account")
                    return False
                self.__zappi = zappis[0]
            logger.info("Using Zappi serial %s", getattr(self.__zappi, "serial_number", "?"))
            return True
        except Exception as e:
            # Network / auth / discovery failure: stay dormant and retry next tick.
            logger.warning("Failed to resolve Zappi: %s", _describe_exception(e))
            return False

    async def __poll(self) -> None:
        '''
        One poll cycle: refresh the Zappi, broadcast its live state, log the session
        energy while charging, and adjust the poll cadence. Every failure is caught and
        logged — a poll must never propagate (APScheduler would otherwise mark the job
        errored) and must never break the live broadcast.
        '''
        if not await self.__ensure_zappi():
            return
        try:
            await self.__zappi.refresh()
        except Exception as e:
            self.__consecutive_failures += 1
            logger.warning(
                "Zappi refresh failed (%d in a row): %s",
                self.__consecutive_failures, _describe_exception(e),
            )
            self.__apply_interval()
            return

        if self.__consecutive_failures:
            logger.info(
                "Zappi refresh recovered after %d failure(s)", self.__consecutive_failures
            )
            self.__consecutive_failures = 0

        status = self.__zappi.status
        plug = self.__zappi.plug_status
        mode = self.__zappi.charge_mode
        charge_added = self.__zappi.charge_added
        voltage = self.__zappi.supply_voltage
        grid_power = self.__zappi.power_grid
        generated_power = self.__zappi.power_generated
        frequency = self.__zappi.supply_frequency
        l1_phase = self.__zappi.l1_phase
        raw = self.__zappi.data
        power = self.__derive_power(charge_added)

        self.__last_frame = self.__build_frame(
            status, plug, mode, power, charge_added, voltage,
            grid_power, generated_power, frequency, l1_phase, raw,
        )
        await self.__server.broadcast(self.__last_frame)

        await self.__log_poll(status, charge_added, power, grid_power)
        self.__is_charging = _STATUS_MAP.get(status) == protocol.CHARGER_STATUS_CHARGING
        self.__apply_interval()

    def __derive_power(self, charge_added) -> float:
        '''
        Derives an instantaneous charge power (W) from the change in the session-energy
        accumulator since the previous poll (pymyenergi has no direct charge-power
        field). A reset to a new session (accumulator drops) or the first poll yields 0.
        Display-only — never used for the loss calc, which reads the logged accumulator.
        Arguments:
            charge_added: The Zappi's charge_added reading this poll (kWh) or None.
        '''
        now = datetime.now(timezone.utc)
        power = 0.0
        if charge_added is not None and self.__last_energy is not None:
            previous_kwh, previous_when = self.__last_energy
            elapsed_s = (now - previous_when).total_seconds()
            if elapsed_s > 0 and charge_added >= previous_kwh:
                # kWh over seconds -> W: (dkWh * 1000 Wh/kWh * 3600 s/h) / dt.
                power = (charge_added - previous_kwh) * 3_600_000.0 / elapsed_s
        if charge_added is not None:
            self.__last_energy = (float(charge_added), now)
        return power

    async def __log_poll(self, status, charge_added, power, grid_power) -> None:
        '''
        Writes charger telemetry to InfluxDB every poll. GridPower and ChargePower are
        logged unconditionally so the Charging view's past-hour graphs and the month-to-
        date home-consumption integral have gap-free data — ChargePower is derived from
        ΔChargeAdded, so it reads 0 when idle, which is the correct value for the graph.
        ChargeAdded (the session accumulator) stays gated to an active session (status
        Charging, or a non-zero accumulator to catch the tail): logging its idle zeros
        forever would bloat the measurement, and the loss calc only needs samples spanning
        a charge. A failed write degrades quietly (the handler swallows it) so it never
        breaks the poll loop.
        Arguments:
            status: The Zappi status string this poll.
            charge_added: Session energy accumulator (kWh) or None.
            power (float): Derived charge power (W).
            grid_power (float): Net grid power (W); + import / - export.
        '''
        when = datetime.now(timezone.utc)
        serial = str(getattr(self.__zappi, "serial_number", "") or self.__zappi_serial or "")
        # GridPower + ChargePower every poll (gap-free for the graphs / home integral).
        points = [
            self.__point(serial, _GRID_POWER_ID, float(grid_power or 0.0), when),
            self.__point(serial, _CHARGE_POWER_ID, float(power or 0.0), when),
        ]
        # ChargeAdded (accumulator) only while a session is active.
        if charge_added is not None:
            is_charging = _STATUS_MAP.get(status) == protocol.CHARGER_STATUS_CHARGING
            if is_charging or charge_added > 0:
                points.append(self.__point(serial, _CHARGE_ADDED_ID, float(charge_added), when))
        await self.__influx.write_charger_data(points)

    def __point(self, serial: str, prop_id: str, value: float, when: datetime) -> Point:
        '''
        Builds one myenergi_data InfluxDB point. Parallels the tesla_data schema (tag
        "id" + "value_float" field) so charging_service can read it back with the same
        query shape, but under its own measurement and with a "serial" tag.
        Arguments:
            serial (str): The Zappi serial (tag).
            prop_id (str): The charger property id (tag), e.g. "ChargeAdded".
            value (float): The reading (value_float field).
            when (datetime): Timezone-aware UTC timestamp for the point.
        '''
        return (
            Point("myenergi_data")
            .tag("serial", serial)
            .tag("id", prop_id)
            .field("value_float", value)
            .time(when, WritePrecision.MS)
        )

    def apply_config(self) -> None:
        '''
        Re-reads the poll cadence and reschedules the poll job through the single
        reschedule point (__apply_interval), so a cadence change from the Options
        view takes effect without a restart and without clobbering the backoff
        state that __apply_interval folds in.

        zappiSerial is deliberately NOT re-read: the Zappi is resolved once when
        the service connects, so changing it is a restart-tier setting.
        '''
        myenergi_config = self.__config.myenergi_config
        idle = int(myenergi_config["pollIntervalIdleSeconds"])
        active = int(myenergi_config["pollIntervalActiveSeconds"])
        if idle == self.__idle_interval and active == self.__active_interval:
            return
        logger.info(
            "MyEnergi poll cadence changed: idle %ss -> %ss, active %ss -> %ss",
            self.__idle_interval, idle, self.__active_interval, active,
        )
        self.__idle_interval = idle
        self.__active_interval = active
        self.__apply_interval()

    def __apply_interval(self) -> None:
        '''
        Sets the poll cadence to the desired interval by rescheduling the job, a no-op
        when it already matches. The base cadence is the active interval while charging or
        the idle interval otherwise; consecutive failures then stretch it by a capped
        exponential backoff (2**failures, bounded by _BACKOFF_MAX_INTERVAL_S) so a
        sustained cloud throttle (429) or outage is not hammered — and because each failure
        also forces pymyenergi to re-query the director next poll, backing off is what
        actually lets a throttle clear. The first successful poll resets the failure count,
        snapping the cadence straight back to idle/active.
        '''
        base = self.__active_interval if self.__is_charging else self.__idle_interval
        if self.__consecutive_failures:
            factor = 2 ** min(self.__consecutive_failures, _BACKOFF_FACTOR_CAP)
            desired = min(base * factor, _BACKOFF_MAX_INTERVAL_S)
        else:
            desired = base
        if desired != self.__current_interval and self.__job is not None:
            self.__job.reschedule(trigger=IntervalTrigger(seconds=desired))
            self.__current_interval = desired
            logger.debug("MyEnergi poll interval -> %ds", desired)

    def __build_frame(
        self, status, plug, mode, power, charge_added, voltage,
        grid_power, generated_power, frequency, l1_phase, raw,
    ) -> bytes:
        '''
        Serialises the Zappi's live state into a CHARGER_STREAM frame: a sequence of
        (sub_id + value) pairs (the same extensible shape as WEATHER_FORECAST). The
        fixed-width readings pack as their zero/UNKNOWN code when missing so the layout
        is stable; the final CHARGER_RAW_JSON sub-id carries the complete raw myenergi
        payload (length-prefixed) so every un-modelled field is still available frontend-
        side without a protocol change.
        Arguments:
            status / plug / mode: pymyenergi enum strings (mapped to byte codes).
            power (float): Derived charge power (W).
            charge_added: Session energy accumulator (kWh) or None.
            voltage: Supply voltage (V) or None.
            grid_power: Net grid power (W); + import / - export, or None.
            generated_power: Local generation power (W), e.g. solar, or None.
            frequency: Supply frequency (Hz) or None.
            l1_phase: Which phase L1 is wired to, or None.
            raw: The full Zappi.data dict for this poll (or None before first refresh).
        '''
        body = bytes()
        body += struct.pack("!B", protocol.CHARGER_STATUS)
        body += struct.pack("!B", _STATUS_MAP.get(status, protocol.CHARGER_STATUS_UNKNOWN))
        body += struct.pack("!B", protocol.CHARGER_PLUG_STATUS)
        body += struct.pack("!B", _PLUG_MAP.get(plug, protocol.CHARGER_PLUG_UNKNOWN))
        body += struct.pack("!B", protocol.CHARGER_MODE)
        body += struct.pack("!B", _MODE_MAP.get(mode, protocol.CHARGER_MODE_UNKNOWN))
        body += struct.pack("!B", protocol.CHARGER_CHARGE_POWER)
        body += struct.pack("!d", float(power))
        body += struct.pack("!B", protocol.CHARGER_SESSION_ENERGY)
        body += struct.pack("!d", float(charge_added or 0.0))
        body += struct.pack("!B", protocol.CHARGER_SUPPLY_VOLTAGE)
        body += struct.pack("!H", max(0, min(65535, int(round(voltage or 0)))))
        body += struct.pack("!B", protocol.CHARGER_GRID_POWER)
        body += struct.pack("!d", float(grid_power or 0.0))
        body += struct.pack("!B", protocol.CHARGER_GENERATED_POWER)
        body += struct.pack("!d", float(generated_power or 0.0))
        body += struct.pack("!B", protocol.CHARGER_SUPPLY_FREQUENCY)
        body += struct.pack("!d", float(frequency or 0.0))
        body += struct.pack("!B", protocol.CHARGER_L1_PHASE)
        body += struct.pack("!B", max(0, min(255, int(l1_phase or 0))))
        body += self.__pack_raw(raw)
        return protocol.frame(protocol.CHARGER_STREAM, body)

    def __pack_raw(self, raw) -> bytes:
        '''
        Serialises the complete raw pymyenergi Zappi payload (every field the myenergi
        API returned this poll, most of which the UI never uses) as a length-prefixed
        UTF-8 JSON blob under the CHARGER_RAW_JSON sub-id. The 4-byte length keeps it
        self-delimiting, so a client that doesn't care can skip it and new myenergi
        fields need no protocol change to reach the frontend. Non-serialisable content
        degrades to an empty object rather than breaking the frame.
        Arguments:
            raw: The Zappi.data dict for this poll (or None before the first refresh).
        '''
        try:
            raw_bytes = json.dumps(raw or {}, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError):
            raw_bytes = b"{}"
        return (
            struct.pack("!B", protocol.CHARGER_RAW_JSON)
            + struct.pack("!I", len(raw_bytes))
            + raw_bytes
        )
