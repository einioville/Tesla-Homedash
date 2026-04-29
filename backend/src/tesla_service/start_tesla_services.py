import asyncio
import logging
import os
import struct

from .telemetry import TelemetryHandler
from .vehicle import Vehicle
from ..influxdb_service.influxdb_handler import InfluxDBHandler
from ..media_service.media_manager import MediaManager
from ..server.server import Server
from ..utils import protocol
from ..utils.config_parser import ConfigUtils
from ..utils.logger_configurator import configure_logging
from ..weather_service.weather_service import WeatherService

logger = logging.getLogger("tesla_service.start_tesla_services")

# Env vars required before any service is constructed.  Missing any of these
# produces surprising mid-startup failures (spotipy NoneType errors, Influx
# auth 401s), so we fail fast with one clear message instead.
REQUIRED_ENV_VARS = (
    "CONFIG_PATH",
    "VIN",
    "API_KEY",
    "INFLUX_TOKEN",
    "SPOTIFY_CLIENT_ID",
    "SPOTIFY_CLIENT_SECRET",
)


def _register_handlers(
    server: Server, mm: MediaManager, vehicle: Vehicle
) -> None:
    '''
    Maps every frontend->backend message type to the service method that
    handles it.  The server itself is opaque to protocol semantics — these
    bindings are the single place where message codes meet service calls.
    '''
    async def _set_progress(payload: bytes) -> None:
        if len(payload) < 4:
            logger.warning("MEDIA_SET_PROGRESS: payload too short (%d bytes)", len(payload))
            return
        await mm.set_progress(struct.unpack("!I", payload[:4])[0])

    server.register_handler(protocol.MEDIA_SKIP,                 lambda _p: mm.skip_forward())
    server.register_handler(protocol.MEDIA_SKIP_BACKWARD,        lambda _p: mm.skip_backward())
    server.register_handler(protocol.MEDIA_PAUSE_PLAY,           lambda _p: mm.pause_play())
    server.register_handler(protocol.MEDIA_SET_PROGRESS,         _set_progress)
    server.register_handler(protocol.TESLA_SWITCH_CLIMATE_STATE, lambda _p: vehicle.switch_climate_state())
    server.register_handler(protocol.TESLA_MINUS_TARGET_TEMP,    lambda _p: vehicle.minus_temp())
    server.register_handler(protocol.TESLA_PLUS_TARGET_TEMP,     lambda _p: vehicle.plus_temp())


async def main():
    configure_logging()
    logger.info("Tesla Homedash services starting")

    missing = [key for key in REQUIRED_ENV_VARS if not ConfigUtils.get_env(key)]
    if missing:
        raise RuntimeError(
            f"Required environment variables not set: {', '.join(missing)}"
        )

    vin = ConfigUtils.get_env("VIN")
    api_key = ConfigUtils.get_env("API_KEY")

    influx_handler = InfluxDBHandler(
        url=os.getenv("INFLUX_URL", "http://localhost:8086"),
        org=os.getenv("INFLUX_ORG", "Tesla-Homedash"),
        timezone=ConfigUtils.get_config()["timeZone"],
    )
    logger.debug("InfluxDB handler initialized")

    server = Server()
    logger.debug("TCP server initialized")

    mm = MediaManager(server=server)
    logger.debug("Media manager initialized")

    weather = WeatherService(server=server)
    logger.debug("Weather service initialized")

    vehicle = Vehicle(
        vin,
        influx_db_handler=influx_handler,
        server=server,
        access_token=api_key,
    )
    logger.debug("Vehicle initialized")

    # Wire incoming-message dispatch and on-connect snapshot before start().
    _register_handlers(server, mm, vehicle)
    for service in (vehicle, mm, weather):
        server.register_service(service)

    await vehicle.init_async_dependent()

    telemetry = TelemetryHandler(
        access_token=api_key, server="eu.teslemetry.com", vehicle=vehicle
    )

    t1 = asyncio.create_task(telemetry.start())
    t2 = asyncio.create_task(server.start())
    t3 = mm.get_run_task()
    t4 = weather.get_run_task()

    logger.info("All services started, gathering tasks")
    await asyncio.gather(t1, t2, t3, t4)


def main_sync():
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
