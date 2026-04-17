from .telemetry import TelemetryHandler
from .vehicle import Vehicle
from ..influxdb_service.influxdb_handler import InfluxDBHandler
from dotenv import load_dotenv
import os
import asyncio
from .tcp_server import TeslaDataServer as TDS
from ..media_service.media_manager import MediaManager
from ..weather_service.weather_service import WeatherService


async def main():
    load_dotenv()

    influx_handler = InfluxDBHandler(
        url="http://localhost:8086",
        org="Tesla-Homedash",
    )
    tds = TDS()
    mm = MediaManager(server=tds)
    weather = WeatherService(server=tds)
    vehicle = Vehicle(
        os.getenv(key="VIN"),
        influx_db_handler=influx_handler,
        server=tds,
        access_token=os.getenv("API_KEY"),
    )
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

    await asyncio.gather(t1, t2, t3, t4)


def main_sync():
    asyncio.run(main())


if __name__ == "__main__":
    main_sync()
