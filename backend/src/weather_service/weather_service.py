from __future__ import annotations

import asyncio
import logging
from datetime import datetime

import aiohttp
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..server.server import Server
from ..utils import protocol
from ..utils.config_parser import Config
from .weather_view import WeatherViewBuilder, describe

logger = logging.getLogger("weather_service.weather_service")

# Hard per-request ceiling on every FMI request, enforced at the socket layer: a
# server that accepts the connection, sends a partial body and then goes silent —
# no FIN, no RST — would otherwise park the request in read() forever
# (weather_service/CLAUDE.md).
_FMI_TIMEOUT = aiohttp.ClientTimeout(total=30, sock_connect=10, sock_read=20)

# Scheduler resilience.  APScheduler's default max_instances=1 means a single
# run that never returns refuses every subsequent tick for the process lifetime
# ('skipped: maximum number of running instances reached (1)').  Allowing a
# second concurrent instance keeps the schedule alive even if one run wedges;
# the grace time stops a briefly busy event loop from dropping a tick as a
# misfire (the APScheduler default is 1 second).
_JOB_MAX_INSTANCES = 2
_MISFIRE_GRACE_SECONDS = 300

# The Weather view's document is several requests in parallel, each under _FMI_TIMEOUT;
# this bounds the whole build, covering anything _FMI_TIMEOUT does not (a pathological
# parse). Must exceed _FMI_TIMEOUT.total so a genuine network timeout reports as such.
_VIEW_DEADLINE_SECONDS = 90

# The view's parts (WeatherViewBuilder's log labels) as the status card names them.
_PART_NAMES = {"location": "paikka", "observation": "havainnot", "forecast": "ennuste",
               "radiation": "UV-arvio", "sun and moon": "aurinko ja kuu", "warnings": "varoitukset"}


