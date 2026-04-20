import asyncio
import logging
from aiohttp import ClientSession
from teslemetry_stream import TeslemetryStream
from .vehicle import Vehicle

logger = logging.getLogger("tesla_service.telemetry")


class TelemetryHandler:
    '''
    Manages the Teslemetry SSE stream connection and routes events to the vehicle handler.

    Reconnection on network loss is handled entirely by the TeslemetryStream library using
    exponential backoff (up to 600 s between retries). This class only manages the
    ClientSession lifetime and shutdown signalling via close().
    Arguments:
        access_token (str): Teslemetry API access token
        server (str): Teslemetry server hostname (e.g. eu.teslemetry.com)
        vehicle (Vehicle): Vehicle instance whose on_telemetry_event callback receives events
    '''

    def __init__(self, access_token: str, server: str, vehicle: Vehicle) -> None:
        self.__access_token = access_token
        self.__vehicle = vehicle
        self.__server = server
        self.__stream: TeslemetryStream | None = None
        self.__close_event = asyncio.Event()

    async def start(self) -> None:
        '''
        Start the telemetry stream listener. Blocks until close() is called.

        The TeslemetryStream library spawns an internal asyncio task (via async_add_listener)
        that iterates the SSE stream and reconnects automatically on any network error — no
        outer retry loop is needed here. The ClientSession stays alive for the full duration
        so the library can reuse it when reconnecting.
        '''
        async with ClientSession() as session:
            self.__stream = TeslemetryStream(
                access_token=self.__access_token,
                vin=await self.__vehicle.get_vin(),
                server=self.__server,
                session=session,
                parse_timestamp=True,
            )

            self.__stream.async_add_connection_listener(self.__on_connection_change)

            # async_add_listener starts the internal listen() task which calls connect()
            # on first iteration and reconnects automatically after any disconnect.
            self.__stream.async_add_listener(self.__vehicle.on_telemetry_event)

            logger.info("Teslemetry stream listener started")
            await self.__close_event.wait()

    def __on_connection_change(self, connected: bool) -> None:
        '''Logs connection state transitions reported by the TeslemetryStream library.'''
        if connected:
            logger.info("Teslemetry stream connected")
        else:
            logger.warning("Teslemetry stream disconnected — library will reconnect automatically")

    def close(self) -> None:
        '''
        Stop the telemetry stream and unblock start(). Safe to call before start() is invoked.

        disconnect() sets active=False on the stream, which causes the library's internal
        listen() task to exit on its next iteration, and closes the active HTTP response.
        '''
        logger.info("Telemetry stream close requested")
        if self.__stream is not None:
            # disconnect() = active=False + close(), which stops the listen() task cleanly
            self.__stream.disconnect()
        self.__close_event.set()
