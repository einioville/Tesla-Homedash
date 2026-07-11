'''
SpotPriceService — broadcasts the live Nord Pool spot price for the Charging view's
current-price tile (issue #12).

A thin always-on wrapper around the shared SpotPriceProvider: it fetches the current hour's
price and re-broadcasts it once per hour as a SPOT_PRICE_STREAM frame, and replays the last
frame to any newly connected client. Structurally identical to WeatherService (initial fetch
+ APScheduler job + last-frame cache for stream_everything), just with a one-hour cadence —
Nord Pool prices are hourly, so there is nothing finer to show.

It is independent of the myenergi charger (constructed and run unconditionally) so the price
tile works even with no Zappi. When spot pricing is disabled in config, run() returns without
scheduling anything and no frame is ever cached, so the tile simply stays empty.
'''
import asyncio
import logging
import struct
from datetime import datetime, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from ..server.server import Server
from ..utils import protocol
from ..utils.config_parser import Config
from .spot_price import SpotPriceProvider

logger = logging.getLogger("charging_service.spot_price_service")

_HOUR_MS = 3_600_000


def _build_spot_price_frame(hour_start_ms: int, spot_eur_per_kwh, all_in_eur_per_kwh) -> bytes:
    '''
    Builds a SPOT_PRICE_STREAM frame. status is 0 (no price) when all_in is None — the
    fixed field block is still written (NaN-filled) so the client parses a constant size —
    else 1. spot is the raw wholesale €/kWh, all_in the VAT+margin estimate the tiles use.
    Arguments:
        hour_start_ms (int): UTC start of the priced hour, epoch-ms.
        spot_eur_per_kwh (float | None): Raw wholesale price, or None.
        all_in_eur_per_kwh (float | None): All-in estimate, or None when unavailable.
    '''
    status = 0 if all_in_eur_per_kwh is None else 1
    spot = float("nan") if spot_eur_per_kwh is None else float(spot_eur_per_kwh)
    all_in = float("nan") if all_in_eur_per_kwh is None else float(all_in_eur_per_kwh)
    body = struct.pack("!B", status)
    body += struct.pack("!q", int(hour_start_ms))
    body += struct.pack("!d", spot)
    body += struct.pack("!d", all_in)
    return protocol.frame(protocol.SPOT_PRICE_STREAM, body)


class SpotPriceService:
    '''
    Fetches and broadcasts the live hourly spot price.
    Arguments:
        server (Server): TCP server used to broadcast + snapshot the price frame.
        config (Config): Shared configuration (timezone for the scheduler).
        provider (SpotPriceProvider): The shared fetch/cache/convert core (also used by the
            on-demand charging cost path).
    '''

    def __init__(self, server: Server, config: Config, provider: SpotPriceProvider):
        self.__server = server
        self.__provider = provider
        self.__zone_info = config.zone_info
        self.__scheduler = AsyncIOScheduler(timezone=self.__zone_info)
        # Most recent framed price packet, replayed verbatim to a newly connected client so
        # its price tile populates immediately without waiting for the next hourly tick.
        self.__last_frame: bytes | None = None

    async def run(self) -> None:
        '''
        Starts the service: pre-warms today+tomorrow's prices, broadcasts the current hour,
        then re-broadcasts every hour on the hour. A no-op when spot pricing is disabled.
        '''
        if not self.__provider.enabled:
            logger.info("Spot pricing disabled; live price service not started")
            return
        logger.info("Spot price service starting")
        # Pre-warm a today+tomorrow window so the hourly broadcasts (and the on-demand cost
        # path) mostly hit the cache; tomorrow's prices publish early afternoon.
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        hour_ms = (now_ms // _HOUR_MS) * _HOUR_MS
        await self.__provider.prices_for_range(hour_ms, hour_ms + 47 * _HOUR_MS)
        await self.__broadcast_current()
        self.__scheduler.start()
        self.__scheduler.add_job(
            func=self.__broadcast_current,
            trigger=CronTrigger(minute=0, timezone=self.__zone_info),
        )

    def get_run_task(self) -> asyncio.Task:
        '''Returns an asyncio Task that starts the spot price service.'''
        return asyncio.create_task(self.run())

    async def __broadcast_current(self) -> None:
        '''
        Fetches the current hour's all-in price (raw price paired from cache) and broadcasts
        it to all clients, caching the frame for stream_everything. On a fetch miss (API
        down / unpublished hour) a status=0 frame is broadcast so the tile can show "—"
        rather than a stale value.
        '''
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        hour_ms = (now_ms // _HOUR_MS) * _HOUR_MS
        all_in = await self.__provider.price_at(now_ms)
        spot = self.__provider.raw_price_at(now_ms)
        self.__last_frame = _build_spot_price_frame(hour_ms, spot, all_in)
        logger.info(
            "Broadcasting spot price: hour=%s all_in=%s €/kWh",
            datetime.fromtimestamp(hour_ms / 1000, tz=timezone.utc).isoformat(),
            "n/a" if all_in is None else f"{all_in:.4f}",
        )
        await self.__server.broadcast(self.__last_frame)

    async def stream_everything(self, client) -> None:
        '''
        Sends the most recent cached price frame to a newly connected client. No-op until
        the first broadcast (or when spot pricing is disabled).
        Arguments:
            client: StreamWriter for the new connection.
        '''
        if self.__last_frame is not None:
            await self.__server.send_to(client, self.__last_frame)