class WeatherService:
    '''
    Keeps the Weather view's document (WEATHER_VIEW) current: builds it every 10
    minutes, broadcasts it and replays the latest one to each new client.
    '''

    def __init__(self, server: Server, config: Config):
        '''
        Initialises the service.  The scheduler is not started here; call
        get_run_task() to start the service as an asyncio Task.
        Arguments:
            server (Server): TLS server used to broadcast the weather document.
            config (Config): Shared in-memory configuration.
        '''
        self.__loop = asyncio.get_running_loop()
        self.__server = server
        # Retained so apply_config() can re-read the location after the Options view
        # writes the home; the scheduler timezone is NOT re-read (see apply_config).
        self.__config = config
        self.__zone_info = config.zone_info
        self.__scheduler = AsyncIOScheduler(timezone=self.__zone_info)
        # Where the weather is for: the home's coordinates, or the weatherPlace name.
        self.__where: dict[str, str] = config.weather_location
        self.__where_name: str = config.weather_location_name
        # The Weather view's document (WEATHER_VIEW), refreshed every 10 minutes; the
        # last frame is replayed to every newly connecting client.
        self.__view_builder = WeatherViewBuilder(self.__zone_info, _FMI_TIMEOUT)
        self.__last_view: bytes | None = None
        self.__view_updated_ms: int | None = None
        # Why the latest view cycle sent nothing, or None after one that did.
        self.__view_failure: str | None = None
        # The end of the last cycle that sent a document with every part fresh.
        self.__last_ok_ms: int | None = None

    def apply_config(self) -> None:
        '''
        Re-reads the runtime-editable settings this service owns and refreshes
        immediately, so the change is visible without waiting up to 10 minutes for
        the next cron tick.  Called by ConfigService after the Options view writes
        "home"; safe to call at any time.

        Only the location is re-read.  The scheduler's timezone is fixed at
        construction: a home in another zone takes effect on the next start.
        '''
        self.__where_name = self.__config.weather_location_name
        new_where = self.__config.weather_location
        if new_where == self.__where:
            return
        logger.info("Weather location changed: %s -> %s", describe(self.__where), describe(new_where))
        self.__where = new_where
        # Drop the cached frame: it describes the OLD place, and replaying it to a
        # client that connects before the refetch lands would show the wrong city.
        self.__last_view = None
        self.__loop.create_task(self.__update_view())

    async def zone_at(self, lat: float, lon: float) -> str | None:
        '''
        The IANA zone FMI gives a point, or None when it could not say.  ConfigService
        asks it for a home being written, before the home is saved.
        Arguments:
            lat (float): The point's latitude.
            lon (float): The point's longitude.
        '''
        return await self.__view_builder.zone_at(lat, lon)

    async def run(self) -> None:
        '''
        Starts the weather service: schedules the 10-minute refresh, then builds
        the first document.
        '''
        logger.info("Weather service starting: %s", describe(self.__where))
        # Schedule BEFORE the initial fetch: the periodic refresh must exist even
        # if the first fetch fails or runs long, otherwise a bad start leaves the
        # service with no job at all and weather never recovers.  Overlapping the
        # initial fetch with a cron tick is harmless — _JOB_MAX_INSTANCES allows
        # it and a broadcast is idempotent.
        self.__scheduler.start()
        # The observations are 10-minute ones, published a few minutes after the slot,
        # so the refresh runs every 10 minutes just after each lands.
        self.__scheduler.add_job(
            func=self.__update_view,
            trigger=CronTrigger(hour="*", minute="4,14,24,34,44,54", timezone=self.__zone_info),
            max_instances=_JOB_MAX_INSTANCES,
            misfire_grace_time=_MISFIRE_GRACE_SECONDS,
            coalesce=True,
        )
        logger.info("Performing initial weather fetch")
        await self.__update_view()

    def health(self) -> dict:
        '''
        Reports weather health for the status view as it stands now: "warn" until
        the first document is cached (at startup, or right after a location change),
        and again while the latest cycle failed or left parts at their last good
        values — the old document stays on screen meanwhile, and the Päivitetty row
        says how old it is. The next good cycle reports "ok" again.
        '''
        config = [["Sijainti", self.__where_name], ["Päivitysväli", "10 min"],
                  ["Lähde", "Ilmatieteen laitos"]]
        if self.__view_updated_ms is not None:
            config.append(["Päivitetty", {"time": self.__view_updated_ms}])
        stale = [_PART_NAMES.get(p, p) for p in self.__view_builder.failed_parts]
        if self.__last_view is None:
            state, detail = "warn", "Ei säätietoja"
        elif self.__view_failure:
            state, detail = "warn", self.__view_failure
        elif stale:
            state, detail = "warn", "Ei päivittynyt: " + ", ".join(stale)
        else:
            state, detail = "ok", "Säätiedot haettu"
        return {"state": state, "detail": detail, "config": config, "last_ok_ms": self.__last_ok_ms}

    def get_run_task(self) -> asyncio.Task:
        '''
        Returns an asyncio Task that starts the weather service.
        '''
        return asyncio.create_task(self.run())

    async def __update_view(self) -> None:
        '''
        Builds the Weather view's document and broadcasts it as a WEATHER_VIEW frame.
        A cycle that yields no document keeps the previous frame.
        '''
        where = self.__where
        try:
            document = await asyncio.wait_for(
                self.__view_builder.build(where), _VIEW_DEADLINE_SECONDS
            )
        except asyncio.TimeoutError:
            logger.warning(
                "Weather view fetch timed out for %s (deadline %ds)",
                describe(where), _VIEW_DEADLINE_SECONDS,
            )
            self.__view_failure = "Viimeisin päivitys aikakatkaistiin"
            return
        if document is None:
            self.__view_failure = "Viimeisin päivitys ei tuottanut ennustetta"
            return
        # The location changed while this was in flight: the cycle the change started
        # describes the new one, and this one must not land after it.
        if where != self.__where:
            return
        self.__last_view = protocol.json_frame(
            protocol.WEATHER_VIEW, protocol.CONFIG_STATUS_OK, document
        )
        self.__view_updated_ms = int(datetime.now().timestamp() * 1000)
        self.__view_failure = None
        if not self.__view_builder.failed_parts:
            self.__last_ok_ms = self.__view_updated_ms
        logger.info(
            "Broadcasting weather view: %d hours, observed %s",
            len(document["hourly"]), document["now"]["time"] or "-",
        )
        await self.__server.broadcast(self.__last_view)

    async def stream_everything(self, client) -> None:
        '''
        Sends the most recent cached document to a single newly connected client.
        No-op until the first __update_view() cycle has produced one.
        Arguments:
            client: StreamWriter for the new connection.
        '''
        if self.__last_view is not None:
            await self.__server.send_to(client, self.__last_view)
