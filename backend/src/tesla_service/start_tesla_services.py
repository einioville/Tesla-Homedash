from .telemetry import TelemetryHandler
from .vehicle import Vehicle
from ..influxdb_service.influxdb_handler import InfluxDBHandler
from dotenv import load_dotenv
import os
import asyncio
import logging
from .tcp_server import TeslaDataServer as TDS
from ..media_service.media_manager import MediaManager
from ..weather_service.weather_service import WeatherService
from ..utils.logger_configurator import configure_logging

logger = logging.getLogger("tesla_service.start_tesla_services")


async def main():
    configure_logging()
    logger.info("Tesla Homedash services starting")

    load_dotenv()

    influx_handler = InfluxDBHandler(
        url="http://localhost:8086",
        org="Tesla-Homedash",
    )
    logger.debug("InfluxDB handler initialized")
    tds = TDS()
    logger.debug("TCP data server initialized")
    mm = MediaManager(server=tds)
    logger.debug("Media manager initialized")
    weather = WeatherService(server=tds)
    logger.debug("Weather service initialized")
    vehicle = Vehicle(
        os.getenv(key="VIN"),
        influx_db_handler=influx_handler,
        server=tds,
        access_token=os.getenv("API_KEY"),
    )
    logger.debug("Vehicle initialized")
    tds.set_vehicle(vehicle=vehicle)
    tds.set_media_manager(mm)
    await vehicle.init_async_dependent()
    telemetry = TelemetryHandler(
        access_token=os.getenv("API_KEY"), server="eu.teslemetry.com", vehicle=vehicle
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
