from .telemetry import TelemetryHandler
from .vehicle import Vehicle
from ..influxdb_service.influxdb_handler import InfluxDBHandler
import os
import asyncio
import logging
from .tcp_server import TeslaDataServer as TDS
from ..media_service.media_manager import MediaManager
from ..weather_service.weather_service import WeatherService
from ..utils.config_parser import ConfigUtils
from ..utils.logger_configurator import configure_logging

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
    )
    logger.debug("InfluxDB handler initialized")
    tds = TDS()
    logger.debug("TCP data server initialized")
    mm = MediaManager(server=tds)
    logger.debug("Media manager initialized")
    weather = WeatherService(server=tds)
    logger.debug("Weather service initialized")
    vehicle = Vehicle(
        vin,
        influx_db_handler=influx_handler,
        server=tds,
        access_token=api_key,
    )
    logger.debug("Vehicle initialized")
    tds.set_vehicle(vehicle=vehicle)
    tds.set_media_manager(mm)
    await vehicle.init_async_dependent()
    telemetry = TelemetryHandler(
        access_token=api_key, server="eu.teslemetry.com", vehicle=vehicle
    )

    t1 = asyncio.create_task(telemetry.start())
    t2 = asyncio.create_task(tds.start())
    t3 = mm.get_run_task()
    t4 = weather.get_run_task()

    logger.info("All services started, gathering tasks")
    await asyncio.gather(t1, t2, t3, t4)


def main_sync():
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
