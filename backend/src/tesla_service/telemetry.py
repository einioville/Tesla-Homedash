import asyncio
from aiohttp import ClientSession
from teslemetry_stream import TeslemetryStream
from .vehicle import Vehicle

class TelemetryHandler:
    def __init__(self, access_token: str, server: str, vehicle: Vehicle) -> None:
        self.__access_token = access_token
        self.__vehicle = vehicle
        self.__server = server
        self.__close_stream = None
        self.__stream = None
        self.__close_event = asyncio.Event()

    async def start(self) -> None:
        while not self.__close_event.is_set():
            try:
                async with ClientSession() as session:
                    print("Stream started")
                    self.__stream = TeslemetryStream(
                        access_token=self.__access_token,
                        vin=await self.__vehicle.get_vin(),
                        server=self.__server,
                        session=session,
                        parse_timestamp=True,
                    )

                    await self.__stream.connect()

                    self.__close_stream = self.__stream.async_add_listener(
                        self.__vehicle.on_telemetry_event
                    )

                    await self.__close_event.wait()
            except Exception:
                await asyncio.sleep(5)

    def close(self) -> None:
        if self.__close_stream is not None:
            self.__stream.close()
            self.__close_stream()
        else:
            return
        self.__close_event.set()
